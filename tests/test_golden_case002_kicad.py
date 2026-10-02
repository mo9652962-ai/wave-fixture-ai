"""多来源真实板测试（case_002：KiCad 空调板 / case_001：EasyEDA 板）。

检验跨来源兼容性：KiCad 命名（B_Cu/B_Mask/Edge_Cuts.gm1）、大量钻孔（169）、
无安装孔的小板（销径告警）、真实避位/上锡区生成（20/24 个区域）。
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
from pin_select import pin_diameter, qualifies, score_drill

CASE = Path(__file__).resolve().parent.parent / "cases" / "case_002_aircon_kicad"

pytestmark = pytest.mark.skipif(
    not (CASE / "aircon-v6-routed-Edge_Cuts.gm1").exists(),
    reason="KiCad case 文件缺失",
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
    return SimpleNamespace(board=board, drills=drills, r1=r1, r2=r2)


def test_kicad_layer_naming_parsed(run):
    """KiCad 命名规范（Edge_Cuts.gm1 等）必须被正确识别。"""
    b = run.board.bounds
    assert b[2] - b[0] == pytest.approx(100.0, abs=0.1)
    assert b[3] - b[1] == pytest.approx(80.0, abs=0.1)
    assert run.board.area == pytest.approx(100.0 * 80.0, rel=0.01)


def test_many_drills_parsed(run):
    """169 个钻孔必须全部解析（含多种孔径）。"""
    assert len(run.drills) == 169
    dias = {round(d[2], 3) for d in run.drills}
    assert len(dias) >= 4  # 多种孔径


def test_pin_selection_collapses_candidates(run):
    """169 个钻孔应被精选为 2 个定位销（而非全部当销）——避免污染避位区。"""
    assert len(run.r1.pins) == 2, f"期望精选 2 个销，实得 {len(run.r1.pins)}"


def test_pins_not_in_avoid_regions(run):
    """精选后的定位销不应落入避位区（旧的「全部钻孔当销」会大量违规）。"""
    from shapely.geometry import Point

    for x, y, _r in run.r1.pins:
        for ai, av in enumerate(run.r2.avoid_polys):
            assert not av.contains(Point(x, y)), f"销 ({x:.1f},{y:.1f}) 落入避位区 {ai+1}"


def test_real_board_generates_keepouts_and_solder(run):
    """有焊盘层的真实板必须生成避位区与上锡区（区别于 case_001 的纯外形板）。"""
    assert len(run.r2.avoid_polys) > 0, "有 B_Mask 层却未生成避位区"
    assert len(run.r2.solder_polys) > 0, "有 F_Mask 层却未生成上锡区"


def test_tiny_pin_diameter_flagged(run):
    """全板只有细信号过孔时，销径过小必须报 warning（真实约束，不静默）。"""
    issues = drc.run_drc(run.r1, run.r2)
    codes = {i["code"] for i in issues}
    if any(r * 2 < 1.5 for _x, _y, r in run.r1.pins):
        assert "PIN_DIAMETER_TOO_SMALL" in codes
        assert all(i["severity"] == "warning" for i in issues if i["code"] == "PIN_DIAMETER_TOO_SMALL")


def test_drc_allows_production_without_blocking(run):
    """该真实板无 blocking/error → 应允许生产（warning 不阻断）。"""
    g = drc.gate(drc.run_drc(run.r1, run.r2))
    assert g["counts"]["blocking"] == 0 and g["counts"]["error"] == 0
    assert g["allowed"] is True


def test_pin_select_secondary_diameter_window():
    """次优孔径窗口（1.8-2.5mm）应能合格——小板常见 2.0mm 安装孔。"""
    bounds = (0, 0, 100, 80)
    c = score_drill(50, 40, 2.0, bounds)
    assert "次优" in " ".join(c.reasons)
    assert c.score >= 2.0


def test_pin_diameter_clamped():
    """销径钳制在 [1.5, 4.0]mm（对标竞品 pinDiameterMm）。"""
    assert pin_diameter(0.5) == 1.5
    assert pin_diameter(6.0) == 4.0
    assert pin_diameter(3.0) == pytest.approx(2.9)


def test_qualifies_requires_threshold_or_nthp():
    bounds = (0, 0, 100, 80)
    assert qualifies(score_drill(50, 40, 3.0, bounds)) is True       # 标准窗口 +4
    assert qualifies(score_drill(50, 40, 2.2, bounds, nthp=True)) is True  # NPTH 放行
    assert qualifies(score_drill(50, 40, 0.3, bounds)) is False      # 细过孔不合格
