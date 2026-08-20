(function(){
  const params=new URLSearchParams(location.search);
  if(!params.has('ui_test'))return;
  async function waitFor(check,timeout=30000){const start=Date.now();while(Date.now()-start<timeout){const value=check();if(value)return value;await new Promise(r=>setTimeout(r,200))}throw new Error('ui test timeout')}
  async function run(){
    await waitFor(()=>state.meta&&document.querySelectorAll('.group-item').length);
    const sticky=getComputedStyle(document.querySelector('.index-panel'));
    const result={sticky_position:sticky.position,sticky_top:sticky.top};
    if(params.get('ui_test')==='detail'){
      await openEtf('510300');await waitFor(()=>document.querySelectorAll('.holdings-table tbody tr').length);
      const detail=document.querySelector('#etfDetail'),grid=document.querySelector('#liveDetail');
      Object.assign(result,{profile_items:document.querySelectorAll('.profile-grid>div').length,holding_rows:document.querySelectorAll('.holdings-table tbody tr').length,quote_cards:document.querySelectorAll('.live-metric').length,detail_overflow:detail.scrollWidth>detail.clientWidth,live_overflow:grid.scrollWidth>grid.clientWidth});
    }else{
      document.querySelector('[data-view="radar"]').click();await waitFor(()=>document.querySelector('#heatmapChart .plot-container'));
      const heat=document.querySelector('#heatmapChart');Object.assign(result,{heat_height:heat.getBoundingClientRect().height,heat_plot:true,heat_rows:[...new Set(state.heatmap.filter(x=>x.group_level===state.heatLevel).map(x=>x.group_name))].length});
    }
    const node=document.createElement('pre');node.id='ui-test-result';node.textContent=JSON.stringify(result);document.body.appendChild(node);document.title='UI_TEST_PASS '+JSON.stringify(result);
  }
  run().catch(e=>{document.title='UI_TEST_FAIL '+e.message});
})();
