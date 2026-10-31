"""Convert the pinned eye checkpoint to an offline CPU-only TorchScript bundle.

No photographs are used. The original checkpoint is loaded with weights_only
and an explicit class allowlist, never arbitrary pickle globals.
"""
import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import sys

from evaluate_bird_eye import MODEL_SHA, MODEL_REV, checksum


def main():
    p=argparse.ArgumentParser();p.add_argument('--weights',type=Path,required=True);p.add_argument('--deps',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if checksum(a.weights)!=MODEL_SHA:raise ValueError('Pinned checkpoint checksum differs')
    if a.output.exists():raise ValueError('Output already exists')
    a.output.mkdir(parents=True)
    def offline(*_,**__):raise OSError('Export is offline')
    socket.socket.connect=offline;socket.create_connection=offline
    os.environ.update(YOLO_CONFIG_DIR=str(a.output/'build-runtime'),YOLO_AUTOINSTALL='False',YOLO_OFFLINE='true',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    sys.path.insert(0,str(a.deps.resolve()))
    import torch
    torch.set_num_threads(2)
    allowed={
        'ultralytics.nn.tasks':['PoseModel'],
        'ultralytics.nn.modules.block':['Attention','Bottleneck','C2PSA','C3k','C3k2','DFL','PSABlock','SPPF'],
        'ultralytics.nn.modules.conv':['Concat','Conv','DWConv'],
        'ultralytics.nn.modules.head':['Pose'],
        'torch.nn':['SiLU','BatchNorm2d','ModuleList','Sequential','Conv2d','Identity','MaxPool2d','Upsample']}
    classes=[getattr(importlib.import_module(m),n) for m,names in allowed.items() for n in names]
    with torch.serialization.safe_globals(classes):checkpoint=torch.load(a.weights,map_location='cpu',weights_only=True)
    model=(checkpoint.get('ema') or checkpoint['model']).float().cpu().eval();del checkpoint
    if list(model.model[-1].kpt_shape)!=[6,3] or model.model[-1].nc!=1:raise ValueError('Unexpected pose layout')
    class Output(torch.nn.Module):
        def __init__(self,m):super().__init__();self.m=m
        def forward(self,x):return self.m(x)[0]
    wrapper=Output(model).eval();torch.manual_seed(13)
    synthetic=torch.rand(1,3,640,640)
    with torch.no_grad():
        expected=wrapper(synthetic);traced=torch.jit.trace(wrapper,synthetic,check_trace=False,strict=False)
        target=a.output/'eye-pose-cpu.ts';traced.save(str(target))
        loaded=torch.jit.load(str(target),map_location='cpu').eval()
        differences=[]
        for value in (synthetic,torch.zeros_like(synthetic),torch.ones_like(synthetic)*.5):
            ref=wrapper(value);out=loaded(value);torch.testing.assert_close(ref,out,rtol=1e-4,atol=1e-4)
            differences.append(float((ref-out).abs().max()))
    manifest={'schema':'plumivault-quality-models-v1','version':'bird-quality-v2','eye_file':target.name,'eye_sha256':checksum(target),'source_model':'synthet/eye-pose-v0','source_revision':MODEL_REV,'source_sha256':MODEL_SHA,'export_torch':torch.__version__,'export_ultralytics':importlib.metadata.version('ultralytics'),'eye_shape':[1,23,8400],'semantics':'existing-bioclip-text-reference-v1','calibrated':False}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'manifest':manifest,'synthetic_max_abs_differences':differences,'photos_read':False}))


if __name__=='__main__':main()
