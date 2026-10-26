"""Synthetic pixels only; genuine user photos are never rendered in these tests."""
import contextlib
import copy
import json
import os
import os, shutil
from pathlib import Path
import subprocess
import sys
import unittest
from PIL import Image
from test_prototype import Fixture,FakeProcessor
import test_prototype
from bird_index.adjustments import recipe,tone_lut,apply_tone,square_input
from bird_index.common import encode,digest,PROJECT
from bird_index.db import Conflict,Database
from bird_index.preview import render,PreviewBusy
from bird_index import folders
from bird_index.search import tokens,locations


class EditorTests(unittest.TestCase):
 def setUp(self):self.f=Fixture()
 def tearDown(self):self.f.close()
 def picture(self,name='test.jpg'):
  p=self.f.file(name)
  with Image.new('RGB',(180,100),(40,70,110)) as im:im.save(p)
  self.f.scan();return p,self.f.lib.items()[-1]
 def test_tone_identity_monotonic_and_owned_pixels(self):
  self.assertEqual(tone_lut({}),list(range(256)))
  for values in ({'brightness':70},{'contrast':-70},{'highlights':-100,'shadows':100}):
   table=tone_lut(values);self.assertEqual(table,sorted(table));self.assertTrue(all(0<=x<=255 for x in table))
  with Image.new('RGB',(3,2),(30,60,100)) as source:
   before=source.tobytes();adjusted=apply_tone(source,{'brightness':30});self.assertEqual(source.tobytes(),before);self.assertGreater(adjusted.getpixel((0,0))[0],30);adjusted.close()
 def test_recipe_rejects_invalid_and_square_keeps_entire_rectangle(self):
  for bad in ({'brightness':float('nan')},{'shadows':True},{'brightness':101},{'box':[-.1,0,.5,1]},{'box':[.5,0,.4,1]},{'unknown':1}):
   with self.assertRaises(ValueError):recipe(bad)
  with Image.new('RGB',(5,3),(200,0,0)) as source:
   padded=square_input(source);self.assertEqual(padded.size,(5,5));self.assertEqual(padded.getpixel((0,1)),(200,0,0));self.assertEqual(padded.getpixel((4,3)),(200,0,0));padded.close()
 def test_original_preview_read_only_and_boundaries(self):
  path,p=self.picture();before=digest(path);metadata,pixels=render(self.f.lib,p['id'],'screen',p['sha256']);self.assertEqual(metadata['source_size'],[180,100]);self.assertTrue(pixels.startswith(b'\xff\xd8'));self.assertTrue(metadata['source_unchanged']);self.assertEqual(before,digest(path))
  self.assertFalse(list(self.f.root.glob('*.xmp')))
  with self.assertRaises(ValueError):render(self.f.lib,p['id'],'screen','0'*64)
  with self.f.lib.image_lock:
   with self.assertRaises(PreviewBusy):render(self.f.lib,p['id'],'full',p['sha256'])
  with self.f.db.transaction() as c:c.execute('UPDATE roots SET allow_paths=?',(encode(['other.jpg']),))
  with self.assertRaises(ValueError):self.f.lib.editor(p['id'])
 def test_preview_rejects_source_changed_outside_index(self):
  path,p=self.picture();path.write_bytes(b'changed synthetic data')
  with self.assertRaisesRegex(ValueError,'内容与索引不符'):render(self.f.lib,p['id'],'screen',p['sha256'])
 def test_adjustment_conflict_and_manual_preservation(self):
  path,p=self.picture();self.f.db.review([{'id':p['id'],'revision':0}],'confirmed',['Bird alpha']);manual=self.f.lib.export_reviews()['photos'];original=self.f.lib.items()[0]['row'];saved=self.f.lib.save_adjustment(p['id'],p['sha256'],0,{'box':[.2,.2,.8,.8],'brightness':40})
  self.assertEqual(saved['revision'],1);self.assertEqual(self.f.lib.export_reviews()['photos'],manual);self.assertEqual(original,self.f.lib.items()[0]['row'])
  with self.assertRaises(Conflict):self.f.lib.save_adjustment(p['id'],p['sha256'],0,{})
  with self.assertRaises(Conflict):self.f.lib.save_adjustment(p['id'],'0'*64,1,{})
  self.assertEqual(self.f.lib.editor(p['id'])['adjustment']['recipe']['brightness'],40)
 def test_single_photo_job_uses_saved_snapshot_and_retains_history(self):
  _,p=self.picture('a.jpg');self.picture('b.jpg');self.f.db.review([{'id':p['id'],'revision':0}],'confirmed',['Bird alpha']);before=self.f.lib.export_reviews()['photos']
  saved=self.f.lib.save_adjustment(p['id'],p['sha256'],0,{'brightness':20});job=self.f.jobs.reprocess(p['id'],p['sha256'],saved['revision'])['id'];self.f.lib.save_adjustment(p['id'],p['sha256'],1,{'brightness':70})
  original=self.f.processor.run;requests=[]
  def run(req):requests.append(copy.deepcopy(req));row=original(req);row['adjustments']=req['adjustment']['recipe'];return row
  self.f.processor.run=run;self.f.jobs.run_one(job);self.assertEqual(len(requests),1);self.assertEqual(requests[0]['adjustment']['recipe']['brightness'],20);self.assertTrue(requests[0]['adjustment']['strict']);self.assertEqual(self.f.lib.export_reviews()['photos'],before);self.assertGreaterEqual(len(self.f.lib.editor(p['id'])['history']),2)
 def test_folder_selection_scope_and_global_limit(self):
  for name in ('a/one.jpg','a/nested/two.jpg','b/three.jpg','c/untouched.jpg','root.jpg'):self.f.file(name)
  self.f.cfg['require_folder_selection']=True
  with self.assertRaises(ValueError):self.f.jobs.create('fixture')
  with self.assertRaises(ValueError):self.f.jobs.create('fixture',scopes=[])
  with self.assertRaises(ValueError):self.f.jobs.create('fixture',scopes=['a','a/nested'])
  job=self.f.jobs.create('fixture',scopes=['a','b'],limit=2)['id'];self.f.jobs.run_one(job);self.assertEqual(len(self.f.processor.calls),2);self.assertTrue(all(p.startswith('a/') for p in self.f.processor.calls));self.assertFalse(any(p['relative_path'].startswith('c/') for p in self.f.lib.items()))
  job=self.f.jobs.create('fixture',scopes=['.'])['id'];self.f.jobs.run_one(job);self.assertEqual(self.f.processor.calls[-1],'root.jpg')
 def test_folder_listing_is_shallow_and_rejects_traversal(self):
  self.f.file('a/nested/private.jpg');self.f.file('b/one.jpg');result=folders.listing(self.f.lib,'fixture');self.assertEqual([r['path'] for r in result['items']],['a','b']);self.assertEqual(self.f.processor.calls,[])
  for bad in ('../models','/photos','a/../b'):
   with self.assertRaises(ValueError):folders.listing(self.f.lib,'fixture',bad)
 def test_unselected_missing_files_not_marked(self):
  self.f.file('a/one.jpg');b=self.f.file('b/two.jpg');self.f.scan();b.unlink();job=self.f.jobs.create('fixture',scopes=['a'])['id'];self.f.jobs.run_one(job);self.assertTrue(all(p['source_status']=='available' for p in self.f.lib.items()))
 def test_folder_context_does_not_relabel_other_folders(self):
  self.f.file('a/one.jpg');self.f.file('b/two.jpg');self.f.scan();before=self.f.lib.export_reviews()['photos'];self.f.lib.context('fixture',{'location':'杭州','region_code':'VIA','use_date':True},'a');items=self.f.lib.items();self.assertEqual(items[0]['row']['capture_context']['location'],'杭州');self.assertEqual(items[1]['row']['capture_context']['location'],'测试地点');self.assertEqual(before,self.f.lib.export_reviews()['photos'])
  self.f.lib.context('fixture',{'location':'天津','region_code':'IIA','use_date':True});self.assertEqual(self.f.lib.effective_context('fixture','a/one.jpg')['location'],'杭州');self.assertEqual(self.f.lib.effective_context('fixture','b/two.jpg')['location'],'天津')
 def test_pinyin_locations_and_bird_aliases(self):
  self.assertIn('fengtoufengying',tokens('凤头蜂鹰'));self.assertIn('ftfy',tokens('凤头蜂鹰'));labels=self.f.lib.labels();self.assertIn('jianiao',labels['Bird alpha']['search']);places=locations(self.f.lib);self.assertTrue(any('hangzhoushi' in r['search'] for r in places['places']));self.assertEqual(len([r for r in places['regions'] if r['kind']=='region']),19)
 def test_database_backup_includes_edit_parameters(self):
  _,p=self.picture();self.f.lib.save_adjustment(p['id'],p['sha256'],0,{'shadows':50});backup=self.f.db.backup();import sqlite3
  with contextlib.closing(sqlite3.connect(backup)) as c:self.assertEqual(json.loads(c.execute('SELECT recipe FROM adjustments').fetchone()[0])['shadows'],50)
 def test_js_crop_curve_and_search(self):
  node=Path(os.environ.get('BIRD_NODE') or shutil.which('node') or 'node');values=[{}, {'brightness':50,'contrast':-10,'highlights':-80,'shadows':60}];data=self.f.base/'curves.json';data.write_text(encode([{'recipe':v,'lut':tone_lut(v)} for v in values]),encoding='utf-8')
  result=subprocess.run([str(node),str(PROJECT/'tests/check_editor_math.js'),str(data)],capture_output=True,text=True,encoding='utf-8');self.assertEqual(result.returncode,0,result.stdout+result.stderr)


