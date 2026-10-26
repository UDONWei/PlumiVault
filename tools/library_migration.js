'use strict';
(function(root){
function seed(data,storage){
 const clone=x=>JSON.parse(JSON.stringify(x));
 const initial=clone(data.initial_manual_review);
 if(!initial)return;
 const byPath=new Map(initial.photos.map(p=>[p.path,p]));
 for(const batch of data.legacy_batches||[]){
  try{
   const text=storage?.getItem('bird-index-nas:manual:'+batch.batch_id);
   if(!text)continue;
   const doc=JSON.parse(text),legacy={labels:data.labels,review_batch_id:batch.batch_id,rows:batch.mapping.map(m=>({path:m.source_path,before:{sha256:m.source_sha256}}))};
   const checker=BirdManualReview.createStore(legacy,null);
   const checked=checker.validate(doc);
   const mapping=new Map(batch.mapping.map(m=>[m.source_path,m]));
   for(const record of checked){const m=mapping.get(record.path),target=byPath.get(m.target_path);if(!target||target.source_sha256!==record.source_sha256)throw Error('旧照片映射不符');}
   for(const record of checked){const m=mapping.get(record.path);byPath.set(m.target_path,{...clone(record),path:m.target_path});}
  }catch(_){data.migration_warning='部分旧浏览器复核记录无效，使用已导出的确认快照；旧暂存未删除。';}
 }
 initial.photos=data.rows.map(r=>byPath.get(r.path));data.initial_manual_review=initial;
}

function merge(data,doc,current){
 if(doc?.batch_id===data.review_batch_id)return doc;
 const batch=(data.legacy_batches||[]).find(b=>b.batch_id===doc?.batch_id);
 if(!batch)throw Error('不是当前批次或已知的历史复核记录');
 const legacy={labels:data.labels,review_batch_id:batch.batch_id,rows:batch.mapping.map(m=>({path:m.source_path,before:{sha256:m.source_sha256}}))};
 const checked=BirdManualReview.createStore(legacy,null).validate(doc);
 const result=JSON.parse(JSON.stringify(current)),byPath=new Map(result.photos.map((p,i)=>[p.path,i]));
 for(const record of checked){
  const mapping=batch.mapping.find(m=>m.source_path===record.path),index=byPath.get(mapping.target_path);
  if(index===undefined||result.photos[index].source_sha256!==record.source_sha256)throw Error('历史复核指纹或路径无效');
  result.photos[index]={...record,path:mapping.target_path};
 }
 return result;
}
root.BirdLibraryMigration={seed,merge};
})(globalThis);
