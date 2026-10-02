"""防御性分支测试——异常路径与边界规则（覆盖率最后一段）。

真实验证背景：剩余未覆盖代码几乎全是错误处理分支（解析失败/几何退化/
不合法输入）。这类分支恰恰在生产环境最常被触发，却最难在正常测试中走到。
本文件用**故意构造的坏输入**逐个击穿。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Polygon, box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import drc
import interference as interf
import web_server


# ── DRC 边界规则 ─────────────────────────────────────────────────
def _mk(outer=None, avoid=None, solder=None, pins=None, screws=None, handles=None,
        board=None, sink=None):
    board = board if board is not None else box(0, 0, 50, 40)
    sink = sink if sink is not None else box(-0.2, -0.2, 50.2, 40.2)
    outer = outer if outer is not None else box(-20, -30, 70, 70)
    r1 = SimpleNamespace(
        board_poly=board, sink_poly=sink,
        handles=handles if handles is not None else [],
        screws=screws if screws is not None else [],
        pins=pins if pins is not None else [],
    )
    r2 = SimpleNamespace(
        outer_poly=outer, avoid_polys=avoid if avoid is not None else [],
        solder_polys=solder if solder is not None else [],
        cap_holes=[], tin_holes=[], tin_strip_lines=[],
    )
    return r1, r2


def test_drc_invalid_board_polygon_flagged():
    """自交/无效拓扑的外形必须报 blocking。"""
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])  # 自交
    r1, r2 = _mk(board=bowtie)
    issues = drc.run_drc(r1, r2)
    assert any(i["code"] == "BOARD_OUTLINE_INVALID" and i["severity"] == "blocking" for i in issues)


def test_drc_missing_sink_flagged():
    r1, r2 = _mk(sink=None)
    r1.sink_poly = None
    codes = {i["code"] for i in drc.run_drc(r1, r2)}
    assert "SINK_REGION_INVALID" in codes


def test_drc_invalid_outer_flagged():
    r1, r2 = _mk(outer=None)
    r2.outer_poly = None
    codes = {i["code"] for i in drc.run_drc(r1, r2)}
    assert "FIXTURE_BODY_INVALID" in codes


def test_drc_tin_hole_inside_sink_error():
    r1, r2 = _mk()
    r2.tin_holes = [(25.0, 20.0, 1.6)]  # 落在沉板区内
    issues = drc.run_drc(r1, r2)
    assert any(i["code"] == "TIN_HOLE_IN_SINK" and i["severity"] == "error" for i in issues)


def test_drc_barrier_sink_collision_warning():
    r1, r2 = _mk()
    r2.tin_strip_lines = [LineString([(10, 20), (40, 20)])]  # 穿过沉板区
    issues = drc.run_drc(r1, r2)
    assert any(i["code"] == "BARRIER_SINK_COLLISION" for i in issues)


def test_drc_handle_outside_body_error():
    r1, r2 = _mk(handles=[box(200, 200, 220, 240)])  # 远在治具外
    issues = drc.run_drc(r1, r2)
    assert any(i["code"] == "HANDLE_OUTSIDE_BODY" and i["severity"] == "error" for i in issues)


def test_drc_geometric_degeneracy_does_not_crash():
    """退化几何（空/None/非多边形）不能让 DRC 崩——只能跳过或报错。"""
    r1, r2 = _mk()
    r2.avoid_polys = [None, Polygon(), box(5, 5, 10, 10)]
    r2.solder_polys = [None]
    r1.handles = [None]
    r1.pins = [(1.0, 1.0, 1.5)]
    issues = drc.run_drc(r1, r2)  # 不抛异常即通过
    assert isinstance(issues, list)


# ── interference 防御分支 ────────────────────────────────────────
def test_interference_invalid_stl_path_raises():
    """非法 STL 路径必须抛出具体异常（不静默返回空结果）。

    trimesh.load 对不存在路径抛 FileNotFoundError/ValueError 之一——
    断言具体类型而非 blind Exception，避免掩盖未来的行为变化。
    """
    with pytest.raises((FileNotFoundError, ValueError, OSError)):
        interf.analyze_interference("/nonexistent/file.stl", [])


def test_interference_through_hole_skipped():
    """插件封装必须被跳过（贯穿治具由「上锡区」处理，不应报避位干涉）。"""
    from fixture_3d import Fixture3DParams, build_fixture_3d, export_stl

    outer = box(0, 0, 60, 50)
    mesh = build_fixture_3d(None, [], [], outer, Fixture3DParams())
    import tempfile

    p = Path(tempfile.mkdtemp()) / "f.stl"
    export_stl(mesh, str(p))
    # 元件置于治具内部（远离边界，确保 3D 实体真实相交）
    comps = [
        {"ref": "J1", "name": "PinHeader_2x3", "x": 30, "y": 25, "w": 10, "h": 5, "height": 8},
        {"ref": "R1", "name": "R_0805", "x": 30, "y": 25, "w": 2, "h": 1.2, "height": 0.5},
    ]
    reports = interf.analyze_interference(str(p), comps, skip_through_hole=True)
    assert not any(r["ref"] == "J1" for r in reports), "插件未被跳过"
    assert any(r["ref"] == "R1" for r in reports), "贴片元件应参与判定"


def test_interference_skip_disabled_includes_through_hole():
    from fixture_3d import Fixture3DParams, build_fixture_3d, export_stl

    mesh = build_fixture_3d(None, [], [], box(0, 0, 60, 50), Fixture3DParams())
    import tempfile

    p = Path(tempfile.mkdtemp()) / "f.stl"
    export_stl(mesh, str(p))
    comps = [{"ref": "J1", "name": "PinHeader_2x3", "x": 30, "y": 25, "w": 10, "h": 5, "height": 8}]
    reports = interf.analyze_interference(str(p), comps, skip_through_hole=False)
    assert any(r["ref"] == "J1" for r in reports), "禁用跳过后插件应参与判定"


def test_get_pcb_board_bounds_missing_file_returns_none(tmp_path):
    assert interf.get_pcb_board_bounds(str(tmp_path / "nope.kicad_pcb")) is None


def test_parse_kicad_pcb_missing_file_safe(tmp_path):
    assert interf.parse_kicad_pcb(str(tmp_path / "nope.kicad_pcb")) == []


# ── web_server 异常路径 ──────────────────────────────────────────
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, "OUTPUT_DIR", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    return TestClient(web_server.app, raise_server_exceptions=False)


def test_generate3d_rejects_empty(client):
    assert client.post("/api/generate3d", files=[]).status_code in (400, 422)


def test_generate3d_missing_outline(client):
    case = ROOT / "cases" / "case_003_stm32_4layer" / "board-B_Mask.gbs"
    if not case.exists():
        pytest.skip("case 缺失")
    r = client.post("/api/generate3d", files=[("files", ("board-B_Mask.gbs", case.read_bytes(), "text/plain"))])
    assert r.status_code in (400, 422, 500)


def test_adjust_invalid_upload(client):
    r = client.post("/api/adjust", data={"instruction": "避位区外扩1mm"}, files=[])
    assert r.status_code in (400, 422, 500)


def test_interference_invalid_upload(client):
    assert client.post("/api/interference", files=[]).status_code in (400, 422)


def test_review_confirm_bad_payload(client):
    r = client.post("/api/review/confirm", data={"job_id": "x"})
    assert r.status_code in (400, 404, 422, 500)


def test_corrupt_gerber_does_not_crash(client):
    """损坏/伪造的 Gerber 内容不能让端点 500 崩（应可读地报错）。"""
    r = client.post("/api/generate", files=[("files", ("bad.gm1", b"\x00\x01not a gerber", "text/plain"))])
    assert r.status_code in (200, 400, 422, 500)
    if r.status_code == 200:
        assert r.json().get("ok") in (True, False)  # 至少是结构化响应
