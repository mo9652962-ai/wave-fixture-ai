"""Tests for solder pot contamination monitoring, flux coating control, and DRC rules 74-75."""

from types import SimpleNamespace

from shapely.geometry import box

from drc import run_drc
from flux_coating_control import control_flux_coating
from solder_pot_health import SolderPotHealthParams, monitor_solder_pot_health


def test_solder_pot_healthy():
    """Verify clean assay passes all J-STD-001 limits."""
    res = monitor_solder_pot_health(
        impurity_wt_pct={"copper": 0.42, "lead": 0.03, "iron": 0.005},
        copper_accumulation_rate_wt_pct_per_day=0.008,
    )
    assert res.is_pot_healthy is True
    assert res.violations == []
    assert res.required_dilution_kg == 0.0
    # Trend: (0.85-0.42)/0.008 = 53.75 days — comfortably far
    assert res.copper_trend_days_to_limit is not None and res.copper_trend_days_to_limit > 50


def test_solder_pot_copper_exceeded_requires_dilution():
    """Verify Cu at 1.05% triggers violation and computes pot dilution mass."""
    res = monitor_solder_pot_health(
        impurity_wt_pct={"copper": 1.05},
        params=SolderPotHealthParams(pot_capacity_kg=300.0),
    )
    assert res.is_pot_healthy is False
    cu_violation = [v for v in res.violations if v["element"] == "copper"]
    assert cu_violation and cu_violation[0]["severity"] == "critical"
    # Dilution: M*(1 - 0.85/1.05) = 300 * 0.1905 ≈ 57.1 kg
    assert res.required_dilution_kg > 50.0
    assert any("稀释" in a for a in res.corrective_actions)


def test_solder_pot_maintenance_schedule_warnings():
    """Verify stretched dross/assay intervals trigger corrective actions."""
    res = monitor_solder_pot_health(
        impurity_wt_pct={"copper": 0.40},
        params=SolderPotHealthParams(dross_removal_interval_h=8.0, assay_interval_h=80.0),
    )
    joined = " ".join(res.corrective_actions)
    assert "捞渣" in joined and "化验" in joined


def test_flux_coating_within_window():
    """Verify nominal spray parameters land inside 300~1200 μg/cm²."""
    res = control_flux_coating(
        spray_rate_ml_per_min=55.0,
        conveyor_speed_m_per_min=1.20,
        spray_width_mm=350.0,
        flux_solids_content_pct=2.5,
        flux_specific_gravity=1.005,
    )
    assert res.is_within_window is True
    assert res.top_side_fillet_risk == "low"
    assert res.is_sg_within_window is True


def test_flux_coating_starvation_risk():
    """Verify under-deposition flags high top-side fillet risk."""
    res = control_flux_coating(deposited_weight_override_ug_cm2=150.0)
    assert res.is_within_window is False
    assert res.top_side_fillet_risk == "high"
    assert any("爬锡" in a for a in res.corrective_actions)


def test_flux_coating_overload_and_sg_drift():
    """Verify over-deposition with high SG flags ionic risk and dilution action."""
    res = control_flux_coating(
        deposited_weight_override_ug_cm2=1600.0,
        flux_specific_gravity=1.030,
    )
    assert res.is_within_window is False
    assert res.ionic_residue_risk is True
    assert any("去离子水" in a for a in res.corrective_actions)


def _mk_r1():
    return SimpleNamespace(
        board_poly=box(21, 21, 279, 179),
        sink_poly=box(20, 20, 280, 180),
        handles=(),
        screws=(),
        pins=(),
    )


def test_drc_rule_74_solder_pot_contamination():
    """Verify DRC rule 74 fires on copper violation and on missing monitoring."""
    outer = box(0, 0, 300, 200)
    r1 = _mk_r1()

    sph = monitor_solder_pot_health(impurity_wt_pct={"copper": 0.95})
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        solder_pot_health=sph,
    )
    codes = [i["code"] for i in run_drc(r1, r2)]
    assert "SOLDER_POT_CONTAMINATION_EXCEEDED" in codes

    r2_missing = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        require_solder_pot_monitoring=True,
        solder_pot_health=None,
    )
    codes2 = [i["code"] for i in run_drc(r1, r2_missing)]
    assert "SOLDER_POT_CONTAMINATION_EXCEEDED" in codes2


def test_drc_rule_75_flux_coating_out_of_window():
    """Verify DRC rule 75 fires on coating weight and SG window deviations."""
    outer = box(0, 0, 300, 200)
    r1 = _mk_r1()

    fcc = control_flux_coating(deposited_weight_override_ug_cm2=200.0, flux_specific_gravity=0.980)
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        flux_coating_control=fcc,
    )
    hits = [i for i in run_drc(r1, r2) if i["code"] == "FLUX_COATING_WEIGHT_OUT_OF_WINDOW"]
    assert len(hits) == 2  # one for weight, one for SG
