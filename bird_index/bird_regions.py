"""Individual bird identities in full-image coordinates; metadata-only reviews."""
import hashlib
import json
from .common import encode,now
from .adjustments import recipe
from .db import Conflict

PREFIX='bird_regions:'


def region_id(box):return hashlib.sha256(encode([round(v,6) for v in box]).encode()).hexdigest()[:20]


def detected(row):
    result=[];views={v.get('region_id'):v for v in row.get('views',[]) if v.get('region_id')}
    for item in row.get('detection',{}).get('detections',[]):
        try:box=recipe({'box':item['box']})['box']
        except (ValueError,TypeError,KeyError):continue
        if not box:continue
        key=region_id(box)
        if any(p['id']==key for p in result):continue
        view=views.get(key,{})
        result.append({'id':key,'box':box,'score':item.get('score'),'candidates':view.get('context_candidates',[]),'status':'unreviewed','species':[]})
    return result


def scene(row,sha,raw=None):
    from subject_detector import iou
    record=json.loads(raw) if raw else {};regions=detected(row)
    signature=hashlib.sha256(encode([sha,regions]).encode()).hexdigest()
    stale=bool(record.get('source_sha') and record['source_sha']!=sha)
    # Keep reviewed anchors on unchanged source pixels; never silently transfer
    # a review to a neighbouring bird when two detections overlap the anchor.
    if not stale:
        used=set()
        for saved in record.get('items',[]):
            if saved['status']=='unreviewed':continue
            matches=[(iou(saved['box'],p['box']),i) for i,p in enumerate(regions) if i not in used]
            matches=sorted((m for m in matches if m[0]>=.65),reverse=True)
            exact=[m for m in matches if regions[m[1]]['id']==saved['id']]
            if exact:matches=exact
            if len(matches)==1:
                i=matches[0][1];used.add(i);regions[i]={**regions[i],**saved,'retained':True}
            else:
                regions.append({**saved,'candidates':[],'retained':True,'needs_box_review':True});used.add(len(regions)-1)
    return {'items':regions,'revision':record.get('revision',0),'source_sha':sha,'key':signature,'stale_previous':stale}


def species(item,confirmed_only=False):
    ids=[]
    for region in item.get('birds',{}).get('items',[]):
        if region['status']=='confirmed':ids.extend(region['species'])
        elif not confirmed_only and region['status']=='unreviewed':ids.extend(c['label']['scientific_name'] for c in region['candidates'] if c['label'].get('kind')=='bird')
    return list(dict.fromkeys(ids))


def save(lib,value):
    pid=value['photo_id'];revision=value['revision'];status=value['status'];names=value['species']
    if type(pid) is not int or pid<1 or type(revision) is not int or revision<0:raise ValueError('照片或标注版本无效')
    lib.db.validate_record(status,names)
    if len(names)>1:raise ValueError('每只鸟请确认一个鸟种')
    with lib.db.transaction() as c:
        row=c.execute('SELECT root_id,rel_path,sha256,summary FROM photos WHERE id=?',(pid,)).fetchone()
        if not row:raise ValueError('照片不存在')
        root=next((r for r in lib.cfg['roots'] if r['id']==row['root_id']),None)
        if not root or root.get('allow_paths') is not None and row['rel_path'] not in root['allow_paths']:raise ValueError('照片超出授权范围')
        old=c.execute('SELECT value FROM meta WHERE key=?',(PREFIX+str(pid),)).fetchone();raw=old[0] if old else None
        current=scene(json.loads(row['summary']),row['sha256'],raw)
        if not value['source_sha'] or value['source_sha']!=row['sha256'] or current['revision']!=revision or value['scene_key']!=current['key']:raise Conflict('照片、检测框或标注已更新，请刷新后重试')
        selected=next((p for p in current['items'] if p['id']==value['region_id']),None)
        if selected is None:raise ValueError('鸟体框不存在')
        record=json.loads(raw) if raw else {};history=record.get('history',[])
        if record.get('source_sha')!=row['sha256']:
            if record.get('items'):history=[*history,{k:v for k,v in record.items() if k!='history'}][-5:]
            record['items']=[]
        items=[p for p in record.get('items',[]) if p['id']!=selected['id']]
        if status!='unreviewed':items.append({'id':selected['id'],'box':selected['box'],'status':status,'species':names,'updated_at':now()})
        updated={'source_sha':row['sha256'],'revision':revision+1,'items':items,'history':history}
        c.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(PREFIX+str(pid),encode(updated)));lib.db.bump(c)
    return scene(json.loads(row['summary']),row['sha256'],encode(updated))
