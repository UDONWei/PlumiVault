"""原型核心验收；只在临时夹具写测试图片，不触碰真实原图。"""
import contextlib,copy,hashlib,json,os,sqlite3,subprocess,sys,tempfile,threading,time,unittest,urllib.request,urllib.error
import os, shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bird_index.common import PROJECT,load_config,encode,safe_file,digest,ProcessLock
from bird_index.db import Database,Conflict
from bird_index.library import Library
from bird_index.jobs import Jobs
from bird_index.server import Server,restore
from bird_index.migration import compact,validate_legacy,initialize_catalog
from stage1_probe import fingerprint

LABELS=[{'kind':'bird','scientific_name':'Bird alpha','zh_name':'甲鸟','english_name':'Alpha','aliases':['旧甲'],'prompt':'Alpha','birdreport_status':'exact_scientific_name'},{'kind':'bird','scientific_name':'Bird beta','zh_name':'乙鸟','english_name':'Beta','aliases':[],'prompt':'Beta','birdreport_status':'unmatched'}]
class Fixture:
 def __init__(self):
  self.temp=tempfile.TemporaryDirectory(prefix='bird-index-test-',dir=os.environ.get('BIRD_TEST_TEMP'));self.base=Path(self.temp.name);self.root=self.base/'photos';self.root.mkdir();self.models=self.base/'models';self.models.mkdir();self.data=self.base/'data'
  (self.models/'model.json').write_text('{}');(self.models/'labels.json').write_text(encode({'labels':LABELS}));(self.models/'detector.json').write_text('{}')
  self.config=self.base/'config.json';self.config.write_text(encode({'data_dir':str(self.data),'model_dir':str(self.models),'labels_path':str(self.models/'labels.json'),'detector_config':str(self.models/'detector.json'),'priors_path':str(PROJECT/'docs/china-birds-occurrence-ioc12.1.json'),'stable_seconds':0,'roots':[{'id':'fixture','name':'测试目录','path':str(self.root),'context':{'location':'测试地点','region_code':None,'use_date':False}}]}),encoding='utf-8')
  self.cfg=load_config(self.config);self.db=Database(self.data);self.db.configure(self.cfg);self.lib=Library(self.db,self.cfg)
  with self.db.transaction() as c:
   for l in LABELS:c.execute('INSERT INTO labels VALUES(?,?,?,?,?)',(l['scientific_name'],l['zh_name'],l['zh_name'],encode(l['aliases']),encode(l)))
   c.execute('INSERT INTO meta VALUES(?,?)',('score_labels',encode(LABELS)))
  self.processor=FakeProcessor(self);self.jobs=Jobs(self.lib,self.processor)
 def file(self,name,content=b'not an original photograph'):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content);os.utime(p,(time.time()-120,time.time()-120));return p
 def scan(self,limit=50,force=False):
  job=self.jobs.create('fixture',limit=limit,force=force)['id'];self.jobs.run_one(job);return job
 def close(self):
  self.jobs.close();parent=Path(os.environ.get('BIRD_TEST_TEMP') or tempfile.gettempdir()).resolve();assert self.base.resolve().parent==parent and self.base.name.startswith('bird-index-test-');self.temp.cleanup()
class FakeProcessor:
 """显式模拟分类器，测试任务状态；不把结果用作真实识别数据。"""
 def __init__(self,fixture):self.f=fixture;self.calls=[];self.fail=set();self.callback=None
 def run(self,request):
  self.calls.append(request['relative_path'])
  if self.callback:self.callback()
  if request['relative_path'] in self.fail:raise ValueError('fixture decode failure')
  path=safe_file(self.f.root,request['relative_path']);before=fingerprint(path,True);name=hashlib.sha256((request['relative_path']+before['sha256']).encode()).hexdigest()+'.jpg'
  from PIL import Image
  with Image.new('RGB',(16,16),'white') as image:image.save(self.f.data/'thumbnails'/name)
  return {'path':request['display_path'],'directory':request['directory'],'before':before,'after':before,'source_unchanged':True,'decode_ok':True,'status':'needs_review','exif':{'EXIF DateTimeOriginal':'2026:01:01 10:00:00'},'capture_context':{'date':'2026-01-01','location':'测试地点'},'detection':{'status':'no_detection'},'views':[{'name':'whole','all_visual_scores':[.7,.3],'thumbnail':{'name':name,'size':[16,16]}}]}
 def close(self):pass

