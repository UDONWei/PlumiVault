"""唯一 CPU 推理子进程：只读原图，写入独立数据目录，禁止网络。"""
from __future__ import annotations
import argparse,contextlib,hashlib,json,os,sys,time,traceback
from pathlib import Path
from .common import load_config,safe_file,relative,encode,FORMATS
from .adjustments import recipe,apply_tone,square_input,TONE_KEYS

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args();cfg=load_config(args.config);data=Path(cfg['data_dir']);protocol=sys.stdout
 for name in ('HF_HOME','TORCH_HOME','XDG_CACHE_HOME','TEMP','TMP','TMPDIR'):os.environ[name]=str(data/'runtime')
 os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TORCH_FORCE_WEIGHTS_ONLY_LOAD='1',OMP_NUM_THREADS=str(cfg['threads']),MKL_NUM_THREADS=str(cfg['threads']),OPENBLAS_NUM_THREADS=str(cfg['threads']))
 from stage1_probe import install_guard,LocalBioCLIP,decode,fingerprint,crop_box,MemoryMeter
 install_guard(data)
 with contextlib.redirect_stdout(sys.stderr):
  import torch
  torch.set_num_threads(cfg['threads']);torch.set_num_interop_threads(1)
  from subject_detector import LocalBirdDetector
  from context_prior import load_occurrences,resolve_context,rank_scores
  from similarity_features import describe
  started=time.perf_counter();model=LocalBioCLIP(cfg['model_dir'],Path(cfg['labels_path']),Path(cfg['text_features']) if cfg.get('text_features') else None);detector=LocalBirdDetector(Path(cfg['detector_config']));initialization=time.perf_counter()-started
  occurrences=load_occurrences(Path(cfg['priors_path']));roots={r['id']:r for r in cfg['roots']}
  thumbdir=data/'thumbnails';usage=sum(p.stat().st_size for p in thumbdir.iterdir() if p.is_file());budget=cfg['thumbnail_budget_mb']*1024**2
  from PIL import Image
  with MemoryMeter() as meter:
   protocol.write(encode({'ready':True,'initialization_s':initialization})+'\n');protocol.flush()
   for line in sys.stdin:
    image=view=model_view=None;row={'decode_ok':False,'status':'error','views':[],'timings':{}};start=time.perf_counter();cpu_start=time.process_time();meter.reset_section();path=before=None
    try:
     req=json.loads(line);root=roots[req['root_id']];rel=relative(req['relative_path'])
     if root.get('allow_paths') is not None and rel not in root['allow_paths']:raise ValueError('照片超出配置清单')
     from .scan_plan import checked_source
     path=checked_source(root['path'],rel) if req.get('expected_source') else safe_file(root['path'],rel)
     if path.suffix.lower() not in FORMATS:raise ValueError('格式不支持')
     if time.time()-path.stat().st_mtime<cfg['stable_seconds']:raise ValueError('照片仍可能正在写入，稍后重试')
     timing=time.perf_counter();before=fingerprint(path,True);row['timings']['source_hash_before_s']=time.perf_counter()-timing
     expected=req.get('expected_source')
     if expected and any(before[k]!=expected[k] for k in ('size','mtime_ns')):raise ValueError('源文件变化，请重新检查目录并确认清单')
     row.update(path=req['display_path'],directory=req['directory'],source_path=rel,source_root=root['path'],before=before)
     image=decode(path,'full',1600,row,row['timings']);row['decode_ok']=True;row['decoded_size']=list(image.size)
     adjustment=req.get('adjustment') or {};settings=recipe(adjustment.get('recipe'));stale=bool(adjustment.get('source_sha') and adjustment['source_sha']!=before['sha256'])
     if stale and adjustment.get('strict'):raise ValueError('原图内容已改变，旧框选不能复用；请先更新索引')
     if stale:settings=recipe()
     row['adjustments']={**settings,'source_sha':before['sha256'],'stale_recipe_ignored':stale,'frame':'decoded_full_v1'}
     timing=time.perf_counter()
     if any(settings[k]!=0 for k in TONE_KEYS):
      toned=apply_tone(image,settings);image.close();image=toned
     row['timings']['tone_s']=time.perf_counter()-timing
     timing=time.perf_counter()
     row['capture_context']=resolve_context(req['context'],{},row.get('exif',{}),root.get('name',Path(root['path']).name),rel,occurrences['regions']);row['similarity']={'whole':describe(image)};row['timings']['similarity_whole_s']=time.perf_counter()-timing
     timing=time.perf_counter()
     try:
      row['detection']={'status':'manual','selected_box':settings['box'],'message':'用户手动框选主体'} if settings['box'] else detector.detect(image)
     except Exception as exc:row['detection']={'status':'error','selected_box':None,'message':'主体检测失败，保留整图待复核','error':str(exc)}
     row['timings']['detection_s']=time.perf_counter()-timing
     box=row['detection'].get('selected_box');view=image;entry={'name':'subject' if box else 'whole','source':'manual_box' if settings['box'] else 'automatic_bird_detection' if box else 'whole'}
     if box:view,entry['pixel_box']=crop_box(image,box);entry['normalized_box']=box
     from .quality import assess
     timing=time.perf_counter();row['quality']=assess(image,box);row['timings']['quality_s']=time.perf_counter()-timing;row['quality'].update(source_sha=before['sha256'],recipe=settings,input='当前解码与调整画面')
     timing=time.perf_counter();row['similarity']['subject']=describe(view) if box else row['similarity']['whole'];row['timings']['similarity_subject_s']=time.perf_counter()-timing;entry['size']=list(view.size);timing=time.perf_counter();model_view=square_input(view) if settings['box'] else view;scores=model.all_scores(model_view);row['timings']['classification_s']=time.perf_counter()-timing
     entry.update(rank_scores(model.labels,scores,row['capture_context'],occurrences,5));entry['all_visual_scores']=scores
     timing=time.perf_counter();after=fingerprint(path,True);row['timings']['source_hash_after_s']=time.perf_counter()-timing;row.update(after=after,source_unchanged=before==after)
     if before!=after:raise ValueError('处理期间源文件变化，结果未采用')
     name=hashlib.sha256((req['root_id']+'\0'+rel+'\0'+before['sha256']+'\0'+cfg['pipeline_version']+'\0'+encode(settings)).encode()).hexdigest()+'.jpg';target=thumbdir/name;temporary=thumbdir/(name+'.tmp')
     timing=time.perf_counter();thumb=view  # All full-resolution work is finished; resize the owned view without another full-size copy.
     try:
      thumb.thumbnail((cfg['thumbnail_edge'],cfg['thumbnail_edge']),Image.Resampling.LANCZOS);thumb.save(temporary,format='JPEG',quality=80);size=temporary.stat().st_size;old=target.stat().st_size if target.exists() else 0
      if usage-old+size>budget:temporary.unlink();raise ValueError('缩略图空间达到配置上限，请调整限额后重试')
      temporary.replace(target);usage+=size-old;entry['thumbnail']={'name':name,'size':list(thumb.size)}
     finally:row['timings']['thumbnail_s']=time.perf_counter()-timing
     row['views']=[entry];row['status']='needs_review'
    except Exception as exc:row['error']=f'{type(exc).__name__}: {exc}'
    finally:
     if model_view is not None and model_view is not view:model_view.close()
     if view is not None and view is not image:view.close()
     if image is not None:image.close()
     if path and before and 'source_unchanged' not in row:
      try:row['after']=fingerprint(path,True);row['source_unchanged']=before==row['after']
      except Exception:row['source_unchanged']=False
     row['timings']['total_s']=time.perf_counter()-start;row['worker_cpu_s']=time.process_time()-cpu_start;meter.sample();row['memory']=meter.report()
    protocol.write(encode({'row':row})+'\n');protocol.flush()
if __name__=='__main__':main()
