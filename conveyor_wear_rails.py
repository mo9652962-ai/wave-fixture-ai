"""波峰焊治具传送带链爪耐磨导轨 (Conveyor Wear Rails) 规划引擎。

工业权威依据：
- AGICORP §3.2 (Wave Pallet Conveyor Edge Protection & Wear Strips):
  在全自动波峰焊连续生产流水线中，治具双侧边缘长期与传送带不锈钢链爪或钛合金链指高速滑移接触。
  合成石 (Durostone / Ricocel) 树脂基体在 260°C 高温与机械摩擦共同作用下，运行数千周期后边缘易碳化磨损、
  起毛刺甚至掉渣，导致治具卡轨、走板高度偏斜或倾覆。
  工业级标准方案：在治具沿传送方向的承载边缘铣出台阶槽，镶嵌可更换的 6061-T6 硬质阳极氧化铝合金
  或 Grade 2 纯钛耐磨滑轨条 (厚 1.5~2.5mm，宽 8.0~12.0mm)，通过 M3 沉头螺钉固定，大幅延长治具基体寿命。
- Kurtz Ersa / SEHO / Vitronics Soltec 工业波峰焊设备规范：
  链爪与链指咬合有效深度通常为 5.0~8.0mm；耐磨条宽度需完全覆盖链爪咬合区，
  且外边缘与沉板区、元器件避位开槽保持 ≥ 8.0mm 安全绝缘与机械间隙，严防链爪刮碰 PCB。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon, box

log = logging.getLogger("conveyor-wear-rails")


@dataclass
class ConveyorWearRailsParams:
    """传送带耐磨导轨规划参数。"""

    enabled: bool = True
    rail_width_mm: float = 10.0  # 耐磨导轨条宽度 (mm, 8~12mm)
    rail_thickness_mm: float = 2.0  # 导轨条厚度 (mm, 沉入治具台阶槽)
    material: str = "6061_t6_anodized"  # 材质: 6061_t6_anodized 或 titanium_gr2
    screw_dia_mm: float = 3.0  # M3 沉头固定螺钉
    screw_csk_dia_mm: float = 6.5  # 90° 沉头窝座直径 (mm)
    screw_pitch_mm: float = 100.0  # 螺钉均布间距 (mm, 80~120mm)
    edge_margin_mm: float = 20.0  # 螺钉距导轨两端的安全退让边距 (mm)
    conveyor_axis: str = "Y"  # 走板行进轴向: 'Y' (左右两侧为承载边) 或 'X' (上下两侧)


@dataclass
class WearRailSegment:
    """单个耐磨导轨条物理属性与装配位置。"""

    side: str  # 'left' | 'right' | 'top' | 'bottom'
    length_mm: float
    width_mm: float
    thickness_mm: float
    material: str
    poly: Polygon
    mounting_holes: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class ConveyorWearRailsResult:
    """耐磨导轨条与固定紧固件整体规划结果。"""

    rails: list[WearRailSegment] = field(default_factory=list)
    total_rail_length_mm: float = 0.0
    mounting_hole_count: int = 0
    material: str = "6061_t6_anodized"
    min_clearance_to_sink_mm: float = 999.0
    bom_items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rail_count": len(self.rails),
            "total_rail_length_mm": round(self.total_rail_length_mm, 2),
            "mounting_hole_count": self.mounting_hole_count,
            "material": self.material,
            "min_clearance_to_sink_mm": (
                round(self.min_clearance_to_sink_mm, 2)
                if self.min_clearance_to_sink_mm < 900
                else None
            ),
            "rails": [
                {
                    "side": r.side,
                    "length_mm": round(r.length_mm, 2),
                    "width_mm": round(r.width_mm, 2),
                    "thickness_mm": round(r.thickness_mm, 2),
                    "material": r.material,
                    "mounting_holes": [
                        (round(x, 2), round(y, 2)) for (x, y) in r.mounting_holes
                    ],
                }
                for r in self.rails
            ],
            "bom_items": self.bom_items,
        }


def plan_conveyor_wear_rails(
    outer_poly: Polygon | None,
    sink_poly: Polygon | None = None,
    params: ConveyorWearRailsParams | None = None,
) -> ConveyorWearRailsResult:
    """根据治具外形与走板传送方向规划两侧耐磨导轨与 M3 沉头螺孔。

    Args:
        outer_poly: 治具外形边界多边形
        sink_poly: 沉板区边界多边形 (可选，用于校核耐磨条与沉板区安全距离)
        params: 导轨参数配置

    Returns:
        ConveyorWearRailsResult: 导轨几何多边形、螺孔坐标与 BOM 清单
    """
    if params is None:
        params = ConveyorWearRailsParams()

    if not params.enabled or outer_poly is None or outer_poly.is_empty:
        return ConveyorWearRailsResult()

    minx, miny, maxx, maxy = outer_poly.bounds
    w = maxx - minx
    h = maxy - miny

    rails: list[WearRailSegment] = []
    total_len = 0.0
    total_holes = 0

    rw = max(5.0, min(params.rail_width_mm, min(w, h) * 0.2))
    pitch = max(40.0, params.screw_pitch_mm)
    margin = max(10.0, params.edge_margin_mm)

    if params.conveyor_axis.upper() == "Y":
        # 走板 Y 轴向：耐磨导轨位于左右两侧 (Left & Right)
        rail_len = h
        # 左侧耐磨条
        left_poly = box(minx, miny, minx + rw, maxy)
        left_holes = _distribute_holes(
            center_x=minx + rw / 2.0,
            start_coord=miny + margin,
            end_coord=maxy - margin,
            pitch=pitch,
            axis="Y",
        )
        rails.append(
            WearRailSegment(
                side="left",
                length_mm=rail_len,
                width_mm=rw,
                thickness_mm=params.rail_thickness_mm,
                material=params.material,
                poly=left_poly,
                mounting_holes=left_holes,
            )
        )
        # 右侧耐磨条
        right_poly = box(maxx - rw, miny, maxx, maxy)
        right_holes = _distribute_holes(
            center_x=maxx - rw / 2.0,
            start_coord=miny + margin,
            end_coord=maxy - margin,
            pitch=pitch,
            axis="Y",
        )
        rails.append(
            WearRailSegment(
                side="right",
                length_mm=rail_len,
                width_mm=rw,
                thickness_mm=params.rail_thickness_mm,
                material=params.material,
                poly=right_poly,
                mounting_holes=right_holes,
            )
        )
        total_len = rail_len * 2
        total_holes = len(left_holes) + len(right_holes)

    else:
        # 走板 X 轴向：耐磨导轨位于上下两侧 (Bottom & Top)
        rail_len = w
        # 下侧耐磨条
        bottom_poly = box(minx, miny, maxx, miny + rw)
        bottom_holes = _distribute_holes(
            center_x=miny + rw / 2.0,
            start_coord=minx + margin,
            end_coord=maxx - margin,
            pitch=pitch,
            axis="X",
        )
        rails.append(
            WearRailSegment(
                side="bottom",
                length_mm=rail_len,
                width_mm=rw,
                thickness_mm=params.rail_thickness_mm,
                material=params.material,
                poly=bottom_poly,
                mounting_holes=bottom_holes,
            )
        )
        # 上侧耐磨条
        top_poly = box(minx, maxy - rw, maxx, maxy)
        top_holes = _distribute_holes(
            center_x=maxy - rw / 2.0,
            start_coord=minx + margin,
            end_coord=maxx - margin,
            pitch=pitch,
            axis="X",
        )
        rails.append(
            WearRailSegment(
                side="top",
                length_mm=rail_len,
                width_mm=rw,
                thickness_mm=params.rail_thickness_mm,
                material=params.material,
                poly=top_poly,
                mounting_holes=top_holes,
            )
        )
        total_len = rail_len * 2
        total_holes = len(bottom_holes) + len(top_holes)

    # 校核与沉板区的最小净距
    min_clr = 999.0
    if sink_poly and not sink_poly.is_empty:
        for r in rails:
            d = r.poly.distance(sink_poly)
            min_clr = min(min_clr, d)

    # 生成物料清单 BOM
    mat_desc = (
        "6061-T6 阳极硬质氧化铝合金耐磨条"
        if params.material == "6061_t6_anodized"
        else "Grade 2 纯钛耐磨防腐导轨条"
    )
    bom_items = [
        {
            "part": f"CONVEYOR-WEAR-STRIP-{params.material.upper()}",
            "description": f"{mat_desc} ({rw:g}mm×{params.rail_thickness_mm:g}mm×{rail_len:g}mm)",
            "quantity": len(rails),
            "unit": "条",
        },
        {
            "part": "SCREW-M3-CSK-DIN7991",
            "description": "M3×8mm 不锈钢沉头十字螺钉 (DIN 7991)",
            "quantity": total_holes,
            "unit": "颗",
        },
    ]

    return ConveyorWearRailsResult(
        rails=rails,
        total_rail_length_mm=total_len,
        mounting_hole_count=total_holes,
        material=params.material,
        min_clearance_to_sink_mm=min_clr,
        bom_items=bom_items,
    )


def _distribute_holes(
    center_x: float,
    start_coord: float,
    end_coord: float,
    pitch: float,
    axis: str,
) -> list[tuple[float, float]]:
    """在导轨中心线上按 pitch 均布螺钉孔。"""
    span = end_coord - start_coord
    if span <= 0:
        coord = (start_coord + end_coord) / 2.0
        return [(center_x, coord)] if axis == "Y" else [(coord, center_x)]

    count = max(2, math.ceil(span / pitch) + 1)
    actual_step = span / (count - 1)

    holes = []
    for i in range(count):
        c = start_coord + i * actual_step
        if axis == "Y":
            holes.append((center_x, c))
        else:
            holes.append((c, center_x))
    return holes


def export_conveyor_wear_rails_to_dxf(msp, result: ConveyorWearRailsResult) -> None:
    """输出耐磨导轨轮廓与 M3 沉头螺孔图元至 DXF 专用图层。"""
    layer_name = "耐磨导轨"

    for r in result.rails:
        if r.poly and not r.poly.is_empty:
            pts = list(r.poly.exterior.coords)
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})

        for hx, hy in r.mounting_holes:
            # 螺孔底孔 Φ3.4mm (r=1.7mm)
            msp.add_circle((hx, hy), radius=1.7, dxfattribs={"layer": layer_name})
            # 沉头窝座 Φ6.5mm (r=3.25mm)
            msp.add_circle((hx, hy), radius=3.25, dxfattribs={"layer": layer_name, "linetype": "DASHED"})

        if r.mounting_holes:
            mid_hole = r.mounting_holes[len(r.mounting_holes) // 2]
            msp.add_text(
                f"WEAR-RAIL {r.material.upper()}",
                dxfattribs={"layer": layer_name, "height": 3.0},
            ).set_placement((mid_hole[0] + 5.0, mid_hole[1]))

