'use strict';
(() => {
const $=id=>document.getElementById(id),S={enabled:true,items:[],at:0,offset:0,total:0,selected:new Set(),busy:false,seq:0,blob:null,options:null,bird:'',folderCatalog:null,groups:[],expanded:new Set(),anchor:null};
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const btn=(text,fn,cls)=>{const b=el('button',text,cls);b.type='button';b.onclick=(event={})=>Promise.resolve().then(()=>fn(event)).catch(S.options.error);return b;};
function select(id,title,values){const l=el('label',title),s=el('select');s.id=id;for(const [value,text] of values){const o=el('option',text);o.value=value;s.append(o);}l.append(s);return l;}
function field(id,title,type='text'){const l=el('label',title),n=el('input');n.id=id;n.type=type;l.append(n);return l;}
function filters(){if(!$('s-flag'))return {};return {flag:$('s-flag').value,rating:$('s-rating').value,min_score:$('s-min').value,max_score:$('s-max').value,quality:$('s-quality').value,sort:$('s-sort').value,storage:$('s-storage').value,visibility:$('s-visibility').value||'visible',state:($('state')?.value==='all'||!$('state')?.value?'any':$('state').value),...directoryFilter(),...(S.enabled?{species:S.bird}:{}),...($('s-storage').value==='quarantined'?{state:'any'}:{})};}
function directoryFilter(){const value=$('s-directory')?.value;return value?JSON.parse(value):{subfolder:''};}
async function loadDirectories(){
 const result=await S.options.api('/api/library-folders'),s=$('s-directory'),previous=s.value;
 s.replaceChildren();const all=el('option','全部已索引目录');all.value='';s.append(all);
 for(const row of result.items){const o=el('option',row.root_name+' / '+(row.path==='.'?'根层文件':row.path)+' · '+row.count+' 张');o.value=JSON.stringify({root:row.root_id,subfolder:row.path});s.append(o);}
 s.value=previous;S.folderCatalog=result.items;
}
function birdTitle(p){
 if(p.manual.status==='confirmed'&&p.manual.species.length)return '已确认：'+p.manual.species.map(S.options.name).join('、')+(p.manual.stale?'（源文件变化，需核对）':'');
 if(p.manual.status==='no_bird')return '人工确认无鸟';
 const c=(p.candidates||[])[0],id=c?.label?.scientific_name;
 return (p.manual.status==='uncertain'?'暂不确定 · ':p.manual.status==='none_match'?'候选都不对 · ':'')+(c?.label?.kind==='bird'?'首选候选：'+S.options.name(id)+'（待确认）':'鸟种待确认');
}
function issueTitle(p){return p.quality?(p.quality.needs_review?(p.quality.issues||[]).join('；'):'未发现明显技术问题，仍需目视复核'):'尚未评分';}
function pictureSummary(){const p=current();if(p)$('s-caption').textContent=birdTitle(p)+' · '+issueTitle(p)+'\n'+p.relative_path+' · '+(p.date||'日期未知')+' · '+(p.context?.location||'地点未设置');}
const current=()=>S.items[S.at];
const selected=()=>S.items.filter(p=>S.selected.has(p.id));
function release(){S.seq++;if(S.blob)URL.revokeObjectURL(S.blob);S.blob=null;}
function hide(){document.body.classList.remove('studio-focus');S.enabled=false;release();$('studio').hidden=true;$('gallery').hidden=false;$('pagination').hidden=false;$('review-bar').hidden=false;}
async function show(){S.enabled=true;$('quick').hidden=true;if(window.BirdIndexApp)window.BirdIndexApp.state.quick.active=false;await refresh();}
function init(options){
 S.options=options;const root=$('studio');if(!root)return;
 const modes=el('div',undefined,'studio-switch');modes.append(btn('初筛工作台',show),el('small','空闲待机 · 2 分钟无操作或页面隐藏时停止任务轮询'));
 modes.append(btn('专注看图 / 展开目录与更多筛选',()=>document.body.classList.toggle('studio-focus')));document.body.classList.add('studio-focus');$('review-bar').before(modes);
 const directoryBar=el('div',undefined,'studio-directory');directoryBar.append(select('s-directory','初筛目录',[['','全部已索引目录']]));
 const birdLabel=field('s-bird-filter','筛选鸟种');directoryBar.append(birdLabel,btn('清除目录与鸟种',()=>{S.bird='';$('s-bird-filter').value='';$('s-directory').value='';$('folder').value='';S.offset=0;return refresh();}));const filterStatus=el('span');filterStatus.id='s-filter-status';directoryBar.append(filterStatus);root.append(directoryBar);
 $('s-directory').onchange=()=>{S.offset=0;refresh().catch(S.options.error);};
 $('s-bird-filter').placeholder='汉字 / 拼音，输入即列候选';
 window.BirdSearch.bind($('s-bird-filter'),birdLabel,options.birds,l=>{S.bird=l.id;S.offset=0;refresh().catch(S.options.error);},()=>{S.bird='';S.offset=0;refresh().catch(S.options.error);});
 const controls=el('div',undefined,'studio-filters');controls.append(select('s-flag','标记',[['','所有标记'],['keep','保留'],['reject','待剔除'],['none','未标记']]),select('s-rating','星级至少',[['','不限'],...[1,2,3,4,5].map(x=>[x,'★'.repeat(x)])]),field('s-min','参考分最低','number'),field('s-max','参考分最高','number'),select('s-quality','质量提示',[['','全部'],['issues','有待复核问题'],['unscored','尚未评分']]),select('s-sort','排序',[['','拍摄索引顺序'],['score','参考分从高到低']]),select('s-storage','原片位置',[['','原目录'],['quarantined','待删除 · 可恢复']]),select('s-visibility','显示范围',[['visible','未隐藏'],['hidden','仅隐藏'],['all','全部（含隐藏）']]));
 controls.append(btn('应用筛选',()=>{S.offset=0;return refresh();}),btn('清除初筛条件',()=>{for(const id of ['s-flag','s-rating','s-min','s-max','s-quality','s-sort','s-storage'])$(id).value='';$('s-visibility').value='visible';S.offset=0;return refresh();}));const filterDetails=el('details',undefined,'studio-filter-details');filterDetails.append(el('summary','筛选：标记、星级、参考分、隐藏与原片位置'),controls);root.append(filterDetails);
 const tools=el('div',undefined,'studio-tools'),all=el('input');all.type='checkbox';all.id='s-select-page';all.onchange=()=>{S.selected=all.checked?new Set(visiblePhotos().map(p=>p.id)):new Set();strip();};const allLabel=el('label');allLabel.append(all,el('span','全选显示的小图'));tools.append(allLabel,btn('勾选图标记保留',()=>markMany('keep')),btn('勾选图标记待剔除',()=>markMany('reject')),btn('勾选图清除标记',()=>markMany('none')),select('s-batch-rating','批量星级',Array.from({length:6},(_,i)=>[String(i),i?i+' 星':'无星'])),btn('应用星级',()=>rateMany()),btn('隐藏勾选图',()=>visibilityMany(true)),btn('恢复显示勾选图',()=>visibilityMany(false)),btn('仅评分勾选图',scoreMany),btn('批量移至待删除',()=>plan('move'),'danger'),btn('恢复勾选原片',()=>plan('restore')));const report=el('a','下载最近任务验证报告','button');report.href='/api/acceptance';tools.append(report,el('span','', 'studio-count'));root.append(tools);
 window.BirdValidation?.init({container:root,api:options.api,error:options.error,message:options.message,selected,repaint:()=>{side();strip();},view:validationView});
 const layout=el('div',undefined,'studio-layout'),stage=el('div',undefined,'studio-stage'),nav=el('div',undefined,'studio-nav');nav.append(btn('← 上一张',()=>move(-1)),el('strong',''),btn('下一张 →',()=>move(1)),btn('加载原图预览',original),btn('缩放 / 框选 / 调整',editor));nav.children[1].id='s-progress';stage.append(nav);
 const image=el('img');image.id='s-image';image.alt='当前照片（仅在你的浏览器显示）';stage.append(image);const caption=el('div');caption.id='s-caption';stage.append(caption);
 const right=el('aside',undefined,'studio-side');right.id='s-side';const shell=el('section',undefined,'studio-side-shell');shell.id='s-side-shell';shell.setAttribute('aria-label','照片初筛 · 标记与鸟种');shell.append(right);layout.append(stage,shell);root.append(layout);
 const film=el('div',undefined,'filmstrip');film.id='s-strip';film.setAttribute('aria-label','照片缩略图栏');film.addEventListener('wheel',e=>window.StudioStrip.wheel(e,film),{passive:false});root.append(film);
 const pages=el('div',undefined,'studio-pages');pages.append(btn('上一页',()=>{if(S.offset){S.offset=Math.max(0,S.offset-100);return refresh();}}),el('span'),btn('下一页',()=>{if(S.offset+100<S.total){S.offset+=100;return refresh();}}));pages.children[1].id='s-pages';root.append(pages,el('small','滚轮横移 · Ctrl 多选 · Shift 首尾范围选择（仅可见小图） · ← → 换图 · P 保留 · X 待剔除 · U 清除标记 · 1～5 星 · 0 清除星级。标记后留在当前位置；应用筛选才重排。缩略图可能是主体裁切，核对整图请主动加载原图。'));
 const dialog=el('dialog');dialog.id='s-dialog';dialog.setAttribute('aria-label','确认原片整理清单');document.body.append(dialog);
 document.addEventListener('keydown',e=>{
  if(!S.enabled||S.busy||window.BirdEditor?.isOpen()||dialog.open||e.repeat||e.ctrlKey||e.altKey||e.metaKey||e.shiftKey||['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.target?.tagName)||e.target?.isContentEditable)return;
  let action;const key=e.key.toLowerCase();if(key==='arrowleft'||key==='arrowright')action=()=>move(key==='arrowleft'?-1:1);else if('pxu'.includes(key)&&key.length===1)action=()=>mark(current(),{p:'keep',x:'reject',u:'none'}[key],null);else if(/^[0-5]$/.test(key))action=()=>mark(current(),null,Number(key));
  if(action){e.preventDefault();Promise.resolve(action()).catch(S.options.error);}
 });
}
async function refresh(){
 if(!S.enabled)return;const sequence=++S.seq;await loadDirectories();if(sequence!==S.seq)return;const result=await S.options.api('/api/library?'+new URLSearchParams({...S.options.filters(),mode:'photos',bursts:'1',offset:S.offset,limit:100}));if(sequence!==S.seq)return;if(S.offset>0&&S.offset>=result.total){S.offset=Math.max(0,Math.floor((result.total-1)/100)*100);return refresh();}
 const previous=current()?.id;S.items=result.items;S.groups=result.bursts||[];S.expanded=new Set([...S.expanded].filter(key=>S.groups.some(g=>g.key===key)));S.anchor=null;S.total=result.total;S.at=Math.max(0,S.items.findIndex(p=>p.id===previous));S.selected.clear();const currentGroup=S.groups.find(g=>g.ids.includes(current()?.id));if(currentGroup&&currentGroup.ids[0]!==current()?.id)S.expanded.add(currentGroup.key);$('s-select-page').checked=false;
 $('studio').hidden=false;$('gallery').hidden=true;$('pagination').hidden=true;$('review-bar').hidden=true;
 $('s-filter-status').textContent=$('list-summary').textContent=(S.bird?'筛选鸟种：'+S.options.name(S.bird)+' · ':'')+'匹配 '+result.matched_photos+' 张';$('s-pages').textContent=(Math.floor(S.offset/100)+1)+' / '+Math.max(1,Math.ceil(S.total/100));$('export-csv').href='/api/export/csv?'+new URLSearchParams(S.options.filters());strip();display();
}
async function validationView(group){
 if(S.busy)return;const sequence=++S.seq,result=await S.options.api('/api/photos?ids='+group.samples.map(p=>p.id).join(','));if(sequence!==S.seq)return;
 S.items=result.items;S.groups=[];S.expanded.clear();S.selected.clear();S.anchor=null;S.at=0;S.offset=0;S.total=S.items.length;
 $('s-filter-status').textContent='正在查看验证组：'+group.name+' · '+S.total+' 张（应用筛选返回图库）';$('s-pages').textContent='验证组 · 1 / 1';display();strip();
}
function visiblePhotos(){return window.StudioStrip.visible(S.items,S.groups,S.expanded);}
function choosePhoto(id,event={}){
 if(S.busy)return;
 const choice=window.StudioStrip.choose(visiblePhotos().map(p=>p.id),S.selected,S.anchor,id,event);
 S.selected=choice.selected;S.anchor=choice.anchor;S.at=S.items.findIndex(p=>p.id===id);display();strip();
}
function strip(reveal=false){
 const filmstrip=$('s-strip'),left=filmstrip.scrollLeft||0;filmstrip.replaceChildren();
 for(const p of visiblePhotos()){
  const i=S.items.findIndex(item=>item.id===p.id),group=S.groups.find(g=>g.ids.includes(p.id));
  const card=el('div',undefined,'film-item'+(i===S.at?' active':'')+(S.selected.has(p.id)?' multi-selected':''));card.dataset.id=String(p.id);
  const check=el('input');check.type='checkbox';check.checked=S.selected.has(p.id);check.setAttribute('aria-label','勾选 '+p.relative_path);
  let rangeClick=false;check.onclick=e=>{rangeClick=!!e?.shiftKey;if(rangeClick){e.preventDefault();choosePhoto(p.id,{shiftKey:true,ctrlKey:!!e.ctrlKey,metaKey:!!e.metaKey});}};
  // onchange supports keyboard and touch checkboxes without affecting the current photo.
  check.onchange=()=>{if(rangeClick||S.busy)return;check.checked?S.selected.add(p.id):S.selected.delete(p.id);S.anchor=p.id;card.classList.toggle('multi-selected',S.selected.has(p.id));count();};
  const b=btn('',event=>choosePhoto(p.id,event)),img=el('img');img.alt=p.relative_path;img.loading='lazy';if(p.thumbnail)img.src=p.thumbnail;b.append(img);
  const q=p.quality?.score,selection=p.selection||{};card.append(check,b,el('small',p.relative_path.split('/').pop()),el('span',({keep:'✓ 保留',reject:'× 待剔除'}[selection.flag]||'未标记')+' '+('★'.repeat(selection.rating||0))+(q!==undefined?' · '+q+' 分':'')));
  card.append(el('span',birdTitle(p),'film-species'),el('span',issueTitle(p),'film-issues'));card.title=birdTitle(p)+' · '+issueTitle(p);
  const validationBadge=window.BirdValidation?.badge(p.id);if(validationBadge)card.append(el('span',validationBadge,'film-validation'));
  if(p.visibility?.hidden)card.append(el('span','已隐藏','film-hidden'));
  if(group&&group.count>1){
   card.append(btn('勾选本页组 · '+group.ids.length+' 张',()=>{if(S.busy)return;S.expanded.add(group.key);S.selected=new Set(group.ids);S.anchor=group.ids[0];strip();S.options.message('已勾选当前页/筛选内 '+group.ids.length+' 张；此连续组共 '+group.count+' 张，其他页或被筛选的照片未加入。');},'film-group'));
   if(group.ids.length>1){const expanded=S.expanded.has(group.key),label=(expanded?'收拢组':'展开组')+' · '+group.ids.length+' 张'+(group.ids.length<group.matched_count?'（当前页 / '+group.matched_count+'）':'');
    card.append(btn(label,()=>{if(S.busy)return;if(expanded){S.expanded.delete(group.key);if(group.ids.includes(current()?.id))S.at=S.items.findIndex(p=>p.id===group.ids[0]);}else S.expanded.add(group.key);
     const visible=new Set(visiblePhotos().map(p=>p.id));S.selected=new Set([...S.selected].filter(id=>visible.has(id)));if(!visible.has(S.anchor))S.anchor=null;display();strip();},'film-group'));
   }else card.append(el('span','连续组 · 当前页/筛选内 1 张，共 '+group.count+' 张','film-group-note'));
  }
  filmstrip.append(card);
 }
 count();filmstrip.scrollLeft=left;
 if(reveal){const currentCard=filmstrip.querySelector('.active');if(currentCard){const x=currentCard.offsetLeft-filmstrip.offsetLeft;if(x<filmstrip.scrollLeft)filmstrip.scrollLeft=x;else if(x+currentCard.clientWidth>filmstrip.scrollLeft+filmstrip.clientWidth)filmstrip.scrollLeft=x+currentCard.clientWidth-filmstrip.clientWidth;}}
}
function count(){const ids=visiblePhotos().map(p=>p.id),all=$('s-select-page'),n=ids.filter(id=>S.selected.has(id)).length;all.checked=ids.length>0&&n===ids.length;all.indeterminate=n>0&&n<ids.length;$('studio').querySelector('.studio-count').textContent='已勾选 '+S.selected.size+' 张（折叠组不自动全选）';}
function display(){
 release();const p=current(),img=$('s-image');img.removeAttribute('src');$('s-side').replaceChildren();$('s-caption').textContent='';$('s-progress').textContent=p?(S.offset+S.at+1)+' / '+S.total:'没有匹配照片';if(!p)return;
 if(p.thumbnail)img.src=p.thumbnail;pictureSummary();side();
}
function side(){
 const p=current();if(!p)return;const right=$('s-side');right.replaceChildren();const sel=p.selection||{flag:'none',rating:0,revision:0};
 right.append(el('h3',birdTitle(p)),el('p',issueTitle(p),'quality-issue'),el('p',({none:'未标记',keep:'✓ 保留',reject:'× 待剔除'}[sel.flag])+' · '+sel.rating+' 星'));
 const marks=el('div',undefined,'studio-buttons');for(const [text,flag] of [['保留 P','keep'],['待剔除 X','reject'],['清除 U','none']])marks.append(btn(text,()=>mark(p,flag,null),flag===sel.flag?'selected':''));right.append(marks);
 const stars=el('div',undefined,'studio-buttons');for(let i=0;i<=5;i++)stars.append(btn(i===0?'无星':i+'★',()=>mark(p,null,i),i===sel.rating?'selected':''));right.append(stars);
 window.BirdValidation?.side(right,p);
 const q=p.quality;right.append(el('h3',q?'技术参考分 '+q.score+' / 100':'尚未评分'));right.append(el('small','鸟眼对焦、遮挡和姿态美观：专门模型评估中，尚未上线；当前分数不包含这些结论。'));
 if(q){right.append(el('small','清晰度 '+(q.clarity??'未知')+' · 曝光 '+q.exposure+' · 构图 '+(q.composition??'未知')));for(const text of q.issues)right.append(el('p',text,'quality-issue'));right.append(el('small',q.limits));}
 else right.append(el('small','勾选后补评分；新处理照片复用解码自动评分。未校准，不依据分数自动删除。'));
 right.append(el('h3','鸟种确认'),el('p',p.manual.species.map(S.options.name).join('、')||({unreviewed:'尚未复核',uncertain:'暂不确定',no_bird:'人工确认无鸟',none_match:'候选都不对'}[p.manual.status]||p.manual.status)));
 for(const c of (p.candidates||[]).filter(c=>c.label.kind==='bird').slice(0,5)){const id=c.label.scientific_name;right.append(btn(S.options.name(id),()=>review(p,'confirmed',[id]),p.manual.species.includes(id)?'selected':''));}
 const search=el('input');search.placeholder='汉字、拼音或首字母搜索鸟种';search.setAttribute('aria-label','鸟种搜索');right.append(search);window.BirdSearch.bind(search,right,S.options.birds,l=>review(p,'confirmed',[l.id]));
 right.append(btn(p.visibility?.hidden?'恢复显示此图':'隐藏此图（不移动）',()=>setVisibility([p],!p.visibility?.hidden)));
 right.append(btn('暂不确定',()=>review(p,'uncertain',[])),btn('无鸟（仅分类，不移动）',()=>review(p,'no_bird',[])),btn('清除鸟种确认',()=>review(p,'unreviewed',[])));
 if(p.source_status==='quarantined')right.append(el('p','原片已暂存。勾选后可恢复；缩略图和人工记录保留。'));
}
async function review(p,status,species){if(S.busy)return;S.busy=true;try{const r=await S.options.api('/api/review',{items:[{id:p.id,revision:p.manual.revision}],status,species});p.manual={...p.manual,...r.records[0],stale:!!(p.sha256&&r.records[0].reviewed_sha!==p.sha256&&status!=='unreviewed')};S.groups=S.groups.filter(g=>!g.ids.includes(p.id));if(current()?.id===p.id){side();pictureSummary();}strip();await S.options.summary();S.options.message('鸟种已保存，图片位置保持。');}finally{S.busy=false;}}
async function mark(p,flag,rating){if(!p||S.busy)return;S.busy=true;try{await writeMarks([p],flag,rating);side();strip();}finally{S.busy=false;}}
async function writeMarks(photos,flag,rating){if(!photos.length)throw Error('请先勾选照片');const r=await S.options.api('/api/selection',{items:photos.map(p=>({id:p.id,revision:p.selection.revision})),flag,rating});for(const record of r.records){const p=S.items.find(p=>p.id===record.photo_id);if(p)p.selection=record;}S.options.message('已保存 '+r.records.length+' 张标记；筛选列表保持，原片尚未移动。');}
async function markMany(flag){if(S.busy)return;S.busy=true;try{await writeMarks(selected(),flag,null);side();strip();}finally{S.busy=false;}}
async function rateMany(){if(S.busy)return;S.busy=true;try{await writeMarks(selected(),null,Number($('s-batch-rating').value));side();strip();}finally{S.busy=false;}}
async function visibilityMany(hidden){return setVisibility(selected(),hidden);}
async function setVisibility(photos,hidden){
 if(S.busy)return;if(!photos.length)throw Error('请先勾选照片');S.busy=true;
 try{const r=await S.options.api('/api/visibility',{items:photos.map(p=>({id:p.id,revision:p.visibility?.revision||0})),hidden});
  for(const record of r.records){const p=S.items.find(p=>p.id===record.photo_id);if(p)p.visibility=record;}
  await refresh();S.options.message(hidden?'已隐藏 '+r.records.length+' 张；可在“显示范围 → 仅隐藏”恢复，不改变原片或鸟种。':'已恢复显示 '+r.records.length+' 张。');
 }finally{S.busy=false;}
}
function move(delta){if(S.busy)return;const visible=visiblePhotos(),at=visible.findIndex(p=>p.id===current()?.id),p=visible[Math.max(0,Math.min(visible.length-1,at+delta))];if(!p)return;S.at=S.items.findIndex(item=>item.id===p.id);display();strip(true);}
async function original(){
 const p=current();if(!p||S.busy)return;const seq=++S.seq,progress=window.BirdProgress?.begin('加载原图预览',1,p.relative_path);let failure=null;try{S.options.message('正在加载适屏预览…');const preview=await window.BirdPreview.load(p,S.options);const blob=preview.blob;if(seq!==S.seq||!S.enabled)return;
 if(S.blob)URL.revokeObjectURL(S.blob);S.blob=URL.createObjectURL(blob);$('s-image').src=S.blob;S.options.message(preview.cached?'已复用内存中的整图预览，无需重新解码或传图。':'已加载整图预览；最近 3 张在本页内存短暂缓存，不预读下一张。');}catch(e){failure=e;throw e;}finally{progress?.finish(failure);}
}
async function editor(){const p=current();if(!p)return;await window.BirdEditor.open(p.id,{api:S.options.api,token:S.options.token,name:S.options.name,birds:S.options.birds,onChanged:async id=>{const fresh=await S.options.api('/api/photos?ids='+id),i=S.items.findIndex(p=>p.id===id);if(i>=0)S.items[i]=fresh.items[0];display();strip();}});}
async function scoreMany(){
 const photos=selected();if(S.busy)return;if(!photos.length)throw Error('请勾选要评分的现有照片，不会扫描新文件');S.busy=true;const progress=window.BirdProgress?.begin('质量评分',photos.length);let failure=null;
 try{for(const [i,p] of photos.entries()){progress?.update({done:i,path:p.relative_path});S.options.message('本地质量评估 '+(i+1)+' / '+photos.length+'；未改变的评分复用结果。');const r=await S.options.api('/api/quality',{photo_id:p.id,source_sha:p.sha256});p.quality=r.quality;progress?.update({done:i+1});side();pictureSummary();strip();}S.options.message('评分完成。请结合原图判断，参考分不会自动移动照片。');}catch(e){failure=e;throw e;}finally{progress?.finish(failure);S.busy=false;}
}
async function plan(action){
 if(S.busy)return;const photos=selected();if(!photos.length)throw Error('请先勾选现有照片');const status=await S.options.api('/api/curation-status');
 if(!status.enabled)throw Error('整理服务尚未启用。标记与评分可以使用；启用独立整理服务后才能批量移动原片。');
 if(photos.length>(status.max_batch||10))throw Error('本次最多勾选 '+(status.max_batch||10)+' 张，请分批确认');
 if(status.pending.length){showRecovery(status.pending);return;}
 const result=await S.options.api('/api/curation-plan',{ids:photos.map(p=>p.id),action});showPlan(result);
}
function showRecovery(items){const dialog=$('s-dialog');dialog.replaceChildren(el('h3','上次整理尚未完成'),el('p','恢复已有操作会根据原路径、暂存路径和指纹核对，不创建重复移动。'));for(const item of items)dialog.append(btn('核对并恢复操作 '+item.id,()=>commit(item.id)));dialog.append(btn('关闭',()=>dialog.close()));dialog.showModal();}
function showPlan(result){
 const dialog=$('s-dialog');dialog.replaceChildren(el('h3',result.action==='move'?'确认移至待删除':'确认恢复原片'),el('p',result.items.length+' 张 · '+(result.action==='move'?result.destination_display+'。保留相对目录，不自动清空。':'从待删除目录恢复到原始路径，不覆盖已有文件。')));const list=el('ul');for(const item of result.items)list.append(el('li',result.action==='move'?item.source+' → '+item.destination:item.destination+' → '+item.source));dialog.append(list,btn('取消',()=>dialog.close()),btn(result.action==='move'?'确认移动这 '+result.items.length+' 张':'确认恢复',()=>commit(result.plan_id),'danger'));dialog.showModal();
}
async function commit(id){if(S.busy)return;S.busy=true;const dialog=$('s-dialog');try{const r=await S.options.api('/api/curation-commit',{plan_id:id});dialog.replaceChildren(el('h3','整理结果'));for(const item of r.results)dialog.append(el('p','照片 '+item.photo_id+'：'+(item.ok?'完成':item.error)));if(r.needs_recovery)dialog.append(btn('核对并恢复此操作',()=>commit(id)));dialog.append(btn('关闭',()=>dialog.close()));await refresh();}finally{S.busy=false;}}
window.BirdStudio={init,filters,refresh,hide,active:()=>S.enabled,state:S};
})();
