from __future__ import annotations
import contextlib,itertools,json,os,queue,sqlite3,subprocess,sys,threading,time,uuid
from . import folders
from pathlib import Path
from .common import FORMATS,now,encode,safe_file,relative,PROJECT
from .migration import compact

class InferenceClient:
 def __init__(self,cfg):self.cfg=cfg;self.process=None;self.log=None;self.initialization=None
 def start(self):
  if self.process and self.process.poll() is None:return
  logfile=Path(self.cfg['data_dir'])/'runtime/worker.log'
  if logfile.exists() and logfile.stat().st_size>5*1024**2:logfile.replace(logfile.with_suffix('.previous.log'))
  self.log=logfile.open('a',encoding='utf-8');flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
  self.process=subprocess.Popen([sys.executable,'-X','utf8','-B','-m','bird_index.worker','--config',self.cfg['_path']],cwd=PROJECT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',bufsize=1,creationflags=flags)
  line=self.process.stdout.readline()
  if not line:raise RuntimeError('模型进程启动失败，详见运行日志')
  ready=json.loads(line)
  if not ready.get('ready'):raise RuntimeError('模型进程没有就绪')
  self.initialization=ready['initialization_s']
 def run(self,request):
  self.start();self.process.stdin.write(encode(request)+'\n');self.process.stdin.flush();line=self.process.stdout.readline()
  if not line:raise RuntimeError('模型进程退出，当前照片可重试')
  return json.loads(line)['row']
 def close(self):
  if self.process:
   if self.process.poll() is None:
    self.process.stdin.close()
    try:self.process.wait(timeout=3)
    except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=10)
   if self.process.stdout:self.process.stdout.close()
   if self.log:self.log.close()
   self.process=None

