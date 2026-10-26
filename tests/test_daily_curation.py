"""Daily organizer uses generated files and an isolated deployment only."""
import json,os,shutil,subprocess,unittest
import os, shutil
from pathlib import Path
from unittest.mock import patch
from test_prototype import Fixture
from bird_index.curation import Organizer
from bird_index.selection import set_selection
from bird_index.common import PROJECT,digest
from enable_daily_curation import enable,synthetic_probe


class DailyCurationTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.dest=self.f.base/'quarantine';self.dest.mkdir()
  for i in range(13):self.f.file(f'日期/{i:02}.jpg',('generated '+str(i)).encode())
  self.f.scan();self.cfg={'enabled':True,'scope':'indexed_root','root_id':'fixture','photo_root':str(self.f.root),'quarantine_root':str(self.dest),'max_batch':100};self.org=Organizer(self.f.db,self.cfg)
 def tearDown(self):self.f.close()
 def reject(self):set_selection(self.f.db,[{'id':i,'revision':0} for i in range(1,14)],'reject',4)
 def test_daily_scope_moves_thirteen_only_after_confirmation_then_restores(self):
  self.reject();self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird alpha'])
  before=self.f.lib.export_reviews();originals={p.relative_to(self.f.root).as_posix():digest(p) for p in self.f.root.rglob('*.jpg')}
  status=self.org.status();self.assertEqual(status['allowed_count'],13);self.assertEqual(status['max_batch'],100)
  p=self.org.plan(list(range(1,14)),'move');self.assertEqual(len(list(self.f.root.rglob('*.jpg'))),13)
  result=self.org.commit(p['plan_id']);self.assertTrue(all(r['ok'] for r in result['results']));self.assertEqual(len(list(self.f.root.rglob('*.jpg'))),0)
  self.assertEqual(self.org.commit(p['plan_id']),result)
  self.assertEqual(self.f.lib.listing({'storage':'quarantined','state':'any','mode':'photos'})['total'],13)
  self.assertTrue(all(p['selection']['rating']==4 for p in self.f.lib.items()))
  result=self.org.commit(self.org.plan(list(range(1,14)),'restore')['plan_id']);self.assertTrue(all(r['ok'] for r in result['results']))
  self.assertEqual(originals,{p.relative_to(self.f.root).as_posix():digest(p) for p in self.f.root.rglob('*.jpg')})
  self.assertEqual(before['photos'],self.f.lib.export_reviews()['photos'])
 def test_requires_reject_known_ids_and_configured_root(self):
  with self.assertRaises(ValueError):self.org.plan([1],'move')
  self.reject()
  for ids in ([999],[True],[1,1],list(range(1,102))):
   with self.assertRaises(ValueError):self.org.plan(ids,'move')
  self.cfg['root_id']='different'
  with self.assertRaises(ValueError):self.org.plan([1],'move')
  self.assertEqual(self.f.db.query('SELECT * FROM file_plans'),[])
 def test_explicit_mode_required_and_unknown_mode_rejected(self):
  self.reject();self.cfg.pop('scope')
  with self.assertRaises(ValueError):self.org.plan([1],'move')
  self.cfg['scope']='all_disk'
  with self.assertRaises(ValueError):self.org.plan([1],'move')
  self.cfg.update(scope='indexed_root',max_batch=0)
  with self.assertRaises(ValueError):self.org.plan([1],'move')


class EnableDailyTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.app=self.f.base/'deployment';self.app.mkdir();(self.app/'config').mkdir();(self.app/'data').mkdir()
  self.library=self.f.base/'library';self.library.mkdir();(self.library/'未处理').mkdir();(self.library/'未处理/untouched.ARW').write_bytes(b'generated test file, must not move')
  self.config={'roots':[{'id':'nas-unprocessed','path':'/photos'}],'keep':'配置不改'};(self.app/'config/config.json').write_text(json.dumps(self.config),encoding='utf-8')
  self.env=b'BIRD_UID=1000\nBIRD_AUTH_HASH=fake$$synthetic\n';(self.app/'.env').write_bytes(self.env)
 def tearDown(self):self.f.close()
 def run_enable(self):return enable(self.app,self.library,'/volume1/照片')
 def test_configuration_backups_and_no_original_moves(self):
  r=self.run_enable();self.assertTrue(r['enabled']);self.assertEqual(r['originals_moved'],0);self.assertFalse(r['scan_started']);self.assertTrue(r['synthetic_probe']['no_overwrite'])
  cfg=json.loads((self.app/'config/curation.json').read_bytes());self.assertEqual(cfg['scope'],'indexed_root');self.assertEqual(cfg['max_batch'],100)
  self.assertEqual(json.loads((self.app/'config/config.json').read_bytes()),self.config)
  self.assertEqual(next(self.app.glob('.env.before-curation-*')).read_bytes(),self.env)
  self.assertIn('BIRD_AUTH_HASH=fake$$synthetic',(self.app/'.env').read_text());self.assertTrue((self.app/'config/curation.enabled').exists())
  self.assertEqual((self.library/'未处理/untouched.ARW').read_bytes(),b'generated test file, must not move');self.assertEqual(list((self.library/'待删除').iterdir()),[])
  self.assertEqual(list((self.app/'data/runtime').iterdir()),[])
  self.run_enable();self.assertEqual(json.loads((self.app/'config/curation.json').read_bytes()),cfg)
 def test_failed_probe_does_not_enable_or_change_configuration(self):
  with patch('enable_daily_curation.synthetic_probe',side_effect=ValueError('synthetic probe failed')):
   with self.assertRaises(ValueError):self.run_enable()
  self.assertFalse((self.app/'config/curation.enabled').exists());self.assertFalse((self.app/'config/curation.json').exists());self.assertEqual((self.app/'.env').read_bytes(),self.env)
 def test_wrong_mapping_and_parent_rejected(self):
  with self.assertRaises(ValueError):enable(self.app,self.library,'/elsewhere')
  (self.app/'config/curation.json').write_text(json.dumps({'root_id':'other'}))
  with self.assertRaises(ValueError):self.run_enable()
  self.assertFalse((self.app/'config/curation.enabled').exists())


