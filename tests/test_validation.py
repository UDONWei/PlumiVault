"""Validation collection uses synthetic metadata and never starts inference."""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import unittest
from unittest.mock import patch

from test_prototype import Fixture
import test_prototype
from bird_index import validation
from bird_index.db import Conflict, Database


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        for i in range(1, 5):
            self.f.file(f'burst/{i}.ARW', f'synthetic {i}'.encode())
        self.f.scan()

    def tearDown(self):
        self.f.close()

    def change(self, **value):
        revision = validation.read(self.f.lib)['revision']
        if value.get('action') == 'add':
            value['sources'] = [{'id': p['id'], 'sha256': p['sha256'], 'adjustment_revision': p['edit_revision']} for p in self.f.lib.items(value['ids'])]
        return validation.change(self.f.lib, {'revision': revision, **value})

    def test_persistence_export_and_complete_isolation(self):
        before = {t: self.f.db.query('SELECT * FROM ' + t) for t in
                  ('photos', 'analyses', 'manual', 'selections', 'visibility', 'jobs', 'adjustments')}
        calls = list(self.f.processor.calls)
        generation = self.f.db.meta('generation')
        original_open = Path.open
        photo_root = self.f.root

        def guarded(path, *args, **kwargs):
            if path.is_relative_to(photo_root):
                raise AssertionError('Validation must not read or write originals')
            return original_open(path, *args, **kwargs)

        with patch.object(Path, 'open', guarded), patch.object(self.f.lib, 'photo_source', side_effect=AssertionError('no disk probe')):
            batch = self.change(action='add', ids=[1, 2, 3])
            group = batch['groups'][0]['id']
            self.change(action='label', group_id=group, ids=[1], fields={'focus': 'clear', 'preference': 'preferred'})
            self.change(action='label', group_id=group, ids=[2], fields={'focus': 'motion_blur', 'preference': 'ordinary'})
            self.change(action='group', group_id=group, name='飞行对照', split='holdout')
            exported = validation.export(self.f.lib)
        self.assertEqual(exported['unreviewed_count'], 1)
        self.assertFalse(exported['production_scoring_enabled'])
        self.assertEqual([s['id'] for s in exported['samples']], [1, 2, 3])
        self.assertTrue(all(s['split'] == 'holdout' for s in exported['samples']))
        self.assertEqual(exported['samples'][0]['sha256'], self.f.lib.items([1])[0]['sha256'])
        self.assertEqual(exported['samples'][0]['subject_box'], [0, 0, 1, 1])
        self.assertNotIn('thumbnail', exported['samples'][0])
        self.assertEqual(self.f.db.meta('generation'), generation)
        self.assertEqual(self.f.processor.calls, calls)
        for table, rows in before.items():
            self.assertEqual(self.f.db.query('SELECT * FROM ' + table), rows)
        reopened = Database(self.f.data)
        self.assertEqual(json.loads(reopened.meta(validation.KEY))['groups'][0]['samples'][0]['focus'], 'clear')
        backup = self.f.db.backup()
        with contextlib.closing(sqlite3.connect(backup)) as c:
            self.assertEqual(json.loads(c.execute('SELECT value FROM meta WHERE key=?', (validation.KEY,)).fetchone()[0])['revision'], 4)

    def test_conflict_and_invalid_batch_are_atomic(self):
        batch = self.change(action='add', ids=[1, 2])
        group = batch['groups'][0]['id']
        before = self.f.db.meta(validation.KEY)
        with self.assertRaises(Conflict):
            validation.change(self.f.lib, {'revision': 0, 'action': 'remove', 'group_id': group})
        for invalid in ([1, 1], [3], [3, True], [3, 99], [1, 4]):
            with self.assertRaises(ValueError):
                self.change(action='add', ids=invalid)
        with self.assertRaises(ValueError):
            self.change(action='label', group_id=group, ids=[1, 4], fields={'focus': 'clear'})
        with self.assertRaises(ValueError):
            self.change(action='label', group_id=group, ids=[1], fields={'rating': 5})
        self.assertEqual(self.f.db.meta(validation.KEY), before)
        with self.assertRaises(Conflict):
            validation.change(self.f.lib, {'revision': batch['revision'], 'action': 'add', 'ids': [3, 4],
                                          'sources': [{'id': i, 'sha256': '0' * 64, 'adjustment_revision': 0} for i in [3, 4]]})

    def test_authorization_fingerprint_status_and_recipe_guard(self):
        batch = self.change(action='add', ids=[1, 2])
        group = batch['groups'][0]['id']
        self.f.cfg['roots'][0]['allow_paths'] = ['burst/1.ARW']
        with self.assertRaises(ValueError):
            validation.export(self.f.lib)
        self.f.cfg['roots'][0].pop('allow_paths')
        with self.f.db.transaction() as c:
            c.execute("UPDATE photos SET sha256=? WHERE id=1", ('a' * 64,))
        self.assertTrue(validation.read(self.f.lib)['groups'][0]['samples'][0]['stale_reason'])
        with self.assertRaises(Conflict):
            self.change(action='label', group_id=group, ids=[1], fields={'focus': 'clear'})
        with self.assertRaises(Conflict):
            validation.export(self.f.lib)
        # Removing a stale validation group remains possible and does not delete photos.
        self.change(action='remove', group_id=group)
        self.assertEqual(len(self.f.lib.items()), 4)
        self.assertEqual(validation.read(self.f.lib)['groups'], [])

    def test_manual_box_snapshot_and_clear_box(self):
        p = self.f.lib.items([1])[0]
        self.f.lib.save_adjustment(1, p['sha256'], 0, {'box': [.1, .2, .7, .8], 'brightness': 20})
        batch = self.change(action='add', ids=[1, 2])
        sample = batch['groups'][0]['samples'][0]
        self.assertEqual(sample['subject_box'], [.1, .2, .7, .8])
        self.assertEqual(sample['saved_recipe']['brightness'], 20)
        self.assertEqual(sample['evaluation_tone'], 'original_unadjusted')
        self.f.lib.save_adjustment(1, p['sha256'], 1, {'box': None})
        with self.assertRaises(Conflict):
            validation.export(self.f.lib)

    def test_thirty_limit_and_no_duplicate_content(self):
        for i in range(5, 33):
            self.f.file(f'burst/{i}.ARW', f'synthetic {i}'.encode())
        self.f.scan()
        self.change(action='add', ids=list(range(1, 31)))
        with self.assertRaises(ValueError):
            self.change(action='add', ids=[31, 32])
        group = validation.read(self.f.lib)['groups'][0]['id']
        self.change(action='remove', group_id=group)
        with self.f.db.transaction() as c:
            c.execute('UPDATE photos SET sha256=(SELECT sha256 FROM photos WHERE id=1) WHERE id=2')
        with self.assertRaises(ValueError):
            self.change(action='add', ids=[1, 2])


