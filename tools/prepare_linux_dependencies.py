"""Prepare fixed Linux/amd64 CPython 3.12 wheels and a Debian runtime library.

Downloads only public packages. Never opens photographs or changes the local venv.
"""
import argparse
import concurrent.futures
import email
import hashlib
from html.parser import HTMLParser
import json
import lzma
from pathlib import Path
import time
import urllib.parse
import zipfile
import requests
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import cpython_tags,compatible_tags
from packaging.utils import canonicalize_name,parse_wheel_filename
from packaging.version import Version

ROOT=Path(__file__).resolve().parents[1]
PLATFORMS=['manylinux_2_'+str(n)+'_x86_64' for n in range(36,4,-1)]+['manylinux2014_x86_64','manylinux2010_x86_64','manylinux1_x86_64','linux_x86_64']
TAGS=list(cpython_tags((3,12),['cp312'],PLATFORMS))+list(compatible_tags((3,12),'cp312',PLATFORMS))
ORDER={tag:i for i,tag in enumerate(TAGS)}
LINUX={'implementation_name':'cpython','implementation_version':'3.12.14','os_name':'posix','platform_machine':'x86_64','platform_python_implementation':'CPython','platform_release':'','platform_system':'Linux','platform_version':'','python_full_version':'3.12.14','python_version':'3.12','sys_platform':'linux','extra':''}

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def fetch(url):
 for attempt in range(3):
  try:
   r=requests.get(url,timeout=(20,45));r.raise_for_status();return r
  except requests.RequestException:
   if attempt==2:raise
   time.sleep(2)

def download(item,base):
 path=base/item['path'];path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists() and sha(path)==item['sha256']:
  print('cached '+path.name,flush=True);return item
 part=path.with_suffix(path.suffix+'.partial')
 for attempt in range(4):
  try:
   offset=part.stat().st_size if part.exists() else 0
   headers={'Range':f'bytes={offset}-'} if offset else {}
   with requests.get(item['url'],headers=headers,stream=True,timeout=(20,45)) as r:
    r.raise_for_status()
    append=offset and r.status_code==206
    if append and not r.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid download range')
    with part.open('ab' if append else 'wb') as f:
     for b in r.iter_content(1048576):f.write(b)
   if sha(part)!=item['sha256']:
    part.unlink();raise ValueError('SHA-256 mismatch: '+path.name)
   part.replace(path);item['bytes']=path.stat().st_size
   print('verified '+path.name+' '+str(item['bytes']),flush=True);return item
  except (requests.RequestException,ValueError):
   if attempt==3:raise
   time.sleep(2)

def wheel_rank(name,version):
 try:_,v,_,tags=parse_wheel_filename(name)
 except ValueError:return None
 if v!=Version(version):return None
 candidates=[ORDER[t] for t in tags if t in ORDER]
 return min(candidates) if candidates else None

class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,tag,attrs):
  if tag=='a':self.links.extend(v for k,v in attrs if k=='href')

def resolve(name,version):
 candidates=[]
 if name in ('torch','torchvision'):
  source='https://download.pytorch.org/whl/cpu/'+name+'/'
  parser=Links();parser.feed(fetch(source).text)
  for href in parser.links:
   url=urllib.parse.urljoin(source,href);parsed=urllib.parse.urlsplit(url)
   filename=urllib.parse.unquote(parsed.path.rsplit('/',1)[-1]);rank=wheel_rank(filename,version)
   digest=urllib.parse.parse_qs(parsed.fragment).get('sha256',[''])[0]
   if rank is not None and len(digest)==64:candidates.append((rank,{'path':'wheels/'+filename,'url':url.split('#')[0],'sha256':digest}))
 else:
  source=f'https://pypi.org/pypi/{name}/{version}/json';data=fetch(source).json()
  for row in data['urls']:
   rank=wheel_rank(row['filename'],version)
   if rank is not None and not row.get('yanked') and (not row.get('requires_python') or Version('3.12.14') in SpecifierSet(row['requires_python'])):
    candidates.append((rank,{'path':'wheels/'+row['filename'],'url':row['url'],'sha256':row['digests']['sha256'],'bytes':row['size']}))
 if not candidates:raise ValueError('No matching Linux wheel: '+name+'=='+version)
 result=sorted(candidates,key=lambda c:(c[0],c[1]['path']))[0][1]
 result.update(name=name,version=version,metadata_source=source)
 return result

