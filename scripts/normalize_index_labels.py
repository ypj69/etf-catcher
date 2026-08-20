from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
LABELS={
 '000001.SH':('中国','上证指数'),'000300.SH':('中国','沪深300'),'000688.SH':('中国','科创50'),
 'GSPC':('美国','标普500指数'),'IXIC':('美国','纳斯达克综合指数'),
 'N225':('日本','日经225指数'),'KS11':('韩国','韩国综合指数'),
}
def main():
 path=ROOT/'data'/'processed'/'indices.parquet';x=pd.read_parquet(path)
 for code,(country,name) in LABELS.items():
  mask=x['index_code'].eq(code);x.loc[mask,'country']=country;x.loc[mask,'index_name']=name
 x.to_parquet(path,index=False);print(json.dumps({'status':'pass','normalized':int(x.index_code.isin(LABELS).sum())},ensure_ascii=False))
if __name__=='__main__':main()
