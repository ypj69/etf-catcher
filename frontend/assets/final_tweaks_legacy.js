(function(){
  const baseOpenEtf=openEtf;
  openEtf=async function(code){
    document.body.classList.add('etf-detail-mode');
    return baseOpenEtf(code);
  };
  document.querySelector('#closeDetail')?.addEventListener('click',()=>document.body.classList.remove('etf-detail-mode'));
  document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>{
    if(button.dataset.view!=='market')document.body.classList.remove('etf-detail-mode');
  }));

  renderHeatmap=function(){
    const rows=state.heatmap.filter(x=>x.group_level===state.heatLevel);
    const dates=[...new Set(rows.map(x=>x.trade_date))].sort();
    const groups=[...new Set(rows.map(x=>x.group_name))];
    const values=rows.map(x=>Math.abs(Number(x.net_flow_yi))).filter(Number.isFinite).sort((a,b)=>a-b);
    const cap=values.length?Math.max(values[Math.min(values.length-1,Math.floor(values.length*.92))],.01):1;
    const z=groups.map(g=>dates.map(d=>rows.find(x=>x.group_name===g&&x.trade_date===d)?.net_flow_yi??null));
    const showCellText=state.heatLevel==='broad';
    const text=z.map(line=>line.map(v=>showCellText&&v!=null&&Math.abs(v)>=Math.max(.3,cap*.18)?Number(v).toFixed(1):''));
    const height=state.heatLevel==='industry'?620:Math.max(390,groups.length*42+95);
    const left=state.heatLevel==='industry'?210:150;
    Plotly.react('heatmapChart',[{
      x:dates,y:groups,z,text,type:'heatmap',zmin:-cap,zmax:cap,zmid:0,
      colorscale:[[0,'#075b45'],[.18,'#168269'],[.42,'#a9d8c8'],[.495,'#f4f4ef'],[.505,'#f4f4ef'],[.58,'#efb7ad'],[.82,'#d45b4f'],[1,'#9e2f2b']],
      colorbar:{title:{text:'亿元',side:'top'},tickformat:'.1f',thickness:14,len:.8},
      texttemplate:'%{text}',textfont:{size:10,color:'#26342e'},
      hovertemplate:'<b>%{y}</b><br>%{x}<br>净流入 %{z:.2f} 亿元<extra></extra>'
    }],{
      ...chartLayout({height,margin:{l:left,r:76,t:12,b:54}}),
      height,
      xaxis:{...layoutBase.xaxis,rangebreaks:breaks(),fixedrange:true,tickangle:0},
      yaxis:{automargin:false,fixedrange:true,tickfont:{size:11},showgrid:false,categoryorder:'array',categoryarray:groups.slice().reverse()}
    },plotCfg);
    const chart=document.querySelector('#heatmapChart');
    chart.style.height=`${height}px`;chart.style.minHeight=`${height}px`;
  };

  document.querySelector('#heatmapChart')?.closest('.panel')?.classList.add('heatmap-panel');
  if(state.meta)renderHeatmap();
})();
