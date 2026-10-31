'use strict';
// Pure selection/navigation rules shared by pointer, keyboard and tests.
(() => {
 function choose(ids,selected,anchor,id,event={}){
  const additive=!!(event.ctrlKey||event.metaKey),next=new Set(additive?selected:[]),at=ids.indexOf(id),start=ids.indexOf(anchor);
  if(event.shiftKey&&start>=0&&at>=0){for(const value of ids.slice(Math.min(start,at),Math.max(start,at)+1))next.add(value);return {selected:next,anchor};}
  if(additive&&next.has(id))next.delete(id);else next.add(id);
  return {selected:next,anchor:id};
 }
 function visible(items,groups,expanded){
  const lookup=new Map();for(const group of groups)for(const id of group.ids)lookup.set(id,group);
  return items.filter(p=>{const group=lookup.get(p.id);return !group||group.ids.length<2||expanded.has(group.key)||p.id===group.ids[0];});
 }
 function wheel(e,element){
  if(e.ctrlKey||element.scrollWidth<=element.clientWidth||Math.abs(e.deltaX||0)>Math.abs(e.deltaY||0))return;
  const amount=(e.deltaY||0)*(e.deltaMode===1?18:e.deltaMode===2?element.clientWidth:1),max=element.scrollWidth-element.clientWidth;
  const next=Math.max(0,Math.min(max,element.scrollLeft+amount));
  if(next!==element.scrollLeft){e.preventDefault();element.scrollLeft=next;}
 }
 function best(items,group){
  const members=items.filter(p=>group.ids.includes(p.id)),valid=members.filter(p=>p.quality?.ai?.status==='reference'&&Number.isFinite(p.quality.score));
  // Compare the same available dimensions and model revision only. A partial
  // page/filter is deliberately labelled as such by the caller.
  if(valid.length<2)return [];
  const signature=p=>JSON.stringify([p.quality.model_key,(p.quality.score_components||[]).map(x=>x.name)]);
  if(valid.length!==members.length||new Set(valid.map(signature)).size!==1)return [];
  return valid.slice().sort((a,b)=>b.quality.score-a.quality.score||a.id-b.id).slice(0,Math.min(2,Math.max(1,Math.ceil(valid.length/4)))).map(p=>p.id);
 }
 window.StudioStrip={choose,visible,wheel,best};
})();
