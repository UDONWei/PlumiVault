"""Produce a reviewable allowlist from one finished job. Does not enable or move."""
import argparse,json,sqlite3
from pathlib import Path
def prepare(path):
 with sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro',uri=True) as c:
  c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
  job=c.execute('SELECT * FROM jobs ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
  if not job or job['state']!='completed':raise ValueError('最近任务必须已完成')
  rows=c.execute("SELECT p.id,p.rel_path,p.root_id FROM job_items j JOIN photos p ON p.id=j.photo_id WHERE j.job_id=? AND j.state='done'",(job['id'],)).fetchall()
  if not 1<=len(rows)<=10 or len({r['root_id'] for r in rows})!=1:raise ValueError('仅支持同一入口的 1～10 张已完成样片')
  return {'enabled':False,'root_id':rows[0]['root_id'],'index_photo_root':'/photos','photo_root':'/library/未处理','quarantine_root':'/library/待删除','display_destination':'/volume1/照片/待删除','allowed_photo_ids':[r['id'] for r in rows],'max_batch':10,'review_files':[r['rel_path'] for r in rows],'job_id':job['id']}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--database',required=True);a=p.parse_args();print(json.dumps(prepare(a.database),ensure_ascii=False,indent=2))
