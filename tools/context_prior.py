"""阶段 1 的可选拍摄背景辅助排序；不识图、不访问网络、不修改照片。"""
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re


POLICY = {
    'id': 'weak-context-v1',
    'region_bonus': 0.15,
    'season_bonus': 0.10,
    'months': {'R': list(range(1, 13)), 'S': [5, 6, 7, 8],
               'W': [11, 12, 1, 2], 'P': [3, 4, 9, 10]},
    'meaning': '实验性弱提示：有当地常规记录加 0.15，符合粗略月份再加 0.10；其余保持原分。',
    'limitation': '月份划分是可审查的工程假设，不是数据集提供的月度概率；未按物种、纬度、海拔校准。',
}
CONTEXT_KEYS = {'location', 'region_code', 'date', 'use_date'}


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('拍摄日期须为 YYYY-MM-DD')
    return date.fromisoformat(value).isoformat()


def validate_context(value, regions=None):
    if not isinstance(value, dict) or set(value) - CONTEXT_KEYS:
        raise ValueError('capture_context 只接受 location、region_code、date、use_date')
    if value.get('date') is not None:
        iso_date(value['date'])
    if 'use_date' in value and not isinstance(value['use_date'], bool):
        raise ValueError('use_date 须为布尔值')
    for key in ('location', 'region_code'):
        v = value.get(key)
        if v is not None and (not isinstance(v, str) or not v.strip() or len(v) > 200):
            raise ValueError(f'{key} 须为非空文字或 null')
    code = value.get('region_code')
    if code and regions is not None and code not in regions:
        raise ValueError(f'未知地理亚区代码：{code}')


def load_occurrences(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    if data.get('schema') != 'china-bird-occurrence-v1' or not data.get('source') or not data.get('license'):
        raise ValueError('分布数据缺少版本、来源或许可')
    if not data.get('regions') or not data.get('species'):
        raise ValueError('分布数据为空')
    for name, regions in data['species'].items():
        if not name or not isinstance(regions, dict):
            raise ValueError('分布数据格式错误')
        for region, statuses in regions.items():
            if region not in data['regions'] or not isinstance(statuses, list) or not statuses or set(statuses) - set('RSWPV'):
                raise ValueError('分布数据含无效地理亚区或居留类型')
    data['sha256'] = hashlib.sha256(raw).hexdigest()
    return data


def resolve_context(defaults, override, exif, root_name, relative_path, regions=None):
    """逐图 > 清单默认 > EXIF > 最近日期目录；文件 mtime 从不参与。"""
    validate_context(defaults, regions)
    validate_context(override, regions)
    merged = {**defaults, **override}
    warnings = []
    exif_date = None
    exif_raw = exif.get('EXIF DateTimeOriginal')
    if exif_raw:
        try:
            exif_date = datetime.strptime(exif_raw, '%Y:%m:%d %H:%M:%S').date().isoformat()
        except ValueError:
            warnings.append('EXIF 拍摄时间无效，未使用')
    folder_date = None
    folders = list(reversed(Path(relative_path.replace('\\', '/')).parts[:-1])) + [root_name]
    for folder in folders:
        m = re.match(r'^(\d{4})-?(\d{2})-?(\d{2})(?!\d)', folder)
        if not m:
            continue
        try:
            folder_date = iso_date('-'.join(m.groups()))
            break
        except ValueError:
            warnings.append(f'目录日期无效：{folder}')
    explicit = merged.get('date')
    if explicit:
        chosen = iso_date(explicit)
        source = 'sample_override' if override.get('date') else 'manifest_default'
    elif exif_date:
        chosen, source = exif_date, 'EXIF DateTimeOriginal'
    elif folder_date:
        chosen, source = folder_date, 'folder_name'
    else:
        chosen, source = None, 'missing'
    if len(set(x for x in (chosen, exif_date, folder_date) if x)) > 1:
        warnings.append('日期来源冲突：采用所示来源，其他值保留供复核')
    code = merged.get('region_code')
    return {'location': merged.get('location'), 'region_code': code,
            'region_name': regions.get(code) if regions and code else None,
            'location_source': 'sample_override' if 'location' in override else ('manifest_default' if defaults.get('location') else 'missing'),
            'region_source': 'sample_override' if 'region_code' in override else ('manifest_default' if defaults.get('region_code') else 'missing'),
            'date': chosen, 'date_source': source, 'exif_datetime': exif_raw,
            'folder_date': folder_date, 'use_date': merged.get('use_date', True), 'warnings': warnings}


def prior_factor(label, context, occurrences):
    code = context.get('region_code')
    neutral = {'factor': 1.0, 'statuses': [], 'reasons': []}
    if occurrences is None or not code:
        return {**neutral, 'reasons': ['地区未设置，保持视觉分数']}
    if code not in occurrences['regions']:
        raise ValueError('未知地理亚区；禁止静默忽略拼写错误')
    if label.get('kind') != 'bird':
        return {**neutral, 'reasons': ['通用对照，不应用鸟类分布提示']}
    statuses = occurrences['species'].get(label.get('scientific_name'), {}).get(code, [])
    if not set(statuses) & set('RSWP'):
        return {**neutral, 'statuses': statuses,
                'reasons': ['只有迷鸟记录，保持原分' if statuses else '没有可用常规记录；不等于当地不存在，保持原分']}
    factor = 1.0 + POLICY['region_bonus']
    reasons = ['有当地留鸟/候鸟/旅鸟记录 +0.15']
    if context.get('date') and context.get('use_date', True):
        month = date.fromisoformat(iso_date(context['date'])).month
        matches = [s for s in statuses if month in POLICY['months'].get(s, [])]
        if matches:
            factor += POLICY['season_bonus']
            reasons.append('符合实验月份规则 ' + '/'.join(matches) + ' +0.10')
        else:
            reasons.append('月份未匹配粗略规则，不额外加分、不排除')
    else:
        reasons.append('日期缺失或季节提示关闭，只用地区')
    return {'factor': factor, 'statuses': statuses, 'reasons': reasons}


def rank_scores(labels, scores, context, occurrences=None, k=5):
    """输入必须为完整候选向量。调整值只用于排序，不归一化、不冒充概率。"""
    if len(labels) != len(scores) or not scores or not 1 <= k <= len(scores):
        raise ValueError('分数须覆盖完整候选表且 k 有效')
    if any(not isinstance(s, (int, float)) or not math.isfinite(s) or s < 0 for s in scores):
        raise ValueError('分数须为非负有限数值')
    if not math.isclose(sum(scores), 1.0, rel_tol=0, abs_tol=1e-4):
        raise ValueError('必须输入全国完整 softmax 分数，不能只重排 Top-K')
    base_order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    raw_ranks = {idx: n+1 for n, idx in enumerate(base_order)}
    priors = [prior_factor(label, context, occurrences) for label in labels]
    adjusted = sorted(range(len(scores)), key=lambda i: (-scores[i] * priors[i]['factor'], i))
    return {
        'candidates': [{'label': labels[i], 'score': scores[i]} for i in base_order[:k]],
        'context_candidates': [{'label': labels[i], 'visual_score': scores[i],
                                'ranking_score': scores[i] * priors[i]['factor'],
                                'visual_rank': raw_ranks[i], **priors[i]} for i in adjusted[:k]],
        'context_applied': occurrences is not None and bool(context.get('region_code')),
        'candidate_count': len(scores),
    }
