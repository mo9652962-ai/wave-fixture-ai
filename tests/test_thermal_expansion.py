"""Tests for CTE mismatch expansion gap and DRC rule 56."""

from types import SimpleNamespace

from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from thermal_expansion import CTE_PPM_K, compute_expansion_gap


def test_expansion_gap_math():
    """Verify ΔL = L × ΔCTE × ΔT arithmetic."""
    gap = compute_expansion_gap(pallet_len_mm=200.0, pcb_len_mm=196.0, material_key="durostone")
    # d_pallet = 200 * 22e-6 * 235 = 1.034mm ; d_pcb = 196 * 15e-6 * 235 = 0.6906mm
    assert abs(gap.pallet_expansion_mm - 1.034) < 0.01
    assert abs(gap.pcb_expansion_mm - 0.6906) < 0.01
    assert abs(gap.differential_mm - 0.343) < 0.02
    assert gap.at_risk is True  # > 0.2mm design clearance
    assert gap.clearance_consumed_pct > 100.0


def test_expansion_gap_small_span_safe():
    """Verify short spans stay under the 0.2mm design clearance."""
    gap = compute_expansion_gap(pallet_len_mm=60.0, pcb_len_mm=58.0, material_key="durostone")
    # d_pallet = 60*22e-6*235 = 0.3102 ; d_pcb = 58*15e-6*235 = 0.2045 ; diff ≈ 0.106 < 0.2
    assert gap.differential_mm < 0.2
    assert gap.at_risk is False


def test_expansion_gap_material_cte_table():
    """Verify CTE table covers all presets and aluminum has highest mismatch."""
    assert set(CTE_PPM_K) >= {"durostone", "ricocel", "fr4_high_tg", "aluminum"}
    gap_al = compute_expansion_gap(pallet_len_mm=200.0, pcb_len_mm=196.0, material_key="aluminum")
    gap_fr4 = compute_expansion_gap(pallet_len_mm=200.0, pcb_len_mm=196.0, material_key="fr4_high_tg")
    # Aluminum CTE 23.6 > FR-4 pallet 15 -> larger differential
    assert gap_al.differential_mm > gap_fr4.differential_mm


def test_drc_rule_56_cte_clearance():
    """Verify DRC rule 56 (SINK_CTE_CLEARANCE_INSUFFICIENT) on long sinks."""
    outer = box(0, 0, 260, 200)
    sink_long = box(20, 20, 240, 180)  # 220mm span
    r1 = SimpleNamespace(board_poly=sink_long, sink_poly=sink_long, handles=[], screws=[], pins=[])

    r2 = Phase2Result(outer_poly=outer, sink_poly=sink_long)
    issues = run_drc(r1, r2)
    assert "SINK_CTE_CLEARANCE_INSUFFICIENT" in [i["code"] for i in issues]

    # Opt-out flag suppresses
    r2_opt = Phase2Result(outer_poly=outer, sink_poly=sink_long)
    r2_opt.check_cte_gap = False
    issues_opt = run_drc(r1, r2_opt)
    assert "SINK_CTE_CLEARANCE_INSUFFICIENT" not in [i["code"] for i in issues_opt]

    # Short sink exempt (< 120mm span both axes)
    sink_short = box(20, 20, 100, 100)
    r1_short = SimpleNamespace(board_poly=sink_short, sink_poly=sink_short, handles=[], screws=[], pins=[])
    r2_short = Phase2Result(outer_poly=outer, sink_poly=sink_short)
    issues_short = run_drc(r1_short, r2_short)
    assert "SINK_CTE_CLEARANCE_INSUFFICIENT" not in [i["code"] for i in issues_short]
