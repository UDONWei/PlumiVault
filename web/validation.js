'use strict';
// Private human labels only. Never call scoring, scan, editor-save or move APIs.
(() => {
const state={batch:null,active:null,current:null,busy:false,options:null};
const focus=[['unreviewed','未标注'],['clear','清晰'],['defocus','疑似虚焦'],['motion_blur','运动模糊'],['mixed','虚焦与运动模糊都有'],['uncertain','原因不确定']];
const preferences=[['unreviewed','未标注'],['preferred','最想保留（允许并列）'],['ordinary','普通／非首选']];
const $=id=>document.getElementById(id);
function element(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function button(text,action){const b=element('button',text);b.type='button';b.onclick=()=>run(action);return b;}
async function run(action){try{if(state.busy)throw Error('验证标注正在保存，请稍后');state.busy=true;await action();}catch(e){state.options.error(e);}finally{state.busy=false;}}
function select(values,value,change){const s=element('select');for(const [v,t] of values){const o=element('option',t);o.value=v;s.append(o);}s.value=value;s.onchange=()=>run(()=>change(s.value));return s;}
const group=()=>state.batch?.groups.find(g=>g.id===state.active);
function init(options){
 state.options=options;const panel=element('details');panel.id='validation-panel';panel.className='validation-panel';panel.append(element('summary','验证样片 · 清晰度与组内偏好（不影响正式评分）'));
 const content=element('div');content.id='validation-content';panel.append(content);options.container.append(panel);
 panel.addEventListener('toggle',()=>{if(panel.open&&!state.batch&&!state.busy)run(load);});
 render();
}
async function load(){state.batch=await state.options.api('/api/validation');if(!group())state.active=state.batch.groups[0]?.id||null;render();state.options.repaint();}
async function save(value){state.batch=await state.options.api('/api/validation',{...value,revision:state.batch.revision});if(!group())state.active=state.batch.groups.at(-1)?.id||null;render();state.options.repaint();state.options.message('验证标注已保存；原片、鸟种、星级与正式评分保持。');}
async function add(){
 const photos=state.options.selected();if(photos.length<2)throw Error('先勾选同一连续组的至少 2 张照片');
 if(!state.batch)await load();
 await save({action:'add',ids:photos.map(p=>p.id),sources:photos.map(p=>({id:p.id,sha256:p.sha256,adjustment_revision:p.edit_revision||0}))});state.active=state.batch.groups.at(-1).id;render();state.options.repaint();
}
function render(){
 const content=$('validation-content');if(!content)return;content.replaceChildren();
 content.append(element('p','先在缩略图勾选连续照片，再建验证组。建议 3 组共 12～24 张，本批最多 30 张。标签保存在图库数据库，导出只含文字与路径。'));
 content.append(button('勾选图建立验证组',add),button('重新加载验证批次',load));
 if(!state.batch)return;
 const count=state.batch.groups.reduce((n,g)=>n+g.samples.length,0);content.append(element('span',' 本批 '+count+' / 30 张'));
 if(!count)return;
 const chooser=select(state.batch.groups.map(g=>[g.id,g.name+' · '+g.samples.length+' 张']),state.active,async id=>{state.active=id;render();});chooser.setAttribute('aria-label','当前验证组');content.append(chooser);
 const g=group();if(!g)return;
 const name=element('input');name.value=g.name;name.maxLength=60;name.setAttribute('aria-label','验证组名称');
 const split=select([['unassigned','用途待定'],['development','调试组'],['holdout','独立验证组']],g.split,async value=>save({action:'group',group_id:g.id,name:g.name,split:value}));split.setAttribute('aria-label','整组用途');
 content.append(name,button('保存组名',()=>save({action:'group',group_id:g.id,name:name.value,split:g.split})),split);
 content.append(button('在工作台查看本组',()=>state.options.view(g)),button('移除该验证组',async()=>{if(!window.confirm('仅移除这个验证组及其验证标注；不删除或移动原片。继续？'))return;await save({action:'remove',group_id:g.id});}));
 const done=g.samples.filter(p=>p.focus!=='unreviewed'&&p.preference!=='unreviewed').length;
 content.append(element('p','当前组：已标注 '+done+' / '+g.samples.length+' 张；最想保留 '+g.samples.filter(p=>p.preference==='preferred').length+' 张。请用原始像素核对，不根据缩略图判断虚焦。'));
 const batch=select(focus,'unreviewed',async()=>{});batch.setAttribute('aria-label','勾选图清晰度标注');
 content.append(batch,button('应用到本组勾选图',()=>save({action:'label',group_id:g.id,ids:state.options.selected().map(p=>p.id),fields:{focus:batch.value}})));
 content.append(button('导出全部验证组 JSON',download),element('small','可导出未标完的草稿；未标注不会被当作普通或不清晰。导出含私人路径，请勿提交公共仓库。'));
 const stale=g.samples.filter(p=>p.stale_reason);if(stale.length)content.append(element('p','有 '+stale.length+' 张索引或框选已变化，导出前请移除该组、重新加入并核对。'));
}
function side(container,photo){
 state.current=photo;
 const section=element('section');section.className='validation-labels';section.append(element('h3','验证标注（独立保存）'));container.append(section);
 if(!state.batch){section.append(button('打开验证样片',async()=>{$('validation-panel').open=true;await load();}));return;}
 const g=state.batch.groups.find(g=>g.samples.some(s=>s.id===photo.id));
 if(!g){section.append(element('small','此图尚未加入验证组。勾选连续照片后，在上方“验证样片”建立组。'));return;}
 const sample=g.samples.find(s=>s.id===photo.id);section.append(element('p',g.name));
 if(sample.stale_reason){section.append(element('p',sample.stale_reason));return;}
 const saveLabel=fields=>save({action:'label',group_id:g.id,ids:[photo.id],fields});
 const f=select(focus,sample.focus,value=>saveLabel({focus:value}));f.setAttribute('aria-label','此图清晰度');
 const preferred=select(preferences,sample.preference,value=>saveLabel({preference:value}));preferred.setAttribute('aria-label','此图组内偏好');
 section.append(f,preferred);
 const note=element('input');note.value=sample.note;note.maxLength=300;note.placeholder='可选：拖影方向、遮挡或判断依据';note.setAttribute('aria-label','验证备注');
 section.append(note,button('保存验证备注',()=>saveLabel({note:note.value})),element('small','先核对眼睛与头部。允许原因不确定、并列保留；不改星级、不移动原片。'));
}
function badge(id){const g=state.batch?.groups.find(g=>g.samples.some(s=>s.id===id));if(!g)return '';const p=g.samples.find(s=>s.id===id);return '验证：'+focus.find(([v])=>v===p.focus)[1]+(p.preference==='preferred'?' · ★组内首选':'')+(p.stale_reason?' · 需重新核对':'');}
async function download(){
 const doc=await state.options.api('/api/export/validation');
 const blob=new Blob([JSON.stringify(doc,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=element('a');
 a.href=url;a.download='plumivault-quality-validation.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 state.options.message('已导出 '+doc.samples.length+' 张的验证清单；未标完 '+doc.unreviewed_count+' 张。没有读取或复制原片。');
}
window.BirdValidation={init,side,badge};
})();
