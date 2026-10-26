'use strict';
// Real progress controller; virtual time and synthetic metadata, no photos/network.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.hidden=false;this.textContent='';}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=[...items];}
 setAttribute(k,v){this.attrs[k]=v;}
}
const text=n=>n.textContent+n.children.map(text).join(' ');
function setup(){
 let now=0,next=0;const timers=new Map(),events={},requests=[],errors=[];
 const nodes=new Map(['task-progress','editor-task-progress'].map(id=>[id,new Element('section')]));
 const doc={hidden:false,getElementById:id=>nodes.get(id),createElement:t=>new Element(t),addEventListener:(n,f)=>{(events[n]??=[]).push(f);}};
 const value={items:[]},env={window:{},document:doc,Date:{now:()=>now},Promise,console,setTimeout:(fn,ms)=>{const id=++next;timers.set(id,{fn,at:now+ms});return id;},clearTimeout:id=>timers.delete(id)};
 vm.createContext(env);vm.runInContext(source,env);
 let respond=()=>Promise.resolve(structuredClone(value));
 const p=env.window.BirdProgress;p.init({api:url=>{assert.equal(url,'/api/jobs');requests.push(url);return respond();},error:e=>errors.push(e),onJobs:()=>{}});
 return {p,doc,nodes,value,requests,errors,respond:f=>{respond=f;},emit:n=>(events[n]||[]).forEach(f=>f()),async advance(ms){const end=now+ms;let guard=0;while(true){const entry=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!entry)break;assert(++guard<1000);const [id,t]=entry;timers.delete(id);now=t.at;t.fn();await flush();}now=end;await flush();}};
}
const job=(state='running',counts={done:3,skipped:1,error:1,pending:4,running:1})=>({id:'task',state,counts,found:10,discovery_done:1,current_photo:{id:4,path:'synthetic/<img onerror=alert(1)>鸟.ARW'}});
(async()=>{
 const s=setup();s.value.items=[job()];await s.p.refresh();
 for(const host of s.nodes.values()){
  assert.equal(host.hidden,false);const bar=host.children[1];assert.equal(bar.value,5);assert.equal(bar.max,10);
  assert(text(host).includes('成功 3'));assert(text(host).includes('失败 1'));assert(text(host).includes('<img onerror=alert(1)>鸟.ARW'));
  assert.equal(host.children[2].tagName,'span','filename is text, never markup');
 }
 let observed=0;const unwatch=s.p.watch(()=>{observed++;});
 s.value.items=[job('paused')];await s.p.refresh();await flush();assert(text(s.nodes.get('task-progress')).includes('正在暂停'));assert.equal(observed,1);unwatch();
 s.value.items=[job('paused',{done:4,pending:6})];s.value.items[0].current_photo=null;await s.p.refresh();assert(text(s.nodes.get('task-progress')).includes('已暂停'));assert(!text(s.nodes.get('task-progress')).includes('鸟.ARW'));
 s.value.items=[job('failed',{done:4,error:1,pending:5})];await s.p.refresh();assert(text(s.nodes.get('task-progress')).includes('有失败项'));assert.equal(s.nodes.get('task-progress').children[1].value,5);assert(s.nodes.get('task-progress').className.includes('has-error'));
 await s.advance(12000);assert.equal(s.nodes.get('task-progress').hidden,true);
 s.value.items=[job('discovering',{})];s.value.items[0].discovery_done=0;await s.p.refresh();assert.equal(s.nodes.get('task-progress').children[1].value,undefined,'directory discovery must be indeterminate');
 s.value.items=[job('running',{running:1})];await s.p.refresh();assert.equal(s.nodes.get('task-progress').children[1].value,0,'one photo is not complete until its result arrives');
 s.respond(()=>Promise.reject(Error('offline')));await assert.rejects(s.p.refresh());assert(text(s.nodes.get('task-progress')).includes('尚未确认完成'));
 s.respond(()=>Promise.resolve(structuredClone(s.value)));
 const n=s.requests.length;s.doc.hidden=true;s.emit('visibilitychange');await s.advance(30000);assert.equal(s.requests.length,n,'hidden page must stop polling');
 s.doc.hidden=false;s.emit('visibilitychange');await flush();assert.equal(s.requests.length,n+1,'return to page refreshes immediately');
 await s.advance(121000);const idleCount=s.requests.length;await s.advance(30000);assert.equal(s.requests.length,idleCount,'2-minute inactivity must stop polling even with a running job');
 assert(text(s.nodes.get('task-progress')).includes('刷新已暂停'));s.emit('pointerdown');await flush();assert.equal(s.requests.length,idleCount+1);
 let release;s.respond(()=>new Promise(r=>{release=r;}));const a=s.p.refresh(),before=s.requests.length,b=s.p.refresh();assert.equal(a,b);assert.equal(s.requests.length,before,'main view and editor share one in-flight read');release({items:[]});await a;
 const score=s.p.begin('质量评分',10,'synthetic/first.ARW');assert.equal(s.nodes.get('task-progress').children[1].value,0);score.update({done:3,path:'synthetic/fourth.ARW'});score.finish(Error('合成读取失败'));assert.equal(s.nodes.get('task-progress').children[1].value,3);assert(text(s.nodes.get('task-progress')).includes('未完成'));assert(text(s.nodes.get('task-progress')).includes('合成读取失败'));
 const preview=s.p.begin('加载原图预览',1,'synthetic/one.ARW');preview.finish();assert.equal(s.nodes.get('task-progress').children[1].value,1);
 const finish=setup();finish.value.items=[job('running',{running:1})];await finish.p.refresh();finish.value.items=[job('completed',{done:1})];finish.value.items[0].current_photo=null;await finish.p.refresh();assert(text(finish.nodes.get('task-progress')).includes('处理完成'));assert.equal(finish.nodes.get('task-progress').children[1].value,1);await finish.advance(12000);assert(finish.nodes.get('task-progress').hidden);
 assert.deepEqual(s.errors,[]);console.log('PASS: counts/current file, modal mirror, errors, completion, single-photo progress, deduplicated polling, hidden/idle stop and wake; no image access.');
})().catch(e=>{console.error(e);process.exitCode=1;});
