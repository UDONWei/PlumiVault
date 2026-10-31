from __future__ import annotations
import argparse,contextlib,json,os,secrets,signal,sqlite3,sys,threading,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .common import load_config,encode,read_json,safe_file,ProcessLock,PROJECT
from .db import Database,Conflict
from .library import Library
from .jobs import Jobs
from . import folders
from .search import locations
from .preview import render as render_original,PreviewBusy

class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,lib,jobs,public_origin=None,gateway_token=None):
  from .scan_plan import ScanPlans
  self.scan_plans=ScanPlans(jobs)
  self.public_origin=public_origin;self.gateway_token=gateway_token;self.lib=lib;self.jobs=jobs;self.token=secrets.token_urlsafe(32);self.pending_imports={};self.import_lock=threading.Lock();super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def setup(self):
  super().setup();self.connection.settimeout(15)
 def log_message(self,*args):pass
 def allowed(self,write=False):
  hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
  origins={'http://'+h for h in hosts}
  if self.server.public_origin:hosts.add(urllib.parse.urlsplit(self.server.public_origin).netloc);origins.add(self.server.public_origin)
  if self.server.gateway_token and not secrets.compare_digest(self.headers.get('X-Bird-Gateway',''),self.server.gateway_token):return False
  if self.headers.get('Host') not in hosts:return False
  if self.headers.get('Sec-Fetch-Site') in ('cross-site',):return False
  origin=self.headers.get('Origin')
  if origin and origin not in origins:return False
  return not write or secrets.compare_digest(self.headers.get('X-Bird-Token',''),self.server.token)
 def send(self,status,body,kind='application/json; charset=utf-8',download=None,headers=None,cache_control='no-store'):
  if not isinstance(body,bytes):body=encode(body).encode('utf-8')
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control',cache_control);self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
  for key,value in (headers or {}).items():self.send_header(key,value)
  if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
  self.end_headers()
  if self.command!='HEAD':self.wfile.write(body)
 def do_GET(self):
  if self.path=='/health' and self.client_address[0] in ('127.0.0.1','::1'):return self.send(200,{'status':'ok'})
  if not self.allowed():self.send(403,{'error':'仅允许本机同源访问'});return
  try:
   parsed=urllib.parse.urlsplit(self.path);path=urllib.parse.unquote(parsed.path);q={k:v[-1] for k,v in urllib.parse.parse_qs(parsed.query).items()};lib=self.server.lib
   if path=='/':return self.send(200,(PROJECT/'web/index.html').read_bytes(),'text/html; charset=utf-8')
   if path in ('/app.js','/app.css','/editor.js','/preview-cache.js','/display-preview.js','/editor-math.js','/search.js','/studio.js','/studio-strip.js','/studio-zoom.js','/validation.js','/studio.css','/progress.js'):
    return self.send(200,(PROJECT/'web'/path[1:]).read_bytes(),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
   if path.startswith('/thumbs/'):
    name=path.removeprefix('/thumbs/')
    if '/' in name or not name.endswith('.jpg'):raise ValueError('缩略图地址无效')
    return self.send(200,safe_file(lib.db.data/'thumbnails',name).read_bytes(),'image/jpeg',cache_control='private, max-age=86400, immutable')
   if path.startswith('/backups/'):
    name=path.removeprefix('/backups/')
    if '/' in name or not name.endswith('.sqlite3'):raise ValueError('备份地址无效')
    return self.send(200,safe_file(lib.db.data/'backups',name).read_bytes(),'application/vnd.sqlite3',name)
   if path=='/api/state':return self.send(200,{'token':self.server.token,**lib.summary()})
   if path=='/api/validation':
    from .validation import read
    return self.send(200,read(lib))
   if path=='/api/export/validation':
    from .validation import export
    return self.send(200,export(lib),download='plumivault-quality-validation.json')
   if path=='/api/labels':return self.send(200,{'items':list(lib.labels().values())})
   if path=='/api/folders':return self.send(200,folders.listing(lib,q['root'],q.get('parent',''),q.get('offset',0),q.get('sort','date_desc')))
   if path=='/api/library-folders':return self.send(200,{'items':folders.catalog(lib)})
   if path=='/api/folder-context':
    root=lib.root(q['root']);scope=q.get('scope','');folders.directory(root['path'],scope);return self.send(200,{'context':lib.effective_context(q['root'],scope+'/__context__' if scope else '__context__')})
   if path=='/api/locations':return self.send(200,locations(lib))
   if path in ('/api/display-preview','/api/display-image'):
    from . import display_preview
    args=(lib,int(q['id']),q['sha'],int(q['revision']))
    if path=='/api/display-preview':return self.send(200,display_preview.status(*args))
    pixels=display_preview.read(*args,q['key'],q['mode'])
    if pixels is None:return self.send(404,{'error':'高清缓存尚未生成或已淘汰，请补生成'})
    return self.send(200,pixels,'image/jpeg')
   if path=='/api/preview-version':return self.send(200,lib.preview_version(int(q['id'])))
   if path=='/api/editor':return self.send(200,lib.editor(int(q['id'])))
   if path=='/api/library':return self.send(200,lib.listing(q))
   if path=='/api/photos':
    ids=[int(x) for x in q.get('ids','').split(',') if x]
    if len(ids)>100:raise ValueError('单次最多读取 100 张详情')
    return self.send(200,{'items':[lib.public(p) for p in lib.items(ids)]})
   if path=='/api/queue':
    labels=lib.labels();ids=[p['id'] for p in lib.items() if lib.match(p,q,labels) and (p['manual']['status'] not in ('confirmed','no_bird') or p['manual']['stale'])];return self.send(200,{'ids':ids})
   if path=='/api/acceptance':
    from .selection import acceptance_report
    return self.send(200,acceptance_report(lib.db,q.get('job')),download='nas-acceptance.json')
   if path=='/api/curation-status':
    from .organizer_client import call
    return self.send(200,call('status',{}))
   if path=='/api/jobs':return self.send(200,{'items':self.server.jobs.list()})
   if path=='/api/export/review':return self.send(200,lib.export_reviews(),download='plumivault-review.json')
   if path=='/api/export/csv':return self.send(200,lib.export_csv(q),'text/csv; charset=utf-8','plumivault.csv')
   self.send(404,{'error':'地址不存在'})
  except (ValueError,KeyError,TypeError,OSError) as exc:self.send(400,{'error':str(exc)})
  except Exception as exc:self.send(500,{'error':'读取失败：'+str(exc)})
 def do_POST(self):
  if not self.allowed(True):
   # Drain small denied bodies before closing so Windows can deliver the 403.
   try:
    size=int(self.headers.get('Content-Length','0'))
    if 0<size<=65536:self.rfile.read(size)
   except (ValueError,OSError):pass
   self.close_connection=True;self.send(403,{'error':'操作来源或会话校验失败，请在本机页面操作'});return
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=8*1024**2 or self.headers.get('Transfer-Encoding'):self.close_connection=True;raise ValueError('请求大小无效或超出 8 MiB')
   value=json.loads(self.rfile.read(size),parse_constant=lambda s:(_ for _ in ()).throw(ValueError('不允许非有限数值')));path=urllib.parse.urlsplit(self.path).path;lib=self.server.lib
   if path=='/api/validation':
    from .validation import change
    result=change(lib,value)
   elif path=='/api/review':result=lib.db.review(value['items'],value['status'],value['species'],value.get('only_unreviewed',False))
   elif path=='/api/selection':
    from .selection import set_selection
    result=set_selection(lib.db,value['items'],value['flag'],value['rating'])
   elif path=='/api/visibility':
    from .visibility import set_visibility
    result=set_visibility(lib.db,value['items'],value['hidden'])
   elif path=='/api/quality':
    from .quality import score_existing
    result=score_existing(lib,value['photo_id'],value['source_sha'])
   elif path in ('/api/curation-plan','/api/curation-commit'):
    from .organizer_client import call
    if not lib.image_lock.acquire(blocking=False):raise PreviewBusy('正在读取原图，请稍后整理')
    try:result=call('plan' if path.endswith('-plan') else 'commit',value)
    finally:lib.image_lock.release()
   elif path=='/api/undo':result=lib.db.undo(int(value['change_id']))
   elif path=='/api/display-preview':
    from .display_preview import generate
    result=generate(lib,value['photo_id'],value['source_sha'],value['revision'])
   elif path=='/api/original':
    metadata,pixels=render_original(lib,value['photo_id'],value.get('resolution','screen'),value['source_sha'])
    return self.send(200,pixels,'image/jpeg',headers={'X-Source-Width':str(metadata['source_size'][0]),'X-Source-Height':str(metadata['source_size'][1]),'X-Source-SHA256':metadata['sha256']})
   elif path=='/api/adjustments':result=lib.save_adjustment(value['photo_id'],value['source_sha'],value['revision'],value['recipe'],value.get('preview'))
   elif path=='/api/reprocess':result=self.server.jobs.reprocess(value['photo_id'],value['source_sha'],value['revision'])
   elif path=='/api/view':result=lib.preferences(value)
   elif path=='/api/context':result=lib.context(value['root_id'],value['context'],value.get('scope',''))
   elif path=='/api/scan-preview':result=self.server.scan_plans.preview(value['root_id'],value['scopes'],value.get('limit'))
   elif path=='/api/scan-confirm':result=self.server.scan_plans.commit(value['preview_token'],value['paths'])
   elif path=='/api/jobs':
    if lib.cfg.get('require_folder_selection'):raise ValueError('请先检查目录变更，再确认处理清单')
    result=self.server.jobs.create(value['root_id'],value.get('scope',''),value.get('limit'),value.get('force',False),value.get('scopes'))
   elif path=='/api/job-action':result=self.server.jobs.action(value['id'],value['action'])
   elif path=='/api/shutdown':
    result={'stopping':True};threading.Thread(target=self.server.shutdown,daemon=True).start()
   elif path=='/api/backup':
    backup=lib.db.backup();result={'name':backup.name,'url':'/backups/'+backup.name}
   elif path=='/api/import-preview':
    result=lib.import_reviews(value);token=secrets.token_urlsafe(24)
    with self.server.import_lock:
     if len(self.server.pending_imports)>8:self.server.pending_imports.clear()
     self.server.pending_imports[token]={'doc':value,'generation':lib.db.meta('generation')}
    result['preview_token']=token
   elif path=='/api/import-apply':
    with self.server.import_lock:pending=self.server.pending_imports.pop(value['preview_token'],None)
    if not pending:raise ValueError('导入预览已过期，请重新选择文件')
    if pending['generation']!=lib.db.meta('generation'):raise Conflict('预览后图库已有变化，请重新预览再应用')
    result=lib.import_reviews(pending['doc'],True,pending['generation'])
   else:self.send(404,{'error':'操作不存在'});return
   self.send(200,result)
  except PreviewBusy as exc:self.send(503,{'error':str(exc)})
  except Conflict as exc:self.send(409,{'error':str(exc)})
  except (ValueError,KeyError,TypeError,OSError) as exc:self.send(400,{'error':str(exc)})
  except Exception as exc:self.send(500,{'error':'保存失败，未确认的操作请重试：'+str(exc)})
 def do_OPTIONS(self):self.send(403,{'error':'不允许跨站访问'})

def serve(config,port=8765):
 from .migration import initialize_catalog
 cfg=load_config(config);db=Database(cfg['data_dir']);host=os.environ.get('BIRD_LISTEN_HOST','127.0.0.1');origin=os.environ.get('BIRD_PUBLIC_ORIGIN');gateway=None
 if host not in ('127.0.0.1','localhost'):
  parsed=urllib.parse.urlsplit(origin or '')
  if parsed.scheme!='https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:raise ValueError('网络监听需要明确的 HTTPS 入口地址')
  gateway=Path(os.environ['BIRD_GATEWAY_TOKEN_FILE']).read_text(encoding='utf-8').strip()
  if len(gateway)<32:raise ValueError('网关密钥至少 32 字符')
 with ProcessLock(db.data/'server.lock'):
  db.configure(cfg);initialize_catalog(db,cfg);db.recover();lib=Library(db,cfg);jobs=Jobs(lib);server=Server((host,port),lib,jobs,origin,gateway)
  marker=db.data/'runtime/server.json';marker.write_text(encode({'pid':os.getpid(),'port':server.server_port,'library_id':db.meta('library_id')}),encoding='utf-8');jobs.start()
  print(encode({'url':f'http://127.0.0.1:{server.server_port}','data_dir':cfg['data_dir'],'scope':'本机原型；无自动扫描，等待用户启动任务'}),flush=True)
  signal.signal(signal.SIGTERM,lambda *_:threading.Thread(target=server.shutdown,daemon=True).start())
  try:server.serve_forever(poll_interval=.3)
  except KeyboardInterrupt:pass
  finally:
   server.server_close();jobs.close()
   if marker.exists() and read_json(marker).get('pid')==os.getpid():marker.unlink()

def restore(config,source):
 cfg=load_config(config);db=Database(cfg['data_dir']);source=Path(source).resolve(strict=True)
 if source==db.path.resolve():raise ValueError('恢复来源不能是正在使用的数据库')
 with ProcessLock(db.data/'server.lock'),contextlib.closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as saved:
  if saved.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库校验失败')
  if saved.execute("SELECT value FROM meta WHERE key='library_id'").fetchone()[0]!=db.meta('library_id'):raise ValueError('备份不属于本图库')
  if saved.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] not in ('1','2','3','4','5'):raise ValueError('备份版本不兼容')
  if db.query("SELECT id FROM file_moves WHERE state='moved' LIMIT 1") or db.query("SELECT id FROM file_plans WHERE state='executing' LIMIT 1"):raise ValueError('存在已暂存或未完成整理的原片；请先按当前日志恢复原片，再恢复数据库')
  safety=db.backup()
  with contextlib.closing(db.connect()) as target:saved.backup(target)
  db=Database(cfg['data_dir']);db.configure(cfg);db.recover();return {'restored':str(source),'previous_backup':str(safety)}

def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['serve','backup','restore','init','evaluate']);p.add_argument('--config',default=str(PROJECT/'config.local.json'));p.add_argument('--port',type=int,default=8765);p.add_argument('--from-file');p.add_argument('--page');p.add_argument('--review');p.add_argument('--output');a=p.parse_args()
 if a.command=='serve':serve(a.config,a.port)
 elif a.command=='backup':print(Database(load_config(a.config)['data_dir']).backup())
 elif a.command=='restore':
  if not a.from_file:p.error('restore 需要 --from-file')
  print(encode(restore(a.config,a.from_file)))
 elif a.command=='init':
  if not a.page or not a.review:p.error('init 需要 --page 与 --review')
  from .migration import bootstrap
  cfg=load_config(a.config);db=Database(cfg['data_dir'])
  with ProcessLock(db.data/'server.lock'):
   db.configure(cfg);print(encode(bootstrap(db,cfg,a.page,a.review)))
 else:
  if not a.page or not a.review or not a.output:p.error('evaluate 需要 --page、--review 与 --output')
  from .migration import evaluate
  print(encode(evaluate(a.page,a.review,a.output)))
if __name__=='__main__':main()
