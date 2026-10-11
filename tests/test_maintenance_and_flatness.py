"""Tests for cleaning/maintenance forecasting and DRC rule 54 (sealing flatness)."""

from types import SimpleNamespace

from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from maintenance import estimate_maintenance_plan, render_maintenance_markdown


def test_maintenance_lifespan_and_titanium_factor():
    """Verify rated lifespan per material and titanium wall-life gain."""
    plan = estimate_maintenance_plan(material_key="durostone", boards_per_day=500.0, boards_per_pallet_pass=1.0)
    assert plan.rated_lifespan_cycles == 8000
    assert plan.effective_wall_life_cycles == 8000

    plan_ti = estimate_maintenance_plan(material_key="durostone", has_titanium_inserts=True)
    assert plan_ti.effective_wall_life_cycles == 24000  # 3x gain

    plan_fr4 = estimate_maintenance_plan(material_key="fr4_high_tg")
    assert plan_fr4.rated_lifespan_cycles == 500


def test_maintenance_cleaning_interval_days():
    """Verify cleaning interval converts 200 cycles to days capped at 7."""
    # 500 boards/day, 1 board per pass -> 500 passes/day -> 200 cycles = 0.4 days -> capped at 1
    plan_fast = estimate_maintenance_plan(boards_per_day=500.0, boards_per_pallet_pass=1.0)
    assert plan_fast.cleaning_interval_days == 1

    # 20 boards/day -> 10 passes/day -> 200 cycles = 20 days -> capped at 7
    plan_slow = estimate_maintenance_plan(boards_per_day=20.0, boards_per_pallet_pass=1.0)
    assert plan_slow.cleaning_interval_days == 7


def test_maintenance_replacement_alerts():
    """Verify 90% alert and end-of-life stop warnings."""
    plan_ok = estimate_maintenance_plan(current_cycles=0)
    assert plan_ok.warnings == []

    plan_alert = estimate_maintenance_plan(current_cycles=7300)
    assert any("预防性换新" in w for w in plan_alert.warnings)

    plan_eol = estimate_maintenance_plan(current_cycles=8100)
    assert any("立即停用换新" in w for w in plan_eol.warnings)


def test_maintenance_markdown_card():
    """Verify shop-floor maintenance card content."""
    plan = estimate_maintenance_plan(material_key="durostone", boards_per_day=300.0, current_cycles=1000)
    md = render_maintenance_markdown(plan, job_name="DEMO_PALLET")
    assert "治具保养点检卡 — DEMO_PALLET" in md
    assert "水基中性清洗剂" in md
    assert "禁用钢丝刷" in md
    assert "ESD 表面阻抗" in md


def test_drc_rule_54_sealing_flatness():
    """Verify DRC rule 54 (PALLET_SEALING_FLATNESS_SPEC_MISSING)."""
    outer = box(0, 0, 320, 240)  # diagonal ~400mm >= 300
    sink = box(30, 30, 290, 210)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # Missing spec triggers
    r2_none = Phase2Result(outer_poly=outer, sink_poly=sink)
    issues_none = run_drc(r1, r2_none)
    assert "PALLET_SEALING_FLATNESS_SPEC_MISSING" in [i["code"] for i in issues_none]

    # Over-tolerance spec triggers
    r2_loose = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_loose.flatness_spec_mm = 0.5
    issues_loose = run_drc(r1, r2_loose)
    assert "PALLET_SEALING_FLATNESS_SPEC_MISSING" in [i["code"] for i in issues_loose]

    # Compliant spec passes
    r2_ok = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_ok.flatness_spec_mm = 0.15
    issues_ok = run_drc(r1, r2_ok)
    assert "PALLET_SEALING_FLATNESS_SPEC_MISSING" not in [i["code"] for i in issues_ok]

    # Small pallet exempt
    outer_small = box(0, 0, 150, 100)
    r2_small = Phase2Result(outer_poly=outer_small, sink_poly=box(20, 20, 130, 80))
    issues_small = run_drc(r1, r2_small)
    assert "PALLET_SEALING_FLATNESS_SPEC_MISSING" not in [i["code"] for i in issues_small]
