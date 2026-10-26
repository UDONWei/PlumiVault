'use strict';
// 本地复核：人工操作不搬动图库 DOM；显式更新时才重排分组。无网络和原图访问。
(() => {
const el=id=>document.getElementById(id),data=JSON.parse(el('review-data').textContent);
let storage=null;try{storage=window.localStorage;}catch(_){}
BirdLibraryMigration.seed(data,storage);
let ready=false,groups=[],groupUI=[],matched=[],pendingView=null,viewPersisted=false,lastChosen=null;
const expanded=new Set(),showAll=new Set(),rankedRows=new Map(),renderedRows=new Set();
const quick={active:false,queue:[],position:0,home:null,done:false};
const defaults={gap:30,grouping:true,foldSimilar:true,breaks:[],keep:[],covers:[]};let prefs={...defaults};
const prefKey='bird-index-nas:view:'+data.review_batch_id;
try{const saved=storage?.getItem(prefKey);if(saved)prefs=BirdGrouping.validatePreferences(JSON.parse(saved),data);}catch(_){el('view-message').textContent='浏览设置暂存不可用，可导入设置。';}
function name(i){const l=data.labels[i];return l?.birdreport?.zh_name||(l?.zh_name&&!/[?\ufffd]/.test(l.zh_name)?l.zh_name:(l?.scientific_name||l?.prompt||'未知鸟种'));}
const manual=BirdManualUI.create(data,name,(i,reason)=>{if(ready)onManualChange(i,reason);},(doc,current)=>BirdLibraryMigration.merge(data,doc,current));
if(typeof ResizeObserver!=='undefined'){new ResizeObserver(()=>document.documentElement.style.setProperty('--review-toolbar-height',el('review-toolbar').offsetHeight+'px')).observe(el('review-toolbar'));}
const cards=data.rows.map((_,i)=>el('photo-'+i)),pool=el('photo-pool');
const labelsById=new Map(data.labels.map((l,i)=>({l,i})).filter(x=>x.l.kind==='bird').map(x=>[x.l.scientific_name,x.i]));
const folders=[...new Set(data.rows.map(r=>r.source_root))],originalContexts=data.rows.map(r=>structuredClone(r.capture_context));
function birdName(id){return labelsById.has(id)?name(labelsById.get(id)):'待确认';}
function candidateIds(i){return (data.rows[i].views[0]?.context_candidates||data.rows[i].views[0]?.candidates||[]).filter(c=>c.label.kind==='bird').map(c=>c.label.scientific_name).slice(0,5);}
function prefsDocument(){return {schema:'bird-view-settings-v1',batch_id:data.review_batch_id,...prefs};}
function savePrefs(){try{if(!storage)throw Error();storage.setItem(prefKey,JSON.stringify(prefsDocument()));viewPersisted=true;el('view-message').textContent='浏览设置已暂存。';}catch(_){viewPersisted=false;el('view-message').textContent='无法暂存，请导出浏览设置。';}}
function download(value,filename){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function button(text,action){const b=document.createElement('button');b.type='button';b.textContent=text;b.addEventListener('click',action);return b;}
function statusMessage(text){el('workspace-message').textContent=text;}
function renderContext(i){const c=data.rows[i].capture_context;el('context-'+i).textContent='拍摄地：'+(c.location||'未知')+' · 日期：'+(c.date||'未知')+'（'+(c.date_source||'未知')+'） · 亚区：'+(data.occurrences.regions[c.region_code]||'未设置');}
function rankRow(i){const row=data.rows[i],results=row.views.map(view=>{const result=BirdContext.rank(data.labels,view.all_visual_scores,row.capture_context,data.occurrences,data.policy,5);view.context_candidates=result.adjusted.map(c=>({label:data.labels[c.i],visual_score:c.score,ranking_score:c.ranking_score,visual_rank:c.visual_rank,factor:c.factor,statuses:c.statuses,reasons:c.reasons}));return result;});rankedRows.set(i,results);return results;}
function fill(list,candidates,adjusted,i){list.replaceChildren();for(const c of candidates){const li=document.createElement('li'),text=document.createElement('span');text.textContent=name(c.i)+(adjusted?' · 排序值 '+c.ranking_score.toFixed(4):' · 分数 '+c.score.toFixed(4));li.append(manual.choice(i,c.i,text));const small=document.createElement('small');small.textContent=adjusted?'原视觉第 '+c.visual_rank+' 名 · '+c.reasons.join('；'):(data.labels[c.i].scientific_name||'通用对照');li.append(small);list.append(li);}}
function renderQuickChoices(i){
 const list=el('quick-choices-'+i);list.replaceChildren();const record=manual.get(i),ids=candidateIds(i);
 ids.forEach((id,n)=>{const label=data.labels[labelsById.get(id)],note=label?.birdreport_status&&!label.birdreport?' · 郑四对应待核对':'';const b=button((n+1)+'  '+birdName(id)+note,()=>manual.confirmOne(i,id));b.setAttribute('data-species',id);b.setAttribute('aria-pressed',String(record.status==='confirmed'&&record.species.some(s=>s.scientific_name===id)));list.append(b);});
 if(lastChosen&&!ids.includes(lastChosen))list.append(button('沿用刚才：'+birdName(lastChosen),()=>manual.confirmOne(i,lastChosen)));
 const unresolved=ids.filter(id=>!data.labels[labelsById.get(id)]?.birdreport).length;el('taxon-note-'+i).textContent=unresolved?'其中 '+unresolved+' 个候选的郑四对应待核对，保留原名。':'候选名称对应记录中心郑四版；旧名仍可搜索。';
}
function renderCandidates(i){if(renderedRows.has(i))return;manual.resetInputs(i);(rankedRows.get(i)||rankRow(i)).forEach((r,j)=>{fill(el('raw-'+i+'-'+j),r.baseline,false,i);fill(el('adjusted-'+i+'-'+j),r.adjusted,true,i);el('change-'+i+'-'+j).textContent=r.baseline[0].i!==r.adjusted[0].i?'地区辅助改变首选，仍需复核':'首选保持';});renderQuickChoices(i);renderedRows.add(i);}
function syncUndo(){const info=manual.historyInfo();for(const id of ['undo-review','quick-undo'])el(id).disabled=!info.canUndo;groupUI.forEach(ui=>ui.undo.disabled=!manual.undoInfo().canUndo);}
function groupStatus(ui,changed=null){
 const records=ui.indices.map(i=>manual.get(i)),unreviewed=ui.indices.filter(i=>manual.get(i).status==='unreviewed');
 const ids=[...new Set([...records.flatMap(r=>r.species.map(s=>s.scientific_name)),...ui.indices.flatMap(candidateIds)])];
 const previous=ui.select.value,changedRecord=changed!==null&&ui.indices.includes(changed)?manual.get(changed):null;
 ui.select.replaceChildren();for(const id of ids){const o=document.createElement('option');o.value=id;o.textContent=birdName(id);ui.select.append(o);}
 ui.select.value=changedRecord?.status==='confirmed'&&changedRecord.species.length===1?changedRecord.species[0].scientific_name:(ids.includes(previous)?previous:(ids.includes(ui.group.species)?ui.group.species:ids[0]||''));
 ui.apply.textContent='确认本组未复核 '+unreviewed.length+' 张';ui.apply.disabled=!unreviewed.length||!ui.select.value;
 const confirmed=records.filter(r=>r.status==='confirmed').length,excluded=records.filter(r=>r.status==='no_bird').length;
 ui.state.textContent='已确认 '+confirmed+' / '+ui.indices.length+' 张'+(excluded?' · 无鸟 '+excluded+' 张':'')+'；只确认未复核成员，已有判断保持。';
 const currentBirds=[...new Set(ui.indices.map(i=>BirdGrouping.identity(data.rows[i],manual.get(i))?.id).filter(Boolean))];
 if(changed!==null||confirmed)ui.title.textContent=(currentBirds.length>1?'鸟种已变更，待重新分组':currentBirds.length===1?birdName(currentBirds[0]):'待复核')+' · '+ui.indices.length+' 张 · 已确认 '+confirmed+' 张';
}
function onManualChange(i,reason){
 if(i!==null){const r=manual.get(i);if(r.status==='confirmed'&&r.species.length===1)lastChosen=r.species[0].scientific_name;if(renderedRows.has(i))renderQuickChoices(i);}
 else for(const index of renderedRows)renderQuickChoices(index);
 groupUI.forEach(ui=>groupStatus(ui,i));syncUndo();
 statusMessage(manual.info().persisted?'已保存。照片位置保持；点击“更新筛选与分组”再整理。':manual.info().notice);
 if(quick.active&&i===quick.queue[quick.position]&&el('auto-next').checked&&['single','no_bird','uncertain'].includes(reason))moveQuick(1);
 else if(quick.active)updateQuickProgress();
}
function matches(i){
 const row=data.rows[i],r=manual.get(i),folder=el('folder-filter').value,state=el('review-filter').value||'all',query=el('library-search').value.trim().toLocaleLowerCase();
 if(folder&&row.source_root!==folder)return false;
 if(state==='no_bird'){if(r.status!=='no_bird')return false;}else if(state!=='any'&&r.status==='no_bird')return false;
 if(state==='pending'&&r.status==='confirmed')return false;
 if(['confirmed','uncertain','none_match'].includes(state)&&r.status!==state)return false;
 if(state==='undetected'&&row.detection?.status==='detected')return false;
 if(!query)return true;
 const ids=r.status==='confirmed'?r.species.map(s=>s.scientific_name):candidateIds(i);
 return [row.path,...ids,...ids.flatMap(id=>{const l=data.labels[labelsById.get(id)];return [birdName(id),l?.zh_name||'',...(l?.aliases||[])];})].some(s=>s.toLocaleLowerCase().includes(query));
}
function renderGroups(){
 if(quick.active)exitQuick(false);
 groups=BirdGrouping.plan(data.rows,data.rows.map((_,i)=>manual.get(i)),prefs);groupUI=[];matched=[];
 for(const card of cards){card.hidden=false;pool.append(card);}const container=el('library-groups');container.replaceChildren();
 const query=el('library-search').value.trim();let showing=0,foldedCount=0,multi=0;
 groups.forEach(group=>{
  const indices=group.indices.filter(matches);if(!indices.length)return;matched.push(...indices);
  const included=new Set(indices),folded=prefs.foldSimilar&&!showAll.has(group.key)&&!query?group.folded.filter(f=>included.has(f.index)&&included.has(f.representative)).map(f=>f.index):[];
  foldedCount+=folded.length;const visible=indices.filter(i=>!folded.includes(i)),cover=visible.includes(group.cover)?group.cover:visible[0];
  for(const i of indices){el('keep-'+i).textContent=prefs.keep.includes(data.rows[i].path)?'已保留 · 恢复自动折叠':'保留此图显示';el('keep-'+i).setAttribute('aria-pressed',String(prefs.keep.includes(data.rows[i].path)));}
  if(!prefs.grouping){for(const i of visible){renderCandidates(i);container.append(cards[i]);showing++;}return;}
  showing++;if(indices.length>1)multi++;
  const wrapper=document.createElement('section');wrapper.className='burst';const details=document.createElement('details'),summary=document.createElement('summary');summary.className='burst-summary';
  const thumb=data.rows[cover].views[0]?.thumbnail;if(thumb){const img=document.createElement('img');img.src='review-thumbnails/'+thumb.name;img.alt='本组封面';img.loading='lazy';summary.append(img);}
  const title=document.createElement('strong'),subtitle=document.createElement('small'),text=document.createElement('div');title.textContent=birdName(group.species)+' · '+indices.length+' 张'+(indices.length<group.indices.length?'（原组 '+group.indices.length+' 张）':'')+' · 待复核';subtitle.textContent=group.directory+' · '+(group.first_time||'拍摄时刻缺失')+' · 相似折叠 '+folded.length+' 张';text.append(title,subtitle);summary.append(text);details.append(summary);
  const toolbar=document.createElement('div');toolbar.className='group-confirm';const select=document.createElement('select');select.setAttribute('aria-label','本组确认鸟种');
  const state=document.createElement('p'),result=document.createElement('p');result.setAttribute('role','status');
  const apply=button('确认本组',()=>{try{const count=manual.confirmMany(indices,select.value);result.textContent='已就地确认 '+count+' 张，可在这里撤销。';}catch(e){result.textContent=e.message;}});
  const undo=button('撤销上次组确认',()=>{try{const count=manual.undoLastBatch();result.textContent='已撤销 '+count+' 张。';}catch(e){result.textContent=e.message;}});
  toolbar.append(select,apply,undo,state,result);details.append(toolbar);
  const ui={group,indices,select,apply,undo,state,result,title};groupUI.push(ui);groupStatus(ui);
  const tools=document.createElement('div');tools.className='group-tools';tools.append(button(showAll.has(group.key)?'按相似规则折叠':'显示本组全部 '+indices.length+' 张',()=>{if(showAll.has(group.key))showAll.delete(group.key);else showAll.add(group.key);indices.forEach(i=>expanded.add(data.rows[i].path));renderGroups();}));
  if(group.indices.length>1)tools.append(button('拆开本组',()=>{prefs.breaks=[...new Set([...prefs.breaks,...group.indices.slice(1).map(i=>data.rows[i].path)])];savePrefs();renderGroups();}));details.append(tools);
  for(const i of indices){cards[i].hidden=folded.includes(i);details.append(cards[i]);}
  details.open=indices.some(i=>expanded.has(data.rows[i].path));if(details.open)visible.forEach(renderCandidates);
  details.addEventListener('toggle',()=>{if(details.open)visible.forEach(renderCandidates);for(const i of indices){const path=data.rows[i].path;if(details.open)expanded.add(path);else expanded.delete(path);}});
  wrapper.append(details);container.append(wrapper);
 });
 el('library-summary').textContent='本次共 '+data.rows.length+' 张；当前筛选 '+matched.length+' 张，显示 '+showing+(prefs.grouping?' 组（其中 '+multi+' 组为连续照片）':' 张')+'，相似折叠 '+foldedCount+' 张。无鸟记录可从“已剔除”找回。';
 if(!showing){const p=document.createElement('p');p.textContent='没有匹配照片，可调整筛选。';container.append(p);}syncUndo();statusMessage('点选只更新记录，后续照片和展开位置保持。');
}
function restoreQuickCard(){if(quick.home){const {i,parent,next,hidden}=quick.home;cards[i].hidden=hidden;if(next&&next.parentNode===parent)parent.insertBefore(cards[i],next);else parent.append(cards[i]);quick.home=null;}}
function showQuick(){
 restoreQuickCard();quick.done=false;const i=quick.queue[quick.position];if(i===undefined)return;
 const card=cards[i];quick.home={i,parent:card.parentNode,next:card.nextSibling,hidden:card.hidden};card.hidden=false;el('quick-stage').append(card);renderCandidates(i);renderQuickChoices(i);updateQuickProgress();card.focus?.({preventScroll:true});
}
function updateQuickProgress(){const i=quick.queue[quick.position],r=i===undefined?null:manual.get(i);el('quick-progress').textContent=(quick.done?'本轮已到最后一张。':'')+' '+(quick.position+1)+' / '+quick.queue.length+' · '+(i===undefined?'':data.rows[i].path)+' · '+({confirmed:'已确认',no_bird:'已剔除，无鸟',unreviewed:'未复核',uncertain:'暂不确定',none_match:'候选都不对'}[r?.status]||'');el('quick-prev').disabled=quick.position<=0;el('quick-next').disabled=quick.position>=quick.queue.length-1;}
function startQuick(after=null){
 if(quick.active)exitQuick(false);
 quick.queue=matched.filter(i=>!['confirmed','no_bird'].includes(manual.get(i).status));
 if(after!==null){const offset=matched.indexOf(after);quick.queue=[...quick.queue.filter(i=>matched.indexOf(i)>offset),...quick.queue.filter(i=>matched.indexOf(i)<=offset)];}
 if(!quick.queue.length){statusMessage('当前筛选没有待复核照片。可选择其他目录或清除筛选。');return;}
 quick.position=0;quick.active=true;el('quick-review').hidden=false;el('library-groups').hidden=true;showQuick();el('quick-review').scrollIntoView?.({block:'start'});
}
function moveQuick(delta){if(!quick.active)return;const next=quick.position+delta;if(next<0)return;if(next>=quick.queue.length){quick.done=true;updateQuickProgress();statusMessage('本轮复核结束，可返回分组或撤销。');return;}quick.position=next;showQuick();}
function exitQuick(rebuild=true){restoreQuickCard();quick.active=false;el('quick-review').hidden=true;el('library-groups').hidden=false;if(rebuild)renderGroups();}
function undoAction(){try{const result=manual.undoLast();if(quick.active){const index=quick.queue.indexOf(result.indices[0]);if(index>=0){quick.position=index;showQuick();}}statusMessage('已撤销刚才 '+result.count+' 张操作。');}catch(e){statusMessage(e.message);}}
function syncPrefs(){el('burst-gap').value=String(prefs.gap);el('group-bursts').checked=prefs.grouping;el('fold-similar').checked=prefs.foldSimilar;}
function applyView(){try{prefs=BirdGrouping.validatePreferences({schema:'bird-view-settings-v1',batch_id:data.review_batch_id,...prefs,gap:Number(el('burst-gap').value),grouping:el('group-bursts').checked,foldSimilar:el('fold-similar').checked},data);savePrefs();renderGroups();}catch(e){el('view-message').textContent=e.message;}}
for(const folder of folders)for(const id of ['folder-filter','context-target']){const o=document.createElement('option');o.value=folder;o.textContent=folder.split(/[\\/]/).at(-1);el(id).append(o);}
Object.entries(data.occurrences.regions).forEach(([code,title])=>{const o=document.createElement('option');o.value=code;o.textContent=code+' · '+title;el('region').append(o);});el('context-target').value=folders[0];
function loadContext(){const c=data.rows.find(r=>r.source_root===el('context-target').value).capture_context;el('locality').value=c.location||'';el('region').value=c.region_code||'';el('enabled').checked=!!c.region_code;el('use-date').checked=c.use_date!==false;el('capture-date').value='';}
function applyContext(reset=false){try{const date=el('capture-date').value;if(date&&!BirdContext.validDate(date))throw Error('日期无效');data.rows.forEach((row,i)=>{if(row.source_root!==el('context-target').value)return;const old=originalContexts[i];row.capture_context={...row.capture_context,location:el('locality').value.trim()||null,region_code:reset?null:(el('enabled').checked?el('region').value||null:null),date:reset?old.date:date||old.date,date_source:date&&!reset?'页面手动覆盖':old.date_source,use_date:!reset&&el('use-date').checked};rankRow(i);renderedRows.delete(i);renderContext(i);});renderGroups();el('message').textContent='已更新选定目录，人工确认保持。';}catch(e){el('message').textContent='无法调整：'+e.message;}}
data.rows.forEach((row,i)=>{el('cover-'+i).addEventListener('click',()=>{const g=groups.find(g=>g.indices.includes(i)),members=new Set(g.indices.map(j=>data.rows[j].path));prefs.covers=prefs.covers.filter(p=>!members.has(p));prefs.covers.push(row.path);savePrefs();renderGroups();});el('keep-'+i).addEventListener('click',()=>{prefs.keep=prefs.keep.includes(row.path)?prefs.keep.filter(p=>p!==row.path):[...prefs.keep,row.path];savePrefs();renderGroups();});el('undo-photo-'+i).addEventListener('click',undoAction);el('next-photo-'+i).addEventListener('click',()=>quick.active?moveQuick(1):startQuick(i));});
el('context-target').addEventListener('change',loadContext);el('apply').addEventListener('click',()=>applyContext());el('reset').addEventListener('click',()=>{el('region').value='';el('capture-date').value='';el('enabled').checked=false;applyContext(true);});
el('export').addEventListener('click',()=>download({schema:'bird-collection-context-v1',samples:data.rows.map((r,i)=>({path:r.path,source_root:r.source_root,source_sha256:r.before.sha256,truth:r.truth,manual_review:manual.get(i),capture_context:r.capture_context}))},'bird-collection-context.json'));
el('apply-view').addEventListener('click',applyView);for(const id of ['group-bursts','fold-similar'])el(id).addEventListener('change',applyView);for(const id of ['folder-filter','review-filter'])el(id).addEventListener('change',renderGroups);el('library-search').addEventListener('input',renderGroups);
el('reset-view').addEventListener('click',()=>{prefs={...defaults,breaks:[],keep:[],covers:[]};showAll.clear();syncPrefs();savePrefs();renderGroups();});el('export-view').addEventListener('click',()=>download(prefsDocument(),'bird-view-settings.json'));
el('import-view').addEventListener('change',async event=>{pendingView=null;el('apply-view-import').disabled=true;const file=event.target.files[0];if(!file)return;try{if(file.size>2*1024*1024)throw Error('文件超过 2 MiB');pendingView=BirdGrouping.validatePreferences(JSON.parse(await file.text()),data);el('apply-view-import').disabled=false;el('view-message').textContent='设置有效，点击应用恢复。';}catch(e){el('view-message').textContent='未导入：'+e.message;}event.target.value='';});el('apply-view-import').addEventListener('click',()=>{if(!pendingView)return;prefs=pendingView;pendingView=null;el('apply-view-import').disabled=true;showAll.clear();syncPrefs();savePrefs();renderGroups();});
el('start-quick').addEventListener('click',()=>startQuick());el('refresh-groups').addEventListener('click',renderGroups);el('undo-review').addEventListener('click',undoAction);el('quick-undo').addEventListener('click',undoAction);el('quick-prev').addEventListener('click',()=>moveQuick(-1));el('quick-next').addEventListener('click',()=>moveQuick(1));el('exit-quick').addEventListener('click',()=>exitQuick());
for(const [id,state] of [['quick-no-bird','no_bird'],['quick-uncertain','uncertain']])el(id).addEventListener('click',()=>{if(quick.active)manual.setStatus(quick.queue[quick.position],state);});
window.addEventListener('keydown',event=>{if(!quick.active||event.repeat||event.ctrlKey||event.altKey||event.metaKey||event.shiftKey||['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName?.toUpperCase())||event.target?.isContentEditable)return;const key=event.key.toLowerCase(),i=quick.queue[quick.position];if(/^[1-5]$/.test(key)){const id=candidateIds(i)[Number(key)-1];if(id){event.preventDefault();manual.confirmOne(i,id);}}else if(key==='0'||key==='u'){event.preventDefault();manual.setStatus(i,key==='0'?'no_bird':'uncertain');}else if(key==='arrowright'||key==='arrowleft'){event.preventDefault();moveQuick(key==='arrowright'?1:-1);}else if(key==='z'){event.preventDefault();undoAction();}});
window.addEventListener('beforeunload',event=>{if(!viewPersisted&&(prefs.keep.length||prefs.breaks.length||prefs.covers.length)){event.preventDefault();event.returnValue='';}});
syncPrefs();loadContext();data.rows.forEach((_,i)=>renderContext(i));ready=true;renderGroups();if(data.migration_warning)el('view-message').textContent=data.migration_warning;
})();
