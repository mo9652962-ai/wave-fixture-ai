"""Tests for pallet storage rack compliance, SMED changeover kit, and DRC rules 78-79."""

from types import SimpleNamespace

from shapely.geometry import box

from changeover_kit import plan_changeover_kit
from drc import run_drc
from pallet_storage_rack import check_storage_rack


def _mk_results():
    r1 = SimpleNamespace(
        board_poly=box(21, 21, 279, 179),
        sink_poly=box(20, 20, 280, 180),
        handles=(),
        screws=(),
        pins=(),
    )
    outer = box(0, 0, 300, 200)
    return r1, outer


def test_storage_rack_compliant():
    """Verify a compliant storage setup raises no violations."""
    res = check_storage_rack(
        pallet_mass_kg=6.0,
        actual_stack=5,
        has_interlayer_pads=True,
        is_epa_grounded=True,
        storage_temp_c=25.0,
        storage_rh_pct=50.0,
        exposure_h_since_last_run=24.0,
    )
    assert res.violations == []
    assert res.bake_required is False
    assert res.recommended_max_stack >= 5


def test_storage_rack_stack_and_environment_violations():
    """Verify over-stacking + no pads + non-EPA + humid storage all fire."""
    res = check_storage_rack(
        pallet_mass_kg=8.0,
        actual_stack=12,  # > practical 8 / mass limit 50/8=6
        has_interlayer_pads=False,
        is_epa_grounded=False,
        storage_rh_pct=70.0,
    )
    assert res.is_stack_ok is False
    assert len(res.violations) >= 4  # stack + pads + EPA + humidity
    assert any("拆垛" in a for a in res.corrective_actions)


def test_storage_rack_bake_required_after_moisture_exposure():
    """Verify >48h exposure mandates pre-run bake."""
    res = check_storage_rack(exposure_h_since_last_run=72.0)
    assert res.bake_required is True
    assert any("烘干" in a for a in res.corrective_actions)


def test_changeover_kit_smed_architecture():
    """Verify insert-based architecture estimates <10min and unique pin codes."""
    res = plan_changeover_kit(product_families=4, daily_changeovers=6, externalization_rate=0.7)
    assert res.estimated_changeover_min < 10.0
    assert len(res.poka_yoke_pin_codes) == 4
    # codes unique
    assert len(set(res.poka_yoke_pin_codes)) == 4
    assert res.daily_time_saved_min > 60.0  # >1h/day recovered


def test_changeover_kit_legacy_baseline():
    """Verify legacy full-pallet changeover reports the 25-45min baseline."""
    res = plan_changeover_kit(product_families=3, uses_common_base=False)
    assert res.estimated_changeover_min >= 25.0
    assert not res.uses_common_base
    assert "通用基板" in res.summary


def test_drc_rule_78_storage_violations():
    """Verify DRC rule 78 aggregates storage violations and bake requirement."""
    r1, outer = _mk_results()
    srk = check_storage_rack(
        pallet_mass_kg=8.0,
        actual_stack=12,
        has_interlayer_pads=False,
        is_epa_grounded=False,
        storage_rh_pct=70.0,
        exposure_h_since_last_run=72.0,
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        pallet_storage_rack=srk,
    )
    hits = [i for i in run_drc(r1, r2) if i["code"] == "PALLET_STORAGE_STACKING_VIOLATION"]
    # 4 storage violations + 1 bake = 5
    assert len(hits) >= 5


def test_drc_rule_79_smed_missing():
    """Verify DRC rule 79 fires when mixed-line production lacks the insert architecture."""
    r1, outer = _mk_results()
    ck = plan_changeover_kit(product_families=3, uses_common_base=False)
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        changeover_kit=ck,
    )
    codes = [i["code"] for i in run_drc(r1, r2)]
    assert "SMED_CHANGEOVER_KIT_MISSING" in codes
