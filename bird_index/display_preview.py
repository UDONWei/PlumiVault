"""Bounded display derivatives. Never feed enhanced pixels into inference or scoring."""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from .adjustments import recipe
from .common import PROJECT, FORMATS, encode, load_config, safe_file
from .db import Conflict
from .preview import PreviewBusy

VERSION = 'display-v1'
EDGE = 2048
MAX_BYTES = 1024 * 1024
MODES = ('raw', 'auto')


def cache_key(sha, box):
    return hashlib.sha256(encode([VERSION, sha, recipe({'box': box})['box']]).encode()).hexdigest()


def subject(image, box):
    """Resize directly from the full-resolution crop; no full-frame copy or upscale."""
    from PIL import Image
    box = recipe({'box': box})['box'] or [0, 0, 1, 1]
    bounds = (box[0]*image.width, box[1]*image.height, box[2]*image.width, box[3]*image.height)
    width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
    scale = min(1., EDGE/max(width, height))
    return image.resize((max(1, int(width*scale)), max(1, int(height*scale))), Image.Resampling.LANCZOS, box=bounds)


def enhance(image):
    """Conservative, adaptive luminance adjustments and mild local clarity, not restoration."""
    from PIL import Image, ImageFilter, ImageStat
    ycc = image.convert('YCbCr')
    y, cb, cr = ycc.split()
    try:
        mean = ImageStat.Stat(y).mean[0]/255
        shadows = min(.18, max(.03, (.55-mean)*.35))
        highlights = .10 if mean > .55 else .05
        lut = []
        for i in range(256):
            x = i/255
            # Preserve black/white endpoints and avoid falsely recovering clipped detail.
            value = x + shadows*4*x*(1-x)**3 - highlights*4*(1-x)*x**3
            value += .08*(value-.5)*value*(1-value)
            lut.append(round(255*max(0, min(1, value))))
        toned = y.point(lut)
        try:
            clarity = toned.filter(ImageFilter.UnsharpMask(radius=1.3, percent=35, threshold=3))
            try:
                merged = Image.merge('YCbCr', (clarity, cb, cr))
                try:return merged.convert('RGB')
                finally:merged.close()
            finally:clarity.close()
        finally:toned.close()
    finally:
        y.close();cb.close();cr.close();ycc.close()


def jpeg(image):
    """Keep dimensions and a strict wire-size bound, even for noisy synthetic inputs."""
    for quality in (88, 82, 74, 64, 50, 35, 20, 10, 1):
        out = io.BytesIO();image.save(out, 'JPEG', quality=quality)
        payload = out.getvalue()
        if len(payload) <= MAX_BYTES:return payload
    raise ValueError('高清预览超过单图大小限制')


def cache_path(cfg):
    return Path(cfg['data_dir'])/'display-previews.sqlite3'


def cached(cfg, key, mode=None):
    if mode is not None and mode not in MODES:raise ValueError('预览模式无效')
    path = cache_path(cfg)
    if not path.exists():return None
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='previews' AND type='table'").fetchone():return None
        column = '1' if mode is None else mode
        row = db.execute('SELECT '+column+' FROM previews WHERE key=?', (key,)).fetchone()
        return row[0] if row else None


def store(cfg, sha, box, image):
    """A private disposable SQLite cache makes pair writes/eviction atomic, with no orphan JPEGs."""
    if max(image.size) > EDGE:raise ValueError('高清预览边长超限')
    raw = jpeg(image)
    with enhance(image) as adjusted:auto = jpeg(adjusted)
    key = cache_key(sha, box);size = len(raw)+len(auto)
    budget = cfg.get('display_preview_budget_mb', 512)*1024**2
    if size > budget:raise ValueError('高清预览缓存限额不足')
    path = cache_path(cfg)
    with contextlib.closing(sqlite3.connect(path, timeout=5)) as db:
        db.execute('PRAGMA auto_vacuum=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS previews(key TEXT PRIMARY KEY, raw BLOB NOT NULL, auto BLOB NOT NULL, bytes INTEGER NOT NULL, created REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM previews WHERE key=?', (key,))
        used, count = db.execute('SELECT COALESCE(SUM(bytes),0),COUNT(*) FROM previews').fetchone()
        for old_key, old_size in db.execute('SELECT key,bytes FROM previews ORDER BY created,key').fetchall():
            if used+size <= budget and count < 1024:break
            db.execute('DELETE FROM previews WHERE key=?', (old_key,));used -= old_size;count -= 1
        db.execute('INSERT INTO previews VALUES(?,?,?,?,?)', (key, raw, auto, size, time.time()))
        db.commit()
    return {'key': key, 'size': list(image.size), 'bytes': size, 'version': VERSION}


