'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const events={},imageEvents={},classes=new Set(),captures=new Set();let resized;
const view={clientWidth:800,clientHeight:600,classList:{toggle:(k,on)=>on?classes.add(k):classes.delete(k)},
 addEventListener:(k,fn)=>events[k]=fn,setPointerCapture:id=>captures.add(id),releasePointerCapture:id=>captures.delete(id),
 getBoundingClientRect:()=>({left:100,top:50,width:view.clientWidth,height:view.clientHeight})};
const image={naturalWidth:1600,naturalHeight:800,style:{},src:'synthetic',getAttribute:()=>image.src,addEventListener:(k,fn)=>imageEvents[k]=fn},label={};
const context={window:{},ResizeObserver:class{constructor(fn){resized=fn;}observe(){}},Map,Math};
vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
const zoom=context.window.StudioZoom.create(view,image,label);
let prevented=0;const event=(extra={})=>({clientX:500,clientY:350,preventDefault:()=>prevented++,...extra});
events.wheel(event({deltaY:-120,deltaMode:0}));assert(zoom.state().scale>1);assert(prevented>0);
zoom.reset();zoom.step(2);assert.equal(zoom.state().scale,2);assert(classes.has('zoomed'));
events.pointerdown(event({pointerId:1,pointerType:'mouse',button:0}));
events.pointermove(event({pointerId:1,clientX:2000,clientY:1500}));assert.equal(zoom.state().x,400);assert.equal(zoom.state().y,100,'pan clamps to drawn image, not letterbox');
events.pointerup(event({pointerId:1}));assert.equal(captures.size,0);
zoom.reset();events.dblclick(event({clientX:600}));assert.equal(zoom.state().scale,2);assert.equal(zoom.state().x,-100,'zoom anchored under pointer');
events.dblclick(event());assert.equal(zoom.state().scale,1);assert.equal(zoom.state().x,0);
events.pointerdown(event({pointerId:2,pointerType:'touch',clientX:400}));events.pointerdown(event({pointerId:3,pointerType:'touch',clientX:600}));
events.pointermove(event({pointerId:3,clientX:800}));assert.equal(zoom.state().scale,2);assert.equal(zoom.state().x,100);
events.pointercancel(event({pointerId:3}));events.pointermove(event({pointerId:2,clientX:450}));assert.equal(zoom.state().x,150);
zoom.reset();assert.equal(captures.size,0);assert.equal(zoom.state().pointers,0);
zoom.step(100);assert.equal(zoom.state().scale,8);zoom.step(.0001);assert.equal(zoom.state().scale,1);
zoom.step(2);imageEvents.load();assert.equal(zoom.state().scale,2,'same-crop comparison preserves magnification');
view.clientWidth=1200;view.clientHeight=300;resized();assert.equal(zoom.state().x,0);
image.src='';zoom.reset();zoom.step(2);assert.equal(zoom.state().scale,1,'empty stage ignores zoom');
events.pointerdown(event({pointerId:9,pointerType:'mouse',button:0}));assert.equal(captures.size,0);
console.log('PASS: anchored wheel/buttons, bounded pan, double click, pinch/cancel, resize, no-image and source-load zoom preservation; no fetch API available.');
