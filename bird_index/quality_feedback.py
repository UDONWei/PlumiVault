"""Local user corrections bound to exact AI output; no images and no training."""
import hashlib
import json
from .common import encode, now
from .db import Conflict
from .adjustments import recipe

PREFIX='quality_feedback:'
CHOICES={
    'eye_location':{'unreviewed','correct','wrong','missed','uncertain'},
    'focus':{'unreviewed','clear','defocus','motion_blur','mixed','uncertain'},
    'occlusion':{'unreviewed','clear','partial','heavy','uncertain'},
    'posture':{'unreviewed','good','ordinary','poor','uncertain'}}


def key(quality):return hashlib.sha256(encode(quality).encode()).hexdigest() if quality else None


def public(raw,sha,quality,edit_revision=None):
    data=json.loads(raw) if raw else {'revision':0,'values':{}}
    return {k:v for k,v in data.items() if k not in ('prediction','history')}|{'stale':bool(data.get('source_sha') and (data['source_sha']!=sha or data.get('quality_key')!=key(quality) or edit_revision is not None and data.get('edit_revision',0)!=edit_revision))}


def save(lib,value):
    pid=value['photo_id'];revision=value['revision'];values=value['values']
    if type(pid) is not int or pid<1 or type(revision) is not int or revision<0:raise ValueError('反馈编号或版本无效')
    if not isinstance(values,dict) or set(values)-set(CHOICES)-{'note'}:raise ValueError('反馈字段无效')
    result={}
    for name,allowed in CHOICES.items():
        choice=values.get(name,'unreviewed')
        if not isinstance(choice,str) or choice not in allowed:raise ValueError('反馈选项无效')
        result[name]=choice
    note=values.get('note','')
    if not isinstance(note,str) or len(note)>500:raise ValueError('备注最多 500 字')
    result['note']=note
    with lib.db.transaction() as c:
        row=c.execute('SELECT root_id,rel_path,sha256,summary FROM photos WHERE id=?',(pid,)).fetchone()
        if not row:raise ValueError('照片不存在')
        root=next((r for r in lib.cfg['roots'] if r['id']==row['root_id']),None)
        if not root or root.get('allow_paths') is not None and row['rel_path'] not in root['allow_paths']:raise ValueError('照片不在当前授权范围')
        quality=json.loads(row['summary']).get('quality')
        if not quality or row['sha256']!=value['source_sha'] or key(quality)!=value['quality_key']:raise Conflict('照片或评分已更新，请刷新后核对')
        edit=c.execute('SELECT * FROM adjustments WHERE photo_id=?',(pid,)).fetchone()
        if edit and (edit['source_sha']!=row['sha256'] or recipe(json.loads(edit['recipe']))!=recipe(quality.get('recipe'))):raise Conflict('编辑参数已变化，请重新评分后纠正')
        old=c.execute('SELECT value FROM meta WHERE key=?',(PREFIX+str(pid),)).fetchone();old=json.loads(old[0]) if old else {'revision':0}
        if old['revision']!=revision:raise Conflict('反馈已在其他窗口修改，请刷新后重试')
        # Preserve a bounded audit trail instead of overwriting earlier corrections.
        history=old.get('history',[])
        if old.get('prediction'):history=[*history,{k:v for k,v in old.items() if k!='history'}][-10:]
        record={'photo_id':pid,'source_sha':row['sha256'],'quality_key':key(quality),'edit_revision':edit['revision'] if edit else 0,'revision':revision+1,'values':result,'prediction':quality,'updated_at':now(),'history':history}
        c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(PREFIX+str(pid),encode(record)));lib.db.bump(c)
    return public(encode(record),row['sha256'],quality)


def export(lib):
    rows=[]
    for item in lib.db.query("SELECT p.id,p.root_id,p.rel_path,p.sha256,p.summary,m.value,a.revision edit_revision FROM photos p JOIN meta m ON m.key=?||p.id LEFT JOIN adjustments a ON a.photo_id=p.id ORDER BY p.id",(PREFIX,)):
        root=next((r for r in lib.cfg['roots'] if r['id']==item['root_id']),None)
        if not root or root.get('allow_paths') is not None and item['rel_path'] not in root['allow_paths']:continue
        record=json.loads(item['value']);quality=json.loads(item['summary']).get('quality')
        rows.append({**record,'root_id':item['root_id'],'relative_path':item['rel_path'],'stale':public(item['value'],item['sha256'],quality,item['edit_revision'] or 0)['stale']})
    return {'schema':'plumivault-quality-feedback-v1','created_at':now(),'automatic_training':False,'photos':rows,'notice':'本地人工纠正与当时模型输出；不含图像，不自动上传或训练。每张保留最近 10 次旧记录。'}
