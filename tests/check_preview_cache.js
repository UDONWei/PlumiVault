'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let clock=0,count=0,reads=0,size=100,version='a',fail=false,delay=null;
const events={},timers=new Map();let timerId=0;
const response=()=>({ok:true,headers:{get:()=>6000},blob:async()=>({size})});
const context={window:{addEventListener:(n,f)=>events[n]=f},Date:{now:()=>clock},AbortController,
 setTimeout:(f,ms)=>{const id=++timerId;timers.set(id,{f,ms});return id;},clearTimeout:id=>timers.delete(id),
 fetch:async()=>{count++;if(fail)throw Error('network down');if(delay)await delay;return response();}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
const p=id=>({id,sha256:'sha-'+id}),options={token:()=>'',api:async url=>{reads++;return {sha256:'sha-'+url.split('=').at(-1),key:version};}},cache=context.window.BirdPreview;
const load=(id,...rest)=>cache.load(p(id),options,...rest);
(async()=>{
 assert.equal((await load(1)).cached,false);assert.equal((await load(1)).cached,true);assert.equal(count,1);assert.equal(reads,2);
 version='b';assert.equal((await load(1)).cached,false);await load(1,'screen',true);assert.equal(count,3);
 await load(1,'full');await load(1,'full');assert.equal(count,5,'full images are never retained');
 cache.clear();await load(1);await load(2);await load(3);await load(1);await load(4);const n=count;await load(1);assert.equal(count,n);await load(2);assert.equal(count,n+1,'evicts least recently used of three');
 clock+=300001;const before=count;await load(1);assert.equal(count,before+1,'expires after five minutes');
 cache.clear();size=5*1024*1024;await load(1);await load(2);await load(3);const b=count;await load(1);assert.equal(count,b+1,'12 MiB cap evicts before entry cap');
 size=13*1024*1024;cache.clear();await load(1);await load(1);assert.equal(count,b+3,'oversized response not retained');
 size=100;cache.clear();fail=true;await assert.rejects(load(1),/network down/);fail=false;assert.equal((await load(1)).cached,false,'failure is retryable');
 await assert.rejects(cache.load(p(1),{...options,api:async()=>({sha256:'changed',key:'x'})}),/照片版本/);
 await assert.rejects(cache.load(p(1),{...options,api:async()=>{throw Error('source missing');}}),/source missing/);
 cache.clear();let release;delay=new Promise(r=>release=r);const a=load(1),c=load(1);for(let i=0;i<8;i++)await Promise.resolve();const waiting=count;release();await Promise.all([a,c]);delay=null;assert.equal(count,waiting,'deduplicates in-flight fetch');
 events.pagehide();const hidden=count;await load(1);assert.equal(count,hidden+1,'pagehide releases cached blobs');
 cache.clear();delay=new Promise(r=>release=r);const late=load(1);for(let i=0;i<8;i++)await Promise.resolve();events.pagehide();release();await late;delay=null;const gone=count;await load(1);assert.equal(count,gone+1,'response completing after pagehide must not repopulate cache');
 console.log('PASS: preview cache revalidation, SHA rejection, LRU/byte/TTL bounds, explicit reload, full bypass, request deduplication, failure retry and pagehide.');
})().catch(e=>{console.error(e);process.exitCode=1;});
