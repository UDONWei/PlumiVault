'use strict';
(function(root){
function seconds(row){
  const value=row.exif?.['EXIF DateTimeOriginal'];
  if(typeof value!=='string')return null;
  const m=/^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})$/.exec(value);
  if(!m)return null;
  const a=m.slice(1).map(Number),d=new Date(Date.UTC(a[0],a[1]-1,a[2],a[3],a[4],a[5]));
  if(d.getUTCFullYear()!==a[0]||d.getUTCMonth()!==a[1]-1||d.getUTCDate()!==a[2]||d.getUTCHours()!==a[3]||d.getUTCMinutes()!==a[4]||d.getUTCSeconds()!==a[5])return null;
  return d.getTime()/1000;
}
function identity(row,record){
  if(record?.status==='confirmed')return record.species.length===1?{id:record.species[0].scientific_name,confirmed:true}:null;
  if(record?.status&&record.status!=='unreviewed')return null;
  const candidate=(row.views?.[0]?.context_candidates||row.views?.[0]?.candidates||[])[0];
  if(row.detection?.status!=='detected'||!candidate||candidate.label.kind!=='bird')return null;
  return {id:candidate.label.scientific_name,confirmed:false};
}
function distance(a,b){
  if(!/^[0-9a-f]{16}$/.test(a||'')||!/^[0-9a-f]{16}$/.test(b||''))return Infinity;
  let n=BigInt('0x'+a)^BigInt('0x'+b),count=0;while(n){count++;n&=n-1n;}return count;
}
function appearance(a,b,colourLimit){
  if(!a||!b||a.algorithm!=='dct63-dhash64-rgb-v1'||b.algorithm!==a.algorithm)return false;
  if(!Number.isFinite(a.aspect)||!Number.isFinite(b.aspect)||Math.max(a.aspect/b.aspect,b.aspect/a.aspect)>1.08)return false;
  if(a.detail_score<.00005||b.detail_score<.00005)return false;
  if(!Array.isArray(a.mean_rgb)||!Array.isArray(b.mean_rgb)||a.mean_rgb.length!==3||b.mean_rgb.length!==3)return false;
  const colour=Math.sqrt(a.mean_rgb.reduce((s,x,i)=>s+(x-b.mean_rgb[i])**2,0));
  return colour<=colourLimit&&distance(a.phash,b.phash)<=6&&distance(a.dhash,b.dhash)<=10;
}
function similar(a,b){
  const ta=seconds(a),tb=seconds(b);
  if(ta===null||tb===null||Math.abs(ta-tb)>10||a.directory!==b.directory)return false;
  if(a.before?.sha256&&a.before.sha256===b.before?.sha256)return true;
  if(a.detection?.status!=='detected'||b.detection?.status!=='detected')return false;
  return appearance(a.similarity?.whole,b.similarity?.whole,.08)&&appearance(a.similarity?.subject,b.similarity?.subject,.12);
}
function plan(rows,records,options={}){
  const gap=Number(options.gap??30);
  if(!Number.isFinite(gap)||gap<1||gap>120)throw Error('连拍间隔须为 1–120 秒');
  const breaks=new Set(options.breaks||[]),keep=new Set(options.keep||[]),covers=new Set(options.covers||[]);
  const ordered=rows.map((row,i)=>({row,i,t:seconds(row),bird:identity(row,records[i])})).sort((a,b)=>a.row.directory.localeCompare(b.row.directory)||((a.t??Infinity)-(b.t??Infinity))||a.row.path.localeCompare(b.row.path,undefined,{numeric:true}));
  const groups=[];
  for(const item of ordered){
    const last=groups.at(-1),previous=last?.items.at(-1);
    const join=previous&&item.bird&&previous.bird&&item.bird.id===previous.bird.id&&item.row.directory===previous.row.directory&&item.t!==null&&previous.t!==null&&item.t-previous.t<=gap&&item.t-last.items[0].t<=300&&!breaks.has(item.row.path);
    if(join)last.items.push(item);else groups.push({items:[item]});
  }
  return groups.map(group=>{
    const members=group.items,ranked=[...members].sort((a,b)=>Number(covers.has(b.row.path))-Number(covers.has(a.row.path))||(b.row.similarity?.subject?.detail_score||0)-(a.row.similarity?.subject?.detail_score||0)||a.i-b.i);
    const representatives=[],folded=[];
    for(const item of ranked){
      const match=!keep.has(item.row.path)&&!covers.has(item.row.path)&&representatives.find(other=>similar(item.row,other.row));
      if(match)folded.push({index:item.i,representative:match.i,reason:item.row.before.sha256===match.row.before.sha256?'内容 SHA-256 相同':'10 秒内整图与主体外观均接近'});
      else representatives.push(item);
    }
    return {key:members[0].row.path,indices:members.map(x=>x.i),visible:representatives.map(x=>x.i).sort((a,b)=>a-b),
      folded,cover:ranked[0].i,species:members[0].bird?.id||null,
      confirmed:members.every(x=>x.bird?.confirmed),directory:members[0].row.directory,
      first_time:members[0].row.exif?.['EXIF DateTimeOriginal']||null};
  });
}
function validatePreferences(doc,data){
  if(!doc||doc.schema!=='bird-view-settings-v1'||doc.batch_id!==data.review_batch_id)throw Error('视图设置批次不匹配');
  const paths=new Set(data.rows.map(r=>r.path));
  if(!Number.isInteger(doc.gap)||doc.gap<1||doc.gap>120||typeof doc.grouping!=='boolean'||typeof doc.foldSimilar!=='boolean')throw Error('视图参数无效');
  const result={gap:doc.gap,grouping:doc.grouping,foldSimilar:doc.foldSimilar};
  for(const key of ['breaks','keep','covers']){
    if(!Array.isArray(doc[key])||doc[key].length>paths.size||new Set(doc[key]).size!==doc[key].length||doc[key].some(p=>!paths.has(p)))throw Error('视图设置含未知或重复照片');
    result[key]=[...doc[key]];
  }
  return result;
}
const api={seconds,identity,distance,similar,plan,validatePreferences};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.BirdGrouping=api;
})(globalThis);
