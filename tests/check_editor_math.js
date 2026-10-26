'use strict';
const assert=require('assert/strict'),fs=require('fs'),M=require('../web/editor-math.js'),S=require('../web/search.js');
for(const row of JSON.parse(fs.readFileSync(process.argv[2],'utf8')))assert.deepEqual([...M.lut(row.recipe)],row.lut);
const view=M.fit(9568,6376,1200,800),point=[.23,.67],screen=[view.x+point[0]*9568*view.scale,view.y+point[1]*6376*view.scale];
for(const v of [view,M.zoom(view,3,...screen,.01,12)]){const p=M.point(...screen,v,9568,6376);assert(Math.abs(p[0]-point[0])<1e-10);assert(Math.abs(p[1]-point[1])<1e-10);}
assert.deepEqual(M.box([.9,.8],[.1,.2]),[.1,.2,.9,.8]);assert.deepEqual(M.point(-100,-100,view,9568,6376),[0,0]);
const bounds=[.2,.2,.8,.8];assert.equal(M.hit([.2,.2],bounds,[.02,.02]),'nw');assert.equal(M.hit([.5,.5],bounds,[.02,.02]),'move');assert.equal(M.hit([.1,.1],bounds,[.02,.02]),null);assert.deepEqual(M.adjustBox(bounds,'nw',[.3,.3],[.2,.2]),[.3,.3,.8,.8]);const moved=M.adjustBox(bounds,'move',[1,1],[.5,.5]);assert.equal(moved[2],1);assert.equal(moved[3],1);assert(Math.abs(moved[0]-.4)<1e-10);
const birds=[{id:'a',name:'白鹭',search:['白鹭','bailu','bl']},{id:'b',name:'凤头蜂鹰',search:['凤头蜂鹰','fengtoufengying','ftfy']},{id:'c',name:'黄腰柳莺',search:['黄腰柳莺','huangyaoliuying','hyly']}];
for(const q of ['凤头','fengtou','ftfy','fengtuo'])assert.equal(S.find(birds,q)[0].id,'b');assert.equal(S.find(birds,'hyly')[0].id,'c');assert.equal(S.find(birds,'bái lù')[0].id,'a');
console.log('Tone LUT parity; zoom and normalized selection; Chinese, pinyin, initials and typo suggestions passed. No image loading.');
