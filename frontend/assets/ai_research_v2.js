(function(){
  if(!document.querySelector('link[href="/assets/ai_research_v2.css"]')){const style=document.createElement('link');style.rel='stylesheet';style.href='/assets/ai_research_v2.css';document.head.appendChild(style)}
  const button=document.querySelector('#askAi'),online=document.querySelector('#aiOnline'),answer=document.querySelector('#aiAnswer');
  if(!button||!online||!answer)return;
  const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function inlineMarkdown(value){
    const links=[];
    let text=String(value??'').replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,(_,label,url)=>{try{const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol))return label;const index=links.push(`<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`)-1;return `\u0000LINK${index}\u0000`}catch(_){return label}});
    text=escapeHtml(text).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/(^|[^*])\*([^*]+)\*/g,'$1<em>$2</em>');
    return text.replace(/\u0000LINK(\d+)\u0000/g,(_,index)=>links[Number(index)]||'');
  }
  function renderMarkdown(value){
    const lines=String(value??'').replace(/\r/g,'').split('\n'),html=[];let list='';
    const closeList=()=>{if(list){html.push(`</${list}>`);list=''}};
    for(const raw of lines){const line=raw.trim();if(!line){closeList();continue}if(/^(```|---+$)/.test(line))continue;
      const heading=line.match(/^(#{1,4})\s+(.+)$/);if(heading){closeList();html.push(`<h${Math.min(4,heading[1].length+2)}>${inlineMarkdown(heading[2])}</h${Math.min(4,heading[1].length+2)}>`);continue}
      const bullet=line.match(/^[-*]\s+(.+)$/),ordered=line.match(/^\d+[.、]\s*(.+)$/),nextList=bullet?'ul':ordered?'ol':'';
      if(nextList){if(list!==nextList){closeList();list=nextList;html.push(`<${list}>`)}html.push(`<li>${inlineMarkdown((bullet||ordered)[1])}</li>`);continue}
      closeList();const quote=line.match(/^>\s*(.+)$/);html.push(quote?`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`:`<p>${inlineMarkdown(line)}</p>`);
    }
    closeList();return html.join('');
  }
  const source=document.createElement('div');source.id='aiSources';source.className='ai-source-note';source.textContent='默认读取本地ETF、行业、市场情绪与宏观监控数据；联网仅按需触发。';answer.insertAdjacentElement('afterend',source);
  button.onclick=async()=>{
    const q=document.querySelector('#aiQuestion').value.trim();if(!q)return;
    answer.textContent='正在检索本地研究数据，并判断是否需要联网补充…';source.textContent='数据检索中';button.disabled=true;
    try{
      const response=await fetch('/api/ai/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,etf_code:state.selectedEtf,online:online.checked})});
      const data=await response.json();if(response.ok)answer.innerHTML=renderMarkdown(data.answer);else answer.textContent=data.error;
      if(response.ok){
        const local=data.sources?.[0]?.coverage||{},range=local.date_range||{},parts=[range.start?`本地查询：${range.start}—${range.end}（${range.trading_days}个交易日）`:'本地查询：所问区间无记录'];
        if(range.explicit_dates)parts.push(`指定区间 ${range.requested_start}—${range.requested_end}`);
        if(range.unavailable_after)parts.push(`已发布数据截至 ${range.published_latest}`);
        if(local.macro_as_of)parts.push(`宏观数据截至 ${local.macro_as_of}`);
        if(local.etfs?.length)parts.push(`ETF ${local.etfs.map(x=>`${x.code}（${x.start}—${x.end}）`).join('、')}`);
        if(local.index_start)parts.push(`全球指数 ${local.index_start}—${local.index_end}`);
        if(local.ranking)parts.push(`${local.ranking.type}：${local.ranking.returned_rows}只，完整样本${local.ranking.eligible_etfs}只，排除缺失${local.ranking.excluded_incomplete_etfs}只`);
        if(local.stable_fund)parts.push('资金雷达：四只核心沪深300ETF（稳定资金行为代理）');
        if(local.omitted_series?.length)parts.push('部分历史明细因容量限制省略，区间合计仍按完整数据计算');
        const safeParts=parts.map(escapeHtml);
        const web=(data.sources||[]).slice(1).map(item=>{const label=[item.title||item.name,item.published_at?`发布 ${item.published_at}`:'',item.retrieved_at?`检索 ${item.retrieved_at}`:''].filter(Boolean).join(' · ');return item.url?`<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(label)}</a>`:esc(label)});
        if(web.length)safeParts.push(`联网来源：${web.join('、')}`);if(data.warning)safeParts.push(escapeHtml(data.warning));source.innerHTML=safeParts.join('｜');
      }else source.textContent='未完成数据检索';
    }catch(error){answer.textContent=`请求失败：${error}`;source.textContent='本地服务连接失败'}finally{button.disabled=false}
  };
  fetch('/api/ai/status').then(r=>r.json()).then(x=>{const status=document.querySelector('#aiStatus');if(x.configured)status.textContent=`已连接 DeepSeek（${x.model}）· 本地全量研究数据 · 按需联网`}).catch(()=>{});
})();