class PrototypeTests(unittest.TestCase):
 def setUp(self):self.f=Fixture()
 def tearDown(self):self.f.close()
 def test_fresh_catalog_and_label_order_guard(self):
  fresh=Database(self.f.base/'fresh-data');initialize_catalog(fresh,self.f.cfg);self.assertEqual(len(fresh.labels()),2);initialize_catalog(fresh,self.f.cfg)
  (self.f.models/'labels.json').write_text(encode({'labels':list(reversed(LABELS))}),encoding='utf-8')
  with self.assertRaises(ValueError):initialize_catalog(fresh,self.f.cfg)
 def test_config_paths_relative_to_config_and_root_removed(self):
  cfg=read_json_test(self.f.config);cfg.update(data_dir='data',model_dir='models',labels_path='models/labels.json',detector_config='models/detector.json');cfg['roots'][0]['path']='photos';self.f.config.write_text(encode(cfg),encoding='utf-8');loaded=load_config(self.f.config);self.assertEqual(Path(loaded['data_dir']),self.f.data);self.assertEqual(Path(loaded['roots'][0]['path']),self.f.root)
  self.f.cfg['roots']=[]
  with self.assertRaises(ValueError):self.f.jobs.create('fixture')
 def test_import_preview_generation_rechecked_in_transaction(self):
  self.f.file('one.jpg');self.f.scan();doc=self.f.lib.export_reviews();generation=self.f.db.meta('generation');self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird beta'])
  with self.assertRaises(Conflict):self.f.lib.import_reviews(doc,True,generation)
  self.assertEqual(self.f.lib.items()[0]['manual']['species'],['Bird beta'])
 def test_incremental_new_files_and_originals_untouched(self):
  a=self.f.file('中文/one.ARW');b=self.f.file('two.PNG');before={p:fingerprint(p,True) for p in (a,b)};self.f.scan();self.assertEqual(len(self.f.processor.calls),2)
  self.f.scan();self.assertEqual(len(self.f.processor.calls),2);self.f.file('中文/three.jpg');self.f.scan();self.assertEqual(len(self.f.processor.calls),3)
  self.assertEqual(before,{p:fingerprint(p,True) for p in (a,b)});self.assertEqual(len(list(self.f.root.rglob('*.*'))),3)
 def test_persistence_revision_conflict_and_undo(self):
  self.f.file('one.jpg');self.f.scan();p=self.f.lib.items()[0];old=self.f.lib.export_reviews();result=self.f.db.review([{'id':p['id'],'revision':0}],'confirmed',['Bird alpha'])
  with self.assertRaises(Conflict):self.f.db.review([{'id':p['id'],'revision':0}],'no_bird',[])
  reopened=Library(Database(self.f.data),self.f.cfg);self.assertEqual(reopened.items()[0]['manual']['species'],['Bird alpha']);self.f.db.undo(result['change_id']);self.assertEqual(self.f.lib.items()[0]['manual']['status'],'unreviewed')
 def test_consecutive_undo_keeps_revision_monotonic(self):
  self.f.file('one.jpg');self.f.scan();a=self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird alpha']);b=self.f.db.review([{'id':1,'revision':1}],'confirmed',['Bird beta']);self.f.db.undo(b['change_id']);self.f.db.undo(a['change_id']);p=self.f.lib.items()[0];self.assertEqual(p['manual']['status'],'unreviewed');self.assertEqual(p['manual']['revision'],4)
 def test_allowlist_does_not_expand_directory(self):
  for name in ('allowed.jpg','not-allowed.jpg'):self.f.file(name)
  with self.f.db.transaction() as c:c.execute('UPDATE roots SET allow_paths=? WHERE id=?',(encode(['allowed.jpg']),'fixture'))
  self.f.scan();self.assertEqual(self.f.processor.calls,['allowed.jpg'])
 def test_same_species_grouping_and_state_filter_boundary(self):
  for name in ('a.jpg','b.jpg','c.jpg'):self.f.file(name)
  self.f.scan();items=[{'id':p['id'],'revision':0} for p in self.f.lib.items()];self.f.db.review(items,'confirmed',['Bird alpha']);self.assertEqual(self.f.lib.listing({})['total'],1);self.f.db.review([{'id':2,'revision':1}],'uncertain',[]);self.assertEqual(self.f.lib.listing({})['total'],3);self.assertEqual(self.f.lib.listing({'state':'confirmed'})['matched_photos'],2)
 def test_no_bird_exclusion_restore(self):
  self.f.file('one.jpg');self.f.scan();p=self.f.lib.items()[0];r=self.f.db.review([{'id':p['id'],'revision':0}],'no_bird',[])
  self.assertEqual(self.f.lib.listing({})['matched_photos'],0);self.assertEqual(self.f.lib.listing({'state':'no_bird'})['matched_photos'],1);self.f.db.undo(r['change_id']);self.assertEqual(self.f.lib.listing({})['matched_photos'],1)
 def test_atomic_batch_does_not_overwrite_manual(self):
  for name in ('one.jpg','two.jpg','three.jpg'):self.f.file(name)
  self.f.scan();p=self.f.lib.items();self.f.db.review([{'id':p[0]['id'],'revision':0}],'uncertain',[]);p=self.f.lib.items();before=self.f.lib.export_reviews();r=self.f.db.review([{'id':x['id'],'revision':x['manual']['revision']} for x in p],'confirmed',['Bird beta'],True)
  self.assertEqual(r['count'],2);self.assertEqual(self.f.lib.items()[0]['manual']['status'],'uncertain');self.f.db.undo(r['change_id']);self.assertEqual(self.f.lib.items()[1]['manual']['status'],'unreviewed')
  snapshot=self.f.lib.export_reviews()['photos']
  with self.assertRaises(Conflict):self.f.db.review([{'id':p[0]['id'],'revision':1},{'id':p[1]['id'],'revision':-1}],'no_bird',[])
  self.assertEqual(snapshot,self.f.lib.export_reviews()['photos'])
 def test_force_and_changed_source_preserve_manual_mark_stale(self):
  path=self.f.file('one.jpg');self.f.scan();p=self.f.lib.items()[0];self.f.db.review([{'id':p['id'],'revision':0}],'confirmed',['Bird alpha']);manual=self.f.lib.items()[0]['manual'].copy();self.f.scan(force=True)
  self.assertEqual(self.f.lib.items()[0]['manual'],manual);path.write_bytes(b'changed fixture content');self.f.scan();after=self.f.lib.items()[0]['manual'];self.assertEqual(after['species'],manual['species']);self.assertTrue(after['stale']);self.assertEqual(self.f.lib.listing({'state':'pending'})['matched_photos'],1)
 def test_pause_cancel_retry_and_restart(self):
  for name in ('a.jpg','b.jpg','c.jpg'):self.f.file(name)
  id=self.f.jobs.create('fixture')['id'];self.f.processor.callback=lambda:self.f.jobs.action(id,'pause');self.f.jobs.run_one(id);self.assertEqual(len(self.f.processor.calls),1);self.assertEqual(self.f.jobs.state(id),'paused')
  self.f.processor.callback=None;self.f.jobs.action(id,'resume');self.f.jobs.run_one(id);self.assertEqual(len(self.f.processor.calls),3);self.assertEqual(self.f.jobs.state(id),'completed')
  second=self.f.jobs.create('fixture',force=True)['id'];self.f.jobs.action(second,'cancel');self.f.jobs.run_one(second);self.assertEqual(len(self.f.processor.calls),3)
  self.f.jobs.action(second,'resume');self.f.processor.fail={'b.jpg'};self.f.jobs.run_one(second);self.assertEqual(self.f.jobs.state(second),'failed');self.f.processor.fail.clear();self.f.jobs.action(second,'retry');self.f.jobs.run_one(second);self.assertEqual(self.f.jobs.state(second),'completed');self.assertEqual(self.f.processor.calls.count('b.jpg'),3)
  with self.f.db.transaction() as c:c.execute("UPDATE jobs SET state='running' WHERE id=?",(second,));c.execute("UPDATE job_items SET state='running' WHERE job_id=? AND photo_id=1",(second,))
  self.f.db.recover();self.assertEqual(self.f.jobs.state(second),'paused');self.assertEqual(self.f.db.query('SELECT state FROM job_items WHERE job_id=? AND photo_id=1',(second,))[0]['state'],'pending')
 def test_limit_and_second_incremental_batch(self):
  for i in range(4):self.f.file(str(i)+'.jpg')
  self.f.scan(limit=2);self.assertEqual(len(self.f.processor.calls),2);self.f.scan(limit=2);self.assertEqual(len(self.f.processor.calls),4)
 def test_missing_and_unavailable_root(self):
  path=self.f.file('one.jpg');self.f.scan();self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird alpha']);path.unlink();self.f.scan();self.assertEqual(self.f.lib.items()[0]['source_status'],'missing');self.assertEqual(self.f.lib.items()[0]['manual']['species'],['Bird alpha'])
  self.f.file('one.jpg');self.f.scan();self.f.root.rename(self.f.base/'offline');id=self.f.scan();self.assertEqual(self.f.jobs.state(id),'failed');self.assertEqual(self.f.lib.items()[0]['source_status'],'available')
 def test_path_and_config_boundaries(self):
  self.f.file('one.jpg')
  for bad in ('../config.json','/absolute.jpg','C:/one.jpg','..\\one.jpg','one.jpg:stream'):
   with self.assertRaises((ValueError,FileNotFoundError)):safe_file(self.f.root,bad)
  cfg=read_json_test(self.f.config);cfg['data_dir']=str(self.f.root/'data');self.f.config.write_text(encode(cfg),encoding='utf-8')
  with self.assertRaises(ValueError):load_config(self.f.config)
 def test_symlink_escape_is_rejected(self):
  outside=self.f.base/'outside.jpg';outside.write_bytes(b'fixture');link=self.f.root/'link.jpg'
  try:link.symlink_to(outside)
  except OSError as exc:self.skipTest('Windows 不允许创建测试符号链接：'+str(exc))
  with self.assertRaises(ValueError):safe_file(self.f.root,'link.jpg')
  self.f.scan();self.assertEqual(self.f.processor.calls,[])
 def test_import_is_atomic_and_backup_created(self):
  self.f.file('one.jpg');self.f.file('two.jpg');self.f.scan();doc=self.f.lib.export_reviews();bad=copy.deepcopy(doc);bad['photos'][1]['observed_sha256']='bad';before=self.f.lib.export_reviews()['photos']
  with self.assertRaises(ValueError):self.f.lib.import_reviews(bad,True)
  self.assertEqual(before,self.f.lib.export_reviews()['photos']);doc['photos'][0].update(status='confirmed',species=['Bird alpha']);self.assertEqual(self.f.lib.import_reviews(doc)['count'],2);self.f.lib.import_reviews(doc,True);self.assertEqual(self.f.lib.items()[0]['manual']['species'],['Bird alpha']);self.assertTrue(list((self.f.data/'backups').glob('*.sqlite3')))
 def test_backup_restore_and_lock(self):
  self.f.file('one.jpg');self.f.scan();backup=self.f.db.backup();self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird beta']);result=restore(self.f.config,backup);self.assertEqual(self.f.lib.items()[0]['manual']['status'],'unreviewed');self.assertTrue(Path(result['previous_backup']).is_file())
  with ProcessLock(self.f.data/'server.lock'):
   with self.assertRaises(RuntimeError):restore(self.f.config,backup)
 def test_context_does_not_overwrite_and_csv_formula_guard(self):
  self.f.file('=1+1.jpg');self.f.scan();self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird alpha']);before=self.f.lib.export_reviews()['photos'];self.f.lib.context('fixture',{'location':'=1+1','region_code':None,'date':'2026-01-02','use_date':False});self.assertEqual(before,self.f.lib.export_reviews()['photos']);self.assertIn("'=1+1",self.f.lib.export_csv({}).decode('utf-8'))
  self.assertEqual(self.f.lib.listing({'from':'2026-01-02','to':'2026-01-02','q':'旧甲'})['matched_photos'],1)
 def test_old_batch_validation_full_path_and_fingerprint(self):
  payload={'review_batch_id':'b','rows':[{'path':'one','before':{'sha256':'abc'}}],'labels':LABELS};doc={'schema':'bird-manual-review-v2','batch_id':'b','photos':[{'path':'one','source_sha256':'abc','status':'confirmed','species':[{'scientific_name':'Bird alpha'}],'updated_at':None}]};self.assertEqual(len(validate_legacy(payload,doc)),1);doc['photos'][0]['source_sha256']='bad'
  with self.assertRaises(ValueError):validate_legacy(payload,doc)
 def test_write_and_network_guard(self):
  path=self.f.file('protected.jpg');output=self.f.base/'guard-output';output.mkdir();script="from pathlib import Path; import sys,socket; sys.path.insert(0,sys.argv[1]); from stage1_probe import install_guard; install_guard(Path(sys.argv[2]));\nfor operation in [lambda:Path(sys.argv[3]).write_bytes(b'bad'),lambda:socket.socket().connect(('127.0.0.1',9))]:\n try:operation();raise AssertionError('guard failed')\n except PermissionError:pass\nprint('guard passed')"
  result=subprocess.run([sys.executable,'-B','-c',script,str(PROJECT/'tools'),str(output),str(path)],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr);self.assertNotEqual(path.read_bytes(),b'bad')

