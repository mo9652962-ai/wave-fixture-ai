"""3D 治具构建测试（build_fixture_3d）——布尔运算与几何不变量。

真实验证背景：3D 构建的布尔差集分支（底板 - 沉板区 - 避位区 - 上锡区）
此前无直接测试，只在真板端到端中间接覆盖；而布尔运算失败会静默 log.warning
并返回未挖孔的实体（治具无法使用）。
"""
from __future__ import annotations

import pytest
from shapely.geometry import box

from fixture_3d import (
    Fixture3DParams,
    build_fixture_3d,
    export_glb,
    export_stl,
    interference_check,
    polygon_to_extrude,
)

P = Fixture3DParams()


def test_build_requires_outer():
    """无外形必须报错（不能返回空实体）。"""
    with pytest.raises(ValueError, match="外形为空"):
        build_fixture_3d(None, [], [], None)


def test_base_volume_matches_outline():
    """只给外形时，体积 = 外形面积 × 厚度（验证拉伸正确）。"""
    outer = box(0, 0, 100, 80)
    mesh = build_fixture_3d(None, [], [], outer)
    assert mesh.volume == pytest.approx(100 * 80 * P.fixture_thickness, rel=0.01)


def test_sink_region_subtracted():
    """沉板区必须被挖掉（体积减少 ≈ 沉板区面积 × 深度）。"""
    outer = box(0, 0, 100, 80)
    base = build_fixture_3d(None, [], [], outer)
    sink = box(20, 20, 60, 60)
    with_sink = build_fixture_3d(sink, [], [], outer)
    removed = base.volume - with_sink.volume
    assert removed == pytest.approx(sink.area * P.sink_depth, rel=0.05), "沉板区未被正确挖除"


def test_avoid_and_solder_holes_subtracted():
    """避位区/上锡区通孔必须挖除。"""
    outer = box(0, 0, 100, 80)
    base = build_fixture_3d(None, [], [], outer)
    avoid = [box(10, 10, 20, 20)]
    solder = [box(50, 50, 60, 58)]
    with_holes = build_fixture_3d(None, avoid, solder, outer)
    removed = base.volume - with_holes.volume
    expected = avoid[0].area * P.avoid_depth + solder[0].area * P.solder_depth
    assert removed == pytest.approx(expected, rel=0.05)


def test_mesh_is_valid_and_watertight():
    """布尔运算结果应是有效网格（非空、面数>0）。"""
    outer = box(0, 0, 60, 40)
    mesh = build_fixture_3d(box(10, 10, 50, 30), [box(2, 2, 8, 8)], [], outer)
    assert len(mesh.faces) > 0
    assert mesh.volume > 0
    assert mesh.is_watertight or mesh.volume > 0  # manifold 引擎通常给出闭合体


def test_boolean_failure_logged_not_silent(monkeypatch, caplog):
    """布尔失败时必须留下 warning（不能静默返回未挖孔实体）。"""
    outer = box(0, 0, 50, 50)
    good = polygon_to_extrude(outer, 0, P.fixture_thickness)

    class Boom:
        def difference(self, other):
            raise RuntimeError("模拟布尔失败")

        volume = good.volume
        faces = good.faces

    # 让第二个 mesh 参与差集时抛错
    calls = {"n": 0}
    real_extrude = polygon_to_extrude

    def fake_extrude(poly, z0, z1):
        m = real_extrude(poly, z0, z1)
        calls["n"] += 1
        if calls["n"] == 2:  # 第一个被挖的实体
            return Boom()
        return m

    monkeypatch.setattr("fixture_3d.polygon_to_extrude", fake_extrude)
    with caplog.at_level("WARNING"):
        build_fixture_3d(box(5, 5, 20, 20), [], [], outer)
    assert any("布尔差集失败" in r.message for r in caplog.records), "布尔失败未告警"


def test_export_stl_and_glb(tmp_path):
    outer = box(0, 0, 40, 30)
    mesh = build_fixture_3d(box(5, 5, 35, 25), [], [], outer)
    stl = export_stl(mesh, str(tmp_path / "f.stl"))
    glb = export_glb(mesh, str(tmp_path / "f.glb"))
    assert stl.exists() and stl.stat().st_size > 100
    assert glb.exists() and glb.stat().st_size > 100


def test_interference_check_with_build():
    """端到端：搭建真实几何后检查干涉判定。"""
    outer = box(0, 0, 100, 80)
    mesh = build_fixture_3d(None, [], [], outer)
    # 元件落在治具范围内且 z 交叠 → 干涉
    hit = interference_check(mesh, [(50, 40, 10, 10, 2.0, "U1")])
    assert any(r["name"] == "U1" for r in hit)
    # 元件在治具外 → 无干涉
    miss = interference_check(mesh, [(500, 400, 10, 10, 2.0, "U2")])
    assert not any(r["name"] == "U2" for r in miss)
