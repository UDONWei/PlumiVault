"""Opt-in original mover. No delete, copy, overwrite or automatic collection.

Run only in the optional organizer container, never grant the index write access.
Every execution is journaled before rename; retries reconcile the same operation.
"""
import contextlib,ctypes,json,os,secrets,stat,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .common import digest,encode,now,relative,ProcessLock
from .db import Database,Conflict

def strict_path(root,rel,create_parents=False):
 root=Path(root).absolute();relative(rel)
 # Check the root and all ancestors too (including Windows reparse points).
 for p in [*reversed(root.parents),root]:
  st=p.lstat()
  if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:raise ValueError('不允许符号链接或重解析目录')
 p=root
 for part in Path(rel).parts:
  p=p/part
  if not p.exists() and not p.is_symlink():
   if create_parents and p!=root/rel:p.mkdir()
   else:continue
  st=p.lstat()
  if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:raise ValueError('不允许符号链接或重解析路径')
 if not p.resolve(strict=False).is_relative_to(root.resolve()):raise ValueError('路径越界')
 return p

@contextlib.contextmanager
def parent_fd(path):
 fd=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY)
 try:
  for part in path.parent.parts[1:]:
   child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=child
  yield fd
 finally:os.close(fd)

def rename_no_replace(source,destination):
 if source.stat().st_dev!=destination.parent.stat().st_dev:raise ValueError('跨文件系统移动被拒绝；不会复制原片')
 if os.name=='nt':os.rename(source,destination);return
 libc=ctypes.CDLL(None,use_errno=True);rename=getattr(libc,'renameat2',None)
 if rename is None:raise ValueError('系统不支持安全的无覆盖移动')
 rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];rename.restype=ctypes.c_int
 with parent_fd(source) as src, parent_fd(destination) as dst:
  if rename(src,os.fsencode(source.name),dst,os.fsencode(destination.name),1)!=0:
   code=ctypes.get_errno();raise OSError(code,os.strerror(code))
  os.fsync(src);os.fsync(dst)

