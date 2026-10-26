"""初筛标记独立于鸟种复核；写入不会改变原文件。"""
import json
from .common import now,encode
from .db import Conflict

def set_selection(db,items,flag,rating):
 if flag not in (None,'none','keep','reject') or (rating is not None and (type(rating)!=int or not 0<=rating<=5)):raise ValueError('标记或星级无效')
 if not isinstance(items,list) or not 1<=len(items)<=100 or len({i['id'] for i in items})!=len(items):raise ValueError('请选择 1～100 张照片')
 records=[]
 with db.transaction() as c:
  if c.execute("SELECT 1 FROM file_plans WHERE state='executing' LIMIT 1").fetchone():raise Conflict("原片整理未完成，请先恢复该操作")
  for item in items:
   p=c.execute('SELECT source_status FROM photos WHERE id=?',(item['id'],)).fetchone()
   if not p or p['source_status']!='available':raise ValueError('只能标记原路径可用的照片')
   old=c.execute('SELECT * FROM selections WHERE photo_id=?',(item['id'],)).fetchone()
   revision=old['revision'] if old else 0
   if revision!=item['revision']:raise Conflict('标记已被另一页面修改，请刷新')
   record={'photo_id':item['id'],'flag':flag if flag is not None else (old['flag'] if old else 'none'),'rating':rating if rating is not None else (old['rating'] if old else 0),'revision':revision+1,'updated_at':now()}
   c.execute('INSERT INTO selections VALUES(?,?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET flag=excluded.flag,rating=excluded.rating,revision=excluded.revision,updated_at=excluded.updated_at',tuple(record.values()))
   records.append(record)
  db.bump(c)
 return {'records':records}

def acceptance_report(db,job_id=None):
 """只读取最近一次任务已保存的结果，不扫描或打开原图。"""
 jobs=db.query('SELECT * FROM jobs WHERE id=?',(job_id,)) if job_id else db.query('SELECT * FROM jobs ORDER BY created_at DESC,rowid DESC LIMIT 1')
 if job_id and not jobs:raise ValueError('任务不存在')
 if not jobs:return {'job':None,'photos':[],'notice':'暂无任务'}
 job=jobs[0];labels={r['id']:r['name'] for r in db.query('SELECT id,name FROM labels')};photos=[]
 rows=db.query('SELECT p.id,p.rel_path,p.source_status,p.inference_status,j.state,j.error,a.payload,(SELECT h.payload FROM processing_history h WHERE h.photo_id=p.id AND h.job_id=j.job_id ORDER BY h.id DESC LIMIT 1) job_payload,m.status,m.species FROM job_items j JOIN photos p ON p.id=j.photo_id LEFT JOIN analyses a ON a.photo_id=p.id LEFT JOIN manual m ON m.photo_id=p.id WHERE j.job_id=? ORDER BY p.id',(job['id'],))
 for r in rows:
  history=r.pop('job_payload');latest=r.pop('payload');payload=json.loads(history or latest or '{}');r['measurement_source']='job_history' if history else 'latest_analysis_not_job_specific';species=json.loads(r.pop('species') or '[]');candidates=(payload.get('views') or [{}])[0].get('context_candidates',[])
  photos.append({**r,'manual_species':[labels.get(s,s) for s in species],'decode_ok':payload.get('decode_ok'),'decode_route':payload.get('decode_route'),'source_unchanged':payload.get('source_unchanged'),'timings':payload.get('timings',{}),'decode_breakdown':payload.get('decode_breakdown',{}),'worker_cpu_s':payload.get('worker_cpu_s'),'memory':payload.get('memory',{}),'candidates':[{'name':labels.get(x['label'].get('scientific_name'),x['label'].get('zh_name') or x['label'].get('prompt')),'score':x.get('ranking_score',x.get('score',x.get('visual_score')))} for x in candidates[:5]]})
 peaks=[p['memory'].get('section_rss_sample_peak_bytes') for p in photos if p['state']=='done' and p['measurement_source']=='job_history'];times=[p['timings'].get('total_s') for p in photos if p['state']=='done' and p['measurement_source']=='job_history']
 return {'job':job,'photos':photos,'max_photo_seconds':max((v for v in times if v is not None),default=None),'max_sampled_worker_rss_bytes':max((v for v in peaks if v is not None),default=None),'limitations':['模型分数不是正确概率；正确性需人工核对。','历史任务优先使用该任务的处理快照；measurement_source=latest_analysis_not_job_specific 表示只有当前分析结果，不能作为该次任务的耗时，跳过项不计本次处理峰值。人工标注和路径状态为当前记录。','内存为每 20 毫秒采样的推理进程 RSS，模型初始化前未采样，不等于整个容器的峰值。','已有任务结果；读取报告不会重新识别或扩大扫描范围。','decode_breakdown 是 decode_s 的子项，不重复相加；worker_cpu_s 为线程累计 CPU 时间，可能大于单图墙钟耗时。指纹耗时包含读取与哈希，不能直接等同于硬盘等待时间。']}
