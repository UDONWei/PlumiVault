'use strict';
(() => {
 const $=id=>document.getElementById(id),M=window.EditorMath;
 let active=null,dialog=null,canvas=null,ctx=null,frame=0,opening=0;
 function text(value,bad=false){$('editor-message').textContent=value;$('editor-message').className=bad?'warning':'';}
 function element(tag,value){const e=document.createElement(tag);if(value!==undefined)e.textContent=value;return e;}
 function dirty(){active.dirty=true;$('editor-save-state').textContent='参数尚未保存';}
 function draw(){
  frame=0;if(!active?.image)return;const s=active,img=s.image,v=s.view;
  ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#15231d';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,v.x,v.y,img.width*v.scale,img.height*v.scale);
  if(!$('editor-original').checked){const pixels=ctx.getImageData(0,0,canvas.width,canvas.height),table=M.lut(s.recipe),a=pixels.data;for(let i=0;i<a.length;i+=4){a[i]=table[a[i]];a[i+1]=table[a[i+1]];a[i+2]=table[a[i+2]];}ctx.putImageData(pixels,0,0);}
  const b=s.drag?.preview||(s.drag?.mode==='box'?M.box(s.drag.start,s.drag.end):(s.recipe.box||s.autoBox));
  if(b){const x=v.x+b[0]*img.width*v.scale,y=v.y+b[1]*img.height*v.scale,w=(b[2]-b[0])*img.width*v.scale,h=(b[3]-b[1])*img.height*v.scale;ctx.strokeStyle='#a8f0bc';ctx.lineWidth=3;ctx.strokeRect(x,y,w,h);ctx.fillStyle='rgba(168,240,188,.12)';ctx.fillRect(x,y,w,h);for(const [cx,cy] of [[x,y],[x+w,y],[x,y+h],[x+w,y+h]]){ctx.fillStyle='#a8f0bc';ctx.fillRect(cx-5,cy-5,10,10);}}
  $('editor-zoom-value').textContent=Math.round(v.scale*100)+'%';$('editor-box-value').textContent=s.recipe.box?'手动选框':s.autoBox?'自动主体选框，可拖动四角或框内':'自动寻找主体';
 }
 function repaint(){if(!frame)frame=requestAnimationFrame(draw);}
 function resize(){if(!active)return;const rect=canvas.getBoundingClientRect();canvas.width=Math.max(200,Math.round(rect.width));canvas.height=Math.max(200,Math.round(rect.height));if(active.image)active.view=M.fit(active.image.width,active.image.height,canvas.width,canvas.height);repaint();}
 function coordinates(e){const r=canvas.getBoundingClientRect();return [(e.clientX-r.left)*canvas.width/r.width,(e.clientY-r.top)*canvas.height/r.height];}
 function zoom(factor,position){if(!active?.image)return;const p=position||[canvas.width/2,canvas.height/2],fit=M.fit(active.image.width,active.image.height,canvas.width,canvas.height);active.view=M.zoom(active.view,factor,...p,fit.scale/4,Math.max(8,fit.scale*24));repaint();}
 function controls(){for(const key of M.keys){$('edit-'+key).value=active.recipe[key];$('value-'+key).textContent=String(active.recipe[key]);}$('editor-original').checked=false;repaint();}
 function candidates(data){
  const target=$('editor-results');target.replaceChildren();
  const title=element('strong','当前候选（点选可确认鸟种）');target.append(title);
  for(const c of data.photo.candidates.filter(c=>c.label.kind==='bird')){const id=c.label.scientific_name,b=element('button',active.options.name(id));b.type='button';b.addEventListener('click',async()=>{const s=active;if(!s||s.busy)return;s.busy=true;try{const result=await s.options.api('/api/review',{items:[{id:data.photo.id,revision:s.data.photo.manual.revision}],status:'confirmed',species:[id]});s.data.photo.manual={...s.data.photo.manual,...result.records[0]};await s.options.onChanged(data.photo.id,result);if(active===s)text('已确认并保存：'+s.options.name(id));}catch(e){if(active===s)text(e.message,true);}finally{s.busy=false;}});target.append(b);}
  const history=element('details'),summary=element('summary','查看此前候选');history.append(summary);
  for(const item of data.history){const p=element('p',(item.job_id===null?'原始结果 · ':'')+item.created_at+'：'+item.candidates.filter(c=>c.label.kind==='bird').map(c=>active.options.name(c.label.scientific_name)).join('、'));history.append(p);}
  target.append(history);
 }
 async function loadOriginal(resolution='screen',fresh=false){
  const s=active;if(!s||s.busy)return;s.busy=true;text(resolution==='full'?'正在读取原始分辨率，仅在内存显示…':'正在按需读取原图…');$('editor-load').disabled=true;
  const progress=window.BirdProgress?.begin('加载原图预览',1,s.data.photo.path);let failure=null;
  try{
   const preview=await window.BirdPreview.load(s.data.photo,s.options,resolution,fresh,s.previewVersion);s.previewVersion=null;
   const blob=preview.blob;if(active!==s)return;
   const url=URL.createObjectURL(blob),img=new Image();try{img.src=url;await img.decode();}finally{URL.revokeObjectURL(url);}if(active!==s)return;
   if(s.image)s.image.src='';s.image=img;s.full=resolution==='full';s.view=M.fit(img.width,img.height,canvas.width,canvas.height);if(s.full)s.view={scale:1,x:(canvas.width-img.width)/2,y:(canvas.height-img.height)/2};
   $('editor-dimensions').textContent='原始画面 '+preview.width+' × '+preview.height+(s.full?' · 原始像素已载入':' · 当前为适屏预览');text((preview.cached?'已复用内存预览，无需重新解码或传图。':'已载入预览。')+'滚轮缩放；框选或移动画面。核对细节可点“原始像素”。');repaint();
  }catch(e){failure=e;if(active===s)text(e.message,true);}finally{progress?.finish(failure);if(active===s){s.busy=false;$('editor-load').disabled=false;}}
 }
 function thumbnail(s){const b=s.recipe.box||s.autoBox||[0,0,1,1],image=s.image,w=Math.max(1,(b[2]-b[0])*image.width),h=Math.max(1,(b[3]-b[1])*image.height),scale=Math.min(1,512/Math.max(w,h)),out=document.createElement('canvas');out.width=Math.max(1,Math.round(w*scale));out.height=Math.max(1,Math.round(h*scale));const c=out.getContext('2d');c.drawImage(image,b[0]*image.width,b[1]*image.height,w,h,0,0,out.width,out.height);const data=c.getImageData(0,0,out.width,out.height),table=M.lut(s.recipe);for(let i=0;i<data.data.length;i+=4){data.data[i]=table[data.data[i]];data.data[i+1]=table[data.data[i+1]];data.data[i+2]=table[data.data[i+2]];}c.putImageData(data,0,0);return out.toDataURL('image/jpeg',.85).split(',')[1];}
 async function save(run=false){
  const s=active;if(!s||s.busy)return;if(!s.image){text('请先成功打开原图后再保存框选或调整。',true);return;}s.busy=true;
  const snapshot=JSON.stringify(s.recipe),progress=window.BirdProgress?.begin('保存调整参数',1,s.data.photo.path);let failure=null;
  try{const result=await s.options.api('/api/adjustments',{photo_id:s.data.photo.id,source_sha:s.data.photo.sha256,revision:s.data.adjustment.revision,recipe:JSON.parse(snapshot),preview:thumbnail(s)});s.data.adjustment=result;s.dirty=JSON.stringify(s.recipe)!==snapshot;if(active===s){$('editor-save-state').textContent=s.dirty?'还有新改动尚未保存':'参数已保存';text('已保存参数，原文件不变。');}
   await s.options.onChanged(s.data.photo.id);
   if(run){const job=await s.options.api('/api/reprocess',{photo_id:s.data.photo.id,source_sha:s.data.photo.sha256,revision:result.revision});s.job=job.id;if(active===s){text('单张识别已排队，使用刚保存的参数；人工确认保持。');s.unwatch?.();s.unwatch=window.BirdProgress.watch(result=>poll(s,result));}window.BirdProgress.refresh().catch(e=>{if(active===s)text('任务已提交，进度暂不可用：'+e.message,true);});}
  }catch(e){failure=e;if(active===s)text(e.message,true);}finally{progress?.finish(failure);s.busy=false;}
 }
 async function poll(s,result){
  if(active!==s||!s.job)return;
  try{const job=result.items.find(j=>j.id===s.job);if(active!==s)return;if(job&&['completed','failed','cancelled'].includes(job.state)){s.job=null;s.unwatch?.();s.unwatch=null;if(job.state==='completed'){s.data=await s.options.api('/api/editor?id='+s.data.photo.id);await s.options.onChanged(s.data.photo.id);if(active===s){candidates(s.data);text('重新识别完成；可对照此前候选，人工确认保持。');}}else text('任务未成功完成，请在扫描任务查看错误或重试。',true);return;}}
  catch(e){if(active===s)text(e.message,true);}
 }
 function close(){if(!active)return;if(active.dirty&&!confirm('调整参数尚未保存，关闭后丢弃本次更改？'))return;active.unwatch?.();if(active.image)active.image.src='';active.image=null;active=null;dialog.close();canvas.width=1;canvas.height=1;}
 function init(){
  if(dialog)return;dialog=$('image-editor');canvas=$('editor-canvas');ctx=canvas.getContext('2d',{willReadFrequently:true});
  $('editor-close').addEventListener('click',close);dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  $('editor-fit').addEventListener('click',()=>{if(active?.image){active.view=M.fit(active.image.width,active.image.height,canvas.width,canvas.height);repaint();}});
  $('editor-full').addEventListener('click',()=>loadOriginal('full'));$('editor-load').addEventListener('click',()=>loadOriginal('screen',true));$('editor-plus').addEventListener('click',()=>zoom(1.3));$('editor-minus').addEventListener('click',()=>zoom(1/1.3));
  $('editor-pan').addEventListener('click',()=>{active.mode='pan';canvas.className='pan';text('拖动可移动画面。');});$('editor-select').addEventListener('click',()=>{active.mode='box';canvas.className='box';text('在对象周围拖出矩形；稍留边缘，识别只使用框内内容。');});
  $('editor-clear-box').addEventListener('click',()=>{active.recipe.box=null;active.autoBox=null;dirty();repaint();});$('editor-reset').addEventListener('click',()=>{active.recipe=M.defaults();active.autoBox=active.data.photo.detection?.selected_box||null;dirty();controls();});$('editor-original').addEventListener('change',repaint);
  for(const key of M.keys)$('edit-'+key).addEventListener('input',()=>{active.recipe[key]=Number($('edit-'+key).value);$('value-'+key).textContent=String(active.recipe[key]);dirty();repaint();});
  $('editor-save').addEventListener('click',()=>save(false));$('editor-recognize').addEventListener('click',()=>save(true));
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.0015),coordinates(e));},{passive:false});
  canvas.addEventListener('pointerdown',e=>{if(!active?.image||e.button!==0)return;const xy=coordinates(e),point=M.point(...xy,active.view,active.image.width,active.image.height,false);if(active.mode==='box'&&point.some(n=>n<0||n>1))return;canvas.setPointerCapture(e.pointerId);const b=active.recipe.box||active.autoBox,handle=active.mode==='box'?M.hit(point,b,[12/(active.image.width*active.view.scale),12/(active.image.height*active.view.scale)]):null;active.drag={mode:handle?'adjust':active.mode,handle,box:b?[...b]:null,start:point,end:point,xy,view:{...active.view}};});
  canvas.addEventListener('pointermove',e=>{if(!active?.drag)return;const xy=coordinates(e),d=active.drag;if(d.mode==='pan')active.view={...d.view,x:d.view.x+xy[0]-d.xy[0],y:d.view.y+xy[1]-d.xy[1]};else {d.end=M.point(...xy,active.view,active.image.width,active.image.height);if(d.mode==='adjust')d.preview=M.adjustBox(d.box,d.handle,d.end,d.start);}repaint();});
  canvas.addEventListener('pointerup',e=>{if(!active?.drag)return;const d=active.drag;if(d.mode==='box'||d.mode==='adjust'){const b=d.preview||M.box(d.start,d.end);if(Math.min(b[2]-b[0],b[3]-b[1])>=.0001&&(b[2]-b[0])*active.image.width>=2&&(b[3]-b[1])*active.image.height>=2){active.recipe.box=b;active.autoBox=null;dirty();}else text('框选太小，请重新框选。',true);}active.drag=null;canvas.releasePointerCapture(e.pointerId);repaint();});
  canvas.addEventListener('pointercancel',()=>{if(active)active.drag=null;repaint();});window.addEventListener('resize',resize);
 }
 async function open(id,options){
  init();if(active){close();if(active)return;}const request=++opening,data=await options.api('/api/editor?id='+id);if(request!==opening)return;active={options,data,previewVersion:data.preview_version,recipe:{...M.defaults(),...data.adjustment.recipe},autoBox:data.photo.detection?.selected_box||null,image:null,mode:'box',busy:false,dirty:false,view:{scale:1,x:0,y:0}};
  if(data.stale_adjustment){active.recipe=M.defaults();active.autoBox=null;text('源文件已变化，旧框选未应用，请重新框选。',true);}
  $('editor-title').textContent=data.photo.path;$('editor-source-path').textContent=data.source_path;$('editor-save-state').textContent=data.adjustment.revision?'已载入保存参数':'尚未保存调整';dialog.showModal();resize();controls();candidates(data);await loadOriginal();
 }
 window.BirdEditor={open,isOpen:()=>!!active};
})();
