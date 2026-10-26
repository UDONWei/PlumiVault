from __future__ import annotations
import collections,csv,io,json,sqlite3,uuid,contextlib,hashlib,threading,re
from pathlib import Path
from .common import now,encode,safe_file,read_json
from .db import Conflict
from .grouping import plan
from .migration import compact,validate_legacy

class Library:
 def __init__(self,db,cfg):self.db=db;self.cfg=cfg;self.image_lock=threading.Lock()
 def root(self,id):
  if id not in {r['id'] for r in self.cfg['roots']}:raise ValueError('目录不在当前授权配置中')
  rows=self.db.query('SELECT * FROM roots WHERE id=?',(id,))
  if not rows:raise ValueError('目录不存在')
  row=rows[0];row['context']=json.loads(row['context']);row['allow_paths']=json.loads(row['allow_paths']) if row['allow_paths'] else None;return row
 def labels(self):
  from .search import tokens
  result={}
  for r in self.db.query('SELECT * FROM labels'):
   payload=json.loads(r['payload']);aliases=json.loads(r['aliases']);names=[r['name'],r['original_name'] or '',*aliases]
   result[r['id']]={'id':r['id'],'name':r['name'],'original_name':r['original_name'],'aliases':aliases,'catalog_status':payload.get('birdreport_status'),'english_name':payload.get('english_name',''),'search':list(dict.fromkeys([r['id'],payload.get('english_name',''),*names,*(key for name in names for key in tokens(name))]))}
  return result

 def items(self,ids=None):
  sql='SELECT p.*,m.status,m.species,m.reviewed_sha,m.updated_at,m.revision,s.flag,s.rating,s.revision AS selection_revision,a.preview AS edit_preview,a.source_sha AS edit_sha,a.revision AS edit_revision,v.hidden,v.revision AS visibility_revision FROM photos p JOIN manual m ON p.id=m.photo_id LEFT JOIN selections s ON s.photo_id=p.id LEFT JOIN adjustments a ON a.photo_id=p.id LEFT JOIN visibility v ON v.photo_id=p.id';args=[]
  if ids is not None:
   if not ids:return []
   sql+=' WHERE p.id IN ('+','.join('?' for _ in ids)+')';args=ids
  rows=self.db.query(sql+' ORDER BY p.id',args);items=[]
  for r in rows:
   if r['edit_preview'] and r['edit_sha']==r['sha256']:r['thumbnail']=r['edit_preview']
   row=json.loads(r['summary']);row.setdefault('path',r['display_path']);row.setdefault('directory',r['root_id']+'/'+str(Path(r['rel_path']).parent));row.setdefault('views',[])
   stale=bool(r['sha256'] and r['reviewed_sha']!=r['sha256'] and r['status']!='unreviewed')
   items.append({'id':r['id'],'path':r['display_path'],'root_id':r['root_id'],'relative_path':r['rel_path'],'pipeline':r['pipeline'],'edit_revision':r['edit_revision'] or 0,'source_status':r['source_status'],'inference_status':r['inference_status'],'error':r['error'],'sha256':r['sha256'],'thumbnail':('/thumbs/'+r['thumbnail']) if r['thumbnail'] else None,'visibility':{'hidden':bool(r['hidden']),'revision':r['visibility_revision'] or 0},'selection':{'flag':r['flag'] or 'none','rating':r['rating'] or 0,'revision':r['selection_revision'] or 0},'row':row,'manual':{'status':r['status'],'species':json.loads(r['species']),'reviewed_sha':r['reviewed_sha'],'updated_at':r['updated_at'],'revision':r['revision'],'stale':stale}})
  return items
 @staticmethod
 def public(item):
  row=item['row'];return {k:v for k,v in item.items() if k!='row'}|{'date':row.get('capture_context',{}).get('date'),'context':row.get('capture_context',{}),'exif':row.get('exif',{}),'detection':row.get('detection',{}),'candidates':(row.get('views') or [{}])[0].get('context_candidates',[]),'visual_candidates':(row.get('views') or [{}])[0].get('candidates',[]),'timings':row.get('timings',{}),'adjustments':row.get('adjustments'),'quality':row.get('quality')}
 def match(self,item,filters,labels):
  visibility=filters.get('visibility','visible')
  if visibility not in ('visible','hidden','all'):raise ValueError('隐藏状态筛选无效')
  if visibility!='all' and item['visibility']['hidden']!=(visibility=='hidden'):return False
  if filters.get('storage')=='quarantined':
   if item['source_status']!='quarantined':return False
  elif item['source_status']=='quarantined':return False
  if filters.get('flag') and item['selection']['flag']!=filters['flag']:return False
  if item['selection']['rating']<int(filters.get('rating') or 0):return False
  quality=item['row'].get('quality') or {}
  if filters.get('min_score') and (quality.get('score') is None or quality['score']<int(filters['min_score'])):return False
  if filters.get('max_score') and (quality.get('score') is None or quality['score']>int(filters['max_score'])):return False
  if filters.get('quality')=='unscored' and quality:return False
  if filters.get('quality')=='issues' and not quality.get('needs_review'):return False
  subfolder=filters.get('subfolder')
  if subfolder=='.' and '/' in item['relative_path']:return False
  if subfolder and subfolder!='.' and not item['relative_path'].startswith(subfolder.strip('/')+'/'):return False
  status=item['manual']['status'];state=filters.get('state','all');context=item['row'].get('capture_context',{})
  if state=='no_bird':
   if status!='no_bird':return False
  elif state!='any' and status=='no_bird':return False
  if state=='pending' and status=='confirmed' and not item['manual']['stale']:return False
  if state in ('confirmed','uncertain','none_match') and status!=state:return False
  if state=='stale' and not item['manual']['stale']:return False
  if state=='missing' and item['source_status']!='missing':return False
  if state=='error' and item['inference_status']!='error':return False
  if state=='undetected' and item['row'].get('detection',{}).get('status')=='detected':return False
  if filters.get('root') and item['root_id']!=filters['root']:return False
  date=context.get('date') or ''
  if filters.get('from') and (not date or date<filters['from']):return False
  if filters.get('to') and (not date or date>filters['to']):return False
  normalize_location=lambda s:re.sub(r'[\s·]|市辖区|省直辖县级行政区划|自治区|特别行政区|省|市','',s).casefold()
  if filters.get('region') and normalize_location(filters['region']) not in normalize_location(context.get('location') or ''):return False
  ids=item['manual']['species'] if status=='confirmed' else [c['label'].get('scientific_name') for c in (item['row'].get('views') or [{}])[0].get('context_candidates',[]) if c['label']['kind']=='bird']
  if filters.get('species') and filters['species'] not in ids:return False
  q=filters.get('q','').strip().casefold()
  if q:
   texts=[item['path']]+ids
   for id in ids:
    l=labels.get(id,{});texts.extend([l.get('name',''),l.get('original_name') or '',l.get('english_name') or '',*l.get('aliases',[]),*l.get('search',[])])
   if not any(q in t.casefold() for t in texts if t):return False
  return True
 def listing(self,filters):
  offset=max(0,int(filters.get('offset',0)));limit=max(1,min(100,int(filters.get('limit',24))));labels=self.labels();items=self.items();prefs=json.loads(self.db.meta('view'));matches=[p for p in items if self.match(p,filters,labels)];wanted={p['id'] for p in matches}
  if filters.get('sort')=='score':matches.sort(key=lambda p:((p['row'].get('quality') or {}).get('score',-1),-p['id']),reverse=True)
  if filters.get('mode')=='photos' or not prefs['grouping']:
   page=matches[offset:offset+limit];result={'total':len(matches),'matched_photos':len(matches),'offset':offset,'limit':limit,'mode':'photos','items':[self.public(p) for p in page]}
   if filters.get('bursts')=='1':
    result['bursts']=[]
    for g in plan(items,prefs,with_similarity=False):
     member_ids={m['id'] for m in g['members']}
     ids=[p['id'] for p in page if p['id'] in member_ids]
     if ids:result['bursts'].append({'key':g['key'],'ids':ids,'count':len(g['members']),'matched_count':sum(m['id'] in wanted for m in g['members']),'species':g['species'],'confirmed':g['confirmed']})
   return result
  groups=[]
  for group in plan(items,prefs):
   members=[p for p in group['members'] if p['id'] in wanted]
   if not members:continue
   selected={p['id'] for p in members};folded=[f for f in group['folded'] if f['id'] in selected and f['representative'] in selected] if prefs['foldSimilar'] else [];hidden={f['id'] for f in folded}
   cover=group['cover'] if group['cover'] in selected and group['cover'] not in hidden else next(p['id'] for p in members if p['id'] not in hidden)
   groups.append({'key':group['key'],'species':group['species'],'confirmed':group['confirmed'],'ids':[p['id'] for p in members],'folded':folded,'cover':self.public(next(p for p in members if p['id']==cover)),'count':len(members),'unreviewed':sum(p['manual']['status']=='unreviewed' for p in members),'members':[{'id':p['id'],'revision':p['manual']['revision'],'status':p['manual']['status']} for p in members]})
  return {'total':len(groups),'matched_photos':len(matches),'offset':offset,'limit':limit,'mode':'groups','items':groups[offset:offset+limit]}
 def summary(self):
  rows=self.db.query('SELECT m.status,m.species,m.reviewed_sha,p.sha256,p.source_status FROM manual m JOIN photos p ON p.id=m.photo_id');counts=collections.Counter(r['status'] for r in rows);species=collections.Counter(s for r in rows if r['status']=='confirmed' for s in json.loads(r['species']));labels=self.labels()
  stale=lambda r:bool(r['sha256'] and r['reviewed_sha']!=r['sha256'] and r['status']!='unreviewed')
  return {'library_id':self.db.meta('library_id'),'photos':len(rows),'counts':dict(counts),'stale':sum(stale(r) for r in rows),'pending':sum(r['status'] not in ('confirmed','no_bird') or stale(r) for r in rows),'missing':sum(r['source_status']=='missing' for r in rows),'species':[{'id':id,'name':labels[id]['name'],'count':count} for id,count in species.most_common()],'roots':[self.root(r['id']) for r in self.cfg['roots']],'view':json.loads(self.db.meta('view')),'taxonomy':json.loads(self.db.meta('taxonomy') or '{}'),'max_files_per_job':self.cfg.get('max_files_per_job',10),'generation':int(self.db.meta('generation'))}
 def preferences(self,prefs):
  if type(prefs.get('gap'))!=int or not 1<=prefs['gap']<=120 or any(type(prefs.get(k))!=bool for k in ('grouping','foldSimilar')):raise ValueError('分组设置无效')
  known={r['id'] for r in self.db.query('SELECT id FROM photos')}
  for key in ('breaks','keep','covers'):
   if not isinstance(prefs.get(key),list) or len(set(prefs[key]))!=len(prefs[key]) or not set(prefs[key])<=known:raise ValueError('浏览设置照片无效')
  prefs={k:prefs[k] for k in ('gap','grouping','foldSimilar','breaks','keep','covers')}
  with self.db.transaction() as c:c.execute("UPDATE meta SET value=? WHERE key='view'",(encode(prefs),));self.db.bump(c)
  return prefs
 def export_reviews(self):
  return {'schema':'bird-index-review-v1','library_id':self.db.meta('library_id'),'exported_at':now(),'photos':[{'id':p['id'],'root_id':p['root_id'],'relative_path':p['relative_path'],'observed_sha256':p['sha256'],**p['manual']} for p in self.items()]}
 def import_reviews(self,doc,apply=False,expected_generation=None):
  items=self.items();byid={p['id']:p for p in items};checked=[]
  if doc.get('schema') in ('bird-manual-review-v1','bird-manual-review-v2'):
   expected=set(json.loads(self.db.meta('legacy_paths') or '[]'))
   if not expected or {r.get('path') for r in doc.get('photos',[])}!=expected:raise ValueError('旧批次导入必须包含完整原批次')
   subset=[p for p in items if p['path'] in expected]
   payload={'rows':[{'path':p['path'],'before':{'sha256':p['sha256']}} for p in subset],'labels':self.db.labels(),'review_batch_id':self.db.meta('legacy_batch')}
   records=validate_legacy(payload,doc)
   for p in subset:
    r=records[p['path']];checked.append({'photo_id':p['id'],'status':r['status'],'species':[s['scientific_name'] for s in r['species']],'reviewed_sha':r['source_sha256'],'updated_at':r['updated_at']})
  else:
   if doc.get('schema')!='bird-index-review-v1' or doc.get('library_id')!=self.db.meta('library_id'):raise ValueError('不是本图库的复核备份')
   photos=doc.get('photos',[])
   if not photos or len(photos)>len(items) or len({p['id'] for p in photos})!=len(photos):raise ValueError('备份照片列表无效')
   for r in photos:
    p=byid.get(r['id'])
    if not p or r['root_id']!=p['root_id'] or r['relative_path']!=p['relative_path'] or r['observed_sha256']!=p['sha256']:raise ValueError('备份路径或照片指纹不符')
    self.db.validate_record(r['status'],r['species'])
    if r['updated_at'] is not None:
     from datetime import datetime
     datetime.fromisoformat(r['updated_at'].replace('Z','+00:00'))
    if r['reviewed_sha'] is not None and (not isinstance(r['reviewed_sha'],str) or len(r['reviewed_sha'])!=64 or any(ch not in '0123456789abcdef' for ch in r['reviewed_sha'])):raise ValueError('人工记录指纹格式无效')
    checked.append({'photo_id':p['id'],**{k:r[k] for k in ('status','species','reviewed_sha','updated_at')}})
  counts=dict(collections.Counter(r['status'] for r in checked))
  if not apply:return {'count':len(checked),'counts':counts,'notice':'应用会替换文件中这些照片的人工记录，其他照片保持；应用前自动建立数据库备份。'}
  backup=self.db.backup()
  with self.db.transaction() as c:
   if expected_generation is not None and c.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0]!=expected_generation:raise Conflict('预览后图库已有变化，请重新预览')
   before=[];after=[]
   for r in checked:
    current=c.execute('SELECT m.*,p.sha256 FROM manual m JOIN photos p ON p.id=m.photo_id WHERE photo_id=?',(r['photo_id'],)).fetchone()
    if current['revision']!=byid[r['photo_id']]['manual']['revision'] or current['sha256']!=byid[r['photo_id']]['sha256']:raise Conflict('导入期间照片记录变化，请重新预览')
    old=self.db.record(current);new={**r,'revision':old['revision']+1};before.append(old);after.append(new)
    c.execute('UPDATE manual SET status=?,species=?,reviewed_sha=?,updated_at=?,revision=? WHERE photo_id=?',(new['status'],encode(new['species']),new['reviewed_sha'],new['updated_at'],new['revision'],r['photo_id']))
   change=c.execute('INSERT INTO changes(created_at,before_json,after_json) VALUES(?,?,?)',(now(),encode(before),encode(after))).lastrowid;self.db.bump(c)
  return {'count':len(checked),'counts':counts,'backup':backup.name,'change_id':change}
 def export_csv(self,filters):
  labels=self.labels();stream=io.StringIO(newline='');writer=csv.writer(stream);writer.writerow(['文件','目录','拍摄日期','日期来源','地点','状态','人工鸟种','学名','模型首选','源文件状态','需重新复核','现有完整路径','模型候选与分数JSON','处理版本','初筛标记','人工星级','技术参考分','质量提示','已隐藏'])
  def cell(value):
   value=str(value or '');return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value
  for p in self.items():
   if not self.match(p,filters,labels):continue
   ctx=p['row'].get('capture_context',{});candidates=(p['row'].get('views') or [{}])[0].get('context_candidates',[]);top=candidates[0]['label'].get('scientific_name','') if candidates else ''
   for s in p['manual']['species'] or ['']:
    writer.writerow([cell(v) for v in (p['path'],p['root_id'],ctx.get('date'),ctx.get('date_source'),ctx.get('location'),p['manual']['status'],labels.get(s,{}).get('name'),s,labels.get(top,{}).get('name',top),p['source_status'],p['manual']['stale'],str(Path(self.root(p['root_id'])['path'])/p['relative_path']),encode(candidates),p['pipeline'],p['selection']['flag'],str(p['selection']['rating']),str((p['row'].get('quality') or {}).get('score','')),'；'.join((p['row'].get('quality') or {}).get('issues',[])),'是' if p['visibility']['hidden'] else '否')])
  return ('\ufeff'+stream.getvalue()).encode('utf-8')
 def context(self,root_id,values,scope=''):
  from context_prior import load_occurrences,validate_context,resolve_context,rank_scores
  occurrences=load_occurrences(Path(self.cfg['priors_path']));validate_context(values,occurrences['regions']);root=self.root(root_id)
  if scope:
   from .folders import directory
   directory(root['path'],scope)
  labels=json.loads(self.db.meta('score_labels'));updated=0
  with self.db.transaction() as c:
   if scope:c.execute('INSERT INTO folder_contexts VALUES(?,?,?) ON CONFLICT(root_id,scope) DO UPDATE SET context=excluded.context',(root_id,scope,encode(values)))
   else:c.execute('UPDATE roots SET context=? WHERE id=?',(encode(values),root_id))
   for record in c.execute('SELECT p.id,p.rel_path,a.payload FROM photos p JOIN analyses a ON a.photo_id=p.id WHERE p.root_id=?',(root_id,)).fetchall():
    if scope and not record['rel_path'].startswith(scope+'/'):continue
    row=json.loads(record['payload']);row['capture_context']=resolve_context(self.effective_context(root_id,record['rel_path'],c),{},row.get('exif',{}),root['name'],record['rel_path'],occurrences['regions'])
    for view in row.get('views',[]):
     if view.get('all_visual_scores'):view.update(rank_scores(labels,view['all_visual_scores'],row['capture_context'],occurrences,min(5,len(labels))))
    c.execute('UPDATE analyses SET payload=? WHERE photo_id=?',(encode(row),record['id']));c.execute('UPDATE photos SET summary=? WHERE id=?',(encode(compact(row)),record['id']));updated+=1
   self.db.bump(c)
  return {'updated':updated,'context':values}

 def photo_source(self,photo_id):
  if type(photo_id)!=int:raise ValueError('照片编号无效')
  rows=self.db.query('SELECT * FROM photos WHERE id=?',(photo_id,))
  if not rows:raise ValueError('照片不存在')
  photo=rows[0];root=self.root(photo['root_id'])
  if photo['source_status']=='quarantined':raise ValueError('原片已移至待删除，请先恢复')
  if root['allow_paths'] is not None and photo['rel_path'] not in root['allow_paths']:raise ValueError('照片不在当前授权清单内')
  safe_file(root['path'],photo['rel_path'])
  return photo
 def adjustment(self,photo_id):
  from .adjustments import recipe
  rows=self.db.query('SELECT * FROM adjustments WHERE photo_id=?',(photo_id,))
  if not rows:return {'recipe':recipe(),'revision':0,'source_sha':None,'updated_at':None}
  row=rows[0];row['recipe']=recipe(json.loads(row['recipe']));return row
 def preview_version(self,photo_id):
  photo=self.photo_source(photo_id);path=safe_file(self.root(photo['root_id'])['path'],photo['rel_path']);s=path.stat()
  key=hashlib.sha256(encode([str(path),photo['sha256'],s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino,s.st_dev]).encode()).hexdigest()
  return {'sha256':photo['sha256'],'key':key}
 def editor(self,photo_id):
  photo=self.photo_source(photo_id);adjust=self.adjustment(photo_id);history=[]
  for r in self.db.query('SELECT * FROM processing_history WHERE photo_id=? ORDER BY id DESC LIMIT 5',(photo_id,)):
   payload=json.loads(r['payload']);history.append({'id':r['id'],'created_at':r['created_at'],'job_id':r['job_id'],'recipe':json.loads(r['recipe']),'source_sha':r['source_sha'],'candidates':(payload.get('views') or [{}])[0].get('context_candidates',[])})
  return {'preview_version':self.preview_version(photo_id),'photo':self.public(self.items([photo_id])[0]),'adjustment':adjust,'stale_adjustment':bool(adjust['source_sha'] and adjust['source_sha']!=photo['sha256']),'history':history,'source_path':str(Path(self.root(photo['root_id'])['path'])/photo['rel_path'])}
 def save_adjustment(self,photo_id,expected_sha,revision,value,preview=None):
  from .adjustments import recipe
  normalized=recipe(value);photo=self.photo_source(photo_id)
  if not expected_sha or photo['sha256']!=expected_sha:raise Conflict('照片版本已改变，请重新打开原图')
  preview_name=None
  if preview is not None:
   from .thumbs import save_jpeg
   preview_name=save_jpeg(self,preview)
  with self.db.transaction() as c:
   old=c.execute('SELECT revision FROM adjustments WHERE photo_id=?',(photo_id,)).fetchone()
   current=c.execute('SELECT sha256 FROM photos WHERE id=?',(photo_id,)).fetchone()[0]
   if (old['revision'] if old else 0)!=revision or current!=expected_sha:raise Conflict('调整参数或照片已被另一任务修改，请重新打开')
   c.execute('INSERT INTO adjustments(photo_id,source_sha,recipe,revision,updated_at,preview) VALUES(?,?,?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET source_sha=excluded.source_sha,recipe=excluded.recipe,revision=excluded.revision,updated_at=excluded.updated_at,preview=excluded.preview',(photo_id,expected_sha,encode(normalized),revision+1,now(),preview_name));self.db.bump(c)
  return self.adjustment(photo_id)

 def effective_context(self,root_id,path,connection=None):
  def query(sql,args):return list(connection.execute(sql,args)) if connection is not None else self.db.query(sql,args)
  base=query('SELECT context FROM roots WHERE id=?',(root_id,))
  if not base:raise ValueError('目录不存在')
  context=json.loads(base[0]['context']);length=-1
  for row in query('SELECT scope,context FROM folder_contexts WHERE root_id=?',(root_id,)):
   if path.startswith(row['scope']+'/') and len(row['scope'])>length:context=json.loads(row['context']);length=len(row['scope'])
  return context
