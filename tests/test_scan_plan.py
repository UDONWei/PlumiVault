"""Incremental confirmation uses only temporary synthetic files, never real photos."""
import json,os,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_prototype import Fixture
from bird_index.scan_plan import ScanPlans
from bird_index.db import Conflict
from bird_index import folders
from bird_index.common import digest

class ScanPlanTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.f.cfg.update(max_files_per_job=0,require_folder_selection=True);self.plans=ScanPlans(self.f.jobs)
 def tearDown(self):self.f.close()
 def preview(self,**kwargs):return self.plans.preview('fixture',['picked'],**kwargs)
 def commit(self,p,paths=None):return self.plans.commit(p['preview_token'],paths if paths is not None else [i['path'] for i in p['items']])['id']
 def test_preview_has_no_writes_then_only_confirmed_subset_runs(self):
  for name in ('picked/a.jpg','picked/sub/b.ARW','outside/never.jpg'):self.f.file(name)
  before={p:(digest(p),p.stat().st_mtime_ns) for p in self.f.root.rglob('*') if p.is_file()}
  plan=self.preview();self.assertEqual(plan['counts']['new'],2);self.assertEqual(self.f.db.query('SELECT * FROM jobs'),[]);self.assertEqual(self.f.db.query('SELECT * FROM photos'),[]);self.assertEqual(self.f.processor.calls,[])
  self.f.file('picked/arrived-after-preview.jpg')
  job=self.commit(plan,['picked/a.jpg']);self.f.jobs.run_one(job)
  self.assertEqual(self.f.processor.calls,['picked/a.jpg']);self.assertEqual(self.f.jobs.state(job),'completed')
  self.assertEqual(before,{p:(digest(p),p.stat().st_mtime_ns) for p in before})
  with self.assertRaises(Conflict):self.commit(plan)
 def test_unchanged_skips_even_after_pipeline_upgrade_and_changed_list_preserves_manual(self):
  a=self.f.file('picked/a.jpg');self.f.file('picked/b.ARW');self.f.jobs.run_one(self.commit(self.preview()))
  self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird beta']);manual=self.f.lib.items([1])[0]['manual']
  self.f.cfg['pipeline_version']='new-version-does-not-force-unchanged'
  plan=self.preview();self.assertEqual(plan['items'],[]);self.assertEqual(plan['counts']['unchanged'],2)
  a.write_bytes(b'synthetic update with different length');plan=self.preview();self.assertEqual(plan['items'][0]['photo_id'],1);self.assertEqual(plan['items'][0]['reason'],'updated')
  job=self.commit(plan);self.f.jobs.run_one(job);self.assertEqual(self.f.processor.calls.count('picked/b.ARW'),1)
  current=self.f.lib.items([1])[0]['manual'];self.assertEqual(current['species'],manual['species']);self.assertEqual(current['revision'],manual['revision']);self.assertTrue(current['stale'])
 def test_changed_between_preview_and_commit_is_atomic_failure(self):
  self.f.file('picked/a.jpg');b=self.f.file('picked/b.jpg');p=self.preview();b.write_bytes(b'new content')
  with self.assertRaises(Conflict):self.commit(p)
  self.assertEqual(self.f.db.query('SELECT * FROM jobs'),[]);self.assertEqual(self.f.db.query('SELECT * FROM photos'),[])
 def test_changed_while_queued_is_not_processed_and_pauses(self):
  a=self.f.file('picked/a.jpg');job=self.commit(self.preview());a.write_bytes(b'new data')
  self.f.jobs.run_one(job);self.assertEqual(self.f.processor.calls,[]);self.assertEqual(self.f.jobs.state(job),'paused')
 def test_failed_item_needs_explicit_confirmation_and_missing_only_reported(self):
  a=self.f.file('picked/a.jpg');b=self.f.file('picked/b.jpg');self.f.processor.fail.add('picked/b.jpg');self.f.jobs.run_one(self.commit(self.preview()))
  a.unlink();p=self.preview();self.assertEqual(p['counts']['retry'],1);self.assertEqual(p['missing'][0]['path'],'picked/a.jpg')
  self.assertEqual(self.f.db.query('SELECT source_status FROM photos WHERE id=1')[0]['source_status'],'available')
  self.assertEqual(len(self.f.processor.calls),2)
 def test_paths_caps_expiry_and_busy_guards(self):
  self.f.file('picked/a.jpg');self.f.file('picked/b.jpg');p=self.preview(limit=1)
  for paths in ([],['picked/a.jpg']*2,['outside/no.jpg']):
   with self.assertRaises(ValueError):self.commit(p,paths)
  with self.assertRaises(ValueError):self.commit(p)
  job=self.commit(p,['picked/a.jpg']);second=self.preview()
  with self.assertRaises(Conflict):self.commit(second,['picked/b.jpg'])
  self.f.jobs.run_one(job)
  self.plans.pending[second['preview_token']]['created']-=1801
  with self.assertRaises(Conflict):self.commit(second,['picked/b.jpg'])
  with self.assertRaises(ValueError):self.plans.preview('fixture',['../outside'])
  for value in (-1,True,'0'):
   with self.assertRaises(ValueError):self.preview(limit=value)
 def test_allowlist_and_root_files_only(self):
  self.f.file('one.jpg');self.f.file('picked/allowed.jpg');self.f.file('picked/not-allowed.jpg')
  with self.f.db.transaction() as c:c.execute('UPDATE roots SET allow_paths=? WHERE id=?',(json.dumps(['one.jpg','picked/allowed.jpg']),'fixture'))
  p=self.preview();self.assertEqual([i['path'] for i in p['items']],['picked/allowed.jpg'])
  p=self.plans.preview('fixture',['.']);self.assertEqual([i['path'] for i in p['items']],['one.jpg'])
 def test_indexed_catalog_is_metadata_only_and_date_sort_unknown_last(self):
  self.f.file('picked/sub/a.jpg');self.f.file('picked/b.jpg');self.f.jobs.run_one(self.commit(self.preview()))
  with patch('os.scandir',side_effect=AssertionError('catalog must not scan originals')),patch.object(Path,'stat',side_effect=AssertionError('catalog must not stat originals')):
   rows=folders.catalog(self.f.lib)
  self.assertEqual({p['path']:p['count'] for p in rows},{'picked':2,'picked/sub':1})
  self.assertEqual(len(self.f.lib.listing({'mode':'photos','subfolder':'picked/sub'})['items']),1)
  for folder in ('20260813&测试','20260101早期','20261350无效','普通目录'):(self.f.root/folder).mkdir()
  result=folders.listing(self.f.lib,'fixture',sort='date_desc');self.assertEqual([r['name'] for r in result['items'][:2]],['20260813&测试','20260101早期'])
  self.assertEqual(next(r for r in result['items'] if r['path']=='picked')['ready'],2)
  rows=folders.listing(self.f.lib,'fixture',sort='name_desc')['items'];self.assertEqual([r['name'] for r in rows],sorted([r['name'] for r in rows],key=str.casefold,reverse=True))

