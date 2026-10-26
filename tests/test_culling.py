"""Synthetic files only. No private photos, no model download, no real moves."""
import contextlib,json,os,sqlite3,time,unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image,ImageFilter,ImageDraw
from test_prototype import Fixture
from bird_index.curation import Organizer,rename_no_replace,strict_path
from bird_index.selection import set_selection,acceptance_report
from bird_index.quality import assess
from bird_index.db import Database,Conflict

class CullingTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.path=self.f.file('日期/a.ARW');self.f.scan();self.dest=self.f.base/'quarantine';self.dest.mkdir();self.cfg={'enabled':True,'root_id':'fixture','photo_root':str(self.f.root),'quarantine_root':str(self.dest),'allowed_photo_ids':[1],'max_batch':10};self.org=Organizer(self.f.db,self.cfg)
 def tearDown(self):self.f.close()
 def reject(self):return set_selection(self.f.db,[{'id':1,'revision':0}],'reject',4)
 def test_selection_preserves_species_and_source_and_filters(self):
  before=self.path.read_bytes();self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird alpha']);self.reject();set_selection(self.f.db,[{'id':1,'revision':1}],'keep',None)
  p=self.f.lib.items()[0];self.assertEqual(p['selection']['rating'],4);self.assertEqual(p['manual']['species'],['Bird alpha']);self.assertEqual(self.path.read_bytes(),before)
  self.assertEqual(self.f.lib.listing({'flag':'reject'})['total'],0);self.assertEqual(self.f.lib.listing({'rating':'5'})['total'],0)
  with self.assertRaises(Conflict):set_selection(self.f.db,[{'id':1,'revision':0}],'reject',3)
 def test_move_restore_idempotent_and_manual_preserved(self):
  self.reject();manual=self.f.lib.items()[0]['manual'];plan=self.org.plan([1],'move');self.assertTrue(self.path.exists());result=self.org.commit(plan['plan_id']);self.assertTrue(result['results'][0]['ok']);self.assertFalse(self.path.exists());self.assertEqual(self.org.commit(plan['plan_id']),result)
  self.assertEqual(self.f.lib.listing({})['total'],0);self.assertEqual(self.f.lib.listing({'storage':'quarantined'})['total'],1)
  restore=self.org.plan([1],'restore');self.assertTrue(self.org.commit(restore['plan_id'])['results'][0]['ok']);self.assertTrue(self.path.exists());self.assertEqual(self.f.lib.items()[0]['manual'],manual)
 def test_disabled_allowlist_and_requires_explicit_reject(self):
  with self.assertRaises(ValueError):self.org.plan([1],'move')
  self.reject();self.cfg['enabled']=False
  with self.assertRaises(ValueError):self.org.plan([1],'move')
  self.cfg['enabled']=True;self.cfg['allowed_photo_ids']=[99]
  with self.assertRaises(ValueError):self.org.plan([1],'move')
 def test_changed_file_and_changed_selection(self):
  self.reject();plan=self.org.plan([1],'move');self.path.write_bytes(b'changed synthetic data');r=self.org.commit(plan['plan_id']);self.assertFalse(r['results'][0]['ok']);self.assertTrue(self.path.exists())
 def test_revision_changed_after_preview(self):
  self.reject();plan=self.org.plan([1],'move');set_selection(self.f.db,[{'id':1,'revision':1}],'keep',None);self.assertFalse(self.org.commit(plan['plan_id'])['results'][0]['ok']);self.assertTrue(self.path.exists())
 def test_collision_never_overwrites(self):
  self.reject();plan=self.org.plan([1],'move');dst=self.dest/plan['items'][0]['destination'];dst.parent.mkdir(parents=True);dst.write_bytes(b'existing');result=self.org.commit(plan['plan_id']);self.assertFalse(result['results'][0]['ok']);self.assertEqual(dst.read_bytes(),b'existing');self.assertTrue(self.path.exists())
 def test_restore_collision(self):
  self.reject();self.org.commit(self.org.plan([1],'move')['plan_id']);self.path.write_bytes(b'new file at original path')
  with self.assertRaises(ValueError):self.org.plan([1],'restore')
 def test_crash_after_move_reconciles(self):
  self.reject();plan=self.org.plan([1],'move');dst=self.dest/plan['items'][0]['destination'];dst.parent.mkdir(parents=True)
  with self.f.db.transaction() as c:c.execute("UPDATE file_plans SET state='executing' WHERE id=?",(plan['plan_id'],))
  rename_no_replace(self.path,dst)
  with self.assertRaises(ValueError):self.f.jobs.create('fixture')
  result=self.org.commit(plan['plan_id']);self.assertTrue(result['results'][0]['ok']);self.assertEqual(self.f.lib.items()[0]['source_status'],'quarantined')
 def test_no_overwrite_primitive_and_no_cross_device_copy(self):
  dst=self.dest/'exists';dst.write_bytes(b'keep')
  with self.assertRaises(OSError):rename_no_replace(self.path,dst)
  self.assertEqual(dst.read_bytes(),b'keep')
  self.reject();plan=self.org.plan([1],'move')
  with patch('bird_index.curation.rename_no_replace',side_effect=OSError(18,'Cross-device')):r=self.org.commit(plan['plan_id'])
  self.assertFalse(r['results'][0]['ok']);self.assertTrue(self.path.exists())
 def test_paths_and_busy_job(self):
  for path in ['../out.ARW','/outside','dir/../../escape']:
   with self.assertRaises(ValueError):strict_path(self.f.root,path)
  self.reject();self.f.jobs.create('fixture')
  with self.assertRaises(ValueError):self.org.plan([1],'move')
 def test_cancelled_job_still_processing_blocks_move(self):
  self.reject();job=self.f.jobs.create('fixture')['id']
  with self.f.db.transaction() as c:
   c.execute("UPDATE jobs SET state='cancelled' WHERE id=?",(job,))
   c.execute("INSERT INTO job_items(job_id,photo_id,state) VALUES(?,1,'running')",(job,))
  with self.assertRaises(ValueError):self.org.plan([1],'move')
  self.assertTrue(self.path.exists());self.assertEqual(self.f.db.query('SELECT * FROM file_plans'),[])
 def test_symlink_rejected(self):
  link=self.f.root/'link'
  try:link.symlink_to(self.dest,target_is_directory=True)
  except OSError:self.skipTest('Windows symlink privilege unavailable')
  with self.assertRaises(ValueError):strict_path(self.f.root,'link/a.ARW',True)
 def test_migration_backup(self):
  with self.f.db.transaction() as c:c.execute("UPDATE meta SET value='2' WHERE key='schema'")
  db=Database(self.f.data);self.assertEqual(db.meta('schema'),'5');backups=list((self.f.data/'backups').glob('*.sqlite3'));self.assertTrue(backups)
  with contextlib.closing(sqlite3.connect(backups[-1])) as c:self.assertEqual(c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0],'2')
 def test_report_does_not_read_photos(self):
  with patch('pathlib.Path.open',side_effect=AssertionError('photo access forbidden')):report=acceptance_report(self.f.db)
  self.assertEqual(len(report['photos']),1);self.assertIsNone(report['max_sampled_worker_rss_bytes']);self.assertTrue(report['photos'][0]['decode_ok'])
 def test_quarantined_stays_quarantined_on_later_scan(self):
  self.reject();self.org.commit(self.org.plan([1],'move')['plan_id']);self.f.scan();self.assertEqual(self.f.lib.items()[0]['source_status'],'quarantined')
 def test_idle_job_loop_waits_until_explicit_wake(self):
  with patch.object(self.f.db,'query',wraps=self.f.db.query) as query:
   self.f.jobs.start();time.sleep(.15);first=query.call_count;time.sleep(.65);self.assertEqual(query.call_count,first)
   self.f.jobs.create('fixture');time.sleep(.2);self.assertGreater(query.call_count,first)
 def test_score_filters_csv_and_cache_no_original_reads(self):
  from bird_index.quality import score_existing
  from bird_index.common import encode
  sha=self.f.lib.items()[0]['sha256'];q={'score':68,'source_sha':sha,'needs_review':True,'issues':['合成测试提示']}
  with self.f.db.transaction() as c:
   row=json.loads(c.execute('SELECT summary FROM photos WHERE id=1').fetchone()[0]);row['quality']=q;c.execute('UPDATE photos SET summary=? WHERE id=1',(encode(row),))
  self.assertEqual(self.f.lib.listing({'min_score':'70'})['total'],0);self.assertEqual(self.f.lib.listing({'max_score':'70','quality':'issues'})['total'],1)
  with patch('bird_index.preview.render',side_effect=AssertionError('must reuse cache')):self.assertTrue(score_existing(self.f.lib,1,sha)['cached'])
  self.assertIn('合成测试提示',self.f.lib.export_csv({}).decode('utf-8'))
  with self.assertRaises(Conflict):score_existing(self.f.lib,1,'0'*64)
 def test_expired_preview_does_not_move(self):
  self.reject();plan=self.org.plan([1],'move')
  with self.f.db.transaction() as c:c.execute('UPDATE file_plans SET created=0 WHERE id=?',(plan['plan_id'],))
  with self.assertRaises(ValueError):self.org.commit(plan['plan_id'])
  self.assertTrue(self.path.exists())
 def test_partial_batch_reports_each_file(self):
  self.f.file('日期/b.ARW');self.f.scan();self.cfg['allowed_photo_ids']=[1,2]
  set_selection(self.f.db,[{'id':1,'revision':0},{'id':2,'revision':0}],'reject',0);plan=self.org.plan([1,2],'move');(self.f.root/'日期/b.ARW').write_bytes(b'changed fixture')
  result=self.org.commit(plan['plan_id']);self.assertEqual([r['ok'] for r in result['results']],[True,False]);self.assertFalse(self.path.exists());self.assertTrue((self.f.root/'日期/b.ARW').exists())
 def test_database_restore_cannot_discard_move_journal(self):
  from bird_index.server import restore
  backup=self.f.db.backup();self.reject();self.org.commit(self.org.plan([1],'move')['plan_id'])
  with self.assertRaises(ValueError):restore(self.f.config,backup)
  self.assertEqual(self.f.lib.items()[0]['source_status'],'quarantined')
 def test_external_replacement_not_adopted_for_quarantined_photo(self):
  self.reject();self.org.commit(self.org.plan([1],'move')['plan_id']);self.path.write_bytes(b'external replacement');self.f.scan();self.assertEqual(self.f.lib.items()[0]['source_status'],'quarantined')

