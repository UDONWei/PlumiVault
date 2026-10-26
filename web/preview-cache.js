'use strict';
// Compressed screen previews live only in this page's memory. No disk cache or prefetch.
(() => {
 const entries=new Map(),pending=new Map(),MAX=12*1024*1024,TTL=5*60*1000;
 let bytes=0,timer=null,generation=0;
 function drop(key){const item=entries.get(key);if(item){bytes-=item.blob.size;entries.delete(key);}}
 function expire(){const now=Date.now();for(const [key,item] of entries)if(now-item.used>=TTL)drop(key);schedule();}
 function schedule(){clearTimeout(timer);timer=null;if(entries.size)timer=setTimeout(expire,Math.max(1,Math.min(...[...entries.values()].map(x=>x.used+TTL))-Date.now()));}
 function clear(){generation++;entries.clear();bytes=0;clearTimeout(timer);timer=null;}
 async function load(photo,options,resolution='screen',fresh=false,version=null){
  // Revalidate file existence, authorization and stat before every reuse; never hash a RAW just to hit cache.
  version=version||await options.api('/api/preview-version?id='+photo.id);
  if(version.sha256!==photo.sha256)throw Error('照片版本已改变，请刷新图库后重新打开');
  const key=JSON.stringify([photo.id,photo.sha256,version.key,resolution]);
  expire();
  if(fresh)drop(key);
  const hit=!fresh&&entries.get(key);
  if(hit){hit.used=Date.now();entries.delete(key);entries.set(key,hit);schedule();return {...hit,cached:true};}
  if(pending.has(key))return pending.get(key);
  const started=generation;
  const task=(async()=>{
   const abort=new AbortController(),deadline=setTimeout(()=>abort.abort(),180000);
   try{
    const response=await fetch('/api/original',{method:'POST',signal:abort.signal,headers:{'Content-Type':'application/json','X-Bird-Token':options.token()},body:JSON.stringify({photo_id:photo.id,source_sha:photo.sha256,resolution})});
    if(!response.ok)throw Error((await response.json()).error||'原图读取失败');
    const blob=await response.blob(),item={blob,width:response.headers.get('X-Source-Width'),height:response.headers.get('X-Source-Height'),used:Date.now()};
    if(started===generation&&resolution==='screen'&&blob.size<=MAX){
     // A replaced file must not leave old cached versions behind.
     for(const old of entries.keys())if(JSON.parse(old)[0]===photo.id)drop(old);
     while(entries.size&&(entries.size>=3||bytes+blob.size>MAX))drop(entries.keys().next().value);
     entries.set(key,item);bytes+=blob.size;schedule();
    }
    return {...item,cached:false};
   }catch(e){if(e.name==='AbortError')throw Error('预览加载超过 3 分钟，请检查连接后重试');throw e;}
   finally{clearTimeout(deadline);}
  })();
  pending.set(key,task);
  try{return await task;}finally{if(pending.get(key)===task)pending.delete(key);}
 }
 window.addEventListener('pagehide',clear);
 window.addEventListener('pageshow',expire);
 window.BirdPreview={load,clear};
})();
