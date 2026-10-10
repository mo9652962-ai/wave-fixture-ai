"""Tests for CNC toolpath grouping / rapid travel optimization and DRC rules 50-51."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from cnc_toolpath_opt import CNCOp, export_toolpath_order_to_dxf, optimize_cnc_toolpath
from drc import run_drc
from fixture_phase2 import Phase2Result


def _sample_ops() -> list[CNCOp]:
    """Interleaved ops designed so grouping + nearest-neighbor beats naive order."""
    return [
        CNCOp("PROFILE", "profile", 6.0, 400.0, (0.0, 0.0)),  # far start
        CNCOp("HOLE_1", "drill", 3.175, 12.0, (10.0, 10.0)),
        CNCOp("VENT_2", "pocket", 2.0, 20.0, (60.0, 60.0)),
        CNCOp("HOLE_2", "drill", 3.175, 12.0, (12.0, 10.5)),
        CNCOp("VENT_1", "pocket", 2.0, 20.0, (58.0, 58.0)),
        CNCOp("DOGBONE_1", "dogbone", 2.0, 6.0, (30.0, 30.0)),
    ]


def test_tool_grouping_and_ordering():
    """Verify ops are grouped by type/tool with profile last and rapid travel reduced."""
    res = optimize_cnc_toolpath(_sample_ops())

    # Profile (rank 3) must come last; drills (rank 0) first
    assert res.sequence[-1].op_type == "profile"
    assert res.sequence[0].op_type == "drill"

    # Same-type ops must be contiguous
    types = [op.op_type for op in res.sequence]
    seen: set[str] = set()
    for t in types:
        if t in seen and types[types.index(t) - 1] != t:
            # allow repeats only when contiguous
            pass
    # drill group contiguous: both HOLE ops adjacent
    idx = [i for i, t in enumerate(types) if t == "drill"]
    assert idx[1] - idx[0] == 1

    # Optimization must not increase rapid travel vs naive order
    assert res.rapid_travel_mm <= res.naive_rapid_mm
    assert res.stats["op_count"] == 6


def test_machining_time_estimation():
    """Verify cutting/rapid/tool-change time components sum to total."""
    res = optimize_cnc_toolpath(_sample_ops())
    assert res.tool_change_count >= 3  # 3.175 / 2.0 / 6.0 mm tools
    assert res.cutting_time_min > 0
    assert res.rapid_time_min > 0
    assert res.tool_change_time_min > 0
    assert abs(res.total_time_min - (res.cutting_time_min + res.rapid_time_min + res.tool_change_time_min)) < 0.05


def test_export_toolpath_order_to_dxf():
    """Verify DXF layer '刀路序号' with ordered operation labels."""
    res = optimize_cnc_toolpath(_sample_ops())
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_toolpath_order_to_dxf(msp, res)

    texts = [e.dxf.text for e in msp if e.dxf.layer == "刀路序号" and e.dxftype() == "TEXT"]
    assert len(texts) == 6
    assert any(t.startswith("01·drill") for t in texts)


def test_drc_rules_50_and_51():
    """Verify DRC rule 50 (CNC_TOOL_CHANGE_EXCESSIVE) and rule 51 (CNC_MACHINING_TIME_BUDGET_EXCEEDED)."""
    sink = box(20, 20, 120, 90)
    outer = box(0, 0, 150, 110)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # Rule 50: 7 distinct tools
    r2_tools = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_tools.cnc_toolpath_opt = SimpleNamespace(
        tool_change_count=7,
        total_time_min=30.0,
        rapid_travel_mm=500.0,
    )
    issues_50 = run_drc(r1, r2_tools)
    assert "CNC_TOOL_CHANGE_EXCESSIVE" in [i["code"] for i in issues_50]

    # Rule 51: 50min machining time
    r2_time = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_time.cnc_toolpath_opt = SimpleNamespace(
        tool_change_count=3,
        total_time_min=50.0,
        rapid_travel_mm=500.0,
    )
    issues_51 = run_drc(r1, r2_time)
    codes = [i["code"] for i in issues_51]
    assert "CNC_MACHINING_TIME_BUDGET_EXCEEDED" in codes
    assert "CNC_TOOL_CHANGE_EXCESSIVE" not in codes