class CullingHTTPTests(unittest.TestCase):
 def test_auth_selection_report_and_disabled_mover(self):
  import threading,urllib.request,urllib.error
  from bird_index.server import Server
  f=Fixture();f.file('one.jpg');f.scan();server=Server(('127.0.0.1',0),f.lib,f.jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
  def request(path,body=None,token=None):
   req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json',**({'X-Bird-Token':token} if token else {})})
   try:
    with urllib.request.urlopen(req) as r:return r.status,json.load(r)
   except urllib.error.HTTPError as e:
    with e:return e.code,json.load(e)
  try:
   body={'items':[{'id':1,'revision':0}],'flag':'keep','rating':5}
   self.assertEqual(request('/api/selection',body)[0],403);self.assertEqual(request('/api/selection',body,server.token)[0],200)
   with patch.dict(os.environ,{'BIRD_ORGANIZER_URL':''}):
    self.assertFalse(request('/api/curation-status')[1]['enabled']);self.assertEqual(request('/api/curation-plan',{'ids':[1],'action':'move'},server.token)[0],400)
   hidden={'items':[{'id':1,'revision':0}],'hidden':True}
   self.assertEqual(request('/api/visibility',hidden)[0],403)
   self.assertEqual(request('/api/visibility',hidden,server.token)[0],200)
   self.assertEqual(request('/api/visibility',hidden,server.token)[0],409)
   self.assertEqual(request('/api/library?mode=photos&visibility=hidden')[1]['total'],1)
   self.assertEqual(request('/api/library?mode=photos')[1]['total'],0)
   self.assertEqual(len(request('/api/acceptance')[1]['photos']),1);self.assertEqual(f.lib.items()[0]['selection']['rating'],5)
  finally:server.shutdown();server.server_close();thread.join();f.close()

class QualityTests(unittest.TestCase):
 def test_synthetic_blur_and_exposure(self):
  im=Image.new('RGB',(400,400),'gray');draw=ImageDraw.Draw(im)
  for x in range(10,390,12):draw.line((x,10,x,390),fill='white',width=3)
  blurred=im.filter(ImageFilter.GaussianBlur(5));sharp=assess(im,[0,0,1,1]);soft=assess(blurred,[0,0,1,1]);self.assertGreater(sharp['clarity'],soft['clarity']);self.assertTrue(any('模糊' in x for x in soft['issues']))
  white=Image.new('RGB',(100,100),'white');self.assertTrue(any('过曝' in x for x in assess(white,[0,0,1,1])['issues']));im.close();blurred.close();white.close()
 def test_no_subject_is_not_aesthetic_claim(self):
  with Image.new('RGB',(100,100),'gray') as im:r=assess(im)
  self.assertIsNone(r['composition']);self.assertIn('未训练审美模型',r['method'])

if __name__=='__main__':unittest.main()
