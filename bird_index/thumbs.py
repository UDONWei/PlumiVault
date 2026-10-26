"""Validate bounded JPEG derivatives before writing into the independent data directory."""
import base64,hashlib,io,os,uuid
from PIL import Image

def save_jpeg(lib,encoded):
 if not isinstance(encoded,str) or len(encoded)>700000:raise ValueError('缩略图超出大小限制')
 try:raw=base64.b64decode(encoded,validate=True)
 except Exception as exc:raise ValueError('缩略图编码无效') from exc
 if len(raw)>512*1024:raise ValueError('缩略图过大')
 with Image.open(io.BytesIO(raw)) as image:
  if image.format!='JPEG' or not 1<=image.width<=512 or not 1<=image.height<=512:raise ValueError('仅接受长边不超过 512 的 JPEG 缩略图')
  image.verify()
 folder=lib.db.data/'thumbnails';name=hashlib.sha256(raw).hexdigest()+'.jpg';target=folder/name
 if target.exists():return name
 usage=sum(p.stat().st_size for p in folder.glob('*.jpg'))
 if usage+len(raw)>lib.cfg['thumbnail_budget_mb']*1024**2:raise ValueError('缩略图空间达到上限')
 temporary=folder/(uuid.uuid4().hex+'.tmp')
 try:
  with temporary.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  temporary.replace(target)
 finally:
  if temporary.exists():temporary.unlink()
 return name
