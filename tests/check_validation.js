'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const nodes=new Map(),errors=[],calls=[],messages=[],downloads=[];
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.events={};this.value='';}
 set id(id){this._id=id;nodes.set(id,this);}get id(){return this._id;}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,fn){this.events[k]=fn;}
 click(){downloads.push({name:this.download,href:this.href});}
 remove(){}
}
const body=new Element('body'),container=new Element('div'),side=new Element('aside');body.append(container,side);
let selected=[{id:1},{id:2}],batch={revision:0,groups:[]},fail=false,viewed=null,blobs=[];
const api=async(url,value)=>{
 calls.push({url,value});if(fail)throw Error('simulated conflict');
 if(url==='/api/validation'&&!value)return structuredClone(batch);
 if(url==='/api/validation'){
  assert.equal(value.revision,batch.revision);
  if(value.action==='add')batch.groups.push({id:'group1',name:'验证组 1',split:'unassigned',samples:value.ids.map(id=>({id,focus:'unreviewed',preference:'unreviewed',note:'',stale_reason:null}))});
  if(value.action==='label')for(const s of batch.groups[0].samples)if(value.ids.includes(s.id))Object.assign(s,value.fields);
  if(value.action==='group')Object.assign(batch.groups[0],{name:value.name,split:value.split});
  if(value.action==='remove')batch.groups=[];
  batch.revision++;return structuredClone(batch);
 }
 if(url==='/api/export/validation')return {schema:'plumivault-quality-validation-v1',samples:batch.groups.flatMap(g=>g.samples),unreviewed_count:1};
 throw Error('Unexpected API: '+url);
};
const ctx={window:{confirm:()=>true},document:{body,createElement:tag=>new Element(tag),getElementById:id=>nodes.get(id)},Blob,URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:synthetic';},revokeObjectURL:()=>{}},setTimeout:fn=>fn(),console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const app=ctx.window.BirdValidation;
function repaint(){side.replaceChildren();app.side(side,{id:1});}
const button=text=>descendants(container).find(n=>n.tagName==='button'&&n.textContent===text);
const labelled=(root,label)=>descendants(root).find(n=>n.attrs['aria-label']===label);
(async()=>{
 app.init({container,api,error:e=>errors.push(e.message),message:m=>messages.push(m),selected:()=>selected,repaint,view:g=>{viewed=g.id;}});
 assert.equal(calls.length,0,'idle initialization must not fetch or poll');
 await button('勾选图建立验证组').onclick();assert.equal(batch.groups[0].samples.length,2);
 let f=labelled(side,'此图清晰度');f.value='defocus';await f.onchange();
 let p=labelled(side,'此图组内偏好');p.value='preferred';await p.onchange();
 assert.equal(batch.groups[0].samples[0].focus,'defocus');assert.equal(batch.groups[0].samples[0].preference,'preferred');
 assert(app.badge(1).includes('组内首选'));assert(!app.badge(3));
 await button('重新加载验证批次').onclick();assert.equal(labelled(side,'此图清晰度').value,'defocus');
 await button('在工作台查看本组').onclick();assert.equal(viewed,'group1');
 selected=[{id:2}];const many=labelled(container,'勾选图清晰度标注');many.value='motion_blur';await button('应用到本组勾选图').onclick();
 assert.equal(batch.groups[0].samples[0].focus,'defocus');assert.equal(batch.groups[0].samples[1].focus,'motion_blur');
 const before=batch.revision;fail=true;f=labelled(side,'此图清晰度');f.value='clear';await f.onchange();assert.equal(batch.revision,before);assert.deepEqual(errors,['simulated conflict']);fail=false;
 await button('重新加载验证批次').onclick();assert.equal(labelled(side,'此图清晰度').value,'defocus');
 await button('导出全部验证组 JSON').onclick();assert.equal(downloads[0].name,'plumivault-quality-validation.json');
 assert.equal(JSON.parse(await blobs[0].text()).samples.length,2);
 assert(calls.every(c=>['/api/validation','/api/export/validation'].includes(c.url)),'must not call scan, move, score or original endpoints');
 await button('移除该验证组').onclick();assert.equal(batch.groups.length,0);
 console.log('PASS: validation creation, independent labels, persistence, batch subset, conflict, group view and JSON export.');
})().catch(e=>{console.error(e);process.exitCode=1;});
