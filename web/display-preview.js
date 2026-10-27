'use strict';
// Only the currently requested subject is fetched. Original RAW decoding is explicit.
(() => {
 const entries=new Map(),MAX=12*1024*1024,TTL=5*60*1000;let bytes=0,timer=null,generation=0;
 function drop(key){const old=entries.get(key);if(old){bytes-=old.blob.size;entries.delete(key);}}
 function expire(){for(const [key,item] of entries)if(Date.now()-item.used>=TTL)drop(key);schedule();}
 function schedule(){clearTimeout(timer);timer=null;if(entries.size)timer=setTimeout(expire,Math.max(1,Math.min(...[...entries.values()].map(x=>x.used+TTL))-Date.now()));}
 function clear(){generation++;entries.clear();bytes=0;clearTimeout(timer);timer=null;}
 const params=p=>({id:p.id,sha:p.sha256,revision:p.edit_revision||0});
 async function load(photo,options,mode,signal){
  if(!['raw','auto'].includes(mode))throw Error('预览模式无效');
  const started=generation,query=params(photo),metadata=await options.api('/api/display-preview?'+new URLSearchParams(query),undefined,signal);
  if(signal?.aborted)throw new DOMException('Aborted','AbortError');
  if(!metadata.ready)return null;
  expire();const key=metadata.key+':'+mode,hit=entries.get(key);
  if(hit){hit.used=Date.now();entries.delete(key);entries.set(key,hit);schedule();return hit;}
  const response=await fetch('/api/display-image?'+new URLSearchParams({...query,key:metadata.key,mode}),{signal});
  if(response.status===404)return null;
  if(!response.ok)throw Error((await response.json()).error||'高清预览读取失败');
  const blob=await response.blob();if(blob.size>1024*1024)throw Error('高清预览超出大小限制');
  const item={blob,used:Date.now()};
  if(started===generation&&!signal?.aborted){
   drop(key);while(entries.size&&(entries.size>=12||bytes+blob.size>MAX))drop(entries.keys().next().value);
   entries.set(key,item);bytes+=blob.size;schedule();
  }
  return item;
 }
 function generate(photo,options){return options.api('/api/display-preview',{photo_id:photo.id,source_sha:photo.sha256,revision:photo.edit_revision||0});}
 window.addEventListener('pagehide',clear);
 window.BirdDisplayPreview={load,generate,clear};
})();
