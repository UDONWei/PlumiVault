"""Task progress uses synthetic database rows; no source photo/model reads."""
import os,shutil,subprocess,unittest
import os, shutil
from pathlib import Path
from unittest.mock import patch
from test_prototype import Fixture

class ProgressTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture()
  with self.f.db.transaction() as c:
   for i in range(1,4):c.execute('INSERT INTO photos(id,root_id,rel_path,display_path) VALUES(?,?,?,?)',(i,'fixture',f'不存在/测试{i}.ARW',f'fixture/不存在/测试{i}.ARW'))
   c.execute("INSERT INTO jobs(id,root_id,scope,limit_count,state,found,created_at,updated_at,discovery_done) VALUES('active','fixture','',10,'running',3,'2026-01-01','2026-01-01',1)")
   for i,state in [(1,'done'),(2,'running'),(3,'pending')]:c.execute('INSERT INTO job_items(job_id,photo_id,state) VALUES(?,?,?)',('active',i,state))
 def tearDown(self):self.f.close()
 def test_current_photo_is_metadata_only_and_survives_pause_request(self):
  before=self.f.db.meta('generation')
  with patch.object(self.f.processor,'run',side_effect=AssertionError('must not process')),patch.object(self.f.jobs,'discover',side_effect=AssertionError('must not scan')):
   result=self.f.jobs.list()[0]
   self.assertEqual(result['current_photo'],{'id':2,'path':'不存在/测试2.ARW'})
   self.assertEqual(result['counts'],{'done':1,'pending':1,'running':1})
   self.f.jobs.action('active','pause');self.assertEqual(self.f.jobs.list()[0]['current_photo']['id'],2)
   with self.f.db.transaction() as c:c.execute("UPDATE job_items SET state='done' WHERE photo_id=2")
   self.assertIsNone(self.f.jobs.list()[0]['current_photo'])
  self.assertEqual(self.f.db.meta('generation'),before)
  self.assertEqual(list(self.f.root.iterdir()),[])
  self.assertEqual(self.f.processor.calls,[])
 def test_active_task_not_hidden_by_fifty_newer_finished_jobs(self):
  with self.f.db.transaction() as c:
   for i in range(55):c.execute("INSERT INTO jobs(id,root_id,scope,limit_count,state,created_at,updated_at) VALUES(?,'fixture','',10,'completed','2026-10-25','2026-10-25')",(f'old-{i}',))
  result=self.f.jobs.list();self.assertEqual(len(result),50);self.assertEqual(result[0]['id'],'active');self.assertTrue(all(j['current_photo'] is None for j in result[1:]))
 def test_progress_asset_and_metadata_endpoint(self):
  import json,threading,urllib.request
  from bird_index.server import Server
  server=Server(("127.0.0.1",0),self.f.lib,self.f.jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   base="http://127.0.0.1:"+str(server.server_port)
   with urllib.request.urlopen(base+"/progress.js",timeout=5) as response:self.assertIn(b"BirdProgress",response.read());self.assertIn("javascript",response.headers["Content-Type"])
   with urllib.request.urlopen(base+"/api/jobs",timeout=5) as response:self.assertEqual(json.load(response)["items"][0]["current_photo"]["id"],2)
   self.assertEqual(self.f.processor.calls,[])
  finally:server.shutdown();server.server_close();thread.join()
 def test_editor_shared_progress(self):
  self.node_check("check_editor_progress.js","web")
 def test_progress_browser_controller(self):
  self.node_check("check_progress.js","web/progress.js")
 def node_check(self,script,target):
  root=Path(__file__).resolve().parents[1]
  node=os.environ.get('BIRD_NODE') or shutil.which('node')
  if not node:
   bundled=Path(os.environ.get('BIRD_NODE') or shutil.which('node') or 'node')
   if bundled.is_file():node=str(bundled)
  if not node:self.skipTest('Node.js unavailable; progress interaction test not run')
  result=subprocess.run([node,str(root/'tests'/script),str(root/target)],capture_output=True,text=True,encoding='utf-8',timeout=20)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
