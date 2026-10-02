"""CI/脚本入口：从 Gerber 生成治具 + 跑 DRC 门禁，产出报告并以退出码表达结论。

用途：
- GitHub Action（action.yml）调用：`python -m ci_drc_gate <gerber_dir> [--out DIR]`
- 本地 CI / 脚本编排
- 非零退出码：0=通过，1=DRC 未过门禁，2=输入缺失（外形层未找到）

设计原则：与库内判定保持同一份真相（直接调 drc.run_drc / drc.gate），
不在 CI 层复制规则。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from shapely.ops import unary_union

import drc
from fixture_phase1 import (
    FixtureParams,
    make_handles,
    make_pins,
    make_screws,
    make_sink_region,
    parse_gerber,
)
from fixture_phase2 import run_phase2


def run_gate(gerber_dir: str, out_dir: str | None = None,
             severity_threshold: str = "error") -> dict:
    """生成治具几何 → 跑 DRC → 写报告。返回 {verdict, exit_code, gate, issues, dxf}。"""
    out = Path(out_dir or "fixture-out")
    out.mkdir(parents=True, exist_ok=True)

    board_polys, drills = parse_gerber(gerber_dir)
    if not board_polys:
        return {"verdict": "INPUT_ERROR", "exit_code": 2, "gate": None, "issues": [],
                "message": "未找到外形层（Edge_Cuts / GM1 / GKO）", "dxf": None}

    board = unary_union(board_polys)
    p1 = FixtureParams()
    sink = make_sink_region(board, p1)
    r1 = SimpleNamespace(
        board_poly=board, sink_poly=sink,
        handles=make_handles(sink, p1),
        screws=make_screws(sink, p1),
        pins=make_pins(drills, p1, sink_poly=sink),
    )
    dxf_path = out / "fixture.dxf"
    r2 = run_phase2(gerber_dir, str(dxf_path))

    issues = drc.run_drc(r1, r2)
    gate = drc.gate(issues)

    # 门禁阈值：默认 error（blocking 与 error 均阻断）
    order = {"info": 0, "warning": 1, "error": 2, "blocking": 3}
    threshold = order.get(severity_threshold, 2)
    breach = any(order.get(i["severity"], 0) >= threshold for i in issues)
    verdict = "FAIL" if breach else "PASS"

    report = {
        "verdict": verdict,
        "exit_code": 1 if breach else 0,
        "gate": gate,
        "issues": issues,
        "dxf": str(dxf_path),
        "threshold": severity_threshold,
        "totals": getattr(r2, "totals", None),
    }
    (out / "drc-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="治具生成 + DRC 门禁（CI 入口）")
    ap.add_argument("gerber_dir", help="Gerber 文件目录")
    ap.add_argument("--out", default="fixture-out", help="产物与报告输出目录")
    ap.add_argument("--severity-threshold", default="error",
                    choices=["info", "warning", "error", "blocking"],
                    help="触发失败的严重度（默认 error）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    rep = run_gate(args.gerber_dir, args.out, args.severity_threshold)

    if rep["verdict"] == "INPUT_ERROR":
        print(f"::error::{rep['message']}" if _in_ci() else f"[error] {rep['message']}")
        return rep["exit_code"]

    g = rep["gate"]
    line = (f"治具 DRC: {rep['verdict']} | blocking {g['counts']['blocking']} / "
            f"error {g['counts']['error']} / warning {g['counts']['warning']} "
            f"| 共 {g['total']} 条")
    print(line if args.quiet else f"\n{line}\n报告: {args.out}/drc-report.json")

    for i in rep["issues"][:20]:
        prefix = "::error::" if (i["severity"] in ("blocking", "error") and _in_ci()) else \
                 ("::warning::" if _in_ci() else "")
        print(f"{prefix}[{i['severity']}] {i['title']} — {i['detail']}（出处: {i.get('source', '-')}）")
    if len(rep["issues"]) > 20:
        print(f"…另 {len(rep['issues']) - 20} 条见报告")
    return rep["exit_code"]


def _in_ci() -> bool:
    import os

    return os.environ.get("GITHUB_ACTIONS") == "true"


if __name__ == "__main__":
    sys.exit(main())
