'use strict';
const path=require('path');
const os=require('os');
const {call}=require(path.join(process.env.IFIND_SKILL_DIR||path.join(os.homedir(),'.codex','skills','ifind-finance-data'),'call-node.js'));

function unpack(result){
  const tables=[];
  for(const item of result?.data?.result?.content||[]){
    try{
      const outer=JSON.parse(item.text||'{}');
      const inner=typeof outer.data==='string'?JSON.parse(outer.data):outer.data;
      for(const entry of inner?.datas||[]){
        const table=entry?.data;
        if(table&&Array.isArray(table.data)){
          const columns=table.columns||[];
          const rows=table.data.map(row=>Array.isArray(row)?Object.fromEntries(columns.map((column,index)=>[column,row[index]])):row);
          tables.push({rows,columns,attrs:table.attrs||{},answer:inner.answer||''});
        }
      }
    }catch(_){}
  }
  return tables;
}

async function main(){
  const chunks=[];for await(const chunk of process.stdin)chunks.push(chunk);
  const payload=JSON.parse(chunks.join('').replace(/^\uFEFF/,'')||'{}');
  const end=String(payload.end||new Date().toISOString().slice(0,10));
  const keys=Array.isArray(payload.keys)?payload.keys:[];
  const starts=payload.starts||{};
  const targetMonths=payload.target_months||{};
  const compact=month=>String(month||'').replace('-','');
  const queries={
    turnover:`沪深两市股票成交额日度数据（${String(starts.turnover||end).replaceAll('-','')}-${end.replaceAll('-','')}），分别返回沪市股票成交金额、深市A股总成交金额、沪深两市股票成交金额，逐日返回日期和数值`,
    credit_increment:`中国社会融资规模增量当月值（${compact(starts.credit_increment)}-${compact(targetMonths.credit_increment)}），逐月返回日期和数值`,
    credit_stock:`中国社会融资规模存量同比（${compact(starts.credit_stock)}-${compact(targetMonths.credit_stock)}），逐月返回日期和数值`,
    household_long_term:`金融机构新增人民币贷款:住户:中长期（${compact(starts.household_long_term)}-${compact(targetMonths.household_long_term)}），逐月返回日期、数值和单位`,
    enterprise_long_term:`中国新增人民币贷款：企（事）业单位中长期贷款当月值（${compact(starts.enterprise_long_term)}-${compact(targetMonths.enterprise_long_term)}），逐月返回日期、数值和单位`,
    money:`中国M1同比、M2同比（${compact(starts.money)}-${compact(targetMonths.money)}），逐月返回日期、数值、单位`,
    pmi:`中国官方制造业PMI、非制造业商务活动指数、综合PMI产出指数（${compact(starts.pmi)}-${compact(targetMonths.pmi)}），逐月返回日期和数值`,
    pmi_new_orders:`中国官方制造业采购经理指数（PMI）新订单指数（${compact(starts.pmi_new_orders)}-${compact(targetMonths.pmi_new_orders)}），逐月返回日期、数值和单位`,
    deposits:`中国金融机构人民币住户存款年内累计增加额、非银行业金融机构存款年内累计增加额（${compact(starts.deposits)}-${compact(targetMonths.deposits)}），逐月返回日期、数值，单位万亿元`
  };
  const results={},errors={};
  for(const key of keys){
    if(!queries[key])continue;
    try{results[key]=unpack(await call('edb','get_edb_data',{query:queries[key]}));}
    catch(error){errors[key]=String(error?.message||error).slice(0,500);}
  }
  process.stdout.write(JSON.stringify({status:Object.keys(errors).length?'partial':'pass',retrieved_at:new Date().toISOString(),requested_keys:keys,results,errors}));
}
main().catch(error=>{process.stderr.write(String(error?.stack||error));process.exit(1)});
