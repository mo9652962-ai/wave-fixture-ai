"""phase1 编排（run）与 DXF 导出测试——端到端产出校验。

真实验证背景：run() 是 CLI 主入口，export_dxf 是最终交付物生成；
此前只经真板间接覆盖，缺少「DXF 内容是否正确」的断言
（比如图层是否齐全、实体是否落在合理坐标范围）。
"""
from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import box

from fixture_phase1 import (
    FixtureParams,
    export_dxf,
    make_handles,
    make_pins,
    make_screws,
    make_sink_region,
    run,
)

CASE = Path(__file__).resolve().parent.parent / "cases" / "case_003_stm32_4layer"


def _result():
    board = box(0, 0, 50, 40)
    p = FixtureParams()
    sink = make_sink_region(board, p)
    return (
        type("R", (), {
            "board_poly": board, "sink_poly": sink,
            "handles": make_handles(sink, p), "screws": make_screws(sink, p),
            "pins": make_pins([(5.0, 5.0, 3.2), (45.0, 35.0, 3.2)], p, sink_poly=sink),
        })(),
        p,
    )


def test_export_dxf_creates_layered_file(tmp_path):
    """导出必须生成含多图层的有效 DXF（图层是下游 CAM 的语义契约）。"""
    res, p = _result()
    out = tmp_path / "f.dxf"
    export_dxf(res, str(out), p)
    assert out.exists() and out.stat().st_size > 500

    doc = ezdxf.readfile(str(out))
    layers = {ly.dxf.name for ly in doc.layers}
    assert len(layers) >= 3, f"图层过少：{layers}"
    assert any(l != "0" for l in layers), "只有默认图层 → 未按语义分层"

    # 实体坐标应落在板/治具附近（不跑到 (0,0) 或天文数字）
    xs, ys = [], []
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "LWPOLYLINE":
            for pt in e.get_points("xy"):
                xs.append(pt[0]); ys.append(pt[1])
        elif t == "LINE":
            xs += [e.dxf.start.x, e.dxf.end.x]; ys += [e.dxf.start.y, e.dxf.end.y]
        elif t == "CIRCLE":
            xs.append(e.dxf.center.x); ys.append(e.dxf.center.y)
    assert xs and ys, "DXF 无几何实体"
    assert -100 < min(xs) and max(xs) < 200, f"x 范围异常: {min(xs)}~{max(xs)}"
    assert -100 < min(ys) and max(ys) < 200, f"y 范围异常: {min(ys)}~{max(ys)}"


def test_export_dxf_includes_circles_for_holes(tmp_path):
    """压扣孔/定位销应以圆实体输出（不是折线近似）。"""
    res, p = _result()
    out = tmp_path / "f.dxf"
    export_dxf(res, str(out), p)
    doc = ezdxf.readfile(str(out))
    circles = [e for e in doc.modelspace() if e.dxftype() == "CIRCLE"]
    assert circles, "压扣孔/定位销未输出为圆实体"
    radii = sorted(round(c.dxf.radius, 3) for c in circles)
    assert any(abs(r - p.screw_d / 2) < 0.1 for r in radii), f"缺少 Φ{p.screw_d} 压扣孔: {radii}"


def test_run_end_to_end_on_real_board(tmp_path):
    """run() 编排：真实板 → 完整 FixtureResult（含 DXF 落盘）。"""
    if not CASE.exists():
        pytest.skip("case_003 缺失")
    out = tmp_path / "real.dxf"
    res = run(str(CASE), str(out))
    assert res.board_poly is not None, "真实板应解析出外形"
    assert res.sink_poly is not None
    assert len(res.handles) == 2
    assert len(res.screws) == 4
    assert len(res.pins) == 2
    assert out.exists() and out.stat().st_size > 500


def test_run_without_outline_returns_empty(tmp_path):
    """无外形层时返回空结果（不抛异常，不产出半成品）。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    res = run(str(empty), str(tmp_path / "x.dxf"))
    assert res.board_poly is None
    assert not (tmp_path / "x.dxf").exists(), "无外形时不应产出 DXF"


def test_run_skips_dxf_when_out_none(tmp_path):
    """out_dxf=None 时只算不落盘（服务端预览路径复用）。"""
    if not CASE.exists():
        pytest.skip("case_003 缺失")
    res = run(str(CASE), None)
    assert res.board_poly is not None
