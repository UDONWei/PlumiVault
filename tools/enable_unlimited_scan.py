"""Explicit, atomic opt-in to unlimited selected-folder jobs; never opens photos."""
import argparse,json,os,stat,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path

def enable(path):
 path=Path(path)
 if path.is_symlink():raise ValueError('Refusing a symlink configuration')
 path=path.resolve(strict=True)
 raw=path.read_bytes();cfg=json.loads(raw.decode('utf-8-sig'))
 if not isinstance(cfg,dict) or cfg.get('require_folder_selection') is not True:
  raise ValueError('Explicit folder selection must remain enabled')
 cap=cfg.get('max_files_per_job')
 if type(cap)!=int or not 0<=cap<=9223372036854775807:raise ValueError('Invalid current job limit')
 if cap==0:return {'changed':False,'max_files_per_job':0,'require_folder_selection':True,'scan_started':False}
 cfg['max_files_per_job']=0
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
 backup=path.with_name('config.before-unlimited-'+stamp+'.json')
 with backup.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.chmod(backup,stat.S_IMODE(path.stat().st_mode))
 fd,name=tempfile.mkstemp(prefix='.config-unlimited-',suffix='.tmp',dir=path.parent)
 temp=Path(name)
 try:
  with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
   f.write(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n');f.flush();os.fsync(f.fileno())
  os.chmod(temp,stat.S_IMODE(path.stat().st_mode))
  os.replace(temp,path)
 finally:
  if temp.exists():temp.unlink()
 return {'changed':True,'backup':str(backup),'max_files_per_job':0,'require_folder_selection':True,'scan_started':False}

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('config');args=parser.parse_args()
 print(json.dumps(enable(args.config),ensure_ascii=False))
