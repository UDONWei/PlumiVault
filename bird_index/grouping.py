"""与旧页一致的保守分组；筛选在完整时间序列分组后执行。"""
from datetime import datetime
import math,re

def seconds(row):
 try:return datetime.strptime(row.get('exif',{}).get('EXIF DateTimeOriginal',''),'%Y:%m:%d %H:%M:%S').timestamp()
 except ValueError:return None

def identity(row,record):
 if record.get('stale'):return None
 if record['status']=='confirmed':return record['species'][0] if len(record['species'])==1 else None
 if record['status']!='unreviewed' or row.get('detection',{}).get('status') not in ('detected','manual'):return None
 view=(row.get('views') or [{}])[0];c=(view.get('context_candidates') or view.get('candidates') or [{}])[0]
 label=c.get('label',{});return label.get('scientific_name') if label.get('kind')=='bird' else None

def appearance(a,b,limit):
 if not a or not b or a.get('algorithm')!='dct63-dhash64-rgb-v1' or b.get('algorithm')!=a['algorithm']:return False
 try:
  if max(a['aspect']/b['aspect'],b['aspect']/a['aspect'])>1.08 or min(a['detail_score'],b['detail_score'])<.00005:return False
  if len(a['mean_rgb'])!=3 or len(b['mean_rgb'])!=3:return False
  if math.sqrt(sum((x-y)**2 for x,y in zip(a['mean_rgb'],b['mean_rgb'])))>limit:return False
  for field,maximum in [('phash',6),('dhash',10)]:
   if not re.fullmatch('[0-9a-f]{16}',a[field]) or not re.fullmatch('[0-9a-f]{16}',b[field]):return False
   if (int(a[field],16)^int(b[field],16)).bit_count()>maximum:return False
  return True
 except (KeyError,ZeroDivisionError,TypeError,ValueError):return False

def similar(a,b):
 ta,tb=seconds(a),seconds(b)
 if ta is None or tb is None or abs(ta-tb)>10 or a.get('directory')!=b.get('directory'):return False
 if a.get('before',{}).get('sha256') and a['before']['sha256']==b.get('before',{}).get('sha256'):return True
 if a.get('detection',{}).get('status') not in ('detected','manual') or b.get('detection',{}).get('status') not in ('detected','manual'):return False
 return appearance(a.get('similarity',{}).get('whole'),b.get('similarity',{}).get('whole'),.08) and appearance(a.get('similarity',{}).get('subject'),b.get('similarity',{}).get('subject'),.12)

def natural(text):return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)',text)]
def plan(items,prefs,with_similarity=True):
 gap=prefs.get('gap',30)
 if type(gap)!=int or not 1<=gap<=120:raise ValueError('连拍间隔须为 1～120 秒')
 ordered=sorted(items,key=lambda p:(p['row'].get('directory',''),seconds(p['row']) if seconds(p['row']) is not None else math.inf,natural(p['path'])))
 groups=[]
 for item in ordered:
  t=seconds(item['row']);bird=identity(item['row'],item['manual']);last=groups[-1] if groups else None;previous=last[-1] if last else None
  prevtime=seconds(previous['row']) if previous else None;firsttime=seconds(last[0]['row']) if last else None
  join=previous and bird and bird==identity(previous['row'],previous['manual']) and item['row'].get('directory')==previous['row'].get('directory') and t is not None and prevtime is not None and t-prevtime<=gap and t-firsttime<=300 and item['id'] not in prefs.get('breaks',[])
  if join:last.append(item)
  else:groups.append([item])
 results=[]
 for members in groups:
  ranked=sorted(members,key=lambda p:(-int(p['id'] in prefs.get('covers',[])),-p['row'].get('similarity',{}).get('subject',{}).get('detail_score',0),p['id']))
  representatives=[];folded=[]
  for item in ranked:
   match=next((p for p in representatives if similar(item['row'],p['row'])),None) if with_similarity and item['id'] not in prefs.get('keep',[])+prefs.get('covers',[]) else None
   if match:folded.append({'id':item['id'],'representative':match['id']})
   else:representatives.append(item)
  results.append({'key':members[0]['id'],'members':members,'cover':ranked[0]['id'],'folded':folded,'species':identity(members[0]['row'],members[0]['manual']),'confirmed':all(m['manual']['status']=='confirmed' and not m['manual']['stale'] for m in members)})
 return results
