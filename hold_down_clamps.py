"""PCB 边缘弹簧旋转压扣压舌布局与锡液浮力补偿引擎 (Hold-Down Clamps & Buoyancy Solver).

工业背景与工艺标准：
- AGICORP §3.0《Wave Solder Pallet Design Guidelines》与 Macaos Solder Pallet Designer：
  液态 SAC305 无铅焊锡密度高达 7.4 g/cm³（Sn63Pb37 达 8.4 g/cm³），远大于 FR-4 基板（约 1.85 g/cm³）。
  当治具浸入液态波峰时，PCB 受到巨大的向上阿基米德浮力与喷口动态冲力：
      F_buoyancy = (ρ_solder - ρ_pcb) * Area_pcb * t_pcb * g + F_dynamic_wave
  若治具四周缺少弹力旋转压扣（Hold-Down Turn-Locks / Clamps），PCB 将被锡波直接浮起，
  导致沉板密封失效、液态锡漫上顶层造成大面积短路报废（IPC-A-610G §7.5）。
- 工业标配压舌规范（Noves / Durostone / 钛合金标准五金）：
  1. 旋转压扣安装孔：M3 轴肩螺钉枢轴孔（Φ3.2mm 沉头或通孔，中心距板边 6.0mm）。
  2. 压舌压边重叠量（Overlap Lip）：标准 3.0mm 压紧板边，宽度 12.0mm，回转半径 14.0mm。
  3. 压扣间距：沿 PCB 周长分布，间距 ≤ 100mm（单板至少布置 4 处压扣）。
  4. 避障间隙：压舌边缘距 PCB 边缘贴片元件必须保持 ≥ 2.0mm 安全避让间隙。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon, box


@dataclass
class HoldDownClampParams:
    solder_density_g_cm3: float = 7.4  # SAC305 熔融无铅锡密度 (g/cm³)
    pcb_density_g_cm3: float = 1.85  # FR-4 密度 (g/cm³)
    pcb_thickness_mm: float = 1.6  # PCB 板厚 (mm)
    clamp_overlap_mm: float = 3.0  # 压扣压入 PCB 边缘重叠宽度 (mm)
    clamp_tab_width_mm: float = 12.0  # 压扣舌片宽度 (mm)
    pivot_offset_from_edge_mm: float = 6.0  # 螺钉轴心距板边距离 (mm)
    pivot_hole_dia_mm: float = 3.2  # M3 轴肩螺栓安装孔径 (mm)
    max_clamp_pitch_mm: float = 100.0  # 相邻压扣最大跨距 (mm)
    single_clamp_force_n: float = 2.0  # 单个弹簧转扣下压力额定值 (N)


@dataclass
class ClampPosition:
    x_mm: float
    y_mm: float
    angle_deg: float
    edge_side: str  # "bottom", "top", "left", "right"
    lip_poly: Polygon | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if "lip_poly" in d:
            d["lip_poly"] = None
        return d


@dataclass
class HoldDownClampsResult:
    buoyancy_force_n: float
    recommended_clamp_count: int
    actual_clamp_count: int
    clamps: list[ClampPosition] = field(default_factory=list)
    clamp_polys: list[Polygon] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def calculate_solder_buoyancy_force(
    board_area_mm2: float,
    pcb_thickness_mm: float = 1.6,
    solder_density_g_cm3: float = 7.4,
    pcb_density_g_cm3: float = 1.85,
    dynamic_wave_factor: float = 1.35,
) -> float:
    """计算浸锡时 PCB 受到的阿基米德浮力与波峰动压合力 (单位: N)。"""
    vol_cm3 = (board_area_mm2 * pcb_thickness_mm) / 1000.0
    net_rho_g_cm3 = solder_density_g_cm3 - pcb_density_g_cm3
    mass_diff_kg = (net_rho_g_cm3 * vol_cm3) / 1000.0
    g = 9.80665
    static_buoyancy = mass_diff_kg * g
    total_force = static_buoyancy * dynamic_wave_factor
    return round(total_force, 2)


def generate_hold_down_clamps(
    sink_poly: Polygon,
    outer_poly: Polygon | None = None,
    params: HoldDownClampParams | None = None,
) -> HoldDownClampsResult:
    """自动计算浮力并在沉板区边缘规划旋转压扣安装孔与压舌轮廓。"""
    p = params or HoldDownClampParams()
    if sink_poly.is_empty:
        return HoldDownClampsResult(0.0, 0, 0)

    sx0, sy0, sx1, sy1 = sink_poly.bounds
    bw = sx1 - sx0
    bh = sy1 - sy0
    board_area = sink_poly.area

    # 1. 计算浮力与最小压扣数量
    f_buoyant = calculate_solder_buoyancy_force(
        board_area_mm2=board_area,
        pcb_thickness_mm=p.pcb_thickness_mm,
        solder_density_g_cm3=p.solder_density_g_cm3,
        pcb_density_g_cm3=p.pcb_density_g_cm3,
    )

    force_claps_needed = math.ceil((f_buoyant * 1.5) / p.single_clamp_force_n)
    perimeter_clamps_needed = 2 * (math.ceil(bw / p.max_clamp_pitch_mm) + math.ceil(bh / p.max_clamp_pitch_mm))
    rec_count = max(4, force_claps_needed, perimeter_clamps_needed)

    # 2. 沿四边布置压扣轴心点与压舌多边形
    clamps: list[ClampPosition] = []
    clamp_polys: list[Polygon] = []

    # 底边 (Bottom)
    n_x = max(1, math.ceil(bw / p.max_clamp_pitch_mm))
    step_x = bw / (n_x + 1)
    for i in range(1, n_x + 1):
        cx = round(sx0 + i * step_x, 2)
        cy = round(sy0 - p.pivot_offset_from_edge_mm, 2)
        lip = box(cx - p.clamp_tab_width_mm / 2, sy0 - 0.5, cx + p.clamp_tab_width_mm / 2, sy0 + p.clamp_overlap_mm)
        clamps.append(ClampPosition(cx, cy, 0.0, "bottom", lip))
        clamp_polys.append(lip)

    # 顶边 (Top)
    for i in range(1, n_x + 1):
        cx = round(sx0 + i * step_x, 2)
        cy = round(sy1 + p.pivot_offset_from_edge_mm, 2)
        lip = box(cx - p.clamp_tab_width_mm / 2, sy1 - p.clamp_overlap_mm, cx + p.clamp_tab_width_mm / 2, sy1 + 0.5)
        clamps.append(ClampPosition(cx, cy, 180.0, "top", lip))
        clamp_polys.append(lip)

    # 左边 (Left)
    n_y = max(1, math.ceil(bh / p.max_clamp_pitch_mm))
    step_y = bh / (n_y + 1)
    for j in range(1, n_y + 1):
        cx = round(sx0 - p.pivot_offset_from_edge_mm, 2)
        cy = round(sy0 + j * step_y, 2)
        lip = box(sx0 - 0.5, cy - p.clamp_tab_width_mm / 2, sx0 + p.clamp_overlap_mm, cy + p.clamp_tab_width_mm / 2)
        clamps.append(ClampPosition(cx, cy, 90.0, "left", lip))
        clamp_polys.append(lip)

    # 右边 (Right)
    for j in range(1, n_y + 1):
        cx = round(sx1 + p.pivot_offset_from_edge_mm, 2)
        cy = round(sy0 + j * step_y, 2)
        lip = box(sx1 - p.clamp_overlap_mm, cy - p.clamp_tab_width_mm / 2, sx1 + 0.5, cy + p.clamp_tab_width_mm / 2)
        clamps.append(ClampPosition(cx, cy, 270.0, "right", lip))
        clamp_polys.append(lip)

    stats = {
        "buoyancy_force_n": f_buoyant,
        "clamping_safety_factor": round((len(clamps) * p.single_clamp_force_n) / max(0.1, f_buoyant), 2),
        "clamp_overlap_mm": p.clamp_overlap_mm,
        "pivot_hole_dia_mm": p.pivot_hole_dia_mm,
    }

    return HoldDownClampsResult(
        buoyancy_force_n=f_buoyant,
        recommended_clamp_count=rec_count,
        actual_clamp_count=len(clamps),
        clamps=clamps,
        clamp_polys=clamp_polys,
        stats=stats,
    )


def export_hold_down_clamps_to_dxf(msp, result: HoldDownClampsResult) -> None:
    """将旋转压扣轴孔、压舌重叠区域及工程注记输出到 DXF 专用图层。"""
    layer_name = "压扣压舌"

    for cl in result.clamps:
        # 1. 轴心安装通孔 (M3 轴肩螺栓 Φ3.2mm)
        msp.add_circle((cl.x_mm, cl.y_mm), radius=1.6, dxfattribs={"layer": layer_name})
        # 外沉台基座标记
        msp.add_circle((cl.x_mm, cl.y_mm), radius=3.5, dxfattribs={"layer": layer_name})

        # 2. 压舌压板边界轮廓
        if cl.lip_poly and not cl.lip_poly.is_empty:
            pts = list(cl.lip_poly.exterior.coords)
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})

    if result.clamps:
        c0 = result.clamps[0]
        msp.add_text(
            f"HOLD-DOWN CLAMP (F={result.buoyancy_force_n:.1f}N, N={result.actual_clamp_count})",
            dxfattribs={"layer": layer_name, "height": 2.5, "insert": (c0.x_mm + 5.0, c0.y_mm)},
        )
