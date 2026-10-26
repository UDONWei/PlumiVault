"""生成可离线调整地区/日期的阶段 1 复核页；只复用已有受限缩略图。"""
import argparse
import html
import hashlib
import json
from pathlib import Path
import shutil

from context_prior import POLICY, load_occurrences


def build(report_path, baseline_path, manifest_path, priors_path, output, manual_review=None):
    from PIL import Image
    report = json.loads(report_path.read_text(encoding='utf-8'))
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    data = load_occurrences(priors_path)
    old_rows = {r['path']: r for r in baseline['rows']}
    if len(report['rows']) != len(manifest['samples']) or [r['path'] for r in report['rows']] != [s['path'] for s in manifest['samples']]:
        raise ValueError('清单与报告不对应')
    photo_root = Path(report['photos_root']).resolve()
    if output.resolve().is_relative_to(photo_root) or photo_root.is_relative_to(output.resolve()):
        raise ValueError('复核页必须放在原图目录之外')
    output.mkdir(parents=True, exist_ok=True)
    from stage1_probe import install_guard
    install_guard(output.resolve())
    thumbs = output / 'review-thumbnails'
    thumbs.mkdir(exist_ok=True)
    cards = []
    subject_mode=bool(report.get('settings',{}).get('detector_config'))
    for ri, row in enumerate(report['rows']):
        old = old_rows[row['path']]
        if not row.get('source_unchanged') or row['status'] == 'error' or row['before'] != old['before'] or row['decoded_size'] != old['decoded_size']:
            raise ValueError('原图指纹/尺寸/状态不符，不能复用缩略图')
        old_views = {v['name']: v for v in old['views']}
        figures = []
        detection_note=html.escape(row.get('detection',{}).get('message',''))
        for vi, view in enumerate(row['views']):
            previous = old_views[view['name']]
            if previous.get('pixel_box') != view.get('pixel_box') or len(view['all_visual_scores']) != len(report['score_labels']):
                raise ValueError('视图或完整分数缺失')
            filename = previous['thumbnail']['name']
            source = (baseline_path.parent / filename).resolve()
            if source.parent != baseline_path.parent.resolve() or source.suffix != '.jpg':
                raise ValueError('缩略图来源越界')
            with Image.open(source) as im:
                if max(im.size) > 512:
                    raise ValueError('禁止复制超限图像')
            destination = thumbs / source.name
            if destination.is_symlink():
                raise ValueError('输出缩略图不能是链接')
            if not destination.exists() or destination.read_bytes() != source.read_bytes():
                shutil.copyfile(source, destination)
            figures.append(f'''<article><h3>{html.escape('自动主体' if view['name']=='subject' else ('整图（未定位到主体）' if subject_mode else view['name']))}</h3><img loading="lazy" src="review-thumbnails/{html.escape(source.name, quote=True)}" alt="供用户复核的受限缩略图"><p id="change-{ri}-{vi}" class="changed"></p><div class="compare"><div><h4>纯图像候选</h4><ol id="raw-{ri}-{vi}"></ol></div><div><h4>地区 / 时间辅助候选</h4><ol id="adjusted-{ri}-{vi}"></ol></div></div></article>''')
        cards.append(f'''<section><h2>{ri+1:02d} · {html.escape(row['path'])}</h2><p id="context-{ri}"></p><p class="changed">{detection_note}</p><details><summary>查看原有真值记录</summary><p>{html.escape(str(row.get('truth') or '未知'))}；本次选择单独记录。</p></details><div class="manual-panel"><h3>本张照片 · 人工确认</h3><p>勾选下方任一候选即可；同种只记一次。只有确认照片里确实有多种鸟时才多选。</p><div id="selected-{ri}" role="status"></div><button type="button" id="none_match-{ri}">候选都不对</button><button type="button" id="uncertain-{ri}">暂不确定</button><button type="button" id="unreviewed-{ri}">清除此图选择</button><details><summary>候选中没有？搜索完整名录</summary><label for="species-search-{ri}">中文名、学名或英文名</label><input id="species-search-{ri}" type="text" maxlength="100" placeholder="输入鸟名"><label for="species-results-{ri}">匹配鸟种</label><select id="species-results-{ri}"><option value="">先输入关键词</option></select><button id="add-species-{ri}" type="button">确认此鸟种</button></details></div><div class="views">{''.join(figures)}</div></section>''')
    payload = {'labels': report['score_labels'], 'rows': report['rows'], 'manifest': manifest,
               'occurrences': data, 'policy': POLICY}
    identities=sorted((r['path'],r['before']['sha256']) for r in report['rows'])
    payload['review_batch_id']=hashlib.sha256(json.dumps(identities,ensure_ascii=False).encode('utf-8')).hexdigest()
    if manual_review:
        payload['initial_manual_review']=json.loads(manual_review.read_text(encoding='utf-8-sig'))
        if payload['initial_manual_review'].get('batch_id')!=payload['review_batch_id']:
            raise ValueError('复核记录不属于当前批次')
    # 小于号转义，防止路径/清单里的文本结束 JSON script 元素。
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; img-src 'self'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'"><title>鸟类复核 · 地区与拍摄时间</title><style>
body{font:16px/1.6 system-ui,sans-serif;margin:24px auto;padding:0 20px;max-width:1600px;color:#203035;background:#f4f6f5}h1{font-size:28px}h2{font-size:22px}h3{margin:0 0 12px}h4{margin:10px 0}section,.controls{background:white;border-radius:12px;padding:24px;margin:24px 0}.notice{border-left:4px solid #a06b16;background:#fff4de;padding:14px}.fields{display:flex;flex-wrap:wrap;gap:18px;align-items:end}label{display:block}select,input[type=text],input[type=date]{display:block;min-height:40px;padding:4px 8px;font:inherit;border:1px solid #b2c1bd;border-radius:5px;box-sizing:border-box}button{padding:9px 16px;margin:12px 8px 0 0;font:inherit;cursor:pointer;border:1px solid #285d50;border-radius:5px;color:#285d50;background:white}button.primary{background:#285d50;color:white}.views{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,590px),1fr));gap:20px}article{padding:16px;border:1px solid #dae1df;border-radius:8px}img{width:100%;height:260px;object-fit:contain;background:#eff2f0}.compare{display:grid;grid-template-columns:1fr 1fr;gap:20px}ol{padding-left:24px;font-size:14px}li{margin-bottom:12px}small{display:block;color:#5a6964;font-size:12px}.changed{color:#825618}#message{font-weight:600}details{margin-top:16px}p{margin:8px 0}@media(max-width:650px){.compare{grid-template-columns:1fr}.controls,section{padding:14px}}
 .manual-panel{background:#eef6f2;padding:16px;border-radius:8px;margin:16px 0}.species-choice{display:flex;gap:9px;align-items:start;padding:6px;cursor:pointer;border-radius:5px}.species-choice input{width:19px;height:19px;flex-shrink:0;accent-color:#285d50}.species-choice:has(input:checked){background:#dbeee4;font-weight:600}.selected-species,button[aria-pressed=true]{background:#285d50;color:white}button:disabled{opacity:.5;cursor:default}input[type=file]{margin:10px 0} .manual-panel select{max-width:100%}</style><script src="context_rank.js" defer></script><script src="manual_review.js" defer></script><script src="manual_review_ui.js" defer></script><script src="context_review.js" defer></script></head><body><h1>鸟类复核 · 地区与拍摄时间</h1><p>阶段 1 限量验证 · 20 张 ARW · 本地 BioCLIP · 全国 1481 鸟种 + 8 个通用对照</p><p class="notice">地区和日期只提供弱辅助排序。所有数值都不是正确概率，Top-K 也不表示同图多种鸟。whole 为整图，其余为固定窗口，不是鸟体检测。请由你判断；开发助手没有观看这些照片。</p>
<div class="controls"><h2>点选鸟种 · 人工复核</h2><p>点击鸟种前的方框即可确认；再次点击可撤销。选择会显示在每张照片顶部。更改地区或候选排序不会覆盖人工选择。</p><button id="export-review" class="primary" type="button">导出复核结果</button><label>导入先前保存的复核 JSON<input id="import-review" type="file" accept=".json,application/json"></label><button id="apply-import" type="button" disabled>应用导入（替换本批复核）</button><p id="review-message" role="status"></p><p>页面会尝试在本浏览器暂存；请导出 JSON 备份。换浏览器或清理浏览器数据后，可导入继续。文件只含文字记录，不包含照片。</p></div><div class="controls"><h2>拍摄背景</h2><div class="fields"><label>拍摄地点（备注）<input id="locality" type="text" maxlength="200" placeholder="例如省、市、拍摄点"></label><label>地理亚区<select id="region"><option value="">未设置 · 保持全国视觉候选</option></select></label><label>覆盖本批拍摄日期<input id="capture-date" type="date"><small>留空使用每张照片的 EXIF / 日期目录</small></label></div><p><label><input id="enabled" type="checkbox" checked>启用地区辅助</label><label><input id="use-date" type="checkbox" checked>加入实验性季节提示</label></p><button class="primary" id="apply" type="button">应用并比较</button><button id="reset" type="button">恢复全国候选</button><button id="export" type="button">导出拍摄背景清单</button><p id="message" role="status"></p><noscript>请启用本地 JavaScript 以查看候选对照；本页不会联网。</noscript><details><summary>查看依据与限制</summary><p>亚区是动物地理区，不是行政省市。地点备注不会自动决定亚区；没有精确边界映射，位置不明确时请保持未设置。月份只使用拍摄日期，不使用文件修改时间或拍摄时刻。</p><p>在全国完整候选中：当地有留鸟/夏候鸟/冬候鸟/旅鸟记录时原分 ×1.15；日期符合粗略规则时再加 0.10，最高 ×1.25。留鸟全年，夏候鸟 5–8 月、冬候鸟 11–2 月、旅鸟 3–4 / 9–10 月。以上月份是待验证的工程假设，不能代表所有物种和纬度。其余候选保持原分，不删除罕见鸟或区域外鸟种；迷鸟记录不加分。资料未知和非物种对照保持原分。</p><p>分布源：<a href="https://doi.org/10.3897/BDJ.10.e93606" target="_blank" rel="noreferrer">Zhang 等（2022）</a>，采用 Zheng 2017 分表、IOC 12.1，19 亚区、1481 种；数据 CC0。资料有年代和覆盖限制，不是城市级出现概率。</p><p>拍摄背景调整刷新后会还原。人工复核独立暂存于浏览器，并可导出与导入 JSON；原模型结果和已有 truth 保持。页面不读取原图、没有后台扫描服务、不修改 EXIF；仅显示已有长边不超过 512 的缩略图。</p></details></div>'''
    if subject_mode:
        page=page.replace('whole 为整图，其余为固定窗口，不是鸟体检测。','每图仅显示一个自动主体；未检测到可靠鸟体时保留整图。检测框与物种均需人工复核。')
        page=page.replace('仅显示已有长边不超过 512 的缩略图','仅显示长边不超过 512 的主体或整图缩略图')
    page += ''.join(cards) + '<script id="review-data" type="application/json">' + encoded + '</script></body></html>'
    target = output / '逐图人工复核.html'
    previous_page = output / '逐图人工复核-首轮.html'
    if target.exists() and not previous_page.exists():
        shutil.copyfile(target, previous_page)
    target.write_text(page, encoding='utf-8')
    for name in ('context_rank.js', 'manual_review.js', 'manual_review_ui.js', 'context_review.js'):
        shutil.copyfile(Path(__file__).parent / name, output / name)
    print(json.dumps({'page': str(target), 'photos': len(report['rows']),
                      'views': sum(len(r['views']) for r in report['rows']), 'bytes': target.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for field in ('report', 'baseline', 'manifest', 'priors', 'output'):
        p.add_argument('--'+field, type=Path, required=True)
    p.add_argument('--manual-review',type=Path)
    a = p.parse_args()
    build(a.report, a.baseline, a.manifest, a.priors, a.output, a.manual_review)
