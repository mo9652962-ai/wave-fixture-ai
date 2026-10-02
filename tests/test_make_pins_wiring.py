"""定位销选点接线测试（make_pins 各分支）——兼容性与兜底路径。

真实验证背景：make_pins 从「全部钻孔都当销」改为「打分精选」后，
三条分支（select=False 旧行为 / sink_poly=None 自动边界 / 无合格候选退回）
此前无直接测试，而它们是向后兼容与真实板兜底的关键。
"""
from __future__ import annotations

import pytest
from shapely.geometry import box

from fixture_phase1 import FixtureParams, make_pins

P = FixtureParams()
SINK = box(0, 0, 100, 80)  # 沉板区 100×80


def test_select_false_returns_all_drills():
    """select=False 必须退回旧行为（全部钻孔成销）——向后兼容/调试用。"""
    drills = [(10.0, 10.0, 3.0), (50.0, 40.0, 1.0), (90.0, 70.0, 0.5)]
    pins = make_pins(drills, P, select=False)
    assert len(pins) == 3
    # 半径 = 孔径/2 - inset
    assert pins[0][2] == pytest.approx(3.0 / 2 - P.pin_inset)


def test_select_false_skips_degenerate():
    """孔径 <= 2×inset 时半径 <=0 → 应被跳过。"""
    pins = make_pins([(1.0, 1.0, 0.1)], P, select=False)
    assert pins == []


def test_select_true_picks_diagonal_pair():
    """默认路径：从多个合格孔中选对角跨距最大的一对。"""
    drills = [(5.0, 5.0, 3.2), (95.0, 75.0, 3.2), (50.0, 40.0, 3.2)]
    pins = make_pins(drills, P, sink_poly=SINK)
    assert len(pins) == 2
    coords = {(round(x, 1), round(y, 1)) for x, y, _r in pins}
    assert coords == {(5.0, 5.0), (95.0, 75.0)}


def test_no_sink_poly_derives_bounds():
    """sink_poly=None 时应用钻孔包围盒 + 20mm padding 派生边界（不崩）。"""
    drills = [(10.0, 10.0, 3.2), (90.0, 70.0, 3.2)]
    pins = make_pins(drills, P, sink_poly=None)
    assert len(pins) == 2, "无 sink_poly 时应仍能选出销"


def test_empty_drills_returns_empty():
    assert make_pins([], P, sink_poly=SINK) == []
    assert make_pins([], P, sink_poly=None) == []


def test_fallback_when_no_qualified_candidate():
    """全为细过孔（孔径远小于窗口）时退回：取最大孔径里对角跨距最大的两个。"""
    drills = [(5.0, 5.0, 0.3), (95.0, 75.0, 0.3), (50.0, 40.0, 0.2)]
    pins = make_pins(drills, P, sink_poly=SINK)
    assert len(pins) == 2, "无合格候选时应退回选最大跨距的一对"
    coords = {(round(x, 1), round(y, 1)) for x, y, _r in pins}
    assert coords == {(5.0, 5.0), (95.0, 75.0)}
    # 退回时销半径有下限 0.5mm（不能给出 0.05mm 的失效销）
    assert all(r >= 0.5 for _x, _y, r in pins)


def test_qualified_pin_uses_actual_diameter():
    """合格孔应使用真实孔径（3.2mm 孔 → 半径 1.5mm），非兜底下限。"""
    pins = make_pins([(5.0, 5.0, 3.2), (95.0, 75.0, 3.2)], P, sink_poly=SINK)
    for _x, _y, r in pins:
        assert r == pytest.approx(3.2 / 2 - P.pin_inset)


def test_real_board_pin_count(tmp_path):
    """真实板：169 孔的板应精选为 2 个销（而非 169 个）。"""
    from pathlib import Path as _P

    from shapely.ops import unary_union

    from fixture_phase1 import make_sink_region, parse_gerber

    case = _P(__file__).resolve().parent.parent / "cases" / "case_002_aircon_kicad"
    if not case.exists():
        pytest.skip("case_002 缺失")
    bp, drills = parse_gerber(str(case))
    sink = make_sink_region(unary_union(bp), P)
    pins = make_pins(drills, P, sink_poly=sink)
    assert len(pins) == 2, f"169 孔板应精选 2 个销，实得 {len(pins)}"
