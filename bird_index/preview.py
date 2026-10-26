"""One-shot, read-only original decoder. JPEG exists only in memory and HTTP."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from .common import PROJECT, FORMATS, encode, load_config, safe_file


class PreviewBusy(ValueError):
    pass


def render(lib, photo_id, resolution, expected_sha):
    if resolution not in ('screen', 'full'):
        raise ValueError('预览分辨率无效')
    photo = lib.photo_source(photo_id)
    if not expected_sha or expected_sha != photo['sha256']:
        raise ValueError('照片版本已改变，请重新打开原图')
    if not lib.image_lock.acquire(blocking=False):
        raise PreviewBusy('当前正在解码或识别一张照片，请稍后再打开；可先暂停扫描任务')
    try:
        request = {'root_id': photo['root_id'], 'relative_path': photo['rel_path'],
                   'sha256': expected_sha, 'resolution': resolution}
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'bird_index.preview',
                                 '--config', lib.cfg['_path']], input=encode(request).encode(),
                                capture_output=True, cwd=PROJECT, timeout=120, creationflags=flags)
        line, separator, pixels = result.stdout.partition(b'\n')
        if not separator:
            raise ValueError('原图解码进程失败：'+result.stderr.decode('utf-8', 'replace')[-500:])
        metadata = json.loads(line)
        if result.returncode or metadata.get('error'):
            raise ValueError(metadata.get('error', '原图解码失败'))
        if len(pixels) != metadata['bytes'] or len(pixels) > 48*1024**2:
            raise ValueError('预览响应大小无效')
        return metadata, pixels
    except subprocess.TimeoutExpired as exc:
        raise ValueError('原图解码超时，请检查文件和资源占用') from exc
    finally:
        lib.image_lock.release()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True)
    cfg = load_config(parser.parse_args().config)
    request = json.load(sys.stdin); protocol = sys.stdout.buffer
    from stage1_probe import decode, fingerprint, install_guard, MemoryMeter
    install_guard(Path(cfg['data_dir']))
    image = None
    try:
        root = next(r for r in cfg['roots'] if r['id'] == request['root_id'])
        relative = request['relative_path']
        if root.get('allow_paths') is not None and relative not in root['allow_paths']:
            raise ValueError('照片不在已授权清单内')
        path = safe_file(root['path'], relative)
        if path.suffix.lower() not in FORMATS:
            raise ValueError('图片格式不支持')
        with MemoryMeter() as meter, contextlib.redirect_stdout(sys.stderr):
            before = fingerprint(path, True)
            if before['sha256'] != request['sha256']:
                raise ValueError('原图内容与索引不符，请先重新扫描这张照片，再重新框选')
            info, timings = {}, {}
            image = decode(path, 'full', 1600, info, timings, half_size=request['resolution'] == 'screen')
            size = info.get('oriented_source_size', list(image.size))
            if size[0]*size[1] > 100_000_000:
                raise ValueError('单张图片超过本版的一亿像素上限')
            if request['resolution'] == 'screen':
                from PIL import Image
                image.thumbnail((3072, 3072), Image.Resampling.LANCZOS)
            data = io.BytesIO(); image.save(data, format='JPEG', quality=88 if request['resolution'] == 'screen' else 92)
            pixels = data.getvalue()
            if fingerprint(path, True) != before:
                raise ValueError('解码期间源文件变化，请重新打开')
            meter.sample()
            metadata = {'source_size': size, 'preview_size': list(image.size), 'sha256': before['sha256'],
                        'bytes': len(pixels), 'timings': timings, 'memory': meter.report(),
                        'decode_route': info.get('decode_route'), 'source_unchanged': True}
        protocol.write(encode(metadata).encode()+b'\n'+pixels); protocol.flush()
    except Exception as exc:
        protocol.write(encode({'error': str(exc)}).encode()+b'\n'); protocol.flush()
        raise SystemExit(1)
    finally:
        if image is not None:
            image.close()


if __name__ == '__main__':
    main()
