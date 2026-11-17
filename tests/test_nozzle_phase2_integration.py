"""选择焊喷嘴核算的 phase2 集成测试。

此前喷嘴块的触发参数 selective_nozzle_dia_mm 未在 Phase2Params 上声明：
run_phase2 的参数覆盖是 hasattr 门控的，未声明的键会被静默丢弃，
结果字段 selective_nozzle_profile 因此恒为 None，DRC 的 BC 组检查
永远拿不到输入。本测试锁定补全后的行为：默认不启用（结果为 None，
与补全前一致）；设置喷嘴内径后核算被真正挂载；喷嘴磨损超限时
DRC BC 组能报出窗口违规。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.ops import unary_union

from drc import run_drc
from fixture_phase1 import (
    FixtureParams,
    make_handles,
    make_pins,
    make_screws,
    make_sink_region,
    parse_gerber,
)
from fixture_phase2 import run_phase2

CASE = Path(__file__).resolve().parent.parent / "cases" / "case_001_espmh"

pytestmark = pytest.mark.skipif(
    not (CASE / "Gerber_BoardOutline.GKO").exists(),
    reason="真实板 case 文件缺失（仅在有 production sample 时运行）",
)


@pytest.fixture(scope="module")
def r1():
    bp, drills = parse_gerber(str(CASE))
    board = unary_union(bp)
    p1 = FixtureParams()
    sink = make_sink_region(board, p1)
    return SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=make_handles(sink, p1),
        screws=make_screws(sink, p1),
        pins=make_pins(drills, p1),
    )


def test_nozzle_profile_off_by_default(r1):
    """默认参数下喷嘴核算不挂载——与补全前行为一致。"""
    r2 = run_phase2(str(CASE), None, phase1_result=r1)
    assert r2.selective_nozzle_profile is None


def test_nozzle_profile_mounted_when_dia_set(r1):
    """经参数覆盖设置喷嘴内径后，核算结果被挂载到 phase2 结果。"""
    r2 = run_phase2(
        str(CASE),
        None,
        phase1_result=r1,
        params2_override={"selective_nozzle_dia_mm": 6.0},
    )
    prof = r2.selective_nozzle_profile
    assert prof is not None
    assert prof.nozzle_inner_dia_mm == 6.0
    assert prof.wave_height_mm > 0


def test_drc_bc_flags_worn_nozzle(r1):
    """喷嘴磨损超限（≥5 万周期需重新镀锡）时，DRC BC 组报出窗口违规。"""
    r2 = run_phase2(
        str(CASE),
        None,
        phase1_result=r1,
        params2_override={
            "selective_nozzle_dia_mm": 6.0,
            "selective_nozzle_cycles": 60_000,
        },
    )
    assert r2.selective_nozzle_profile is not None
    assert r2.selective_nozzle_profile.retinning_recommended
    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "SELECTIVE_NOZZLE_WINDOW_VIOLATION" in codes
