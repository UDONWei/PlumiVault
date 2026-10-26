"""Create a private NAS bundle of code and selected model files, never photographs."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--include-models',action='store_true');args=parser.parse_args()
    output=args.output.resolve()
    if output.exists():raise ValueError('交付文件已存在，请选择新文件名')
    entries=[]
    for folder in ('bird_index','web','tools','docs','deploy'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and (path.suffix.lower() in {'.py','.js','.json','.html','.css','.md','.txt','.sh','.example'} or path.name=='Caddyfile'):
                entries.append((path,path.relative_to(ROOT).as_posix()))
    for name in ('Dockerfile','.dockerignore','compose.yaml','requirements-linux.lock.txt','README.md','STATUS.md'):
        entries.append((ROOT/name,name))
    if args.include_models:
        offline=ROOT/'offline'
        for config_name in ('model.json','detector-ssdlite.json'):
            config=json.loads((offline/config_name).read_text(encoding='utf-8-sig'));weights=(offline/config['weights']).resolve(strict=True)
            if not weights.is_relative_to(offline.resolve()) or sha(weights)!=config['sha256']:raise ValueError('模型文件或 SHA-256 不符')
            entries.extend([(offline/config_name,'models/'+config_name),(weights,'models/'+weights.name)])
        entries.append((offline/'text_features.pt','models/text_features.pt'))
        # Optional privately obtained taxonomy is configured separately; never bundled here.
    forbidden={'.arw','.jpg','.jpeg','.png','.tif','.tiff','.webp','.bmp','.sqlite3'}
    if any(path.suffix.lower() in forbidden or not path.resolve().is_relative_to(ROOT) for path,name in entries):raise ValueError('交付清单含禁止打包的文件')
    manifest={'scope':'private NAS installation; models and reference catalogues keep their own licences; no photos or user database','files':[{'path':name,'bytes':path.stat().st_size,'sha256':sha(path)} for path,name in entries]}
    output.parent.mkdir(parents=True,exist_ok=True)
    # Model weights are already dense; uncompressed tar avoids unnecessary CPU work.
    with tarfile.open(output,'w') as archive:
        for path,name in entries:archive.add(path,arcname=name,recursive=False)
        import io
        data=json.dumps(manifest,ensure_ascii=False,indent=2).encode();info=tarfile.TarInfo('BUNDLE_MANIFEST.json');info.size=len(data);archive.addfile(info,io.BytesIO(data))
    result={'path':str(output),'bytes':output.stat().st_size,'sha256':sha(output),'files':len(entries),'models_included':args.include_models}
    output.with_suffix(output.suffix+'.sha256').write_text(result['sha256']+'  '+output.name+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
