(function(){
  const footer=document.querySelector('footer');
  if(footer) footer.textContent='面板更新至最新上一个完整交易日；iFinD自动任务请设在08:30以后。实时详情按需联网查询，空值不填0。仅用于研究，不构成投资建议。';
  window.addEventListener('error',event=>document.documentElement.dataset.etfJsError=String(event.message||event.error||'unknown'));
  window.addEventListener('unhandledrejection',event=>document.documentElement.dataset.etfJsError=String(event.reason||'unhandled rejection'));
  const load=src=>new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=src;script.onload=resolve;script.onerror=reject;document.body.appendChild(script)});
  load('/assets/final_tweaks_legacy.js')
    .then(()=>load('/assets/radar_fix_v2.js'))
    .then(()=>load('/assets/stable_fund_behavior.js'))
    .then(()=>load('/assets/layout_fix_v3.js'))
    .then(()=>load('/assets/ai_research_v2.js'))
    .catch(error=>console.error('ETF frontend enhancement failed',error));
})();
