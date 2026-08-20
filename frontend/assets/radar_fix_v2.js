(function(){
  const style=document.createElement('link');style.rel='stylesheet';style.href='/assets/radar_fix_v2.css';document.head.appendChild(style);
  state.radar=null;
  const number=(value,digits=2)=>value==null?'—':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits});
  const signed=(value,suffix='')=>value==null?'—':`${value>=0?'+':''}${number(value)}${suffix}`;

  function installRadarLayout(){
    const radar=document.querySelector('#radar');if(!radar||document.querySelector('#stableFundBehaviorPanel'))return;
    const ranking=radar.querySelector('.two-col');
    const wrapper=document.createElement('div');
    wrapper.innerHTML=`<section id="stableFundBehaviorPanel" class="panel radar-section stable-fund-panel"><div class="panel-head stable-fund-head"><div><p class="kicker">STABLE FUND BEHAVIOR</p><h3>核心沪深300ETF稳定资金行为</h3><p class="radar-help">把市场位置、4只核心ETF份额20日变化与历史Z分数放在同一时间轴观察。</p></div><div id="stableFundState" class="stable-fund-state">读取中</div></div><div id="stableFundMetrics" class="stable-fund-metrics"></div><div id="stableFundBehaviorChart" class="chart stable-fund-chart"></div><p class="stable-fund-disclaimer">状态观察，不是交易信号。</p></section><div class="radar-grid radar-section"><section class="panel"><div class="panel-head"><div><h3>分类资金仪表盘</h3><p class="radar-help">比较当日与5日、10日、20日资金方向，点击分类可查看完整走势。</p></div><div class="tabs" id="radarCategoryLevel"><button class="active" data-level="industry">行业</button><button data-level="broad">宽基</button><button data-level="asset">大类</button></div></div><div id="radarCategoryTable" class="radar-table-wrap"></div></section><section class="panel"><div class="panel-head"><div><h3>资金异动信号</h3><p class="radar-help">按照相对前5日均值的加速度、连续方向和反转识别。</p></div></div><div id="radarSignals" class="signal-list"></div></section></div>`;
    ranking.parentNode.insertBefore(wrapper,ranking);
    const heatPanel=document.querySelector('#heatmapChart')?.closest('.panel');
    heatPanel?.classList.add('heatmap-panel');
    const heatTitle=heatPanel?.querySelector('h3');if(heatTitle)heatTitle.textContent='近10个交易日分类资金热力图';
    const oldMode=document.querySelector('#heatMode');oldMode?.remove();
    const legend=heatPanel?.querySelector('.heat-meaning');legend?.remove();
    const level=document.querySelector('#heatLevel');
    if(level&&!level.querySelector('[data-level="asset"]'))level.insertAdjacentHTML('beforeend','<button data-level="asset">大类</button>');
    level?.querySelectorAll('button').forEach(button=>button.onclick=()=>{level.querySelectorAll('button').forEach(x=>x.classList.remove('active'));button.classList.add('active');state.heatLevel=button.dataset.level;renderHeatmap()});
    document.querySelectorAll('#radarCategoryLevel button').forEach(button=>button.onclick=()=>{document.querySelectorAll('#radarCategoryLevel button').forEach(x=>x.classList.remove('active'));button.classList.add('active');renderCategoryTable(button.dataset.level)});
  }

  renderIndices=function(){
    const allowed=state.indexScope==='cn'?['000001.SH','000300.SH','000688.SH']:state.indexScope==='overseas'?['GSPC','IXIC','N225','KS11']:null;
    const rows=state.indices.filter(row=>!allowed||allowed.includes(row.index_code));
    const dates=[...new Set(rows.map(row=>row.date))].sort();
    const traces=[...new Set(rows.map(row=>row.index_code))].map(code=>{const byDate=new Map(rows.filter(row=>row.index_code===code).map(row=>[row.date,row]));const first=rows.find(row=>row.index_code===code);return{x:dates,y:dates.map(date=>byDate.get(date)?.normalized??null),customdata:dates.map(date=>{const row=byDate.get(date);return row?[row.close,row.change_pct,row.is_carried?` · 沿用 ${row.source_date}`:'']:[null,null,'']}),name:first.index_name,type:'scatter',mode:'lines+markers',connectgaps:true,line:{width:1.8},marker:{size:3},hovertemplate:'<b>%{fullData.name}</b>：收盘 %{customdata[0]:,.2f} · 涨跌 %{customdata[1]:.2f}% · 归一化 %{y:.2f}%{customdata[2]}<extra></extra>'}});
    Plotly.react('indexChart',traces,{...layoutBase,hovermode:'x unified',hoverlabel:{align:'left',bgcolor:'#fff',bordercolor:'#627169',font:{size:10,color:'#26342e'}},xaxis:{...layoutBase.xaxis,type:'category',categoryorder:'array',categoryarray:dates,nticks:10},yaxis:{...layoutBase.yaxis,title:'2026年首日=100'}},plotCfg);
  };

  function renderOverview(){const o=state.radar?.overview;if(!o)return;const market=document.querySelector('#metricCards');if(market)market.innerHTML=[metric('全市场净流入',signed(o.net_flow_yi,' 亿'),o.net_flow_yi>=0?'整体净流入':'整体净流出'),metric('份额变化',signed(o.share_change_yi,' 亿份'),'拆分校正后'),metric('成交额',`${number(o.turnover_yi,0)} 亿`,'ETF市场活跃度'),metric('资金覆盖率',`${number(o.flow_coverage_pct)}%`,`${o.inflow_etfs}只流入 / ${o.outflow_etfs}只流出`),metric('ETF总规模',`${number(state.meta?.total_scale_yi,0)} 亿`,`${number(state.meta?.etf_count,0)}只ETF`)].join('');const radarMetrics=document.querySelector('#radarMetrics');if(radarMetrics){radarMetrics.innerHTML='';radarMetrics.hidden=true}}
  function renderCategoryTable(level='industry'){const rows=(state.radar?.category_summary||[]).filter(row=>row.group_level===level).sort((a,b)=>(b.net_flow_yi??-Infinity)-(a.net_flow_yi??-Infinity));const host=document.querySelector('#radarCategoryTable');if(!host)return;host.innerHTML=`<table class="data-table radar-table"><thead><tr><th>分类</th><th>当日</th><th>5日</th><th>10日</th><th>20日</th><th>份额变化</th><th>成交额</th><th>有效ETF</th></tr></thead><tbody>${rows.map(row=>`<tr data-group="${esc(row.group_name)}" data-level="${level}"><td><strong>${esc(row.group_name)}</strong></td><td class="${color(row.net_flow_yi)}">${signed(row.net_flow_yi)}</td><td class="${color(row.flow_5d_yi)}">${signed(row.flow_5d_yi)}</td><td class="${color(row.flow_10d_yi)}">${signed(row.flow_10d_yi)}</td><td class="${color(row.flow_20d_yi)}">${signed(row.flow_20d_yi)}</td><td class="${color(row.share_change_yi)}">${signed(row.share_change_yi)}</td><td>${number(row.amount_yi,0)}</td><td>${row.valid_flow_etfs}/${row.active_etfs}</td></tr>`).join('')}</tbody></table>`;host.querySelectorAll('tr[data-group]').forEach(row=>row.onclick=()=>{state.level=row.dataset.level;state.group=row.dataset.group;document.querySelector('[data-view="market"]')?.click();document.querySelector(`#groupLevel [data-level="${row.dataset.level}"]`)?.click();renderGroupList();renderGroupCharts();document.querySelector('.monitor-layout')?.scrollIntoView({behavior:'smooth'})})}
  function renderSignals(){const rows=state.radar?.signals||[];const picked=[...rows.slice(0,4),...rows.slice(-4).reverse()];const host=document.querySelector('#radarSignals');if(!host)return;host.innerHTML=picked.length?picked.map(row=>`<div class="signal-item"><div><strong>${esc(row.group_name)}</strong><small>${row.reversal?'方向反转 · ':''}${row.streak?`连续${Math.abs(row.streak)}日${row.streak>0?'流入':'流出'}`:'方向震荡'}</small></div><em class="${color(row.acceleration_yi)}">${signed(row.acceleration_yi)} 亿</em></div>`).join(''):'<p class="radar-empty">暂无足够历史数据</p>'}
  renderHeatmap=function(){
    const rows=(state.radar?.heatmap||[]).filter(row=>row.group_level===state.heatLevel);
    const dates=[...new Set(rows.map(row=>row.trade_date))].sort().reverse();
    const totals={};rows.forEach(row=>totals[row.group_name]=(totals[row.group_name]||0)+(Number(row.net_flow_yi)||0));
    const groups=[...new Set(rows.map(row=>row.group_name))].sort((a,b)=>totals[b]-totals[a]);
    const lookup=new Map(rows.map(row=>[`${row.trade_date}|${row.group_name}`,row]));
    const z=dates.map(date=>groups.map(group=>lookup.get(`${date}|${group}`)?.net_flow_yi??null));
    const share=dates.map(date=>groups.map(group=>lookup.get(`${date}|${group}`)?.share_change_yi??null));
    const values=rows.map(row=>Math.abs(Number(row.net_flow_yi))).filter(Number.isFinite).sort((a,b)=>a-b);const cap=Math.max(values[Math.floor(values.length*.9)]||1,.01);
    const text=z.map(line=>line.map(value=>value==null?'':Number(value).toFixed(1)));
    const width=Math.max(760,groups.length*82+160),height=Math.max(390,dates.length*37+105),host=document.querySelector('#heatmapChart');host.style.minWidth=`${width}px`;host.style.height=`${height}px`;
    Plotly.react(host,[{x:groups,y:dates,z,text,customdata:share,type:'heatmap',zmin:-cap,zmax:cap,zmid:0,colorscale:[[0,'#006837'],[.18,'#1a9850'],[.38,'#91cf60'],[.49,'#e8f3bd'],[.5,'#fff7bc'],[.58,'#fdae61'],[.78,'#f46d43'],[1,'#a50026']],colorbar:{title:{text:'净流入（亿元）',side:'right'},tickformat:'.1f',thickness:17,len:.82},texttemplate:'%{text}',textfont:{size:10,color:'#26342e'},hovertemplate:'<b>%{x}</b><br>%{y}<br>净流入 %{z:.2f} 亿元<br>份额变化 %{customdata:.2f} 亿份<extra></extra>'}],{...layoutBase,height,width,margin:{l:82,r:88,t:18,b:115},hovermode:'closest',xaxis:{type:'category',tickangle:-45,side:'bottom',showgrid:false,fixedrange:true},yaxis:{type:'category',categoryorder:'array',categoryarray:dates.slice().reverse(),showgrid:false,fixedrange:true}},plotCfg);
  };
  function renderRadarNow(){if(!state.radar)return;renderOverview();renderCategoryTable(document.querySelector('#radarCategoryLevel .active')?.dataset.level||'industry');renderSignals();renderHeatmap();window.renderStableFundBehavior?.();requestAnimationFrame(()=>document.querySelectorAll('#radar .js-plotly-plot').forEach(chart=>Plotly.Plots.resize(chart)))}
  installRadarLayout();
  document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>{if(button.dataset.view==='radar')setTimeout(renderRadarNow,40)}));
  fetch('/data/radar.json',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error('radar data unavailable');return response.json()}).then(data=>{state.radar=data;renderOverview();renderIndices();if(document.querySelector('#radar')?.classList.contains('active'))renderRadarNow()}).catch(error=>console.error(error));
})();