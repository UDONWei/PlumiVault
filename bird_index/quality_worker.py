"""One-shot quality evaluation; no model loaded, original pixels stay in memory."""
import argparse,contextlib,json,os,subprocess,sys,time
from pathlib import Path
from .common import PROJECT,load_config,encode,safe_file
from .adjustments import recipe,apply_tone

def run(cfg,request):
 flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
 result=subprocess.run([sys.executable,'-X','utf8','-B','-m','bird_index.quality_worker','--config',cfg['_path']],input=encode(request),capture_output=True,text=True,encoding='utf-8',timeout=180,cwd=PROJECT,creationflags=flags)
 if result.returncode:raise ValueError('质量计算失败：'+result.stderr[-500:])
 return json.loads(result.stdout)

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);cfg=load_config(p.parse_args().config);req=json.load(sys.stdin);protocol=sys.stdout
 from stage1_probe import install_guard,fingerprint,decode,MemoryMeter
 install_guard(Path(cfg['data_dir']));start=time.perf_counter();image=None
 with contextlib.redirect_stdout(sys.stderr),MemoryMeter() as meter:
  try:
   root=next(r for r in cfg['roots'] if r['id']==req['root_id'])
   if root.get('allow_paths') is not None and req['relative_path'] not in root['allow_paths']:raise ValueError('照片超出授权清单')
   path=safe_file(root['path'],req['relative_path']);before=fingerprint(path,True)
   if before['sha256']!=req['expected_sha']:raise ValueError('原片指纹变化')
   row={'path':req['display_path'],'source_path':req['relative_path'],'before':before,'timings':{}};image=decode(path,'full',1600,row,row['timings']);settings=recipe(req['adjustment']['recipe']);toned=apply_tone(image,settings);image.close();image=toned
   from .quality import assess
   row['quality']=assess(image,settings['box'] or req.get('detected_box'));row['quality'].update(source_sha=before['sha256'],recipe=settings,input='完整解码与当前调整画面')
   after=fingerprint(path,True)
   if before!=after:raise ValueError('评分期间原片变化')
   meter.sample();row.update(after=after,decode_ok=True,source_unchanged=True,adjustments=settings,memory=meter.report());row['timings']['total_s']=time.perf_counter()-start
  finally:
   if image is not None:image.close()
 protocol.write(encode(row));protocol.flush()
if __name__=='__main__':main()
