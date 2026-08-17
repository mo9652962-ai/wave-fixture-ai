# -*- coding: utf-8 -*-
"""
fixture_3d — 波峰焊治具 3D 预览 + 干涉分析

将 Phase2 的 2D 治具结果（沉板区/避位区/上锡区/治具外形）拉伸成 3D：
- 治具外形 → 底板（厚度 fixture_thickness）
- 沉板区 → 下沉槽（PCB 放置位，深 pcb_thickness）
- 避位区 → 通孔（SMD 元件避位，贯穿板厚）
- 上锡区 → 通孔（插件焊脚，贯穿板厚）

干涉分析：检查避位区/上锡区是否与 PCB 元件（3D 高度）重叠。

输出：STL 文件（可三视/three.js 预览）+ 干涉报告
技术栈：shapely(2D 几何) + trimesh(拉伸/布尔) + numpy
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fixture3d")


@dataclass
class Fixture3DParams:
    """3D 治具参数（单位 mm）"""
    fixture_thickness: float = 8.0    # 治具底板厚度
    pcb_thickness: float = 1.6        # PCB 板厚（沉板区深度）
    sink_depth: float = 1.6           # 沉板区下沉深度
    avoid_depth: float = 8.0          # 避位区通孔深度（贯穿）
    solder_depth: float = 8.0         # 上锡区通孔深度（贯穿）


def polygon_to_extrude(poly: Polygon, z_bottom: float, z_top: float) -> trimesh.Trimesh:
    """2D 多边形 → 3D 拉伸体（沿 Z 轴）"""
    if poly is None or poly.is_empty:
        return None
    # 简化顶点（减少三角面）
    poly = poly.simplify(0.05, preserve_topology=True)
    exterior = np.array(poly.exterior.coords)[:, :2]
    # 用 trimesh 的 extrusion
    path = np.zeros((len(exterior), 3))
    path[:, :2] = exterior
    mesh = trimesh.creation.extrude_polygon(poly, height=z_top - z_bottom)
    # 平移到 z_bottom
    mesh.apply_translation([0, 0, z_bottom])
    return mesh


def build_fixture_3d(
    sink_poly: Polygon,
    avoid_polys: list[Polygon],
    solder_polys: list[Polygon],
    outer_poly: Polygon,
    p: Fixture3DParams = None,
) -> trimesh.Trimesh:
    """构建治具 3D 实体：底板 + 挖沉板区 + 挖避位区 + 挖上锡区"""
    p = p or Fixture3DParams()

    # 1. 治具底板（外形，厚度 fixture_thickness）
    base = polygon_to_extrude(outer_poly, 0, p.fixture_thickness)
    if base is None:
        raise ValueError("治具外形为空，无法构建 3D")

    meshes = [base]
    log.info(f"  底板: {base.volume:.0f} mm³")

    # 2. 沉板区（下沉槽，从顶部挖深 sink_depth）
    if sink_poly is not None and not sink_poly.is_empty:
        sink_3d = polygon_to_extrude(sink_poly, p.fixture_thickness - p.sink_depth, p.fixture_thickness)
        if sink_3d is not None:
            meshes.append(sink_3d)
            log.info(f"  沉板区: {sink_3d.volume:.0f} mm³")

    # 3. 避位区（通孔，贯穿整个厚度）
    for i, poly in enumerate(avoid_polys):
        h = polygon_to_extrude(poly, 0, p.avoid_depth)
        if h is not None:
            meshes.append(h)
    log.info(f"  避位区: {len(avoid_polys)} 个通孔")

    # 4. 上锡区（通孔）
    for i, poly in enumerate(solder_polys):
        h = polygon_to_extrude(poly, 0, p.solder_depth)
        if h is not None:
            meshes.append(h)
    log.info(f"  上锡区: {len(solder_polys)} 个通孔")

    # 布尔运算：底板 - 沉板区 - 避位区 - 上锡区
    result = meshes[0]
    for m in meshes[1:]:
        try:
            result = result.difference(m)
        except Exception as e:
            log.warning(f"  布尔差集失败: {e}")
    return result


def interference_check(
    fixture_mesh: trimesh.Trimesh,
    component_boxes: list[tuple[float, float, float, float, float, float]],
) -> list[dict]:
    """
    干涉分析：检查 PCB 元件（3D 包围盒）是否与治具实体重叠。

    component_boxes: [(x, y, w, h, height, name)] 元件在 PCB 上的包围盒（xy 平面）+ 高度
    返回：干涉报告列表 [{name, overlap_volume, min_z, max_z}]
    """
    reports = []
    for x, y, w, h, height, name in component_boxes:
        # 元件 3D 包围盒（PCB 表面 z=pcb_thickness 起，向上 height）
        comp = trimesh.creation.box(extents=[w, h, height])
        comp.apply_translation([x, y, 1.6 + height / 2])  # PCB 表面 + 半高
        try:
            inter = fixture_mesh.intersection(comp, engine="manifold")
            if inter is not None and inter.volume > 0.001:
                reports.append({
                    "name": name,
                    "overlap_volume_mm3": round(inter.volume, 2),
                    "box": [x, y, w, h, height],
                })
        except Exception as e:
            log.warning(f"  干涉检测 {name} 失败: {e}")
    return reports


def export_stl(mesh: trimesh.Trimesh, out_path: str) -> Path:
    """导出 STL"""
    mesh.export(out_path)
    return Path(out_path)


def export_glb(mesh: trimesh.Trimesh, out_path: str) -> Path:
    """导出 GLB（three.js 直接加载）"""
    mesh.export(out_path, file_type="glb")
    return Path(out_path)


if __name__ == "__main__":
    # 自测：用空调板的结果构建 3D
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from fixture_phase2 import run_phase2

    gerber_dir = r"D:\aircon-pcb-demo\gerber"
    result = run_phase2(gerber_dir, None)  # 不输出 DXF
    if result:
        outer = result.outer_poly
        sink = result.sink_poly if hasattr(result, "sink_poly") else None
        avoid = result.avoid_polys
        solder = result.solder_polys

        # 需要 sink_poly，从 phase1 补
        from fixture_phase1 import parse_gerber, make_sink_region, FixtureParams
        polys, drills = parse_gerber(gerber_dir)
        from shapely.ops import unary_union as _uu
        board = _uu(polys)
        sink = make_sink_region(board, FixtureParams())

        mesh = build_fixture_3d(sink, avoid, solder, outer)
        out = export_stl(mesh, str(Path(__file__).parent / "output" / "fixture-3d.stl"))
        print(f"✅ 3D 治具已导出: {out} ({out.stat().st_size//1024} KB)")
