"""本地 CPU 鸟体定位；只处理内存图像，结果必须由用户复核。"""
import hashlib
import json
import math
from pathlib import Path


def iou(a,b):
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    area=lambda x:(x[2]-x[0])*(x[3]-x[1])
    return overlap/(area(a)+area(b)-overlap) if overlap else 0


def choose_subject(proposals, threshold=.35, padding=.18):
    if not 0<threshold<1 or not 0<=padding<=.5:raise ValueError('检测阈值/边距无效')
    clean=[]
    for p in proposals:
        box=p['box'];score=p['score']
        if not math.isfinite(score) or not 0<=score<=1 or len(box)!=4 or not all(math.isfinite(x) for x in box):continue
        if not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1):continue
        if score>=threshold and not p.get('internal_edge_cut'):clean.append(dict(p))
    clean.sort(key=lambda p:-p['score'])
    kept=[]
    for p in clean:
        if not any(iou(p['box'],q['box'])>.45 for q in kept):kept.append(p)
    if not kept:return {'status':'no_detection','selected_box':None,'detections':[], 'message':'未定位到可靠鸟体，保留整图；不代表没有鸟'}
    subject=kept[0];x1,y1,x2,y2=subject['box'];dx=(x2-x1)*padding;dy=(y2-y1)*padding
    box=[max(0,x1-dx),max(0,y1-dy),min(1,x2+dx),min(1,y2+dy)]
    return {'status':'detected','selected_box':box,'detections':kept,'selected_score':subject['score'],
            'multiple_candidates':len(kept)>1,'selection':'最高检测分数；与鸟种分类及人工真值无关',
            'message':('检测到多个可能鸟体，当前展示最高分主体，需复核是否漏鸟' if len(kept)>1 else '自动鸟体框外扩 18%，保留身体周边；完整性待复核')}


def square_box(box,size):
    # 方形上下文避免 BioCLIP 的中央裁切再次截掉鸟体。
    w,h=size;x1,y1,x2,y2=box
    left,top,right,bottom=x1*w,y1*h,x2*w,y2*h
    side=max(right-left,bottom-top)
    if side>min(w,h):return box
    cx=(left+right)/2;cy=(top+bottom)/2
    left=max(0,min(w-side,cx-side/2));top=max(0,min(h-side,cy-side/2))
    return [left/w,top/h,(left+side)/w,(top+side)/h]


class LocalBirdDetector:
    def __init__(self, config_path, threshold=.35):
        import torch
        from torchvision.models.detection import ssdlite320_mobilenet_v3_large,SSDLite320_MobileNet_V3_Large_Weights
        self.threshold=threshold
        config_path=Path(config_path);config=json.loads(config_path.read_text(encoding='utf-8-sig'))
        if config['architecture']!='ssdlite320_mobilenet_v3_large':raise ValueError('检测器类型错误')
        weights=(config_path.parent/config['weights']).resolve(strict=True)
        if not weights.is_relative_to(config_path.parent.resolve()) or hashlib.sha256(weights.read_bytes()).hexdigest()!=config['sha256']:raise ValueError('检测权重路径或哈希不符')
        # 两项 weights 显式为空，防止隐式下载 ImageNet backbone。
        self.model=ssdlite320_mobilenet_v3_large(weights=None,weights_backbone=None,num_classes=91).cpu().eval()
        self.model.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True))
        meta=SSDLite320_MobileNet_V3_Large_Weights.COCO_V1.meta
        self.bird_id=meta['categories'].index('bird')
        self.details={**config,'score_threshold':threshold,'padding':.18,'device':'cpu','batch_size':1,
                      'search':'整图 + 3×3 重叠分区（边长 40%）；内存内检测，不输出这些分区',
                      'preprocess':'PIL bilinear resize 320x320，float [0,1]，模型内部归一化；独立定位 bird 类'}

    def detect(self,image):
        import torch
        from PIL import Image
        from torchvision.transforms.functional import pil_to_tensor
        windows=[(0,0,1,1)]+[(x,y,x+.4,y+.4) for y in (0,.3,.6) for x in (0,.3,.6)]
        proposals=[];w,h=image.size
        with torch.inference_mode():
            for n,window in enumerate(windows):
                x1,y1,x2,y2=window
                bounds=(math.floor(x1*w),math.floor(y1*h),math.ceil(x2*w),math.ceil(y2*h))
                crop=image if n==0 else image.crop(bounds)
                try:
                    small=crop.resize((320,320),Image.Resampling.BILINEAR)
                    try:tensor=pil_to_tensor(small).float()/255
                    finally:small.close()
                    prediction=self.model([tensor])[0]
                finally:
                    if crop is not image:crop.close()
                for b,score,label in zip(prediction['boxes'].tolist(),prediction['scores'].tolist(),prediction['labels'].tolist()):
                    if label!=self.bird_id or score<self.threshold:continue
                    clipped=[max(0,min(1,v/320)) for v in b]
                    edge_cut=(n>0 and ((clipped[0]<.01 and bounds[0]>0) or (clipped[1]<.01 and bounds[1]>0) or (clipped[2]>.99 and bounds[2]<w) or (clipped[3]>.99 and bounds[3]<h)))
                    mapped=[(bounds[0]+clipped[0]*(bounds[2]-bounds[0]))/w,(bounds[1]+clipped[1]*(bounds[3]-bounds[1]))/h,
                            (bounds[0]+clipped[2]*(bounds[2]-bounds[0]))/w,(bounds[1]+clipped[3]*(bounds[3]-bounds[1]))/h]
                    proposals.append({'box':mapped,'score':score,'search_window':n,'internal_edge_cut':edge_cut})
        result=choose_subject(proposals,self.threshold)
        if result['selected_box']:
            result['padded_box_before_square']=result['selected_box']
            result['selected_box']=square_box(result['selected_box'],image.size)
            result['crop_geometry']='优先扩展为图内方形，保留检测框和边距；大于图像短边时保留矩形'
        result.update(search_windows=len(windows),raw_proposals=proposals)
        return result

