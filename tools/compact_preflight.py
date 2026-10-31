"""Run via stdin in the existing index container. Metadata only; no photo probe."""
import argparse
import json
import os
from pathlib import Path
import sqlite3


def check(backup=False):
    cfg=json.loads(Path('/config/config.json').read_text(encoding='utf-8'))
    curator=json.loads(Path('/config/curation.json').read_text(encoding='utf-8'))
    assert Path('/config/curation.enabled').is_file() and curator.get('enabled') is True, 'Organizer must already be enabled'
    assert cfg['data_dir']=='/data' and cfg.get('require_folder_selection') is True, 'Preserve explicit folder selection'
    assert len(cfg['roots'])==1 and cfg['roots'][0]['path']=='/photos', 'Expected one existing /photos root'
    assert curator['index_photo_root']=='/photos' and curator['root_id']==cfg['roots'][0]['id'], 'Root mismatch'
    assert curator['photo_root'].startswith('/library/') and curator['quarantine_root'].startswith('/library/'), 'Organizer mapping invalid'
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        if p.parent.name==str(os.getpid()):continue
        try:args=p.read_bytes().split(b'\0')
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
        assert not any(a in (b'bird_index.worker',b'bird_index.preview',b'bird_index.display_preview') for a in args), 'Wait for recognition/preview processes to finish'
    db=sqlite3.connect('file:/data/index.sqlite3?mode=ro',uri=True)
    try:
        assert not db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','discovering','running','paused') LIMIT 1").fetchone(), 'Finish or cancel pending jobs first'
        assert not db.execute("SELECT 1 FROM job_items WHERE state='running' LIMIT 1").fetchone(), 'A photo is still processing'
        assert not db.execute("SELECT 1 FROM file_plans WHERE state='executing' LIMIT 1").fetchone(), 'Recover unfinished moves first'
        print('Photos:',db.execute('SELECT count(*) FROM photos').fetchone()[0], 'Jobs:',db.execute('SELECT count(*) FROM jobs').fetchone()[0])
    finally:db.close()
    if backup:
        from bird_index.db import Database
        print('Database backup:',Database('/data').backup())
    print('Metadata preflight passed. No scan, source write or move performed.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--backup',action='store_true');check(parser.parse_args().backup)
