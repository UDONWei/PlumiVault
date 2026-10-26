from __future__ import annotations
import collections,copy,hashlib,json,re,shutil
from pathlib import Path
from .common import encode,read_json,digest,now,safe_file,STATES,relative


def read_page(path):
 text=Path(path).read_text(encoding='utf-8-sig')
 match=re.search(r'<script id="review-data" type="application/json">(.*?)</script>',text,re.S)
 if not match:raise ValueError('找不到既有复核数据')
 return json.loads(match.group(1))

def compact(row):
 data={key:copy.deepcopy(row[key]) for key in ('path','directory','exif','capture_context','before','detection','similarity','views','decode_ok','status','timings','memory','adjustments','decoded_size','quality','decode_route','source_unchanged','decode_breakdown','worker_cpu_s') if key in row}
 for view in data.get('views',[]):view.pop('all_visual_scores',None)
 return data

def validate_legacy(payload,doc):
 if doc.get('schema') not in ('bird-manual-review-v1','bird-manual-review-v2') or doc.get('batch_id')!=payload['review_batch_id']:raise ValueError('人工文件批次不符')
 rows=payload['rows'];items=doc.get('photos',[])
 if len(items)!=len(rows) or len({i['path'] for i in items})!=len(items):raise ValueError('人工文件照片数或路径不符')
 by={i['path']:i for i in items};birds={l['scientific_name'] for l in payload['labels'] if l['kind']=='bird'}
 for row in rows:
  item=by.get(row['path'])
  if not item or item['source_sha256']!=row['before']['sha256']:raise ValueError('人工文件源照片指纹不符')
  species=item['species']
  if item['status'] not in STATES or (item['status']=='confirmed')!=bool(species):raise ValueError('人工状态与鸟种不符')
  ids=[s['scientific_name'] for s in species]
  if len(ids)!=len(set(ids)) or not set(ids)<=birds:raise ValueError('未知或重复人工鸟种')
  if item['updated_at'] is not None:
   from datetime import datetime
   datetime.fromisoformat(item['updated_at'].replace('Z','+00:00'))
 return by

def bootstrap(db,cfg,page,review):
 if db.query('SELECT count(*) AS n FROM photos')[0]['n']:raise ValueError('数据库已有照片，拒绝重复初始化；使用复核导入功能')
 payload=read_page(page);doc=read_json(review);by=validate_legacy(payload,doc)
 roots={str(Path(r['path']).resolve()):r for r in cfg['roots']}
 prepared=[];total_bytes=0
 for row in payload['rows']:
  root=roots.get(str(Path(row['source_root']).resolve()))
  if root is None:raise ValueError('报告目录不在授权配置中')
  rel=relative(row['source_path'].replace('\\','/'))
  if root.get('allow_paths') is not None and rel not in root['allow_paths']:raise ValueError('报告超出限量清单')
  name=row['views'][0]['thumbnail']['name'];thumb=safe_file(Path(page).parent/'review-thumbnails',name)
  from PIL import Image
  with Image.open(thumb) as image:
   if max(image.size)>cfg['thumbnail_edge']:raise ValueError('缩略图尺寸超限')
  total_bytes+=thumb.stat().st_size;prepared.append((row,root,rel,thumb))
 if total_bytes>cfg['thumbnail_budget_mb']*1024**2:raise ValueError('缩略图超出空间限额')
 archive=db.data/'imports'/('manual-'+digest(review)+'.json')
 if not archive.exists():shutil.copyfile(review,archive)
 with db.transaction() as c:
  for label in payload['labels']:
   if label['kind']!='bird':continue
   name=label.get('birdreport',{}).get('zh_name') or label.get('zh_name') or label['scientific_name']
   if '?' in name or '\ufffd' in name:name=label['scientific_name']
   c.execute('INSERT INTO labels VALUES(?,?,?,?,?)',(label['scientific_name'],name,label.get('zh_name'),encode(label.get('aliases',[])),encode(label)))
  for row,root,rel,thumb in prepared:
   row['directory']=root['id']+'/'+str(Path(rel).parent).replace('\\','/')
   destination=db.data/'thumbnails'/thumb.name
   if destination.exists() and digest(destination)!=digest(thumb):raise ValueError('已有缩略图名称冲突')
   if not destination.exists():shutil.copyfile(thumb,destination)
   photo_id=c.execute('INSERT INTO photos(root_id,rel_path,display_path,size,mtime_ns,sha256,pipeline,inference_status,thumbnail,summary) VALUES(?,?,?,?,?,?,?,?,?,?)',(root['id'],rel,row['path'],row['before']['size'],row['before']['mtime_ns'],row['before']['sha256'],cfg['pipeline_version'],'ready',thumb.name,encode(compact(row)))).lastrowid
   c.execute('INSERT INTO analyses VALUES(?,?)',(photo_id,encode(row)))
   m=by[row['path']];c.execute('INSERT INTO manual VALUES(?,?,?,?,?,?)',(photo_id,m['status'],encode([s['scientific_name'] for s in m['species']]),m['source_sha256'],m['updated_at'],1))
  for key,value in [('legacy_batch',doc['batch_id']),('legacy_paths',encode([p['path'] for p in doc['photos']])),('taxonomy',encode(payload.get('taxonomy',{}))),('manual_archive',str(archive)),('score_labels',encode(payload['labels']))]:c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,value))
  db.bump(c)
 return {'photos':len(prepared),'counts':dict(collections.Counter(p['status'] for p in doc['photos'])),'archive':str(archive),'sha256':digest(archive)}

