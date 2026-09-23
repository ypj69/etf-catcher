import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import collect_ifind_with_fallback as route
import collect_ifind_python_api as native
import ifind_native_config as config
import ingest_ifind_direct_flows as ingest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('message', ['用户使用工具已超限', '额度不足', '额度已用完', 'IFIND_QUOTA_EXHAUSTED', 'insufficient quota'])
def test_quota_tokens(message):
    assert route.is_quota_exhausted(message)


@pytest.mark.parametrize('code,message,expected,calls', [
    (0, '', 'ifind_mcp', 1),
    (1, 'network timeout', 'ifind_mcp', 1),
    (1, '429 请求过于频繁', 'ifind_mcp', 1),
    (1, '用户使用工具已超限', 'ifind_python_api', 2),
])
def test_routing(tmp_path, monkeypatch, code, message, expected, calls):
    observed = []
    def run(command):
        observed.append(command)
        return subprocess.CompletedProcess(command, code if len(observed) == 1 else 0, '', message if len(observed) == 1 else '')
    monkeypatch.setattr(route, 'run', run)
    monkeypatch.setattr(route, 'load_credentials', lambda: ('test', 'not-a-real-secret'))
    monkeypatch.setattr(route, 'STATUS_PATH', tmp_path / 'status.json')
    monkeypatch.setattr(sys, 'argv', ['route', '--jobs', 'jobs.json', '--output', 'out.jsonl'])
    if code:
        with pytest.raises(SystemExit) as result:
            route.main()
        assert result.value.code == (0 if calls == 2 else 1)
    else:
        route.main()
    assert len(observed) == calls
    state = json.loads(route.STATUS_PATH.read_text())
    assert state['route'] == expected
    assert state['fallback_used'] == (calls == 2)


def test_missing_credentials_fails_without_native_call(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(route, 'run', lambda cmd: calls.append(cmd) or subprocess.CompletedProcess(cmd, 1, '额度不足', ''))
    def missing():
        raise RuntimeError('Run configure-ifind.ps1')
    monkeypatch.setattr(route, 'load_credentials', missing)
    monkeypatch.setattr(route, 'STATUS_PATH', tmp_path / 'status.json')
    monkeypatch.setattr(sys, 'argv', ['route', '--jobs', 'jobs', '--output', 'out'])
    with pytest.raises(SystemExit):
        route.main()
    assert len(calls) == 1
    assert json.loads(route.STATUS_PATH.read_text())['reason'] == 'native_credentials_unavailable'


def test_environment_credentials_must_be_pair(monkeypatch):
    monkeypatch.setenv('IFIND_API_USERNAME', 'sample-user')
    monkeypatch.delenv('IFIND_API_PASSWORD', raising=False)
    with pytest.raises(RuntimeError, match='both'):
        config.load_credentials()
    monkeypatch.setenv('IFIND_API_PASSWORD', 'sample-password')
    assert config.load_credentials() == ('sample-user', 'sample-password')


def test_dpapi_decryption_errors_do_not_leak(tmp_path, monkeypatch):
    path = tmp_path / 'account.dpapi'
    path.write_text('encrypted-placeholder')
    monkeypatch.setattr(config, 'CREDENTIAL_PATH', path)
    for key in ('IFIND_API_USERNAME', 'IFIND_API_PASSWORD'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='sensitive-value'))
    with pytest.raises(RuntimeError, match='Cannot decrypt') as error:
        config.load_credentials()
    assert 'sensitive-value' not in str(error.value)


def job(code, day='2026-09-22'):
    return {'job_id': code+'_'+day, 'codes':[code], 'ths_codes':[code+'.SH'], 'start_date':day, 'end_date':day}


def test_native_resume_units_source_and_empty_retry(tmp_path, monkeypatch):
    jobs = [job('510300'), job('510500')]
    input_path = tmp_path / 'jobs.json'
    output = tmp_path / 'results.jsonl'
    input_path.write_text(json.dumps(jobs))
    previous = dict(jobs[0], status='success', answer='|证券代码|日期|\n|---|---|\n|510300|2026-09-22|')
    output.write_text(json.dumps(previous)+'\n')
    observed, logouts = [], []
    def bd(codes, indicators, params, fmt):
        observed.append((codes, indicators, params, fmt))
        return SimpleNamespace(errorcode=0, dataVol=3, data=[{'thscode':'510500.SH', 'table':{
            'ths_fund_shares_fund':[100], 'ths_fund_scale_fund':[200], 'ths_netcashflow_fund':[-3]}}])
    monkeypatch.setitem(sys.modules, 'iFinDPy', SimpleNamespace(THS_BD=bd, THS_iFinDLogin=lambda *a:0, THS_iFinDLogout=lambda:logouts.append(True)))
    monkeypatch.setattr(native, 'load_credentials', lambda: ('fake', 'fake'))
    monkeypatch.setattr(native, 'load_universe', lambda: ({}, {}))
    monkeypatch.setattr(sys, 'argv', ['native', '--jobs', str(input_path), '--output', str(output), '--pause-seconds', '0'])
    native.main()
    assert len(observed) == 1 and observed[0][0] == ['510500.SH']
    assert observed[0][2] == '2026-09-22;2026-09-22;2026-09-22'
    assert len(logouts) == 1
    records, _ = ingest.extract_records(output, '2026-09-22')
    assert records['510500']['fund_scale'] == 200
    assert records['510500']['direct_net_flow'] == -3
    assert records['510500']['source'] == 'iFinD_Python_API_THS_BD'
    native.main()
    assert len(observed) == 1  # all completed: no further SDK request
    assert native.markdown_answer([], ['510500.SH'], '2026-09-22', {})[1] == 0


