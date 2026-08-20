from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etf_flow.direct_flow import DIRECT_FLOW_SOURCE, resolve_direct_or_estimated
from etf_flow.minimal import rebuild_summaries


def resolve(database: Path, target_date: str) -> dict[str, int | str]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    rows = connection.execute(
        """SELECT d.etf_code,d.fund_scale,o.direct_net_flow,e.estimated_net_flow
           FROM etf_daily d
           LEFT JOIN etf_direct_flow_observations o USING(trade_date,etf_code)
           LEFT JOIN etf_flow_estimates e USING(trade_date,etf_code)
           WHERE d.trade_date=?""",
        (target_date,),
    ).fetchall()
    counts: dict[str, int | str] = {"date": target_date, "rows": len(rows)}
    try:
        connection.execute("BEGIN IMMEDIATE")
        for row in rows:
            result = resolve_direct_or_estimated(
                row["direct_net_flow"], row["estimated_net_flow"], row["fund_scale"]
            )
            counts[result.decision] = int(counts.get(result.decision, 0)) + 1
            selected = result.selected
            if result.decision.startswith("direct"):
                connection.execute(
                    """UPDATE etf_daily SET net_flow=?,net_inflow=?,net_outflow=?,flow_source=?,
                       source_field='get_fund_ownership|净流入额',data_status='final',reason_code=NULL,updated_at=?
                       WHERE trade_date=? AND etf_code=?""",
                    (selected, max(selected or 0.0, 0.0), max(-(selected or 0.0), 0.0), DIRECT_FLOW_SOURCE,
                     now, target_date, row["etf_code"]),
                )
            elif result.decision.startswith("estimated"):
                reason = (
                    "DIRECT_FLOW_DISPUTED_ESTIMATE_USED"
                    if result.decision == "estimated_disputed_direct"
                    else "DIRECT_FLOW_MISSING_ESTIMATE_USED"
                )
                connection.execute(
                    """UPDATE etf_daily SET net_flow=?,net_inflow=?,net_outflow=?,
                       flow_source='estimated_share_change',data_status='final',reason_code=?,updated_at=?
                       WHERE trade_date=? AND etf_code=?""",
                    (selected, max(selected or 0.0, 0.0), max(-(selected or 0.0), 0.0),
                     reason, now, target_date, row["etf_code"]),
                )
            else:
                connection.execute(
                    """UPDATE etf_daily SET net_flow=NULL,net_inflow=NULL,net_outflow=NULL,
                       flow_source=NULL,data_status='not_available',reason_code=?,updated_at=?
                       WHERE trade_date=? AND etf_code=?""",
                    (result.decision.upper(), now, target_date, row["etf_code"]),
                )
            connection.execute(
                """INSERT INTO etf_direct_flow_observations(
                       trade_date,etf_code,direct_net_flow,source,source_field,available_at,
                       estimated_net_flow,selected_net_flow,resolution,absolute_difference,
                       relative_difference,resolved_at)
                   VALUES(?,?,?,'iFinD_get_fund_ownership','净流入额',?,?,?,?,?,?,?)
                   ON CONFLICT(trade_date,etf_code) DO UPDATE SET
                       estimated_net_flow=excluded.estimated_net_flow,
                       selected_net_flow=excluded.selected_net_flow,
                       resolution=excluded.resolution,
                       absolute_difference=excluded.absolute_difference,
                       relative_difference=excluded.relative_difference,
                       resolved_at=excluded.resolved_at""",
                (target_date, row["etf_code"], row["direct_net_flow"], now,
                 row["estimated_net_flow"], selected, result.decision,
                 result.absolute_difference, result.relative_difference, now),
            )
        connection.commit()
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        summary_tables = {"etf_master", "etf_group_daily", "etf_flow_top10_daily"}
        if summary_tables <= tables:
            derived = rebuild_summaries(connection, target_date, target_date)
            counts["group_rows"] = derived["groups"]
            counts["top10_rows"] = derived["top10"]
            counts["summary_status"] = "rebuilt"
        elif database.resolve() == (ROOT / "data" / "etf_flow.sqlite3").resolve():
            raise RuntimeError(f"production summary tables missing: {sorted(summary_tables - tables)}")
        else:
            counts["group_rows"] = 0
            counts["top10_rows"] = 0
            counts["summary_status"] = "skipped_minimal_database"
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "data" / "etf_flow.sqlite3"))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = {"status": "pass", **resolve(Path(args.database), args.date)}
    (ROOT / "runtime" / "direct_flow_resolution.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
