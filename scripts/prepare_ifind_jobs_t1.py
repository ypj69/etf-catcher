from __future__ import annotations
import argparse, csv, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(); p.add_argument('--date',required=True); p.add_argument('--output',required=True); p.add_argument('--limit',type=int); a=p.parse_args()
 with (ROOT/'config'/'etf_universe.csv').open(encoding='utf-8-sig',newline='') as h: rows=[r for r in csv.DictReader(h) if r.get('enabled')=='1']
 if a.limit: rows=rows[:a.limit]
 # Public build: only fields consumed by the dashboard. pct_change is derived locally.
 fields='基金份额、基金规模、收盘价和成交额'
 jobs=[]
 for offset in range(0,len(rows),5):
  batch=rows[offset:offset+5]; subjects='、'.join(f"{r['etf_name']}({r['etf_code']}.{r['exchange']})" for r in batch)
  jobs.append({'job_id':f't1_{offset:04d}_{a.date}','codes':[r['etf_code'] for r in batch],'start_date':a.date,'end_date':a.date,'query':f'分别查询{subjects}在{a.date}的{fields}，返回证券代码、证券简称、日期、数值和单位'})
 out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(jobs,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'date':a.date,'etfs':len(rows),'jobs':len(jobs),'output':str(out)},ensure_ascii=False))
if __name__=='__main__': main()