class ValidationHTTPTests(unittest.TestCase):
    setUp = test_prototype.HTTPTests.setUp
    tearDown = test_prototype.HTTPTests.tearDown
    req = test_prototype.HTTPTests.req

    def test_routes_auth_persistence_and_export(self):
        self.f.file('b.jpg', b'other synthetic data')
        self.f.scan()
        request = {'action': 'add', 'revision': 0, 'ids': [1, 2]}
        request['sources'] = [{'id': p['id'], 'sha256': p['sha256'], 'adjustment_revision': p['edit_revision']} for p in self.f.lib.items([1, 2])]
        self.assertEqual(self.req('/api/validation', request)[0], 403)
        status, body = self.req('/api/validation', request, {'X-Bird-Token': self.server.token})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(self.req('/api/validation')[1])['revision'], 1)
        status, body = self.req('/api/export/validation')
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['samples']), 2)
        self.assertEqual(self.req('/validation.js')[0], 200)
        self.server.gateway_token = 'g' * 40
        self.assertEqual(self.req('/api/export/validation')[0], 403)


class ValidationBrowserTests(unittest.TestCase):
    def test_existing_nas_label_cache_compatibility(self):
        path = Path(__file__).resolve().parents[1] / 'docs/china-birds-ioc12.1-probe.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), '6f56faec6ec4a2bc9f8748475ac2d4a8ea6e0f24396841dfa621b8189103637d')

    def test_labels_and_export_controller(self):
        node = os.environ.get('BIRD_NODE') or shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([node, str(root / 'tests/check_validation.js'), str(root / 'web/validation.js')], capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
