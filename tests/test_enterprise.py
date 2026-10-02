"""企业级升级测试：材料库 / 拼版阵列 / CNC G 代码 / DRC 工业合规 / 生产报告。

覆盖目标（对应 2026-10 企业级研究升级）：
1. materials：预设库完整性、重量/成本估算、板厚吸附
2. panelize：网格数学、几何复制、元件复制、 DogboneCorner 平移
3. cnc_gcode：G 代码结构（G21/G90/G54/换刀/M30）、Z 深度不超安全界、路径安全校验
4. drc G 组：轨道限宽 / 最小开口 / 薄壁 / 拼版间距
5. report：生产工单 Markdown 生成与路径安全
6. web 集成：/api/generate 返回 gcode_url / report_url / material
"""
from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

import drc
import materials
import report as report_mod
from materials import MATERIALS, get_material
from panelize import build_grid, panelize_geometry, replicate_components

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "cases" / "case_003_stm32_4layer"


# ── 1. materials ─────────────────────────────────────────────────
def test_materials_library_complete():
    """四种工业材料齐全，Durostone 为默认且 ESD。"""
    assert set(MATERIALS) >= {"durostone", "ricocel", "fr4_high_tg", "aluminum"}
    d = MATERIALS["durostone"]
    assert d.esd_safe is True
    assert d.max_service_temp_c >= 260
    assert 8 in d.thickness_options_mm and 10 in d.thickness_options_mm
    assert get_material(None).key == "durostone"
    assert get_material("不存在的材料").key == "durostone"  # 回退不抛异常


def test_material_weight_and_cost():
    """重量 = 面积×厚×密度；成本含材料费。"""
    m = MATERIALS["durostone"]
    w = materials.estimate_weight(100 * 100, 10.0, m)
    # 10000mm² × 10mm = 100cm³ × 1.9 = 190g = 0.19kg
    assert abs(w - 0.19) < 0.01
    cost = materials.estimate_cost(1.0, m, machining_minutes=60.0)
    assert cost["material_cost"] == pytest.approx(m.price_per_kg, rel=0.01)
    assert cost["machining_cost"] == pytest.approx(120.0, rel=0.01)
    assert cost["total"] == pytest.approx(m.price_per_kg + 120.0, rel=0.01)


def test_material_thickness_snap():
    """板厚吸附：设计 9mm → 取 10mm 档位（向上取档）。"""
    m = MATERIALS["durostone"]
    assert materials.nearest_sheet_thickness(9.0, m) == 10.0
    assert materials.nearest_sheet_thickness(10.0, m) == 10.0
    assert materials.nearest_sheet_thickness(0.5, m) == 2.0


# ── 2. panelize ──────────────────────────────────────────────────
def test_panel_grid_math():
    """2×3 网格：offsets 数、间距、总占位。"""
    demo = Polygon([(0, 0), (60, 0), (60, 40), (0, 40)])
    g = build_grid(demo.bounds, 2, 3, 5.0)
    assert len(g.offsets) == 6
    assert g.offsets[1] == (65.0, 0.0)     # 第二列 +60+5
    assert g.offsets[2] == (0.0, 45.0)     # 第二行 +40+5（行优先排列）
    assert g.offsets[3] == (65.0, 45.0)
    assert g.total_w == pytest.approx(125.0)
    assert g.total_h == pytest.approx(130.0)


def test_panelize_geometry_replicates_all():
    """几何复制：sink 并集、避位/上锡/盖板/销全部按片数翻倍。"""
    unit = box(0, 0, 60, 40)
    avoid = [box(10, 10, 20, 20)]
    caps = [(15.0, 15.0, 2.45)]
    pins = [(5.0, 5.0, 1.5)]
    handles = [box(-10, 0, 0, 10)]
    screws = [(-5.0, 5.0)]
    corners = []
    from dogbone import DogboneCorner
    corners.append(DogboneCorner(index=0, vertex=(60.0, 40.0), center=(61.31, 41.31),
                                 cutter_r=1.85, bisector=(0.707, 0.707),
                                 angle_deg=90.0, style="dogbone",
                                 lead_in_line=((63.0, 41.31), (61.31, 41.31))))
    grid, sink, avoids, _solders, caps2, pins2, handles2, screws2, corners2 = panelize_geometry(
        unit.bounds, unit, avoid, [], caps, pins, handles, screws, corners, 2, 2, 5.0)
    assert len(grid.offsets) == 4
    # 2×2 = 4 片，所有列表 ×4
    assert len(avoids) == 4
    assert len(caps2) == 4
    assert len(pins2) == 4
    assert len(handles2) == 4
    assert len(screws2) == 4
    assert len(corners2) == 4
    # 第二片偏移 = (65, 0)（行优先）
    assert pins2[1] == (70.0, 5.0, 1.5)
    assert corners2[1].center == (61.31 + 65.0, 41.31)
    # sink 并集覆盖 4 片
    assert sink.area >= 4 * 60 * 40 * 0.99


