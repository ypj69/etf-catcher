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
    }catch(_){/* A malformed table must not discard other indicators. */}
  }
  return tables;
}

function hasColumn(tables,include,exclude=[]){
  return (tables||[]).some(table=>(table.columns||[]).some(column=>{
    const text=String(column);
    return include.every(token=>text.includes(token))&&!exclude.some(token=>text.includes(token));
  }));
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
  let quotaExhausted=false;
  for(const key of keys){
    const query=queries[key]; if(!query)continue;
    try{
      const response=await call('edb','get_edb_data',{query});
      if(/用户使用工具已超限|IFIND_QUOTA_EXHAUSTED|额度.*耗尽/.test(JSON.stringify(response))){
        errors[key]='IFIND_QUOTA_EXHAUSTED';quotaExhausted=true;break;
      }
      results[key]=unpack(response);
      if(!results[key].length)errors[key]='No usable indicator table returned';
    }
    catch(error){
      const message=String(error?.message||error);
      errors[key]=message.slice(0,500);
      if(/用户使用工具已超限|IFIND_QUOTA_EXHAUSTED|额度.*耗尽/.test(message)){quotaExhausted=true;break;}
    }
  }
  // Natural-language multi-indicator replies can silently omit one requested
  // column while still returning success. Retry only the missing monthly field.
  const fallbacks={
    money:[
      {id:'m1',include:['M1'],query:`中国M1同比（${compact(starts.money)}-${compact(targetMonths.money)}），逐月返回日期、数值和单位`},
      {id:'m2',include:['M2'],query:`中国M2同比（${compact(starts.money)}-${compact(targetMonths.money)}），逐月返回日期、数值和单位`}
    ],
    pmi:[
      {id:'manufacturing',include:['制造业','PMI'],exclude:['非制造业'],query:`中国官方制造业PMI（${compact(starts.pmi)}-${compact(targetMonths.pmi)}），逐月返回日期和数值`},
      {id:'non_manufacturing',include:['非制造业'],query:`中国非制造业商务活动指数（${compact(starts.pmi)}-${compact(targetMonths.pmi)}），逐月返回日期和数值`},
      {id:'composite',include:['综合','PMI'],query:`中国综合PMI产出指数（${compact(starts.pmi)}-${compact(targetMonths.pmi)}），逐月返回日期和数值`}
    ],
    deposits:[
      {id:'household',include:['住户'],query:`中国金融机构人民币住户存款年内累计增加额（${compact(starts.deposits)}-${compact(targetMonths.deposits)}），逐月返回日期、数值，单位万亿元`},
      {id:'nbfi',include:['非银行'],query:`中国非银行业金融机构存款年内累计增加额（${compact(starts.deposits)}-${compact(targetMonths.deposits)}），逐月返回日期、数值，单位万亿元`}
    ]
  };
  for(const [key,specs] of Object.entries(fallbacks)){
    if(quotaExhausted)break;
    if(!keys.includes(key))continue;
    for(const spec of specs){
      if(hasColumn(results[key],spec.include,spec.exclude))continue;
      try{const response=await call('edb','get_edb_data',{query:spec.query});
        if(/用户使用工具已超限|IFIND_QUOTA_EXHAUSTED|额度.*耗尽/.test(JSON.stringify(response))){errors[key]='IFIND_QUOTA_EXHAUSTED';quotaExhausted=true;break;}
        results[key]=(results[key]||[]).concat(unpack(response));}
      catch(error){
        const message=String(error?.message||error);
        errors[`${key}.${spec.id}`]=message.slice(0,500);
        if(/用户使用工具已超限|IFIND_QUOTA_EXHAUSTED|额度.*耗尽/.test(message)){quotaExhausted=true;break;}
      }
    }
    if(specs.every(spec=>hasColumn(results[key],spec.include,spec.exclude)))delete errors[key];
  }
  process.stdout.write(JSON.stringify({status:Object.keys(errors).length?'partial':'pass',retrieved_at:new Date().toISOString(),requested_keys:keys,results,errors}));
}
main().catch(error=>{process.stderr.write(String(error?.stack||error));process.exit(1)});
