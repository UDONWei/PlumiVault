"""Package source-only update, excluding credentials, photos, models and runtime data."""
import argparse,hashlib,json,re,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build(output,name='culling-r2'):
 if not re.fullmatch('[a-z0-9-]+',name):raise ValueError('版本名称无效')
 output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);files=[]
 for folder in ('bird_index','web','tools','docs','deploy','tests'):
  for p in (ROOT/folder).rglob('*'):
   if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts and p.suffix in ('.py','.js','.css','.html','.md','.json','.txt','.sh','.yaml','.csv','.tsv'):files.append(p)
 for filename in ('AGENTS.md','README.md','STATUS.md','Dockerfile','Dockerfile.offline','Dockerfile.compact','Dockerfile.compact.dockerignore','.dockerignore','compose.yaml','compose.offline.yaml','compose.curation.yaml','compose.compact.yaml','requirements-linux.lock.txt'):
  p=ROOT/filename
  if p.is_file():files.append(p)
 files.append(ROOT/'deploy/compact.Caddyfile')
 files=sorted(set(files));archive=output/('bird-index-nas-'+name+'.tar.gz')
 if archive.exists():raise ValueError('交付包已存在，拒绝覆盖；请使用新版本名称')
 with tarfile.open(archive,'w:gz') as tar:
  for p in files:tar.add(p,arcname=p.relative_to(ROOT).as_posix(),recursive=False)
 checksum=hashlib.sha256(archive.read_bytes()).hexdigest();archive.with_suffix(archive.suffix+'.sha256').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
 with tarfile.open(archive) as tar:
  names=tar.getnames();assert len(names)==len(files);assert all(not n.startswith(('/', 'config/','data/','models/','offline/','app-data/')) and '..' not in Path(n).parts for n in names)
 print(json.dumps({'path':str(archive),'bytes':archive.stat().st_size,'files':len(files),'sha256':checksum},ensure_ascii=False))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--name',default='culling-r2');a=parser.parse_args();build(a.output,a.name)
