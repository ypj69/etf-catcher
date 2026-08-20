from __future__ import annotations
import argparse,json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--date',required=True);a=p.parse_args();cut=pd.Timestamp(a.date);data=ROOT/'data'/'processed';counts={}
 for name,col in [('etf_daily.parquet','trade_date'),('group_daily.parquet','trade_date'),('corporate_actions.parquet','trade_date'),('indices.parquet','date')]:
  path=data/name;x=pd.read_parquet(path);x[col]=pd.to_datetime(x[col]);before=len(x);x=x.loc[x[col].le(cut)].copy();x.to_parquet(path,index=False,compression='zstd' if name in {'etf_daily.parquet','group_daily.parquet'} else None);counts[name]={'before':before,'after':len(x),'latest':str(x[col].max().date()) if len(x) else None}
 print(json.dumps({'status':'pass','cutoff':a.date,'files':counts},ensure_ascii=False))
if __name__=='__main__':main()
