"""Experimental, offline CPU evaluator. Not imported by the NAS application.

Only the pinned model below is accepted. Default input is synthetic; --manifest
enables explicit read-only paths, never discovery or directory scanning.
"""
import argparse,hashlib,json,math,os,sys,time,threading,socket,statistics,importlib,html,platform
from pathlib import Path

MODEL_SHA='ec9e4b80a93eb6e2b21633e2ff2df30c49faa1eb7919dd24345c7dc295b2d1be'
MODEL_REV='6e7bd361ba84b17d81f0fb4315a44a868df5b692'
KEYS=['beak','left_eye','right_eye','head_top','left_shoulder','right_shoulder']

def manifest(path):
 data=json.loads(Path(path).read_text(encoding='utf-8-sig'));rows=data['samples']
 if not isinstance(rows,list) or not 1<=len(rows)<=30:raise ValueError('Explicit evaluation manifest requires 1 to 30 samples')
 seen=set()
 for r in rows:
  p=Path(r['path'])
  if not p.is_absolute() or not p.is_file() or p.suffix.lower() not in ('.arw','.jpg','.jpeg','.png','.tif','.tiff','.webp','.bmp'):raise ValueError('Existing absolute image path required')
  if str(p.resolve()) in seen:raise ValueError('Duplicate sample')
  seen.add(str(p.resolve()))
  b=r.get('subject_box',[0,0,1,1])
  if len(b)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in b) or not (0<=b[0]<b[2]<=1 and 0<=b[1]<b[3]<=1):raise ValueError('subject_box must be normalized x1,y1,x2,y2')
  if len(r.get('sha256',''))!=64 or any(c not in '0123456789abcdef' for c in r['sha256']):raise ValueError('Pinned source SHA256 required')
 return rows

