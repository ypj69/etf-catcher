from __future__ import annotations
import argparse, json, os, tempfile
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);a=p.parse_args();path=Path(a.input)
    if not path.exists(): print(json.dumps({'status':'skipped','reason':'missing'}));return
    latest={};invalid=0
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except json.JSONDecodeError: invalid+=1;continue
        key=row.get('job_id')
        if key: latest[key]=row
    ordered=sorted(latest.values(),key=lambda x:str(x.get('job_id','')))
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent);os.close(fd);tmp=Path(tmp)
    try:
        tmp.write_text(''.join(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n' for x in ordered),encoding='utf-8')
        os.replace(tmp,path)
    finally:
        if tmp.exists(): tmp.unlink()
    print(json.dumps({'status':'pass','unique':len(ordered),'invalid':invalid,'output':str(path)},ensure_ascii=False))
if __name__=='__main__':main()