class Organizer:
 def __init__(self,db,config):self.db=db;self.cfg=config;self.lock=threading.Lock()
 def check(self):
  if self.cfg.get('enabled') is not True:raise ValueError('原片整理未启用')
  allowed=self.cfg.get('allowed_photo_ids',[])
  mode=self.cfg.get('scope','allowlist')
  if mode not in ('allowlist','indexed_root'):raise ValueError('整理授权范围无效')
  if mode=='allowlist' and (not allowed or any(type(x)!=int or x<1 for x in allowed)):raise ValueError('尚未配置允许整理的照片编号')
  strict_path(Path(self.cfg['photo_root']),'__boundary_check__');strict_path(Path(self.cfg['quarantine_root']),'__boundary_check__')
  source=Path(self.cfg['photo_root']).resolve(strict=True);dest=Path(self.cfg['quarantine_root']).resolve(strict=True)
  if source==dest or source.is_relative_to(dest) or dest.is_relative_to(source):raise ValueError('原片和待删除目录必须分离')
  return source,dest
 def photo(self,c,pid):
  if type(pid)!=int or pid<1:raise ValueError('照片编号无效')
  if self.cfg.get('scope','allowlist')!='indexed_root' and pid not in self.cfg['allowed_photo_ids']:raise ValueError('照片超出本轮授权清单')
  p=c.execute('SELECT p.*,s.flag,s.revision AS selection_revision FROM photos p LEFT JOIN selections s ON s.photo_id=p.id WHERE p.id=?',(pid,)).fetchone()
  if not p or p['root_id']!=self.cfg['root_id'] or not p['sha256']:raise ValueError('照片根目录或指纹无效')
  root=c.execute('SELECT path,allow_paths FROM roots WHERE id=?',(p['root_id'],)).fetchone()
  if Path(root['path'])!=Path(self.cfg.get('index_photo_root',self.cfg['photo_root'])):raise ValueError('根目录映射不一致')
  if root['allow_paths'] and p['rel_path'] not in json.loads(root['allow_paths']):raise ValueError('照片不在原授权路径清单')
  return p
 @staticmethod
 def idle(c):
  if c.execute("SELECT 1 FROM jobs WHERE state IN ('queued','discovering','running','paused') LIMIT 1").fetchone():raise ValueError('请先完成或取消扫描任务，再整理原片')
  if c.execute("SELECT 1 FROM job_items WHERE state='running' LIMIT 1").fetchone():raise ValueError('当前照片尚未处理结束，请等待后再整理原片')
 def plan(self,ids,action):
  source,dest=self.check()
  maximum=self.batch_limit()
  if action not in ('move','restore') or not isinstance(ids,list) or not 1<=len(ids)<=maximum or any(type(pid)!=int or pid<1 for pid in ids) or len(set(ids))!=len(ids):raise ValueError('请明确勾选 1～'+str(maximum)+' 张现有照片')
  plan_id=uuid.uuid4().hex;items=[]
  with self.db.transaction() as c:
   self.idle(c)
   if c.execute("SELECT 1 FROM file_plans WHERE state='executing'").fetchone():raise Conflict('有未完成的整理，请先恢复该操作')
   for pid in ids:
    p=self.photo(c,pid)
    if action=='move':
     if p['source_status']!='available' or p['flag']!='reject':raise ValueError('只有明确标记待剔除且原片可用的照片才能移走')
     item={'id':uuid.uuid4().hex,'photo_id':pid,'source':p['rel_path'],'destination':p['rel_path'],'sha256':p['sha256'],'revision':p['selection_revision']}
     if strict_path(dest,item['destination']).exists():raise Conflict('待删除目录已有同名文件，未移动；请先核对或恢复已有文件')
     original=strict_path(source,item['source'])
     if not original.is_file() or original.stat().st_size!=p['size'] or original.stat().st_mtime_ns!=p['mtime_ns']:raise Conflict('原片元数据已变化，请重新核对')
    else:
     moves=c.execute("SELECT * FROM file_moves WHERE photo_id=? AND state='moved' ORDER BY updated_at DESC LIMIT 1",(pid,)).fetchone()
     if p['source_status']!='quarantined' or not moves:raise ValueError('没有可恢复的暂存记录')
     item=dict(moves)
     if strict_path(source,item['source']).exists():raise ValueError('原路径已存在文件，不会覆盖')
     if not strict_path(dest,item['destination']).is_file():raise ValueError('暂存原片不可用')
    items.append(item)
   c.execute('INSERT INTO file_plans VALUES(?,?,?,?,?,NULL)',(plan_id,time.time(),'planned',action,encode(items)))
  return {'plan_id':plan_id,'action':action,'items':items,'destination_display':self.cfg.get('display_destination','/volume1/照片/待删除'),'expires_seconds':600}
 def batch_limit(self):
  value=self.cfg.get('max_batch',10);maximum=100 if self.cfg.get('scope')=='indexed_root' else 10
  if type(value)!=int or not 1<=value<=maximum:raise ValueError('整理批次数量配置无效')
  return value
 def status(self):
  count=self.db.query('SELECT count(*) n FROM photos WHERE root_id=?',(self.cfg['root_id'],))[0]['n'] if self.cfg.get('scope')=='indexed_root' else len(self.cfg.get('allowed_photo_ids',[]))
  return {'enabled':self.cfg.get('enabled',False),'scope':self.cfg.get('scope','allowlist'),'max_batch':self.batch_limit(),'allowed_count':count,'pending':self.db.query("SELECT id,action,state FROM file_plans WHERE state='executing'"),'destination':'/volume1/照片/待删除'}
 def commit(self,plan_id):
  source,dest=self.check()
  with self.lock,ProcessLock(self.db.data/'curation.lock'):
   with self.db.transaction() as c:
    row=c.execute('SELECT * FROM file_plans WHERE id=?',(plan_id,)).fetchone()
    if not row:raise ValueError('预览不存在')
    if row['state']=='done':return json.loads(row['result'])
    if row['state']=='planned' and time.time()-row['created']>600:raise ValueError('预览已过期，请重新预览')
    self.idle(c)
    if c.execute("SELECT 1 FROM file_plans WHERE state='executing' AND id!=?",(plan_id,)).fetchone():raise Conflict('请先恢复其他未完成整理操作')
    items=json.loads(row['payload']);action=row['action']
    for item in items:
     photo=self.photo(c,item['photo_id'])
     if row['state']=='planned':
      if action=='move' and photo['source_status']!='available':raise Conflict('预览后原片位置已改变，请重新预览')
      if action=='restore':
       move=c.execute('SELECT state FROM file_moves WHERE id=?',(item['id'],)).fetchone()
       if photo['source_status']!='quarantined' or not move or move['state']!='moved':raise Conflict('预览后恢复记录已改变，请重新预览')
    c.execute("UPDATE file_plans SET state='executing' WHERE id=?",(plan_id,))
   results=[]
   for item in items:
    try:
     with self.db.transaction() as c:
      self.idle(c);p=self.photo(c,item['photo_id'])
      if action=='move' and (p['flag']!='reject' or p['selection_revision']!=item['revision']):raise Conflict('预览后标记已改变，请重新预览')
      if p['sha256']!=item['sha256']:raise Conflict('照片指纹版本已改变')
      srcroot,srcrel,dstroot,dstrel=(source,item['source'],dest,item['destination']) if action=='move' else (dest,item['destination'],source,item['source'])
      src=strict_path(srcroot,srcrel);dst=strict_path(dstroot,dstrel,True)
      # Reconcile interruption after rename but before SQLite commit.
      if not src.exists() and dst.is_file() and digest(dst)==item['sha256']:pass
      else:
       if not src.is_file() or dst.exists():raise ValueError('源文件缺失或目标已存在，未覆盖任何文件')
       before=src.stat()
       if digest(src)!=item['sha256'] or tuple(getattr(src.stat(),k) for k in ('st_size','st_mtime_ns','st_ino','st_dev'))!=tuple(getattr(before,k) for k in ('st_size','st_mtime_ns','st_ino','st_dev')):raise Conflict('原片已变化，拒绝移动')
       rename_no_replace(src,dst)
       if digest(dst)!=item['sha256']:raise Conflict('移动后指纹异常，保留日志待核对')
      moved='moved' if action=='move' else 'restored'
      c.execute('INSERT INTO file_moves VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at',(item['id'],item['photo_id'],item['source'],item['destination'],item['sha256'],moved,now()))
      c.execute('UPDATE photos SET source_status=? WHERE id=?',('quarantined' if action=='move' else 'available',item['photo_id']));self.db.bump(c)
     results.append({'photo_id':item['photo_id'],'ok':True,'state':moved})
    except Exception as exc:results.append({'photo_id':item['photo_id'],'ok':False,'error':str(exc)})
   # If files moved but DB commit failed, retain executing state for explicit recovery.
   unresolved=False
   for item,r in zip(items,results):
    if not r['ok']:
     srcroot,srcrel,dstroot,dstrel=(source,item['source'],dest,item['destination']) if action=='move' else (dest,item['destination'],source,item['source'])
     if not strict_path(srcroot,srcrel).exists() and strict_path(dstroot,dstrel).exists():unresolved=True
   result={'plan_id':plan_id,'action':action,'results':results,'needs_recovery':unresolved}
   with self.db.transaction() as c:c.execute('UPDATE file_plans SET state=?,result=? WHERE id=?',('executing' if unresolved else 'done',encode(result),plan_id))
   return result

def main():
 cfg=json.loads(Path('/config/curation.json').read_text(encoding='utf-8'));token=Path('/run/secrets/gateway_token').read_text().strip();organizer=Organizer(Database('/data'),cfg)
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   self.connection.settimeout(10);code=200
   try:
    if len(token)<32 or not secrets.compare_digest(self.headers.get('X-Bird-Organizer',''),token):raise ValueError('整理服务校验失败')
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=65536:raise ValueError('请求大小无效')
    data=json.loads(self.rfile.read(size));method=self.path
    if method=='/plan':result=organizer.plan(data['ids'],data['action'])
    elif method=='/commit':result=organizer.commit(data['plan_id'])
    elif method=='/status':result=organizer.status()
    else:raise ValueError('操作不存在')
   except Exception as exc:code=400;result={'error':str(exc)}
   body=encode(result).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 ThreadingHTTPServer(('0.0.0.0',8766),Handler).serve_forever()
if __name__=='__main__':main()
