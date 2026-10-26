"""Static deployment checks only; this does not build or run Docker."""
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
doc=yaml.safe_load((ROOT/'compose.yaml').read_text(encoding='utf-8'))
index=doc['services']['index'];gateway=doc['services']['gateway']
assert 'ports' not in index and index['networks']==['private']
assert doc['networks']['private']['internal'] is True
assert index['read_only'] is True and index['cap_drop']==['ALL']
assert not index.get('cap_add')
assert gateway['read_only'] is True and gateway['cap_drop']==['ALL']
assert gateway['cap_add']==['NET_BIND_SERVICE']
assert 'no-new-privileges:true' in gateway['security_opt']
assert not gateway.get('privileged',False)
assert all(m['target']!='/photos' for m in gateway['volumes'])
offline=yaml.safe_load((ROOT/'compose.offline.yaml').read_text(encoding='utf-8'))
assert offline['services']['gateway']=={'pull_policy':'never','cap_add':['NET_BIND_SERVICE']}
assert index['mem_limit']=='6g' and index['cpus']==2
mounts={m['target']:m for m in index['volumes']}
assert mounts['/photos']['read_only'] is True
assert mounts['/models']['read_only'] is True
assert mounts['/config']['read_only'] is True
assert all(m['bind']['create_host_path'] is False for m in index['volumes'])
assert 'BIRD_BIND_IP' in gateway['ports'][0] and ':8443:8443' in gateway['ports'][0]
assert gateway['environment']['BIRD_TLS_SERVER_NAME']=='${BIRD_BIND_IP:?set NAS LAN IP}'
cfg=json.loads((ROOT/'deploy/config.nas.example.json').read_text(encoding='utf-8'))
assert cfg['require_folder_selection'] is True
assert cfg['max_files_per_job']==0 and cfg['thumbnail_edge']<=512
assert cfg['roots'][0]['path']=='/photos' and cfg['data_dir']=='/data'
caddy=(ROOT/'deploy/gateway/Caddyfile').read_text(encoding='utf-8')
assert 'tls internal' in caddy and 'basic_auth' in caddy and 'X-Bird-Gateway' in caddy
assert 'default_sni {$BIRD_TLS_SERVER_NAME:192.0.2.10}' in caddy
assert (ROOT/'.dockerignore').read_text().splitlines()[0]=='**'
assert all(b'\r' not in p.read_bytes() for p in (ROOT/'deploy').rglob('*.sh'))
print(json.dumps({'static_checks':'passed','docker_build':'not_run_here','nas_runtime':'not_run_here','photos_mount':'read_only','gateway_capabilities':['NET_BIND_SERVICE'],'automatic_scan':False},ensure_ascii=False))

curation=yaml.safe_load((ROOT/'compose.curation.yaml').read_text(encoding='utf-8'))
organizer=curation['services']['organizer']
assert 'ports' not in organizer and organizer['networks']==['private']
assert organizer['cap_drop']==['ALL'] and organizer['read_only'] is True
assert all(m['target']!='/photos' for m in organizer['volumes'])
assert curation['services']['index']=={'environment':{'BIRD_ORGANIZER_URL':'http://organizer:8766'}}
print('optional curation isolation: passed; NAS rename runtime remains unverified')
