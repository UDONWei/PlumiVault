"""Small, private validation batches. Metadata only; no image reads or scoring."""
import contextlib
import json
import re
import uuid
from pathlib import PurePosixPath

from .adjustments import recipe
from .common import encode, now, relative
from .db import Conflict

KEY = 'quality_validation_v1'
FOCUS = {'unreviewed', 'clear', 'defocus', 'motion_blur', 'mixed', 'uncertain'}
PREFERENCE = {'unreviewed', 'preferred', 'ordinary'}


def _load(c):
    row = c.execute('SELECT value FROM meta WHERE key=?', (KEY,)).fetchone()
    return json.loads(row[0]) if row else {'revision': 0, 'groups': []}


def _snapshot(lib, c, photo_id):
    photo = c.execute('SELECT * FROM photos WHERE id=?', (photo_id,)).fetchone()
    if not photo:
        raise ValueError('验证照片不存在')
    root = next((r for r in lib.cfg['roots'] if r['id'] == photo['root_id']), None)
    if not root or (root.get('allow_paths') is not None and photo['rel_path'] not in root['allow_paths']):
        raise ValueError('验证照片不在当前授权范围')
    relative(photo['rel_path'])
    if photo['source_status'] != 'available' or photo['inference_status'] != 'ready':
        raise ValueError('只能加入原目录中已处理完成的照片')
    if not re.fullmatch(r'[0-9a-f]{64}', photo['sha256'] or ''):
        raise ValueError('照片没有有效指纹，请先正常完成索引')
    adjustment = c.execute('SELECT * FROM adjustments WHERE photo_id=?', (photo_id,)).fetchone()
    if adjustment and adjustment['source_sha'] != photo['sha256']:
        raise Conflict('框选对应旧原片，请先核对编辑参数')
    settings = recipe(json.loads(adjustment['recipe']) if adjustment else None)
    summary = json.loads(photo['summary'])
    # An explicit cleared manual box means whole frame, not the old detection.
    box = settings['box'] if adjustment else summary.get('detection', {}).get('selected_box')
    box = recipe({'box': box})['box'] or [0, 0, 1, 1]
    return {'id': photo_id, 'root_id': photo['root_id'], 'root_path': root['path'], 'relative_path': photo['rel_path'],
            'sha256': photo['sha256'], 'size': photo['size'], 'mtime_ns': photo['mtime_ns'],
            'subject_box': box, 'adjustment_revision': adjustment['revision'] if adjustment else 0,
            'saved_recipe': settings, 'evaluation_tone': 'original_unadjusted',
            'capture_time': summary.get('exif', {}).get('EXIF DateTimeOriginal'),
            'focus': 'unreviewed', 'preference': 'unreviewed', 'note': ''}


def _status(lib, c, record):
    try:
        current = _snapshot(lib, c, record['id'])
        keys = ('root_id', 'root_path', 'relative_path', 'sha256', 'size', 'mtime_ns', 'subject_box',
                'adjustment_revision', 'saved_recipe')
        if any(current[k] != record[k] for k in keys):
            return '索引或框选已改变，请移出验证组后重新加入并复核'
    except (ValueError, KeyError, TypeError) as exc:
        return str(exc)
    return None


def _public(lib, c, batch):
    for group in batch['groups']:
        for sample in group['samples']:
            sample['stale_reason'] = _status(lib, c, sample)
    return batch


def read(lib):
    with contextlib.closing(lib.db.connect()) as c:
        c.execute('BEGIN')
        return _public(lib, c, _load(c))


