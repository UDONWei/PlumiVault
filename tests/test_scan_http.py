import json,threading,unittest,urllib.request,urllib.error
from test_prototype import Fixture
from bird_index.server import Server
from bird_index.selection import acceptance_report

class ScanHTTPTests(unittest.TestCase):
 def test_rescan_ui_is_explicit_subset_and_resets_after_submission(self):
  import os,shutil,subprocess
  from bird_index.common import PROJECT
  node=os.environ.get('BIRD_NODE') or shutil.which('node')
  if not node:self.skipTest('Node unavailable')
  f=Fixture()
  for name in ('picked/a.jpg','picked/b.jpg','outside/c.jpg'):f.file(name)
  f.scan();f.cfg.update(max_files_per_job=0,require_folder_selection=True)
  server=Server(('127.0.0.1',0),f.lib,f.jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   run=subprocess.run([node,str(PROJECT/'tests/check_app_page.js'),'http://127.0.0.1:'+str(server.server_port),'rescan'],capture_output=True,text=True,encoding='utf-8',timeout=30)
   self.assertEqual(run.returncode,0,run.stdout+run.stderr)
   job=next(j for j in f.jobs.list() if j['state']=='queued');self.assertEqual(job['force'],1);self.assertEqual(job['counts']['pending'],1)
   f.jobs.run_one(job['id']);self.assertEqual(f.processor.calls.count('picked/a.jpg'),2);self.assertEqual(f.processor.calls.count('picked/b.jpg'),1);self.assertEqual(f.processor.calls.count('outside/c.jpg'),1)
  finally:server.shutdown();server.server_close();thread.join();f.close()
 def test_preview_confirm_auth_guard_and_folder_catalog(self):
  f=Fixture();f.cfg.update(max_files_per_job=0,require_folder_selection=True);f.file('picked/a.jpg')
  server=Server(('127.0.0.1',0),f.lib,f.jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
  def call(path,value=None,authorized=True):
   headers={'Content-Type':'application/json'}
   if authorized:headers['X-Bird-Token']=server.token
   request=urllib.request.Request(base+path,data=json.dumps(value).encode() if value is not None else None,headers=headers)
   try:
    with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.load(response)
   except urllib.error.HTTPError as e:return e.code,json.load(e)
  try:
   value={'root_id':'fixture','scopes':['picked'],'limit':0}
   self.assertEqual(call('/api/scan-preview',value,False)[0],403)
   self.assertEqual(call('/api/jobs',value)[0],400)
   status,plan=call('/api/scan-preview',value);self.assertEqual(status,200);self.assertEqual(f.jobs.list(),[])
   status,_=call('/api/scan-confirm',{'preview_token':plan['preview_token'],'paths':['other.jpg']});self.assertEqual(status,400)
   status,result=call('/api/scan-confirm',{'preview_token':plan['preview_token'],'paths':['picked/a.jpg']});self.assertEqual(status,200)
   f.jobs.run_one(result['id']);status,catalog=call('/api/library-folders');self.assertEqual(catalog['items'][0]['ready'],1)
   status,report=call('/api/acceptance?job='+result['id']);self.assertEqual(status,200);self.assertEqual(report['job']['id'],result['id']);self.assertEqual(report['photos'][0]['measurement_source'],'job_history')
   self.assertEqual(call('/api/acceptance?job=missing')[0],400)
   self.assertEqual(call('/api/scan-preview',value)[1]['counts']['unchanged'],1)
   self.assertEqual(call('/api/scan-preview',{**value,'rescan':'true'})[0],400)
   status,again=call('/api/scan-preview',{**value,'rescan':True});self.assertEqual(again['counts']['rescan'],1)
   self.assertEqual(call('/api/scan-preview',{**value,'rescan':True},False)[0],403)
   status,job=call('/api/scan-confirm',{'preview_token':again['preview_token'],'paths':['picked/a.jpg']});self.assertEqual(status,200)
   f.jobs.run_one(job['id']);self.assertEqual(f.processor.calls.count('picked/a.jpg'),2)
  finally:server.shutdown();server.server_close();thread.join();f.close()
 def test_old_job_report_uses_original_measurement_after_later_analysis(self):
  f=Fixture()
  try:
   f.file('a.jpg');job=f.scan()
   with f.db.transaction() as c:
    history=json.loads(c.execute('SELECT payload FROM processing_history WHERE job_id=?',(job,)).fetchone()[0]);history['timings']={'total_s':3.0};history['worker_cpu_s']=4.2;history['decode_breakdown']={'unpack_s':.5}
    c.execute('UPDATE processing_history SET payload=? WHERE job_id=?',(json.dumps(history),job))
    current={**history,'timings':{'total_s':99}}
    c.execute('UPDATE analyses SET payload=?',(json.dumps(current),))
   report=acceptance_report(f.db,job);self.assertEqual(report['max_photo_seconds'],3.0);self.assertEqual(report['photos'][0]['worker_cpu_s'],4.2)
   second=f.scan();report=acceptance_report(f.db,second);self.assertIsNone(report['max_photo_seconds']);self.assertEqual(report['photos'][0]['state'],'skipped')
  finally:f.close()

if __name__=='__main__':unittest.main()
