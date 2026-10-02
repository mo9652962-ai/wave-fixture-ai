"""DRC 门禁测试：规则触发 / 分级 / 生产放行判定 / 水印。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, box

from drc import (
    CONVEYOR_MAX_L_MM,
    CONVEYOR_MAX_W_MM,
    apply_watermark,
    counts,
    gate,
    production_allowed,
    run_drc,
)

SRC = ("fixture: board 100x80, sink 100.4x80.4, outer 140x140")


def _geom(outer_size=(140.0, 140.0), avoid=None, solder=None, pins=None, screws=None,
          handles=None, tin_holes=None, tin_strips=None):
    """构造一组可控的 phase 结果（默认全部合法）。"""
    board = box(0, 0, 100, 80)
    sink = box(-0.2, -0.2, 100.2, 80.2)
    outer = box(-20, -30, 120 + outer_size[0] - 140, 110 + outer_size[1] - 140)
    r1 = SimpleNamespace(
        board_poly=board, sink_poly=sink,
        handles=handles if handles is not None else [box(-19, 20, 1, 60), box(99, 20, 119, 60)],
        screws=screws if screws is not None else [(-10, -10), (110, -10), (-10, 90), (110, 90)],
        pins=pins if pins is not None else [(5, 5, 1.4), (95, 75, 1.4)],
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=avoid if avoid is not None else [box(30, 30, 40, 40)],
        solder_polys=solder if solder is not None else [box(60, 20, 70, 30)],
        cap_holes=[(50, 50, 2.45)],
        tin_holes=tin_holes if tin_holes is not None else [(-5, 40, 1.6)],
        tin_strip_lines=tin_strips if tin_strips is not None else [LineString([(0, -40), (100, -40)])],
    )
    return r1, r2


def test_clean_fixture_passes_all_gates():
    issues = run_drc(*_geom())
    g = gate(issues)
    assert g["allowed"] is True
    assert g["counts"]["blocking"] == 0 and g["counts"]["error"] == 0


def test_every_issue_has_source_citation():
    """工业级要求：每条规则都要能追溯到出处。"""
    r1, r2 = _geom(avoid=[box(30, 30, 40, 40), box(200, 200, 210, 210)])  # 第二个越界
    issues = run_drc(r1, r2)
    assert issues, "应至少有一条发现"
    for i in issues:
        assert i["source"], f"{i['code']} 缺出处"
        assert i["severity"] in ("blocking", "error", "warning", "info")


def test_avoid_outside_outer_is_blocking():
    r1, r2 = _geom(avoid=[box(500, 500, 510, 510)])
    g = gate(run_drc(r1, r2))
    assert g["allowed"] is False
    assert g["worst"] == "blocking"


def test_fixture_exceeding_conveyor_is_error():
    # 治具 > 762mm → 传送带极限报 error
    big = 900.0
    r1, r2 = _geom()
    r2.outer_poly = box(0, 0, big, 300)
    r2.avoid_polys, r2.solder_polys = [], []
    issues = run_drc(r1, r2)
    hit = [i for i in issues if i["code"] == "FIXTURE_SIZE_EXCEEDS_CONVEYOR"]
    assert len(hit) == 1
    assert hit[0]["severity"] == "error" and hit[0]["required"] == CONVEYOR_MAX_L_MM


def test_insufficient_pins_and_clamps_warn_only():
    r1, r2 = _geom(pins=[(5, 5, 1.4)], screws=[(-10, -10)])
    issues = run_drc(r1, r2)
    codes = {i["code"] for i in issues}
    assert "LOCATING_PINS_INSUFFICIENT" in codes and "CLAMPS_INSUFFICIENT" in codes
    assert all(i["severity"] == "warning" for i in issues if i["code"].endswith("INSUFFICIENT"))
    # 只有 warning → 仍允许生产
    assert gate(issues)["allowed"] is True


def test_pin_inside_avoid_is_error():
    r1, r2 = _geom(pins=[(35, 35, 1.4), (95, 75, 1.4)], avoid=[box(30, 30, 40, 40)])
    issues = run_drc(r1, r2)
    hits = [i for i in issues if i["code"] == "PIN_IN_AVOID"]
    assert len(hits) == 1 and hits[0]["severity"] == "error"
    assert gate(issues)["allowed"] is False


def test_clamp_inside_sink_is_error():
    r1, r2 = _geom(screws=[(50, 40), (110, -10), (-10, 90), (110, 90)])
    issues = run_drc(r1, r2)
    assert any(i["code"] == "CLAMP_IN_SINK" and i["severity"] == "error" for i in issues)


def test_tin_hole_in_sink_is_error():
    r1, r2 = _geom(tin_holes=[(50, 40, 1.6)])
    issues = run_drc(r1, r2)
    assert any(i["code"] == "TIN_HOLE_IN_SINK" for i in issues)


def test_avoid_solder_overlap_is_warning():
    r1, r2 = _geom(avoid=[box(30, 30, 60, 60)], solder=[box(50, 50, 70, 70)])
    issues = run_drc(r1, r2)
    hits = [i for i in issues if i["code"] == "AVOID_SOLDER_OVERLAP"]
    assert hits and hits[0]["severity"] == "warning"


def test_handle_outside_body_is_error():
    r1, r2 = _geom(handles=[box(500, 20, 520, 60), box(99, 20, 119, 60)])
    issues = run_drc(r1, r2)
    assert any(i["code"] == "HANDLE_OUTSIDE_BODY" for i in issues)


def test_counts_and_production_allowed_helpers():
    issues = [{"severity": "warning"}, {"severity": "error"}, {"severity": "error"}]
    c = counts(issues)
    assert c["warning"] == 1 and c["error"] == 2 and c["blocking"] == 0
    assert production_allowed(issues) is False
    assert production_allowed([{"severity": "warning"}, {"severity": "info"}]) is True


def test_watermark_writes_preview_dxf(tmp_path):
    import ezdxf

    src = tmp_path / "fixture.dxf"
    doc = ezdxf.new("R2010")
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 80), (0, 80)], close=True)
    doc.saveas(str(src))

    out = apply_watermark(src)
    assert Path(out).exists() and "PREVIEW" in Path(out).name
    # 水印层里有文字实体
    d2 = ezdxf.readfile(out)
    texts = [e for e in d2.modelspace() if e.dxftype() == "TEXT"]
    assert len(texts) >= 3
    assert all(e.dxf.layer == "WATERMARK" for e in texts)


@pytest.mark.parametrize("size,expect", [
    ((480.0, 700.0), True),   # 在极限内
    ((520.0, 700.0), False),  # 短边超 508
])
def test_conveyor_limits_boundary(size, expect):
    r1, r2 = _geom()
    r2.outer_poly = box(0, 0, size[0], size[1])
    r2.avoid_polys, r2.solder_polys = [], []
    issues = run_drc(r1, r2)
    hit = any(i["code"] == "FIXTURE_SIZE_EXCEEDS_CONVEYOR" for i in issues)
    assert hit is (not expect)
    assert CONVEYOR_MAX_W_MM == 508.0
