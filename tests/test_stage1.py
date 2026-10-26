"""仅合成测试夹具；不代表真实鸟类识别或 A7R IV 样片通过。"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

os.environ['PYTHONUTF8'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'tools'))
import stage1_probe as probe
from PIL import Image


class Boundaries(unittest.TestCase):
    def test_nested_outputs_rejected(self):
        with self.assertRaises(ValueError):
            probe.disjoint(PROJECT, PROJECT / 'photos')

    def test_traversal_and_ads_rejected(self):
        for path in ('../x.jpg', 'x.jpg:stream', 'C:/x.jpg'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                probe.photo_path(PROJECT, path)

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / 'photos'
            root.mkdir()
            outside = base / 'outside.jpg'
            outside.write_bytes(b'fixture')
            try:
                (root / 'link.jpg').symlink_to(outside)
            except OSError:
                self.skipTest('当前 Windows 不允许创建符号链接；未验证')
            with self.assertRaises(ValueError):
                probe.photo_path(root, 'link.jpg')

    def test_crop_edges_and_invalid_boxes(self):
        with Image.new('RGB', (100, 50)) as image:
            cropped, box = probe.crop_box(image, [.1, .2, .5, .8])
            self.assertEqual(cropped.size, (40, 30))
            self.assertEqual(box, (10, 10, 50, 40))
            cropped.close()
            for box in ([0, 0, float('nan'), 1], [0, 0, 2, 1], [1, 0, 0, 1]):
                with self.assertRaises(ValueError):
                    probe.crop_box(image, box)

    def test_guard_in_subprocess(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            photo = base / 'fixture.jpg'
            photo.write_bytes(b'original substitute')
            out = base / 'output'
            out.mkdir()
            code = '''
import sys, socket
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from stage1_probe import install_guard
photo, out = Path(sys.argv[2]), Path(sys.argv[3])
install_guard(out)
for operation in (lambda: photo.write_bytes(b'bad'), lambda: photo.unlink(),
                  lambda: socket.create_connection(('127.0.0.1', 9))):
    try: operation()
    except PermissionError: pass
    else: raise AssertionError('guard did not reject')
(out / 'allowed.txt').write_text('ok')
'''
            result = subprocess.run([sys.executable, '-B', '-c', code, str(PROJECT / 'tools'), str(photo), str(out)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(photo.read_bytes(), b'original substitute')

    def test_synthetic_formats_failure_isolation_and_source_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / '照片 root'
            dated = root / '2026-01-01'
            dated.mkdir(parents=True)
            samples = []
            for fmt, ext in [('JPEG', 'JPG'), ('PNG', 'png'), ('TIFF', 'tif'), ('WEBP', 'webp'), ('BMP', 'bmp')]:
                target = dated / f'合成测试.{ext}'
                with Image.new('RGB', (120, 80), (15, 130, 25)) as image:
                    if fmt == 'JPEG':
                        exif = Image.Exif()
                        exif[274] = 6
                        image.save(target, format=fmt, exif=exif)
                    else:
                        image.save(target, format=fmt)
                samples.append({'path': str(target.relative_to(root)), 'truth': None, 'boxes': [[.1, .2, .5, .8]], 'scenario': 'synthetic_only'})
            bad = dated / '损坏.arw'
            bad.write_bytes(b'synthetic corrupt file, NOT camera sample')
            samples.insert(1, {'path': str(bad.relative_to(root)), 'truth': None})
            samples.append({'path': 'missing.jpg', 'truth': None})
            manifest = base / 'manifest.json'
            manifest.write_text(json.dumps({'samples': samples}, ensure_ascii=False), encoding='utf-8')
            before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            output = base / 'results'
            result = subprocess.run([sys.executable, '-B', str(PROJECT / 'tools/stage1_probe.py'),
                                     '--photos-root', str(root), '--manifest', str(manifest), '--output', str(output),
                                     '--stable-seconds', '0', '--hash-samples', '--thumbnails', '--thumbnail-edge', '64'],
                                    capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['summary']['processed'], 7)
            self.assertEqual(report['summary']['decode_success'], 5)
            self.assertEqual(report['rows'][0]['decoded_size'], [80, 120])
            self.assertIsNone(report['summary']['accuracy'])
            self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()})
            for file in output.glob('*.jpg'):
                with Image.open(file) as image:
                    self.assertLessEqual(max(image.size), 64)
            self.assertEqual(len(list(output.glob('*.jpg'))), 10)


if __name__ == '__main__':
    unittest.main()
