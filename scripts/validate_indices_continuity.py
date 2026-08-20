from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CODES = {"000001.SH", "000300.SH", "000688.SH", "GSPC", "IXIC", "N225", "KS11"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    target = pd.Timestamp(args.date)
    indices = pd.read_parquet(ROOT / "data/processed/indices.parquet")
    indices["date"] = pd.to_datetime(indices["date"])
    recent = indices.loc[indices["date"].between(target - pd.Timedelta(days=14), target)].copy()
    daily = pd.read_parquet(ROOT / "data/processed/etf_daily.parquet", columns=["trade_date"])
    expected_cn = set(pd.to_datetime(daily.loc[pd.to_datetime(daily.trade_date).between(target - pd.Timedelta(days=14), target), "trade_date"]).dt.normalize())
    errors: list[str] = []
    details: dict[str, dict] = {}
    for code in sorted(CODES):
        dates = sorted(set(recent.loc[recent.index_code.eq(code), "date"].dt.normalize()))
        if not dates:
            errors.append(f"{code}: no recent observations")
            continue
        if code.startswith("000"):
            missing = sorted(expected_cn - set(dates))
            if missing:
                errors.append(f"{code}: missing A-share sessions {','.join(x.strftime('%Y-%m-%d') for x in missing)}")
        gaps = [(a, b, (b - a).days) for a, b in zip(dates, dates[1:]) if (b - a).days > 4]
        if gaps:
            errors.append(f"{code}: suspicious gaps {[(str(a.date()), str(b.date()), n) for a,b,n in gaps]}")
        details[code] = {"rows": len(dates), "latest": str(dates[-1].date())}
    report = {"status": "pass" if not errors else "fail", "target_date": args.date, "series": details, "errors": errors}
    out = ROOT / "runtime/index_continuity_validation.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
