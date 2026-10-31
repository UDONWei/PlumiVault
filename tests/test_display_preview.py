"""Synthetic-only high-resolution display and cache regressions."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageStat
from test_prototype import Fixture
from bird_index import display_preview as dp
from bird_index.common import PROJECT, encode, digest
from bird_index.db import Conflict
from bird_index.preview import PreviewBusy


class DisplayPreviewTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.path=self.f.file('synthetic.jpg')
        with Image.new('RGB',(3000,1200),(70,90,80)) as image:image.save(self.path)
        self.f.scan();self.photo=self.f.lib.items()[0];self.sha=self.photo['sha256']

    def tearDown(self):self.f.close()

    def test_crop_full_resolution_without_upscale_or_source_mutation(self):
        with Image.open(self.path) as image:
            before=image.tobytes()
            with dp.subject(image,None) as whole:self.assertEqual(whole.size,(2048,819))
            with dp.subject(image,[.2,.2,.4,.8]) as crop:self.assertEqual(crop.size,(600,720))
            self.assertEqual(image.tobytes(),before)
        for box in ([0,0,2,1],[0,0,float('nan'),1],[0,0,0,1]):
            with self.assertRaises(ValueError):dp.cache_key(self.sha,box)

    def test_auto_is_separate_preserves_size_and_has_bounded_bytes(self):
        pixels=np.random.default_rng(4).integers(0,256,(2048,2048,3),dtype=np.uint8)
        with Image.fromarray(pixels) as image:
            original=image.tobytes()
            with dp.enhance(image) as auto:
                self.assertEqual(auto.size,image.size);self.assertNotEqual(auto.tobytes(),original)
                self.assertLessEqual(len(dp.jpeg(auto)),dp.MAX_BYTES)
            self.assertEqual(image.tobytes(),original)
        with Image.new('RGB',(40,40),(35,35,35)) as dark,dp.enhance(dark) as adjusted:
            self.assertGreater(ImageStat.Stat(adjusted).mean[0],35)

    def test_cache_budget_pair_eviction_and_read_does_not_touch_db(self):
        cfg={**self.f.cfg,'display_preview_budget_mb':.08}
        with Image.fromarray(np.random.default_rng(5).integers(0,256,(180,180,3),dtype=np.uint8)) as image:
            first=dp.store(cfg,'first',None,image)
            latest=dp.store(cfg,'last',None,image)
        self.assertIsNone(dp.cached(cfg,first['key'],'raw'))
        self.assertIsNotNone(dp.cached(cfg,latest['key'],'auto'))
        path=dp.cache_path(cfg);before=(path.stat().st_mtime_ns,digest(path))
        for _ in range(3):self.assertTrue(dp.cached(cfg,latest['key']))
        self.assertEqual((path.stat().st_mtime_ns,digest(path)),before)
        with contextlib.closing(sqlite3.connect(path)) as db:
            self.assertLessEqual(db.execute('SELECT SUM(bytes) FROM previews').fetchone()[0],cfg['display_preview_budget_mb']*1024**2)
        with self.assertRaises(ValueError):dp.cached(cfg,latest['key'],'raw FROM previews; DROP TABLE previews')

    def test_denoise_flat_noise_edges_and_original_separation(self):
        rng=np.random.default_rng(17)
        pixels=np.full((180,240,3),65.,dtype=float);pixels[:,120:,:]=205
        pixels=np.clip(pixels+rng.normal(0,12,pixels.shape),0,255).astype(np.uint8)
        with Image.fromarray(pixels) as image:
            raw=dp.jpeg(image);before=image.tobytes()
            with dp.enhance(image) as enhanced:
                clean=np.asarray(enhanced)
                self.assertLess(clean[15:160,15:100].std(axis=(0,1)).mean(),pixels[15:160,15:100].std(axis=(0,1)).mean())
                self.assertGreater(float(clean[:,130:200].mean()-clean[:,20:100].mean()),110)
            entry=dp.store(self.f.cfg,self.sha,None,image)
            self.assertEqual(dp.cached(self.f.cfg,entry['key'],'raw'),raw)
            self.assertEqual(image.tobytes(),before)
            with patch.object(dp,'VERSION','display-v1'):old=dp.cache_key(self.sha,None)
            self.assertNotEqual(old,entry['key']);self.assertIsNone(dp.cached(self.f.cfg,old))

    def test_browser_studio_zoom(self):
        node=os.environ.get('BIRD_NODE') or shutil.which('node') or 'node'
        result=subprocess.run([node,str(PROJECT/'tests/check_studio_zoom.js'),str(PROJECT/'web/studio-zoom.js')],capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_explicit_generation_cache_hit_and_versions(self):
        original=digest(self.path);before=self.f.lib.items()[0]
        self.assertFalse(dp.status(self.f.lib,1,self.sha,0)['ready'])
        self.assertFalse(dp.cache_path(self.f.cfg).exists()) # Browsing missing cache creates nothing.
        result=dp.generate(self.f.lib,1,self.sha,0)
        self.assertFalse(result['cached']);self.assertTrue(result['source_unchanged'])
        with patch.object(dp.subprocess,'run',side_effect=AssertionError('cache must not decode')):
            self.assertTrue(dp.generate(self.f.lib,1,self.sha,0)['cached'])
        raw=dp.read(self.f.lib,1,self.sha,0,result['key'],'raw')
        auto=dp.read(self.f.lib,1,self.sha,0,result['key'],'auto')
        with Image.open(io.BytesIO(raw)) as r,Image.open(io.BytesIO(auto)) as a:self.assertEqual(r.size,a.size)
        self.assertEqual(digest(self.path),original);self.assertEqual(self.f.lib.items()[0],before)
        self.f.lib.save_adjustment(1,self.sha,0,{'box':[.2,.2,.4,.8],'brightness':50})
        with self.assertRaises(Conflict):dp.read(self.f.lib,1,self.sha,0,result['key'],'raw')
        self.assertFalse(dp.status(self.f.lib,1,self.sha,1)['ready'])
        changed=dp.generate(self.f.lib,1,self.sha,1)
        with Image.open(io.BytesIO(dp.read(self.f.lib,1,self.sha,1,changed['key'],'raw'))) as image:
            self.assertEqual(image.size,(600,720));self.assertLess(ImageStat.Stat(image).mean[0],80) # Ignores manual brightness.
        with self.assertRaises(Conflict):dp.read(self.f.lib,1,self.sha,1,result['key'],'auto')

    def test_source_permissions_stat_changes_and_busy_are_enforced(self):
        self.f.lib.image_lock.acquire()
        try:
            with self.assertRaises(PreviewBusy):dp.generate(self.f.lib,1,self.sha,0)
        finally:self.f.lib.image_lock.release()
        with self.f.db.transaction() as c:c.execute("UPDATE photos SET source_status='quarantined' WHERE id=1")
        with self.assertRaises(ValueError):dp.status(self.f.lib,1,self.sha,0)
        with self.f.db.transaction() as c:
            c.execute("UPDATE photos SET source_status='available' WHERE id=1")
            c.execute('UPDATE roots SET allow_paths=?',(encode(['different.jpg']),))
        with self.assertRaises(ValueError):dp.status(self.f.lib,1,self.sha,0)
        with self.f.db.transaction() as c:c.execute('UPDATE roots SET allow_paths=NULL')
        s=self.path.stat();os.utime(self.path,ns=(s.st_atime_ns,s.st_mtime_ns+1_000_000_000))
        with self.assertRaises(Conflict):dp.status(self.f.lib,1,self.sha,0)

    def test_generation_detects_same_size_mtime_source_replacement_by_hash(self):
        s=self.path.stat();data=bytearray(self.path.read_bytes());data[-10]^=1;self.path.write_bytes(data);os.utime(self.path,ns=(s.st_atime_ns,s.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'原片与索引'):dp.generate(self.f.lib,1,self.sha,0)
        self.assertFalse(dp.cache_path(self.f.cfg).exists())

    def test_scan_reuses_decode_and_keeps_display_tone_out_of_scoring(self):
        import stage1_probe,subject_detector,context_prior,similarity_features,torch
        from bird_index import worker,quality
        from bird_index.adjustments import apply_tone
        source=Image.new('RGB',(600,400),(60,60,60));before=source.tobytes();seen=[]
        class Model:
            labels=[]
            def __init__(self,*args):pass
            def all_scores(self,image):return []
        class Detector:
            def __init__(self,*args):pass
            def detect(self,image):return {'selected_box':[.2,.2,.8,.8]}
        req={'root_id':'fixture','relative_path':'synthetic.jpg','display_path':'fixture/synthetic.jpg','directory':'fixture','context':{},'adjustment':{'recipe':{'brightness':30}}}
        output=io.StringIO()
        with contextlib.ExitStack() as stack:
            for obj,name,value in [(stage1_probe,'install_guard',lambda *_:None),(stage1_probe,'LocalBioCLIP',Model),(subject_detector,'LocalBirdDetector',Detector),
                (context_prior,'load_occurrences',lambda *_:{'regions':[]}),(context_prior,'resolve_context',lambda *_:{}),(context_prior,'rank_scores',lambda *_:{}),
                (similarity_features,'describe',lambda *_:{}),(torch,'set_num_threads',lambda *_:None),(torch,'set_num_interop_threads',lambda *_:None),
                (quality,'assess',lambda image,box:seen.append(image.getpixel((0,0))) or {})]:stack.enter_context(patch.object(obj,name,value))
            decoded=stack.enter_context(patch.object(stage1_probe,'decode',side_effect=lambda *_:source.copy()))
            stack.enter_context(patch.object(sys,'argv',['worker','--config',str(self.f.config)]));stack.enter_context(patch.object(sys,'stdin',io.StringIO(encode(req)+'\n')));stack.enter_context(patch.object(sys,'stdout',output))
            worker.main()
        row=json.loads(output.getvalue().splitlines()[-1])['row'];self.assertNotIn('error',row);self.assertEqual(decoded.call_count,1)
        self.assertEqual(source.tobytes(),before);self.assertGreater(seen[0][0],60)
        key=row['views'][0]['display_preview']['key']
        with Image.open(io.BytesIO(dp.cached(self.f.cfg,key,'raw'))) as image:self.assertAlmostEqual(ImageStat.Stat(image).mean[0],60,delta=2)
        source.close()

    def test_browser_display_cache(self):
        node=os.environ.get('BIRD_NODE') or shutil.which('node') or 'node'
        result=subprocess.run([node,str(PROJECT/'tests/check_display_preview.js'),str(PROJECT/'web/display-preview.js')],capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_http_routes_authentication_and_same_crop_pair(self):
        from bird_index.server import Server
        server=Server(('127.0.0.1',0),self.f.lib,self.f.jobs)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,body=None,token=True):
            headers={'X-Bird-Token':server.token} if token else {}
            req=urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,data=encode(body).encode() if body is not None else None,headers=headers)
            try:
                with urllib.request.urlopen(req,timeout=30) as r:return r.status,r.read(),r.headers
            except urllib.error.HTTPError as e:
                with e:return e.code,e.read(),e.headers
        try:
            query='id=1&sha='+self.sha+'&revision=0'
            code,body,_=request('/api/display-preview?'+query);self.assertEqual(code,200);self.assertFalse(json.loads(body)['ready'])
            body={'photo_id':1,'source_sha':self.sha,'revision':0}
            self.assertEqual(request('/api/display-preview',body,False)[0],403)
            code,payload,_=request('/api/display-preview',body);self.assertEqual(code,200,payload);key=json.loads(payload)['key']
            for mode in dp.MODES:
                code,payload,headers=request('/api/display-image?'+query+'&key='+key+'&mode='+mode)
                self.assertEqual(code,200);self.assertEqual(headers['Content-Type'],'image/jpeg')
                self.assertEqual(headers['Cache-Control'],'no-store')
                with Image.open(io.BytesIO(payload)) as image:self.assertEqual(image.size,(2048,819))
            self.assertEqual(request('/api/display-image?'+query+'&key=wrong&mode=raw')[0],400)
            self.assertEqual(request('/display-preview.js')[0],200)
            self.assertIn(b'/display-preview.js',request('/')[1])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
