"""波峰焊工装首件检验卡 (FAI Checklist)、工艺指导卡及 DRC 规则 38/39 测试。

对标体系：
- IATF 16949 / ISO 9001 工装夹具首检放行机制
- IPC-A-610G 电子组件焊接外观与透锡质量
- IPC-7351 贴片波峰焊阴影效应
- CNC 机加工深腔刀具长径比 (L/D <= 3.0)
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import box

import drc
from process_card import STANDARD_FAI_ITEMS, generate_process_card_markdown


def test_process_card_fai_items():
    """验证包含完整的 10 项首件检验项目 (涵盖机械尺寸、装配功能、过炉工艺与焊接质量)。"""
    assert len(STANDARD_FAI_ITEMS) == 10
    categories = {item.category for item in STANDARD_FAI_ITEMS}
    assert categories == {"机械尺寸", "装配功能", "过炉工艺", "焊接质量"}
    assert any("沉板贴合间隙" in item.check_item for item in STANDARD_FAI_ITEMS)
    assert any("金手指防爬锡密封" in item.check_item for item in STANDARD_FAI_ITEMS)
    assert any("通孔引脚垂直透锡率" in item.check_item for item in STANDARD_FAI_ITEMS)


def test_generate_process_card_markdown_content():
    """验证生成的首件卡 Markdown 内容符合体系规范。"""
    md = generate_process_card_markdown(
        job_name="TEST_JOB_001",
        pallet_size_str="130.0×105.0mm",
        material_name="Durostone 10mm",
        fasteners_count={"clamps": 4, "pins": 2, "dams": 2},
    )
    assert "波峰焊工装首件检验卡 (FAI Checklist)" in md
    assert "IATF 16949 / ISO 9001" in md
    assert "TEST_JOB_001" in md
    assert "130.0×105.0mm" in md
    assert "压扣×4" in md
    assert "批量生产放行签字栏" in md


def test_drc_rule_chip_wave_shadow_risk():
    """两个相邻避位区过近 (<1.0mm) 时触发 CHIP_WAVE_SHADOW_RISK 阴影效应告警。"""
    # 间距仅 0.5mm
    a1 = box(10, 10, 20, 20)
    a2 = box(20.5, 10, 30.5, 20)
    r1 = SimpleNamespace(
        board_poly=box(0, 0, 80, 80), sink_poly=box(0, 0, 80, 80), handles=[], screws=[], pins=[]
    )
    r2_shadow = SimpleNamespace(
        avoid_polys=[a1, a2],
        solder_polys=[],
        cap_holes=[],
        outer_poly=box(-10, -10, 90, 90),
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=box(0, 0, 80, 80),
        dogbone_corners=[],
        panel_grid=None,
        vent_holes=[],
    )
    issues = drc.run_drc(r1, r2_shadow)
    codes = {i["code"] for i in issues}
    assert "CHIP_WAVE_SHADOW_RISK" in codes


def test_drc_rule_tool_accessibility_ld_ratio():
    """治具板厚过厚导致刀具深径比 L/D > 3.0 时触发 FIXTURE_TOOL_ACCESSIBILITY 告警。"""
    r1 = SimpleNamespace(
        board_poly=box(0, 0, 80, 80), sink_poly=box(0, 0, 80, 80), handles=[], screws=[], pins=[]
    )
    r2 = SimpleNamespace(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=box(-10, -10, 90, 90),
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=box(0, 0, 80, 80),
        dogbone_corners=[],
        panel_grid=None,
        vent_holes=[],
    )
    # 板厚 15mm 对应 Φ3.7mm 铣刀: L/D = 15 / 3.7 = 4.05 > 3.0
    issues = drc.run_drc(r1, r2, pallet_thickness=15.0)
    codes = {i["code"] for i in issues}
    assert "FIXTURE_TOOL_ACCESSIBILITY" in codes

    # 板厚 10mm: L/D = 10 / 3.7 = 2.70 <= 3.0 -> 无告警
    issues2 = drc.run_drc(r1, r2, pallet_thickness=10.0)
    codes2 = {i["code"] for i in issues2}
    assert "FIXTURE_TOOL_ACCESSIBILITY" not in codes2


def test_web_api_generates_fai_card(tmp_path):
    """验证 /api/generate 产生首件检验卡下载链接。"""
    from fastapi.testclient import TestClient

    import web_server

    client = TestClient(web_server.app)
    # 模拟真实工程文件上传
    case_dir = Path("cases/case_003_stm32_4layer")
    if not case_dir.exists():
        pytest.skip("case_003 缺失")

    files = []
    for f in sorted(case_dir.iterdir()):
        if f.suffix in (".gbl", ".gbs", ".gm1", ".gtl", ".gts", ".drl"):
            files.append(("files", (f.name, f.read_bytes(), "text/plain")))

    resp = client.post("/api/generate", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "fai_url" in data and data["fai_url"] is not None
    # 验证下载内容
    fai_resp = client.get(data["fai_url"])
    assert fai_resp.status_code == 200
    assert "波峰焊工装首件检验卡" in fai_resp.text
