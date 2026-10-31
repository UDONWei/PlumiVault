'use strict';
// Exercise real thumbnail click handlers with synthetic metadata; no image or network reads.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const nodes=new Map(),errors=[],calls=[],progress=[];let failScore=true,bursts=[],validationOptions;
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
class Element{
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attrs={};this.events={};this.className='';this.textContent='';this.value='';this.checked=false;this.hidden=false;this.offsetLeft=0;this.clientWidth=100;this.clientHeight=100;this.naturalWidth=400;this.naturalHeight=300;this.style={};this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};}
 set id(value){this._id=value;nodes.set(value,this);}get id(){return this._id;}
 append(...items){for(const item of items){item.parentNode=this;this.children.push(item);}}
 replaceChildren(...items){this.children=[];this.append(...items);}
 before(item){this.parentNode.append(item);}
 setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];if(k==='src')delete this.src;}
 getAttribute(k){return k==='src'?this.src||null:this.attrs[k]||null;}
 setPointerCapture(){}releasePointerCapture(){}
 getBoundingClientRect(){return {left:0,top:0,width:this.clientWidth,height:this.clientHeight};}
 addEventListener(name,fn){this.events[name]=fn;}
 querySelector(selector){return descendants(this).find(n=>selector.startsWith('.')?n.className.split(' ').includes(selector.slice(1)):false)||null;}
 scrollTo(value){this.scroll=value;}
 showModal(){this.open=true;}close(){this.open=false;}
}
const body=new Element('body');
for(const id of ['studio','quick','gallery','pagination','review-bar','list-summary','export-csv','folder']){const n=new Element();n.id=id;body.append(n);}
const photos=Array.from({length:10},(_,i)=>({id:i+1,relative_path:`synthetic/${i+1}.jpg`,date:'2026-01-01',context:{location:'合成测试'},thumbnail:`/synthetic/${i+1}.jpg`,sha256:String(i+1).repeat(64),manual:{status:'confirmed',species:['Bird alpha'],revision:1},candidates:[],selection:{flag:'none',rating:0,revision:0}}));
const context={window:{BirdProgress:{begin:(title,total)=>{const row={title,total,done:0};progress.push(row);return {update:value=>Object.assign(row,value),finish:error=>{row.error=error?.message||null;}};}},BirdSearch:{bind:()=>{}},BirdEditor:{isOpen:()=>false}},document:{body,getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),addEventListener:()=>{}},matchMedia:()=>({matches:false}),URL:{revokeObjectURL:()=>{}},URLSearchParams,Promise,console};
const timers=new Map();let timerId=0;
Object.assign(context,{AbortController,setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id)});
context.URL.createObjectURL=blob=>'blob:'+blob.tag;
const api=async(url,value)=>{calls.push({url,value});if(url==='/api/library-folders')return {items:[{root_id:'fixture',root_name:'测试',path:'synthetic',count:photos.length}]};if(url.startsWith('/api/library?')){const scope=new URLSearchParams(url.split('?')[1]).get('visibility')||'visible';const visible=photos.filter(p=>scope==='all'||!!p.visibility?.hidden===(scope==='hidden'));return {items:structuredClone(visible),total:visible.length,matched_photos:visible.length,bursts:bursts.map(g=>({...g,ids:g.ids.filter(id=>visible.some(p=>p.id===id))}))};}if(url==='/api/visibility')return {records:value.items.map(item=>{const p=photos.find(p=>p.id===item.id);p.visibility={photo_id:p.id,hidden:value.hidden,revision:item.revision+1};return p.visibility;})};if(url==='/api/selection')return {records:value.items.map(item=>{const p=photos.find(p=>p.id===item.id);p.selection={photo_id:p.id,flag:value.flag??p.selection.flag,rating:value.rating??p.selection.rating,revision:item.revision+1};return p.selection;})};if(url==='/api/curation-status')return {enabled:true,scope:'indexed_root',max_batch:100,pending:[]};
if(url.startsWith('/api/photos?ids='))return {items:structuredClone(photos.filter(p=>url.split('=')[1].split(',').map(Number).includes(p.id)))};
if(url==='/api/curation-plan')return {plan_id:'synthetic-plan',action:value.action,destination_display:'synthetic quarantine',items:value.ids.map(id=>({source:'synthetic/'+id+'.jpg',destination:'synthetic quarantine/'+id+'.jpg'}))};
if(url==='/api/curation-commit')return {results:photos.map(p=>({photo_id:p.id,ok:true})),needs_recovery:false};
if(url==='/api/quality'){if(failScore&&value.photo_id===2)throw Error('synthetic score failure');return {quality:{score:70,issues:[],exposure:70,limits:'synthetic only'}};}throw Error('Unexpected request '+url);};
context.window.BirdValidation={init:options=>validationOptions=options,side:()=>{},badge:()=>''};
vm.createContext(context);vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[2]),'studio-strip.js'),'utf8'),context);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
vm.runInContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[2]),'studio-zoom.js'),'utf8'),context);
(async()=>{
 const app=context.window.BirdStudio;app.init({api,name:id=>id,birds:()=>[],filters:()=>app.filters(),token:()=>'',message:()=>{},error:e=>errors.push(e.message),summary:async()=>{}});await app.refresh();
 assert.equal(nodes.get('s-image').parentNode.id,'s-viewport');
 await descendants(body).find(n=>n.textContent==='放大 ＋').onclick();assert(app.state.zoom.state().scale>1);
 assert.equal(nodes.get('s-side-shell').tagName,'SECTION','right pane is not collapsed');
 assert.equal(nodes.get('s-directory').children.length,2);
 nodes.get('s-directory').value=JSON.stringify({root:'fixture',subfolder:'synthetic'});
 assert.equal(app.filters().subfolder,'synthetic');assert.equal(app.filters().root,'fixture');
 assert(nodes.get('s-caption').textContent.includes('已确认：Bird alpha'));
 const strip=nodes.get('s-strip');strip.scrollLeft=275;const check=strip.children[0].children[0];check.checked=true;check.onchange();
 for(const index of [4,8,1,9]){
  await strip.children[index].children[1].onclick({ctrlKey:true});assert.deepEqual(errors,[],'thumbnail click must not report an error');assert.equal(app.state.at,index);assert.equal(strip.scrollLeft,275,'pointer must preserve film position');assert.equal(strip.children.length,10);assert.equal(strip.querySelector('.active').dataset.id,String(index+1));assert.equal(nodes.get('s-image').src,photos[index].thumbnail);assert.equal(nodes.get('s-progress').textContent,`${index+1} / 10`);assert(app.state.selected.has(1));
 }
 assert.equal(app.state.zoom.state().scale,1,'changing photo resets zoom');
 await strip.children[4].children[1].onclick({ctrlKey:true});
 await descendants(nodes.get('s-side')).find(n=>n.textContent==='保留 P').onclick();
 await descendants(nodes.get('s-side')).find(n=>n.textContent==='4★').onclick();
 assert.deepEqual(errors,[]);assert.equal(photos[4].selection.flag,'keep');assert.equal(photos[4].selection.rating,4);assert.equal(app.state.at,4);assert.equal(strip.children.length,10);assert.equal(strip.querySelector('.active').dataset.id,'5');assert(app.state.selected.has(1));
 assert(calls.every(c=>c.url.startsWith('/api/library?')||c.url==='/api/library-folders'||c.url==='/api/selection'));
 app.state.selected=new Set([1]);
 const second=strip.children[1].children[0];second.checked=true;second.onchange();
 const score=descendants(body).find(n=>n.textContent==='仅评分勾选图');await score.onclick();
 assert.equal(progress.at(-1).done,1);assert.equal(progress.at(-1).total,2);assert.equal(progress.at(-1).error,'synthetic score failure');assert.equal(app.state.busy,false);assert.equal(errors.at(-1),'synthetic score failure');
 failScore=false;await score.onclick();assert.equal(progress.at(-1).done,2);assert.equal(progress.at(-1).error,null);assert.equal(strip.children.length,10);assert.equal(app.state.at,4);
 assert(calls.every(c=>c.url.startsWith('/api/library?')||['/api/selection','/api/quality','/api/library-folders'].includes(c.url)));
 for(let id=11;id<=13;id++)photos.push({...structuredClone(photos[0]),id,relative_path:`synthetic/${id}.jpg`,thumbnail:`/synthetic/${id}.jpg`});
 await app.refresh();const all=nodes.get('s-select-page');all.checked=true;all.onchange();await score.onclick();
 assert.equal(progress.at(-1).total,13);assert.equal(progress.at(-1).done,13);assert.equal(progress.at(-1).error,null);assert.equal(strip.children.length,13);
 const moveButton=descendants(body).find(n=>n.textContent==='批量移至待删除');await moveButton.onclick();
 const dialog=nodes.get('s-dialog');assert(dialog.open);assert.equal(calls.filter(c=>c.url==='/api/curation-plan').at(-1).value.ids.length,13);
 assert.equal(calls.filter(c=>c.url==='/api/curation-commit').length,0,'preview must not move files');
 await descendants(dialog).find(n=>n.textContent==='取消').onclick();assert.equal(dialog.open,false);assert.equal(calls.filter(c=>c.url==='/api/curation-commit').length,0);
 await moveButton.onclick();await descendants(dialog).find(n=>n.textContent==='确认移动这 13 张').onclick();assert.equal(calls.filter(c=>c.url==='/api/curation-commit').length,1);
 await descendants(dialog).find(n=>n.textContent==='关闭').onclick();
 all.checked=true;all.onchange();await descendants(body).find(n=>n.textContent==='恢复勾选原片').onclick();
 assert(descendants(dialog).some(n=>n.textContent==='synthetic quarantine/1.jpg → synthetic/1.jpg'),'restore preview must show return direction');
 assert(descendants(dialog).some(n=>n.textContent.includes('恢复到原始路径')));
 assert.equal(calls.filter(c=>c.url==='/api/curation-commit').length,1);
 await descendants(dialog).find(n=>n.textContent==='取消').onclick();

 // Exercise real grouped DOM and selection handlers, including a collapsed member exclusion.
 bursts=[{key:1,ids:[1,2,3],count:3,matched_count:3}];app.state.at=0;await app.refresh();
 assert.equal(strip.children.length,11);assert.equal(strip.children[0].dataset.id,'1');
 await strip.children[0].children[1].onclick();
 await strip.children[2].children[1].onclick({shiftKey:true});
 assert.deepEqual([...app.state.selected],[1,4,5]);assert.equal(strip.scrollLeft,275);
 await descendants(strip.children[0]).find(n=>n.textContent.startsWith('展开组')).onclick();
 assert.equal(strip.children.length,13);
 await strip.children[0].children[1].onclick();await strip.children[2].children[1].onclick({shiftKey:true});
 assert.deepEqual([...app.state.selected],[1,2,3]);
 await descendants(strip.children[2]).find(n=>n.textContent.startsWith('收拢组')).onclick();
 assert.equal(strip.children.length,11);assert.deepEqual([...app.state.selected],[1]);assert.equal(app.state.at,0);
 const checkRange=strip.children[2].children[0];let cancelled=false;
 checkRange.onclick({shiftKey:true,preventDefault:()=>cancelled=true});checkRange.onchange();
 assert(cancelled);assert.equal(app.state.anchor,1);assert.deepEqual([...app.state.selected],[1,4,5]);
 nodes.get('s-batch-rating').value='3';await descendants(body).find(n=>n.textContent==='应用星级').onclick();
 assert.deepEqual(calls.filter(c=>c.url==='/api/selection').at(-1).value.items.map(p=>p.id),[1,4,5]);
 assert.equal(photos[1].selection.rating,0,'collapsed member must not be batch marked');

 await descendants(body).find(n=>n.textContent==='隐藏勾选图').onclick();
 assert.equal(app.state.total,10);assert.deepEqual(photos.filter(p=>p.visibility?.hidden).map(p=>p.id),[1,4,5]);
 nodes.get('s-visibility').value='hidden';await app.refresh();assert.equal(app.state.total,3);
 const hiddenAll=nodes.get('s-select-page');hiddenAll.checked=true;hiddenAll.onchange();
 await descendants(body).find(n=>n.textContent==='恢复显示勾选图').onclick();assert.equal(app.state.total,0);
 nodes.get('s-visibility').value='visible';await app.refresh();assert.equal(app.state.total,13);assert.equal(photos[0].selection.rating,3);
 // Explicit group selection expands only current-page members, never all 103.
 bursts[0].count=103;bursts[0].matched_count=103;await app.refresh();
 await descendants(strip.children[0]).find(n=>n.textContent==='勾选本页组 · 3 张').onclick();
 assert.deepEqual([...app.state.selected],[1,2,3]);assert.equal(strip.children.length,13);
 await validationOptions.view({name:'合成验证组',samples:[{id:1},{id:3}]});
 assert.equal(app.state.total,2);assert.deepEqual(Array.from(app.state.items,p=>p.id),[1,3]);assert.equal(strip.children.length,2);
 assert.equal(app.state.selected.size,0);assert(nodes.get('s-filter-status').textContent.includes('合成验证组'));
 await app.refresh();assert.equal(app.state.total,13,'applying filters returns to ordinary library');
 assert.deepEqual(errors,['synthetic score failure']);
 // A late HD response must never replace a newer photo, and raw/auto use the same photo.
 let resolveLate,displayCalls=[],generated=[];
 context.window.BirdDisplayPreview={load:async(p,options,mode,signal)=>{displayCalls.push({id:p.id,mode,signal});return new Promise(resolve=>resolveLate=resolve);},generate:async p=>generated.push(p.id)};
 const toggle=nodes.get('s-display-mode'),late=toggle.onclick();await Promise.resolve();await Promise.resolve();
 const pending=displayCalls.at(-1);assert.equal(pending.mode,'raw');
 await strip.children[1].children[1].onclick();const newer=nodes.get('s-image').src;assert(pending.signal.aborted);
 resolveLate({blob:{tag:'stale'}});await late;assert.equal(nodes.get('s-image').src,newer);
 context.window.BirdDisplayPreview.load=async(p,options,mode)=>{displayCalls.push({id:p.id,mode});return {blob:{tag:mode+'-'+p.id}};};
 app.state.zoom.step(2);
 await toggle.onclick();assert.equal(nodes.get('s-image').src,'blob:auto-'+app.state.items[app.state.at].id);
 await toggle.onclick();assert.equal(nodes.get('s-image').src,'blob:raw-'+app.state.items[app.state.at].id);
 assert(nodes.get('s-display-label').textContent.includes('同裁切、未调整'));
 assert.equal(app.state.zoom.state().scale,2,'comparison preserves zoom');
 app.state.selected=new Set([1,3]);await descendants(body).find(n=>n.textContent==='补生成勾选图高清预览').onclick();
 assert.deepEqual(generated,[1,3]);assert.equal(app.state.busy,false);assert.equal(progress.at(-1).done,2);
 context.window.BirdDisplayPreview.load=async()=>null;await toggle.onclick();assert.equal(nodes.get('s-display-generate').hidden,false);
 assert(nodes.get('s-display-label').textContent.includes('旧缩略图'));assert.deepEqual(errors,['synthetic score failure']);
 console.log('PASS: thumbnail navigation, culling marks/scores, 13-photo organizer preview/cancel/explicit confirmation; synthetic metadata only.');
})().catch(e=>{console.error(e);process.exitCode=1;});
