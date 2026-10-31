"""Three supervised processes in one container; Tailscale stays independent."""
import argparse
import http.client
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .compact_sandbox import restrict, probe

ROLES = ('organizer', 'index', 'gateway')


def role_policy(role, curation):
    if role == 'index':return ['/data', '/tmp', '/dev/null'], [8765], [8766]
    if role == 'gateway':return ['/gateway-data', '/gateway-config', '/tmp', '/dev/null'], [8443], [8765]
    if role != 'organizer':raise ValueError('Unknown compact service')
    paths = [Path(curation[k]).resolve(strict=True) for k in ('photo_root', 'quarantine_root')]
    if any(not p.is_relative_to('/library') or str(p) == '/library' for p in paths):raise ValueError('Organizer roots must be explicit children of /library')
    if paths[0] == paths[1] or paths[0].is_relative_to(paths[1]) or paths[1].is_relative_to(paths[0]):raise ValueError('Organizer roots overlap')
    return ['/data', '/tmp', '/dev/null', *map(str, paths)], [8766], []


def configuration():
    cfg = json.loads(Path('/config/config.json').read_text(encoding='utf-8'))
    curation = json.loads(Path('/config/curation.json').read_text(encoding='utf-8'))
    if not Path('/config/curation.enabled').is_file() or curation.get('enabled') is not True:
        raise ValueError('Compact migration requires already-enabled organizer; it never enables moves')
    if cfg.get('data_dir') != '/data' or not cfg.get('require_folder_selection'):
        raise ValueError('Expected existing /data configuration and explicit folder selection')
    if not cfg.get('roots') or any(r.get('path') != '/photos' for r in cfg['roots']):
        raise ValueError('Compact migration supports the existing /photos library only')
    if curation.get('index_photo_root') != '/photos':raise ValueError('Organizer index mapping differs')
    for role in ROLES:role_policy(role, curation)
    return curation


def child(role):
    curation = configuration();writes, bind, connect = role_policy(role, curation)
    # Caddy must fchmod newly created private keys. It cannot open originals,
    # including their /library alias; index/organizer cannot call fchmod at all.
    readable = ['/usr', '/lib', '/lib64', '/etc', '/proc', '/sys', '/dev',
                '/app', '/config', '/run/secrets'] if role == 'gateway' else None
    abi = restrict(writes, bind, connect, readable=readable, allow_fchmod=role == 'gateway')
    Path('/tmp/compact-'+role+'.json').write_text(json.dumps({'role': role, 'pid': os.getpid(), 'landlock_abi': abi, 'metadata_seccomp': True}), encoding='utf-8')
    os.environ.update(HOME='/tmp', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    if role == 'index':
        os.environ.update(BIRD_LISTEN_HOST='127.0.0.1', BIRD_ORGANIZER_URL='http://127.0.0.1:8766', BIRD_COMPACT='1')
        command = [sys.executable, '-B', '-m', 'bird_index', 'serve', '--config', '/config/config.json', '--port', '8765']
    elif role == 'organizer':
        os.environ['BIRD_ORGANIZER_HOST'] = '127.0.0.1'
        command = [sys.executable, '-B', '-m', 'bird_index.curation']
    else:
        os.environ.update(XDG_DATA_HOME='/gateway-data', XDG_CONFIG_HOME='/gateway-config', GOMEMLIMIT='192MiB')
        token = Path('/run/secrets/gateway_token').read_text().strip()
        if len(token) < 32:raise ValueError('Gateway token missing')
        os.environ['BIRD_GATEWAY_TOKEN'] = token
        command = ['/usr/local/bin/caddy', 'run', '--config', '/config/compact.Caddyfile', '--adapter', 'caddyfile']
    os.execvpe(command[0], command, os.environ)


def stop_children(children):
    # Process groups also contain model/decoder children. Never leave them behind.
    for p in reversed(children):
        try:os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:pass
    deadline = time.monotonic()+25
    for p in children:
        try:p.wait(timeout=max(.01, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:pass
    for p in children:
        try:os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:pass
        p.wait()


def supervise():
    configuration();probe()  # Every restart must pass before any server is started.
    stopping = False;children = []
    def requested(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, requested);signal.signal(signal.SIGINT, requested)
    try:
        for role in ROLES:
            marker = Path('/tmp/compact-'+role+'.json')
            if marker.exists():marker.unlink()
            children.append(subprocess.Popen([sys.executable, '-B', '-m', 'bird_index.compact', '--child', role], start_new_session=True, close_fds=True))
        while not stopping:
            if any(p.poll() is not None for p in children):return 1
            time.sleep(.5)
        return 0
    finally:stop_children(children)


def health():
    for role in ROLES:
        row = json.loads(Path('/tmp/compact-'+role+'.json').read_text())
        if row['role'] != role or row['landlock_abi'] < 6 or row.get('metadata_seccomp') is not True:raise RuntimeError('Missing sandbox attestation')
        os.kill(row['pid'], 0)
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with direct.open('http://127.0.0.1:8765/health', timeout=3) as response:
        if json.load(response).get('status') != 'ok':raise RuntimeError('Index health failed')
    token = Path('/run/secrets/gateway_token').read_text().strip()
    # The lightweight health route does not query the library or move journal.
    request = urllib.request.Request('http://127.0.0.1:8766/health', data=b'{}', headers={'X-Bird-Organizer': token})
    with direct.open(request, timeout=3) as response:
        if json.load(response).get('enabled') is not True:raise RuntimeError('Organizer not enabled')
    # Trust the same existing local CA; never suppress TLS verification.
    ca = '/gateway-data/caddy/pki/authorities/local/root.crt'
    tls = ssl.create_default_context(cafile=ca)
    name = os.environ['BIRD_TLS_SERVER_NAME']
    with socket.create_connection(('127.0.0.1', 8443), timeout=3) as connection:
        with tls.wrap_socket(connection, server_hostname=name) as encrypted:
            encrypted.sendall(('GET / HTTP/1.1\r\nHost: '+name+':8443\r\nConnection: close\r\n\r\n').encode('ascii'))
            with http.client.HTTPResponse(encrypted) as response:
                response.begin()
                if response.status != 401:raise RuntimeError('Gateway did not require login')
    print('Compact health OK: index + HTTPS authentication + organizer + sandbox markers')


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--child', choices=ROLES);parser.add_argument('--health', action='store_true');args = parser.parse_args()
    if args.child:child(args.child)
    elif args.health:health()
    else:raise SystemExit(supervise())


if __name__ == '__main__':main()
