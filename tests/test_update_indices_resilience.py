from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "update_indices.py"
SPEC = importlib.util.spec_from_file_location("update_indices", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def success_payload(answer: str = "ok") -> bytes:
    inner = {"data": json.dumps({"answer": answer}, ensure_ascii=False)}
    outer = {"data": {"result": {"content": [{"text": json.dumps(inner, ensure_ascii=False)}]}}}
    return json.dumps(outer, ensure_ascii=False).encode("utf-8")


class UpdateIndicesResilienceTests(unittest.TestCase):
    def test_retries_and_persists_node_error_text(self):
        failed = subprocess.CompletedProcess(["node"], 1, stdout=b"", stderr="服务暂时不可用".encode("utf-8"))
        passed = subprocess.CompletedProcess(["node"], 0, stdout=success_payload("指数结果"), stderr=b"")
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(MODULE, "CALL_STATUS", Path(folder) / "status.json"), mock.patch.object(
            MODULE.subprocess, "run", side_effect=[failed, passed]
        ) as run, mock.patch.object(MODULE.time, "sleep") as sleep:
            answer = MODULE.call_ifind("查询沪深300", retry_delays=(0.1,))
            status = json.loads((Path(folder) / "status.json").read_text(encoding="utf-8"))

        self.assertEqual(answer, "指数结果")
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(0.1)
        self.assertEqual(status["status"], "pass")
        self.assertEqual(status["attempts"][0]["stderr"], "服务暂时不可用")
        command_script = run.call_args_list[0].args[0][2]
        self.assertIn("Buffer.from", command_script)
        self.assertNotIn("查询沪深300", command_script)

    def test_final_failure_contains_last_node_error(self):
        failed = subprocess.CompletedProcess(["node"], 2, stdout=b"", stderr=b"quota exhausted")
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(MODULE, "CALL_STATUS", Path(folder) / "status.json"), mock.patch.object(
            MODULE.subprocess, "run", return_value=failed
        ), mock.patch.object(MODULE.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "quota exhausted"):
                MODULE.call_ifind("query", retry_delays=(0.0, 0.0))
            status = json.loads((Path(folder) / "status.json").read_text(encoding="utf-8"))

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["attempt_count"], 3)

    def test_semantic_quota_error_is_not_recorded_as_pass(self):
        passed_process = subprocess.CompletedProcess(
            ["node"], 0, stdout=success_payload("用户使用工具已超限 "), stderr=b""
        )
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(
            MODULE, "CALL_STATUS", Path(folder) / "status.json"
        ), mock.patch.object(MODULE.subprocess, "run", return_value=passed_process):
            answer = MODULE.call_ifind("query", retry_delays=())
            status = json.loads((Path(folder) / "status.json").read_text(encoding="utf-8"))

        self.assertIn("超限", answer)
        self.assertEqual(status["status"], "semantic_error")
        self.assertIn("超限", status["attempts"][-1]["semantic_error"])

    def test_tencent_kline_parser_and_change_pct_use_previous_close(self):
        payload = {
            "data": {
                "sh000300": {
                    "day": [
                        ["2026-09-03", "4500", "4510", "4520", "4490", "1"],
                        ["2026-09-04", "4510", "4555.1", "4560", "4500", "1"],
                    ]
                }
            }
        }
        parsed = MODULE.parse_tencent_kline(payload, "000300.SH")
        self.assertEqual(parsed[-1]["close"], 4555.1)
        self.assertEqual(parsed[-1]["source"], "Tencent historical K-line")

        base = pd.DataFrame(
            [{"date": pd.Timestamp("2026-09-02"), "index_code": "000300.SH", "close": 4500.0}]
        )
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
        response.__exit__.return_value = False

        empty_payload = {"data": {"sh000001": {"day": []}, "sh000688": {"day": []}}}
        empty_response = mock.MagicMock()
        empty_response.__enter__.return_value.read.return_value = json.dumps(empty_payload).encode("utf-8")
        empty_response.__exit__.return_value = False
        with mock.patch.object(MODULE, "urlopen", side_effect=[empty_response, response, empty_response]):
            rows, _ = MODULE.fetch_tencent_indices("2026-09-03", "2026-09-04", base, retry_delays=())

        hs300 = rows.loc[rows["index_code"] == "000300.SH"].sort_values("date")
        self.assertAlmostEqual(float(hs300.iloc[0]["change_pct"]), (4510 / 4500 - 1) * 100)
        self.assertAlmostEqual(float(hs300.iloc[1]["change_pct"]), (4555.1 / 4510 - 1) * 100)


if __name__ == "__main__":
    unittest.main()
