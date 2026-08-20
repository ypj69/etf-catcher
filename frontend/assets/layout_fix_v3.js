(function(){
  const css=document.createElement('link');css.rel='stylesheet';css.href='/assets/layout_fix_v3.css';document.head.appendChild(css);
  const plotIds=['indexChart','flowChart','shareChart','stableFundBehaviorChart','heatmapChart','etfChart','depositMigrationChart','turnoverChart','creditChart','pmiChart','treasuryChart','fedDollarChart'];
  let resizeTimer=0;
  function resizeVisiblePlots(){clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{plotIds.forEach(id=>{const host=document.getElementById(id);if(host&&host.offsetParent!==null&&host.classList.contains('js-plotly-plot')){try{Plotly.Plots.resize(host)}catch(error){console.warn('plot resize failed',id,error)}}})},60)}
  if(typeof renderGroupCharts==='function'){
    const originalRenderGroupCharts=renderGroupCharts;
    renderGroupCharts=function(){const result=originalRenderGroupCharts.apply(this,arguments);requestAnimationFrame(resizeVisiblePlots);return result};
  }
  renderHeatmap=function(){
    const rows=(state.radar?.heatmap||[]).filter(row=>row.group_level===state.heatLevel);
    const dates=[...new Set(rows.map(row=>row.trade_date))].sort().reverse();
    const totals={};rows.forEach(row=>totals[row.group_name]=(totals[row.group_name]||0)+(Number(row.net_flow_yi)||0));
    const groups=[...new Set(rows.map(row=>row.group_name))].sort((a,b)=>totals[b]-totals[a]);
    const map=new Map(rows.map(row=>[`${row.trade_date}|${row.group_name}`,row]));
    const z=dates.map(date=>groups.map(group=>{const value=map.get(`${date}|${group}`)?.net_flow_yi;return value==null?null:Number(value)}));
    const share=dates.map(date=>groups.map(group=>{const value=map.get(`${date}|${group}`)?.share_change_yi;return value==null?null:Number(value)}));
    const values=rows.map(row=>Math.abs(Number(row.net_flow_yi))).filter(Number.isFinite).sort((a,b)=>a-b);
    const cap=Math.max(values[Math.floor(values.length*.9)]||1,.01);
    const host=document.querySelector('#heatmapChart');if(!host)return;
    host.style.minWidth='0';host.style.width='100%';const height=Math.max(430,dates.length*38+120);host.style.height=`${height}px`;
    const annotations=[];
    dates.forEach((date,rowIndex)=>groups.forEach((group,columnIndex)=>{const value=z[rowIndex][columnIndex];if(value==null)return;annotations.push({x:group,y:date,xref:'x',yref:'y',showarrow:false,text:value.toFixed(1),font:{size:10,color:Math.abs(value)>=cap*.43?'#fff':'#17231e'}})}));
    Plotly.react(host,[{x:groups,y:dates,z,customdata:share,type:'heatmap',zmin:-cap,zmax:cap,zmid:0,colorscale:[[0,'#006837'],[.18,'#1a9850'],[.38,'#91cf60'],[.49,'#e8f3bd'],[.5,'#fff7bc'],[.58,'#fdae61'],[.78,'#f46d43'],[1,'#a50026']],colorbar:{title:{text:'净流入（亿元）',side:'right'},tickformat:'.1f',thickness:16,len:.78},hovertemplate:'<b>%{x}</b><br>%{y}<br>净流入 %{z:.2f} 亿元<br>份额变化 %{customdata:.2f} 亿份<extra></extra>'}],{...layoutBase,height,autosize:true,margin:{l:82,r:82,t:14,b:126},hovermode:'closest',annotations,xaxis:{type:'category',tickangle:-48,tickfont:{size:10},side:'bottom',showgrid:false,fixedrange:true,automargin:false},yaxis:{type:'category',categoryorder:'array',categoryarray:dates.slice().reverse(),tickfont:{size:11},showgrid:false,fixedrange:true,automargin:true}},{...plotCfg,responsive:true});
  };
  function polishRadarPlots(){window.renderStableFundBehavior?.();resizeVisiblePlots()}
  document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>{setTimeout(()=>{if(button.dataset.view==='radar'&&state.radar){renderHeatmap();polishRadarPlots()}else resizeVisiblePlots()},120)}));
  document.querySelectorAll('#heatLevel button').forEach(button=>button.addEventListener('click',()=>setTimeout(polishRadarPlots,80)));
  window.addEventListener('resize',resizeVisiblePlots,{passive:true});
  if('ResizeObserver' in window){const observer=new ResizeObserver(resizeVisiblePlots);['.detail-panel','#radar','.heatmap-panel','#macro'].forEach(selector=>{const node=document.querySelector(selector);if(node)observer.observe(node)})}
  setTimeout(()=>{if(document.querySelector('#radar')?.classList.contains('active')&&state.radar){renderHeatmap();polishRadarPlots()}resizeVisiblePlots()},260);
})();
