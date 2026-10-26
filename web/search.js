'use strict';
(function(root){
 function norm(s){return String(s||'').toLowerCase().replace(/ü/g,'v').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[\s·'’_-]/g,'');}
 function near(a,b){if(Math.abs(a.length-b.length)>1)return false;let i=0,j=0,errors=0;while(i<a.length&&j<b.length){if(a[i]===b[j]){i++;j++;continue;}if(++errors>1)return false;if(a.length>b.length)i++;else if(b.length>a.length)j++;else {if(a[i]===b[j+1]&&a[i+1]===b[j]){i+=2;j+=2;}else{i++;j++;}}}return errors+(i<a.length||j<b.length?1:0)<=1;}
 function score(text,q){const t=norm(text);if(t===q)return 0;if(t.startsWith(q))return 1;if(t.includes(q))return 2;let i=0;for(const c of t)if(c===q[i])i++;if(q.length>=2&&i===q.length)return 4;if(/^[a-z]{4,}$/.test(q)&&[q.length-1,q.length,q.length+1].some(n=>near(q,t.slice(0,n))))return 5;return 99;}
 function find(items,query,limit=12){const q=norm(query);if(!q)return [];return items.map(item=>({item,score:Math.min(...(item.search||[item.name]).filter(Boolean).map(t=>score(t,q)))})).filter(x=>x.score<99).sort((a,b)=>a.score-b.score||a.item.name.localeCompare(b.item.name,'zh-CN')).slice(0,limit).map(x=>x.item);}
 function bind(input,parent,items,onSelect,onInput){
  const list=document.createElement('div');list.className='autocomplete-results';list.setAttribute('role','listbox');list.hidden=true;parent.append(list);input.setAttribute('autocomplete','off');input.setAttribute('aria-autocomplete','list');let matches=[],index=-1;
  const choose=item=>{list.hidden=true;input.value=item.name;onSelect(item);};
  function update(changed=false){if(changed)onInput?.();matches=find(items(),input.value);index=-1;list.replaceChildren();for(const item of matches){const b=document.createElement('button');b.type='button';b.textContent=item.name+(item.id&&!item.id.startsWith('region:')&&!/^\d/.test(item.id)&&item.id!==item.name?' · '+item.id:'');b.setAttribute('role','option');b.addEventListener('click',()=>choose(item));list.append(b);}list.hidden=!matches.length;}
  input.addEventListener('input',()=>update(true));input.addEventListener('focus',()=>update(false));input.addEventListener('keydown',e=>{if(e.key==='Escape'){list.hidden=true;return;}if(!matches.length||list.hidden)return;if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();index=(index+(e.key==='ArrowDown'?1:-1)+matches.length)%matches.length;[...list.children].forEach((b,i)=>b.className=i===index?'active':'');}if(e.key==='Enter'){e.preventDefault();choose(matches[Math.max(0,index)]);}});
  input.addEventListener('blur',()=>setTimeout(()=>{list.hidden=true;},180));return {list,update};
 }
 const api={norm,near,find,bind};root.BirdSearch=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
