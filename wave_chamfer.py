"""波峰焊导流斜面倒角 (Bottom Wave Flow Chamfering) 与脱锡防连锡槽 (Solder Thief) 引擎。

工业权威依据：
- AGICORP Wave Solder Pallet Design Guidelines:
  "Pallet machined for solder openings, with 60° bottom side chamfers to maximize solder flow and wave entry."
  底部 60° 倒角是波峰进入的工业标准，45° 倒角适用于贴片间隙受限区域。
- SMTA Wave Soldering Defect Prevention Guidelines:
  开孔垂直直壁会在迎锡侧引起波峰紊流与阴影效应 (Shadow Effect导致漏焊)，
  在脱锡侧 (Trailing Edge) 则因表面张力拉丝导致密集引脚桥连短路 (Bridging)。
  在脱锡边缘设计 1.5mm~2.5mm 的脱锡导流槽 (Solder Thief Relief / Run-off Pocket)
  可加速熔融焊锡剥离回落至锡锅。
- 刀具标准：
  CNC 加工采用 60° 或 90° 锥柄倒角铣刀 (Chamfer Mill)，在开孔底面外轮廓走倒角精修刀路。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon

log = logging.getLogger("fixture-chamfer")


@dataclass
class ChamferParams:
    """导流斜面与脱锡槽参数。"""

    enabled: bool = True
    chamfer_angle_deg: float = 60.0  # 倒角角度：60.0° (标准) 或 45.0°
    chamfer_width_mm: float = 2.0  # 底面导流斜面水平展开宽度 (mm)
    enable_solder_thief: bool = True  # 开启脱锡侧防连锡延伸槽
    solder_thief_len_mm: float = 2.5  # 出口侧脱锡槽延伸长度 (mm)
    conveyor_flow_direction: str = "X+"  # 过板传送方向: "X+" (左至右) | "X-" | "Y+" | "Y-"


@dataclass
class SolderOpeningChamfer:
    """单个上锡开孔的导流倒角与脱锡槽几何图元。"""

    index: int
    original_poly: Polygon
    chamfer_poly: Polygon  # 倒角外扩边界多边形 (底面)
    chamfer_toolpath_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )
    solder_thief_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )
    aspect_ratio: float = 0.0  # 开孔深宽比 (开孔深 / 最小开孔宽)
    min_opening_dim_mm: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "aspect_ratio": round(self.aspect_ratio, 2),
            "min_opening_dim_mm": round(self.min_opening_dim_mm, 2),
            "toolpath_segments": len(self.chamfer_toolpath_lines),
            "has_thief_relief": len(self.solder_thief_lines) > 0,
        }


def generate_wave_flow_chamfers(
    solder_polys: list[Polygon],
    pallet_thickness_mm: float = 10.0,
    board_pocket_depth_mm: float = 2.1,
    params: ChamferParams | None = None,
) -> list[SolderOpeningChamfer]:
    """为各个上锡区生成底面 60°/45° 导流斜面轮廓与脱锡防桥连特征。"""
    p = params or ChamferParams()
    if not p.enabled or not solder_polys:
        return []

    results: list[SolderOpeningChamfer] = []
    # 开孔垂直深度 = 治具总厚度 - 沉板槽深
    hole_depth_mm = max(pallet_thickness_mm - board_pocket_depth_mm, 1.0)

    for i, sp in enumerate(solder_polys):
        if sp is None or sp.is_empty:
            continue

        minx, miny, maxx, maxy = sp.bounds
        w = maxx - minx
        h = maxy - miny
        min_dim = min(w, h)
        # 计算开孔深宽比: 深度 / 最小尺寸 (行业门禁: > 1.2 易导致熔融焊锡毛细阻滞无法填孔)
        aspect_ratio = hole_depth_mm / min_dim if min_dim > 0 else 999.0

        # 1. 倒角外扩边界多边形 (以 chamfer_width 向外缓冲，shapely 2.x 使用 'mitre')
        chamfered = sp.buffer(p.chamfer_width_mm, join_style="mitre")

        # 2. 生成倒角刀心刀路 (沿着倒角中线均匀走刀)
        toolpath_poly = sp.buffer(p.chamfer_width_mm / 2.0, join_style="round")
        toolpath_lines = []
        if isinstance(toolpath_poly, Polygon) and not toolpath_poly.is_empty:
            pts = list(toolpath_poly.exterior.coords)
            for j in range(len(pts) - 1):
                toolpath_lines.append((pts[j], pts[j + 1]))

        # 3. 脱锡侧延伸导流槽 (Solder Thief)
        # 默认传送方向为 X+ (从左至右)，则右侧 (X 最大处) 为脱锡侧 (Trailing Edge)
        thief_lines = []
        if p.enable_solder_thief:
            if p.conveyor_flow_direction == "X+":
                # 在右边缘绘制导流梳齿/倒三角排锡凹槽线
                x_exit = maxx
                y_mid = (miny + maxy) / 2.0
                y_span = min(h * 0.6, 15.0)
                thief_lines.append(
                    ((x_exit, y_mid - y_span / 2.0), (x_exit + p.solder_thief_len_mm, y_mid))
                )
                thief_lines.append(
                    ((x_exit + p.solder_thief_len_mm, y_mid), (x_exit, y_mid + y_span / 2.0))
                )
            elif p.conveyor_flow_direction == "Y+":
                y_exit = maxy
                x_mid = (minx + maxx) / 2.0
                x_span = min(w * 0.6, 15.0)
                thief_lines.append(
                    ((x_mid - x_span / 2.0, y_exit), (x_mid, y_exit + p.solder_thief_len_mm))
                )
                thief_lines.append(
                    ((x_mid, y_exit + p.solder_thief_len_mm), (x_mid + x_span / 2.0, y_exit))
                )

        results.append(
            SolderOpeningChamfer(
                index=i + 1,
                original_poly=sp,
                chamfer_poly=chamfered,
                chamfer_toolpath_lines=toolpath_lines,
                solder_thief_lines=thief_lines,
                aspect_ratio=aspect_ratio,
                min_opening_dim_mm=min_dim,
            )
        )

    log.info(f"✅ 生成 {len(results)} 个上锡开孔的 {p.chamfer_angle_deg:.0f}° 导流倒角与脱锡排锡槽")
    return results


def export_chamfers_to_dxf(
    msp, chamfers: list[SolderOpeningChamfer], layer: str = "导流倒角"
) -> None:
    """将倒角轮廓与脱锡引流线写入 DXF 图纸。"""
    from fixture_phase2 import poly_to_dxf_polyline

    for ch in chamfers:
        # 倒角外框
        poly_to_dxf_polyline(msp, ch.chamfer_poly, layer)
        # 脱锡槽排锡图元
        for p1, p2 in ch.solder_thief_lines:
            msp.add_line(p1, p2, dxfattribs={"layer": layer, "linetype": "DASHED"})
