"""Repair macro-only publication failures without collecting ETF data again."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from macro_freshness import evaluate_macro_freshness

ROOT = Path(__file__).resolve().parents[1]


def needs_refresh(payload, target):
    current = evaluate_macro_freshness(payload, target)
    return (payload.get('target_date') != target or payload.get('refresh_status') != 'success'
            or current['status'] != 'pass' or payload.get('freshness') != current)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', required=True)
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    path = ROOT / 'data/web/macro_monitor.json'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        payload = {}
    if needs_refresh(payload, args.date):
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_macro_monitor_data.py'), '--target-date', args.date], check=True)
        payload = json.loads(path.read_text(encoding='utf-8'))
        if needs_refresh(payload, args.date):
            raise RuntimeError('Macro data remains incomplete; inspect macro_monitor.json freshness and errors')
    subprocess.run([sys.executable, str(ROOT / 'scripts/sync_authoritative_cache.py'), '--database', args.database], check=True)


if __name__ == '__main__':
    main()
