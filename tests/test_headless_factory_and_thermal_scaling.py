"""Tests for headless factory release package, thermal expansion CAM scaling, and DRC rules 64-65."""

import io
import zipfile
from types import SimpleNamespace

from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from headless_factory_pipeline import build_factory_release_package
from thermal_scaling import apply_thermal_scaling_to_polygon, calculate_thermal_expansion_scaling


def test_thermal_expansion_scaling_math():
    """Verify anisotropic scaling factor k ≈ 1.001645 for Durostone ΔT=235K."""
    res = calculate_thermal_expansion_scaling(span_x_mm=200.0, span_y_mm=150.0, material_key="durostone")
    assert 1.0015 <= res.scale_factor_x <= 1.0018
    assert res.hot_state_compensation_um_x >= 300.0  # 200mm * 0.00165 ≈ 330 um
    assert res.is_scaling_recommended is True

    # Apply scaling to pocket polygon
    poly = box(0, 0, 200, 150)
    scaled_p = apply_thermal_scaling_to_polygon(poly, res.scale_factor_x, res.scale_factor_y)
    assert scaled_p.is_valid
    assert scaled_p.area > poly.area
    # Length increased by ~0.33mm
    assert scaled_p.bounds[2] - scaled_p.bounds[0] > 200.3


def test_build_factory_release_package():
    """Verify factory release package ZIP and cryptographic SHA256 manifest."""
    pkg, zip_bytes = build_factory_release_package(
        job_id="JOB_TEST_888",
        dxf_bytes=b"SECTION 2 HEADER ENDSEC",
        setup_sheet_md="# CNC SETUP",
        quotation_md="# QUOTATION",
        maintenance_md="# MAINTENANCE",
        qc_release_md="# QC RELEASE",
        gcode_nc="G21 G90 G00 X0 Y0",
        material_key="durostone",
    )
    assert pkg.job_id == "JOB_TEST_888"
    assert pkg.total_deliverables == 7  # 6 files + MANIFEST.sha256
    assert len(zip_bytes) > 100
    assert "fixture_cam.dxf" in pkg.manifest_sha256_text
    assert "cnc_setup_sheet.md" in pkg.manifest_sha256_text

    # Unpack zip and verify contents
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    namelist = zf.namelist()
    assert "fixture_cam.dxf" in namelist
    assert "cnc_toolpath.nc" in namelist
    assert "MANIFEST.sha256" in namelist
    assert zf.read("cnc_setup_sheet.md").decode("utf-8") == "# CNC SETUP"


def test_drc_rule_64_thermal_scaling_required():
    """Verify DRC rule 64 (THERMAL_CAM_SCALING_REQUIRED)."""
    outer = box(0, 0, 260, 220)
    sink_large = box(20, 20, 230, 190)  # span = 210mm >= 200mm
    r1 = SimpleNamespace(board_poly=sink_large, sink_poly=sink_large, handles=[], screws=[], pins=[])

    # Unscaled large pallet triggers
    r2_unscaled = Phase2Result(outer_poly=outer, sink_poly=sink_large)
    r2_unscaled.require_thermal_scaling = True
    issues = run_drc(r1, r2_unscaled)
    codes = [i["code"] for i in issues]
    assert "THERMAL_CAM_SCALING_REQUIRED" in codes

    # With scaling applied, rule passes
    r2_scaled = Phase2Result(outer_poly=outer, sink_poly=sink_large)
    r2_scaled.require_thermal_scaling = True
    r2_scaled.thermal_scaling_applied = True
    issues_ok = run_drc(r1, r2_scaled)
    assert "THERMAL_CAM_SCALING_REQUIRED" not in [i["code"] for i in issues_ok]


def test_drc_rule_65_manifest_unverified():
    """Verify DRC rule 65 (FACTORY_RELEASE_MANIFEST_UNVERIFIED)."""
    outer = box(0, 0, 180, 140)
    sink = box(20, 20, 160, 120)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    r2 = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2.manifest_sha256_verified = False
    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "FACTORY_RELEASE_MANIFEST_UNVERIFIED" in codes