class DecodeOptimizationTests(unittest.TestCase):
 def test_full_raw_does_not_extract_discarded_preview(self):
  import numpy as np
  import types,stage1_probe
  class Raw:
   sizes=types.SimpleNamespace(flip=0,width=8,height=6,_asdict=lambda:{'width':8,'height':6})
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def open_file(self,path):pass
   def extract_thumb(self):raise AssertionError('full decode must not extract preview')
   def unpack(self):pass
   def postprocess(self,**kw):return np.full((6,8,3),90,dtype=np.uint8)
  raw=Raw();info={};times={}
  with patch.dict('sys.modules',{'rawpy':types.SimpleNamespace(RawPy=lambda:raw,ColorSpace=types.SimpleNamespace(sRGB=1))}),patch.object(stage1_probe,'metadata',return_value={}):
   image=stage1_probe.decode(Path('synthetic.ARW'),'full',1600,info,times)
  self.assertEqual(image.getpixel((0,0)),(90,90,90));self.assertEqual(info['decode_route'],'full_raw_in_memory');self.assertNotIn('preview_s',times);image.close()
 def test_neutral_tone_lut_is_identity(self):
  from bird_index.adjustments import recipe,tone_lut
  self.assertEqual(tone_lut(recipe()),list(range(256)))

if __name__=='__main__':unittest.main()
