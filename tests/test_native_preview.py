import io,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from test_prototype import Fixture
from bird_index import native_preview as native
from bird_index.db import Conflict

class NativePreviewTests(unittest.TestCase):
 def test_original_resolution_lossless_cache_and_source_version(self):
  f=Fixture()
  try:
   f.file('synthetic.jpg');f.scan();sha=f.lib.items()[0]['sha256'];box=[.1,.1,.9,.9]
   f.lib.save_adjustment(1,sha,0,{'box':box})
   with Image.new('RGB',(3200,2800),(25,76,141)) as image:
    result=native.store(f.cfg,sha,box,image)
    self.assertEqual(result['size'],[2560,2240]);self.assertFalse(result['resized'])
    with patch.object(Path,'open',side_effect=AssertionError('must not read originals')):pixels=native.read(f.lib,1,sha)
    with Image.open(io.BytesIO(pixels)) as restored:self.assertEqual(restored.size,(2560,2240));self.assertEqual(restored.getpixel((50,50)),image.getpixel((370,330)))
   with self.assertRaises(Conflict):native.read(f.lib,1,'wrong')
   self.assertTrue(f.db.backup().exists())
  finally:f.close()
 def test_budget_and_missing_never_decode(self):
  f=Fixture()
  try:
   f.file('synthetic.jpg');f.scan();sha=f.lib.items()[0]['sha256']
   self.assertIsNone(native.read(f.lib,1,sha))
   with Image.new('RGB',(40,40),'blue') as image:
    one=native.store(f.cfg,sha,[0,0,1,1],image)
    with patch.object(native,'BUDGET',one['bytes']+5):native.store(f.cfg,'b'*64,[0,0,1,1],image)
   self.assertIsNone(native.read(f.lib,1,sha))
  finally:f.close()