class DailyDeploymentTests(unittest.TestCase):
 def test_compose_helper_preserves_optional_service_in_both_start_modes(self):
  shell=os.environ.get('BIRD_SH') or shutil.which('sh') or 'sh'
  if not Path(shell).is_file():self.skipTest('POSIX shell unavailable')
  f=Fixture()
  try:
   root=f.base/'compose-test';root.mkdir();(root/'config').mkdir()
   shutil.copy(PROJECT/'deploy/compose-command.sh',root/'helper.sh')
   harness=root/'run.sh';harness.write_text('cd "$BIRD_TEST_DIR"\ndocker() { printf "%s\\n" "$*"; }\n. ./helper.sh\nbird_compose ps\n',encoding='utf-8',newline='\n')
   for online in ('0','1'):
    for enabled in (False,True):
     marker=root/'config/curation.enabled'
     if marker.exists():marker.unlink()
     if enabled:marker.write_text('enabled')
     env={**os.environ,'BIRD_TEST_DIR':root.as_posix(),'BIRD_COMPOSE_ONLINE':online}
     r=subprocess.run([shell,harness.as_posix()],env=env,capture_output=True,text=True,timeout=20)
     self.assertEqual(r.returncode,0,r.stderr);self.assertEqual('compose.offline.yaml' in r.stdout,online=='0');self.assertEqual('compose.curation.yaml' in r.stdout,enabled)
   for name in ('start-nas.sh','start-nas-offline.sh'):
    r=subprocess.run([shell,'-n',str(PROJECT/'deploy'/name)],capture_output=True,text=True,timeout=20)
    self.assertEqual(r.returncode,0,r.stderr)
  finally:f.close()
 def test_upgrade_preserves_overlay_and_enable_stops_on_probe_failure(self):
  shell=os.environ.get('BIRD_SH') or shutil.which('sh') or 'sh'
  if not Path(shell).is_file():self.skipTest('POSIX shell unavailable')
  f=Fixture()
  try:
   root=f.base/'deploy-test';root.mkdir();(root/'config').mkdir();(root/'config/config.json').write_text('{}');(root/'.env').write_text('# synthetic')
   shutil.copytree(PROJECT/'deploy',root/'deploy')
   harness=root/'run.sh';harness.write_text('''set -eu
cd "$BIRD_TEST_DIR"
date() { printf 20261026010000; }
id() { printf 1000; }
docker() {
 printf '%s\\n' "$*" >> "$BIRD_TEST_LOG"
 case "$*" in
  *"ps -q index"*) printf synthetic-index;;
  "inspect --format"*)
   case "$*" in *".Source"*) printf '/volume1/照片/未处理';; *) printf false;; esac;;
  *"exec -T index"*) if [ "$BIRD_TEST_MODE" = busy ]; then return 7; fi;;
  "run --rm"*)
   if [ "$BIRD_TEST_MODE" = probe-failed ]; then return 8; fi
   printf 'enabled' > config/curation.enabled;;
 esac
 return 0
}
. "./deploy/$BIRD_SCRIPT.sh"
''',encoding='utf-8',newline='\n')
   for script,mode,enabled in [('upgrade-culling','ok',False),('upgrade-culling','ok',True),('upgrade-culling','busy',True),('enable-curation','ok',False),('enable-curation','probe-failed',False)]:
    marker=root/'config/curation.enabled'
    if marker.exists():marker.unlink()
    if enabled:marker.write_text('enabled')
    log=root/(script+'-'+mode+'-'+str(enabled)+'.log')
    env={**os.environ,'BIRD_TEST_DIR':root.as_posix(),'BIRD_TEST_LOG':log.as_posix(),'BIRD_TEST_MODE':mode,'BIRD_SCRIPT':script}
    result=subprocess.run([shell,harness.as_posix()],env=env,capture_output=True,text=True,encoding='utf-8',timeout=20);calls=log.read_text(encoding='utf-8')
    if mode=='ok':
     self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('--wait --wait-timeout 120',calls)
     if enabled or script=='enable-curation':self.assertIn('-f compose.curation.yaml up',calls);self.assertIn('index organizer',calls)
     else:self.assertNotIn('compose.curation.yaml',calls)
    else:self.assertNotEqual(result.returncode,0);self.assertNotIn('up -d',calls)
    if script=='enable-curation':
     self.assertIn('--network none',calls);self.assertIn('--cap-drop ALL',calls);self.assertNotIn('chmod',calls)
  finally:f.close()


if __name__=='__main__':unittest.main()
