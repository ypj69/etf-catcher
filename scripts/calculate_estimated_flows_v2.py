from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from etf_flow.estimated_flow_v2 import rebuild_estimated_flows
def main():
 p=argparse.ArgumentParser();p.add_argument('--database',default=str(ROOT/'data'/'etf_flow.sqlite3'));p.add_argument('--start',required=True);p.add_argument('--end',required=True);a=p.parse_args()
 c=sqlite3.connect(a.database)
 try:r=rebuild_estimated_flows(c,a.start,a.end)
 finally:c.close()
 print(json.dumps({'status':'pass',**r},ensure_ascii=False))
if __name__=='__main__':main()
