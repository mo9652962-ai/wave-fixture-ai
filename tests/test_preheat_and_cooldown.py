"""Tests for preheat ramp compliance, post-wave cooldown control, and DRC rules 76-77."""

from types import SimpleNamespace

from shapely.geometry import box

from cooldown_control import check_cooldown_control
from drc import run_drc
from preheat_profile import check_preheat_profile


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


def test_preheat_profile_compliant():
    """Verify a well-tuned recipe lands in every window."""
    res = check_preheat_profile(
        preheat_length_m=1.8,
        conveyor_speed_m_per_min=1.2,
        preheat_zone1_temp_c=115.0,
        preheat_zone2_temp_c=145.0,
        measured_exit_temp_c=118.0,
        soak_time_s=80.0,
    )
    assert res.is_ramp_compliant is True
    assert res.is_exit_temp_compliant is True
    assert res.is_soak_compliant is True
    assert res.is_thermal_shock_ok is True
    assert res.violations == []


def test_preheat_profile_cold_exit_thermal_shock():
    """Verify a cold exit trips both activation and thermal-shock violations."""
    res = check_preheat_profile(
        preheat_length_m=1.0,
        conveyor_speed_m_per_min=2.0,
        measured_exit_temp_c=85.0,  # < 100 → solvent boiling + shock ΔT=170
    )
    assert res.is_exit_temp_compliant is False
    assert res.is_thermal_shock_ok is False  # 255-85 = 170 > 130
    assert any("热冲击" in v for v in res.violations)


def test_preheat_profile_water_based_tighter_window():
    """Verify water-based flux uses the 105~125°C window."""
    res = check_preheat_profile(
        preheat_length_m=1.8,
        conveyor_speed_m_per_min=1.2,
        measured_exit_temp_c=101.0,  # passes standard 100~130, fails water-based 105~125
        flux_type="water_based",
    )
    assert res.is_exit_temp_compliant is False


def test_preheat_profile_fast_ramp():
    """Verify ramp above 4°C/s is flagged."""
    res = check_preheat_profile(
        preheat_length_m=0.3,
        conveyor_speed_m_per_min=2.0,
        measured_exit_temp_c=120.0,  # 90s transit, 95°C rise → rate by measured 120-25 / 9s? use override
    )
    # 0.3m / 2m/min = 9s transit; ramp=(120-25)/9=10.6 °C/s > 4
    assert res.is_ramp_compliant is False
    assert any("芯吸分层" in v or "热冲击微裂" in v for v in res.violations)


def test_cooldown_compliant():
    """Verify tuned fan and zone pass rate and length checks."""
    res = check_cooldown_control(
        conveyor_speed_m_per_min=1.2,
        cooling_zone_length_m=1.6,
        fan_speed_pct=45.0,
    )
    assert res.is_rate_compliant is True
    assert res.is_length_sufficient is True
    # 190°C drop at 2.5°C/s target needs 76s; 1.2m/min → 1.52m... 1.5m marginally ok? required = 1.2*76/60=1.52
    # Model rate limited by time: 190/75s dwell = 2.53 → length 1.5 vs required 1.52 → borderline; assert both fields exist
    assert res.required_cooling_length_m > 0


def test_cooldown_excessive_rate():
    """Verify a full-blast short zone exceeds 4°C/s."""
    # dwell = 48s; capacity 6.0, rate by time = 190/48 = 3.96 — under. Force measured override:
    res2 = check_cooldown_control(
        conveyor_speed_m_per_min=1.2,
        cooling_zone_length_m=1.5,
        measured_cooling_rate_c_per_s=5.8,
    )
    assert res2.is_rate_compliant is False
    assert any("枝晶" in v for v in res2.violations)


def test_cooldown_insufficient_length():
    """Verify a too-short cooling zone leaves the board above 60°C at unload."""
    res = check_cooldown_control(
        conveyor_speed_m_per_min=1.2,
        cooling_zone_length_m=0.4,  # required ≈1.52m
        fan_speed_pct=60.0,
    )
    assert res.is_length_sufficient is False
    assert res.exit_handle_temp_c > 60.0
    assert any("下板" in v or "堆叠" in v for v in res.violations)


def test_drc_rule_76_preheat_window():
    """Verify DRC rule 76 fires on out-of-window preheat metadata."""
    r1, outer = _mk_results()
    php = check_preheat_profile(
        preheat_length_m=1.0,
        conveyor_speed_m_per_min=2.0,
        measured_exit_temp_c=85.0,
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        preheat_profile=php,
    )
    hits = [i for i in run_drc(r1, r2) if i["code"] == "PREHEAT_PROFILE_OUT_OF_WINDOW"]
    assert len(hits) >= 2  # exit-temp + thermal-shock


def test_drc_rule_77_cooldown():
    """Verify DRC rule 77 fires on rate and length violations."""
    r1, outer = _mk_results()
    cdc = check_cooldown_control(
        conveyor_speed_m_per_min=1.2,
        cooling_zone_length_m=0.4,
        measured_cooling_rate_c_per_s=5.5,
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        cooldown_control=cdc,
    )
    hits = [i for i in run_drc(r1, r2) if i["code"] == "COOLDOWN_RATE_EXCESSIVE"]
    assert len(hits) == 2  # rate + length
