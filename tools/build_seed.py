from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd


TABLES_WITH_DATA = ("etf_master", "etf_daily", "etf_group_daily", "metadata")
TABLES_SCHEMA_ONLY = ("etf_flow_estimates", "etf_direct_flow_observations")
WEB_FILES = ("meta.json", "indices.json", "groups.json", "etfs.json", "etf_daily.json", "rankings.json", "heatmap.json", "radar.json", "macro_monitor.json", "stable_fund_behavior.json")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def copy_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    copy_rows: bool,
    where_sql: str = "",
    parameters: tuple = (),
) -> int:
    create_sql = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not create_sql or not create_sql[0]:
        raise RuntimeError(f"source table missing: {table}")
    target.execute(create_sql[0])
    if not copy_rows:
        return 0
    columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
    placeholders = ",".join("?" for _ in columns)
    names = ",".join(f'"{column}"' for column in columns)
    cursor = source.execute(f'SELECT {names} FROM "{table}" {where_sql}', parameters)
    rows = 0
    while True:
        batch = cursor.fetchmany(10_000)
        if not batch:
            break
        target.executemany(f'INSERT INTO "{table}"({names}) VALUES({placeholders})', batch)
        rows += len(batch)
    for sql, in source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)):
        target.execute(sql)
    return rows


def dataframe_table(connection: sqlite3.Connection, frame: pd.DataFrame, table: str, date_columns: tuple[str, ...]) -> int:
    copy = frame.copy()
    for column in date_columns:
        copy[column] = pd.to_datetime(copy[column]).dt.strftime("%Y-%m-%d")
    copy.to_sql(table, connection, if_exists="replace", index=False)
    return len(copy)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-database", required=True)
    parser.add_argument("--groups", required=True)
    parser.add_argument("--indices", required=True)
    parser.add_argument("--macro", required=True)
    parser.add_argument("--web-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--history-start", default="2025-01-01")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    meta = json.loads((Path(args.web_dir) / "meta.json").read_text(encoding="utf-8"))
    cutoff = str(meta["market_latest"])
    archive = output / f"etf-catcher-seed-{cutoff}.zip"
    if archive.exists() and not args.force:
        raise FileExistsError(f"seed archive exists: {archive}")

    with tempfile.TemporaryDirectory(prefix="etf-catcher-seed-") as temp_name:
        temp = Path(temp_name)
        data_dir = temp / "data"
        web_dir = data_dir / "web"
        web_dir.mkdir(parents=True)
        database = data_dir / "etf_catcher.sqlite3"
        source_path = Path(args.source_database).resolve()
        source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(database)
        counts = {}
        try:
            target.execute("PRAGMA journal_mode=DELETE")
            target.execute("PRAGMA synchronous=OFF")
            for table in TABLES_WITH_DATA:
                if table in {"etf_daily", "etf_group_daily"}:
                    counts[table] = copy_table(
                        source, target, table, True, "WHERE trade_date >= ?", (args.history_start,)
                    )
                else:
                    counts[table] = copy_table(source, target, table, True)
            for table in TABLES_SCHEMA_ONLY:
                counts[table] = copy_table(source, target, table, False)
            groups = pd.read_parquet(args.groups)
            indices = pd.read_parquet(args.indices)
            groups = groups.loc[pd.to_datetime(groups["trade_date"]).ge(args.history_start)].copy()
            indices = indices.loc[pd.to_datetime(indices["date"]).ge(args.history_start)].copy()
            counts["panel_group_daily"] = dataframe_table(target, groups, "panel_group_daily", ("trade_date",))
            counts["index_daily"] = dataframe_table(target, indices[["date", "country", "index_code", "index_name", "close", "change_pct", "normalized", "source"]], "index_daily", ("date",))
            macro_text = Path(args.macro).read_text(encoding="utf-8")
            target.execute("CREATE TABLE macro_payload(id INTEGER PRIMARY KEY CHECK(id=1),payload_json TEXT NOT NULL,updated_at TEXT NOT NULL)")
            macro = json.loads(macro_text)
            target.execute("INSERT INTO macro_payload VALUES(1,?,?)", (json.dumps(macro, ensure_ascii=False, separators=(",", ":")), str(macro.get("generated_at") or "")))
            target.execute("CREATE INDEX idx_panel_group_name_date ON panel_group_daily(group_name,trade_date)")
            target.execute("CREATE INDEX idx_index_code_date ON index_daily(index_code,date)")
            target.commit()
            quick = target.execute("PRAGMA quick_check").fetchone()[0]
            if quick != "ok":
                raise RuntimeError(f"seed quick_check failed: {quick}")
        finally:
            source.close()
            target.close()
        compact = sqlite3.connect(database)
        compact.execute("VACUUM")
        compact.close()
        for name in WEB_FILES:
            source_file = Path(args.web_dir) / name
            if not source_file.exists():
                raise FileNotFoundError(source_file)
            shutil.copy2(source_file, web_dir / name)
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now().astimezone().isoformat(),
            "history_start": args.history_start,
            "market_latest": meta.get("market_latest"),
            "flow_latest": meta.get("flow_latest"),
            "database": "data/etf_catcher.sqlite3",
            "database_bytes": database.stat().st_size,
            "database_sha256": digest(database),
            "source_database_sha256": digest(source_path),
            "tables": counts,
            "web_files": list(WEB_FILES),
            "sources": ["同花顺iFinD衍生数据", "交易所公开数据", "美国财政部", "FRED", "Yahoo Finance Chart API"],
            "data_notice": "See DATA_NOTICE.md in the code repository before redistribution or use.",
        }
        (temp / "seed-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(temp.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(temp))
    result = {**manifest, "archive": str(archive), "archive_bytes": archive.stat().st_size, "archive_sha256": digest(archive)}
    (output / "seed-release-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
