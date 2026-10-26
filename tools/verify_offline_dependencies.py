"""Hash/check the offline payload with only Python's standard library."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(folder,config=None):
 base=Path(folder).resolve(strict=True)
 manifest=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
 if manifest['platform']!='linux/amd64' or manifest['python']!='3.12.14':raise ValueError('Offline target mismatch')
 seen=set()
 for row in manifest['files']:
  rel=Path(row['path'])
  if rel.is_absolute() or '..' in rel.parts or row['path'] in seen:raise ValueError('Invalid offline file path')
  path=base/rel
  if path.is_symlink() or not path.resolve(strict=True).is_relative_to(base):raise ValueError('Offline file escapes bundle')
  seen.add(row['path']);h=hashlib.sha256()
  with path.open('rb') as f:
   for block in iter(lambda:f.read(1048576),b''):h.update(block)
  if h.hexdigest()!=row['sha256']:raise ValueError('SHA-256 mismatch: '+row['path'])
 actual={p.relative_to(base).as_posix() for name in ('wheels','debs') for p in (base/name).iterdir() if p.is_file()}
 expected={name for name in seen if name.startswith(('wheels/','debs/'))}
 if actual!=expected:raise ValueError('Unexpected or missing dependency files')
 if config:
  cfg=json.loads(Path(config).read_text(encoding='utf-8-sig'))
  cap=cfg.get('max_files_per_job')
  if cfg.get('require_folder_selection') is not True or type(cap)!=int or not 0<=cap<=9223372036854775807:raise ValueError('NAS configuration must require folder selection and a valid job limit (0 means unlimited)')
 return {'offline_files_verified':len(seen),'platform':manifest['platform'],'config_checked':bool(config),'scan_started':False}


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--config');a=p.parse_args()
 print(json.dumps(verify(a.folder,a.config)))
