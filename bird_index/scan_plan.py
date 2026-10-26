"""Stat-only scan preview; only an explicitly confirmed manifest is queued."""
import itertools
import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from . import folders
from .common import FORMATS, encode, now, safe_file
from .db import Conflict


def checked_source(root, rel):
    # Reject a newly substituted link even if it targets another file inside the root.
    parent=Path(rel).parent.as_posix()
    folders.directory(root,'' if parent=='.' else parent)
    path=Path(root)/rel
    info=path.lstat()
    if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
        raise ValueError('不能处理链接或重解析文件')
    return safe_file(root,rel)


def signature(row):
    return None if row is None else tuple(row[k] for k in ('id', 'size', 'mtime_ns', 'sha256', 'inference_status', 'source_status'))


class ScanPlans:
    def __init__(self, jobs):
        self.jobs = jobs
        self.lib = jobs.lib
        self.db = jobs.db
        self.lock = threading.Lock()
        self.pending = {}

    @staticmethod
    def idle(connection):
        if connection.execute("SELECT 1 FROM jobs WHERE state IN ('queued','discovering','running','paused') LIMIT 1").fetchone() or connection.execute("SELECT 1 FROM job_items WHERE state='running' LIMIT 1").fetchone():
            raise Conflict('请先完成或取消现有任务，再检查目录变更')
        if connection.execute("SELECT 1 FROM file_plans WHERE state='executing' LIMIT 1").fetchone():
            raise Conflict('原片整理尚未完成')

    def preview(self, root_id, scopes, limit=None):
        root = self.lib.root(root_id)
        scopes = folders.validate(root['path'], scopes)
        cap = self.jobs.cfg['max_files_per_job']
        if limit is None:
            limit = cap
        if type(limit) is not int or not 0 <= limit <= 9223372036854775807 or cap and (limit == 0 or limit > cap):
            raise ValueError('任务数量无效或超过配置上限')
        base = Path(root['path'])
        errors = []
        def walk(folder, recurse=True):
            try:
                with os.scandir(folder) as stream:
                    entries = sorted(stream, key=lambda e: e.name.casefold())
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if recurse:
                                yield from walk(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and Path(entry.path).suffix.lower() in FORMATS:
                            yield Path(entry.path).relative_to(base).as_posix()
                    except OSError as exc:
                        errors.append(str(exc))
            except OSError as exc:
                errors.append(str(exc))
        if root['allow_paths'] is not None:
            paths = (p for p in root['allow_paths'] if folders.includes(p, scopes))
        else:
            paths = itertools.chain.from_iterable(walk(base if s == '.' else base/s, s != '.') for s in scopes)
        known = {p['rel_path']: p for p in self.db.query('SELECT * FROM photos WHERE root_id=?', (root_id,))}
        items = []
        seen = set()
        counts = dict(new=0, updated=0, retry=0, unchanged=0, unavailable=0)
        for rel in paths:
            if rel in seen:
                continue
            seen.add(rel)
            old = known.get(rel)
            try:
                stat = checked_source(base, rel).stat()
            except (OSError, ValueError) as exc:
                errors.append(rel + ': ' + str(exc))
                counts['unavailable'] += 1
                continue
            if old and old['source_status'] == 'quarantined':
                counts['unavailable'] += 1
                continue
            if old is None:
                reason = 'new'
            elif (old['size'], old['mtime_ns']) != (stat.st_size, stat.st_mtime_ns):
                reason = 'updated'
            elif old['inference_status'] != 'ready':
                reason = 'retry'
            else:
                reason = 'unchanged'
            counts[reason] += 1
            if reason != 'unchanged':
                items.append({'path': rel, 'photo_id': old['id'] if old else None, 'reason': reason,
                              'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, '_record': signature(old)})
        missing = [{'photo_id': p['id'], 'path': rel} for rel, p in known.items()
                   if folders.includes(rel, scopes) and rel not in seen and p['source_status'] != 'quarantined']
        token = secrets.token_urlsafe(24)
        plan = dict(root_id=root_id, scopes=scopes, limit=limit, items=items, created=time.monotonic())
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if time.monotonic()-v['created'] < 1800}
            while len(self.pending) >= 4:
                del self.pending[next(iter(self.pending))]
            self.pending[token] = plan
        return {'preview_token': token, 'root_id': root_id, 'scopes': scopes, 'limit': limit,
                'items': [{k: v for k, v in item.items() if not k.startswith('_')} for item in items],
                'counts': counts, 'missing': missing, 'errors': errors,
                'notice': '只检查路径、大小和修改时间，未读取照片内容或启动识别。未变化照片跳过；清单 30 分钟有效，服务重启后需重新检查。'}

    def commit(self, token, paths):
        with self.lock:
            plan = self.pending.get(token)
            if not plan or time.monotonic()-plan['created'] >= 1800:
                raise Conflict('变更清单已过期，请重新检查目录')
            if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
                raise ValueError('请勾选要处理的变更文件，不允许重复')
            indexed = {i['path']: i for i in plan['items']}
            if not set(paths) <= indexed.keys():
                raise ValueError('确认文件不在变更清单中')
            if plan['limit'] and len(paths) > plan['limit']:
                raise ValueError('勾选张数超过本次处理上限')
            root = self.lib.root(plan['root_id'])
            folders.validate(root['path'], plan['scopes'])
            identifier = uuid.uuid4().hex
            with self.db.transaction() as c:
                self.idle(c)
                # Check the whole selection before writing any records.
                for rel in paths:
                    item = indexed[rel]
                    stat = checked_source(root['path'], rel).stat()
                    old = c.execute('SELECT * FROM photos WHERE root_id=? AND rel_path=?', (root['id'], rel)).fetchone()
                    if (stat.st_size, stat.st_mtime_ns) != (item['size'], item['mtime_ns']) or signature(old) != item['_record']:
                        raise Conflict('清单之后文件或索引变化，请重新检查目录：' + rel)
                c.execute('INSERT INTO jobs(id,root_id,scope,limit_count,state,force,created_at,updated_at,scopes,discovery_done,found) VALUES(?,?,?,?,?,?,?,?,?,1,?)',
                          (identifier, root['id'], '', plan['limit'], 'queued', 0, now(), now(), encode(plan['scopes']), len(paths)))
                for rel in paths:
                    item = indexed[rel]
                    pid = item['photo_id']
                    if pid is None:
                        display = root['id']+'/'+rel
                        row = {'path': display, 'directory': root['id']+'/'+str(Path(rel).parent), 'capture_context': root['context'], 'views': []}
                        pid = c.execute('INSERT INTO photos(root_id,rel_path,display_path,size,mtime_ns,summary) VALUES(?,?,?,?,?,?)',
                                        (root['id'], rel, display, item['size'], item['mtime_ns'], encode(row))).lastrowid
                        c.execute('INSERT INTO manual(photo_id) VALUES(?)', (pid,))
                    request = {'scan_source': {'size': item['size'], 'mtime_ns': item['mtime_ns']}}
                    c.execute('INSERT INTO job_items(job_id,photo_id,state,request) VALUES(?,?,?,?)', (identifier, pid, 'pending', encode(request)))
                self.db.bump(c)
            del self.pending[token]
        self.jobs.wake.set()
        return {'id': identifier, 'confirmed': len(paths), 'notice': '只处理已确认清单；检查后新增的其他文件不会自动加入'}
