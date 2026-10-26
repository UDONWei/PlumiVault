'use strict';
(() => {
 const targets=['task-progress','editor-task-progress'],listeners=new Set(),local=new Map();
 let options=null,jobs=[],pending=null,timer=null,expiry=null,lastActivity=Date.now(),recent=null,offline=false,sequence=0;
 const active=j=>['queued','discovering','running','paused'].includes(j.state)||(j.counts?.running||0)>0;
 const processing=j=>['queued','discovering','running'].includes(j.state)||(j.counts?.running||0)>0;
 const rank=j=>(j.counts?.running?0:({running:1,discovering:2,queued:3,paused:4}[j.state]??5));
 const awake=()=>!document.hidden&&Date.now()-lastActivity<120000;
 const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 function describe(job){
  const c=job.counts||{},total=Object.values(c).reduce((n,v)=>n+Number(v||0),0),done=(c.done||0)+(c.skipped||0)+(c.error||0);
  const names={queued:'等待开始',discovering:'正在检查所选目录',running:'正在识别',paused:'已暂停',completed:'处理完成',failed:'处理结束，有失败项',cancelled:'已取消'};
  const draining=c.running&&['paused','cancelled'].includes(job.state);
  const title=draining?(job.state==='paused'?'正在暂停':'正在取消')+'，等待当前照片结束':names[job.state]||job.state;
  const known=!!job.discovery_done&&total>0;
  let detail=known?`已结束 ${done} / ${total} 张 · 成功 ${c.done||0} · 跳过 ${c.skipped||0} · 失败 ${c.error||0}`:`已发现 ${job.found||0} 张，数量尚未确定`;
  if(job.state==='running')detail+=' · 单张包含模型准备、读取与识别，完成后更新计数';
  if(job.error)detail+=' · '+job.error;
  return {title,total:known?total:0,done,path:job.current_photo?.path||'',detail,bad:job.state==='failed',server:true};
 }
 function remember(item){
  recent=item;clearTimeout(expiry);expiry=setTimeout(()=>{recent=null;render();},12000);
 }
 function render(){
  const server=jobs.filter(active).sort((a,b)=>rank(a)-rank(b)),locals=[...local.values()];
  const item=locals.at(-1)||(server.length?describe(server[0]):recent);
  for(const id of targets){
   const host=document.getElementById(id);if(!host)continue;
   host.hidden=!item;host.replaceChildren();if(!item)continue;
   host.className='processing-progress'+(item.bad?' has-error':'');
   const title=node('strong',item.title),bar=node('progress');bar.setAttribute('aria-label',item.title);
   if(item.total>0){bar.max=item.total;bar.value=Math.min(item.total,Math.max(0,item.done));}
   const label=node('span',item.total>0?`${item.done} / ${item.total} 张`:'处理中');label.className='processing-count';
   const row=node('div');row.className='processing-heading';row.append(title,label);host.append(row,bar);
   if(item.path){const path=node('span',item.path);path.className='processing-file';path.title=item.path;host.append(path);}
   let detail=item.detail||'按实际完成张数更新，不估算单张内部百分比';
   const extra=locals.length+server.length-1;if(extra>0)detail+=` · 另有 ${extra} 个任务`;
   if(item.server&&offline&&server.length)detail+=' · 连接暂不可用，显示上次进度，尚未确认完成';
   else if(item.server&&!awake()&&server.length)detail+=' · 页面空闲，进度刷新已暂停；操作页面后更新';
   host.append(node('small',detail));
  }
 }
 function schedule(){
  clearTimeout(timer);timer=null;
  if(!options||!awake()){render();return;}
  timer=setTimeout(()=>{timer=null;if(awake())refresh().catch(()=>{});else render();},jobs.some(processing)?3000:10000);
 }
 function refresh(){
  if(pending)return pending;
  if(!options)return Promise.resolve({items:[]});
  clearTimeout(timer);timer=null;
  pending=(async()=>{
   try{
    const result=await options.api('/api/jobs');
    const before=new Set(jobs.filter(active).map(j=>j.id));jobs=result.items;offline=false;
    const ended=jobs.find(j=>before.has(j.id)&&!active(j));if(ended)remember(describe(ended));
    render();options.onJobs?.(result);
    for(const listener of listeners)Promise.resolve().then(()=>listener(result)).catch(e=>options.error?.(e));
    return result;
   }catch(e){offline=true;render();throw e;}
   finally{pending=null;schedule();}
  })();
  return pending;
 }
 function wake(){
  const idle=Date.now()-lastActivity>=120000;lastActivity=Date.now();
  if(!document.hidden&&(idle||timer===null))refresh().catch(()=>{});
 }
 function init(value){
  if(options)return;options=value;lastActivity=Date.now();
  for(const event of ['pointerdown','keydown','wheel'])document.addEventListener(event,wake,{passive:true});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(timer);timer=null;render();}else{lastActivity=Date.now();refresh().catch(()=>{});}});
 }
 function begin(title,total=1,path=''){
  const id=++sequence,item={title,total,done:0,path,detail:'按实际完成张数更新，不估算单张内部百分比'};
  local.set(id,item);render();
  return {update(value){if(local.has(id)){Object.assign(item,value);render();}},finish(error){
   if(!local.has(id))return;local.delete(id);
   remember({...item,title:error?title+'未完成':title+'完成',done:error?item.done:item.total,bad:!!error,detail:error?(error.message||String(error)):'已完成，结果已返回'});render();
  }};
 }
 window.BirdProgress={init,refresh,begin,watch(listener){listeners.add(listener);return()=>listeners.delete(listener);}};
})();