def audit_wheels(base,plan):
 metadata={};versions={r['name']:Version(r['version']) for r in plan};extras={n:set() for n in versions}
 for row in plan:
  with zipfile.ZipFile(base/row['path']) as z:
   names=[n for n in z.namelist() if n.endswith('.dist-info/METADATA') and len(n.split('/'))==2]
   assert len(names)==1;meta=email.message_from_bytes(z.read(names[0]))
   assert canonicalize_name(meta['Name'])==row['name'] and Version(meta['Version'])==versions[row['name']]
   if meta['Requires-Python']:assert Version('3.12.14') in SpecifierSet(meta['Requires-Python'])
   metadata[row['name']]=meta
 changed=True;missing=[];edges=[]
 while changed:
  changed=False;missing=[];edges=[]
  for name,meta in metadata.items():
   for value in meta.get_all('Requires-Dist',[]):
    req=Requirement(value)
    if req.marker and not any(req.marker.evaluate({**LINUX,'extra':extra}) for extra in {''}|extras[name]):continue
    target=canonicalize_name(req.name);edges.append((name,str(req)))
    if target not in versions:missing.append((name,str(req)));continue
    if req.url or versions[target] not in req.specifier:raise ValueError('Incompatible dependency: '+name+' requires '+str(req))
    new=set(req.extras)-extras[target]
    if new:extras[target].update(new);changed=True
 if missing:raise ValueError('Missing Linux dependencies: '+repr(missing))
 forbidden=[n for n in versions if n.startswith('nvidia-') or n=='triton']
 if forbidden:raise ValueError('Unexpected GPU dependencies: '+repr(forbidden))
 return {'platform':LINUX,'packages':len(plan),'dependency_edges':edges,'missing':missing,'gpu_packages':forbidden}

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--base-status',type=Path,required=True);a=p.parse_args();base=a.output.resolve();base.mkdir(parents=True,exist_ok=True)
 versions={}
 for line in (ROOT/'requirements-linux.lock.txt').read_text().splitlines():
  if not line.strip() or line.startswith(('#','--')):continue
  req=Requirement(line);spec=list(req.specifier);assert len(spec)==1 and spec[0].operator=='=='
  versions[canonicalize_name(req.name)]=spec[0].version
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  plan=list(pool.map(lambda kv:resolve(*kv),versions.items()))
 (base/'wheel-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
 print(json.dumps({'resolved_wheels':len(plan),'target':'Linux CPython 3.12 amd64'}),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  plan=list(pool.map(lambda row:download(row,base),plan))
 audit=audit_wheels(base,plan);(base/'wheel-audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
 # Use Debian's HTTPS package index and its declared SHA-256, not a mirror guess.
 index_url='https://deb.debian.org/debian/dists/bookworm/main/binary-amd64/Packages.xz'
 index=fetch(index_url).content;(base/'debian-Packages.xz').write_bytes(index)
 paragraphs=lzma.decompress(index).decode().split('\n\n')
 package=next(b for b in paragraphs if b.startswith('Package: libgomp1\n') and '\nArchitecture: amd64\n' in b)
 fields=dict(line.split(': ',1) for line in package.splitlines() if ': ' in line and not line.startswith(' '))
 status=a.base_status.read_text(encoding='utf-8');gcc=next(b for b in status.split('\n\n') if b.startswith('Package: gcc-12-base\n'))
 assert 'Version: '+fields['Version'] in gcc,'Base gcc version does not match libgomp1'
 assert fields['Depends']=='gcc-12-base (= '+fields['Version']+'), libc6 (>= 2.34)',fields['Depends']
 deb={'path':'debs/'+Path(fields['Filename']).name,'url':'https://deb.debian.org/debian/'+fields['Filename'],'sha256':fields['SHA256'],'bytes':int(fields['Size']),'name':'libgomp1','version':fields['Version'],'metadata_source':index_url,'metadata_sha256':hashlib.sha256(index).hexdigest()}
 download(deb,base)
 requirements='\n'.join(row['name']+'=='+row['version']+' --hash=sha256:'+row['sha256'] for row in sorted(plan,key=lambda r:r['name']))+'\n'
 (base/'requirements.offline.lock.txt').write_text(requirements,encoding='utf-8')
 extra={'path':'requirements.offline.lock.txt','sha256':sha(base/'requirements.offline.lock.txt'),'bytes':(base/'requirements.offline.lock.txt').stat().st_size}
 manifest={'platform':'linux/amd64','python':'3.12.14','base_image':'python:3.12.14-slim-bookworm','base_config_digest':'sha256:febd0be41adb897a0ab8f1f1c693d8912669ea60c4940e076e9946b60e210ef0','files':plan+[deb,extra],'validation':'Linux metadata dependency closure and file hashes verified; NAS build pending'}
 (base/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 print(json.dumps({'ready':True,'wheels':len(plan),'debs':1,'bytes':sum((base/r['path']).stat().st_size for r in manifest['files'])}),flush=True)

if __name__=='__main__':main()