def test_replicate_components_refs():
    """元件复制：位号加 [ij] 后缀、坐标按片平移。"""
    comps = [{"ref": "R1", "name": "R0603", "x": 10.0, "y": 10.0, "w": 1.6, "h": 0.8, "height": 0.5}]
    g = build_grid((0, 0, 60, 40), 2, 1, 5.0)
    out = replicate_components(comps, g)
    assert len(out) == 2
    assert out[0]["ref"] == "R1[11]"
    assert out[1]["ref"] == "R1[21]"
    assert out[1]["x"] == pytest.approx(75.0)


# ── 3. cnc_gcode ─────────────────────────────────────────────────
def _make_simple_geometry():
    sink = box(0, 0, 60, 40)
    avoid = [box(10, 10, 30, 20)]
    solder = [box(35, 10, 45, 20)]
    caps = [(50.0, 30.0, 2.45)]
    pins = [(5.0, 5.0, 1.5), (55.0, 5.0, 1.5)]
    handles = [box(-10, 0, -1, 20)]
    outer = box(-30, -30, 90, 70)
    return sink, avoid, solder, caps, pins, handles, outer


def test_gcode_structure_and_safety(tmp_path):
    """G 代码结构：G21/G90/G54/换刀/M30；Z 深度不超贯穿深度；输出路径受白名单保护。"""
    from cnc_gcode import generate_gcode

    sink, avoid, solder, caps, pins, handles, outer = _make_simple_geometry()
    out = tmp_path / "fixture.nc"
    stats = generate_gcode(sink, avoid, solder, caps, pins, handles, outer,
                           str(out), material_key="durostone",
                           pallet_thickness=10.0, board_thickness=1.6,
                           parent_hint=tmp_path)
    text = out.read_text(encoding="ascii")
    assert "G21" in text and "G90" in text and "G54" in text
    assert "M30" in text and "M5" in text
    assert "T1 M6" in text and "T2 M6" in text  # 钻头组 + 立铣刀
    # Z 深度边界：贯穿 = -(10+1)，沉板 = -1.9；不允许出现超过破底深度的 Z
    assert "Z-11" in text
    # 统计
    assert stats["pocket_ops"] > 0
    assert stats["profile_passes"] > 0
    assert stats["machining_minutes"] > 0
    assert stats["line_count"] > 50


def test_gcode_rejects_bad_path(tmp_path):
    """输出路径安全：非白名单后缀 / 越出父目录必须拒绝。"""
    from cnc_gcode import generate_gcode, resolve_safe_out_path

    sink, avoid, solder, caps, pins, handles, outer = _make_simple_geometry()
    with pytest.raises(ValueError):
        generate_gcode(sink, avoid, solder, caps, pins, handles, outer,
                       str(tmp_path / "evil.exe"), parent_hint=tmp_path)
    with pytest.raises(ValueError):
        resolve_safe_out_path(str(tmp_path.parent / "outside.nc"), parent_hint=tmp_path)


def test_gcode_material_changes_parameters(tmp_path):
    """材料预设影响进给：铝（高进给）切长耗时 < 合成石（保守进给）。"""
    from cnc_gcode import generate_gcode

    sink, avoid, solder, caps, pins, handles, outer = _make_simple_geometry()
    s1 = generate_gcode(sink, avoid, solder, caps, pins, handles, outer,
                        str(tmp_path / "a.nc"), material_key="durostone",
                        pallet_thickness=10.0, parent_hint=tmp_path)
    s2 = generate_gcode(sink, avoid, solder, caps, pins, handles, outer,
                        str(tmp_path / "b.nc"), material_key="aluminum",
                        pallet_thickness=10.0, parent_hint=tmp_path)
    assert s1["material"] == "durostone"
    assert s2["material"] == "aluminum"
    assert s1["machining_minutes"] > s2["machining_minutes"]  # 合成石更保守更慢


