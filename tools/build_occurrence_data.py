"""从已下载的 CC0 补充表生成阶段 1 地区/居留类型数据，无网络。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

REGIONS = {
    'IA': '大兴安岭亚区', 'IB': '长白山亚区', 'IC': '松辽平原亚区',
    'IIA': '黄淮平原亚区', 'IIB': '黄土高原亚区',
    'IIIA': '东部草原亚区', 'IIIB': '西部荒漠亚区', 'IIIC': '天山山地亚区',
    'IVA': '羌塘高原亚区', 'IVB': '青海藏南亚区',
    'VA': '西南山地亚区', 'VB': '喜马拉雅亚区',
    'VIA': '东部丘陵平原亚区', 'VIB': '西部山地高原亚区',
    'VIIA': '闽广沿海亚区', 'VIIB': '滇南山地亚区', 'VIIC': '海南岛亚区',
    'VIID': '台湾亚区', 'VIIE': '南海诸岛亚区',
}


def build(source, target):
    raw = source.read_bytes()
    rows = csv.DictReader(raw.decode('gb18030').splitlines(), delimiter='\t')
    species = {}
    for row in rows:
        if row['The data source'].strip() != 'Zheng, 2017':
            continue
        name = row['Scientific name'].strip()
        if name in species:
            raise ValueError('2017 分表中重复学名')
        found = {}
        for code in REGIONS:
            statuses = []
            for status in 'RSWPV':
                flag = row[code + status].strip()
                if flag not in ('0', '1'):
                    raise ValueError(f'未知分布标记：{name}/{code}/{status}/{flag}')
                if flag == '1':
                    statuses.append(status)
            if statuses:
                found[code] = statuses
        species[name] = found
    if len(species) != 1481:
        raise ValueError(f'预期 1481 条，实际 {len(species)}')
    data = {'schema': 'china-bird-occurrence-v1',
            'source': 'Zhang Q, Han J, Xia C, Møller AP (2022). A dataset of bird distributions in zoogeographical regions of China. Biodiversity Data Journal 10: e93606. https://doi.org/10.3897/BDJ.10.e93606',
            'license': 'Dataset CC0; article CC BY 4.0',
            'input_sha256': hashlib.sha256(raw).hexdigest(),
            'period': 'Zheng, 2017', 'taxonomy': 'IOC 12.1',
            'scope': '19 个动物地理亚区；非行政区，非城市级、非逐月记录。0 仅按无可用记录处理。',
            'region_names_note': '中文亚区名称为论文表 1 对应译名；没有行政边界或城市自动映射。',
            'regions': REGIONS,
            'status_names': {'R': '留鸟', 'S': '夏候鸟', 'W': '冬候鸟', 'P': '旅鸟', 'V': '迷鸟'},
            'species': species}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'species': len(species), 'regions': len(REGIONS), 'output': str(target)}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    build(a.source, a.output)
