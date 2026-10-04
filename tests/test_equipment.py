"""真机档案库与 DRC H 组（真机合规）测试。

研究出处：Electrovert 官方 datasheet（ITW EAE）+ IPC-SMEMA-9851 传送高度窗口。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import box

import drc
from equipment import MACHINES, get_machine


# ── 1. 机台画像 ──────────────────────────────────────────────────
def test_machine_profiles_official_data():
    """Electrovert 官方数据：VectraES 22.7kg / Elite 457mm / Electra 610mm。"""
    es = MACHINES["electrovert_vectra_es"]
    assert es.conveyor_load_kg == pytest.approx(22.7, abs=0.1)  # 50 lb
    assert es.official is True
    elite = MACHINES["electrovert_vectra_elite"]
    assert elite.process_width_max_mm == 457.0  # 18in
    elite_h = MACHINES["electrovert_electra"]
    assert elite_h.process_width_max_mm == 610.0  # 24in


def test_machine_fallback_and_smema():
    """未知机台回退 generic_350；SMEMA 高度窗口 940-965mm（IPC-SMEMA-9851）。"""
    assert get_machine(None).key == "generic_350"
    assert get_machine("不存在的机台").key == "generic_350"
    lo, hi = get_machine("jt_350").conveyor_height_mm
    assert (lo, hi) == (940.0, 965.0)
    # 非官方画像显式标注
    assert MACHINES["jt_350"].official is False


# ── 2. DRC H 组 ─────────────────────────────────────────────────
def _mk_r1r2(outer_w=120.0, outer_h=80.0):
    board = box(10, 10, 10 + outer_w - 40, 10 + outer_h - 40)
    sink = board.buffer(0.2)
    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=[],
        screws=[],
        pins=[(15.0, 15.0, 1.5), (60.0, 60.0, 1.5)],
        dogbone_corners=[],
    )
    r2 = SimpleNamespace(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=box(0, 0, outer_w, outer_h),
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=sink,
        dogbone_corners=[],
        panel_grid=None,
    )
    return r1, r2


def test_drc_machine_width_mismatch():
    """450×360 治具（短边 360）放不进 350mm 通用轨 → MACHINE_WIDTH_MISMATCH。"""
    r1, r2 = _mk_r1r2(outer_w=450.0, outer_h=360.0)
    issues = drc.run_drc(
        r1, r2, machine_key="generic_350", material_key="durostone", pallet_thickness=10.0
    )
    codes = [i["code"] for i in issues]
    assert "MACHINE_WIDTH_MISMATCH" in codes
    hit = next(i for i in issues if i["code"] == "MACHINE_WIDTH_MISMATCH")
    assert hit["current"] == 360.0 and hit["required"] == 350.0
    assert "轨距" in hit["detail"]


def test_drc_machine_width_ok_on_elite():
    """457mm 治具放进 VectraElite → 无轨距报错。"""
    r1, r2 = _mk_r1r2(outer_w=450.0, outer_h=80.0)
    issues = drc.run_drc(
        r1,
        r2,
        machine_key="electrovert_vectra_elite",
        material_key="durostone",
        pallet_thickness=10.0,
    )
    assert "MACHINE_WIDTH_MISMATCH" not in [i["code"] for i in issues]


def test_drc_machine_overload():
    """小载荷机台 + 大治具 → MACHINE_OVERLOAD error（铝 20mm 毛坯 ≈13kg > 10kg）。"""
    r1, r2 = _mk_r1r2(outer_w=600.0, outer_h=400.0)
    issues = drc.run_drc(
        r1, r2, machine_key="generic_350", material_key="aluminum", pallet_thickness=20.0
    )
    codes = [i["code"] for i in issues]
    assert "MACHINE_OVERLOAD" in codes
    hit = next(i for i in issues if i["code"] == "MACHINE_OVERLOAD")
    assert hit["current"] > 10.0 and hit["required"] == 10.0


def test_drc_smema_info_always_present():
    """指定机台 → SMEMA_HEIGHT_CHECK info（不阻断）。"""
    r1, r2 = _mk_r1r2()
    issues = drc.run_drc(
        r1, r2, machine_key="electrovert_vectra_es", material_key="durostone", pallet_thickness=10.0
    )
    hit = [i for i in issues if i["code"] == "SMEMA_HEIGHT_CHECK"]
    assert len(hit) == 1 and hit[0]["severity"] == "info"
    assert "940-965mm" in hit[0]["detail"]


def test_drc_no_machine_no_h_rules():
    """不指定机台 → H 组完全不触发（向后兼容）。"""
    r1, r2 = _mk_r1r2(outer_w=400.0, outer_h=80.0)
    issues = drc.run_drc(r1, r2, material_key="durostone")
    codes = [i["code"] for i in issues]
    assert not any(c.startswith(("MACHINE_", "SMEMA_")) for c in codes)


# ── 3. report 机台行 ────────────────────────────────────────────
def test_report_includes_machine_row():
    """指定机台 → 工单规格表出现目标机台行（含 official 标注）。"""
    from report import build_report

    r1, r2 = _mk_r1r2()
    verdict = {
        "allowed": True,
        "counts": {"blocking": 0, "error": 0, "warning": 0, "info": 0},
        "worst": "info",
        "total": 0,
    }
    md = build_report(
        "machine-test",
        r1,
        r2,
        verdict,
        material={"key": "durostone", "thickness": 10.0, "board_pocket_depth": 1.9},
        weight_kg=0.4,
        cost={
            "material_cost": 168.0,
            "machining_cost": 0.0,
            "total": 168.0,
            "currency": "CNY",
            "note": "",
        },
        machine_key="jt_350",
    )
    assert "劲拓 350 波峰焊" in md and "450mm" in md
    assert "以随机手册为准" in md
    md2 = build_report(
        "machine-test",
        r1,
        r2,
        verdict,
        material={"key": "durostone", "thickness": 10.0, "board_pocket_depth": 1.9},
        weight_kg=0.4,
        cost={
            "material_cost": 168.0,
            "machining_cost": 0.0,
            "total": 168.0,
            "currency": "CNY",
            "note": "",
        },
    )
    assert "目标机台" not in md2  # 不指定则无机台行