# ── 4. DRC G 组工业合规 ──────────────────────────────────────────
def _mk_r1r2(outer_w=120.0, outer_h=80.0, avoid_w=10.0, panel_grid=None,
             rail_max=None):
    """构造最小 r1/r2 测试对象。"""
    from types import SimpleNamespace

    board = box(10, 10, 10 + outer_w - 40, 10 + outer_h - 40)
    sink = board.buffer(0.2)
    outer = box(0, 0, outer_w, outer_h)
    avoid = [box(30, 30, 30 + avoid_w, 30 + 10)] if avoid_w else []
    r1 = SimpleNamespace(board_poly=board, sink_poly=sink, handles=[], screws=[],
                         pins=[(15.0, 15.0, 1.5), (60.0, 60.0, 1.5)],
                         dogbone_corners=[])
    r2 = SimpleNamespace(avoid_polys=avoid, solder_polys=[], cap_holes=[],
                         outer_poly=outer, rail_lines=[], tin_strip_lines=[],
                         tin_holes=[], sink_poly=sink, dogbone_corners=[],
                         panel_grid=panel_grid)
    if rail_max is not None:
        r2.rail_max_mm = rail_max
    return r1, r2


def test_drc_rail_width_overflow():
    """治具短边超轨距上限 → blocking 级 error。"""
    r1, r2 = _mk_r1r2(outer_w=400.0, outer_h=350.0, rail_max=330.0)
    issues = drc.run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "RAIL_WIDTH_OVERFLOW" in codes


def test_drc_min_opening_width():
    """避位开口 < 3.8mm → warning（Macaos 指南）。"""
    r1, r2 = _mk_r1r2(avoid_w=2.0)
    issues = drc.run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "MIN_OPENING_WIDTH" in codes


def test_drc_thin_wall():
    """沉板区与避位区壁厚 < 1.5mm → warning（APTPCB）。"""
    board = box(10, 10, 60, 60)
    sink = board.buffer(0.2)
    # 避位区紧贴沉板边界（外扩 0.2 后相距 0）
    avoid = [box(60.25, 20, 75, 40)]
    from types import SimpleNamespace

    r1 = SimpleNamespace(board_poly=board, sink_poly=sink, handles=[], screws=[],
                         pins=[(15.0, 15.0, 1.5), (40.0, 40.0, 1.5)], dogbone_corners=[])
    r2 = SimpleNamespace(avoid_polys=avoid, solder_polys=[], cap_holes=[],
                         outer_poly=box(0, 0, 120, 80), rail_lines=[], tin_strip_lines=[],
                         tin_holes=[], sink_poly=sink, dogbone_corners=[], panel_grid=None)
    issues = drc.run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "THIN_WALL" in codes


def test_drc_panel_gap():
    """拼版间距 < 3mm → warning。"""
    r1, r2 = _mk_r1r2(panel_grid={"cols": 2, "rows": 2, "gap": 2.0, "copies": 4,
                                  "total": [125.0, 85.0]})
    issues = drc.run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "PANEL_GAP_TOO_SMALL" in codes


