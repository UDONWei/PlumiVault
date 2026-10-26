"""Reversible display state, independent of species, rating and original location."""
from .common import now
from .db import Conflict

def set_visibility(db,items,hidden):
 if type(hidden)!=bool or not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('请选择 1～100 张照片及有效隐藏状态')
 if any(not isinstance(i,dict) or type(i.get('id'))!=int or type(i.get('revision'))!=int for i in items) or len({i['id'] for i in items})!=len(items):raise ValueError('隐藏照片清单无效')
 records=[]
 with db.transaction() as c:
  for item in items:
   if not c.execute('SELECT 1 FROM photos WHERE id=?',(item['id'],)).fetchone():raise ValueError('照片不存在')
   old=c.execute('SELECT * FROM visibility WHERE photo_id=?',(item['id'],)).fetchone();revision=old['revision'] if old else 0
   if revision!=item['revision']:raise Conflict('隐藏状态已被另一页面修改，请刷新')
   record={'photo_id':item['id'],'hidden':hidden,'revision':revision+1,'updated_at':now()}
   c.execute('INSERT INTO visibility VALUES(?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET hidden=excluded.hidden,revision=excluded.revision,updated_at=excluded.updated_at',tuple(record.values()));records.append(record)
  db.bump(c)
 return {'records':records}