@pytest.mark.parametrize('reply', ["{message:'额度不足'}", "{data:{result:{content:[{text:'empty'}]}}}"])
def test_node_semantic_errors_exit_nonzero(tmp_path, reply):
    (tmp_path / 'call-node.js').write_text('exports.call=async()=>('+reply+');', encoding='utf-8')
    jobs = tmp_path / 'jobs.json'
    jobs.write_text(json.dumps([job('510300')]))
    result = subprocess.run(['node', str(ROOT/'scripts/collect_ifind_incremental.js'), '--jobs', str(jobs),
        '--output', str(tmp_path/'out.jsonl'), '--attempts','1','--concurrency','1'],
        env=dict(os.environ, IFIND_SKILL_DIR=str(tmp_path)), capture_output=True, text=True, encoding='utf-8')
    assert result.returncode != 0
    assert ('IFIND_QUOTA_EXHAUSTED' if '额度' in reply else 'IFIND_JOB_FAILED') in result.stderr


def test_public_contract():
    text = (ROOT/'scripts/update_one_day.ps1').read_text(encoding='utf-8')
    assert 'collect_ifind_with_fallback.py' in text
    assert 'collect_ifind_incremental.js' not in text
    ignore = (ROOT/'.gitignore').read_text()
    assert 'config/ifind-native.local.dpapi' in ignore
    assert 'vendor/' in ignore
    assert 'ifind_api_credentials.local.json' not in (ROOT/'scripts/collect_ifind_python_api.py').read_text(encoding='utf-8')


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI integration')
def test_dpapi_roundtrip_synthetic_account(tmp_path, monkeypatch):
    path = tmp_path / '账户.dpapi'
    for key in ('IFIND_API_USERNAME', 'IFIND_API_PASSWORD'):
        monkeypatch.delenv(key, raising=False)
    script = "Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1') -ErrorAction Stop; [Console]::InputEncoding=[Text.UTF8Encoding]::new($false); [Console]::In.ReadToEnd() | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString"
    payload = json.dumps({'username':'测试账号', 'password':'synthetic-only-非真实'}, ensure_ascii=False)
    encrypted = subprocess.run(['powershell.exe','-NoProfile','-Command',script], input=payload,
        capture_output=True, text=True, encoding='utf-8', check=True).stdout.strip()
    assert 'synthetic' not in encrypted
    path.write_text(encrypted, encoding='ascii')
    monkeypatch.setattr(config, 'CREDENTIAL_PATH', path)
    assert config.load_credentials() == ('测试账号', 'synthetic-only-非真实')


@pytest.mark.parametrize('mode', ['empty','error'])
def test_native_failure_retries_and_preserves_success(tmp_path, monkeypatch, mode):
    inputs, output = tmp_path/'jobs.json', tmp_path/'out.jsonl'
    inputs.write_text(json.dumps([job('510500')]))
    prefix = json.dumps(dict(job('510300'), status='success', answer='|a|\n|--|\n|1|'))+'\n'
    output.write_text(prefix)
    calls, logouts = [], []
    def bd(*args):
        calls.append(args)
        return SimpleNamespace(errorcode=0 if mode=='empty' else -1, data=[], dataVol=0)
    monkeypatch.setitem(sys.modules, 'iFinDPy', SimpleNamespace(THS_BD=bd, THS_iFinDLogin=lambda *a:0, THS_iFinDLogout=lambda:logouts.append(1)))
    monkeypatch.setattr(native, 'load_credentials', lambda: ('fake', 'fake'))
    monkeypatch.setattr(native, 'load_universe', lambda: ({}, {}))
    monkeypatch.setattr(native.time, 'sleep', lambda _: None)
    monkeypatch.setattr(sys, 'argv', ['native','--jobs',str(inputs),'--output',str(output),'--attempts','2'])
    with pytest.raises(RuntimeError, match='collection failed'):
        native.main()
    assert len(calls) == 2 and len(logouts) == 1
    assert output.read_text().startswith(prefix)
    assert json.loads(output.read_text().splitlines()[-1])['status'] == 'error'


def test_native_failure_propagates(tmp_path, monkeypatch):
    results = iter([subprocess.CompletedProcess([],1,'额度不足',''), subprocess.CompletedProcess([],2,'native failure','')])
    monkeypatch.setattr(route, 'run', lambda _: next(results))
    monkeypatch.setattr(route, 'load_credentials', lambda: ('fake','fake'))
    monkeypatch.setattr(route, 'STATUS_PATH', tmp_path/'status.json')
    monkeypatch.setattr(sys,'argv',['route','--jobs','jobs','--output','out'])
    with pytest.raises(SystemExit) as result:
        route.main()
    assert result.value.code == 2
    assert json.loads(route.STATUS_PATH.read_text())['status'] == 'fail'
