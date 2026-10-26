/* 本地复核页与 Python 排序的一致性由 tests/test_context.py 检查。 */
(function (root) {
  'use strict';
  function validDate(text) {
    if (typeof text !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
    const [y,m,d] = text.split('-').map(Number);
    const days = [31, (y%4===0 && (y%100!==0 || y%400===0)) ? 29 : 28,31,30,31,30,31,31,30,31,30,31];
    return y>=1 && m>=1 && m<=12 && d>=1 && d<=days[m-1];
  }
  function factor(label, context, data, policy) {
    const code = context.region_code;
    const neutral = {factor:1, statuses:[], reasons:[]};
    if (!data || !code) return {...neutral, reasons:['地区未设置，保持视觉分数']};
    if (!Object.hasOwn(data.regions, code)) throw Error('未知地理亚区');
    if (label.kind !== 'bird') return {...neutral, reasons:['通用对照，不应用鸟类分布提示']};
    const statuses = data.species[label.scientific_name]?.[code] || [];
    if (!statuses.some(s => 'RSWP'.includes(s))) return {...neutral, statuses,
      reasons:[statuses.length ? '只有迷鸟记录，保持原分' : '没有可用常规记录；不等于当地不存在，保持原分']};
    let value = 1 + policy.region_bonus;
    const reasons = ['有当地留鸟/候鸟/旅鸟记录 +0.15'];
    if (context.date && context.use_date !== false) {
      if (!validDate(context.date)) throw Error('无效日期');
      const month = Number(context.date.slice(5,7));
      const matches = statuses.filter(s => (policy.months[s] || []).includes(month));
      if (matches.length) { value += policy.season_bonus; reasons.push('符合实验月份规则 ' + matches.join('/') + ' +0.10'); }
      else reasons.push('月份未匹配粗略规则，不额外加分、不排除');
    } else reasons.push('日期缺失或季节提示关闭，只用地区');
    return {factor:value, statuses, reasons};
  }
  function rank(labels, scores, context, data, policy, k=5) {
    if (labels.length!==scores.length || !scores.length || k<1 || k>scores.length ||
        scores.some(s => !Number.isFinite(s) || s<0) || Math.abs(scores.reduce((a,b)=>a+b,0)-1)>1e-4)
      throw Error('必须提供全国完整 softmax 分数');
    const rows = scores.map((score,i)=>({i,score,...factor(labels[i],context,data,policy)}));
    const raw = [...rows].sort((a,b)=>b.score-a.score || a.i-b.i);
    const positions = Object.fromEntries(raw.map((x,i)=>[x.i,i+1]));
    return {baseline: raw.slice(0,k), adjusted: rows.map(x=>({...x,ranking_score:x.score*x.factor,visual_rank:positions[x.i]}))
      .sort((a,b)=>b.ranking_score-a.ranking_score || a.i-b.i).slice(0,k)};
  }
  const api = {validDate, factor, rank};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.BirdContext = api;
})(globalThis);
