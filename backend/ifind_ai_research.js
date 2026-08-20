'use strict';
const path=require('path');
const os=require('os');
const {call}=require(path.join(process.env.IFIND_SKILL_DIR||path.join(os.homedir(),'.codex','skills','ifind-finance-data'),'call-node.js'));

function answerOf(result){
  return (result?.data?.result?.content||[]).map(item=>{
    try{const outer=JSON.parse(item.text||'{}');const inner=typeof outer.data==='string'?JSON.parse(outer.data):outer.data;return inner?.answer||item.text||''}
    catch(_){return item.text||''}
  }).join('\n');
}

async function main(){
  const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);
  const payload=JSON.parse(chunks.join('').replace(/^\uFEFF/,'')||'{}');
  const question=String(payload.question||'').slice(0,1800);
  const subject=String(payload.subject||'').slice(0,300);
  const results=[];
  const end=new Date(),start=new Date(end.getTime()-45*86400000);
  const endDate=end.toISOString().slice(0,10),startDate=start.toISOString().slice(0,10);
  const dateHint=`当前日期${endDate}，查询区间${startDate}至${endDate}`;
  const add=async(server,tool,params,label)=>{const raw=await call(server,tool,params),body=answerOf(raw).slice(0,16000),link=body.match(/\[([^\]]{2,200})\]\((https?:\/\/[^)]+)\)/),rawUrl=link?.[2]||(body.match(/https?:\/\/[^\s)>\]"']+/)||[])[0]||'https://www.51ifind.com/',url=rawUrl.replace(/[\\.,，。]+$/,''),published=(body.match(/20\d{2}[-年\/]\d{1,2}[-月\/]\d{1,2}/)||[])[0]||null;results.push({source:`iFinD/${label}`,title:link?.[1]||label,url,published_at:published,retrieved_at:new Date().toISOString(),requested_start:startDate,requested_end:endDate,text:body})};
  if(subject&&/行情|走势|涨跌|净值|价格|成交|份额|规模|收益|盘口/.test(question)){
    await add('fund','get_fund_market_performance',{query:`${dateHint}。${subject} ${question}。请返回该区间内所需指标、数值与单位，不得返回其他年份。`.trim()},'基金行情与业绩');
  }else if(/新闻|资讯|政策|事件|公告|催化|发生|消息|近期|最新|会议|概率|FedWatch|联网|搜索/.test(question)){
    await add('news','search_news',{query:`${subject} ${question}`.trim(),time_start:startDate,time_end:endDate,size:5},'新闻资讯');
  }else if(/指数|大盘|沪深|上证|科创|创业板|标普|纳斯达克|日经|韩国|美股|日韩/.test(question)&&!subject){
    await add('index','index_data',{query:`${dateHint}。${question}。请返回区间内最近20个交易日的日期、收盘点数和涨跌幅，不得返回其他年份。`},'指数数据');
  }else{
    await add('fund','get_fund_market_performance',{query:`${dateHint}。${subject} ${question}。请返回该区间内所需指标、数值与单位，不得返回其他年份。`.trim()},'基金行情与业绩');
  }
  process.stdout.write(JSON.stringify({status:'pass',results}));
}
main().catch(error=>{process.stderr.write(String(error?.stack||error));process.exit(1)});
