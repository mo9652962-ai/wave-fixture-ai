"""case_003：circuit-agent 生成的 4 层板（STM32）——跨仓素材验证。

素材来源：`/d/circuit-agent/build/test_gen_4l/`（circuit-agent 的 4 层板产出，
KiCad 全套命名 + .kicad_pcb），证明本工具可处理**其他 AI EDA 工具生成的**板。

本 case 的特殊价值：
- 唯一含**合格安装孔**（3.2mm）的板 → 定位销走打分算法正常路径（非退回分支）
- 唯一 DRC 全绿的真实板（板小、元件少、避位覆盖完整）
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
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
from interference import get_pcb_board_bounds
from pin_select import qualifies, score_drill

CASE = Path(__file__).resolve().parent.parent / "cases" / "case_003_stm32_4layer"

pytestmark = pytest.mark.skipif(
    not (CASE / "board-Edge_Cuts.gm1").exists(),
    reason="STM32 4 层板 case 文件缺失",
)


@pytest.fixture(scope="module")
def run():
    bp, drills = parse_gerber(str(CASE))
    board = unary_union(bp)
    p1 = FixtureParams()
    sink = make_sink_region(board, p1)
    r1 = SimpleNamespace(
        board_poly=board, sink_poly=sink,
        handles=make_handles(sink, p1), screws=make_screws(sink, p1),
        pins=make_pins(drills, p1, sink_poly=sink),
    )
    r2 = run_phase2(str(CASE), None)
    return SimpleNamespace(board=board, drills=drills, r1=r1, r2=r2, sink=sink)


def test_four_layer_board_parsed(run):
    """4 层板（含 In1_Cu/In2_Cu 内层）的 Edge_Cuts 必须正确识别板框。"""
    b = run.board.bounds
    assert b[2] - b[0] == pytest.approx(37.0, abs=0.1)
    assert b[3] - b[1] == pytest.approx(37.0, abs=0.1)


def test_mounting_hole_produces_qualified_pin(run):
    """3.2mm 安装孔应走打分正常路径产出合格销（非退回分支）。"""
    assert len(run.r1.pins) == 2
    for _x, _y, r in run.r1.pins:
        assert r * 2 >= 1.5, f"销径 {r*2:.2f}mm 过小"


def test_pin_scoring_standard_window(run):
    """3.2mm 孔应命中标准窗口（+4）并通过合格线。"""
    bounds = run.sink.bounds
    hits = [d for d in run.drills if 2.5 <= d[2] <= 4.5]
    assert hits, "期望存在标准窗口孔径的安装孔"
    c = score_drill(hits[0][0], hits[0][1], hits[0][2], bounds)
    assert qualifies(c)


def test_small_board_drc_clean(run):
    """小板 + 避位覆盖完整 → DRC 应全绿（真实板里的正例）。"""
    g = drc.gate(drc.run_drc(run.r1, run.r2))
    assert g["allowed"] is True
    assert g["counts"]["blocking"] == 0 and g["counts"]["error"] == 0


def test_keepouts_and_solder_generated(run):
    """有 mask 层 → 必须生成避位区与上锡区。"""
    assert len(run.r2.avoid_polys) >= 1
    assert len(run.r2.solder_polys) >= 1


def test_board_bounds_from_kicad_matches_gerber(run):
    """KiCad 板框与 Gerber 沉板区范围应一致（跨格式一致性）。"""
    pb = get_pcb_board_bounds(str(CASE / "board.kicad_pcb"))
    assert pb is not None
    sb = run.sink.bounds
    # 沉板区 = 板框外扩 0.2mm
    assert (sb[2] - sb[0]) == pytest.approx((pb[2] - pb[0]) + 0.4, abs=0.15)
    assert (sb[3] - sb[1]) == pytest.approx((pb[3] - pb[1]) + 0.4, abs=0.15)


def test_cross_tool_compatibility():
    """跨工具兼容性：本 case 由 circuit-agent（另一个 AI EDA 工具）生成，
    必须能被本工具完整处理——证明输出格式遵循标准而非某工具私有约定。"""
    bp, drills = parse_gerber(str(CASE))
    assert bp and drills, "circuit-agent 产出的板无法解析"