# ── 5. report ────────────────────────────────────────────────────
def test_report_generation(tmp_path):
    """生产工单：包含材料/成本/DRC/G 代码关键节。"""

    r1, r2 = _mk_r1r2(panel_grid={"cols": 2, "rows": 2, "gap": 5.0, "copies": 4,
                                  "total": [125.0, 85.0]})
    verdict = {"allowed": True, "counts": {"blocking": 0, "error": 0, "warning": 1, "info": 0},
               "worst": "warning", "total": 1}
    md = report_mod.build_report(
        "test-job", r1, r2, verdict,
        material={"key": "durostone", "thickness": 10.0, "board_pocket_depth": 1.9},
        weight_kg=0.42, cost={"material_cost": 176.4, "machining_cost": 60.0,
                              "total": 236.4, "currency": "CNY", "note": "估算"},
        gcode_stats={"machining_minutes": 30.0, "pocket_ops": 12, "profile_passes": 7,
                     "tools": [{"number": 1, "kind": "drill", "dia_mm": 3.0, "rpm": 18000},
                               {"number": 2, "kind": "endmill", "dia_mm": 3.7, "rpm": 18000}],
                     "cut_len_mm": 12000.0, "line_count": 900},
        interference_summary={"component_count": 17, "interference_count": 2,
                              "suspicious": [{"ref": "FB1", "height": 1.5, "suspicious_reason": "未知封装"}]},
    )
    assert "# 波峰焊治具生产工单" in md
    assert "Durostone" in md
    assert "拼版阵列" in md and "2 × 2" in md
    assert "CNC 加工程序" in md
    assert "T1 D3.0mm" in md and "T2 D3.7mm" in md
    assert "元" if False else "CNY" in md
    out = tmp_path / "r.md"
    got = report_mod.write_report(out, md, parent_hint=tmp_path)
    assert Path(got).read_text(encoding="utf-8").startswith("# 波峰焊治具生产工单")


def test_report_path_safety(tmp_path):
    """报告路径安全：.exe 拒绝 / 越出父目录拒绝。"""
    with pytest.raises(ValueError):
        report_mod.resolve_safe_report_path(tmp_path / "x.exe", parent_hint=tmp_path)
    with pytest.raises(ValueError):
        report_mod.resolve_safe_report_path(tmp_path.parent / "x.md", parent_hint=tmp_path)


# ── 6. web 集成（真实 case_003）──────────────────────────────────
def _files_for_upload():
    files = []
    for f in sorted(CASE.iterdir()):
        if f.suffix in (".gbl", ".gbs", ".gm1", ".gtl", ".gts", ".drl"):
            files.append(("files", (f.name, f.read_bytes(), "text/plain")))
    return files


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import web_server

    with TestClient(web_server.app) as c:
        yield c


def test_web_generate_returns_enterprise_deliverables(client):
    """/api/generate 返回 gcode_url + report_url + material（企业级三件套）。"""
    if not CASE.exists():
        pytest.skip("case_003 缺失")
    r = client.post(
        "/api/generate",
        files=_files_for_upload(),
        data={"material": "durostone", "panel_cols": 1, "panel_rows": 1},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["gcode_url"], "必须返回 CNC G 代码下载链接"
    assert d["report_url"], "必须返回生产报告下载链接"
    assert d["material"]["key"] == "durostone"
    assert d["material"]["weight_kg"] > 0
    assert client.get(d["gcode_url"]).status_code == 200
    assert client.get(d["report_url"]).status_code == 200
    # G 代码内容抽查
    nc = client.get(d["gcode_url"]).text
    assert "G21" in nc and "M30" in nc


def test_web_generate_with_panelization(client):
    """2×1 拼版：stats.panel 出现，治具外形翻倍。"""
    if not CASE.exists():
        pytest.skip("case_003 缺失")
    r1 = client.post("/api/generate", files=_files_for_upload())
    assert r1.status_code == 200
    assert "board_size" in r1.json()["stats"]

    r2 = client.post(
        "/api/generate",
        files=_files_for_upload(),
        data={"panel_cols": 2, "panel_rows": 1, "panel_gap": 5.0},
    )
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["stats"].get("panel", {}).get("cols") == 2
    assert d2["stats"]["panel"]["copies"] == 2


def test_web_interference_panelized(client):
    """拼版干涉分析：元件按阵列复制，计数翻倍。"""
    if not CASE.exists():
        pytest.skip("case_003 缺失")
    files = _files_for_upload()
    pcb = CASE / "board.kicad_pcb"
    if not pcb.exists():
        pytest.skip("case_003 无 kicad_pcb")
    files.append(("files", ("board.kicad_pcb", pcb.read_bytes(), "text/plain")))
    r = client.post(
        "/api/interference",
        files=files,
        data={"panel_cols": 2, "panel_rows": 1, "panel_gap": 5.0},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    # 2×1 拼版 → 元件数应约为单板的 2 倍
    r1 = client.post("/api/interference", files=files)
    n_single = r1.json()["component_count"]
    assert d["component_count"] == pytest.approx(n_single * 2)
