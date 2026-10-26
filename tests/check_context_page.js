'use strict';
// 只读取报告文字并模拟 DOM 事件，不渲染或读取私人图像。
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert/strict');
const pagePath=process.argv[2],source=fs.readFileSync(pagePath,'utf8');
const payload=JSON.parse(source.match(/<script id="review-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const api=require('../tools/manual_review.js');
const seededPayload=JSON.parse(JSON.stringify(payload));delete payload.initial_manual_review;
const totalViews=payload.rows.reduce((n,r)=>n+r.views.length,0);
const clone=x=>JSON.parse(JSON.stringify(x));
function storage(){const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v)};}
if(seededPayload.initial_manual_review){const seeded=api.createStore(seededPayload,storage());assert.equal(seeded.counts().confirmed,16);assert.equal(seeded.counts().uncertain,3);assert.equal(seeded.counts().unreviewed,1);}
const cache=storage(),core=api.createStore(payload,cache),birds=payload.labels.filter(l=>l.kind==='bird'),id=birds[0].scientific_name;
assert.equal(core.counts().unreviewed,20);core.toggle(0,id);core.toggle(0,birds[1].scientific_name);assert.equal(core.get(0).species.length,2);
const good=core.document();assert.equal(api.createStore(payload,cache).get(0).species.length,2);
core.toggle(0,id);assert.equal(core.get(0).species.length,1);core.setStatus(0,'none_match');assert.equal(core.get(0).species.length,0);assert.equal(core.get(0).status,'none_match');
core.importDocument(good);const snapshot=JSON.stringify(core.document());
const invalid=[];
let bad=clone(good);bad.batch_id='wrong';invalid.push(bad);
bad=clone(good);bad.photos[0].source_sha256='wrong';invalid.push(bad);
bad=clone(good);bad.photos[1]=clone(bad.photos[0]);invalid.push(bad);
bad=clone(good);bad.photos[0].species[0].scientific_name='a rock';invalid.push(bad);
bad=clone(good);bad.photos[0].status='uncertain';invalid.push(bad);
bad=clone(good);bad.photos[0].species.push(clone(bad.photos[0].species[0]));invalid.push(bad);
for(const doc of invalid){assert.throws(()=>core.importDocument(doc));assert.equal(JSON.stringify(core.document()),snapshot);}
const noStorage=api.createStore(payload,{getItem:()=>null,setItem:()=>{throw Error('blocked');}});noStorage.toggle(0,id);assert.equal(noStorage.get(0).status,'confirmed');assert.equal(noStorage.info().persisted,false);assert.match(noStorage.info().notice,/导出/);
assert.throws(()=>core.toggle(0,'a rock'));assert.equal(JSON.stringify(core.document()),snapshot);
class Element{constructor(){this.value='';this.checked=false;this.textContent='';this.children=[];this.events={};this.attrs={};this.disabled=false;}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}addEventListener(n,f){this.events[n]=f;}setAttribute(n,v){this.attrs[n]=v;}click(){if(this.events.click)return this.events.click();}}
function boot(cache){const elements=new Map();for(const match of source.matchAll(/\bid="([^\"]+)"/g)){assert(!elements.has(match[1]));elements.set(match[1],new Element());}
const el=id=>{assert(elements.has(id),'缺少 DOM id: '+id);return elements.get(id);};
el('review-data').textContent=JSON.stringify(payload);el('enabled').checked=true;el('use-date').checked=true;
let downloaded;const window={localStorage:cache,addEventListener:()=>{}};
const sandbox={window,console,structuredClone,Blob,setTimeout:fn=>fn(),URL:{createObjectURL:blob=>{downloaded=blob;return 'blob:test';},revokeObjectURL:()=>{}},document:{getElementById:id=>elements.get(id)||null,createElement:()=>new Element()}};
vm.createContext(sandbox);for(const file of ['context_rank.js','manual_review.js','manual_review_ui.js','context_review.js'])vm.runInContext(fs.readFileSync(path.join(path.dirname(pagePath),file),'utf8'),sandbox);
return {el,download:async()=>JSON.parse(await downloaded.text())};}
(async()=>{
const local=storage(),ui=boot(local),el=ui.el;
assert(!el('message').textContent.startsWith('无法调整'));assert.equal(el('region').value,'IIA');assert.match(el('review-message').textContent,/已确认 0\/20/);
const choice=el('raw-0-0').children[0].children[0].children[0];assert.equal(choice.type,'checkbox');choice.events.change();assert(choice.checked);assert.match(el('review-message').textContent,/已确认 1\/20/);
el('export-review').click();const exportedReview=await ui.download();assert.equal(exportedReview.photos[0].status,'confirmed');const selected=exportedReview.photos[0].species[0].scientific_name;
el('enabled').checked=false;el('apply').click();assert.match(el('message').textContent,/首选改变 0\//);el('export-review').click();assert.equal((await ui.download()).photos[0].species[0].scientific_name,selected);
const reloaded=boot(local);assert.match(reloaded.el('review-message').textContent,/已确认 1\/20/);assert.match(reloaded.el('review-message').textContent,/已恢复/);
el('none_match-0').click();assert.match(el('review-message').textContent,/候选都不对 1/);el('uncertain-0').click();assert.match(el('review-message').textContent,/暂不确定 1/);el('unreviewed-0').click();assert.match(el('review-message').textContent,/未复核 20/);
el('species-search-0').value=selected;el('species-search-0').events.input();assert(el('species-results-0').children.some(x=>x.value===selected));el('species-results-0').value=selected;el('add-species-0').click();el('add-species-0').click();el('export-review').click();assert.equal((await ui.download()).photos[0].species.length,1);
el('selected-0').children[1].click();assert.match(el('review-message').textContent,/已确认 0\/20/);
const beforeImportMessage=el('selected-0').children[0].textContent;
const importer=el('import-review');importer.files=[{size:100,text:async()=>JSON.stringify(exportedReview)}];await importer.events.change({target:importer});assert.equal(el('apply-import').disabled,false);assert.equal(el('selected-0').children[0].textContent,beforeImportMessage);el('apply-import').click();assert.match(el('review-message').textContent,/已确认 1\/20/);
importer.files=[{size:100,text:async()=>JSON.stringify(invalid[0])}];await importer.events.change({target:importer});assert.equal(el('apply-import').disabled,true);assert.match(el('review-message').textContent,/未导入/);el('export-review').click();assert.equal((await ui.download()).photos[0].status,'confirmed');
el('capture-date').value='2026-02-29';el('apply').click();assert.match(el('message').textContent,/日期无效/);el('capture-date').value='2026-01-07';el('apply').click();assert.match(el('context-0').textContent,/页面手动覆盖/);
el('export').click();const manifest=await ui.download();assert.deepEqual(manifest.samples.map(s=>s.truth),payload.manifest.samples.map(s=>s.truth));assert.equal(manifest.samples[0].manual_review.status,'confirmed');assert(manifest.samples.every(s=>s.capture_context.date==='2026-01-07'));
el('reset').click();assert.equal(el('capture-date').value,'');el('export-review').click();assert.equal((await ui.download()).photos[0].species[0].scientific_name,selected);
assert.equal((source.match(/<img /g)||[]).length,totalViews);assert(source.includes("connect-src 'none'"));
console.log(JSON.stringify({rows:20,views:totalViews,core:'dedup,multispecies,revoke,storage restore/failure,atomic invalid imports,source binding',ui:'click,search,status,refresh,rereank preservation,export,import preview/apply,original truth preservation',rendered_images:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});

