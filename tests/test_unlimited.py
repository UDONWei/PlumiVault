"""Unlimited batches use explicit synthetic folders, never the user's NAS/photos."""
import json,os,shutil,subprocess,threading,unittest
import os, shutil
from pathlib import Path
from unittest.mock import patch
from test_prototype import Fixture
from bird_index.common import load_config,digest,PROJECT
from bird_index.db import Database
from bird_index.server import Server
from enable_unlimited_scan import enable

class UnlimitedTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.f.cfg.update(max_files_per_job=0,require_folder_selection=True)
  for i in range(13):self.f.file(f'picked/{i:02}.ARW')
  self.f.file('picked/sub/nested.jpg');self.f.file('outside/keep.ARW');self.f.file('root-only.jpg')
 def tearDown(self):self.f.close()
 def create(self,**kw):return self.f.jobs.create('fixture',scopes=['picked'],**kw)['id']
 def test_unlimited_recursive_incremental_and_manual_preservation(self):
  sources={p:(digest(p),p.stat().st_mtime_ns) for p in self.f.root.rglob('*') if p.is_file()}
  job=self.create(limit=0);self.f.jobs.run_one(job)
  self.assertEqual(self.f.jobs.state(job),'completed');self.assertEqual(len(self.f.processor.calls),14)
  self.assertTrue(all(p.startswith('picked/') for p in self.f.processor.calls))
  self.assertEqual(self.f.jobs.list()[0]['counts'],{'done':14})
  self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird beta']);before=self.f.lib.items([1])[0]['manual']
  again=self.create();self.f.jobs.run_one(again);self.assertEqual(len(self.f.processor.calls),14)
  row=next(j for j in self.f.jobs.list() if j['id']==again);self.assertEqual(row['counts'],{'skipped':14})
  self.f.file('picked/new.jpg');third=self.create();self.f.jobs.run_one(third)
  self.assertEqual(len(self.f.processor.calls),15);self.assertEqual(self.f.lib.items([1])[0]['manual'],before)
  self.assertEqual(sources,{p:(digest(p),p.stat().st_mtime_ns) for p in sources})
  self.assertEqual(self.f.db.query("SELECT count(*) n FROM photos WHERE rel_path NOT LIKE 'picked/%'")[0]['n'],0)
 def test_unlimited_pause_resume_and_restart_does_not_expand_scope(self):
  job=self.create()
  def pause():self.f.jobs.action(job,'pause');self.f.processor.callback=None
  self.f.processor.callback=pause;self.f.jobs.run_one(job)
  self.assertEqual(len(self.f.processor.calls),1);self.assertEqual(self.f.jobs.state(job),'paused')
  Database(self.f.data).recover();self.f.jobs.action(job,'resume');self.f.jobs.run_one(job)
  self.assertEqual(self.f.jobs.state(job),'completed');self.assertEqual(len(self.f.processor.calls),14);self.assertEqual(len(set(self.f.processor.calls)),14)
 def test_cancel_and_resume_keeps_completed_rows(self):
  job=self.create()
  def cancel():self.f.jobs.action(job,'cancel');self.f.processor.callback=None
  self.f.processor.callback=cancel;self.f.jobs.run_one(job)
  self.assertEqual(self.f.jobs.state(job),'cancelled');self.assertEqual(len(self.f.processor.calls),1)
  self.f.jobs.action(job,'resume');self.f.jobs.run_one(job)
  self.assertEqual(len(self.f.processor.calls),14);self.assertEqual(self.f.jobs.state(job),'completed')
 def test_no_selection_invalid_values_and_legacy_cap(self):
  for scopes in (None,[],[''],['../outside']):
   with self.assertRaises((ValueError,FileNotFoundError)):self.f.jobs.create('fixture',scopes=scopes,limit=0)
  for value in (-1,True,'0',1.5,9223372036854775808):
   with self.assertRaises(ValueError):self.create(limit=value)
  self.f.cfg['max_files_per_job']=10
  with self.assertRaises(ValueError):self.create(limit=0)
  self.f.cfg.update(max_files_per_job=0,require_folder_selection=False)
  with self.assertRaises(ValueError):self.f.jobs.create('fixture',limit=0)
  self.assertEqual(self.f.db.query('SELECT count(*) n FROM jobs')[0]['n'],0)
 def test_finite_limit_still_works_and_root_files_never_recurse(self):
  job=self.create(limit=2);self.f.jobs.run_one(job);self.assertEqual(len(self.f.processor.calls),2)
  job=self.f.jobs.create('fixture',scopes=['.'],limit=0)['id'];self.f.jobs.run_one(job)
  self.assertEqual(self.f.processor.calls[-1],'root-only.jpg');self.assertEqual(len(self.f.processor.calls),3)
 def test_config_migration_only_changes_limit_and_backs_up_exact_bytes(self):
  cfg=json.loads(self.f.config.read_text(encoding='utf-8'));cfg.update(max_files_per_job=10,require_folder_selection=True,custom={'preserve':'原设置'})
  self.f.config.write_text(json.dumps(cfg,ensure_ascii=False),encoding='utf-8');raw=self.f.config.read_bytes()
  result=enable(self.f.config);self.assertEqual(Path(result['backup']).read_bytes(),raw)
  after=json.loads(self.f.config.read_bytes());expected={**cfg,'max_files_per_job':0};self.assertEqual(after,expected)
  self.assertEqual(load_config(self.f.config)['max_files_per_job'],0);self.assertFalse(result['scan_started'])
  backups=list(self.f.base.glob('config.before-unlimited-*.json'));stamp=self.f.config.stat().st_mtime_ns
  self.assertFalse(enable(self.f.config)['changed']);self.assertEqual(self.f.config.stat().st_mtime_ns,stamp);self.assertEqual(list(self.f.base.glob('config.before-unlimited-*.json')),backups)
  self.assertEqual(self.f.processor.calls,[]);self.assertEqual(self.f.db.query('SELECT count(*) n FROM jobs')[0]['n'],0)
 def test_failed_atomic_config_change_preserves_old_config(self):
  cfg={'max_files_per_job':10,'require_folder_selection':True,'preserve':['a','b']};self.f.config.write_text(json.dumps(cfg));raw=self.f.config.read_bytes()
  with patch('enable_unlimited_scan.os.replace',side_effect=OSError('synthetic replacement failure')):
   with self.assertRaises(OSError):enable(self.f.config)
  self.assertEqual(self.f.config.read_bytes(),raw);self.assertEqual(list(self.f.base.glob('.config-unlimited-*.tmp')),[])
  cfg['require_folder_selection']=False;self.f.config.write_text(json.dumps(cfg));raw=self.f.config.read_bytes()
  with self.assertRaises(ValueError):enable(self.f.config)
  self.assertEqual(self.f.config.read_bytes(),raw)
 def test_unlimited_ui_and_selected_folder_request(self):
  node=os.environ.get('BIRD_NODE') or shutil.which('node') or 'node'
  if not Path(node).is_file():self.skipTest('Node unavailable')
  server=Server(('127.0.0.1',0),self.f.lib,self.f.jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   result=subprocess.run([node,str(PROJECT/'tests/check_app_page.js'),'http://127.0.0.1:'+str(server.server_port),'unlimited'],capture_output=True,text=True,encoding='utf-8',timeout=30)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   rows=self.f.jobs.list();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['limit_count'],0);self.assertEqual(json.loads(rows[0]['scopes']),['picked'])
   self.assertEqual(self.f.processor.calls,[])
  finally:server.shutdown();server.server_close();thread.join()
 def test_upgrade_shell_order_and_failure_guards_with_fake_docker(self):
  shell=os.environ.get('BIRD_SH') or shutil.which('sh') or 'sh'
  if not Path(shell).is_file():self.skipTest('POSIX shell unavailable; NAS script runtime not tested')
  folder=self.f.base/'upgrade-fixture';folder.mkdir();(folder/'config').mkdir();(folder/'config/config.json').write_text('{}');(folder/'.env').write_text('# synthetic only')
  harness=folder/'run.sh';harness.write_text('''#!/bin/sh
set -eu
cd "$BIRD_TEST_DIR"
# Deterministic mock identity/time; no dependency on host POSIX utilities.
date() { printf 20261025180000; }
id() { printf 1000; }
docker() {
 printf '%s\\n' "$*" >> "$BIRD_TEST_LOG"
 case "$*" in
  *"ps -q index"*) printf 'synthetic-index\\n';;
  "inspect --format"*) if [ "$BIRD_TEST_MODE" = rw ]; then printf 'true\\n'; else printf 'false\\n'; fi;;
  *"exec -T index"*) if [ "$BIRD_TEST_MODE" = busy ]; then return 7; fi;;
  *"build index"*) if [ "$BIRD_TEST_MODE" = build-failed ]; then return 8; fi;;
 esac
 return 0
}
. "$BIRD_UPGRADE_SCRIPT"
''',encoding='utf-8',newline='\n')
  for mode in ['ok','rw','busy','build-failed']:
   log=folder/(mode+'.log');env={**os.environ,'BIRD_TEST_DIR':folder.as_posix(),'BIRD_TEST_LOG':log.as_posix(),'BIRD_TEST_MODE':mode,'BIRD_UPGRADE_SCRIPT':(PROJECT/'deploy/upgrade-unlimited.sh').as_posix()}
   result=subprocess.run([shell,harness.as_posix()],env=env,capture_output=True,text=True,encoding='utf-8',timeout=25);calls=log.read_text(encoding='utf-8') if log.exists() else ''
   if mode=='ok':
    self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertLess(calls.index('db.backup()'),calls.index('build index'));self.assertLess(calls.index('build index'),calls.index('enable_unlimited_scan.py'));self.assertLess(calls.index('enable_unlimited_scan.py'),calls.index('up -d --no-build'))
    helper=next(line for line in calls.splitlines() if line.startswith('run '));self.assertIn('--network none',helper);self.assertIn('target=/settings',helper);self.assertNotIn('target=/photos',helper);self.assertNotIn('compose.curation',calls)
   else:
    self.assertNotEqual(result.returncode,0);self.assertNotIn('enable_unlimited_scan.py',calls);self.assertNotIn('up -d --no-build',calls)

if __name__=='__main__':unittest.main()
