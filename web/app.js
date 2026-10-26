'use strict';
(() => {
const $=id=>document.getElementById(id),state={token:null,labels:new Map(),summary:null,offset:0,limit:24,total:0,groups:[],photos:new Map(),mounts:new Map(),undo:[],busy:false,quick:{active:false,ids:[],at:0},importToken:null,species:'',selectedFolders:new Set(),folderParent:'',locations:null};
const statusNames={unreviewed:'尚未复核',confirmed:'人工确认',uncertain:'暂不确定',none_match:'候选都不对',no_bird:'无鸟 · 已剔除'};
function node(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
function button(text,fn,cls){const b=node('button',text,cls);b.type='button';b.addEventListener('click',()=>Promise.resolve(fn()).catch(error));return b;}
function message(text,bad=false){$('notice').textContent=text;$('notice').className=bad?'error':'';}
function error(err){message(err.message||String(err),true);}
async function request(path,body){const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Bird-Token':state.token},body:JSON.stringify(body)};const response=await fetch(path,options);const data=await response.json();if(!response.ok)throw Error(data.error||'请求失败');return data;}
function name(id){return state.labels.get(id)?.name||id||'待复核';}
function candidates(photo){return photo.candidates.filter(c=>c.label.kind==='bird').slice(0,5).map(c=>c.label.scientific_name);}
function filters(){return {root:$('folder').value,state:$('state').value||'all',q:$('search').value.trim(),region:$('region').value.trim(),from:$('date-from').value,to:$('date-to').value,species:state.species,...(window.BirdStudio?.filters()||{})};}
function query(extra={}){return new URLSearchParams({...filters(),...extra}).toString();}
async function updateSummary(initial=false){
 const info=await request('/api/state');state.token=info.token;state.summary=info;
 $('stats').replaceChildren(...[['照片',info.photos],['已确认',info.counts.confirmed||0],['待复核',info.pending],['已确认鸟种',info.species.length],['无鸟已剔除',info.counts.no_bird||0]].map(([title,value])=>{const n=node('div',undefined,'stat');n.append(node('strong',String(value)),node('span',title));return n;}));
 $('species-list').replaceChildren(...info.species.map(s=>button(s.name+' · '+s.count,()=>{state.species=s.id;$('search').value='';state.offset=0;return refresh();})));
 $('catalog-note').textContent='鸟种名称优先对应记录中心郑四版，旧名可搜索。无法明确对应的名称标注待核对。';
 if(initial){
  const cap=info.max_files_per_job??10;$('task-limit').max=cap===0?'':String(cap);$('task-limit').min=cap===0?'0':'1';$('task-limit').value=cap===0?'0':String(Math.min(10,cap));
  for(const root of info.roots)for(const id of ['folder','task-root']){const o=node('option',root.name);o.value=root.id;$(id).append(o);}
  $('gap').value=String(info.view.gap);$('grouping').checked=info.view.grouping;$('fold').checked=info.view.foldSimilar;loadContext();
 }
}
function cache(photos){for(const p of photos)state.photos.set(p.id,p);}
async function getPhotos(ids){const result=await request('/api/photos?ids='+ids.join(','));cache(result.items);return ids.map(id=>state.photos.get(id)).filter(Boolean);}
function syncRecord(records){
 for(const record of records){const p=state.photos.get(record.photo_id);if(p)p.manual={...p.manual,...record,stale:!!(record.reviewed_sha&&p.sha256&&record.reviewed_sha!==p.sha256)};
  for(const group of state.groups){const member=group.members.find(m=>m.id===record.photo_id);if(member){const previous=member.status;member.revision=record.revision;member.status=record.status;if(previous==='unreviewed'&&record.status!=='unreviewed')group.unreviewed--;if(previous!=='unreviewed'&&record.status==='unreviewed')group.unreviewed++;group.renderBar?.();}}
  for(const mount of state.mounts.get(record.photo_id)||[])mount();
  if(state.quick.active&&state.quick.ids[state.quick.at]===record.photo_id){state.quick.render?.();$('quick-progress').textContent=(state.quick.at+1)+' / '+state.quick.ids.length+' · '+statusNames[record.status];}
 }
}
function undoButtons(){$('undo').disabled=!state.undo.length;}
async function save(photo,status,ids,advance=false){
 if(state.busy)return;state.busy=true;
 try{
  const result=await request('/api/review',{items:[{id:photo.id,revision:photo.manual.revision}],status,species:ids});syncRecord(result.records);state.undo.push({id:result.change_id,photos:[photo.id]});undoButtons();message('已保存到图库。');await updateSummary();
  if(advance&&state.quick.active&&state.quick.ids[state.quick.at]===photo.id&&$('auto-next').checked)await moveQuick(1);
 }catch(err){error(err);}finally{state.busy=false;}
}
async function undo(){
 if(state.busy||!state.undo.length)return;state.busy=true;
 try{const change=state.undo.at(-1),result=await request('/api/undo',{change_id:change.id});state.undo.pop();syncRecord(result.records);undoButtons();await updateSummary();if(state.quick.active){const at=state.quick.ids.indexOf(change.photos[0]);if(at>=0){state.quick.at=at;await showQuick();}}message('已撤销刚才 '+result.count+' 张操作。');}catch(err){error(err);}finally{state.busy=false;}
}
function photoCard(photo){
 const card=node('section',undefined,'photo');card.setAttribute('tabindex','-1');const heading=node('h3',photo.path);card.append(heading);
 if(photo.source_status==='missing')card.append(node('p','原路径已失效，确认记录仍保留。请先恢复原路径后增量扫描；本版不会自动重连文件。','warning'));
 if(photo.error)card.append(node('p','处理提示：'+photo.error,'warning'));
 if(photo.manual.stale)card.append(node('p','源文件内容已变化，旧人工确认保留，请重新核对。','warning'));
 card.append(button('打开原图 / 框选与调整',()=>window.BirdEditor.open(photo.id,{api:request,token:()=>state.token,name,birds:()=>[...state.labels.values()],onChanged:async(id,result)=>{await getPhotos([id]);for(const mount of state.mounts.get(id)||[])mount();if(result){syncRecord(result.records);state.undo.push({id:result.change_id,photos:[id]});undoButtons();}await updateSummary();}})));
 const layout=node('div',undefined,'photo-layout'),figure=node('div'),actions=node('div');
 if(photo.thumbnail){const img=node('img',undefined,'photo-image');img.src=photo.thumbnail;img.alt='主体或整图缩略图';img.loading='lazy';figure.append(img);}else figure.append(node('p','尚无缩略图，等待处理。','empty'));
 figure.append(node('small',(photo.context.location||'地点未设置')+' · '+(photo.date||'日期未知')),node('small',photo.detection.message||'主体尚未定位'));
 const selected=node('div',undefined,'status'),choices=node('div',undefined,'candidates');actions.append(selected,choices);
 function render(){
  photo=state.photos.get(photo.id)||photo;
  selected.replaceChildren(node('strong',statusNames[photo.manual.status]));
  for(const id of photo.manual.species)selected.append(button(name(id)+' ×',()=>{const ids=photo.manual.species.filter(s=>s!==id);return save(photo,ids.length?'confirmed':'unreviewed',ids);},'chip'));
  choices.replaceChildren(...candidates(photo).map((id,i)=>{const label=state.labels.get(id),b=button((i+1)+'  '+name(id)+(label?.catalog_status!=='exact_scientific_name'?' · 名录待核对':''),()=>save(photo,'confirmed',[id],true),photo.manual.species.includes(id)?'selected':'');b.setAttribute('aria-pressed',String(photo.manual.species.includes(id)));return b;}));
 }
 render();if(state.quick.active)state.quick.render=render;else state.mounts.set(photo.id,[render]);
 const statuses=node('div',undefined,'actions');for(const [title,status] of [['无鸟，剔除','no_bird'],['暂不确定','uncertain'],['候选都不对','none_match'],['清除／恢复','unreviewed']])statuses.append(button(title,()=>save(photo,status,[],['no_bird','uncertain'].includes(status))));statuses.append(button('撤销刚才',undo));actions.append(statuses);
 const search=node('details'),input=node('input'),multi=node('input'),multiLabel=node('label');input.type='text';input.placeholder='输入汉字、拼音或首字母，直接点选候选';multi.type='checkbox';multiLabel.append(multi,node('span','追加为同图另一鸟种'));search.append(node('summary','搜索其他鸟种 / 同图多鸟'),input,multiLabel);
 window.BirdSearch.bind(input,search,()=>[...state.labels.values()],label=>save(photo,'confirmed',multi.checked?[...new Set([...photo.manual.species,label.id])]:[label.id],!multi.checked));actions.append(search);layout.append(figure,actions);card.append(layout);
 const evidence=node('details'),list=node('div',undefined,'candidate-evidence');evidence.append(node('summary','候选依据与拍摄信息'),list);list.append(node('p','模型分数不是正确概率。日期来源：'+(photo.context.date_source||'未知')));
 for(const [title,items] of [['纯视觉',photo.visual_candidates],['地区与日期辅助',photo.candidates]])list.append(node('p',title+'：'+items.map(c=>name(c.label.scientific_name||c.label.prompt)+' '+Number(c.ranking_score??c.score??c.visual_score).toFixed(4)).join('；')));
 if(photo.context.warnings?.length)list.append(node('p',photo.context.warnings.join('；')));card.append(evidence);
 const keep=node('details');keep.append(node('summary','封面与相似折叠设置'),button('保留此图 / 恢复自动折叠',()=>setPhotoPreference(photo.id,'keep')),button('设为本组封面',()=>setPhotoPreference(photo.id,'covers')));card.append(keep);return card;
}
async function setPhotoPreference(id,key){
 const prefs=structuredClone(state.summary.view);
 if(key==='covers'){const g=state.groups.find(g=>g.ids.includes(id));if(g)prefs.covers=prefs.covers.filter(i=>!g.ids.includes(i));prefs.covers.push(id);}else prefs.keep=prefs.keep.includes(id)?prefs.keep.filter(i=>i!==id):[...prefs.keep,id];
 await request('/api/view',prefs);await updateSummary();message('设置已保存，点击“更新筛选与分组”查看结果。');
}
function groupCard(group){
 const details=node('details',undefined,'group'),summary=node('summary'),text=node('div',undefined,'group-title');
 if(group.cover.thumbnail){const img=node('img',undefined,'cover');img.src=group.cover.thumbnail;img.alt='本组封面';img.loading='lazy';summary.append(img);}text.append(node('strong',name(group.species)+' · '+group.count+' 张'),node('small',(group.confirmed?'人工已确认':'含待复核判断')+' · '+group.cover.path),node('small','相似折叠 '+group.folded.length+' 张'));summary.append(text);details.append(summary);
 const toolbar=node('div',undefined,'group-bar'),select=node('input'),status=node('small'),content=node('div');let loaded=0,all=false;
 select.type='text';select.placeholder='输入鸟种汉字、拼音或首字母';select.className='autocomplete-input';select.birdId=group.species||candidates(group.cover)[0]||'';select.value=name(select.birdId);window.BirdSearch.bind(select,toolbar,()=>[...state.labels.values()],l=>{select.birdId=l.id;},()=>{select.birdId='';});
 const apply=button('确认本组未复核',async()=>{
  if(state.busy)return;if(!select.birdId)throw Error('请从即时提示中选择鸟种');state.busy=true;
  try{const before=group.unreviewed,result=await request('/api/review',{items:group.members,status:'confirmed',species:[select.birdId],only_unreviewed:true});syncRecord(result.records);group.unreviewed=Math.max(0,before-result.count);state.undo.push({id:result.change_id,photos:result.records.map(r=>r.photo_id)});undoButtons();group.renderBar();await updateSummary();message('已就地确认 '+result.count+' 张，照片位置保持。');}finally{state.busy=false;}
 },'primary');
 group.renderBar=()=>{apply.textContent='确认本组未复核 '+group.unreviewed+' 张';apply.disabled=group.unreviewed===0;status.textContent='只写未复核成员，已有确认、不确定和无鸟记录保持。';};group.renderBar();toolbar.append(select,apply,button('撤销刚才',undo),status);details.append(toolbar);
 async function loadMore(reset=false){
  if(reset){loaded=0;content.replaceChildren();}
  const hidden=new Set(group.folded.map(f=>f.id)),ids=all?group.ids:group.ids.filter(i=>!hidden.has(i));const photos=await getPhotos(ids.slice(loaded,loaded+50));photos.forEach(p=>content.append(photoCard(p)));loaded+=photos.length;more.hidden=loaded>=ids.length;
 }
 const controls=node('div',undefined,'actions'),more=button('继续显示本组照片',()=>loadMore());controls.append(button('显示本组全部 '+group.count+' 张',async()=>{all=true;await loadMore(true);}),button('拆开本组',async()=>{const prefs=structuredClone(state.summary.view);prefs.breaks=[...new Set([...prefs.breaks,...group.ids.slice(1)])];await request('/api/view',prefs);await updateSummary();message('已保存拆组设置，点击“更新筛选与分组”查看。');}));details.append(controls,content,more);
 details.addEventListener('toggle',()=>{if(details.open&&!loaded)loadMore().catch(error);});return details;
}
async function refresh(){
 if(window.BirdStudio?.active())return window.BirdStudio.refresh();
 if(state.quick.active)exitQuick(false);const result=await request('/api/library?'+query({offset:state.offset,limit:state.limit}));state.total=result.total;state.groups=result.mode==='groups'?result.items:[];state.mounts.clear();$('gallery').replaceChildren();
 if(!result.items.length)$('gallery').append(node('p','没有匹配照片，可调整目录、状态或日期。','empty'));
 if(result.mode==='groups'){cache(result.items.map(g=>g.cover));result.items.forEach(g=>$('gallery').append(groupCard(g)));}else{cache(result.items);result.items.forEach(p=>$('gallery').append(photoCard(p)));}
 $('list-summary').textContent='匹配 '+result.matched_photos+' 张 · '+result.total+(result.mode==='groups'?' 组':' 张');$('page-info').textContent=(Math.floor(state.offset/state.limit)+1)+' / '+Math.max(1,Math.ceil(state.total/state.limit));$('prev-page').disabled=state.offset===0;$('next-page').disabled=state.offset+state.limit>=state.total;$('export-csv').href='/api/export/csv?'+query();
}
async function startQuick(){if(state.busy)return;window.BirdStudio?.hide();const result=await request('/api/queue?'+query());if(!result.ids.length){message('当前筛选没有待复核照片。');return;}state.quick={active:true,ids:result.ids,at:0};$('quick').hidden=false;$('gallery').hidden=true;$('pagination').hidden=true;await showQuick();$('quick').scrollIntoView({block:'start'});}
async function showQuick(){
 const sequence=state.quick.sequence=(state.quick.sequence||0)+1,id=state.quick.ids[state.quick.at],photos=await getPhotos([id]);if(!state.quick.active||sequence!==state.quick.sequence)return;if(!photos.length)throw Error('照片不存在');$('quick-photo').replaceChildren(photoCard(photos[0]));$('quick-progress').textContent=(state.quick.at+1)+' / '+state.quick.ids.length+' · '+statusNames[photos[0].manual.status];$('prev-quick').disabled=state.quick.at===0;$('next-quick').disabled=state.quick.at===state.quick.ids.length-1;$('quick-photo').children[0].focus({preventScroll:true});
}
async function moveQuick(delta){if(!state.quick.active)return;const next=state.quick.at+delta;if(next<0)return;if(next>=state.quick.ids.length){message('本轮已到最后一张，可返回图库或撤销。');return;}state.quick.at=next;await showQuick();}
function exitQuick(reload=true){state.quick.active=false;$('quick').hidden=true;$('gallery').hidden=false;$('pagination').hidden=false;if(reload)return refresh();}
async function loadJobs(){
 if(window.BirdProgress)return window.BirdProgress.refresh();
 const result=await request('/api/jobs');renderJobs(result);return result;
}
function renderJobs(result){
 const jobs=$('jobs'),scrollTop=jobs.scrollTop;
 const titles={queued:'等待开始',discovering:'正在检查目录',running:'正在处理',paused:'已暂停',completed:'已完成',failed:'有失败项',cancelled:'已取消'};
 jobs.replaceChildren(...result.items.map(job=>{const box=node('div',undefined,'job'),root=state.summary.roots.find(r=>r.id===job.root_id);box.append(node('strong',(root?.name||job.root_id)+' · '+titles[job.state]),node('p','发现 '+job.found+' · 已处理 '+(job.counts.done||0)+' · 跳过 '+(job.counts.skipped||0)+' · 失败 '+(job.counts.error||0)+' · 待处理 '+((job.counts.pending||0)+(job.counts.running||0))));const report=node('a','下载此任务报告','button');report.href='/api/acceptance?job='+encodeURIComponent(job.id);box.append(report);if(job.error)box.append(node('small',job.error));for(const [title,action] of (['queued','discovering','running'].includes(job.state)?[['暂停','pause'],['取消','cancel']]:job.state==='paused'?[['继续','resume'],['取消','cancel']]:job.state==='failed'?[['重试失败项','retry'],['继续待处理','resume']]:job.state==='cancelled'?[['继续剩余','resume']]:[]))box.append(button(title,async()=>{await request('/api/job-action',{id:job.id,action});await loadJobs();}));return box;}));
 jobs.scrollTop=scrollTop;
}
async function previewScan(){
 if(state.scanBusy)return;
 if(!state.selectedFolders.size)throw Error('请先勾选一个要检查的文件夹');
 const raw=$('task-limit').value.trim(),limit=Number(raw);
 if(!/^\d+$/.test(raw)||!Number.isSafeInteger(limit))throw Error('处理张数须为非负整数；0 表示不设上限');
 state.scanBusy=true;$('start-job').disabled=true;
 try{
  message('正在检查所选目录的文件名、大小和修改时间，尚未开始识别…');
  const result=await request('/api/scan-preview',{root_id:$('task-root').value,scopes:[...state.selectedFolders],limit});
  showScanPlan(result);message('变更检查完成，请核对清单后确认处理。未变化照片不会重新识别。');
 }finally{state.scanBusy=false;$('start-job').disabled=false;}
}
function showScanPlan(plan){
 const dialog=$('scan-dialog'),c=plan.counts;
 dialog.replaceChildren(node('h3','确认目录变更'),node('p',plan.scopes.join('、')),node('p',`新增 ${c.new} · 更新 ${c.updated} · 待重试 ${c.retry} · 未变化跳过 ${c.unchanged} · 不可用 ${c.unavailable}`),node('small',plan.notice));
 if(plan.errors.length)dialog.append(node('p','目录检查不完整：'+plan.errors.join('；'),'warning'));
 if(plan.missing.length){const details=node('details');details.append(node('summary',`已有索引但本次未找到 ${plan.missing.length} 张（检查错误时也可能不可见，不删除索引）`));for(const row of plan.missing)details.append(node('p','#'+row.photo_id+' · '+row.path));dialog.append(details);}
 const chosen=new Set(plan.items.filter((_,i)=>!plan.limit||i<plan.limit).map(p=>p.path));
 const controls=node('div',undefined,'actions'),info=node('strong'),list=node('div',undefined,'scan-files'),pager=node('div',undefined,'actions');let page=0;
 const confirm=button('确认处理',async()=>{
  if(!chosen.size)throw Error('请先勾选需要处理的变更文件');if(state.scanBusy)return;
  state.scanBusy=true;confirm.disabled=true;
  try{const r=await request('/api/scan-confirm',{preview_token:plan.preview_token,paths:[...chosen]});dialog.close();await loadJobs();message('已确认处理 '+r.confirmed+' 张；未勾选及未变化照片不处理。');}
  finally{state.scanBusy=false;confirm.disabled=false;}
 },'primary');confirm.id='scan-confirm';
 function status(){info.textContent='已勾选 '+chosen.size+' / '+plan.items.length+' 张'+(plan.limit?'；本次上限 '+plan.limit:'；不限张数');confirm.disabled=!chosen.size;}
 function render(){
  list.replaceChildren();
  for(const [i,p] of plan.items.slice(page*100,page*100+100).entries()){
   const row=node('label',undefined,'scan-file'),check=node('input');check.type='checkbox';check.checked=chosen.has(p.path);
   check.addEventListener('change',()=>{if(check.checked&&plan.limit&&chosen.size>=plan.limit){check.checked=false;message('已达到本次上限；可取消其他勾选或重新检查时调整上限。',true);return;}check.checked?chosen.add(p.path):chosen.delete(p.path);status();});
   row.append(check,node('span',`${page*100+i+1}. ${p.photo_id?'#'+p.photo_id:'新文件'} · ${{new:'新增',updated:'文件已更新',retry:'未完成/失败，需重试'}[p.reason]} · ${p.path}`));list.append(row);
  }
  pager.replaceChildren(button('上一页',()=>{page=Math.max(0,page-1);render();}),node('span',(page+1)+' / '+Math.max(1,Math.ceil(plan.items.length/100))),button('下一页',()=>{page=Math.min(Math.max(0,Math.ceil(plan.items.length/100)-1),page+1);render();}));status();
 }
 controls.append(button('全选变更（按本次上限）',()=>{chosen.clear();for(const p of plan.items.slice(0,plan.limit||plan.items.length))chosen.add(p.path);render();}),button('清空勾选',()=>{chosen.clear();render();}),info);
 dialog.append(controls,list,pager,button('取消，不开始处理',()=>dialog.close()),confirm);render();dialog.showModal();
}

function showFolderSelection(){$('folder-selection').textContent=state.selectedFolders.size?'已勾选 '+state.selectedFolders.size+' 项：'+[...state.selectedFolders].map(s=>s==='.'?'根目录文件（不递归）':s).join('、'):'尚未勾选目录，不会开始扫描';}
async function browseFolders(parent='',offset=0){
 const root=$('task-root').value;if(!root)return;const result=await request('/api/folders?'+new URLSearchParams({root,parent,offset,sort:$('folder-sort').value||'date_desc'}));state.folderParent=parent;$('task-scope').value=parent;$('context-scope').value=parent;loadFolderContext().catch(error);$('folder-current').textContent=parent||'根目录';if(!offset)$('folder-list').replaceChildren();
 const rows=[...(result.root_files_option&&offset===0?[{name:'根目录中的照片文件（不进入子文件夹）',path:'.'}]:[]),...result.items];
 for(const item of rows){const row=node('div',undefined,'folder-row'),label=node('label'),check=node('input');check.type='checkbox';check.checked=state.selectedFolders.has(item.path);check.addEventListener('change',()=>{if(check.checked){for(const s of state.selectedFolders)if(s!=='.'&&item.path!=='.'&&(s.startsWith(item.path+'/')||item.path.startsWith(s+'/')))state.selectedFolders.delete(s);state.selectedFolders.add(item.path);}else state.selectedFolders.delete(item.path);showFolderSelection();});label.append(check,node('span',item.name+(item.path==='.'?'':'（含子目录）')));row.append(label);if(item.indexed)row.append(node('small','已扫描 '+item.ready+' / 已索引 '+item.indexed+' 张','folder-scanned'));if(item.path!=='.')row.append(button('展开',()=>browseFolders(item.path)));$('folder-list').append(row);}
 if(result.next_offset!==null)$('folder-list').append(button('显示更多目录',()=>browseFolders(parent,result.next_offset)));showFolderSelection();
}
async function loadFolderContext(){const root=$('task-root').value,scope=$('context-scope').value.trim();if(!root)return;const result=await request('/api/folder-context?'+new URLSearchParams({root,scope}));if(root!==$('task-root').value||scope!==$('context-scope').value.trim())return;const c=result.context;$('context-location').value=c.location||'';$('context-region').regionCode=c.region_code||'';$('context-region').value=state.locations.regions.find(r=>r.kind==='region'&&r.region_code===c.region_code)?.name||'';$('context-date').value=c.date||'';$('context-season').checked=c.use_date!==false;}
function loadContext(){const root=state.summary.roots.find(r=>r.id===$('task-root').value);if(!root)return;const c=root.context;$('context-location').value=c.location||'';$('context-region').regionCode=c.region_code||'';$('context-region').value=state.locations?.regions.find(r=>r.kind==='region'&&r.region_code===c.region_code)?.name||c.region_code||'';$('context-date').value=c.date||'';$('context-season').checked=c.use_date!==false;}
function event(id,type,fn){$(id).addEventListener(type,()=>Promise.resolve(fn()).catch(error));}
async function main(){
 const labels=await request('/api/labels');state.labels=new Map(labels.items.map(l=>[l.id,l]));state.locations=await request('/api/locations');await updateSummary(true);window.BirdProgress?.init({api:request,onJobs:renderJobs,error});window.BirdStudio?.init({api:request,token:()=>state.token,name,birds:()=>[...state.labels.values()],filters,save,getPhotos,summary:updateSummary,message,error});await refresh();await loadJobs();message('已连接本机图库，人工记录自动保存到数据库。');
 event('refresh','click',()=>{state.offset=0;return refresh();});for(const id of ['folder','state'])event(id,'change',()=>{state.offset=0;return refresh();});event('clear-filter','click',()=>{for(const id of ['folder','search','region','date-from','date-to'])$(id).value='';$('state').value='all';state.species='';state.offset=0;return refresh();});
 event('prev-page','click',()=>{state.offset=Math.max(0,state.offset-state.limit);return refresh();});event('next-page','click',()=>{state.offset+=state.limit;return refresh();});event('start-quick','click',startQuick);event('close-quick','click',exitQuick);event('prev-quick','click',()=>moveQuick(-1));event('next-quick','click',()=>moveQuick(1));event('undo','click',undo);
 event('backup','click',async()=>{const result=await request('/api/backup',{});message('数据库备份已保存：'+result.name);const a=node('a','下载这份备份','button');a.href=result.url;$('notice').append(a);});
 event('import-file','change',async()=>{state.importToken=null;$('apply-import').disabled=true;const file=$('import-file').files[0];if(!file)return;if(file.size>8*1024*1024)throw Error('复核备份超过 8 MiB');const result=await request('/api/import-preview',JSON.parse(await file.text()));state.importToken=result.preview_token;$('import-info').textContent='有效记录 '+result.count+' 张。'+result.notice;$('apply-import').disabled=false;});
 event('apply-import','click',async()=>{if(!state.importToken)return;const result=await request('/api/import-apply',{preview_token:state.importToken});state.importToken=null;$('apply-import').disabled=true;state.undo.push({id:result.change_id,photos:[]});undoButtons();await updateSummary();await refresh();message('已导入 '+result.count+' 张，操作前数据库已备份。');});
 event('save-view','click',async()=>{const prefs={...state.summary.view,gap:Number($('gap').value),grouping:$('grouping').checked,foldSimilar:$('fold').checked};await request('/api/view',prefs);await updateSummary();await refresh();message('浏览设置已保存。');});event('reset-view','click',async()=>{await request('/api/view',{gap:30,grouping:true,foldSimilar:true,breaks:[],keep:[],covers:[]});await updateSummary();$('gap').value='30';$('grouping').checked=true;$('fold').checked=true;await refresh();});
 event('toggle-tasks','click',()=>{$('tasks-panel').open=!$('tasks-panel').open;});event('task-root','change',()=>{state.selectedFolders.clear();state.folderParent='';$('task-scope').value='';$('context-scope').value='';$('folder-list').replaceChildren();showFolderSelection();loadContext();});event('start-job','click',previewScan);
 event('folder-sort','change',()=>browseFolders(state.folderParent));
 event('save-context','click',async()=>{const result=await request('/api/context',{root_id:$('task-root').value,scope:$('context-scope').value.trim(),context:{location:$('context-location').value.trim()||null,region_code:$('context-region').regionCode||null,date:$('context-date').value||null,use_date:$('context-season').checked}});state.locations=await request('/api/locations');await updateSummary();await refresh();message('已更新 '+result.updated+' 张的拍摄背景与候选，人工确认保持。');});
 event('context-scope','change',loadFolderContext);event('browse-folders','click',()=>browseFolders($('task-scope').value.trim()));event('folder-up','click',()=>browseFolders(state.folderParent.split('/').slice(0,-1).join('/')));event('clear-folders','click',()=>{state.selectedFolders.clear();showFolderSelection();return browseFolders(state.folderParent);});
 window.BirdSearch.bind($('search'),$('search').parentNode,()=>[...state.labels.values()],l=>{state.species=l.id;state.offset=0;refresh().catch(error);},()=>{state.species='';});
 const places=()=>[...state.locations.regions.filter(r=>r.kind==='known'),...state.locations.places];
 window.BirdSearch.bind($('context-location'),$('context-location').parentNode,places,l=>{$('context-region').regionCode=l.region_code||'';$('context-region').value=state.locations.regions.find(r=>r.kind==='region'&&r.region_code===l.region_code)?.name||'';},()=>{$('context-region').regionCode='';$('context-region').value='';});
 window.BirdSearch.bind($('context-region'),$('context-region').parentNode,()=>state.locations.regions.filter(r=>r.kind==='region'),l=>{$('context-region').regionCode=l.region_code;},()=>{$('context-region').regionCode='';});
 window.BirdSearch.bind($('region'),$('region').parentNode,places,()=>{state.offset=0;refresh().catch(error);});
 document.addEventListener('keydown',event=>{if(window.BirdEditor?.isOpen()||!state.quick.active||state.busy||event.repeat||event.ctrlKey||event.altKey||event.metaKey||event.shiftKey||['INPUT','SELECT','TEXTAREA'].includes(event.target?.tagName)||event.target?.isContentEditable)return;const key=event.key.toLowerCase(),photo=state.photos.get(state.quick.ids[state.quick.at]);let action;
 if(/^[1-5]$/.test(key)){const id=candidates(photo)[Number(key)-1];if(id)action=()=>save(photo,'confirmed',[id],true);}else if(key==='0'||key==='u')action=()=>save(photo,key==='0'?'no_bird':'uncertain',[],true);else if(key==='z')action=undo;else if(key==='arrowleft'||key==='arrowright')action=()=>moveQuick(key==='arrowleft'?-1:1);
 if(action){event.preventDefault();Promise.resolve(action()).catch(error);}});
 if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>document.documentElement.style.setProperty('--bar-height',$('review-bar').offsetHeight+'px')).observe($('review-bar'));
 // BirdProgress owns the single shared job poller (including the editor).
}
window.BirdIndexApp={state,ready:main().catch(error),refresh,save,startQuick,undo};
})();
