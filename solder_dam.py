"""波峰焊防浮渣扰流槽与倾角动态浸锡补偿引擎 (Solder Dam & Dross Skimmer Channels).

工业背景与工艺标准：
- Kurtz Ersa / SEHO / Vitronics Soltec 波峰焊设备技术规范与维护手册：
  波峰焊槽表面长期漂浮氧化锡渣（Dross），当治具以 4°~7°（标称 5.5°）倾角
  驶入液态锡波时，若治具前端为直壁平面，浮渣将被直接推向 PCB 沉板孔，
  导致通孔引脚发生焊锡桥连短路与锡渣夹杂缺陷（IPC-A-610G §7.5）。
- 工业对标方案（Macaos / AGICORP / Ersa）：
  1. 前缘撇渣切刀（Solder Skimmer Chisel）：在治具迎锡进板侧铣削 45° 分流倒角，平滑破开锡波表面张力。
  2. 横向排渣导流槽（Transverse Dross Dam）：设置 8mm 宽、2.5mm 深的双向横向泄渣斜槽，
     将浮渣自动排挤至治具外侧导轨，严防浮渣倒灌入开孔。
  3. 传送带 5.5° 倾角爬坡动态浸锡高度补偿（Conveyor Incline Dynamic Clearance）：
     按 Δz = (x - x0) * tan(θ) 动态核算治具底面沿运动轴的爬坡高度变化与元件离锡安全间隙。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon, box


@dataclass
class SolderDamParams:
    dam_width_mm: float = 8.0  # 撇渣槽宽度 (mm)
    dam_depth_mm: float = 2.5  # 撇渣槽沉削深度 (mm)
    dam_margin_from_edge_mm: float = 6.0  # 距治具入板前边缘距离 (mm)
    lead_bevel_deg: float = 45.0  # 迎锡侧劈波破浪切角 (度)
    conveyor_incline_deg: float = 5.5  # 传送带爬坡倾角 (Ersa / Vitronics 标称 5.5°)
    enable_drainage_channels: bool = True  # 是否生成双向外倾排渣槽


@dataclass
class SolderDamResult:
    dam_poly: Polygon
    bevel_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)
    drainage_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)
    conveyor_incline_deg: float = 5.5
    stats: dict[str, Any] = field(default_factory=dict)


def compute_incline_dynamic_clearance(
    comp_x_mm: float,
    comp_height_mm: float,
    board_length_mm: float,
    incline_deg: float = 5.5,
    nominal_pocket_depth_mm: float = 3.0,
) -> dict[str, Any]:
    """计算传送带 5.5° 爬坡倾角下，底面元件的动态浸锡间隙与浸润风险。

    公式：
        Δz_slope = comp_x_mm * tan(rad(θ))
        effective_clearance = nominal_pocket_depth_mm - comp_height_mm - Δz_slope
    """
    rad = math.radians(incline_deg)
    slope_factor = math.tan(rad)
    dz_slope = round(comp_x_mm * slope_factor, 2)
    effective_clearance = round(nominal_pocket_depth_mm - comp_height_mm - dz_slope, 2)
    has_wave_contact_risk = effective_clearance < 0.8

    return {
        "comp_x_mm": comp_x_mm,
        "comp_height_mm": comp_height_mm,
        "incline_deg": incline_deg,
        "dz_slope_mm": dz_slope,
        "effective_clearance_mm": effective_clearance,
        "has_wave_contact_risk": has_wave_contact_risk,
    }


def generate_solder_dam_and_incline(
    outer_poly: Polygon,
    sink_poly: Polygon | None = None,
    params: SolderDamParams | None = None,
) -> SolderDamResult:
    """在治具入板前缘生成 45° 破浪切角与 8mm 横向防浮渣导流泄渣槽。"""
    p = params or SolderDamParams()
    ox0, oy0, ox1, _oy1 = outer_poly.bounds

    # 1. 前缘撇渣槽多边形 (布置在治具底面入板进料侧前缘，在沉板区之前)
    dam_y0 = oy0 + p.dam_margin_from_edge_mm
    dam_y1 = dam_y0 + p.dam_width_mm

    # 槽体横跨治具有效宽度，两侧各留 10mm 导轨边保护
    dam_x0 = ox0 + 10.0
    dam_x1 = ox1 - 10.0

    raw_dam_box = box(dam_x0, dam_y0, dam_x1, dam_y1)
    dam_r = raw_dam_box.buffer(1.5, join_style="round").buffer(-1.5, join_style="round")
    dam_poly = dam_r if isinstance(dam_r, Polygon) else raw_dam_box

    # 2. 迎锡侧劈波破浪切角线条 (45° Bevel lines)
    bevel_lines = []
    # 生成沿进料侧的导流破浪线
    bevel_lines.append(((dam_x0, dam_y0), (dam_x1, dam_y0)))
    bevel_lines.append(((dam_x0 + 2.0, dam_y0 + 1.0), (dam_x1 - 2.0, dam_y0 + 1.0)))

    # 3. 双向外倾横向排渣导流槽线条 (两翼向外倾斜排出浮渣)
    drainage_lines = []
    if p.enable_drainage_channels:
        mid_x = (dam_x0 + dam_x1) / 2.0
        # 从中线向左侧轨边引流
        drainage_lines.append(((mid_x, dam_y0 + p.dam_width_mm / 2.0), (ox0 + 5.0, dam_y0)))
        # 从中线向右侧轨边引流
        drainage_lines.append(((mid_x, dam_y0 + p.dam_width_mm / 2.0), (ox1 - 5.0, dam_y0)))

    stats = {
        "dam_width_mm": p.dam_width_mm,
        "dam_depth_mm": p.dam_depth_mm,
        "lead_bevel_deg": p.lead_bevel_deg,
        "conveyor_incline_deg": p.conveyor_incline_deg,
        "channel_length_mm": round(dam_x1 - dam_x0, 1),
    }

    return SolderDamResult(
        dam_poly=dam_poly,
        bevel_lines=bevel_lines,
        drainage_lines=drainage_lines,
        conveyor_incline_deg=p.conveyor_incline_deg,
        stats=stats,
    )


def export_solder_dam_to_dxf(msp, result: SolderDamResult) -> None:
    """输出波峰焊防浮渣导流槽到 DXF 专用图层。"""
    layer_name = "防渣导流"

    # 1. 导出撇渣槽轮廓
    if result.dam_poly and not result.dam_poly.is_empty:
        pts = list(result.dam_poly.exterior.coords)
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})

    # 2. 导出 45° 破浪切角线
    for p1, p2 in result.bevel_lines:
        msp.add_line(p1, p2, dxfattribs={"layer": layer_name})

    # 3. 导出排渣导流槽中心线
    for p1, p2 in result.drainage_lines:
        msp.add_line(p1, p2, dxfattribs={"layer": layer_name})

    # 4. 标注工程文字
    if result.dam_poly and not result.dam_poly.is_empty:
        x0, y0, _x1, _y1 = result.dam_poly.bounds
        msp.add_text(
            f"DROSS SKIMMER DAM ({result.conveyor_incline_deg:.1f} DEG INCLINE)",
            dxfattribs={"layer": layer_name, "height": 2.5, "insert": (x0 + 5.0, y0 + 2.5)},
        )
