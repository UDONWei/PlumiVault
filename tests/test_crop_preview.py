"""NAS-only crop persistence and adjusted scoring. Synthetic pixels, no private photos."""
import base64,io,json,unittest
from unittest.mock import patch
from PIL import Image
from test_prototype import Fixture
from bird_index.thumbs import save_jpeg
from bird_index.quality import score_existing
from bird_index.common import encode,digest

class CropPreviewTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.path=self.f.file('test.jpg')
  with Image.new('RGB',(180,100),(80,70,60)) as im:im.save(self.path)
  self.f.scan();self.photo=self.f.lib.items()[0]
 def tearDown(self):self.f.close()
 def test_saved_crop_survives_reload_and_does_not_write_original(self):
  before=digest(self.path);data=io.BytesIO()
  with Image.new('RGB',(60,40),'red') as im:im.save(data,format='JPEG')
  original=self.photo['thumbnail'];saved=self.f.lib.save_adjustment(1,self.photo['sha256'],0,{'box':[.2,.3,.8,.9]},base64.b64encode(data.getvalue()).decode())
  item=self.f.lib.items([1])[0];self.assertNotEqual(item['thumbnail'],original);self.assertEqual(item['thumbnail'],'/thumbs/'+saved['preview']);self.assertEqual(digest(self.path),before)
  from bird_index.library import Library
  self.assertEqual(Library(self.f.db,self.f.cfg).items([1])[0]['thumbnail'],item['thumbnail'])
 def test_rejects_large_or_invalid_thumbnail(self):
  with self.assertRaises(ValueError):save_jpeg(self.f.lib,'invalid base64')
  huge=io.BytesIO()
  with Image.new('RGB',(513,1)) as im:im.save(huge,format='JPEG')
  with self.assertRaises(ValueError):save_jpeg(self.f.lib,base64.b64encode(huge.getvalue()).decode())
 def test_quality_uses_saved_recipe_then_reuses_without_reading_original(self):
  sha=self.photo['sha256'];before=digest(self.path);self.f.lib.save_adjustment(1,sha,0,{'brightness':30,'box':[.2,.2,.8,.8]})
  result=score_existing(self.f.lib,1,sha);self.assertFalse(result['cached']);self.assertEqual(result['quality']['recipe']['brightness'],30);self.assertEqual(digest(self.path),before)
  with patch('bird_index.quality_worker.run',side_effect=AssertionError('must reuse cache')):self.assertTrue(score_existing(self.f.lib,1,sha)['cached'])
  self.f.lib.save_adjustment(1,sha,1,{'brightness':40})
  result=score_existing(self.f.lib,1,sha);self.assertFalse(result['cached']);self.assertEqual(result['quality']['recipe']['brightness'],40)
 def test_reprocessing_replaces_saved_preview_only_if_revision_still_current(self):
  data=io.BytesIO()
  with Image.new('RGB',(32,24),'red') as im:im.save(data,format='JPEG')
  encoded=base64.b64encode(data.getvalue()).decode();a=self.f.lib.save_adjustment(1,self.photo['sha256'],0,{'brightness':10},encoded)
  job=self.f.jobs.reprocess(1,self.photo['sha256'],a['revision'])['id'];self.f.jobs.run_one(job);self.assertIsNone(self.f.lib.adjustment(1)['preview'])
  a=self.f.lib.save_adjustment(1,self.photo['sha256'],1,{'brightness':20},encoded);job=self.f.jobs.reprocess(1,self.photo['sha256'],a['revision'])['id'];a=self.f.lib.save_adjustment(1,self.photo['sha256'],2,{'brightness':50},encoded);self.f.jobs.run_one(job);self.assertEqual(self.f.lib.adjustment(1)['preview'],a['preview'])
if __name__=='__main__':unittest.main()
