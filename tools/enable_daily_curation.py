"""Explicit opt-in helper. Creates a quarantine directory, never moves photos.

Run in the NAS image with the deployment at /deployment and the common photo
parent at /library. Only generated test files under data/runtime are moved.
"""
import argparse,json,os,tempfile,uuid,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bird_index.curation import rename_no_replace,strict_path


def synthetic_probe(data):
    runtime=Path(data)/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='organizer-selftest-',dir=runtime) as temp:
        root=Path(temp);a=root/'source';b=root/'destination';a.mkdir();b.mkdir()
        source=a/'synthetic.txt';dest=b/'synthetic.txt';source.write_bytes(b'generated organizer self-test, not a photograph')
        dest.write_bytes(b'keep existing')
        try:rename_no_replace(source,dest)
        except OSError:pass
        else:raise ValueError('安全移动检查失败：没有拒绝已存在目标')
        if dest.read_bytes()!=b'keep existing' or not source.exists():raise ValueError('安全移动检查破坏了测试文件')
        dest.unlink();before=source.read_bytes();inode=source.stat().st_ino
        rename_no_replace(source,dest)
        if source.exists() or dest.read_bytes()!=before or dest.stat().st_ino!=inode:raise ValueError('合成文件移动校验失败')
        rename_no_replace(dest,source)
        if dest.exists() or source.read_bytes()!=before:raise ValueError('合成文件恢复校验失败')
    return {'move':True,'restore':True,'no_overwrite':True,'original_photo_probe':False}


def atomic(path,contents):
    path=Path(path);temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        mode=path.stat().st_mode & 0o777 if path.exists() else 0o600
        with temp.open('wb') as f:f.write(contents);f.flush();os.fsync(f.fileno())
        os.chmod(temp,mode);os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


def enable(deployment,library,host_parent):
    deployment=Path(deployment);library=Path(library)
    if host_parent!='/volume1/照片':raise ValueError('照片父目录与用户确认的位置不同，拒绝启用')
    cfg=json.loads((deployment/'config/config.json').read_text(encoding='utf-8'))
    roots=[r for r in cfg['roots'] if r['path']=='/photos']
    if len(roots)!=1:raise ValueError('需要唯一的 /photos 图库入口')
    source=library/'未处理';dest=library/'待删除'
    # Check lexical paths before resolve so a symlink is not silently accepted.
    strict_path(source,'__boundary_check__')
    if not source.is_dir():raise ValueError('原片目录不可用')
    target=deployment/'config/curation.json';old=json.loads(target.read_text(encoding='utf-8')) if target.exists() else None
    if old and (old.get('root_id')!=roots[0]['id'] or old.get('photo_root')!='/library/未处理' or old.get('quarantine_root')!='/library/待删除'):raise ValueError('已有整理配置映射不同，拒绝覆盖')
    probe=synthetic_probe(deployment/'data')
    if not dest.exists():dest.mkdir()  # Only the explicitly chosen quarantine directory.
    strict_path(dest,'__boundary_check__')
    if not dest.is_dir() or source.stat().st_dev!=dest.stat().st_dev:raise ValueError('待删除目录必须与原片位于同一文件系统')
    if not all(os.access(p,os.W_OK|os.X_OK) for p in (source,dest)):raise ValueError('当前 NAS 用户没有目录移动所需权限；没有修改权限或移动照片')
    value={'enabled':True,'scope':'indexed_root','root_id':roots[0]['id'],'index_photo_root':'/photos','photo_root':'/library/未处理','quarantine_root':'/library/待删除','display_destination':host_parent+'/待删除','max_batch':100}
    suffix=uuid.uuid4().hex[:12];backups=[]
    for path in (target,deployment/'.env'):
        if path.exists():
            backup=path.with_name(path.name+'.before-curation-'+suffix);atomic(backup,path.read_bytes());backups.append(backup.name)
    env=deployment/'.env';text=env.read_text(encoding='utf-8')
    # Preserve secrets and every unrelated setting without shell evaluation.
    lines=[s for s in text.splitlines() if not s.strip().startswith('BIRD_PHOTO_PARENT=')]
    lines.append('BIRD_PHOTO_PARENT='+host_parent)
    atomic(env,('\n'.join(lines)+'\n').encode('utf-8'))
    atomic(target,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    atomic(deployment/'config/curation.enabled',b'indexed-root-v1\n')
    return {'enabled':True,'root_id':roots[0]['id'],'scope':'indexed_root','max_batch':100,'destination':host_parent+'/待删除','synthetic_probe':probe,'backups':backups,'originals_moved':0,'scan_started':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--deployment',default='/deployment');p.add_argument('--library',default='/library');p.add_argument('--host-parent',required=True);a=p.parse_args()
    print(json.dumps(enable(a.deployment,a.library,a.host_parent),ensure_ascii=False))
