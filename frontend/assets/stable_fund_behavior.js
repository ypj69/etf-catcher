(function(){
  const style=document.createElement('link');style.rel='stylesheet';style.href='/assets/stable_fund_behavior.css';document.head.appendChild(style);
  let payload=null;
  const finite=value=>value==null?null:Number(value);
  const fmt=(value,digits=2)=>value==null||!Number.isFinite(Number(value))?'-':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits});
  const signed=value=>value==null||!Number.isFinite(Number(value))?'-':`${Number(value)>=0?'+':''}${fmt(value)}%`;
  const stateClass=code=>code==='reverse_replenishment'?'is-replenishment':code==='high_retreat'?'is-retreat':code==='warming_up'?'is-warming':'is-neutral';

  function renderMetrics(latest,data){
    const host=document.querySelector('#stableFundMetrics');if(!host)return;
    host.innerHTML=[
      ['市场位置（120日）',`${fmt(latest.market_position_120_pct)}%`,latest.market_position_120_pct<=20?'低位区':latest.market_position_120_pct>=80?'高位区':'区间中部'],
      ['4只ETF份额20日变化',signed(latest.share_change_20d_pct),`合计份额 ${fmt(latest.total_share_yi)} 亿份`],
      ['历史Z分数',fmt(latest.z120_hist),`前${data.method.z_window}个观测，不含当日；至少${data.method.z_min_periods}期`]
    ].map(([label,value,note])=>`<div class="stable-fund-metric"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('');
  }

  function renderChart(data){
    const host=document.querySelector('#stableFundBehaviorChart');if(!host)return;
    const rows=data.series||[],dates=rows.map(row=>row.trade_date),byDate=new Map(rows.map(row=>[row.trade_date,row]));
    const events=data.events||[];
    const shapes=[
      {type:'rect',xref:'paper',yref:'y2',x0:0,x1:1,y0:0,y1:20,fillcolor:'rgba(14,107,80,.08)',line:{width:0},layer:'below'},
      {type:'rect',xref:'paper',yref:'y2',x0:0,x1:1,y0:80,y1:100,fillcolor:'rgba(185,55,49,.06)',line:{width:0},layer:'below'},
      {type:'line',xref:'paper',yref:'y',x0:0,x1:1,y0:0,y1:0,line:{color:'#8f9c96',width:1}},
      {type:'line',xref:'paper',yref:'y2',x0:0,x1:1,y0:20,y1:20,line:{color:'#68a58b',width:1,dash:'dot'}},
      {type:'line',xref:'paper',yref:'y2',x0:0,x1:1,y0:80,y1:80,line:{color:'#d18f8a',width:1,dash:'dot'}}
    ];
    const eventTrace=(code,color,symbol,textPosition)=>{
      const selected=events.filter(event=>event.state_code===code).map(event=>({event,row:byDate.get(event.start_date)})).filter(item=>item.row);
      return {x:selected.map(item=>item.event.start_date),y:selected.map(item=>finite(item.row.share_change_20d_pct)),type:'scatter',mode:'markers+text',name:code==='reverse_replenishment'?'稳定资金正在逆向回补':'稳定资金正在高位撤退',showlegend:false,cliponaxis:false,marker:{size:11,color,symbol,line:{color:'#fff',width:1}},text:selected.map(item=>item.event.state_label),textposition:textPosition,textfont:{size:11,color},customdata:selected.map(item=>[item.row.market_position_120_pct,item.row.z120_hist]),hovertemplate:'%{x}<br>%{text}<br>20日份额变化 %{y:.2f}%<br>市场位置 %{customdata[0]:.2f}%<br>Z分数 %{customdata[1]:.2f}<extra></extra>'};
    };
    const traces=[
      {x:dates,y:rows.map(row=>finite(row.share_change_20d_pct)),type:'bar',name:'20日份额变化',marker:{color:rows.map(row=>finite(row.share_change_20d_pct)>=0?'rgba(38,132,98,.78)':'rgba(190,78,72,.75)')},hovertemplate:'%{x}<br>20日份额变化 %{y:.2f}%<extra></extra>'},
      eventTrace('reverse_replenishment','#0e6b50','triangle-up','top center'),
      eventTrace('high_retreat','#b24640','triangle-down','bottom center'),
      {x:dates,y:rows.map(row=>finite(row.total_share_yi)),xaxis:'x3',yaxis:'y3',type:'bar',name:'4只核心ETF总份额',marker:{color:'rgba(36,79,117,.72)'},hovertemplate:'%{x}<br>4只核心ETF总份额 %{y:.2f} 亿份<extra></extra>'},
      {x:dates,y:rows.map(row=>finite(row.market_position_120_pct)),xaxis:'x2',yaxis:'y2',type:'scatter',mode:'lines',name:'上证120日位置',line:{color:'#244f75',width:2},hovertemplate:'%{x}<br>上证120日位置 %{y:.2f}%<extra></extra>'},
      {x:[null],y:[null],xaxis:'x2',yaxis:'y2',type:'scatter',mode:'markers',name:'低位区间（≤20%）',marker:{symbol:'square',size:10,color:'rgba(14,107,80,.16)'},hoverinfo:'skip'},
      {x:[null],y:[null],xaxis:'x2',yaxis:'y2',type:'scatter',mode:'markers',name:'高位区间（≥80%）',marker:{symbol:'square',size:10,color:'rgba(185,55,49,.14)'},hoverinfo:'skip'}
    ];
    const axis={showgrid:true,gridcolor:'#e8ecea',zeroline:false,tickfont:{size:10,color:'#65736c'},fixedrange:true};
    Plotly.react(host,traces,{...layoutBase,height:780,autosize:true,showlegend:true,hovermode:'x unified',bargap:.18,margin:{l:78,r:24,t:16,b:72},shapes,
      legend:{orientation:'h',x:.5,y:-.07,xanchor:'center',yanchor:'top',font:{size:10,color:'#617069'},bgcolor:'rgba(255,255,255,.88)'},
      xaxis:{domain:[0,1],anchor:'y',showticklabels:false,showgrid:false,fixedrange:true},
      yaxis:{...axis,domain:[.72,1],title:{text:'20日总份额变化（%）',standoff:8}},
      xaxis2:{domain:[0,1],anchor:'y2',matches:'x',showticklabels:false,showgrid:false,fixedrange:true},
      yaxis2:{...axis,domain:[.40,.64],range:[-3,103],dtick:20,title:{text:'上证120日位置（%）',standoff:8}},
      xaxis3:{domain:[0,1],anchor:'y3',matches:'x',type:'date',showgrid:false,tickformat:'%Y-%m',dtick:'M1',fixedrange:true},
      yaxis3:{...axis,domain:[0,.32],title:{text:'4只核心ETF总份额（亿份）',standoff:8}}
    },{...plotCfg,responsive:true});
  }

  window.renderStableFundBehavior=function(){
    if(!payload)return;
    const latest=payload.latest||{},badge=document.querySelector('#stableFundState');
    if(badge){badge.className=`stable-fund-state ${stateClass(latest.state_code)}`;badge.innerHTML=`<span>${payload.alert&&payload.alert.active?'重点观察':'当前状态'}</span><strong>${latest.state_label||'-'}</strong>`}
    renderMetrics(latest,payload);renderChart(payload);
    const disclaimer=document.querySelector('.stable-fund-disclaimer');if(disclaimer)disclaimer.textContent=`${payload.disclaimer} 仅当市场位置、20日份额变化与Z分数三项条件同时满足时标注；核心ETF：${payload.core_etfs.join('、')}。`;
  };

  fetch('/data/stable_fund_behavior.json',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error('stable fund behavior data unavailable');return response.json()}).then(data=>{payload=data;window.renderStableFundBehavior()}).catch(error=>{console.error(error);const badge=document.querySelector('#stableFundState');if(badge)badge.textContent='数据暂不可用'});
  document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>{if(button.dataset.view==='radar')setTimeout(()=>window.renderStableFundBehavior(),80)}));
})();
