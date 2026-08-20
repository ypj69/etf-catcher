(function(){
  const originalRenderHeatmap=renderHeatmap;
  renderHeatmap=function(){
    const rows=state.heatmap.filter(x=>x.group_level===state.heatLevel);
    const dates=[...new Set(rows.map(x=>x.trade_date))].sort();
    const groups=[...new Set(rows.map(x=>x.group_name))];
    const values=rows.map(x=>Math.abs(Number(x.net_flow_yi))).filter(Number.isFinite).sort((a,b)=>a-b);
    const cap=values.length?values[Math.min(values.length-1,Math.floor(values.length*.92))]:1;
    const z=groups.map(g=>dates.map(d=>rows.find(x=>x.group_name===g&&x.trade_date===d)?.net_flow_yi??null));
    const text=z.map(line=>line.map(v=>v==null?'':Math.abs(v)>=Math.max(1,cap*.22)?Number(v).toFixed(1):''));
    Plotly.react('heatmapChart',[{x:dates,y:groups,z,text,type:'heatmap',zmin:-cap,zmax:cap,zmid:0,
      colorscale:[[0,'#075b45'],[.18,'#168269'],[.42,'#a9d8c8'],[.495,'#f4f4ef'],[.505,'#f4f4ef'],[.58,'#efb7ad'],[.82,'#d45b4f'],[1,'#9e2f2b']],
      colorbar:{title:{text:'净流入（亿元）'},tickformat:'.1f',thickness:14,len:.84},
      texttemplate:'%{text}',textfont:{size:10,color:'#17231e'},
      hovertemplate:'<b>%{y}</b><br>%{x}<br>净流入 %{z:.2f} 亿元<extra></extra>'}],
      chartLayout({margin:{l:165,r:78,t:12,b:50},yaxis:{automargin:true,fixedrange:true},xaxis:{...layoutBase.xaxis,rangebreaks:breaks(),fixedrange:true},height:Math.max(480,groups.length*27+90)}),plotCfg);
  };

  function firstRow(tables){return tables?.flatMap(t=>t.rows||[])[0]||{}}
  function pick(obj,keys){return keys.map(k=>[k,obj[k]]).filter(([,v])=>v!==undefined&&v!==null&&v!=='')}
  function cleanLabel(k){return k.replace(/（单位：[^）]+）/g,'').replace(/（净值估值）/g,'')}
  function metricCards(entries){return `<div class="live-metrics">${entries.map(([k,v])=>`<div class="live-metric"><span>${esc(cleanLabel(k))}</span><strong>${esc(v)}</strong></div>`).join('')}</div>`}
  function infoGrid(entries){return `<dl class="profile-grid">${entries.map(([k,v])=>`<div><dt>${esc(cleanLabel(k))}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`}
  function holdingRows(tables){
    const nameRow=(tables?.[0]?.rows||[]).find(r=>String(r['证券代码']||'').endsWith('.SH')||String(r['证券代码']||'').endsWith('.SZ'))||tables?.[0]?.rows?.[0]||{};
    const valueRow=(tables?.[1]?.rows||[]).find(r=>String(r['证券代码']||'').endsWith('.SH')||String(r['证券代码']||'').endsWith('.SZ'))||tables?.[1]?.rows?.[0]||{};
    return Array.from({length:10},(_,i)=>{const rank=i+1;const suffix=`排名：第${rank}名`;const find=(obj,starts)=>Object.entries(obj).find(([k])=>k.startsWith(starts)&&k.includes(suffix))?.[1]||'';return{rank,name:find(nameRow,'重仓股股票名称'),code:find(nameRow,'重仓股股票代码'),shares:find(valueRow,'重仓股持股数量'),value:find(valueRow,'重仓股持股市值')}}).filter(x=>x.name||x.code);
  }
  function holdingsTable(rows){return `<div class="table-scroll"><table class="data-table holdings-table"><thead><tr><th>排名</th><th>证券</th><th>代码</th><th>持有数量</th><th>持仓市值</th></tr></thead><tbody>${rows.map(x=>`<tr><td><span class="rank">${x.rank}</span></td><td><strong>${esc(x.name)}</strong></td><td class="mono">${esc(x.code)}</td><td>${esc(x.shares||'—')}</td><td>${esc(x.value||'—')}</td></tr>`).join('')}</tbody></table></div>`}
  renderLive=function(data){
    const profile=firstRow(data.live.profile?.tables),quotes=firstRow(data.live.quotes?.tables),holdings=holdingRows(data.live.portfolio?.tables);
    const tracking=profile['跟踪指数名称'];
    if(tracking&&!$('#etfMeta').textContent.includes(tracking))$('#etfMeta').insertAdjacentHTML('beforeend',`<span>跟踪：${esc(tracking)}</span>`);
    $('#liveStatus').innerHTML=`<span class="live-dot"></span>${esc(data.source)} · 盘口为当前查询快照 · 持仓为最新披露期，并非实时仓位`;
    const quoteKeys=['最新价','涨跌幅','IOPV（净值估值）','成交额','成交量','今开','最高','最低','折溢价','time'];
    const profileKeys=['基金全称','基金管理人','基金投资类型','跟踪指数名称','跟踪指数代码','基金成立日','上市日期','姓名','管理费率（单位：%）','托管费率（单位：%）'];
    const feeRow=firstRow((data.live.profile?.tables||[]).slice(1));Object.assign(profile,feeRow);
    $('#liveDetail').innerHTML=`<section class="live-section quote-section"><div class="section-title"><div><p class="kicker">LIVE SNAPSHOT</p><h4>当日盘口</h4></div><small>${esc(quotes.time||'')}</small></div>${metricCards(pick(quotes,quoteKeys.filter(k=>k!=='time')))}</section><div class="live-detail-grid"><section class="live-section"><div class="section-title"><div><p class="kicker">FUND PROFILE</p><h4>基金简况</h4></div></div>${infoGrid(pick(profile,profileKeys))}</section><section class="live-section holdings-section"><div class="section-title"><div><p class="kicker">LATEST DISCLOSURE</p><h4>前十大持仓</h4></div><small>最新披露期</small></div>${holdingsTable(holdings)}</section></div>`;
  };

  if(state.meta){renderHeatmap()}
})();