def snapshot(lib, photo_id, sha, revision):
    photo = lib.photo_source(photo_id)
    if not sha or photo['sha256'] != sha:raise Conflict('照片版本已改变，请刷新图库')
    adjust = lib.adjustment(photo_id)
    if type(revision) is not int or adjust['revision'] != revision:raise Conflict('裁切参数已改变，请刷新图库')
    if adjust['source_sha'] and adjust['source_sha'] != sha:raise Conflict('框选对应旧原片，请先重新核对')
    path = safe_file(lib.root(photo['root_id'])['path'], photo['rel_path']);stat = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (photo['size'], photo['mtime_ns']):raise Conflict('原片已变化，请先检查目录变更')
    row = json.loads(photo['summary'])
    box = adjust['recipe']['box'] or (row.get('detection') or {}).get('selected_box')
    # An explicitly saved reset clears a previous manual crop. Automatic detection remains usable.
    if adjust['revision'] and not adjust['recipe']['box'] and row.get('detection', {}).get('status') == 'manual':box = None
    box = recipe({'box': box})['box']
    return photo, box, cache_key(sha, box)


def status(lib, photo_id, sha, revision):
    _, _, key = snapshot(lib, photo_id, sha, revision)
    return {'key': key, 'ready': bool(cached(lib.cfg, key)), 'edge': EDGE}


def read(lib, photo_id, sha, revision, key, mode):
    _, _, current = snapshot(lib, photo_id, sha, revision)
    if key != current:raise Conflict('主体裁切已改变，请重新加载')
    return cached(lib.cfg, key, mode)


def generate(lib, photo_id, sha, revision):
    if not lib.image_lock.acquire(blocking=False):raise PreviewBusy('正在处理照片，请等当前照片完成后重试')
    try:
        photo, box, key = snapshot(lib, photo_id, sha, revision)
        if cached(lib.cfg, key):return {'key': key, 'ready': True, 'cached': True}
        request = {'root_id': photo['root_id'], 'relative_path': photo['rel_path'], 'sha256': sha, 'box': box}
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'bird_index.display_preview', '--config', lib.cfg['_path']],
                                input=encode(request).encode(), capture_output=True, cwd=PROJECT, timeout=150, creationflags=flags)
        if result.returncode:raise ValueError('高清预览生成失败：'+result.stdout.decode('utf-8', 'replace')[-500:])
        metadata = json.loads(result.stdout)
        _, _, latest = snapshot(lib, photo_id, sha, revision)
        if latest != key:raise Conflict('生成期间裁切已改变，请重新加载')
        return {'key': key, 'ready': True, 'cached': False, **metadata}
    except subprocess.TimeoutExpired as exc:raise ValueError('高清预览生成超时，请稍后重试') from exc
    finally:lib.image_lock.release()


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--config', required=True)
    cfg = load_config(parser.parse_args().config);request = json.load(sys.stdin)
    from stage1_probe import install_guard, decode, fingerprint
    install_guard(Path(cfg['data_dir']))
    try:
        root = next(r for r in cfg['roots'] if r['id'] == request['root_id'])
        rel = request['relative_path']
        if root.get('allow_paths') is not None and rel not in root['allow_paths']:raise ValueError('照片不在授权清单内')
        path = safe_file(root['path'], rel)
        if path.suffix.lower() not in FORMATS:raise ValueError('格式不支持')
        before = fingerprint(path, True)
        if before['sha256'] != request['sha256']:raise ValueError('原片与索引不符，请先检查目录变更')
        timings = {};started = time.perf_counter()
        with contextlib.redirect_stdout(sys.stderr):
            with decode(path, 'full', 1600, {}, timings) as image:
                preview = subject(image, request['box'])
            with preview:
                if fingerprint(path, True) != before:raise ValueError('生成期间原片变化，未保存预览')
                result = store(cfg, before['sha256'], request['box'], preview)
        print(encode({**result, 'total_s': time.perf_counter()-started, 'source_unchanged': True}))
    except Exception as exc:
        print(encode({'error': str(exc)}));raise SystemExit(1)


if __name__ == '__main__':main()
