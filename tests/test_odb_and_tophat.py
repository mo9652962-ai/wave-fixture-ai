"""ODB++ 复合工程数据解析器与铰链式防翘曲上盖 (Top Hat) 测试。

对标标准：
- Valor / Siemens ODB++ 复合工程数据规范 (matrix / profile / eda/data)
- AGICORP Top Hat Design Guide: 铰链安装位、锁扣固定位、观察开窗、弹力下压顶针
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest
from shapely.geometry import box

import drc
from fixture_phase1 import parse_gerber
from odb_parser import (
    ODBData,
    is_odb_archive,
    parse_odb_package,
)
from top_hat import (
    TopHatParams,
    TopHatResult,
    export_top_hat_to_dxf,
    generate_top_hat,
)

ROOT = Path(__file__).resolve().parent.parent


# ── 1. ODB++ 解析器测试 ───────────────────────────────────────────
def _create_mock_odb_tar(tmp_path: Path) -> Path:
    """构建一个合法的 ODB++ tar.gz 结构包。"""
    root = tmp_path / "odb_job"
    root.mkdir()
    (root / "matrix").mkdir()
    (root / "matrix" / "matrix").write_text(
        "STEP {\n  NAME=pcb\n}\nLAYER {\n  NAME=profile\n  TYPE=DOCUMENT\n}\n"
        "LAYER {\n  NAME=drill\n  TYPE=DRILL\n}\n",
        encoding="utf-8",
    )
    step = root / "steps" / "pcb"
    step.mkdir(parents=True)

    # profile 文件: 100x80mm 矩形
    (step / "profile").write_text(
        "OB 0 0\nL 0 0 100 0\nL 100 0 100 80\nL 100 80 0 80\nL 0 80 0 0\nOE\n",
        encoding="utf-8",
    )

    # drill 层: 2 个钻孔
    drill_layer = step / "layers" / "drill"
    drill_layer.mkdir(parents=True)
    (drill_layer / "features").write_text(
        "$1 round 3.0\nP 10.0 10.0 1\nP 90.0 70.0 1\n",
        encoding="utf-8",
    )

    # eda/data: 2 个元器件 (含高度)
    (step / "eda").mkdir()
    (step / "eda" / "data").write_text(
        "PKG QFP-48\nXMIN=0\nXMAX=7\nYMIN=0\nYMAX=7\nHEIGHT=1.6\n\n"
        "PKG 0603\nXMIN=0\nXMAX=1.6\nYMIN=0\nYMAX=0.8\nHEIGHT=0.55\n\n"
        "CMP 1 QFP-48 U1 50.0 40.0 0.0 T\n"
        "CMP 2 0603 R1 25.0 25.0 90.0 B\n",
        encoding="utf-8",
    )

    tar_path = tmp_path / "board_odb.tgz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(root, arcname=".")
    return tar_path


def test_is_odb_archive(tmp_path):
    tgz = tmp_path / "test.tgz"
    tgz.write_text("dummy", encoding="utf-8")
    assert is_odb_archive(tgz) is True
    assert is_odb_archive(tmp_path / "board.gbr") is False


def test_parse_odb_package_extracts_all_data(tmp_path):
    tar_path = _create_mock_odb_tar(tmp_path)
    odb: ODBData = parse_odb_package(tar_path)
    assert odb.has_outline is True
    assert odb.step_name == "pcb"

    # 板框 100x80
    b = odb.board_poly.bounds
    assert (b[2] - b[0]) == pytest.approx(100.0, abs=0.5)
    assert (b[3] - b[1]) == pytest.approx(80.0, abs=0.5)

    # 钻孔
    assert len(odb.drills) == 2
    assert odb.drills[0] == (10.0, 10.0, 3.0)

    # 元器件 (含顶层与底层判定)
    assert len(odb.components) == 2
    comp_map = {c.ref: c for c in odb.components}
    assert comp_map["U1"].side == "FSide" and comp_map["U1"].height == pytest.approx(1.6)
    assert comp_map["R1"].side == "BSide" and comp_map["R1"].height == pytest.approx(0.55)


def test_parse_gerber_transparent_odb_support(tmp_path):
    tar_path = _create_mock_odb_tar(tmp_path)
    board_polys, drills = parse_gerber(str(tar_path))
    assert len(board_polys) == 1
    assert board_polys[0].area == pytest.approx(100 * 80, abs=50)
    assert len(drills) == 2


# ── 2. Top Hat 铰链式上盖测试 ────────────────────────────────────
def test_generate_top_hat_geometry():
    outer = box(0, 0, 160, 120)
    sink = box(30, 20, 130, 100)
    board = box(30.2, 20.2, 129.8, 99.8)
    caps = [(50.0, 50.0, 2.45)]
    p = TopHatParams(enabled=True, cover_thickness_mm=6.0, cover_inset_mm=2.0)

    res = generate_top_hat(outer, sink, board, caps, p)
    assert res.cover_poly is not None
    cb = res.cover_poly.bounds
    assert (cb[2] - cb[0]) == pytest.approx(156.0, abs=0.5)  # 160 - 4
    assert (cb[3] - cb[1]) == pytest.approx(116.0, abs=0.5)  # 120 - 4

    # 铰链孔 2 个，锁扣孔 1 个
    assert len(res.hinge_holes) == 2
    assert len(res.latch_holes) == 1
    # 铰链孔位于上方后轨
    assert res.hinge_holes[0][1] == pytest.approx(110.0, abs=1.0)
    # 锁扣孔位于下方前轨
    assert res.latch_holes[0][1] == pytest.approx(10.0, abs=1.0)
    # 开窗至少 1 个
    assert len(res.window_polys) >= 1
    # 压柱继承 cap_holes
    assert len(res.press_pins) == 1


def test_export_top_hat_to_dxf(tmp_path):
    outer = box(0, 0, 160, 120)
    sink = box(30, 20, 130, 100)
    board = box(30, 20, 130, 100)
    res = generate_top_hat(outer, sink, board, None, TopHatParams())

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_top_hat_to_dxf(msp, res, layer_prefix="上盖")

    out_file = tmp_path / "top_hat.dxf"
    doc.saveas(out_file)

    doc_read = ezdxf.readfile(out_file)
    msp_read = doc_read.modelspace()
    layers = {e.dxf.layer for e in msp_read}
    assert "上盖外形" in layers
    assert "上盖开孔" in layers
    assert "铰链位" in layers
    assert "锁扣位" in layers


def test_drc_tophat_hinge_overflow():
    """上盖铰链孔超出治具外框时触发 TOPHAT_HINGE_OVERFLOW。"""
    outer = box(0, 0, 100, 80)
    sink = box(20, 20, 80, 60)
    r1 = SimpleNamespace(
        board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[(15, 15, 1.5), (85, 65, 1.5)]
    )

    # 正常上盖
    tophat_ok = TopHatResult(
        cover_poly=box(2, 2, 98, 78),
        hinge_holes=[(30.0, 70.0, 2.1), (70.0, 70.0, 2.1)],
        latch_holes=[(50.0, 10.0, 1.7)],
    )
    r2_ok = SimpleNamespace(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=outer,
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=sink,
        dogbone_corners=[],
        panel_grid=None,
        vent_holes=[],
        top_hat=tophat_ok,
    )
    issues_ok = drc.run_drc(r1, r2_ok)
    assert not any(i["code"].startswith("TOPHAT_") for i in issues_ok)

    # 异常铰链孔越界 (y=95 > 80)
    tophat_bad = TopHatResult(
        cover_poly=box(2, 2, 98, 78),
        hinge_holes=[(30.0, 95.0, 2.1)],
        latch_holes=[(50.0, -10.0, 1.7)],
    )
    r2_bad = SimpleNamespace(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=outer,
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=sink,
        dogbone_corners=[],
        panel_grid=None,
        vent_holes=[],
        top_hat=tophat_bad,
    )
    issues_bad = drc.run_drc(r1, r2_bad)
    codes_bad = {i["code"] for i in issues_bad}
    assert "TOPHAT_HINGE_OVERFLOW" in codes_bad
    assert "TOPHAT_LATCH_OVERFLOW" in codes_bad
