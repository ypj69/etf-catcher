from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    with (ROOT / "config" / "etf_universe.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("enabled") == "1"]
    if args.limit:
        rows = rows[: args.limit]
    jobs = []
    for offset in range(0, len(rows), 5):
        batch = rows[offset : offset + 5]
        subjects = "、".join(f"{row['etf_code']}.{row['exchange']}" for row in batch)
        query = (
            f"分别查询{subjects}在{args.date}的净流入额。"
            f"交易日期必须固定为{args.date}，不使用最新日期。"
            "返回证券代码、证券简称、日期、净流入额和单位。"
        )
        jobs.append(
            {
                "job_id": f"direct_flow_{offset:04d}_{args.date}",
                "codes": [row["etf_code"] for row in batch],
                "start_date": args.date,
                "end_date": args.date,
                "query": query,
            }
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "pass", "date": args.date, "etfs": len(rows), "jobs": len(jobs), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
