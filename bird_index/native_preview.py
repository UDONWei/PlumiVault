"""Lossless decoded-pixel crops; created only during explicit processing."""
import hashlib,io,json,sqlite3,contextlib,time
from pathlib import Path
from .common import encode
from .adjustments import recipe
from .db import Conflict

BUDGET=2*1024**3
MAX_BYTES=256*1024**2

def key(sha,box):return hashlib.sha256(encode(['native-png-v1',sha,recipe({'box':box})['box']]).encode()).hexdigest()
def path(cfg):return Path(cfg['data_dir'])/'native-previews.sqlite3'

def store(cfg,sha,box,image):
    box=recipe({'box':box})['box'] or [0,0,1,1]
    bounds=(int(box[0]*image.width),int(box[1]*image.height),max(int(box[0]*image.width)+1,int(box[2]*image.width)),max(int(box[1]*image.height)+1,int(box[3]*image.height)))
    with image.crop(bounds) as crop:
        size=list(crop.size);buffer=io.BytesIO();crop.save(buffer,'PNG',compress_level=1);pixels=buffer.getvalue()
    if len(pixels)>MAX_BYTES:return {'available':False,'reason':'原像素缓存超过单图限额'}
    cache_key=key(sha,box)
    with contextlib.closing(sqlite3.connect(path(cfg),timeout=15)) as db:
        db.execute('PRAGMA auto_vacuum=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS crops(key TEXT PRIMARY KEY,pixels BLOB NOT NULL,bytes INTEGER NOT NULL,created REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE');db.execute('DELETE FROM crops WHERE key=?',(cache_key,))
        used=db.execute('SELECT COALESCE(SUM(bytes),0) FROM crops').fetchone()[0]
        for old,n in db.execute('SELECT key,bytes FROM crops ORDER BY created').fetchall():
            if used+len(pixels)<=BUDGET:break
            db.execute('DELETE FROM crops WHERE key=?',(old,));used-=n
        db.execute('INSERT INTO crops VALUES(?,?,?,?)',(cache_key,pixels,len(pixels),time.time()));db.commit()
    return {'available':True,'key':cache_key,'size':size,'bytes':len(pixels),'format':'PNG','resized':False}

def read(lib,pid,sha,region=None):
    photo=lib.photo_source(pid)
    if not sha or photo['sha256']!=sha:raise Conflict('照片版本改变，请刷新')
    row=json.loads(photo['summary'])
    if region:
        from .bird_regions import scene
        bird=next((r for r in scene(row,sha,lib.db.meta('bird_regions:'+str(pid)))['items'] if r['id']==region),None)
        if bird is None:raise ValueError('鸟体框无效')
        box=bird['box']
    else:
        adjust=lib.adjustment(pid)
        if adjust['source_sha'] not in (None,sha):raise Conflict('裁切版本已失效')
        box=adjust['recipe']['box'] or row.get('detection',{}).get('selected_box') or [0,0,1,1]
    cache=path(lib.cfg)
    if not cache.exists():return None
    with contextlib.closing(sqlite3.connect(cache.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        result=db.execute('SELECT pixels FROM crops WHERE key=?',(key(sha,box),)).fetchone()
    return result[0] if result else None
