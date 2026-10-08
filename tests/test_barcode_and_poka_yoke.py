"""工业 4.0 MES 追溯条码标牌槽 (barcode_tag)、防呆防反向切角及 DRC 规则 42/43 测试。

对标标准：
- IPC-1782 Component & Carrier Traceability Standard (25x12mm 耐高温条码/二维码沉槽)
- Toyota Production System (TPS) Poka-Yoke Error-Proofing Standard (防呆防反向切角)
"""

from __future__ import annotations

from types import SimpleNamespace

import ezdxf
import pytest
from shapely.geometry import box

import drc
from barcode_tag import (
    BarcodeTagResult,
    generate_traceability_and_poka_yoke,
)
from fixture_phase2 import Phase2Result, export_dxf2


def test_generate_traceability_and_poka_yoke():
    """验证生成 25x12mm 追溯槽及沉板区 45° 防呆切角。"""
    outer = box(0, 0, 150, 120)
    sink = box(20, 20, 130, 100)
    res = generate_traceability_and_poka_yoke(outer, sink_poly=sink, job_name="WAVE_JOB_999")

    assert res.tag_recess_poly is not None
    # 25x12mm
    tb = res.tag_recess_poly.bounds
    assert (tb[2] - tb[0]) == pytest.approx(25.0, abs=0.5)
    assert (tb[3] - tb[1]) == pytest.approx(12.0, abs=0.5)
    assert "WAVE_JOB_999" in res.tag_text
    assert len(res.poka_yoke_lines) >= 1


def test_export_barcode_tag_to_dxf(tmp_path):
    """DXF 导出包含「追溯标识」图层。"""
    outer = box(0, 0, 100, 80)
    sink = box(15, 15, 85, 65)
    bt_res = generate_traceability_and_poka_yoke(outer, sink_poly=sink)

    r2 = Phase2Result(
        outer_poly=outer,
        barcode_tag=bt_res,
    )
    out_file = tmp_path / "barcode_test.dxf"
    export_dxf2(r2, str(out_file))

    doc = ezdxf.readfile(out_file)
    layers = {l.dxf.name for l in doc.layers}
    assert "追溯标识" in layers
    msp = doc.modelspace()
    texts = [e for e in msp if e.dxf.layer == "追溯标识" and e.dxftype() == "TEXT"]
    assert len(texts) >= 1
    assert "UID:" in texts[0].dxf.text


def test_drc_rule_traceability_tag_missing():
    """量产大板要求 MES 追溯但未设标牌槽时触发 TRACEABILITY_TAG_RECESS_MISSING。"""
    large_outer = box(0, 0, 180, 150)  # 27000 mm² >= 20000 mm²
    r1 = SimpleNamespace(
        board_poly=box(10, 10, 80, 80),
        sink_poly=box(10, 10, 80, 80),
        handles=[],
        screws=[],
        pins=[],
    )
    r2_no_tag = Phase2Result(
        outer_poly=large_outer,
        barcode_tag=None,
    )
    r2_no_tag.require_mes_traceability = True
    issues = drc.run_drc(r1, r2_no_tag)
    codes = {i["code"] for i in issues}
    assert "TRACEABILITY_TAG_RECESS_MISSING" in codes


def test_drc_rule_poka_yoke_keying_missing():
    """正方形或近对称板型未设防呆切角时触发 POKA_YOKE_KEYING_MISSING。"""
    # 50x50mm 正方形板 (长宽比 1.0)
    square_sink = box(20, 20, 70, 70)
    r1 = SimpleNamespace(
        board_poly=square_sink, sink_poly=square_sink, handles=[], screws=[], pins=[]
    )
    r2_symmetric = Phase2Result(
        outer_poly=box(0, 0, 100, 100),
        sink_poly=square_sink,
        barcode_tag=BarcodeTagResult(poka_yoke_lines=[]),  # 未设防呆切角
    )
    issues = drc.run_drc(r1, r2_symmetric)
    codes = {i["code"] for i in issues}
    assert "POKA_YOKE_KEYING_MISSING" in codes
