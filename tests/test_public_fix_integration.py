import json
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import build_macro_monitor_data as macro
import server
from ensure_macro_cache import needs_refresh
from test_macro_freshness import payload

ROOT = Path(__file__).resolve().parents[1]


def test_public_ai_uses_published_interval_not_selected_etf(tmp_path, monkeypatch):
    db = tmp_path / 'test.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.executescript('''
          CREATE TABLE etf_master(etf_code TEXT,etf_name TEXT,exchange TEXT,asset_class TEXT,
            category_l1 TEXT,category_l2 TEXT,tracking_index_code TEXT,tracking_index_name TEXT,enabled INTEGER);
          CREATE TABLE etf_daily(trade_date TEXT,etf_code TEXT,close REAL,pct_change REAL,fund_share REAL,
            fund_scale REAL,net_flow REAL,amount REAL,flow_source TEXT,data_status TEXT);
          CREATE TABLE panel_group_daily(trade_date TEXT,group_name TEXT,net_flow_yi REAL);
        ''')
        for code in ('510300', '510310', '510330', '159919'):
            conn.execute('INSERT INTO etf_master VALUES (?,?,?,?,?,?,?,?,?)', (code, code+'ETF', 'SH', 'stock', '宽基', '沪深300', '', '', 1))
            for day, flow in [('2026-09-14', 10), ('2026-09-15', 20), ('2026-09-16', 99999)]:
                conn.execute('INSERT INTO etf_daily VALUES (?,?,?,?,?,?,?,?,?,?)', (day, code, 1, 1, 1, 1, flow, 1, 'iFinD', 'ok'))
        conn.execute('INSERT INTO panel_group_daily VALUES (?,?,?)', ('2026-09-15', '科技（半导体）', 3.5))
    (tmp_path / 'meta.json').write_text(json.dumps({'flow_latest':'2026-09-15'}), encoding='utf-8')
    monkeypatch.setattr(server, 'DATABASE', db)
    monkeypatch.setattr(server, 'WEB_DATA', tmp_path)
    text, coverage = server.local_research_context({'etf_code':'510300'}, '最近一天ETF净流入前十')
    assert coverage['etfs'] == []
    rank = next(s for s in json.loads(text) if '排名' in s['type'])
    assert rank['rows'][0]['net_flow'] == 20
    assert coverage['date_range']['end'] == '2026-09-15'
    text, coverage = server.local_research_context({}, '9月14日到9月15日核心沪深300ETF资金流')
    total = next(s for s in json.loads(text) if s['type'] == '四只核心沪深300ETF区间合计')
    assert total['net_flow'] == 120 and total['complete']
    text, coverage = server.local_research_context({}, '9月15日半导体资金流')
    group = next(s for s in json.loads(text) if s['type'].startswith('分类历史'))
    assert group['rows'][0]['net_flow_yi'] == 3.5


def test_macro_incremental_checks_all_siblings(monkeypatch):
    old = {'tabs': {'credit_pmi': {'series': [
        {'id':sid, 'points':[{'date':day, 'value':50.0}]}
        for sid, day in [('manufacturing_pmi','2026-08-31'), ('composite_pmi','2026-08-31'), ('non_manufacturing_pmi','2026-07-31')]
    ]}}}
    captured = {}
    def run(*args, **kwargs):
        captured.update(json.loads(kwargs['input']))
        return SimpleNamespace(stdout='{"results":{},"errors":{}}')
    monkeypatch.setattr(macro.subprocess, 'run', run)
    macro.run_ifind('2026-09-16', old)
    assert 'pmi' in captured['keys']
    assert captured['starts']['pmi'] == '2026-08'


def test_macro_cache_assessment_changes_trigger_repair():
    data = payload()
    data['target_date'] = '2026-09-04'
    data['refresh_status'] = 'success'
    data['freshness'] = macro.evaluate_macro_freshness(data, '2026-09-04')
    assert not needs_refresh(data, '2026-09-04')
    data['freshness'] = {'status':'pass'}
    assert needs_refresh(data, '2026-09-04')


def test_macro_node_only_queries_requested_keys_and_stops_on_quota(tmp_path):
    caller = tmp_path / 'call-node.js'
    caller.write_text("exports.call=async function(){require('fs').appendFileSync(process.env.CALL_LOG,'call\\n');return {message:'用户使用工具已超限'};};", encoding='utf-8')
    log = tmp_path / 'calls.txt'
    env = dict(os.environ, IFIND_SKILL_DIR=str(tmp_path), CALL_LOG=str(log))
    script = str(ROOT / 'backend/ifind_macro_data.js')
    result = subprocess.run(['node', script], input=json.dumps({'end':'2026-09-16','keys':['money','pmi'],'starts':{'money':'2026-08','pmi':'2026-08'},'target_months':{'money':'2026-08','pmi':'2026-08'}}), text=True, encoding='utf-8', capture_output=True, env=env, check=True)
    assert json.loads(result.stdout)['errors']['money'] == 'IFIND_QUOTA_EXHAUSTED'
    assert len(log.read_text().splitlines()) == 1
