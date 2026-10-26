'use strict';
(function(root){
function create(data,displayName,onChange,adaptImport){
let storage=null;try{storage=window.localStorage;}catch(_){}
const review=BirdManualReview.createStore(data,storage), inputs=data.rows.map(()=>[]);
const el=id=>document.getElementById(id), message=el('review-message');let pending=null;
function render(ri,notify=true,reason=null){
const record=review.get(ri),selected=new Set(record.species.map(s=>s.scientific_name));
for(const item of inputs[ri])item.checkbox.checked=selected.has(item.id);
const panel=el('selected-'+ri);panel.replaceChildren();const heading=document.createElement('strong');
heading.textContent={unreviewed:'尚未复核',confirmed:'人工确认',none_match:'候选都不对（不等于没有鸟）',uncertain:'暂不确定',no_bird:'已标记无鸟 · 可恢复'}[record.status];panel.append(heading);
for(const species of record.species){const index=data.labels.findIndex(l=>l.scientific_name===species.scientific_name),b=document.createElement('button');b.type='button';b.className='selected-species';b.textContent=displayName(index)+' ×';b.setAttribute('aria-label','撤销确认 '+displayName(index));b.addEventListener('click',()=>{review.toggle(ri,species.scientific_name);render(ri);});panel.append(b);}
for(const state of ['none_match','uncertain','unreviewed','no_bird'])el(state+'-'+ri)?.setAttribute('aria-pressed',String(record.status===state));
if(notify&&onChange)onChange(ri,reason);
const c=review.counts();message.textContent='已确认 '+c.confirmed+'/'+data.rows.length+' 张 · 候选都不对 '+c.none_match+' · 暂不确定 '+c.uncertain+' · 无鸟已剔除 '+c.no_bird+' · 未复核 '+c.unreviewed+'。'+review.info().notice;
}
function renderAll(){data.rows.forEach((_,i)=>render(i,false));if(onChange)onChange(null);}
function choice(ri,index,main){
const label=data.labels[index];if(label.kind!=='bird')return main;
const wrapper=document.createElement('label'),checkbox=document.createElement('input');wrapper.className='species-choice';checkbox.type='checkbox';
checkbox.checked=review.get(ri).species.some(s=>s.scientific_name===label.scientific_name);checkbox.setAttribute('aria-label','确认本张照片包含 '+displayName(index));
checkbox.addEventListener('change',()=>{review.toggle(ri,label.scientific_name);render(ri);});inputs[ri].push({checkbox,id:label.scientific_name});wrapper.append(checkbox,main);return wrapper;
}
data.rows.forEach((row,ri)=>{
for(const state of ['none_match','uncertain','unreviewed','no_bird'])el(state+'-'+ri)?.addEventListener('click',()=>{review.setStatus(ri,state);render(ri,true,state);});
const input=el('species-search-'+ri),select=el('species-results-'+ri);
input.addEventListener('input',()=>{select.replaceChildren();const query=input.value.trim().toLocaleLowerCase();
const found=query?data.labels.map((label,i)=>({label,i})).filter(({label,i})=>label.kind==='bird'&&[displayName(i),label.zh_name,label.scientific_name,label.english_name,...(label.aliases||[])].some(s=>(s||'').toLocaleLowerCase().includes(query))).slice(0,50):[];
const hint=document.createElement('option');hint.value='';hint.textContent=found.length?'请选择鸟种（最多显示 50 项）':(query?'无匹配，请调整关键词':'先输入中文名或学名');select.append(hint);
for(const item of found){const option=document.createElement('option');option.value=item.label.scientific_name;option.textContent=displayName(item.i)+' · '+item.label.scientific_name+(item.label.birdreport_status&&!item.label.birdreport?' · 郑四对应待核对':'');select.append(option);}select.value='';});
el('add-species-'+ri).addEventListener('click',()=>{if(!select.value){message.textContent='请先从搜索结果中点选鸟种。';return;}review.confirmOne(ri,select.value);render(ri,true,'single');});
});
el('export-review').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(review.document(),null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='bird-manual-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message.textContent='已请求下载人工复核 JSON；可导入继续复核。请保留该文件，不含照片。';});
el('import-review').addEventListener('change',async event=>{
pending=null;el('apply-import').disabled=true;const file=event.target.files[0];if(!file)return;
try{if(file.size>2*1024*1024)throw Error('复核 JSON 超过 2 MiB 上限');const parsed=JSON.parse(await file.text()),doc=adaptImport?adaptImport(parsed,review.document()):parsed,checked=review.validate(doc);pending=parsed;el('apply-import').disabled=false;message.textContent='文件有效，'+checked.filter(x=>x.status==='confirmed').length+' 张有人工确认。点击“应用导入”将替换本批复核；需保留当前选择时请先导出。';}catch(err){message.textContent='未导入：'+err.message;}event.target.value='';
});
el('apply-import').addEventListener('click',()=>{
if(!pending)return;
try{const doc=adaptImport?adaptImport(pending,review.document()):pending;review.importDocument(doc);pending=null;el('apply-import').disabled=true;renderAll();}
catch(err){pending=null;el('apply-import').disabled=true;message.textContent='未导入：'+err.message;}
});
window.addEventListener('beforeunload',event=>{if(!review.info().persisted&&review.document().photos.some(p=>p.updated_at)){event.preventDefault();event.returnValue='';}});
renderAll();return {info:review.info,choice,resetInputs:i=>{inputs[i]=[];},get:review.get,renderAll,confirmMany:(indices,id)=>{const count=review.confirmMany(indices,id);renderAll();return count;},undoLastBatch:()=>{const count=review.undoLastBatch();renderAll();return count;},undoInfo:review.undoInfo,confirmOne:(i,id)=>{review.confirmOne(i,id);render(i,true,'single');},setStatus:(i,state)=>{review.setStatus(i,state);render(i,true,state);},undoLast:()=>{const result=review.undoLast();renderAll();return result;},historyInfo:review.historyInfo};
}
root.BirdManualUI={create};
})(globalThis);

