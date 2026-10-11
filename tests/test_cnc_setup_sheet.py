"""Tests for CNC setup sheet generation and DRC rules 52-53."""

from types import SimpleNamespace

from shapely.geometry import box

from cnc_setup_sheet import generate_cnc_setup_sheet
from cnc_toolpath_opt import CNCOp, optimize_cnc_toolpath
from drc import run_drc
from fixture_phase2 import Phase2Result


def _tpo():
    ops = [
        CNCOp("HOLE_1", "drill", 3.175, 12.0, (10.0, 10.0)),
        CNCOp("HOLE_2", "drill", 3.175, 12.0, (12.0, 10.5)),
        CNCOp("SINK_POCKET", "pocket", 6.0, 300.0, (20.0, 20.0)),
        CNCOp("OUTER_PROFILE", "profile", 6.0, 400.0, (0.0, 0.0)),
    ]
    return optimize_cnc_toolpath(ops)


def test_setup_sheet_tools_and_stock():
    """Verify tool table grouping, standard-ladder flags, and stock sizing."""
    res = generate_cnc_setup_sheet(_tpo(), outer_width_mm=120.0, outer_height_mm=90.0)

    # Stock: (120+20, 90+20) = 140x110 -> already multiples of 5
    assert res.stock_width_mm == 140.0
    assert res.stock_height_mm == 110.0
    assert res.min_stock_width_mm == 140.0

    # Tool table: T01 = 3.175 drill, T02 = 6.0 pocket/profile
    assert [t.dia_mm for t in res.tools] == [3.175, 6.0]
    assert res.tools[0].tool_id == "T01"
    assert res.tools[0].op_count == 2
    assert all(t.is_standard for t in res.tools)
    assert res.wcs == "G54"


def test_setup_sheet_markdown_content():
    """Verify markdown contains stock, WCS, and operation order table."""
    res = generate_cnc_setup_sheet(_tpo(), 120.0, 90.0, job_name="DEMO_JOB")
    md = res.markdown
    assert "CNC 加工准备单 — DEMO_JOB" in md
    assert "G54" in md
    assert "140" in md
    assert "| T01 | 3.175 |" in md
    assert "OUTER_PROFILE" in md


def test_setup_sheet_nonstandard_tool_flag():
    """Verify off-ladder tool diameter is flagged."""
    ops = [CNCOp("ODD_POCKET", "pocket", 2.7, 50.0, (5.0, 5.0))]
    res = generate_cnc_setup_sheet(optimize_cnc_toolpath(ops), 50.0, 40.0)
    assert res.nonstandard_tools == [2.7]
    assert res.tools[0].is_standard is False


def test_drc_rules_52_and_53():
    """Verify DRC rule 52 (non-standard tool) and rule 53 (stock insufficient)."""
    outer = box(0, 0, 120, 90)
    sink = box(20, 20, 100, 70)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # Rule 52: off-ladder tool diameter 2.7mm
    r2_tool = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_tool.cnc_toolpath_opt = SimpleNamespace(tool_order=[2.7], total_time_min=20.0)
    issues_52 = run_drc(r1, r2_tool)
    codes_52 = [i["code"] for i in issues_52]
    assert "CNC_NONSTANDARD_TOOL_DIAMETER" in codes_52

    # Rule 53: stock smaller than outer + 2x10mm clamp margin
    r2_stock = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_stock.stock_width_mm = 100.0  # need 140
    r2_stock.stock_height_mm = 110.0
    issues_53 = run_drc(r1, r2_stock)
    codes_53 = [i["code"] for i in issues_53]
    assert "CNC_STOCK_SIZE_INSUFFICIENT" in codes_53

    # Sufficient stock passes
    r2_ok = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_ok.stock_width_mm = 140.0
    r2_ok.stock_height_mm = 110.0
    issues_ok = run_drc(r1, r2_ok)
    assert "CNC_STOCK_SIZE_INSUFFICIENT" not in [i["code"] for i in issues_ok]
