'use strict';
// 仅在浏览器内重排已计算的数字；没有联网、照片读取或后台服务。
(() => {
  const data = JSON.parse(document.getElementById('review-data').textContent);
  const region = document.getElementById('region');
  const locality = document.getElementById('locality');
  const dateInput = document.getElementById('capture-date');
  const enabled = document.getElementById('enabled');
  const useDate = document.getElementById('use-date');
  const message = document.getElementById('message');
  const manual=BirdManualUI.create(data,name);
  Object.entries(data.occurrences.regions).forEach(([code, name]) => {
    const option = document.createElement('option'); option.value=code; option.textContent=`${code} · ${name}`; region.append(option);
  });
  const first = data.rows[0].capture_context;
  region.value = first.region_code || '';
  locality.value = first.location || '';
  dateInput.title = '本批默认日期：'+(first.date || '未知')+'；留空保留逐图日期来源';
  function context(row) {
    return {...row.capture_context, location:locality.value.trim() || null,
      region_code:enabled.checked ? region.value || null : null,
      date:dateInput.value || row.capture_context.date, use_date:useDate.checked};
  }
  function name(i) {
    const label = data.labels[i];
    return label.zh_name && !/[?\ufffd]/.test(label.zh_name) ? label.zh_name :
      (label.scientific_name ? label.scientific_name+'（中文待核对）' : label.prompt);
  }
  function fill(list, candidates, adjusted, ri) {
    list.replaceChildren();
    for (const c of candidates) {
      const li = document.createElement('li');
      const main = document.createElement('span');
      main.textContent = name(c.i) + (adjusted ? ` · 排序值 ${c.ranking_score.toFixed(4)}` : ` · 分数 ${c.score.toFixed(4)}`);
      li.append(manual.choice(ri,c.i,main));
      const detail = document.createElement('small');
      detail.textContent = adjusted ? `原视觉第 ${c.visual_rank} 名 · 原分 ${c.score.toFixed(4)} × ${c.factor.toFixed(2)}；${c.reasons.join('；')}` : (data.labels[c.i].scientific_name || '通用对照提示');
      li.append(detail); list.append(li);
    }
  }
  function update() {
    try {
      if (dateInput.value && !BirdContext.validDate(dateInput.value)) throw Error('日期无效，请填写 YYYY-MM-DD');
      let changes=0, viewCount=0, wholeChanges=0;
      const subjectMode=!!data.rows[0]?.detection;
      data.rows.forEach((row, ri) => {
        manual.resetInputs(ri);
        const ctx = context(row);
        const details = document.getElementById(`context-${ri}`);
        const conflicts = [...row.capture_context.warnings];
        if (dateInput.value && dateInput.value!==row.capture_context.date) conflicts.push('正在使用手动日期，原始日期仍保留');
        details.textContent = `拍摄地：${ctx.location || '未填写'} · 亚区：${data.occurrences.regions[ctx.region_code] || '未设置'} · 日期：${ctx.date || '未知'}（${dateInput.value ? '页面手动覆盖' : row.capture_context.date_source}） · EXIF：${row.capture_context.exif_datetime || '无'} · 目录日期：${row.capture_context.folder_date || '无'}` + (conflicts.length ? ' · '+conflicts.join('；') : '');
        row.views.forEach((view, vi) => {
          const result = BirdContext.rank(data.labels, view.all_visual_scores, ctx, data.occurrences, data.policy, 5);
          fill(document.getElementById(`raw-${ri}-${vi}`),result.baseline,false,ri);
          fill(document.getElementById(`adjusted-${ri}-${vi}`),result.adjusted,true,ri);
          const changed = result.baseline[0].i!==result.adjusted[0].i;
          changes += Number(changed); viewCount++;
          wholeChanges += Number(changed && view.name==='whole');
          document.getElementById(`change-${ri}-${vi}`).textContent = changed ? '首选候选已改变，待你复核' : '首选候选保持';
        });
      });
      message.textContent = (subjectMode ? `${data.rows.length} 张，每图一个主体或整图回退；地区/时间辅助使首选改变 ${changes}/${viewCount}。改变数量不代表准确率。` : `${data.rows.length} 张、${viewCount} 个视图；整图首选改变 ${wholeChanges}/${data.rows.length}，全部视图首选改变 ${changes}/${viewCount}。改变数量不代表准确率。`) + (!region.value || !enabled.checked ? ' 当前未应用地区/季节加分。' : ' 已应用实验性弱提示，所有候选仍待确认。');
    } catch (err) { message.textContent = '无法调整：'+err.message; }
  }
  document.getElementById('apply').addEventListener('click', update);
  document.getElementById('reset').addEventListener('click',()=>{
    region.value=''; locality.value=''; dateInput.value=''; enabled.checked=true; useDate.checked=true; update();
  });
  document.getElementById('export').addEventListener('click',()=>{
    if (dateInput.value && !BirdContext.validDate(dateInput.value)) {message.textContent='日期无效，未导出'; return;}
    const manifest=structuredClone(data.manifest);
    manifest.samples=manifest.samples.map((sample,i)=>({ ...sample, manual_review:manual.get(i), capture_context:{
      ...manifest.capture_context, ...sample.capture_context,
      location:locality.value.trim() || null, region_code:enabled.checked ? region.value || null : null,
      date:dateInput.value || sample.capture_context?.date || manifest.capture_context?.date || null,
      use_date:useDate.checked} }));
    const blob = new Blob([JSON.stringify(manifest,null,2)],{type:'application/json;charset=utf-8'});
    const url=URL.createObjectURL(blob), a=document.createElement('a');
    a.href=url; a.download='samples-with-context.json'; a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    message.textContent='已请求下载背景清单，附带独立 manual_review 人工复核字段；原 truth 保持。没有保存照片或修改 EXIF。';
  });
  update();
})();
