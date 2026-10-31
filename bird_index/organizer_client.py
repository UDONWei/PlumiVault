"""Only authenticated, internal organizer calls; no image data in requests."""
import json,os,urllib.request,urllib.error
from pathlib import Path
from .common import encode

def call(path,value):
 base=os.environ.get('BIRD_ORGANIZER_URL')
 allowed={'http://organizer:8766'}
 if os.environ.get('BIRD_COMPACT')=='1':allowed.add('http://127.0.0.1:8766')
 if base not in allowed:
  if path=='status':return {'enabled':False,'pending':[],'destination':'/volume1/照片/待删除'}
  raise ValueError('原片整理未启用；可先标记和筛选，启用独立整理服务后才能移动')
 token=Path(os.environ['BIRD_GATEWAY_TOKEN_FILE']).read_text().strip()
 request=urllib.request.Request(base+'/'+path,data=encode(value).encode(),headers={'Content-Type':'application/json','X-Bird-Organizer':token})
 try:
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=600) as response:return json.load(response)
 except urllib.error.HTTPError as exc:raise ValueError(json.load(exc).get('error','整理服务拒绝操作')) from exc
 except urllib.error.URLError as exc:raise ValueError('整理服务不可用；若执行中断，请查询待恢复操作，不要另建重复任务') from exc