def read_json_test(path):return json.loads(path.read_text(encoding='utf-8'))

class HTTPTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture()
  for name in ('a.jpg','b.jpg','c.jpg'):self.f.file(name)
  self.f.scan();self.server=Server(('127.0.0.1',0),self.f.lib,self.f.jobs);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.f.close()
 def req(self,path,body=None,headers=None):
  h=headers or {};data=None
  if body is not None:data=encode(body).encode();h={'Content-Type':'application/json',**h}
  r=urllib.request.Request(self.url+path,data=data,headers=h)
  try:
   with urllib.request.urlopen(r,timeout=10) as response:return response.status,response.read()
  except urllib.error.HTTPError as error:return error.code,error.read()
 def test_http_security_and_roundtrip(self):
  status,body=self.req('/api/state');self.assertEqual(status,200);token=json.loads(body)['token'];review={'items':[{'id':1,'revision':0}],'status':'no_bird','species':[]}
  self.assertEqual(self.req('/api/review',review)[0],403);self.assertEqual(self.req('/api/review',review,{'X-Bird-Token':token,'Origin':'https://untrusted.example'})[0],403);self.assertEqual(self.req('/api/state',headers={'Host':'untrusted.example'})[0],403)
  self.assertEqual(self.req('/api/review',review,{'X-Bird-Token':token})[0],200);self.assertEqual(self.req('/api/review',review,{'X-Bird-Token':token})[0],409)
  self.assertEqual(self.req('/thumbs/../index.sqlite3')[0],400);self.assertEqual(self.req('/api/jobs',{'root_id':'unknown'},{'X-Bird-Token':token})[0],400)
  self.assertEqual(json.loads(self.req('/api/library')[1])['matched_photos'],2)
 def test_authenticated_shutdown(self):
  self.assertEqual(self.req('/api/shutdown',{})[0],403)
  self.assertEqual(self.req('/api/shutdown',{}, {'X-Bird-Token':self.server.token})[0],200)
  self.thread.join(timeout=3);self.assertFalse(self.thread.is_alive())
 def test_ui_group_undo_without_loading_members(self):
  with self.f.db.transaction() as c:
   for r in c.execute('SELECT id,summary FROM photos').fetchall():
    row=json.loads(r['summary']);row['detection']['status']='detected';c.execute('UPDATE photos SET summary=? WHERE id=?',(encode(row),r['id']))
  node=Path(os.environ.get('BIRD_NODE') or shutil.which('node') or 'node')
  result=subprocess.run([str(node),str(PROJECT/'tests/check_app_page.js'),self.url,'group'],capture_output=True,text=True,encoding='utf-8',timeout=35)
  self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
 def test_ui_without_image_loading(self):
  node=Path(os.environ.get('BIRD_NODE') or shutil.which('node') or 'node')
  result=subprocess.run([str(node),str(PROJECT/'tests/check_app_page.js'),self.url],capture_output=True,text=True,encoding='utf-8',timeout=35)
  self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

if __name__=='__main__':unittest.main()
