"""CI 门禁入口（ci_drc_gate）测试——退出码契约与报告结构。

这是 GitHub Action 的调用入口：退出码语义是外部契约
（0=通过 / 1=DRC 未过门禁 / 2=输入缺失），必须锁定。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ci_drc_gate

CASE_OK = ROOT / "cases" / "case_003_stm32_4layer"   # DRC 全绿
CASE_WARN = ROOT / "cases" / "case_002_aircon_kicad"  # 有 warning


def test_gate_pass_exit_code_zero(tmp_path):
    if not CASE_OK.exists():
        pytest.skip("case_003 缺失")
    rep = ci_drc_gate.run_gate(str(CASE_OK), str(tmp_path))
    assert rep["verdict"] == "PASS"
    assert rep["exit_code"] == 0
    assert rep["gate"]["allowed"] is True


def test_gate_fail_when_threshold_lowered(tmp_path):
    """阈值设为 warning 时，含 warning 的板应 FAIL（退出码 1）。"""
    if not CASE_WARN.exists():
        pytest.skip("case_002 缺失")
    rep = ci_drc_gate.run_gate(str(CASE_WARN), str(tmp_path), severity_threshold="warning")
    assert rep["verdict"] == "FAIL"
    assert rep["exit_code"] == 1
    assert rep["gate"]["counts"]["warning"] > 0


def test_gate_input_error_exit_code_two(tmp_path):
    """无外形层 → INPUT_ERROR + 退出码 2（区别于门禁失败）。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    rep = ci_drc_gate.run_gate(str(empty), str(tmp_path / "out"))
    assert rep["verdict"] == "INPUT_ERROR"
    assert rep["exit_code"] == 2
    assert "外形层" in rep["message"]


def test_report_written_and_structured(tmp_path):
    """报告必须落盘且含外部消费所需字段。"""
    if not CASE_OK.exists():
        pytest.skip("case_003 缺失")
    ci_drc_gate.run_gate(str(CASE_OK), str(tmp_path))
    report = json.loads((tmp_path / "drc-report.json").read_text(encoding="utf-8"))
    for k in ("verdict", "exit_code", "gate", "issues", "dxf", "threshold"):
        assert k in report
    assert Path(report["dxf"]).exists(), "DXF 必须实际生成"


def test_dxf_artifact_generated(tmp_path):
    if not CASE_OK.exists():
        pytest.skip("case_003 缺失")
    rep = ci_drc_gate.run_gate(str(CASE_OK), str(tmp_path))
    p = Path(rep["dxf"])
    assert p.is_file() and p.stat().st_size > 500


def test_main_returns_exit_code(tmp_path):
    """CLI 入口返回的退出码即门禁结论（供 Action / shell 消费）。"""
    if not CASE_OK.exists():
        pytest.skip("case_003 缺失")
    rc = ci_drc_gate.main([str(CASE_OK), "--out", str(tmp_path), "--quiet"])
    assert rc == 0
    rc2 = ci_drc_gate.main([str(tmp_path / "nope"), "--out", str(tmp_path / "o2"), "--quiet"])
    assert rc2 == 2


def test_issues_carry_source_citation(tmp_path):
    """报告里的每条问题必须带出处（工业级可追溯要求）。"""
    if not CASE_WARN.exists():
        pytest.skip("case_002 缺失")
    rep = ci_drc_gate.run_gate(str(CASE_WARN), str(tmp_path), severity_threshold="warning")
    assert rep["issues"]
    for i in rep["issues"]:
        assert i.get("source"), f"{i['code']} 缺出处"
