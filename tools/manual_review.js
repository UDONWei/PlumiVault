'use strict';
(function(root){
const SCHEMA='bird-manual-review-v2',statuses=['unreviewed','confirmed','none_match','uncertain','no_bird'];
function createStore(data,storage){
 const key='bird-index-nas:manual:'+data.review_batch_id,clone=x=>JSON.parse(JSON.stringify(x));
 const birds=new Map(data.labels.filter(l=>l.kind==='bird').map(l=>[l.scientific_name,l]));
 let records=data.rows.map(r=>({path:r.path,source_sha256:r.before.sha256,status:'unreviewed',species:[],updated_at:null}));
 let persisted=false,restored=false,notice='尚未选择鸟种。',lastBatch=null,history=[],invalidSaved=false;
 function validate(doc){
  if(!doc||!['bird-manual-review-v1',SCHEMA].includes(doc.schema)||doc.batch_id!==data.review_batch_id||!Array.isArray(doc.photos)||doc.photos.length!==records.length)throw Error('复核文件与当前照片批次不匹配');
  const paths=new Map();for(const item of doc.photos){if(!item||paths.has(item.path))throw Error('复核文件照片重复或无效');paths.set(item.path,item);}
  return data.rows.map(row=>{
   const item=paths.get(row.path);if(!item||item.source_sha256!==row.before.sha256||!statuses.includes(item.status)||!Array.isArray(item.species)||item.species.length>birds.size)throw Error('照片指纹、状态或物种列表无效');
   const seen=new Set(),species=item.species.map(s=>{if(!s||!birds.has(s.scientific_name)||seen.has(s.scientific_name))throw Error('未知、重复或非鸟类标签');seen.add(s.scientific_name);return speciesRecord(birds.get(s.scientific_name));});
   if((item.status==='confirmed')!==(species.length>0))throw Error('状态与物种列表不一致');
   if(item.updated_at!==null&&(typeof item.updated_at!=='string'||!/^\d{4}-\d{2}-\d{2}T.*Z$/.test(item.updated_at)||!Number.isFinite(Date.parse(item.updated_at))))throw Error('复核时间无效');
   return {path:row.path,source_sha256:row.before.sha256,status:item.status,species,updated_at:item.updated_at};
  });
 }
 function speciesRecord(l){return {scientific_name:l.scientific_name,zh_name:l.zh_name||null,english_name:l.english_name||null};}
 function document(){
  const doc={schema:SCHEMA,batch_id:data.review_batch_id,photos:clone(records)};
  if(data.taxonomy){doc.taxonomy=clone(data.taxonomy);for(const photo of doc.photos)for(const species of photo.species){const target=birds.get(species.scientific_name)?.birdreport;if(target)species.birdreport=clone(target);}}
  return doc;
 }
 function save(){
  try{if(!storage||invalidSaved)throw Error();storage.setItem(key,JSON.stringify(document()));persisted=true;notice='已保存到本浏览器；建议导出复核结果备份。';}
  catch(_){persisted=false;notice=invalidSaved?'检测到无法读取的旧暂存，已保留原文；当前操作请导出备份。':'浏览器暂存不可用：请在刷新或关闭页面前导出复核结果。';}
 }
 try{
  if(!storage)throw Error();const saved=storage.getItem(key);
  if(saved){try{records=validate(JSON.parse(saved));}catch(err){invalidSaved=true;throw err;}
   // 保留升级前的文字记录；沿用批次和路径，不重置用户在浏览器完成的确认。
   const backup=key+':before-quick-review-v2';try{if(!storage.getItem(backup))storage.setItem(backup,saved);}catch(_){}
   persisted=true;restored=true;notice='已恢复本浏览器保存的人工复核。';
  }
 }catch(_){notice=invalidSaved?'旧暂存无法读取，原文已保留；请导出或导入核对。':'浏览器暂存不可用或旧记录无效；可导入复核 JSON。';}
 if(!restored&&data.initial_manual_review){try{records=validate(data.initial_manual_review);if(!invalidSaved)save();}catch(_){notice='附带复核记录不匹配，未载入。';}}
 function checkIndices(indices){if(!Array.isArray(indices)||!indices.length||new Set(indices).size!==indices.length||indices.some(i=>!Number.isInteger(i)||!records[i]))throw Error('照片列表无效');}
 function commit(indices,change,kind){
  checkIndices(indices);const before=indices.map(i=>clone(records[i])),stamp=new Date().toISOString();
  const next=indices.map(i=>({...change(clone(records[i])),updated_at:stamp}));
  indices.forEach((i,n)=>records[i]=next[n]);
  const item={indices:[...indices],before,after:indices.map(i=>clone(records[i])),kind};history.push(item);if(history.length>50)history.shift();if(kind==='batch')lastBatch=item;save();return indices.length;
 }
 function toggle(index,id){const l=birds.get(id);if(!l)throw Error('无效鸟种');return commit([index],r=>{const found=r.species.findIndex(s=>s.scientific_name===id);if(found>=0)r.species.splice(found,1);else r.species.push(speciesRecord(l));r.status=r.species.length?'confirmed':'unreviewed';return r;},'single');}
 function confirmOne(index,id){const l=birds.get(id);if(!l)throw Error('无效鸟种');return commit([index],r=>({...r,status:'confirmed',species:[speciesRecord(l)]}),'single');}
 function setStatus(index,status){if(!['unreviewed','none_match','uncertain','no_bird'].includes(status))throw Error('无效状态');return commit([index],r=>({...r,status,species:[]}),'single');}
 function importDocument(doc){const checked=validate(doc);records=checked;lastBatch=null;history=[];save();}
 function confirmMany(indices,id){
  const label=birds.get(id);if(!label)throw Error('整组确认鸟种无效');checkIndices(indices);
  const eligible=indices.filter(i=>records[i].status==='unreviewed');if(!eligible.length)throw Error('本组没有可整组确认的未复核照片');
  return commit(eligible,r=>({...r,status:'confirmed',species:[speciesRecord(label)]}),'batch');
 }
 function unchanged(item){return !!item&&item.indices.every((i,n)=>JSON.stringify(records[i])===JSON.stringify(item.after[n]));}
 function restore(item){if(!item||!unchanged(item))throw Error('相关照片已再次修改，不能覆盖新判断');item.indices.forEach((i,n)=>records[i]=clone(item.before[n]));history=history.filter(h=>h!==item);if(lastBatch===item)lastBatch=null;save();return {count:item.indices.length,indices:[...item.indices],kind:item.kind};}
 function undoInfo(){return {count:lastBatch?.indices.length||0,canUndo:unchanged(lastBatch)};}
 function undoLastBatch(){if(!lastBatch)throw Error('没有可撤销的整组确认');return restore(lastBatch).count;}
 function undoLast(){return restore(history.at(-1));}
 function historyInfo(){const item=history.at(-1);return {count:item?.indices.length||0,canUndo:unchanged(item),kind:item?.kind||null};}
 return {key,document,validate,toggle,confirmOne,setStatus,importDocument,confirmMany,undoLastBatch,undoInfo,undoLast,historyInfo,get:i=>clone(records[i]),info:()=>({notice,persisted}),counts:()=>Object.fromEntries(statuses.map(s=>[s,records.filter(r=>r.status===s).length]))};
}
const api={SCHEMA,createStore};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.BirdManualReview=api;
})(globalThis);
