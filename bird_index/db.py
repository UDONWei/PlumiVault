from __future__ import annotations
import contextlib,sqlite3,uuid,json,hashlib
from pathlib import Path
from .common import now,encode,STATES

class Conflict(ValueError):pass
class Database:
 def __init__(self,data_dir):
  self.data=Path(data_dir);self.data.mkdir(parents=True,exist_ok=True);self.path=self.data/'index.sqlite3'
  for folder in ('thumbnails','backups','imports','runtime'): (self.data/folder).mkdir(exist_ok=True)
  with contextlib.closing(self.connect()) as c:
   if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone():
    schema=c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if schema and schema[0] not in ('1','2','3','4','5'):raise ValueError('数据库版本不兼容，拒绝修改')
   if self.path.exists() and c.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone():
    if schema and schema[0] in ('1','2','3','4'):self.backup()
   c.executescript('''
   PRAGMA journal_mode=WAL;
   CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS roots(id TEXT PRIMARY KEY,path TEXT NOT NULL,name TEXT NOT NULL,context TEXT NOT NULL,allow_paths TEXT);
   CREATE TABLE IF NOT EXISTS labels(id TEXT PRIMARY KEY,name TEXT NOT NULL,original_name TEXT,aliases TEXT NOT NULL,payload TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS photos(id INTEGER PRIMARY KEY,root_id TEXT NOT NULL REFERENCES roots(id),rel_path TEXT NOT NULL,display_path TEXT NOT NULL UNIQUE,size INTEGER,mtime_ns INTEGER,sha256 TEXT,pipeline TEXT,source_status TEXT NOT NULL DEFAULT 'available',inference_status TEXT NOT NULL DEFAULT 'pending',error TEXT,thumbnail TEXT,summary TEXT NOT NULL DEFAULT '{}',UNIQUE(root_id,rel_path));
   CREATE TABLE IF NOT EXISTS analyses(photo_id INTEGER PRIMARY KEY REFERENCES photos(id),payload TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS manual(photo_id INTEGER PRIMARY KEY REFERENCES photos(id),status TEXT NOT NULL DEFAULT 'unreviewed',species TEXT NOT NULL DEFAULT '[]',reviewed_sha TEXT,updated_at TEXT,revision INTEGER NOT NULL DEFAULT 0);
   CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,undone INTEGER NOT NULL DEFAULT 0);
   CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,root_id TEXT NOT NULL REFERENCES roots(id),scope TEXT NOT NULL,limit_count INTEGER NOT NULL,state TEXT NOT NULL,force INTEGER NOT NULL DEFAULT 0,found INTEGER NOT NULL DEFAULT 0,skipped INTEGER NOT NULL DEFAULT 0,error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,discovery_done INTEGER NOT NULL DEFAULT 0);
   CREATE TABLE IF NOT EXISTS job_items(job_id TEXT NOT NULL REFERENCES jobs(id),photo_id INTEGER NOT NULL REFERENCES photos(id),state TEXT NOT NULL,error TEXT,PRIMARY KEY(job_id,photo_id));
   CREATE TABLE IF NOT EXISTS folder_contexts(root_id TEXT NOT NULL REFERENCES roots(id),scope TEXT NOT NULL,context TEXT NOT NULL,PRIMARY KEY(root_id,scope));
   CREATE TABLE IF NOT EXISTS selections(photo_id INTEGER PRIMARY KEY REFERENCES photos(id),flag TEXT NOT NULL,rating INTEGER NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS visibility(photo_id INTEGER PRIMARY KEY REFERENCES photos(id),hidden INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS file_plans(id TEXT PRIMARY KEY,created REAL NOT NULL,state TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,result TEXT);
   CREATE TABLE IF NOT EXISTS file_moves(id TEXT PRIMARY KEY,photo_id INTEGER NOT NULL REFERENCES photos(id),source TEXT NOT NULL,destination TEXT NOT NULL,sha256 TEXT NOT NULL,state TEXT NOT NULL,updated_at TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS adjustments(photo_id INTEGER PRIMARY KEY REFERENCES photos(id),source_sha TEXT NOT NULL,recipe TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS processing_history(id INTEGER PRIMARY KEY,photo_id INTEGER NOT NULL REFERENCES photos(id),created_at TEXT NOT NULL,job_id TEXT,source_sha TEXT,recipe TEXT NOT NULL,payload TEXT NOT NULL);
   CREATE INDEX IF NOT EXISTS history_photo ON processing_history(photo_id,id);
   CREATE INDEX IF NOT EXISTS photo_root ON photos(root_id,rel_path);
   CREATE INDEX IF NOT EXISTS review_state ON manual(status);
   CREATE INDEX IF NOT EXISTS task_queue ON job_items(job_id,state);
   ''')
   if 'scopes' not in {r['name'] for r in c.execute('PRAGMA table_info(jobs)')}:
    c.execute('ALTER TABLE jobs ADD COLUMN scopes TEXT')
   if 'request' not in {r['name'] for r in c.execute('PRAGMA table_info(job_items)')}:
    c.execute('ALTER TABLE job_items ADD COLUMN request TEXT')
   if 'preview' not in {r['name'] for r in c.execute('PRAGMA table_info(adjustments)')}:c.execute('ALTER TABLE adjustments ADD COLUMN preview TEXT')
   c.execute("INSERT INTO meta VALUES('schema','5') ON CONFLICT(key) DO UPDATE SET value='5'")
   c.execute("INSERT OR IGNORE INTO meta VALUES('library_id',?)",(str(uuid.uuid4()),))
   c.execute("INSERT OR IGNORE INTO meta VALUES('generation','0')")
   c.execute("INSERT OR IGNORE INTO meta VALUES('view',?)",(encode({'gap':30,'foldSimilar':True,'grouping':True,'breaks':[],'keep':[],'covers':[]}),))
   c.commit()
 def connect(self):
  c=sqlite3.connect(self.path,timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=15000');return c
 @contextlib.contextmanager
 def transaction(self):
  c=self.connect()
  try:c.execute('BEGIN IMMEDIATE');yield c;c.commit()
  except BaseException:c.rollback();raise
  finally:c.close()
 def query(self,sql,args=()):
  with contextlib.closing(self.connect()) as c:return [dict(r) for r in c.execute(sql,args)]
 def meta(self,key):
  rows=self.query('SELECT value FROM meta WHERE key=?',(key,));return rows[0]['value'] if rows else None
 @staticmethod
 def bump(c):c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
 def configure(self,cfg):
  with self.transaction() as c:
   for root in cfg['roots']:
    old=c.execute('SELECT * FROM roots WHERE id=?',(root['id'],)).fetchone()
    if old and old['path']!=root['path']:raise ValueError('目录路径改变需要显式迁移，不能静默重连')
    c.execute('INSERT INTO roots VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,allow_paths=excluded.allow_paths',(root['id'],root['path'],root.get('name',Path(root['path']).name),encode(root.get('context',{})),encode(root.get('allow_paths')) if root.get('allow_paths') is not None else None))
 def labels(self):return [json.loads(r['payload']) for r in self.query('SELECT payload FROM labels ORDER BY rowid')]
 @staticmethod
 def record(row):
  return {'photo_id':row['photo_id'],'status':row['status'],'species':json.loads(row['species']),'reviewed_sha':row['reviewed_sha'],'updated_at':row['updated_at'],'revision':row['revision']}
 def validate_record(self,status,species):
  if status not in STATES or not isinstance(species,list) or len(species)>20 or len(set(species))!=len(species):raise ValueError('人工状态或物种无效')
  if (status=='confirmed')!=bool(species):raise ValueError('确认状态与物种列表不一致')
  known={r['id'] for r in self.query('SELECT id FROM labels')}
  if any(s not in known for s in species):raise ValueError('鸟种不在当前名录中')
 def review(self,items,status,species,only_unreviewed=False):
  self.validate_record(status,species)
  if not isinstance(items,list) or not 1<=len(items)<=5000 or len({i['id'] for i in items})!=len(items):raise ValueError('照片选择无效')
  before=[];after=[]
  with self.transaction() as c:
   for item in items:
    row=c.execute('SELECT m.*,p.sha256 FROM manual m JOIN photos p ON p.id=m.photo_id WHERE photo_id=?',(item['id'],)).fetchone()
    if row is None:raise ValueError('照片不存在')
    if row['revision']!=item['revision']:raise Conflict('记录已被另一页面修改，请刷新后再操作')
    if only_unreviewed and row['status']!='unreviewed':continue
    before.append(self.record(row));changed={**before[-1],'status':status,'species':species,'reviewed_sha':row['sha256'],'updated_at':now(),'revision':row['revision']+1};after.append(changed)
    c.execute('UPDATE manual SET status=?,species=?,reviewed_sha=?,updated_at=?,revision=? WHERE photo_id=?',(status,encode(species),changed['reviewed_sha'],changed['updated_at'],changed['revision'],item['id']))
   if not before:raise ValueError('所选照片没有可确认的未复核成员')
   change=c.execute('INSERT INTO changes(created_at,before_json,after_json) VALUES(?,?,?)',(now(),encode(before),encode(after))).lastrowid;self.bump(c)
  return {'change_id':change,'records':after,'count':len(after)}
 def undo(self,change_id):
  with self.transaction() as c:
   item=c.execute('SELECT * FROM changes WHERE id=?',(change_id,)).fetchone()
   if not item or item['undone']:raise ValueError('此操作已撤销或不存在')
   before=json.loads(item['before_json']);after=json.loads(item['after_json']);result=[]
   for old,new in zip(before,after):
    row=c.execute('SELECT * FROM manual WHERE photo_id=?',(old['photo_id'],)).fetchone()
    current=self.record(row)
    if {k:v for k,v in current.items() if k!='revision'}!={k:v for k,v in new.items() if k!='revision'}:raise Conflict('照片已有后续修改，不能覆盖新判断')
   for old,new in zip(before,after):
    current_revision=c.execute('SELECT revision FROM manual WHERE photo_id=?',(old['photo_id'],)).fetchone()[0]
    restored={**old,'revision':current_revision+1};result.append(restored)
    c.execute('UPDATE manual SET status=?,species=?,reviewed_sha=?,updated_at=?,revision=? WHERE photo_id=?',(old['status'],encode(old['species']),old['reviewed_sha'],old['updated_at'],restored['revision'],old['photo_id']))
   c.execute('UPDATE changes SET undone=1 WHERE id=?',(change_id,));self.bump(c)
  return {'count':len(result),'records':result}
 def backup(self):
  target=self.data/'backups'/('index-'+now().replace(':','').replace('.','')+'-'+uuid.uuid4().hex[:6]+'.sqlite3')
  with contextlib.closing(self.connect()) as source,contextlib.closing(sqlite3.connect(target)) as dest:source.backup(dest)
  return target
 def recover(self):
  with self.transaction() as c:
   c.execute("UPDATE job_items SET state='pending' WHERE state='running'")
   c.execute("UPDATE jobs SET state='paused',error='程序重启，等待手动继续',updated_at=? WHERE state IN ('queued','discovering','running')",(now(),))