class Jobs:
 def __init__(self,library,processor=None):
  self.lib=library;self.db=library.db;self.cfg=library.cfg;self.stop=threading.Event();self.wake=threading.Event();self.thread=None;self.processor=processor or InferenceClient(self.cfg)
 def start(self):self.thread=threading.Thread(target=self.loop,daemon=True,name='bird-index-jobs');self.thread.start()
 def close(self):
  self.stop.set();self.wake.set();self.processor.close()
  if self.thread:self.thread.join(timeout=10)
 def list(self):
  # One read snapshot: progress never opens originals or starts processing.
  with contextlib.closing(self.db.connect()) as c:
   c.execute('BEGIN')
   jobs=[dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY CASE WHEN state IN ('queued','discovering','running','paused') THEN 0 ELSE 1 END,created_at DESC LIMIT 50")]
   for job in jobs:
    job['counts']={r['state']:r['n'] for r in c.execute('SELECT state,count(*) n FROM job_items WHERE job_id=? GROUP BY state',(job['id'],))}
    current=c.execute("SELECT p.id,p.rel_path path FROM job_items i JOIN photos p ON p.id=i.photo_id WHERE i.job_id=? AND i.state='running' ORDER BY p.id LIMIT 1",(job['id'],)).fetchone() if job['counts'].get('running') else None
    job['current_photo']=dict(current) if current else None
   return jobs
 def create(self,root_id,scope='',limit=None,force=False,scopes=None):
  root=self.lib.root(root_id);scope=relative(scope,empty=True)
  if scopes is not None:scopes=folders.validate(root['path'],scopes)
  elif self.cfg.get('require_folder_selection'):raise ValueError('请先勾选目录后扫描')
  cap=self.cfg['max_files_per_job']
  if limit is None:limit=0 if cap==0 else min(50,cap)
  if type(limit)!=int or not 0<=limit<=9223372036854775807 or type(force)!=bool:raise ValueError('任务数量或设置无效')
  if cap and (limit==0 or limit>cap):raise ValueError('任务数量超过当前配置上限')
  if limit==0 and not scopes:raise ValueError('不设上限时必须明确勾选目录')
  if scope:
   path=(Path(root['path'])/scope).resolve(strict=True)
   if not path.is_relative_to(Path(root['path'])) or not path.is_dir():raise ValueError('扫描子目录越界或不存在')
  id=uuid.uuid4().hex
  with self.db.transaction() as c:
   if c.execute("SELECT 1 FROM file_plans WHERE state='executing' LIMIT 1").fetchone():raise ValueError('原片整理尚未完成，请先恢复整理操作')
   if c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','discovering','running','paused')").fetchone()[0]>=20:raise ValueError('已有较多未完成任务，请先完成或取消')
   c.execute('INSERT INTO jobs(id,root_id,scope,limit_count,state,force,created_at,updated_at,scopes) VALUES(?,?,?,?,?,?,?,?,?)',(id,root_id,scope,limit,'queued',int(force),now(),now(),encode(scopes) if scopes is not None else None))
  self.wake.set()
  return {'id':id}
 def reprocess(self,photo_id,source_sha,revision):
  photo=self.lib.photo_source(photo_id);adjustment=self.lib.adjustment(photo_id)
  if photo['sha256']!=source_sha or adjustment['revision']!=revision or adjustment['source_sha']!=source_sha:raise ValueError('请先保存当前照片的调整参数再重新识别')
  id=uuid.uuid4().hex
  with self.db.transaction() as c:
   current=c.execute('SELECT revision FROM adjustments WHERE photo_id=?',(photo_id,)).fetchone()
   if current['revision']!=revision:raise ValueError('调整参数已更新，请重新打开编辑器')
   if c.execute("SELECT 1 FROM file_plans WHERE state='executing' LIMIT 1").fetchone():raise ValueError('原片整理尚未完成，请先恢复整理操作')
   if c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','discovering','running','paused')").fetchone()[0]>=20:raise ValueError('未完成任务过多，请先完成或取消')
   if c.execute("SELECT 1 FROM job_items i JOIN jobs j ON j.id=i.job_id WHERE i.photo_id=? AND j.state IN ('queued','discovering','running','paused') AND i.state IN ('pending','running') LIMIT 1",(photo_id,)).fetchone():raise ValueError('这张照片已有未完成任务，请先完成或取消')
   c.execute('INSERT INTO jobs(id,root_id,scope,limit_count,state,force,created_at,updated_at,discovery_done) VALUES(?,?,?,?,?,?,?,?,1)',(id,photo['root_id'],'',1,'queued',1,now(),now()))
   c.execute('INSERT INTO job_items(job_id,photo_id,state,request) VALUES(?,?,?,?)',(id,photo_id,'pending',encode({**adjustment,'strict':True})))
   c.execute('UPDATE jobs SET found=1 WHERE id=?',(id,))
  self.wake.set()
  return {'id':id,'photo_id':photo_id,'notice':'只重新识别这一张，已有人工确认保持'}
 def action(self,id,action):
  with self.db.transaction() as c:
   job=c.execute('SELECT * FROM jobs WHERE id=?',(id,)).fetchone()
   if not job:raise ValueError('任务不存在')
   if action=='pause' and job['state'] in ('queued','discovering','running'):state='paused'
   elif action=='cancel' and job['state'] not in ('completed','cancelled'):state='cancelled'
   elif action in ('resume','retry') and job['state'] in ('paused','failed','completed','cancelled'):
    if c.execute("SELECT 1 FROM file_plans WHERE state='executing' LIMIT 1").fetchone():raise ValueError('原片整理尚未完成')
    state='queued'
    if action=='retry':c.execute("UPDATE job_items SET state='pending',error=NULL WHERE job_id=? AND state='error'",(id,))
   else:raise ValueError('当前任务状态不支持这个操作')
   c.execute('UPDATE jobs SET state=?,updated_at=?,error=NULL WHERE id=?',(state,now(),id))
  self.wake.set()
  return {'id':id,'state':state,'notice':'暂停和取消会在当前照片结束后生效；已完成结果保留'}
 def state(self,id):return self.db.query('SELECT state FROM jobs WHERE id=?',(id,))[0]['state']
 def discover(self,job):
  root=self.lib.root(job['root_id']);base=Path(root['path']);scope=job['scope'];selected=json.loads(job['scopes']) if job.get('scopes') else None;seen=set();paths=[];errors=[]
  if not base.is_dir():raise ValueError('照片目录不可访问，未将已有文件批量标为丢失')
  def walk(folder,recurse=True):
   try:
    with os.scandir(folder) as scan:entries=sorted(list(scan),key=lambda e:e.name.casefold())
    for entry in entries:
     if self.stop.is_set() or self.state(job['id']) in ('paused','cancelled'):return
     try:
      info=entry.stat(follow_symlinks=False)
      if entry.is_symlink() or (getattr(info,'st_file_attributes',0)&0x400):continue
      path=Path(entry.path)
      if entry.is_dir(follow_symlinks=False):
       if recurse:yield from walk(path)
      elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in FORMATS:yield path.relative_to(base).as_posix()
     except OSError as exc:errors.append(str(exc))
   except OSError as exc:errors.append(str(exc))
  if selected is not None:folders.validate(base,selected)
  if root['allow_paths'] is not None:iterator=(p for p in root['allow_paths'] if (folders.includes(p,selected) if selected is not None else not scope or p.startswith(scope+'/')))
  elif selected is not None:iterator=itertools.chain.from_iterable(walk(base if s=='.' else base/s,recurse=s!='.') for s in selected)
  else:iterator=walk(base/scope)
  to_process=0;skipped=0;limited=False
  for rel in iterator:
   if self.stop.is_set() or self.state(job['id']) in ('paused','cancelled'):return
   seen.add(rel)
   try:path=safe_file(base,rel);stat=path.stat()
   except (OSError,ValueError) as exc:
    with self.db.transaction() as c:c.execute("UPDATE photos SET source_status='missing',error=? WHERE root_id=? AND rel_path=?",(str(exc),root['id'],rel));self.db.bump(c)
    continue
   with self.db.transaction() as c:
    old=c.execute('SELECT * FROM photos WHERE root_id=? AND rel_path=?',(root['id'],rel)).fetchone()
    if old and old['source_status']=='quarantined':
     skipped+=1;continue
    unchanged=old and old['size']==stat.st_size and old['mtime_ns']==stat.st_mtime_ns and old['pipeline']==self.cfg['pipeline_version'] and old['inference_status']=='ready' and not job['force']
    if old:
     pid=old['id'];c.execute("UPDATE photos SET source_status='available' WHERE id=?",(pid,))
    else:
     display=root['id']+'/'+rel;row={'path':display,'directory':root['id']+'/'+str(Path(rel).parent),'capture_context':root['context'],'views':[]}
     pid=c.execute('INSERT INTO photos(root_id,rel_path,display_path,size,mtime_ns,summary) VALUES(?,?,?,?,?,?)',(root['id'],rel,display,stat.st_size,stat.st_mtime_ns,encode(row))).lastrowid;c.execute('INSERT INTO manual(photo_id) VALUES(?)',(pid,))
    existing=c.execute('SELECT state FROM job_items WHERE job_id=? AND photo_id=?',(job['id'],pid)).fetchone()
    if not existing:c.execute('INSERT INTO job_items(job_id,photo_id,state,error) VALUES(?,?,?,NULL)',(job['id'],pid,'skipped' if unchanged else 'pending'))
    if unchanged:skipped+=1
    elif not existing or existing['state']=='pending':to_process+=1
    c.execute('UPDATE jobs SET found=?,skipped=?,updated_at=? WHERE id=?',(len(seen),skipped,now(),job['id']));self.db.bump(c)
   if job['limit_count']>0 and to_process>=job['limit_count']:limited=True;break
  if self.state(job['id']) in ('paused','cancelled'):return
  if not limited and not errors:
   with self.db.transaction() as c:
    for old in c.execute('SELECT id,rel_path,source_status FROM photos WHERE root_id=?',(root['id'],)).fetchall():
     if (folders.includes(old['rel_path'],selected) if selected is not None else not scope or old['rel_path'].startswith(scope+'/')) and old['rel_path'] not in seen and old['source_status']!='quarantined':c.execute("UPDATE photos SET source_status='missing' WHERE id=?",(old['id'],))
  with self.db.transaction() as c:
   message=('本次达到处理数量上限；完成后可再建增量任务继续。' if limited else '')+(' 部分目录不可读：'+'; '.join(errors)[:800] if errors else '')
   c.execute('UPDATE jobs SET discovery_done=1,error=?,updated_at=? WHERE id=?',(message or None,now(),job['id']));self.db.bump(c)
 def run_one(self,id):
  rows=self.db.query('SELECT * FROM jobs WHERE id=?',(id,))
  if not rows:return
  job=rows[0]
  if job['state'] not in ('queued','discovering','running'):return
  try:
   if not job['discovery_done']:
    with self.db.transaction() as c:c.execute("UPDATE jobs SET state='discovering',updated_at=? WHERE id=? AND state='queued'",(now(),id))
    self.discover(job)
   if self.state(id) in ('paused','cancelled') or self.stop.is_set():return
   with self.db.transaction() as c:c.execute("UPDATE jobs SET state='running',updated_at=? WHERE id=? AND state IN ('queued','discovering')",(now(),id))
   while not self.stop.is_set() and self.state(id)=='running':
    pending=self.db.query("SELECT p.*,j.request FROM job_items j JOIN photos p ON p.id=j.photo_id WHERE j.job_id=? AND j.state='pending' ORDER BY p.id LIMIT 1",(id,))
    if not pending:
     with self.db.transaction() as c:
      errors=c.execute("SELECT count(*) FROM job_items WHERE job_id=? AND state='error'",(id,)).fetchone()[0]
      c.execute("UPDATE jobs SET state=?,updated_at=? WHERE id=? AND state='running'",('failed' if errors else 'completed',now(),id))
     break
    p=pending[0];root=self.lib.root(p['root_id'])
    with self.db.transaction() as c:c.execute("UPDATE job_items SET state='running' WHERE job_id=? AND photo_id=?",(id,p['id']))
    try:
     stored=json.loads(p['request']) if p['request'] else {}
     expected=stored.get('scan_source')
     if expected:
      from .scan_plan import checked_source
      stat=checked_source(root['path'],p['rel_path']).stat()
      if (stat.st_size,stat.st_mtime_ns)!=(expected['size'],expected['mtime_ns']):raise ValueError('源文件变化，请重新检查目录并确认清单')
     adjustment=stored if stored and not expected else {**self.lib.adjustment(p['id']),'strict':False}
     with self.lib.image_lock:
      row=self.processor.run({'root_id':root['id'],'relative_path':p['rel_path'],'display_path':p['display_path'],'directory':root['id']+'/'+str(Path(p['rel_path']).parent),'context':self.lib.effective_context(root['id'],p['rel_path']),'adjustment':adjustment,'expected_source':expected})
     if row.get('error') or not row.get('source_unchanged') or not row.get('views'):raise ValueError(row.get('error') or '源文件校验或识别结果无效')
     # 地区设置可能在处理过程中改变，使用最终数据库设置重新排序已有分数。
     from context_prior import resolve_context,load_occurrences,rank_scores
     priors=load_occurrences(Path(self.cfg['priors_path']));latest=self.lib.root(root['id']);row['capture_context']=resolve_context(self.lib.effective_context(root['id'],p['rel_path']),{},row.get('exif',{}),latest['name'],p['rel_path'],priors['regions'])
     labels=json.loads(self.db.meta('score_labels'))
     for view in row['views']:view.update(rank_scores(labels,view['all_visual_scores'],row['capture_context'],priors,min(5,len(labels))))
     before=row['before'];thumb=row['views'][0]['thumbnail']['name'];safe_file(self.db.data/'thumbnails',thumb)
     with self.db.transaction() as c:
      original=c.execute('SELECT payload FROM analyses WHERE photo_id=?',(p['id'],)).fetchone()
      if original and not c.execute('SELECT 1 FROM processing_history WHERE photo_id=? LIMIT 1',(p['id'],)).fetchone():
       c.execute('INSERT INTO processing_history(photo_id,created_at,job_id,source_sha,recipe,payload) VALUES(?,?,?,?,?,?)',(p['id'],now(),None,p['sha256'],encode({}),original['payload']))
      c.execute('INSERT INTO processing_history(photo_id,created_at,job_id,source_sha,recipe,payload) VALUES(?,?,?,?,?,?)',(p['id'],now(),id,before['sha256'],encode(row.get('adjustments',{})),encode(compact(row))))
      c.execute("UPDATE photos SET size=?,mtime_ns=?,sha256=?,pipeline=?,source_status='available',inference_status='ready',error=NULL,thumbnail=?,summary=? WHERE id=?",(before['size'],before['mtime_ns'],before['sha256'],self.cfg['pipeline_version'],thumb,encode(compact(row)),p['id']))
      c.execute('INSERT INTO analyses VALUES(?,?) ON CONFLICT(photo_id) DO UPDATE SET payload=excluded.payload',(p['id'],encode(row)));c.execute("UPDATE job_items SET state='done',error=NULL WHERE job_id=? AND photo_id=?",(id,p['id']));self.db.bump(c)
      c.execute('UPDATE adjustments SET preview=NULL WHERE photo_id=? AND revision=? AND source_sha=?',(p['id'],adjustment['revision'],before['sha256']))
    except Exception as exc:
     with self.db.transaction() as c:c.execute("UPDATE job_items SET state='error',error=? WHERE job_id=? AND photo_id=?",(str(exc),id,p['id']));c.execute("UPDATE photos SET inference_status='error',error=? WHERE id=?",(str(exc),p['id']));self.db.bump(c)
     if '源文件变化' in str(exc):self.action(id,'pause')
     if isinstance(exc,RuntimeError):raise
    with self.db.transaction() as c:c.execute('UPDATE jobs SET updated_at=? WHERE id=?',(now(),id))
  except Exception as exc:
   with self.db.transaction() as c:c.execute("UPDATE jobs SET state='failed',error=?,updated_at=? WHERE id=? AND state NOT IN ('paused','cancelled')",(str(exc),now(),id))
  finally:self.processor.close()
 def loop(self):
  while not self.stop.is_set():
   self.wake.clear()
   jobs=self.db.query("SELECT id FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1")
   if jobs:self.run_one(jobs[0]['id'])
   else:self.wake.wait()
