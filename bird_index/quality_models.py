"""Offline CPU references: bird-eye location and BioCLIP text/image comparisons.

Not calibrated focus, occlusion or aesthetic probabilities. Unknown dimensions
are excluded from the combined score, never silently assigned a good score.
"""
import json
import math
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageFilter
from .common import digest

VERSION='bird-quality-v2'
EYE_SHA='1d0b6ecf50598fdebe800d89f0e925bcd1c12dfae9cc268e4202d704b99e0061'
PROMPTS={
    'occlusion':[
        ('clear','主体较完整、遮挡较少',100,['a photo of a bird clearly visible with nothing blocking its body','a fully visible bird with an unobstructed head and body']),
        ('partial','疑似部分遮挡',55,['a photo of a bird partially hidden behind branches and leaves','a bird with part of its body obscured by vegetation']),
        ('heavy','疑似明显遮挡',15,['a photo of a bird mostly hidden behind dense leaves and branches','a barely visible bird with its head and body heavily obscured'])],
    'posture':[
        ('good','姿态较舒展、表现较好',100,['a beautiful wildlife photo of a bird in a graceful expressive pose','an attractive bird portrait with a natural elegant posture']),
        ('ordinary','姿态普通',60,['an ordinary wildlife photograph of a bird in a plain neutral pose','a simple documentary photograph of a bird resting normally']),
        ('poor','姿态可能欠佳',20,['a bird photographed in an awkward unflattering pose with its head turned away','a wildlife photo showing an awkward bird posture with its face hidden'])]}


def manifest_path(cfg):return Path(cfg['model_dir'])/'quality/manifest.json'


def cache_key(cfg):
    path=manifest_path(cfg)
    return VERSION+':'+(digest(path) if path.is_file() else 'missing')


def unknown(reason):return {'status':'unknown','score':None,'label':reason}


def semantic_reference(values, definitions):
    values=np.asarray(values,dtype=np.float64)
    if values.shape!=(len(definitions),) or not np.isfinite(values).all():raise ValueError('Invalid semantic output')
    order=np.argsort(values)[::-1];margin=float(values[order[0]]-values[order[1]])
    evidence={'similarities':[round(float(x),5) for x in values],'margin':round(margin,5),'method':'BioCLIP 文图匹配，非专门训练的遮挡/审美模型'}
    if margin<.015:return {**unknown('描述匹配接近，暂无法判断'),**evidence}
    weights=np.exp((values-values.max())*25);weights/=weights.sum()
    score=round(float(sum(w*d[2] for w,d in zip(weights,definitions))))
    best=definitions[int(order[0])]
    return {'status':'reference','score':score,'category':best[0],'label':best[1],**evidence}


def eye_reference(crop,prediction):
    """Fixed 640 letterbox geometry; use original crop pixels for local detail."""
    raw=np.asarray(prediction,dtype=np.float32)
    if raw.ndim!=3 or raw.shape[:2]!=(1,23) or raw.shape[2]<1 or not np.isfinite(raw).all():raise ValueError('Invalid eye output')
    index=int(np.argmax(raw[0,4]));row=raw[0,:,index];confidence=float(row[4]);w,h=crop.size
    result={**unknown('未可靠定位鸟眼'),'bird_confidence':round(confidence,4),'points':[],'method':'鸟眼定位＋局部平滑后细节强度；不是镜头合焦证明'}
    if confidence<.4:return result
    scale=min(640/w,640/h);nw,nh=max(1,round(w*scale)),max(1,round(h*scale));left=(640-nw)//2;top=(640-nh)//2
    scores=[];radius=max(6,min(48,round(min(w,h)*.035)))
    for i,name in ((1,'left_eye'),(2,'right_eye')):
        x=(float(row[5+i*3])-left)/scale;y=(float(row[6+i*3])-top)/scale;c=float(row[7+i*3])
        if c<.65 or not (radius<=x<w-radius and radius<=y<h-radius):continue
        box=(int(x-radius),int(y-radius),int(x+radius),int(y+radius))
        if min(box[2]-box[0],box[3]-box[1])<24:continue
        with crop.crop(box) as region,region.convert('L') as gray,gray.filter(ImageFilter.GaussianBlur(.6)) as smoothed:
            a=np.asarray(smoothed,dtype=np.float32)/255
        lap=4*a[1:-1,1:-1]-a[:-2,1:-1]-a[2:,1:-1]-a[1:-1,:-2]-a[1:-1,2:]
        variance=float(np.var(lap));score=round(float(np.clip(24*math.log1p(variance/.0001),0,100)));scores.append(score)
        result['points'].append({'name':name,'x':round(x/w,6),'y':round(y/h,6),'confidence':round(c,4),'score':score,'patch_pixels':list(a.shape[::-1])})
    if not scores:return result
    score=round(float(np.mean(scores)))
    return {**result,'status':'reference','score':score,'label':'眼部细节偏弱，需核对虚焦或模糊' if score<40 else '眼部细节中等，建议放大核对' if score<70 else '眼部细节较清晰（定位可能误判）'}


