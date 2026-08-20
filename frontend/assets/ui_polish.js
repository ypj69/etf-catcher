(function(){
  const priorRenderLive=renderLive;
  function formatValue(label,value){
    const number=Number(value);
    if(!Number.isFinite(number))return value;
    if(label==='涨跌幅'||label==='折溢价')return `${number.toFixed(2)}%`;
    if(label==='成交额')return number>=1e8?`${(number/1e8).toFixed(2)}亿`:number>=1e4?`${(number/1e4).toFixed(2)}万`:number.toLocaleString('zh-CN');
    if(label==='成交量')return number>=1e8?`${(number/1e8).toFixed(2)}亿份`:number>=1e4?`${(number/1e4).toFixed(2)}万份`:`${number.toLocaleString('zh-CN')}份`;
    return number.toLocaleString('zh-CN',{maximumFractionDigits:4});
  }
  renderLive=function(data){
    priorRenderLive(data);
    document.querySelectorAll('.live-metric').forEach(card=>{
      const label=card.querySelector('span')?.textContent||'';
      const value=card.querySelector('strong');
      if(value)value.textContent=formatValue(label,value.textContent);
      if(label==='涨跌幅'&&value){const n=parseFloat(value.textContent);value.classList.toggle('quote-up',n>0);value.classList.toggle('quote-down',n<0)}
    });
  };
})();
