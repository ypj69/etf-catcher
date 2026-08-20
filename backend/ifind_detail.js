'use strict';
const path=require('path');
const os=require('os');
const skillDir=process.env.IFIND_SKILL_DIR||path.join(os.homedir(),'.codex','skills','ifind-finance-data');
const {call}=require(path.join(skillDir,'call-node.js'));
const code=String(process.argv[2]||'').replace(/\D/g,'');
if(!/^\d{6}$/.test(code))throw new Error('ETF code is invalid');
const suffix=code.startsWith('5')?'SH':'SZ';
const symbol=`${code}.${suffix}`;
function text(result){return (result?.data?.result?.content||[]).map(x=>x.text||'').join('\n')}
async function main(){
  const [profile,portfolio,quotes]=await Promise.all([
    call('fund','get_fund_profile',{query:`查询${symbol}的基金简称、全称、成立日、上市日、基金管理人、基金经理、投资类型、跟踪指数名称、跟踪指数代码、管理费率和托管费率`}),
    call('fund','get_fund_portfolio',{query:`查询${symbol}最新一期前十大重仓股，列出证券代码、证券名称、持仓市值、持仓数量、占基金资产净值比例和报告期`}),
    call('fund','fund_highfreq_quotes',{symbols:symbol,indicators:'最新价,今开,最高,最低,涨跌幅,成交额,成交量,IOPV净值估值,折溢价',data_mode:'real_time',interval:1})
  ]);
  process.stdout.write(JSON.stringify({profile:text(profile),portfolio:text(portfolio),quotes:text(quotes)}));
}
main().catch(error=>{process.stderr.write(String(error?.stack||error));process.exit(1)});
