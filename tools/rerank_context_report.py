"""只读取已有完整候选分数和清单，应用拍摄背景；不读取原图或模型。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from context_prior import POLICY, load_occurrences, rank_scores, resolve_context


def rerank(source, manifest_path, priors_path, output):
    raw = source.read_bytes()
    report = json.loads(raw.decode('utf-8'))
    photo_root = Path(report['photos_root']).resolve()
    if output.resolve().is_relative_to(photo_root):
        raise ValueError('重排报告禁止写入照片目录')
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw.decode('utf-8-sig'))
    occurrences = load_occurrences(priors_path)
    if [r['path'] for r in report['rows']] != [s['path'] for s in manifest['samples']]:
        raise ValueError('清单路径与已有报告不一致')
    if not 1 <= len(report['rows']) <= 50:
        raise ValueError('仅支持 1～50 张阶段 1 样片')
    result = copy.deepcopy(report)
    result['kind'] = 'stage1_context_rerank'
    result['context_rerank'] = {'source_report': str(source),
        'source_report_sha256': hashlib.sha256(raw).hexdigest(),
        'manifest_sha256': hashlib.sha256(manifest_raw).hexdigest(),
        'photo_access': '本次仅重排已有数字，未重新读取照片',
        'timings_note': '原 timings/memory/model_init_s 为来源模型运行测量；本次重排时间单列',
        'policy': POLICY, 'occurrences_sha256': occurrences['sha256']}
    result['context_prior'] = {'enabled': True, 'policy': POLICY,
        'data': {k:v for k,v in occurrences.items() if k!='species'}}
    result['capture_context_evidence'] = manifest.get('capture_context_evidence')
    start = time.perf_counter()
    root_name = Path(report['photos_root'].replace('\\', '/')).name
    for row, sample in zip(result['rows'], manifest['samples']):
        row_start = time.perf_counter()
        row['capture_context'] = resolve_context(manifest.get('capture_context', {}), sample.get('capture_context', {}),
            row.get('exif', {}), root_name, row['path'], occurrences['regions'])
        for view in row['views']:
            ranked = rank_scores(result['score_labels'], view['all_visual_scores'], row['capture_context'],
                                 occurrences, len(view['candidates']))
            if ranked['candidates'] != view['candidates']:
                raise ValueError('纯图像候选不一致，拒绝覆盖')
            view.update(ranked)
        row['context_rerank_s'] = time.perf_counter() - row_start
    result['context_rerank']['ranking_total_s'] = time.perf_counter() - start
    # 每次产生新结果文件，不覆盖来源记录。
    with output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    changed = [(r['path'],v['name']) for r in result['rows'] for v in r['views']
               if v['candidates'][0]['label'] != v['context_candidates'][0]['label']]
    print(json.dumps({'output':str(output), 'ranking_s':result['context_rerank']['ranking_total_s'],
                      'changed_top1_views':len(changed), 'changed_top1_whole':sum(v=='whole' for _,v in changed)},ensure_ascii=False))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'manifest', 'priors', 'output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    rerank(a.source,a.manifest,a.priors,a.output)
