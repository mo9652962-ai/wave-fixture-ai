"""Tests for brass thread insert planning, quotation integration, and DRC rule 57."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from quotation import HARDWARE_UNIT_PRICES_CNY, estimate_quotation
from thread_inserts import INSERT_LIBRARY, export_thread_inserts_to_dxf, plan_thread_inserts


def test_insert_library_specs():
    """Verify M3/M4 insert dimensions."""
    m3 = INSERT_LIBRARY["M3"]
    assert m3.thread == "M3"
    assert m3.outer_dia_mm == 4.6
    assert m3.life_cycles == 500
    m4 = INSERT_LIBRARY["M4"]
    assert m4.outer_dia_mm == 6.0


def test_plan_thread_inserts():
    """Verify insert planning for snap screws + hinge holes."""
    plan = plan_thread_inserts(
        screw_holes=[(10.0, 10.0), (90.0, 10.0), (10.0, 90.0), (90.0, 90.0)],
        hinge_holes=[(45.0, 5.0)],
    )
    assert plan.stats["insert_count"] == 5
    assert plan.stats["m3_count"] == 4
    assert plan.stats["m4_count"] == 1
    assert len(plan.insert_polys) == 5


def test_export_thread_inserts_to_dxf():
    """Verify DXF layer '嵌件螺母' with insert outlines and note."""
    plan = plan_thread_inserts(screw_holes=[(15.0, 15.0), (85.0, 15.0)])
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_thread_inserts_to_dxf(msp, plan)

    layers = {entity.dxf.layer for entity in msp}
    assert "嵌件螺母" in layers
    texts = [e.dxf.text for e in msp if e.dxf.layer == "嵌件螺母" and e.dxftype() == "TEXT"]
    assert any("BRASS INSERT" in t for t in texts)


def test_drc_rule_57_thread_inserts_missing():
    """Verify DRC rule 57 (THREAD_INSERTS_MISSING)."""
    outer = box(0, 0, 140, 110)
    sink = box(20, 20, 120, 90)
    r1 = SimpleNamespace(
        board_poly=sink,
        sink_poly=sink,
        handles=[],
        screws=[(10.0, 10.0), (130.0, 10.0)],  # 2 snap screws
        pins=[],
    )

    r2_missing = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_missing.require_thread_inserts = True
    issues_missing = run_drc(r1, r2_missing)
    codes = [i["code"] for i in issues_missing]
    assert "THREAD_INSERTS_MISSING" in codes

    # With inserts planned, rule passes
    plan = plan_thread_inserts(screw_holes=[(10.0, 10.0), (130.0, 10.0)])
    r2_ok = Phase2Result(outer_poly=outer, sink_poly=sink, thread_inserts=plan)
    r2_ok.require_thread_inserts = True
    issues_ok = run_drc(r1, r2_ok)
    assert "THREAD_INSERTS_MISSING" not in [i["code"] for i in issues_ok]


def test_quotation_brass_insert_line():
    """Verify brass insert price appears in quotation hardware BOM."""
    assert HARDWARE_UNIT_PRICES_CNY["brass_insert_m3"] > 0
    q = estimate_quotation(quantity=5, machining_time_min=10.0, hardware_counts={"brass_insert_m3": 4.0})
    items = [c.item for c in q.cost_lines]
    assert "brass_insert_m3" in items
    # subtotal: 5 pcs x 4 inserts x 0.45 = 9.0
    assert abs(q.hardware_cost_cny - 9.0) < 0.01
