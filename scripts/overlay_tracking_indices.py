from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    source=ROOT/'data/processed/tracking_indices.json'; target=ROOT/'data/web/etfs.json'
    if not source.exists(): print('{"status":"skipped"}'); return
    mapping={x['etf_code']:x for x in json.loads(source.read_text(encoding='utf-8'))}; etfs=json.loads(target.read_text(encoding='utf-8')); changed=0
    for x in etfs:
        m=mapping.get(str(x['etf_code']))
        if m:
            if m.get('tracking_index_name'): x['tracking_index_name']=m['tracking_index_name']
            if m.get('tracking_index_code'): x['tracking_index_code']=m['tracking_index_code']
            changed+=1
    target.write_text(json.dumps(etfs,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(json.dumps({'status':'pass','overlaid':changed},ensure_ascii=False))
if __name__=='__main__': main()
