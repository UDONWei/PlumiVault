"""记录中心郑四名称对应；保留模型标识、候选数量与历史人工记录。"""
import collections,unicodedata


def annotate(labels,snapshot):
 index=collections.defaultdict(list)
 normalize=lambda text:' '.join(unicodedata.normalize('NFC',text).split())
 active=[row for row in snapshot['taxa'] if row.get('enable')==1]
 for row in active:index[normalize(row['latinname'])].append(row)
 counts=collections.Counter()
 for label in labels:
  if label.get('kind')!='bird':continue
  label.pop('birdreport',None)
  matches=index.get(normalize(label['scientific_name']),[])
  # 公开选择器包含旧名搜索别名；同一官方 ID、名称、学名只算一个目标。
  targets={(r['id'],r['name'],normalize(r['latinname'])) for r in matches}
  status='exact_scientific_name' if len(targets)==1 else 'ambiguous' if targets else 'unmatched'
  counts[status]+=1;label['birdreport_status']=status
  if len(targets)==1:
   row=matches[0];label['birdreport']={'version':'CH4','id':row['id'],'zh_name':row['name'],'scientific_name':row['latinname'],'mapping':status}
   aliases=[label.get('zh_name')]
   for match in matches:aliases.extend(match.get(k) for k in ('name','pinyin','szm'))
   label['aliases']=list(dict.fromkeys(x for x in aliases if x))
 return {'source':snapshot['source_page'],'title':snapshot['title'],'version':'CH4','retrieved_date':snapshot['retrieved_date'],'response_sha256':snapshot['response_sha256'],'catalog_rows':len(snapshot['taxa']),'catalog_taxon_ids':len({r['id'] for r in active}),'counts':dict(counts),'scope':'学名精确对应的名称兼容层；同官方 ID 的重复查询别名合并，分类拆分/合并未自动迁移。'}


def crosswalk(labels,snapshot):
 import copy
 labels=copy.deepcopy(labels);metadata=annotate(labels,snapshot)
 rows=[{'model_scientific_name':l['scientific_name'],'original_zh_name':l.get('zh_name'),'status':l['birdreport_status'],'target':l.get('birdreport'),'aliases':l.get('aliases',[])} for l in labels if l.get('kind')=='bird']
 summary={**metadata['counts'],'catalog_rows':metadata['catalog_rows'],'catalog_taxon_ids':metadata['catalog_taxon_ids'],'mapped_chinese_name_changes':sum(r['target'] is not None and r['original_zh_name']!=r['target']['zh_name'] for r in rows)}
 return {'source':{k:v for k,v in snapshot.items() if k!='taxa'},'summary':summary,'method':metadata['scope'],'rows':rows}


if __name__=='__main__':
 import argparse,json
 from pathlib import Path
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--snapshot',type=Path,required=True);parser.add_argument('--labels-report',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args()
 snapshot=json.loads(args.snapshot.read_text(encoding='utf-8'))
 labels=json.loads(args.labels_report.read_text(encoding='utf-8'))['score_labels']
 report=crosswalk(labels,snapshot)
 args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report['summary'],ensure_ascii=False))
