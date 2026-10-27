'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let ready=false,key='first',fetches=0,generations=0,events={},timers=new Map(),timerId=0,lastSignal;
const context={window:{addEventListener:(name,fn)=>events[name]=fn},Map,Date,URLSearchParams,DOMException,
 setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
 fetch:async()=>{fetches++;return {ok:true,status:200,blob:async()=>({size:100})};}};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
const preview=context.window.BirdDisplayPreview,photo={id:1,sha256:'a'.repeat(64),edit_revision:0};
const options={api:async(path,body,signal)=>{lastSignal=signal;if(body){generations++;ready=true;return {ready:true,key};}return {ready,key};}};
(async()=>{
 assert.equal(await preview.load(photo,options,'auto'),null);assert.equal(fetches,0);assert.equal(generations,0);
 await preview.generate(photo,options);assert.equal(generations,1);
 const first=await preview.load(photo,options,'auto');await preview.load(photo,options,'raw');assert.equal(fetches,2);
 assert.equal(await preview.load(photo,options,'auto'),first);assert.equal(fetches,2);
 key='changed-crop';await preview.load({...photo,edit_revision:1},options,'auto');assert.equal(fetches,3);
 ready=false;assert.equal(await preview.load(photo,options,'auto'),null);assert.equal(generations,1);
 ready=true;const aborted={aborted:true};await assert.rejects(preview.load(photo,options,'auto',aborted),{name:'AbortError'});assert.equal(fetches,3);assert.equal(lastSignal,aborted);
 events.pagehide();assert.equal(timers.size,0);await preview.load(photo,options,'auto');assert.equal(fetches,4);
 await assert.rejects(preview.load(photo,options,'invalid'));
 console.log('Display cache: explicit generation, crop versions, two modes, no prefetch, cancellation and cleanup passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
