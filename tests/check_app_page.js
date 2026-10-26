'use strict';
// 临时合成数据 + 真实本机 API；模拟 DOM，不加载图片资源。
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const base=process.argv[2],root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'web/index.html'),'utf8');
class Element{
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.open=false;this.children=[];this.events={};this.attrs={};this.textContent='';this.parentNode=null;this.className='';}
 append(...nodes){for(const n of nodes){if(n.parentNode)n.parentNode.children=n.parentNode.children.filter(x=>x!==n);this.children.push(n);n.parentNode=this;if(this.tagName==='SELECT'&&this.children.length===1)this.value=n.value;}}
 replaceChildren(...nodes){this.children.forEach(n=>n.parentNode=null);this.children=[];this.append(...nodes);}
 setAttribute(key,value){this.attrs[key]=value;}
 addEventListener(key,fn){this.events[key]=fn;}
 click(){if(!this.disabled)return this.events.click?.({target:this});}
 scrollIntoView(){}
 focus(){}
 showModal(){this.open=true;}close(){this.open=false;}
}
const elements=new Map();for(const match of source.matchAll(/<([a-z0-9]+)\b([^>]*\bid="([^"]+)"[^>]*)>/gi)){const e=new Element(match[1]);e.checked=/\bchecked\b/.test(match[2]);e.disabled=/\bdisabled\b/.test(match[2]);e.hidden=/\bhidden\b/.test(match[2]);e.value=match[2].match(/\bvalue="([^"]*)"/)?.[1]||'';assert(!elements.has(match[3]));elements.set(match[3],e);}
const el=id=>{assert(elements.has(id),'Missing DOM: '+id);return elements.get(id);};
const initial=node=>{const option=new Element('option');option.value='';node.append(option);};initial(el('folder'));el('state').value='all';
for(const id of ['search','context-location','context-region','region']){const label=new Element('label');label.append(el(id));}
const events={},requests=[];
const sandbox={console,structuredClone,URLSearchParams,Promise,clearTimeout,setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms);timer.unref();return timer;},setInterval:()=>1,window:{},document:{getElementById:el,createElement:tag=>new Element(tag),addEventListener:(n,fn)=>{const previous=events[n];events[n]=e=>{previous?.(e);fn(e);};}},fetch:async(url,options)=>{requests.push(url);assert(url.startsWith('/api/'),'不加载任何图像或其他资源');return fetch(base+url,options);}};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync(path.join(root,'web/search.js'),'utf8'),sandbox);vm.runInContext(fs.readFileSync(path.join(root,'web/progress.js'),'utf8'),sandbox);vm.runInContext(fs.readFileSync(path.join(root,'web/app.js'),'utf8'),sandbox);
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
async function until(predicate){const end=Date.now()+6000;while(!predicate()){if(Date.now()>end)throw Error('UI operation timeout: '+el('notice').textContent);await new Promise(r=>setTimeout(r,15));}}
(async()=>{
 const app=sandbox.window.BirdIndexApp;await app.ready;
 if(process.argv[3]==='unlimited'){
  assert.equal(el('task-limit').value,'0');assert.equal(el('task-limit').max,'');assert.equal(el('task-limit').min,'0');
  const jobs=async()=> (await (await fetch(base+'/api/jobs')).json()).items;
  await el('start-job').click();assert(el('notice').textContent.includes('请先勾选'));assert.equal((await jobs()).length,0);
  app.state.selectedFolders.add('picked');el('task-limit').value='';await el('start-job').click();assert.equal((await jobs()).length,0);assert(el('notice').textContent.includes('非负整数'));
  el('task-limit').value='0';await el('start-job').click();assert.equal((await jobs()).length,0,'preview must not queue a job');assert(el('scan-dialog').open);
  await descendants(el('scan-dialog')).find(e=>e.id==='scan-confirm').click();
  const rows=await jobs();assert.equal(rows.length,1);assert.equal(rows[0].limit_count,0);assert.deepEqual(JSON.parse(rows[0].scopes),['picked']);assert.equal(rows[0].counts.pending,14);assert(el('notice').textContent.includes('已确认处理'));
  console.log('PASS: unlimited default, no implicit selection, invalid number rejected, selected-folder-only job submission; no images loaded');return;
 }
 if(process.argv[3]==='group'){
  assert.equal(app.state.total,1);const group=app.state.groups[0];assert.equal(group.unreviewed,3);assert.equal(app.state.photos.size,1);
  const apply=descendants(el('gallery')).find(e=>e.textContent.startsWith('确认本组未复核'));await apply.click();assert.equal(group.unreviewed,0);assert.equal(apply.disabled,true);await el('undo').click();assert.equal(group.unreviewed,3);assert.equal(apply.disabled,false);assert.equal(app.state.summary.counts.unreviewed,3);console.log('unloaded group confirm and undo passed; no image loading');return;
 }
 assert.equal(app.state.total,3);assert.equal(app.state.summary.photos,3);
 const roots=[...el('gallery').children],group=roots[0];group.open=true;group.events.toggle();await until(()=>descendants(group).some(e=>e.className==='candidates'));
 const card=descendants(group).find(e=>e.className==='photo'),parent=card.parentNode,choices=descendants(card).find(e=>e.className==='candidates');await choices.children[0].click();assert.equal(card.parentNode,parent);roots.forEach((n,i)=>assert.equal(el('gallery').children[i],n));assert.equal(app.state.summary.counts.confirmed,1);
 await el('undo').click();assert.equal(app.state.summary.counts.unreviewed,3);roots.forEach((n,i)=>assert.equal(el('gallery').children[i],n));
 await el('start-quick').click();assert.equal(app.state.quick.ids.length,3);assert.equal(el('quick').hidden,false);
 const q0=app.state.quick.ids[0];events.keydown({key:'1',target:{tagName:'INPUT'},preventDefault:()=>{}});assert.equal(app.state.photos.get(q0).manual.status,'unreviewed');
 events.keydown({key:'1',target:{tagName:'BODY'},preventDefault:()=>{}});await until(()=>!app.state.busy&&app.state.quick.at===1);assert.equal(app.state.photos.get(q0).manual.status,'confirmed');
 const q1=app.state.quick.ids[1];events.keydown({key:'0',target:{tagName:'BODY'},preventDefault:()=>{}});await until(()=>!app.state.busy&&app.state.quick.at===2);assert.equal(app.state.photos.get(q1).manual.status,'no_bird');
 await el('undo').click();assert.equal(app.state.quick.at,1);assert.equal(app.state.photos.get(q1).manual.status,'unreviewed');
 el('auto-next').checked=false;events.keydown({key:'u',target:{tagName:'BODY'},preventDefault:()=>{}});await until(()=>!app.state.busy&&app.state.photos.get(q1).manual.status==='uncertain');assert.equal(app.state.quick.at,1);
 await el('close-quick').click();assert.equal(el('quick').hidden,true);assert.equal(el('gallery').hidden,false);
 el('state').value='pending';await el('state').events.change();assert.equal(app.state.total,2);
 await el('backup').click();assert(el('notice').children.some(e=>e.tagName==='A'&&e.href.startsWith('/backups/')));
 const saved=await (await fetch(base+'/api/export/review')).json();assert.equal(saved.photos.find(p=>p.id===q0).status,'confirmed');assert.equal(saved.photos.find(p=>p.id===q1).status,'uncertain');
 console.log(JSON.stringify({passed:true,api:'real loopback HTTP with synthetic records',ui:'stable gallery save/undo; quick queue; keyboard/input guard; no-bird; database backup; filters',images_loaded:false,requests:requests.length}));
})().catch(err=>{console.error(err);process.exitCode=1;});