class QualityModels:
    def __init__(self,cfg,bioclip):
        self.key=cache_key(cfg);self.eye=None;self.engine=getattr(bioclip,'engine',None);self.text=None;self.error=None
        try:
            path=manifest_path(cfg)
            if not path.is_file():raise ValueError('未安装质量模型，请上传独立模型包后重新评分')
            meta=json.loads(path.read_text(encoding='utf-8'))
            if meta.get('schema')!='plumivault-quality-models-v1' or meta.get('eye_sha256')!=EYE_SHA or meta.get('eye_file')!='eye-pose-cpu.ts':raise ValueError('质量模型清单不匹配')
            weight=path.parent/'eye-pose-cpu.ts'
            if weight.is_symlink() or digest(weight)!=EYE_SHA:raise ValueError('鸟眼权重校验失败')
            if self.engine is None:raise ValueError('BioCLIP 尚未加载')
            import torch
            self.eye=torch.jit.load(str(weight),map_location='cpu').eval()
            texts=[s for group in PROMPTS.values() for _,_,_,variants in group for s in variants]
            with torch.inference_mode():
                tokens=self.engine.tokenizer(texts).to('cpu')
                features=self.engine.model.encode_text(tokens)
                features=torch.nn.functional.normalize(features,dim=-1).reshape(6,2,-1).mean(dim=1)
                self.text=torch.nn.functional.normalize(features,dim=-1).T.contiguous()
        except Exception as exc:self.eye=None;self.error=str(exc)[:250]

    def assess(self,image,box):
        started=time.perf_counter()
        result={'version':VERSION,'model_key':self.key,'calibrated':False,'status':'unavailable' if self.eye is None else 'reference','eye':unknown('无法判断'),'occlusion':unknown('无法判断'),'posture':unknown('无法判断')}
        if self.eye is None:
            result['error']=self.error;return result
        if not box:
            result['status']='unknown';result['error']='未定位鸟类主体，请先框选主体';return result
        import torch
        from .adjustments import square_input
        w,h=image.size
        try:
            if len(box)!=4 or not all(math.isfinite(x) for x in box) or not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1):raise ValueError('主体框无效')
            bounds=(int(box[0]*w),int(box[1]*h),max(int(box[0]*w)+1,int(box[2]*w)),max(int(box[1]*h)+1,int(box[3]*h)))
            with image.crop(bounds) as crop:
                if min(crop.size)<24:
                    result['status']='unknown';result['error']='主体像素不足';return result
                cw,ch=crop.size;scale=min(640/cw,640/ch);nw,nh=max(1,round(cw*scale)),max(1,round(ch*scale))
                with Image.new('RGB',(640,640),(114,114,114)) as canvas,crop.resize((nw,nh),Image.Resampling.BILINEAR) as resized:
                    canvas.paste(resized,((640-nw)//2,(640-nh)//2));a=np.array(canvas,dtype=np.float32)/255
                tensor=torch.from_numpy(a).permute(2,0,1).unsqueeze(0).contiguous()
                with torch.inference_mode():prediction=self.eye(tensor).cpu().numpy()
                result['eye']=eye_reference(crop,prediction)
                # Bound the square canvas instead of padding a full 61MP crop.
                factor=min(1,224/max(cw,ch))
                with crop.resize((max(1,round(cw*factor)),max(1,round(ch*factor))),Image.Resampling.LANCZOS) as reduced,square_input(reduced) as square:
                    with torch.inference_mode():
                        feature=self.engine.model.encode_image(self.engine.preprocess(square).unsqueeze(0).to('cpu'))
                        feature=torch.nn.functional.normalize(feature,dim=-1)
                        values=(feature@self.text).cpu().numpy()[0]
                for index,(key,definitions) in enumerate(PROMPTS.items()):result[key]=semantic_reference(values[index*3:index*3+3],definitions)
                result['subject_box']=list(box)
        except Exception as exc:
            result['status']='error';result['error']=str(exc)[:250]
        finally:result['seconds']=round(time.perf_counter()-started,4)
        return result


def combine(base,reference):
    result={**base,'version':VERSION,'technical_score':base['score'],'ai':reference,'model_key':reference['model_key']}
    weights=[('technical',base['score'],.6)]
    for key,weight in (('eye',.25),('occlusion',.1),('posture',.05)):
        part=reference[key]
        if part['status']=='reference' and part['score'] is not None:weights.append((key,part['score'],weight))
    result['score']=round(sum(v*w for _,v,w in weights)/sum(w for _,_,w in weights))
    result['score_components']=[{'name':k,'score':v,'weight':w} for k,v,w in weights]
    result['issues']=list(base['issues'])
    for key in ('eye','occlusion','posture'):
        part=reference[key]
        if part['status']=='reference' and part['score']<45:
            result['issues'].append(part['label']);result['needs_review']=True
    result['method']='技术特征＋鸟眼局部细节＋BioCLIP 遮挡/姿态描述匹配'
    result['limits']='AI 参考分，未校准；眼点可能误检，遮挡/姿态不是专门训练的分类器。未知维度不计分，不同可用维度的分数需谨慎比较；人工判断优先。'
    return result
