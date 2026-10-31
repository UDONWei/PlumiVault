"""Synthetic pixels and metadata, never private photos or downloaded weights."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageFilter
from test_prototype import Fixture
from bird_index.quality import assess
from bird_index.quality_models import eye_reference,semantic_reference,PROMPTS,combine,unknown,VERSION,QualityModels
from bird_index import quality_feedback as feedback
from bird_index.common import encode
from bird_index.db import Conflict


class QualityReferenceTests(unittest.TestCase):
 def test_eye_local_detail_degrades_with_blur_and_abstains_on_missing_points(self):
  a=np.indices((400,400)).sum(axis=0)//4%2*180+30
  with Image.fromarray(a.astype('uint8')).convert('RGB') as sharp,sharp.filter(ImageFilter.GaussianBlur(4)) as blurred:
   output=np.zeros((1,23,1),dtype=np.float32);output[0,4,0]=.9;output[0,8:11,0]=[320,320,.99]
   good=eye_reference(sharp,output);soft=eye_reference(blurred,output)
   self.assertGreater(good['score'],soft['score']);self.assertEqual(good['points'][0]['x'],.5)
   output[0,10,0]=.3;self.assertIsNone(eye_reference(sharp,output)['score'])
   output[0,10,0]=.99;output[0,8,0]=-100;self.assertIsNone(eye_reference(sharp,output)['score'])
   output[0,4,0]=.1;self.assertEqual(eye_reference(sharp,output)['status'],'unknown')
 def test_semantic_tie_unknown_and_scores_not_probabilities(self):
  self.assertIsNone(semantic_reference([.3,.301,.3],PROMPTS['occlusion'])['score'])
  clear=semantic_reference([.4,.2,.1],PROMPTS['occlusion']);hidden=semantic_reference([.1,.2,.4],PROMPTS['occlusion'])
  self.assertGreater(clear['score'],hidden['score']);self.assertEqual(hidden['category'],'heavy')
  for invalid in ([1,2],[float('nan'),0,1]):
   with self.assertRaises(ValueError):semantic_reference(invalid,PROMPTS['posture'])
 def test_unknown_never_improves_score_and_missing_model_is_explicit(self):
  with Image.new('RGB',(80,80),(120,120,120)) as image:
   base=assess(image,[.1,.1,.9,.9]);reference={'model_key':'synthetic','eye':unknown('missing'),'occlusion':unknown('missing'),'posture':unknown('missing')}
   result=combine(base,reference);self.assertEqual(result['score'],base['score']);self.assertEqual(len(result['score_components']),1)
   reference['eye']={'status':'reference','score':0,'label':'soft'};self.assertLess(combine(base,reference)['score'],base['score'])
  with patch('bird_index.quality_models.manifest_path',return_value=Path('no-synthetic-manifest')),patch('bird_index.quality_models.cache_key',return_value='missing'):
   model=QualityModels({'model_dir':'synthetic'},type('Model',(),{'engine':None})())
   self.assertEqual(model.assess(None,None)['status'],'unavailable')


class QualityFeedbackTests(unittest.TestCase):
 def test_http_feedback_token_revision_and_export(self):
  import threading,urllib.request,urllib.error
  from bird_index.server import Server
  server=Server(('127.0.0.1',0),self.f.lib,self.f.jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  def call(path,value=None,authorized=True):
   headers={'Content-Type':'application/json'}
   if authorized:headers['X-Bird-Token']=server.token
   request=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,data=json.dumps(value).encode() if value is not None else None,headers=headers)
   try:
    with urllib.request.urlopen(request,timeout=5) as response:return response.status,json.load(response)
   except urllib.error.HTTPError as error:return error.code,json.load(error)
  try:
   payload=self.request(focus='clear',posture='good')
   self.assertEqual(call('/api/quality-feedback',payload,False)[0],403)
   status,saved=call('/api/quality-feedback',payload);self.assertEqual(status,200);self.assertEqual(saved['revision'],1)
   self.assertEqual(call('/api/quality-feedback',payload)[0],409)
   status,exported=call('/api/export/quality-feedback');self.assertEqual(status,200);self.assertEqual(exported['photos'][0]['values']['focus'],'clear')
  finally:server.shutdown();server.server_close();thread.join()
 def setUp(self):
  self.f=Fixture();self.f.file('fixture/a.jpg');self.f.scan();self.set_quality({'version':VERSION,'score':70,'source_sha':self.f.lib.items()[0]['sha256'],'recipe':{},'ai':{'status':'reference'}})
 def tearDown(self):self.f.close()
 def set_quality(self,q):
  with self.f.db.transaction() as c:
   row=json.loads(c.execute('SELECT summary FROM photos WHERE id=1').fetchone()[0]);row['quality']=q;c.execute('UPDATE photos SET summary=? WHERE id=1',(encode(row),))
 def request(self,**values):
  p=self.f.lib.public(self.f.lib.items([1])[0]);return {'photo_id':1,'source_sha':p['sha256'],'quality_key':p['quality_key'],'revision':p['quality_feedback']['revision'],'values':values}
 def test_local_corrections_export_backup_and_no_score_or_manual_mutation(self):
  original=self.f.lib.public(self.f.lib.items()[0]);before=self.f.lib.export_reviews()['photos']
  with patch.object(Path,'open',side_effect=AssertionError('feedback must not open images')):
   saved=feedback.save(self.f.lib,self.request(focus='defocus',occlusion='partial',posture='good',note='合成反馈'))
   exported=feedback.export(self.f.lib)
  current=self.f.lib.public(self.f.lib.items()[0]);self.assertEqual(saved['revision'],1);self.assertFalse(saved['stale']);self.assertEqual(current['quality'],original['quality']);self.assertEqual(self.f.lib.export_reviews()['photos'],before)
  self.assertEqual(exported['photos'][0]['prediction'],original['quality']);self.assertFalse(exported['automatic_training'])
  self.assertTrue(self.f.db.backup().is_file())
 def test_revision_source_and_output_conflicts_and_history_bound(self):
  request=self.request(focus='clear');feedback.save(self.f.lib,request)
  with self.assertRaises(Conflict):feedback.save(self.f.lib,request)
  for _ in range(13):feedback.save(self.f.lib,self.request(focus='uncertain'))
  self.assertEqual(len(feedback.export(self.f.lib)['photos'][0]['history']),10)
  request=self.request(focus='clear');self.set_quality({'version':VERSION,'score':20,'recipe':{}})
  with self.assertRaises(Conflict):feedback.save(self.f.lib,request)
  self.assertTrue(self.f.lib.public(self.f.lib.items()[0])['quality_feedback']['stale'])
 def test_edits_auth_scope_and_invalid_labels(self):
  for values in ({'focus':'fake'},{'secret':'no'},{'note':'x'*501}):
   with self.assertRaises(ValueError):feedback.save(self.f.lib,self.request(**values))
  request=self.request(focus='clear');self.f.lib.save_adjustment(1,request['source_sha'],0,{'brightness':20})
  with self.assertRaises(Conflict):feedback.save(self.f.lib,request)
  self.f.cfg['roots'][0]['allow_paths']=[]
  with self.assertRaises(ValueError):feedback.save(self.f.lib,request)
  self.assertEqual(feedback.export(self.f.lib)['photos'],[])


if __name__=='__main__':unittest.main()
