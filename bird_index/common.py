from __future__ import annotations
import contextlib,hashlib,json,os,re,sqlite3,sys,time,uuid
from pathlib import Path
from datetime import datetime,timezone

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'tools'))
FORMATS={'.arw','.jpg','.jpeg','.png','.tif','.tiff','.webp','.bmp'}
STATES={'unreviewed','confirmed','uncertain','none_match','no_bird'}
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def encode(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def disjoint(*paths):
 paths=[Path(p).resolve() for p in paths]
 for i,a in enumerate(paths):
  for b in paths[i+1:]:
   if a.is_relative_to(b) or b.is_relative_to(a):raise ValueError(f'目录必须互相独立：{a} / {b}')
def relative(value,empty=False):
 if not isinstance(value,str) or '\x00' in value or '\\' in value:raise ValueError('路径须使用 / 分隔')
 if value=='' and empty:return ''
 if not value or value.startswith('/') or ':' in value or any(p in {'','..','.'} for p in value.split('/')):raise ValueError('相对路径无效')
 return value
def safe_file(root,rel,existing=True):
 relative(rel);root=Path(root).resolve();path=(root/rel).resolve(strict=existing)
 if not path.is_relative_to(root) or (existing and not path.is_file()):raise ValueError('文件越界或不存在')
 return path
def load_config(path):
 cfg=read_json(path);cfg['_path']=str(Path(path).resolve());cfg['_project']=str(PROJECT)
 base=Path(cfg['_path']).parent
 def resolve(value):return str((base/Path(value)).resolve())
 for key in ('data_dir','model_dir','labels_path','priors_path','text_features','detector_config','taxonomy_snapshot'):
  if cfg.get(key):cfg[key]=resolve(cfg[key])
 if not cfg.get('roots'):raise ValueError('必须显式配置照片目录')
 ids=set()
 for root in cfg['roots']:
  if not re.fullmatch('[a-zA-Z0-9_-]{1,40}',root['id']) or root['id'] in ids:raise ValueError('目录编号无效或重复')
  ids.add(root['id']);root['path']=resolve(root['path'])
  if root.get('allow_paths') is not None:
   for r in root['allow_paths']:relative(r)
  disjoint(root['path'],cfg['data_dir'],cfg['model_dir'])
  if PROJECT.is_relative_to(Path(root['path'])) or Path(root['path']).is_relative_to(PROJECT):raise ValueError('程序目录与照片目录不能嵌套')
 for i,r in enumerate(cfg['roots']):
  for other in cfg['roots'][i+1:]:disjoint(r['path'],other['path'])
 for key,default,low,high in [('threads',2,1,8),('thumbnail_edge',512,64,512),('thumbnail_budget_mb',1024,1,4096),('max_files_per_job',500,0,9223372036854775807),('stable_seconds',60,0,3600)]:
  value=cfg.setdefault(key,default)
  if type(value)!=int or not low<=value<=high:raise ValueError('配置数值无效：'+key)
 signature=[digest(Path(cfg['model_dir'])/'model.json'),digest(cfg['labels_path']),digest(cfg['detector_config']),str(cfg['thumbnail_edge'])]
 cfg['pipeline_version']='subject-v1-'+hashlib.sha256(encode(signature).encode()).hexdigest()[:20]
 return cfg

class ProcessLock:
 def __init__(self,path):self.path=Path(path);self.file=None
 def __enter__(self):
  self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b');self.file.seek(0)
  if self.path.stat().st_size==0:self.file.write(b'0');self.file.flush();self.file.seek(0)
  try:
   if os.name=='nt':
    import msvcrt;msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl;fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError:self.file.close();raise RuntimeError('同一数据目录已有程序运行，请先停止')
  return self
 def __exit__(self,*exc):
  if self.file:
   self.file.seek(0)
   if os.name=='nt':
    import msvcrt;msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
   else:
    import fcntl;fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
   self.file.close()
