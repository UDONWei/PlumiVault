"""Local pinyin search keys; no network or taxonomy changes."""
from functools import lru_cache
from pathlib import Path
from .common import PROJECT,read_json


@lru_cache(maxsize=16384)
def tokens(value):
    from pypinyin import lazy_pinyin,Style
    if not value:return ()
    return (''.join(lazy_pinyin(value,style=Style.NORMAL)),''.join(lazy_pinyin(value,style=Style.FIRST_LETTER)))


@lru_cache(maxsize=1)
def places():
    path=PROJECT/'docs/locations-reference.json'
    if not path.exists():return []
    return [{**r,'search':list(dict.fromkeys([r['name'],*r['parts'],*tokens(r['name']),*(key for part in r['parts'] for key in tokens(part))]))} for r in read_json(path)['places']]


def locations(lib):
    regions=read_json(lib.cfg['priors_path'])['regions']
    suggestions=[{'id':'region:'+code,'name':name,'region_code':code,'kind':'region','search':[code,name,*tokens(name)]} for code,name in regions.items()]
    for row in lib.db.query("SELECT id,context FROM roots UNION ALL SELECT root_id || ':' || scope AS id,context FROM folder_contexts"):
        import json
        c=json.loads(row['context']);name=c.get('location')
        if name:suggestions.append({'id':'known:'+row['id'],'name':name,'region_code':c.get('region_code'),'kind':'known','search':[name,*tokens(name)]})
    return {'places':places(),'regions':suggestions,'reference_date':'2023-06-30','notice':'地名仅作离线输入参考；自由填写保留，未知地点不自动推断鸟类分布亚区。'}
