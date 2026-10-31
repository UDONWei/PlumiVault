'use strict';
// Client-only transforms: zooming never requests another image or decodes a RAW.
(() => {
 function create(view,image,label){
  let scale=1,x=0,y=0;const points=new Map();
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  function bounds(){
   const w=view.clientWidth,h=view.clientHeight,iw=image.naturalWidth||w,ih=image.naturalHeight||h;
   const fit=Math.min(w/Math.max(1,iw),h/Math.max(1,ih));
   return {x:Math.max(0,(iw*fit*scale-w)/2),y:Math.max(0,(ih*fit*scale-h)/2)};
  }
  function paint(){
   const b=bounds();x=clamp(x,-b.x,b.x);y=clamp(y,-b.y,b.y);
   image.style.transform=`translate(${x}px, ${y}px) scale(${scale})`;
   view.classList.toggle('zoomed',scale>1);label.textContent=scale===1?'适应':scale.toFixed(1)+'×';
   label.title='相对适应窗口的放大倍率；放大不增加图片真实细节';
  }
  function position(clientX,clientY){const r=view.getBoundingClientRect();return {x:clientX-r.left-r.width/2,y:clientY-r.top-r.height/2};}
  function zoom(next,px=0,py=0){
   if(!image.getAttribute('src'))return;
   const n=clamp(next,1,8),ratio=n/scale;x=px-(px-x)*ratio;y=py-(py-y)*ratio;scale=n;paint();
  }
  function clearPoints(){for(const id of points.keys())try{view.releasePointerCapture(id);}catch(_){}points.clear();}
  function reset(){clearPoints();scale=1;x=y=0;paint();}
  view.addEventListener('wheel',e=>{
   if(!image.getAttribute('src')||!e.deltaY)return;
   e.preventDefault();const p=position(e.clientX,e.clientY),delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?view.clientHeight:1);
   zoom(scale*Math.exp(-clamp(delta,-240,240)*.0025),p.x,p.y);
  },{passive:false});
  view.addEventListener('dblclick',e=>{e.preventDefault();if(scale>1)reset();else{const p=position(e.clientX,e.clientY);zoom(2,p.x,p.y);}});
  view.addEventListener('pointerdown',e=>{
   if(!image.getAttribute('src')||(e.pointerType==='mouse'&&e.button!==0)||points.size>=2)return;
   e.preventDefault();points.set(e.pointerId,{x:e.clientX,y:e.clientY});view.setPointerCapture(e.pointerId);
  });
  view.addEventListener('pointermove',e=>{
   if(!points.has(e.pointerId))return;e.preventDefault();
   const before=[...points.values()],old=points.get(e.pointerId),next={x:e.clientX,y:e.clientY};points.set(e.pointerId,next);
   if(points.size===1){x+=next.x-old.x;y+=next.y-old.y;paint();return;}
   const after=[...points.values()],distance=p=>Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y),mid=p=>({x:(p[0].x+p[1].x)/2,y:(p[0].y+p[1].y)/2});
   const d=distance(before),a=mid(before),b=mid(after),p=position(a.x,a.y);
   if(d>1)zoom(scale*distance(after)/d,p.x,p.y);
   x+=b.x-a.x;y+=b.y-a.y;paint();
  });
  const end=e=>{points.delete(e.pointerId);try{view.releasePointerCapture(e.pointerId);}catch(_){}};
  for(const event of ['pointerup','pointercancel','lostpointercapture'])view.addEventListener(event,end);
  image.addEventListener('load',paint);image.addEventListener('dragstart',e=>e.preventDefault());
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(paint).observe(view);
  paint();return {reset,step:factor=>zoom(scale*factor),state:()=>({scale,x,y,pointers:points.size})};
 }
 window.StudioZoom={create};
})();
