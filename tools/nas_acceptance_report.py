"""Read-only report for both old NAS schema 2 and current schema. No photo access."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bird_index.selection import acceptance_report
class ReadOnly:
 def __init__(self,path):self.path=Path(path).resolve(strict=True)
 def query(self,sql,args=()):
  c=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
  try:c.execute('PRAGMA query_only=ON');return [dict(r) for r in c.execute(sql,args)]
  finally:c.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--database',default='/data/index.sqlite3');a=p.parse_args()
 print(json.dumps(acceptance_report(ReadOnly(a.database)),ensure_ascii=False,indent=2))