def change(lib, value):
    if not isinstance(value, dict) or type(value.get('revision')) is not int:
        raise ValueError('验证批次版本无效')
    with lib.db.transaction() as c:
        batch = _load(c)
        if value['revision'] != batch['revision']:
            raise Conflict('验证标注已被其他页面更新，请重新加载验证批次')
        action = value.get('action')
        if action == 'add':
            ids = value.get('ids')
            if not isinstance(ids, list) or not 2 <= len(ids) <= 30 or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('每组请明确勾选 2～30 张照片')
            old = [s for g in batch['groups'] for s in g['samples']]
            if len(old) + len(ids) > 30:
                raise ValueError('本轮验证最多 30 张；请先导出并移除已完成的组')
            if set(ids) & {s['id'] for s in old}:
                raise ValueError('照片已在验证批次中，不能重复加入不同组')
            samples = [_snapshot(lib, c, i) for i in ids]
            sources = value.get('sources')
            if not isinstance(sources, list) or len(sources) != len(ids) or any(not isinstance(s, dict) or type(s.get('id')) is not int for s in sources):
                raise ValueError('缺少工作台照片版本，请刷新后重新勾选')
            expected = {s['id']: s for s in sources}
            if set(expected) != set(ids) or any(expected[s['id']].get('sha256') != s['sha256'] or expected[s['id']].get('adjustment_revision') != s['adjustment_revision'] for s in samples):
                raise Conflict('勾选后照片或框选已变化，请刷新工作台再建立验证组')
            if len({(s['root_id'], str(PurePosixPath(s['relative_path']).parent)) for s in samples}) != 1:
                raise ValueError('请选同一拍摄目录的一段连续照片作为一组')
            hashes = [s['sha256'] for s in old + samples]
            if len(set(hashes)) != len(hashes):
                raise ValueError('所选清单存在相同内容，不能重复纳入验证')
            batch['groups'].append({'id': uuid.uuid4().hex, 'name': '验证组 ' + str(batch['revision'] + 1),
                                    'split': 'unassigned', 'samples': samples})
        else:
            group = next((g for g in batch['groups'] if g['id'] == value.get('group_id')), None)
            if not group:
                raise ValueError('验证组不存在')
            if action == 'remove':
                batch['groups'].remove(group)
            elif action == 'group':
                name, split = value.get('name'), value.get('split')
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or split not in ('unassigned', 'development', 'holdout'):
                    raise ValueError('验证组名称或用途无效')
                group.update(name=name.strip(), split=split)
            elif action == 'label':
                ids, fields = value.get('ids'), value.get('fields')
                if not isinstance(ids, list) or not ids or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
                    raise ValueError('请选择验证组内照片')
                if not set(ids) <= {s['id'] for s in group['samples']}:
                    raise ValueError('所选照片不全属于当前验证组')
                if not isinstance(fields, dict) or not fields or set(fields) - {'focus', 'preference', 'note'}:
                    raise ValueError('验证字段无效')
                if 'focus' in fields and fields['focus'] not in FOCUS:
                    raise ValueError('清晰度标注无效')
                if 'preference' in fields and fields['preference'] not in PREFERENCE:
                    raise ValueError('偏好标注无效')
                if 'note' in fields and (not isinstance(fields['note'], str) or len(fields['note']) > 300):
                    raise ValueError('备注最多 300 字')
                for sample in group['samples']:
                    if sample['id'] in ids:
                        reason = _status(lib, c, sample)
                        if reason:
                            raise Conflict(reason)
                        sample.update(fields)
            else:
                raise ValueError('验证操作无效')
        batch['revision'] += 1
        batch['updated_at'] = now()
        c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY, encode(batch)))
        # Do not bump library generation, rewrite analyses or trigger processing.
        return _public(lib, c, batch)


def export(lib):
    with contextlib.closing(lib.db.connect()) as c:
        c.execute('BEGIN')
        batch = _public(lib, c, _load(c))
        samples = []
        if not batch['groups']:
            raise ValueError('请先建立验证组')
        for group in batch['groups']:
            for sample in group['samples']:
                if sample['stale_reason']:
                    raise Conflict('照片 ' + str(sample['id']) + '：' + sample['stale_reason'])
                root = next(r for r in lib.cfg['roots'] if r['id'] == sample['root_id'])
                samples.append({**sample, 'group': group['id'], 'group_name': group['name'], 'split': group['split'],
                                'path': root['path'].rstrip('/\\') + '/' + sample['relative_path']})
        return {'schema': 'plumivault-quality-validation-v1', 'library_id': lib.db.meta('library_id'),
                'revision': batch['revision'], 'exported_at': now(), 'samples': samples,
                'groups': [{k: v for k, v in g.items() if k != 'samples'} for g in batch['groups']],
                'unreviewed_count': sum(s['focus'] == 'unreviewed' or s['preference'] == 'unreviewed' for s in samples),
                'production_scoring_enabled': False, 'source_verification': 'index_snapshot_only_rehash_before_evaluation',
                'notes': ['仅文件清单与人工标注，不包含照片。请私下保存，不要上传公共仓库。',
                          '导出不读取原片；实验前必须核对当前文件指纹。未标注项不作为负例。',
                          '眼部评估使用原色图及保存的主体框；亮度等参数仅留作参照，不自动应用。',
                          '调试与独立验证按整组划分；连续性与跨组相似性仍需人工核对。']}
