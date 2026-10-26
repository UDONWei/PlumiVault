"""Local, explainable culling estimates. Not a calibrated aesthetic/focus model."""
import io,json,math
import numpy as np
from PIL import Image
from .common import encode,now

def assess(image,box=None):
 # Fixed analysis scale limits CPU/memory and makes scores comparable within a burst.
 scale=min(1,1024/max(image.size));sample=image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))),Image.Resampling.LANCZOS)
 try:
  rgb=np.asarray(sample.convert('RGB'),dtype=np.float32)/255
  gray=rgb@np.array([.2126,.7152,.0722],dtype=np.float32);h,w=gray.shape;roi=gray
  issues=[];framing=None
  if box and len(box)==4:
   x1,y1,x2,y2=[max(0,min(1,float(x))) for x in box]
   if x2>x1 and y2>y1:
    roi=gray[int(y1*h):max(int(y1*h)+1,int(y2*h)),int(x1*w):max(int(x1*w)+1,int(x2*w))]
    area=(x2-x1)*(y2-y1);margin=min(x1,y1,1-x2,1-y2);framing=90
    if area<.015:framing-=35;issues.append('主体偏小，细节判断可靠性低')
    if margin<.015:framing-=25;issues.append('主体接近画面边缘，留意裁断')
  else:issues.append('未定位主体，清晰度按整图估计');framing=None
  if min(roi.shape)<8:sharpness=0;clarity=None;issues.append('主体像素不足，无法可靠评分')
  else:
   lap=4*roi[1:-1,1:-1]-roi[:-2,1:-1]-roi[2:,1:-1]-roi[1:-1,:-2]-roi[1:-1,2:]
   sharpness=float(np.var(lap));clarity=round(float(np.clip(22*math.log1p(sharpness/0.00015),0,100)))
   if clarity<40:issues.append('细节偏弱：疑似虚焦、运动模糊或低纹理')
  high=float(np.mean(roi>=.98));low=float(np.mean(roi<=.025));exposure=round(max(0,100-200*high-120*low))
  if high>.03:issues.append('主体高光溢出，疑似过曝（白色羽毛也可能触发）')
  if low>.12:issues.append('主体暗部较多，疑似欠曝（深色羽毛也可能触发）')
  components=[(clarity,.60),(exposure,.25),(framing,.15)];weight=sum(v for k,v in components if k is not None)
  score=round(sum(k*v for k,v in components if k is not None)/weight)
  return {'version':'local-quality-v1','score':score,'clarity':clarity,'exposure':exposure,'composition':framing,'issues':issues or ['未发现明显技术问题，仍需目视复核'],'needs_review':bool(issues),'metrics':{'laplacian_variance':round(sharpness,8),'highlight_fraction':round(high,4),'shadow_fraction':round(low,4)},'analysis_size':[w,h],'method':'已有主体定位＋局部清晰度、曝光和边缘构图规则；未训练审美模型','limits':'参考分，非正确概率。噪声可能抬高清晰度分；不能可靠区分虚焦与运动模糊，不能判断鸟姿美感。'}
 finally:sample.close()

def score_existing(lib,photo_id,sha):
 from .db import Conflict
 from .adjustments import recipe
 photo=lib.public(lib.items([photo_id])[0]);cached=photo.get('quality')
 if not sha or photo['sha256']!=sha:raise Conflict('照片版本已改变')
 adjustment=lib.adjustment(photo_id)
 if adjustment['source_sha'] not in (None,sha):raise Conflict('旧调整参数已失效，请先确认编辑参数')
 if cached and cached.get('source_sha')==sha and recipe(cached.get('recipe'))==adjustment['recipe']:return {'photo_id':photo_id,'quality':cached,'cached':True}
 if not lib.image_lock.acquire(blocking=False):raise ValueError('正在读取或识别原图，请稍后评分')
 try:
  source=lib.photo_source(photo_id);req={'photo_id':photo_id,'root_id':source['root_id'],'relative_path':source['rel_path'],'display_path':source['display_path'],'expected_sha':sha,'adjustment':adjustment,'detected_box':photo['detection'].get('selected_box')}
  from .quality_worker import run
  row=run(lib.cfg,req)
  quality=row['quality'];quality.update(created_at=now(),decode_memory=row['memory'])
 finally:
  lib.image_lock.release()
 with lib.db.transaction() as c:
  row=c.execute('SELECT sha256,summary FROM photos WHERE id=?',(photo_id,)).fetchone()
  if row['sha256']!=sha:raise Conflict('评分期间索引版本改变')
  edit=c.execute('SELECT revision FROM adjustments WHERE photo_id=?',(photo_id,)).fetchone()
  if (edit['revision'] if edit else 0)!=adjustment['revision']:raise Conflict('评分期间调整参数改变，请重新评分')
  payload=json.loads(row['summary']);payload['quality']=quality;c.execute('UPDATE photos SET summary=? WHERE id=?',(encode(payload),photo_id))
  full=c.execute('SELECT payload FROM analyses WHERE photo_id=?',(photo_id,)).fetchone()
  if full:
   payload=json.loads(full['payload']);payload['quality']=quality;c.execute('UPDATE analyses SET payload=? WHERE photo_id=?',(encode(payload),photo_id))
  lib.db.bump(c)
 return {'photo_id':photo_id,'quality':quality,'cached':False}