class EditorHTTPTests(unittest.TestCase):
 setUp=test_prototype.HTTPTests.setUp
 tearDown=test_prototype.HTTPTests.tearDown
 req=test_prototype.HTTPTests.req
 def test_http_original_and_saved_edit(self):
  path=self.f.root/'a.jpg'
  with Image.new('RGB',(48,36),(60,100,150)) as im:im.save(path)
  self.f.scan(force=True);p=self.f.lib.items()[0];headers={'X-Bird-Token':self.server.token};body={'photo_id':p['id'],'source_sha':p['sha256'],'resolution':'screen'}
  self.assertEqual(self.req('/api/original',body)[0],403);status,pixels=self.req('/api/original',body,headers);self.assertEqual(status,200);self.assertTrue(pixels.startswith(b'\xff\xd8'))
  self.assertEqual(self.req('/api/adjustments',{'photo_id':p['id'],'source_sha':p['sha256'],'revision':0,'recipe':{'highlights':-40}},headers)[0],200)
  self.assertEqual(self.req('/api/reprocess',{'photo_id':p['id'],'source_sha':p['sha256'],'revision':1},headers)[0],200)
 def test_preview_version_endpoint_and_asset(self):
  status,body=self.req('/api/preview-version?id=1');self.assertEqual(status,200);self.assertEqual(json.loads(body)['sha256'],self.f.lib.items()[0]['sha256'])
  status,body=self.req('/preview-cache.js');self.assertEqual(status,200);self.assertIn(b'BirdPreview',body)
  self.server.public_origin='https://192.0.2.10:8443';self.server.gateway_token='g'*40
  self.assertEqual(self.req('/api/preview-version?id=1')[0],403)
 def test_gateway_identity_and_origin(self):
  self.server.public_origin='https://192.0.2.10:8443';self.server.gateway_token='g'*40
  self.assertEqual(self.req('/api/state')[0],403)
  headers={'Host':'192.0.2.10:8443','X-Bird-Gateway':'g'*40,'Origin':'https://192.0.2.10:8443'}
  self.assertEqual(self.req('/api/state',headers=headers)[0],200);headers['Origin']='https://other.example';self.assertEqual(self.req('/api/state',headers=headers)[0],403)
  self.assertEqual(self.req('/health')[0],200)


if __name__=='__main__':unittest.main()
