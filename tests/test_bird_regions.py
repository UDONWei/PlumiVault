"""Synthetic multi-bird metadata; no real photos or model inference."""
import json,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
from test_prototype import Fixture,LABELS
from bird_index.bird_regions import detected,save,scene
from bird_index.common import encode
from bird_index.db import Conflict,Database
from bird_index.library import Library
from bird_index import display_preview


class BirdRegionsTests(unittest.TestCase):
 def setUp(self):
  self.f=Fixture();self.f.file('multi.jpg');self.f.scan();self.row=json.loads(self.f.db.query('SELECT summary FROM photos')[0]['summary'])
  self.row['detection']={'status':'detected','selected_box':[.05,.05,.4,.5],'detections':[{'box':[.1,.1,.3,.4],'score':.9},{'box':[.6,.3,.9,.8],'score':.8}]}
  self.store();self.sha=self.f.lib.items()[0]['sha256']
 def tearDown(self):self.f.close()
 def store(self):
  with self.f.db.transaction() as c:c.execute('UPDATE photos SET summary=?',(encode(self.row),))
 def request(self,index=0,species='Bird alpha'):
  p=self.f.lib.public(self.f.lib.items()[0]);b=p['birds'];return {'photo_id':1,'source_sha':p['sha256'],'scene_key':b['key'],'revision':b['revision'],'region_id':b['items'][index]['id'],'status':'confirmed','species':[species]}
 def test_independent_reviews_survive_reload_and_filter_without_photo_reads(self):
  old=self.f.lib.items()[0]['manual'];self.f.db.review([{'id':1,'revision':0}],'confirmed',['Bird alpha'])
  with patch.object(Path,'open',side_effect=AssertionError('No photo reads for annotations')):
   save(self.f.lib,self.request(0));save(self.f.lib,self.request(1,'Bird beta'))
   public=self.f.lib.public(self.f.lib.items()[0]);self.assertEqual([r['species'] for r in public['birds']['items']],[['Bird alpha'],['Bird beta']])
   for bird in ('Bird alpha','Bird beta'):self.assertEqual(self.f.lib.listing({'species':bird,'mode':'photos'})['total'],1)
   self.assertEqual({r['id'] for r in self.f.lib.summary()['species']},{'Bird alpha','Bird beta'})
  self.assertEqual(public['manual']['revision'],1);self.assertEqual(public['selection']['rating'],0)
  reopened=Library(Database(self.f.data),self.f.cfg);self.assertEqual(reopened.public(reopened.items()[0])['birds'],public['birds']);self.assertTrue(self.f.db.backup().is_file())
  self.assertIn('乙鸟',self.f.lib.export_csv({}).decode('utf-8-sig'))
 def test_conflicts_scope_and_rescan_anchor_retention(self):
  request=self.request();save(self.f.lib,request)
  with self.assertRaises(Conflict):save(self.f.lib,request)
  self.row['detection']['detections'][0]['box']=[.11,.1,.31,.4];self.store()
  p=self.f.lib.public(self.f.lib.items()[0]);self.assertEqual(p['birds']['items'][0]['species'],['Bird alpha']);self.assertEqual(p['birds']['items'][0]['box'],[.1,.1,.3,.4])
  request=self.request(1,'Bird beta');self.row['detection']['detections'][1]['box']=[.7,.3,.95,.8];self.store()
  with self.assertRaises(Conflict):save(self.f.lib,request)
  self.f.cfg['roots'][0]['allow_paths']=[]
  with self.assertRaises(ValueError):save(self.f.lib,self.request())
 def test_source_change_never_reuses_old_bird_identity(self):
  save(self.f.lib,self.request())
  with self.f.db.transaction() as c:c.execute('UPDATE photos SET sha256=?',('b'*64,))
  p=self.f.lib.public(self.f.lib.items()[0]);self.assertTrue(p['birds']['stale_previous']);self.assertEqual(p['birds']['items'][0]['species'],[])
  save(self.f.lib,self.request(1,'Bird beta'));self.assertTrue(json.loads(self.f.db.meta('bird_regions:1'))['history'])
 def test_old_cropped_thumbnail_not_used_and_full_preview_ignores_manual_crop(self):
  p=self.f.lib.public(self.f.lib.items()[0]);self.assertTrue(p['display_full']);self.assertIsNone(p['thumbnail'])
  self.f.lib.save_adjustment(1,self.sha,0,{'box':[.1,.1,.3,.4]})
  _,box,key=display_preview.snapshot(self.f.lib,1,self.sha,1)
  self.assertIsNone(box);self.assertEqual(key,display_preview.cache_key(self.sha,None))
  self.assertEqual(self.f.lib.adjustment(1)['recipe']['box'],[.1,.1,.3,.4],'saved crop remains available')
 def test_http_auth_stale_revision_and_two_birds(self):
  from bird_index.server import Server
  server=Server(('127.0.0.1',0),self.f.lib,self.f.jobs);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  def call(value,auth=True):
   headers={'X-Bird-Token':server.token} if auth else {}
   try:
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+'/api/bird-region',data=encode(value).encode(),headers=headers),timeout=5) as r:return r.status,json.load(r)
   except urllib.error.HTTPError as e:return e.code,json.load(e)
  try:
   first=self.request();self.assertEqual(call(first,False)[0],403);self.assertEqual(call(first)[0],200);self.assertEqual(call(first)[0],409)
   status,result=call(self.request(1,'Bird beta'));self.assertEqual(status,200);self.assertEqual(result['items'][0]['species'],['Bird alpha']);self.assertEqual(result['items'][1]['species'],['Bird beta'])
  finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