def checksum(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def review_page(report,target):
 cards=[]
 for r in report['samples']:
  pid=r['id'];points=[p for p in r['keypoints_crop_pixels'] if p['name'] in ('left_eye','right_eye') and p['confidence']>=.5 and 0<=p['x']<r['input_size'][0] and 0<=p['y']<r['input_size'][1]]
  choices=''.join(f'<label>{label}<select data-field="{field}"><option value="unknown">未核对 / 无法判断</option>'+''.join(f'<option value="{v}">{t}</option>' for v,t in opts)+'</select></label>' for field,label,opts in [('eye','眼点位置',[('correct','标出的眼点均正确'),('wrong','存在错误眼点'),('missed','可见眼睛未标出')]),('focus','眼部合焦（请结合原图）',[('sharp','清晰'),('soft','不清晰')]),('occlusion','主体遮挡',[('clear','无遮挡'),('partial','部分遮挡'),('heavy','明显遮挡')]),('preference','个人偏好',[('candidate','愿意列为备选'),('ordinary','普通'),('reject','不选')])])
  cards.append(f'<article data-id="{pid}"><h2>照片 {pid} · {html.escape(Path(r["path"]).name)}</h2><img src="eye-review-assets/{pid}.jpg" alt="照片 {pid} 主体缩略图与候选眼点"><p>达到实验阈值的眼点：{len(points)}；红圈为候选左眼，蓝圈为候选右眼。不是对焦结论。</p>{choices}<label>备注<input data-field="note" maxlength="500"></label></article>')
 data=json.dumps({'schema':'plumivault-eye-review-v1','model_sha256':report['model_sha256'],'photos':[{'id':r['id'],'source_sha256':r['sha256']} for r in report['samples']]},ensure_ascii=False).replace('<','\\u003c')
 text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; script-src 'unsafe-inline'"><title>翎匣 · 鸟眼模型实验复核</title><style>body{font:16px system-ui;background:#171d22;color:#e7edf2;max-width:1100px;margin:auto;padding:20px}header{position:sticky;top:0;background:#171d22;padding:12px;z-index:1}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}article{background:#26323b;padding:16px;border-radius:8px}img{max-width:100%;display:block}label{display:block;margin:10px 0}select,input,button{font:inherit;margin:5px;padding:7px}p{line-height:1.5}small{color:#b4c5ce}</style><header><h1>鸟眼定位实验 · 尚未上线</h1><p>仅此前 10 张的限尺寸主体图。请核对圆圈是否落在真实眼睛上；看不清时选“无法判断”。判断对焦应另在图库打开原始像素。本页不上传、不移动、不改图库记录；请导出结果，刷新不会保留未导出的选择。</p><button id="export">导出复核 JSON</button><span id="status"></span></header><main>'''+''.join(cards)+'''</main><script>const data='''+data+''';document.getElementById('export').onclick=()=>{const result={...data,photos:data.photos.map(p=>{const node=document.querySelector('article[data-id="'+p.id+'"]'),r={...p};for(const f of node.querySelectorAll('[data-field]'))r[f.dataset.field]=f.value;return r;})};const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='plumivault-eye-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);document.getElementById('status').textContent='已导出；请保留 JSON 文件。';};</script></html>'''
 target.write_text(text,encoding='utf-8')

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--weights',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--deps',type=Path);ap.add_argument('--manifest',type=Path);ap.add_argument('--review-html',action='store_true',help='Write <=512px derived review thumbnails beside the report; no full-sized copies');a=ap.parse_args()
 if a.output.exists():raise ValueError('Refusing to overwrite report')
 rows=manifest(a.manifest) if a.manifest else []
 if a.review_html and (not rows or len({r.get('id') for r in rows})!=len(rows) or any(type(r.get('id'))!=int or r['id']<1 for r in rows)):raise ValueError('Review requires distinct positive numeric IDs')
 if any(a.output.resolve().is_relative_to(Path(r['path']).resolve().parent) for r in rows):raise ValueError('Output must be outside every source directory')
 if checksum(a.weights)!=MODEL_SHA:raise ValueError('Candidate model SHA256 mismatch')
 if a.review_html:
  assets=a.output.parent/'eye-review-assets';assets.mkdir(parents=True,exist_ok=False)
  if (a.output.parent/'eye-review.html').exists():raise ValueError('Review already exists')
 if a.deps:sys.path.insert(0,str(a.deps.resolve()))
 # Disable network before importing the evaluator stack. No telemetry/downloads.
 def offline(*args,**kwargs):raise OSError('Network disabled during local evaluation')
 socket.socket.connect=offline;socket.create_connection=offline
 runtime=a.output.parent/'eye-eval-runtime';runtime.mkdir(parents=True,exist_ok=True)
 os.environ.update(YOLO_CONFIG_DIR=str(runtime),YOLO_AUTOINSTALL='False',YOLO_OFFLINE='true',MPLCONFIGDIR=str(runtime/'matplotlib'),OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
 import psutil
 peak=[psutil.Process().memory_info().rss];stop=threading.Event()
 def watch():
  while not stop.wait(.01):peak[0]=max(peak[0],psutil.Process().memory_info().rss)
 thread=threading.Thread(target=watch,daemon=True);thread.start();started=time.perf_counter()
 import numpy as np,torch
 from PIL import Image
 torch.set_num_threads(2);torch.set_num_interop_threads(1)
 # Explicit allowlist, never arbitrary checkpoint globals or weights_only=False.
 allowed={
  'ultralytics.nn.tasks':['PoseModel'],
  'ultralytics.nn.modules.block':['Attention','Bottleneck','C2PSA','C3k','C3k2','DFL','PSABlock','SPPF'],
  'ultralytics.nn.modules.conv':['Concat','Conv','DWConv'],
  'ultralytics.nn.modules.head':['Pose'],
  'torch.nn':['SiLU','BatchNorm2d','ModuleList','Sequential','Conv2d','Identity','MaxPool2d','Upsample']}
 classes=[getattr(importlib.import_module(m),n) for m,names in allowed.items() for n in names]
 with torch.serialization.safe_globals(classes):checkpoint=torch.load(a.weights,map_location='cpu',weights_only=True)
 model=(checkpoint.get('ema') or checkpoint['model']).float().eval();del checkpoint
 if list(model.model[-1].kpt_shape)!=[6,3] or model.model[-1].nc!=1:raise ValueError('Unexpected model output layout')
 load_s=time.perf_counter()-started
 def infer(im):
  w,h=im.size;scale=min(640/w,640/h);nw,nh=max(1,round(w*scale)),max(1,round(h*scale));left=(640-nw)//2;top=(640-nh)//2
  with Image.new('RGB',(640,640),(114,114,114)) as canvas, im.resize((nw,nh),Image.Resampling.BILINEAR) as resized:
   canvas.paste(resized,(left,top));arr=np.array(canvas,dtype=np.float32)/255
  tensor=torch.from_numpy(arr).permute(2,0,1).unsqueeze(0).contiguous();t=time.perf_counter()
  with torch.inference_mode():out=model(tensor)
  output=out[0] if isinstance(out,tuple) else out;duration=time.perf_counter()-t
  if output.ndim!=3 or output.shape[1]!=23:raise ValueError('Unexpected candidate prediction shape')
  raw=output[0,:,output[0,4].argmax()].detach().numpy();confidence=float(raw[4])
  points=[{'name':name,'x':float((raw[5+i*3]-left)/scale),'y':float((raw[6+i*3]-top)/scale),'confidence':float(raw[7+i*3])} for i,name in enumerate(KEYS)] if confidence>=.25 else []
  return {'inference_s':duration,'bird_confidence':confidence,'keypoints_crop_pixels':points,'input_size':[w,h],'focus_score':None,'occlusion_score':None,'posture_aesthetic_score':None}
 report={'schema':'plumivault-eye-evaluation-v1','experimental':True,'production_enabled':False,'model_sha256':MODEL_SHA,'model_revision':MODEL_REV,'device':'cpu','torch_threads':2,'torch':torch.__version__,'numpy':np.__version__,'platform':platform.platform(),'processor':platform.processor(),'load_s':load_s,'private_images_read':bool(rows),'samples':[],'limits':['Keypoints are locations, not proof of focus or occlusion.','No calibrated quality score or group recommendation.','Computer CPU timing is not NAS timing.']}
 if not rows:
  with Image.new('RGB',(640,640),'gray') as im:
   results=[infer(im) for _ in range(6)]
  report.update(input='synthetic uniform gray; no accuracy validation',warmup_s=results[0]['inference_s'],inference_median_s=statistics.median(r['inference_s'] for r in results[1:]),synthetic_runs=results)
 else:
  from stage1_probe import decode,fingerprint
  for r in rows:
   p=Path(r['path']);before=fingerprint(p,True)
   if before['sha256']!=r['sha256']:raise ValueError('Source SHA mismatch; no inference')
   times={};info={};im=decode(p,'full',1600,info,times)
   try:
    w,h=im.size;b=r.get('subject_box',[0,0,1,1]);box=(int(b[0]*w),int(b[1]*h),max(int(b[0]*w)+1,int(b[2]*w)),max(int(b[1]*h)+1,int(b[3]*h)))
    with im.crop(box) as crop:
     result=infer(crop)
     if a.review_html:
      from PIL import ImageDraw
      size=crop.size;crop.thumbnail((512,512));draw=ImageDraw.Draw(crop)
      for point in result['keypoints_crop_pixels']:
       if point['name'] not in ('left_eye','right_eye') or point['confidence']<.5 or not (0<=point['x']<size[0] and 0<=point['y']<size[1]):continue
       x,y=point['x']*crop.width/size[0],point['y']*crop.height/size[1];color='#ff5656' if point['name']=='left_eye' else '#52bfff';draw.ellipse((x-5,y-5,x+5,y+5),outline=color,width=2)
      crop.save(assets/f'{r["id"]}.jpg',quality=80)
   finally:im.close()
   after=fingerprint(p,True)
   if before!=after:raise ValueError('Source changed during evaluation')
   report['samples'].append({'id':r.get('id'),'path':str(p),'sha256':r['sha256'],'group':r.get('group'), 'crop_pixels':box,'decode_timings':times,**result})
 stop.set();thread.join();report['sampled_peak_rss_bytes']=peak[0];report['total_s']=time.perf_counter()-started
 if a.review_html:review_page(report,a.output.parent/'eye-review.html')
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'report':str(a.output),'model_enabled_in_app':False,'samples':len(rows),'peak_rss_bytes':peak[0]}))

if __name__=='__main__':main()
