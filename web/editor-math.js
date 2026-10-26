'use strict';
(function(root){
 const keys=['brightness','contrast','highlights','shadows'];
 const defaults=()=>({version:1,brightness:0,contrast:0,highlights:0,shadows:0,box:null});
 function lut(r){return Uint8ClampedArray.from({length:256},(_,i)=>{let y=Math.min(1,i/255*2**((r.brightness||0)/50));y+=.25*((r.shadows||0)/100*(1-y)**3+(r.highlights||0)/100*y**3);y=(y-.5)*2**((r.contrast||0)/100)+.5;return Math.round(Math.max(0,Math.min(1,y))*255);});}
 function fit(w,h,cw,ch){const scale=Math.min(cw/w,ch/h)*.96;return {scale,x:(cw-w*scale)/2,y:(ch-h*scale)/2};}
 function point(x,y,v,w,h,clamp=true){const p=[(x-v.x)/(w*v.scale),(y-v.y)/(h*v.scale)];return clamp?p.map(n=>Math.max(0,Math.min(1,n))):p;}
 function box(a,b){return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];}
 function zoom(v,factor,x,y,min,max){const scale=Math.max(min,Math.min(max,v.scale*factor)),ratio=scale/v.scale;return {scale,x:x-(x-v.x)*ratio,y:y-(y-v.y)*ratio};}
 function hit(p,b,tolerance){if(!b)return null;for(const [handle,x,y] of [['nw',b[0],b[1]],['ne',b[2],b[1]],['sw',b[0],b[3]],['se',b[2],b[3]]])if(Math.abs(p[0]-x)<=tolerance[0]&&Math.abs(p[1]-y)<=tolerance[1])return handle;return p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3]?'move':null;}
 function adjustBox(b,handle,p,start){if(handle==='move'){const dx=Math.max(-b[0],Math.min(1-b[2],p[0]-start[0])),dy=Math.max(-b[1],Math.min(1-b[3],p[1]-start[1]));return [b[0]+dx,b[1]+dy,b[2]+dx,b[3]+dy];}const a=[...b];a[handle.includes('w')?0:2]=p[0];a[handle.includes('n')?1:3]=p[1];return box(a.slice(0,2),a.slice(2));}
 const api={keys,defaults,lut,fit,point,box,zoom,hit,adjustBox};root.EditorMath=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
