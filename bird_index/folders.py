"""Browse directory names only. No implicit recursive scan."""
import os
from pathlib import Path
from .common import relative


def directory(root, rel=''):
    base=Path(root).resolve(strict=True)
    if rel:
        relative(rel)
    path=base/rel
    current=base
    for part in Path(rel).parts:
        current=current/part;info=current.lstat()
        if current.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('不能扫描链接或重解析目录')
    resolved=path.resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_dir():
        raise ValueError('目录越界或不存在')
    return resolved


def validate(root, scopes):
    if not isinstance(scopes,list) or not 1<=len(scopes)<=30 or any(not isinstance(s,str) or not s for s in scopes):
        raise ValueError('请先勾选 1～30 个目录；不允许默认扫描全部目录')
    if len(set(scopes))!=len(scopes):raise ValueError('勾选目录重复')
    for scope in scopes:
        directory(root,'' if scope=='.' else scope)
        if scope!='.' and any(scope.startswith(other+'/') for other in scopes if other!='.' and other!=scope):
            raise ValueError('上级目录已包含勾选的下级目录，请取消重复选择')
    return scopes


def includes(relative_path, scopes):
    return any(('/' not in relative_path if scope=='.' else relative_path.startswith(scope+'/')) for scope in scopes)


def listing(lib, root_id, parent='', offset=0, sort='date_desc'):
    root=lib.root(root_id);base=directory(root['path'],parent);rows=[]
    with os.scandir(base) as entries:
        for e in entries:
            info=e.stat(follow_symlinks=False)
            if e.is_symlink() or getattr(info,'st_file_attributes',0)&0x400 or not e.is_dir(follow_symlinks=False):continue
            rel=(parent+'/' if parent else '')+e.name
            if root['allow_paths'] is not None and not any(p.startswith(rel+'/') for p in root['allow_paths']):continue
            rows.append({'name':e.name,'path':rel})
    indexed={r['path']:r for r in catalog(lib) if r['root_id']==root_id}
    for row in rows:
        known=indexed.get(row['path'],{});row.update(indexed=known.get('count',0),ready=known.get('ready',0))
    sort_rows(rows,sort);offset=max(0,int(offset));limit=200
    return {'root_id':root_id,'parent':parent,'items':rows[offset:offset+limit],'total':len(rows),
            'next_offset':offset+limit if offset+limit<len(rows) else None,
            'root_files_option':parent==''}


def catalog(lib):
    """Indexed folders, including ancestors. Metadata only, no source stat calls."""
    roots={r['id']:r for r in lib.cfg['roots']}
    result={}
    for photo in lib.db.query('SELECT root_id,rel_path,inference_status FROM photos'):
        root_id=photo['root_id']
        if root_id not in roots:continue
        parts=photo['rel_path'].split('/')[:-1]
        paths=['/'.join(parts[:i]) for i in range(1,len(parts)+1)] if parts else ['.']
        for path in paths:
            row=result.setdefault((root_id,path),{'root_id':root_id,'root_name':roots[root_id].get('name',root_id),'path':path,'count':0,'ready':0})
            row['count']+=1;row['ready']+=photo['inference_status']=='ready'
    return sorted(result.values(),key=lambda row:(row['root_id'],row['path'].casefold()))


def sort_rows(rows, order):
    """Date comes from a valid YYYYMMDD folder prefix, never filesystem mtime."""
    import datetime,re
    if order not in ('date_asc','date_desc','name_asc','name_desc'):raise ValueError('目录排序无效')
    def date(row):
        match=re.match(r'^(\d{8})',row['name'])
        if match:
            try:return datetime.datetime.strptime(match[1],'%Y%m%d').date().isoformat()
            except ValueError:pass
        return None
    for row in rows:row['date']=date(row)
    reverse=order.endswith('_desc')
    if order.startswith('name'):rows.sort(key=lambda row:row['name'].casefold(),reverse=reverse)
    else:
        dated=sorted((r for r in rows if r['date']),key=lambda r:(r['date'],r['name'].casefold()),reverse=reverse)
        other=sorted((r for r in rows if not r['date']),key=lambda r:r['name'].casefold())
        rows[:]=dated+other
