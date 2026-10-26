"""Synthetic source metadata and mock RAW pixels only; no private image input."""
import os,sys,subprocess,unittest
import os, shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from test_prototype import Fixture
from bird_index.common import PROJECT,encode
from bird_index.preview import render
import stage1_probe

class PreviewCacheTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.path=self.f.file('screen.jpg')
  with Image.new('RGB',(180,100),'blue') as im:im.save(self.path)
  self.f.scan();self.photo=self.f.lib.items()[0]
 def tearDown(self):self.f.close()
 def test_stat_key_changes_and_is_metadata_only(self):
  with patch('bird_index.common.digest',side_effect=AssertionError('must not hash')):
   a=self.f.lib.preview_version(1);self.assertEqual(a,self.f.lib.preview_version(1));self.assertEqual(a,self.f.lib.editor(1)['preview_version'])
   s=self.path.stat();os.utime(self.path,ns=(s.st_atime_ns,s.st_mtime_ns+1_000_000_000));self.assertNotEqual(a['key'],self.f.lib.preview_version(1)['key'])
  with self.f.db.transaction() as c:c.execute("UPDATE photos SET source_status='quarantined' WHERE id=1")
  with self.assertRaisesRegex(ValueError,'暂存|待删除'):self.f.lib.preview_version(1)
 def test_cache_validation_rejects_missing_or_unauthorized_source(self):
  with self.f.db.transaction() as c:c.execute('UPDATE roots SET allow_paths=?',(encode(['other.jpg']),))
  with self.assertRaises(ValueError):self.f.lib.preview_version(1)
  with self.f.db.transaction() as c:c.execute('UPDATE roots SET allow_paths=NULL')
  self.path.unlink()
  with self.assertRaises((ValueError,FileNotFoundError)):self.f.lib.preview_version(1)
 def test_screen_jpeg_is_bounded_and_full_keeps_size(self):
  with Image.new('RGB',(3200,800),'blue') as im:im.save(self.path)
  self.f.scan(force=True);p=self.f.lib.items()[0]
  screen,_=render(self.f.lib,1,'screen',p['sha256']);full,_=render(self.f.lib,1,'full',p['sha256'])
  self.assertEqual(screen['source_size'],[3200,800]);self.assertEqual(screen['preview_size'],[3072,768]);self.assertEqual(full['preview_size'],[3200,800])
 def test_raw_half_mode_is_opt_in_and_preserves_oriented_dimensions(self):
  calls=[]
  class Raw:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   sizes=SimpleNamespace(width=8,height=6,flip=5,_asdict=lambda:{'width':8,'height':6,'flip':5})
   def open_file(self,path):pass
   def unpack(self):pass
   def postprocess(self,**kw):calls.append(kw);return np.zeros((4,3,3) if kw['half_size'] else (8,6,3),dtype=np.uint8)
  with patch('rawpy.RawPy',Raw),patch.object(stage1_probe,'metadata',return_value={}):
   info={};image=stage1_probe.decode(Path('synthetic.ARW'),'full',1600,info,{},half_size=True)
   self.assertEqual(image.size,(3,4));self.assertEqual(info['oriented_source_size'],[6,8]);self.assertEqual(info['decode_route'],'half_raw_in_memory');image.close()
   image=stage1_probe.decode(Path('synthetic.ARW'),'full',1600,{},{});image.close();self.assertFalse(calls[-1]['half_size'])
 def test_browser_cache(self):
  node=Path(os.environ.get('BIRD_NODE') or shutil.which('node') or 'node')
  r=subprocess.run([str(node),str(PROJECT/'tests/check_preview_cache.js'),str(PROJECT/'web/preview-cache.js')],capture_output=True,text=True,encoding='utf-8',timeout=20)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()
