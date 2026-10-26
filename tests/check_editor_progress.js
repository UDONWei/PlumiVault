'use strict';
// Exercise the real editor and shared progress controller with synthetic canvas/API responses.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const root=path.resolve(process.argv[2]),elements=new Map(),requests=[],errors=[];let originalReads=0;
const flush=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
class Element{
 constructor(tag='div'){this.tagName=tag;this.children=[];this.attrs={};this.events={};this.value='';this.checked=false;this.width=100;this.height=100;this.textContent='';}
 append(...n){this.children.push(...n);}replaceChildren(...n){this.children=[...n];}setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,f){this.events[k]=f;}getBoundingClientRect(){return {width:640,height:480,left:0,top:0};}
 getContext(){return {drawImage(){},getImageData(){return {data:new Uint8ClampedArray([0,0,0,255])};},putImageData(){}};}
 toDataURL(){return 'data:image/jpeg;base64,c3ludGhldGlj';}showModal(){this.open=true;}close(){this.open=false;}
}
for(const m of fs.readFileSync(path.join(root,'index.html'),'utf8').matchAll(/<([\w-]+)\b[^>]*\bid="([^"]+)"/g))elements.set(m[2],new Element(m[1]));
const doc={hidden:false,getElementById:id=>elements.get(id),createElement:t=>new Element(t),addEventListener(){}};
const context={AbortController,window:{addEventListener(){}},document:doc,Promise,console,setTimeout:()=>1,clearTimeout(){},requestAnimationFrame:()=>1,confirm:()=>true,URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},Image:class {constructor(){this.width=100;this.height=100;}async decode(){}},fetch:async url=>{originalReads++;assert.equal(url,'/api/original');return {ok:true,blob:async()=>({synthetic:true,size:100}),headers:{get:()=>100}};}};
vm.createContext(context);for(const name of ['editor-math','progress','preview-cache','editor'])vm.runInContext(fs.readFileSync(path.join(root,name+'.js'),'utf8'),context);
const data={preview_version:{sha256:'fixture-sha',key:'stat-1'},photo:{id:1,path:'synthetic/one.ARW',sha256:'fixture-sha',manual:{revision:1,species:['Bird alpha']},candidates:[],detection:{selected_box:[.1,.1,.9,.9]}},adjustment:{revision:0,recipe:{}},history:[],source_path:'synthetic/one.ARW'};
let task=0,job=null,changed=0;
const api=async(url,body)=>{requests.push(url);if(url==='/api/editor?id=1')return structuredClone(data);if(url==='/api/adjustments'){assert.equal(body.photo_id,1);data.adjustment={revision:data.adjustment.revision+1,recipe:body.recipe};return structuredClone(data.adjustment);}if(url==='/api/reprocess'){assert.equal(body.photo_id,1);job={id:String(++task),state:'running',counts:{running:1},found:1,discovery_done:1,current_photo:{id:1,path:'synthetic/one.ARW'}};return {id:job.id};}throw Error('Editor must not poll independently: '+url);};
(async()=>{
 const p=context.window.BirdProgress,editor=context.window.BirdEditor;
 p.init({api:async url=>{assert.equal(url,'/api/jobs');return {items:job?[structuredClone(job)]:[]};},error:e=>errors.push(e)});
 await editor.open(1,{api,token:()=>'',name:id=>id,birds:()=>[],onChanged:async()=>{changed++;}});
 await elements.get('editor-recognize').events.click();await flush();
 assert.equal(task,1);assert.equal(changed,1);assert.equal(elements.get('task-progress').hidden,false);assert.equal(elements.get('editor-task-progress').hidden,false);assert.equal(elements.get('task-progress').children[1].value,0);
 job={...job,state:'completed',counts:{done:1},current_photo:null};await p.refresh();await flush();assert.equal(changed,2);assert(elements.get('editor-message').textContent.includes('重新识别完成'));assert.equal(elements.get('task-progress').children[1].value,1);
 await elements.get('editor-recognize').events.click();await flush();assert.equal(task,2);elements.get('editor-close').events.click();assert(!editor.isOpen());const before=changed,reads=requests.filter(x=>x==='/api/editor?id=1').length;
 job={...job,state:'completed',counts:{done:1},current_photo:null};await p.refresh();await flush();assert.equal(changed,before);assert.equal(requests.filter(x=>x==='/api/editor?id=1').length,reads);assert.equal(elements.get('task-progress').children[1].value,1,'main page keeps showing completion after editor close');assert(!requests.includes('/api/jobs'));assert.deepEqual(errors,[]);
 await editor.open(1,{api,token:()=>'',name:id=>id,birds:()=>[],onChanged:async()=>{changed++;}});assert.equal(originalReads,1,'closing and reopening reuses the screen preview');assert(elements.get('editor-message').textContent.includes('复用'));
 console.log('PASS: real editor submission/completion, shared progress, no duplicate job polling, safe editor close; synthetic pixels only.');
})().catch(e=>{console.error(e);process.exitCode=1;});
