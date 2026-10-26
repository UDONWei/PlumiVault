"""Offline dependency tamper checks and first-scan guard; synthetic files only."""
import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from verify_offline_dependencies import verify


class OfflineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='bird-offline-test-',dir=os.environ.get('BIRD_TEST_TEMP'))
  self.base=Path(self.tmp.name);(self.base/'wheels').mkdir();(self.base/'debs').mkdir()
  data=b'synthetic dependency fixture';self.wheel=self.base/'wheels/demo.whl';self.wheel.write_bytes(data)
  self.manifest={'platform':'linux/amd64','python':'3.12.14','files':[{'path':'wheels/demo.whl','sha256':hashlib.sha256(data).hexdigest()}]};self.write_manifest()
 def write_manifest(self):(self.base/'manifest.json').write_text(json.dumps(self.manifest),encoding='utf-8')
 def tearDown(self):
  expected=Path(os.environ.get('BIRD_TEST_TEMP') or tempfile.gettempdir()).resolve()
  assert self.base.resolve().parent==expected and self.base.name.startswith('bird-offline-test-')
  self.tmp.cleanup()
 def test_tampering_and_extra_wheels_are_rejected(self):
  self.assertEqual(verify(self.base)['offline_files_verified'],1)
  extra=self.base/'wheels/unlisted.whl';extra.write_bytes(b'extra')
  with self.assertRaisesRegex(ValueError,'Unexpected'):verify(self.base)
  extra.unlink();self.wheel.write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'SHA-256'):verify(self.base)
 def test_manifest_path_escape_and_duplicates_are_rejected(self):
  self.manifest['files'][0]['path']='../escape';self.write_manifest()
  with self.assertRaisesRegex(ValueError,'path'):verify(self.base)
  self.manifest['files'][0]['path']='wheels/demo.whl';self.manifest['files']*=2;self.write_manifest()
  with self.assertRaisesRegex(ValueError,'path'):verify(self.base)
 def test_explicit_selection_and_finite_or_unlimited_cap(self):
  config=self.base/'config.json'
  for cap,selection in ((-1,True),(True,True),('0',True),(0,False),(10,False),(10,'true')):
   config.write_text(json.dumps({'max_files_per_job':cap,'require_folder_selection':selection}))
   with self.assertRaisesRegex(ValueError,'NAS configuration'):verify(self.base,config)
  for cap in (0,10,100):
   config.write_text(json.dumps({'max_files_per_job':cap,'require_folder_selection':True}))
   result=verify(self.base,config);self.assertTrue(result['config_checked']);self.assertFalse(result['scan_started'])


if __name__=='__main__':unittest.main()