def evaluate(page,review,output):
 payload=read_page(page);doc=read_json(review);manual=validate_legacy(payload,doc);details=[];counts=collections.Counter();metrics={k:{'denominator':0,'top1':0,'top3':0,'top5':0} for k in ('visual','context')};folders={};species=collections.defaultdict(lambda:collections.Counter());group_sets=set()
 for row in payload['rows']:
  record=manual[row['path']];counts[record['status']]+=1;v=row['views'][0];truth=[s['scientific_name'] for s in record['species']];single=record['status']=='confirmed' and len(truth)==1
  entry={'path':row['path'],'manual':record,'detection':row.get('detection',{}).get('status'),'candidates':{key:[c['label'].get('scientific_name') for c in v[field]] for key,field in [('visual','candidates'),('context','context_candidates')]}}
  if single:
   folder=row['source_root'];f=folders.setdefault(folder,{'denominator':0,'top1':0,'top3':0,'top5':0});f['denominator']+=1
   species[truth[0]]['photos']+=1
   for key in metrics:
    m=metrics[key];m['denominator']+=1
    for k in (1,3,5):
     hit=int(truth[0] in entry['candidates'][key][:k]);m['top'+str(k)]+=hit
     if key=='context':f['top'+str(k)]+=hit;species[truth[0]]['top'+str(k)]+=hit
   group_sets.add((folder,truth[0]))
  details.append(entry)
 result={'manual_file':str(review),'manual_sha256':digest(review),'generated_at':now(),'counts':dict(counts),'single_species_photos':metrics['visual']['denominator'],'unique_confirmed_species':len(species),'metrics':metrics,'by_folder':folders,'by_species':dict(species),'rows':details,'limitations':'用户看过候选后确认；存在同批连续照片，不是独立、跨地区的总体准确率。多物种、不确定、未复核、无鸟不纳入单物种命中分母。未重新识别或读取原照片。'}
 Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return {k:v for k,v in result.items() if k not in ('rows','by_species')}


def initialize_catalog(db,cfg):
 """Initialize an empty catalogue; never reinterpret saved score columns."""
 labels=read_json(cfg['labels_path'])['labels']
 signature=lambda rows:[(r.get('kind'),r.get('scientific_name'),r.get('prompt')) for r in rows]
 previous=db.meta('score_labels')
 if previous:
  if signature(json.loads(previous))!=signature(labels):raise ValueError('模型标签顺序或提示已改变，需要显式迁移；拒绝混用已有分数')
  with db.transaction() as c:c.execute('INSERT OR IGNORE INTO meta VALUES(?,?)',('pipeline:'+cfg['pipeline_version'],encode({'model':read_json(Path(cfg['model_dir'])/'model.json'),'detector':read_json(cfg['detector_config']),'labels_sha256':digest(cfg['labels_path'])})))
  return
 if db.query('SELECT count(*) n FROM photos')[0]['n']:raise ValueError('已有照片缺少标签顺序记录，请恢复完整备份')
 taxonomy={}
 if cfg.get('taxonomy_snapshot'):
  from taxon_catalog import annotate
  taxonomy=annotate(labels,read_json(cfg['taxonomy_snapshot']))
 with db.transaction() as c:
  for label in labels:
   if label['kind']!='bird':continue
   name=label.get('birdreport',{}).get('zh_name') or label.get('zh_name') or label['scientific_name']
   if '?' in name or '\ufffd' in name:name=label['scientific_name']
   c.execute('INSERT INTO labels VALUES(?,?,?,?,?)',(label['scientific_name'],name,label.get('zh_name'),encode(label.get('aliases',[])),encode(label)))
  c.execute('INSERT INTO meta VALUES(?,?)',('score_labels',encode(labels)))
  c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('taxonomy',encode(taxonomy)))
  c.execute('INSERT INTO meta VALUES(?,?)',('pipeline:'+cfg['pipeline_version'],encode({'model':read_json(Path(cfg['model_dir'])/'model.json'),'detector':read_json(cfg['detector_config']),'labels_sha256':digest(cfg['labels_path'])})))
