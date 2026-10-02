"""真实板干涉分析测试（KiCad case_002）——3D 路径的首个真板覆盖。

背景（2026-10-02 真板实测暴露 2 个缺陷）：
1. **判定逻辑 OR→AND**：原「3D 重叠>5mm³ **或** 2D 覆盖<0.85」会把与治具完全不相交的
   元件也报干涉（真实板 36/36 全报）；改为**仅 3D 实体重叠超阈值才判干涉**，
   2D 覆盖降级为归因信息。
2. **板框解析**：`get_pcb_board_bounds` 只支持 `gr_rect`，而真实板用 `gr_line` 四条边围成
   → 返回 None → 坐标变换退化为纯 Y 翻转、未做平移对齐 → 元件坐标整体错位。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.ops import unary_union

from fixture_3d import Fixture3DParams, build_fixture_3d, export_stl
from fixture_phase1 import (
    FixtureParams,
    make_handles,
    make_pins,
    make_screws,
    make_sink_region,
    parse_gerber,
)
from fixture_phase2 import run_phase2
from interference import (
    INTERFERENCE_RATIO_THRESHOLD,
    INTERFERENCE_VOLUME_THRESHOLD_MM3,
    analyze_interference,
    get_pcb_board_bounds,
    parse_kicad_pcb,
    transform_pcb_to_gerber,
)

CASE = Path(__file__).resolve().parent.parent / "cases" / "case_002_aircon_kicad"
PCB = next(CASE.glob("*.kicad_pcb"), None)

pytestmark = pytest.mark.skipif(
    PCB is None or not (CASE / "aircon-v6-routed-Edge_Cuts.gm1").exists(),
    reason="KiCad case 文件缺失",
)


def test_board_bounds_from_gr_lines():
    """板框必须能从 gr_line（四条边围成）解析——真实板常见写法，非 gr_rect。"""
    pb = get_pcb_board_bounds(str(PCB))
    assert pb is not None, "板框解析返回 None（gr_line 支持缺失）"
    xmin, ymin, xmax, ymax = pb
    assert (xmax - xmin) == pytest.approx(100.0, abs=0.1)
    assert (ymax - ymin) == pytest.approx(80.0, abs=0.1)


def test_component_transform_aligns_to_gerber_frame():
    """元件坐标变换后必须落在板/沉板区范围内（对齐验证）。"""
    pb = get_pcb_board_bounds(str(PCB))
    bp, _dr = parse_gerber(str(CASE))
    sink = make_sink_region(unary_union(bp), FixtureParams())
    comps = parse_kicad_pcb(str(PCB))
    assert comps
    sb = sink.bounds
    inside = 0
    for c in comps:
        tx, ty = transform_pcb_to_gerber(c["x"], c["y"], pb, sb)
        if sb[0] - 5 <= tx <= sb[2] + 5 and sb[1] - 5 <= ty <= sb[3] + 5:
            inside += 1
    # 绝大多数元件应落在板框内（允许少量板边/板外的丝印件）
    assert inside / len(comps) > 0.85, f"仅 {inside}/{len(comps)} 个元件落在板框内"


@pytest.fixture(scope="module")
def interference(tmp_path_factory):
    bp, drills = parse_gerber(str(CASE))
    board = unary_union(bp)
    p1 = FixtureParams()
    sink = make_sink_region(board, p1)
    _r1 = SimpleNamespace(  # 仅用于驱动 pins 计算（避免 lint 未使用告警）
        board_poly=board, sink_poly=sink,
        handles=make_handles(sink, p1), screws=make_screws(sink, p1),
        pins=make_pins(drills, p1, sink_poly=sink),
    )
    r2 = run_phase2(str(CASE), None)
    mesh = build_fixture_3d(sink, r2.avoid_polys, r2.solder_polys, r2.outer_poly, Fixture3DParams())
    out = tmp_path_factory.mktemp("interf") / "fx.stl"
    export_stl(mesh, str(out))
    comps = parse_kicad_pcb(str(PCB))
    reports = analyze_interference(
        str(out), comps,
        pcb_bounds=get_pcb_board_bounds(str(PCB)),
        gerber_bounds=sink.bounds,
        avoid_polys=r2.avoid_polys,
    )
    return SimpleNamespace(comps=comps, reports=reports)


def test_no_mass_false_positives(interference):
    """关键回归：不应把所有元件都报成干涉（原 OR 逻辑导致 36/36 全报）。

    阈值从「绝对值 5mm³」改为「绝对值 0.5mm³ 或 相对占比 5%」后，小元件
    （0402/0603，自身体积 ~0.2mm³）不再被阈值掩盖——报告数上升是预期的，
    但每条都应有物理依据（重叠可观 或 避位覆盖不足）。
    """
    n, total = len(interference.reports), len(interference.comps)
    assert n < total, f"{n}/{total} 元件被报干涉——疑似全量误报回归"
    for r in interference.reports:
        has_basis = (
            r["overlap_mm3"] > INTERFERENCE_VOLUME_THRESHOLD_MM3
            or r.get("overlap_ratio", 0) > INTERFERENCE_RATIO_THRESHOLD
        )
        assert has_basis, f"{r['ref']} 报告缺少物理依据: {r}"


def test_every_reported_overlap_exceeds_threshold(interference):
    """每条干涉的 3D 重叠必须真超阈值（判定语义 = 实体真的压到）。"""
    for r in interference.reports:
        assert r["overlap_mm3"] > INTERFERENCE_VOLUME_THRESHOLD_MM3, r


def test_large_components_flagged_with_low_avoid_coverage(interference):
    """大体积元件（继电器/数码管）若未被避位区覆盖，必须报出来——真实设计缺陷。"""
    big = [r for r in interference.reports if r["overlap_mm3"] > 500]
    assert big, "真实板上的大元件应有干涉报告"
    for r in big:
        assert r["cover_ratio"] < 0.85, f"{r['ref']} 已被避位覆盖却报重叠"


def test_cover_ratio_reported_as_attribution(interference):
    """2D 覆盖作为归因信息必须存在（不再触发判定，但要能解释原因）。"""
    for r in interference.reports:
        assert "cover_ratio" in r and "avoid_covered" in r
        assert 0.0 <= r["cover_ratio"] <= 1.0
