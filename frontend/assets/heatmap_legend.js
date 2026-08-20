(function(){
  const host=document.querySelector('#heatmapChart')?.closest('.panel')?.querySelector('.panel-head');
  const tabs=host?.querySelector('.tabs');
  if(host&&tabs&&!host.querySelector('.heat-meaning')){
    const box=document.createElement('div');box.className='heat-meaning';box.innerHTML='<span class="out">净流出</span><i></i><span>0</span><span class="in">净流入</span>';host.insertBefore(box,tabs);
  }
})();
