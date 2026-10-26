"""从 PyTorch 官方准备固定版本检测权重；只在准备阶段联网。"""
import argparse,hashlib,json,urllib.request
from pathlib import Path
NAME='ssdlite320_mobilenet_v3_large_coco-a79551df.pth'
URL='https://download.pytorch.org/models/'+NAME
SHA='a79551df90c79834bcd3bb3845ef9d966b5449a3a9b2833ae8404778ca5d65d2'
def prepare(folder):
 folder.mkdir(parents=True,exist_ok=True);target=folder/NAME
 if not target.exists():
  partial=folder/(NAME+'.part')
  with partial.open('xb') as out,urllib.request.urlopen(URL,timeout=60) as response:
   while block:=response.read(256*1024):out.write(block)
  if hashlib.sha256(partial.read_bytes()).hexdigest()!=SHA:raise ValueError('权重 SHA-256 不符，保留 .part 供排查')
  partial.rename(target)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=SHA:raise ValueError('已有检测权重不匹配，不覆盖')
 metadata={'architecture':'ssdlite320_mobilenet_v3_large','weights':NAME,'source':URL,'torchvision':'0.22.1','sha256':SHA,'code_license':'BSD-3-Clause','weights_terms':'Torchvision pretrained weights may have training-data terms; local evaluation only, weights excluded from source package','input_size':320,'category':'bird'}
 (folder/'detector-ssdlite.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8');print('Verified detector:',target)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-dir',type=Path,required=True);a=p.parse_args();prepare(a.model_dir)

