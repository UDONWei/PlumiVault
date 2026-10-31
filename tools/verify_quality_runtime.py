"""NAS synthetic CPU probe, no photograph reads and no network."""
import argparse
import json
from pathlib import Path
import socket
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bird_index.common import load_config,digest
from bird_index.quality_models import manifest_path,EYE_SHA


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default='/config/config.json');a=p.parse_args();cfg=load_config(a.config)
    path=manifest_path(cfg);meta=json.loads(path.read_text(encoding='utf-8'))
    if meta.get('eye_file')!='eye-pose-cpu.ts' or meta.get('eye_sha256')!=EYE_SHA:raise ValueError('Unexpected quality manifest')
    weight=path.parent/'eye-pose-cpu.ts'
    if weight.is_symlink() or digest(weight)!=EYE_SHA:raise ValueError('Eye model checksum failed')
    sandbox=False
    if Path('/config/compact.enabled').is_file():
        from bird_index.compact_sandbox import restrict
        restrict(['/data','/tmp','/dev/null'],[8765],[8766]);sandbox=True
    def offline(*args,**kwargs):raise OSError('Quality verification is offline')
    socket.socket.connect=offline;socket.create_connection=offline
    import torch
    torch.set_num_threads(cfg['threads']);torch.set_num_interop_threads(1)
    started=time.perf_counter();model=torch.jit.load(str(weight),map_location='cpu').eval()
    with torch.inference_mode():out=model(torch.zeros(1,3,640,640))
    if tuple(out.shape)!=(1,23,8400) or not torch.isfinite(out).all():raise ValueError('Invalid synthetic inference output')
    print(json.dumps({'quality_runtime':'passed','device':'cpu','sandbox':sandbox,'seconds':round(time.perf_counter()-started,3),'originals_read':False,'model_sha256':EYE_SHA}))


if __name__=='__main__':main()
