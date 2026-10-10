"""钛合金耐磨挡锡刀片嵌件与双波峰浸锡时间窗口求解器 (Titanium Inserts & Wave Dwell Time Solver).

工业背景与工艺标准：
- AGICORP §5.0《Wave Solder Pallet Design Guidelines》与 Ersa / SEHO 维护规程：
  复合合成石（Durostone / Ricocel）在连续 260°C 熔融锡流长期冲刷下，
  厚度 < 2.0mm 的相邻上锡开孔隔锡肋壁（Thin Wall / Knife-Edge Dam）极易发生
  树脂碳化剥落、分层断裂，导致两侧开孔锡流串通引发大规模焊锡桥连报废。
  工业级量产治具强制要求在 < 1.8mm 薄壁处镶嵌 0.8mm~1.0mm 纯钛（Grade 2 Titanium）
  或不锈钢 316 耐磨薄片，并由 M2 沉头耐高温螺钉固定（螺距 20~30mm）。
- SMTA Wave Soldering Handbook & IPC J-STD-001 浸锡接触时间（Dwell Time）规范：
  波峰浸润时间 t_dwell = L_pocket / v_conveyor。
  SAC305 无铅合金标准要求：
    * 芯片扰流波 (Chip Wave): 0.5s ~ 1.5s (破除气泡与阴影效应)
    * 主平滑波 (Main Wave): 2.5s ~ 4.5s (充分润湿与引脚透锡)
    * 总有效接触时间: 3.0s ~ 5.5s (传送带速度 0.8 ~ 1.5 m/min)
  若上锡开口沿走板轴行程过短导致 t_dwell < 2.5s 则透锡不足，行程过长导致 t_dwell > 6.0s 则造成基板热冲击分层。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon, box


@dataclass
class TitaniumInsertParams:
    blade_thickness_mm: float = 0.8  # 钛合金刀片厚度 (mm)
    blade_height_mm: float = 8.0  # 钛刀片高度 (mm)
    fixing_screw_hole_dia_mm: float = 2.2  # M2 沉头螺丝固定孔径 (mm)
    fixing_screw_pitch_mm: float = 25.0  # 螺丝间距 (mm)
    knife_edge_threshold_mm: float = 1.8  # 触发加装钛嵌件的临界壁厚 (mm)
    conveyor_speed_m_per_min: float = 1.1  # 标称传送带线速度 (m/min)


@dataclass
class TitaniumBlade:
    blade_id: str
    center_x_mm: float
    center_y_mm: float
    length_mm: float
    thickness_mm: float
    orientation: str  # "horizontal" or "vertical"
    screw_holes: list[tuple[float, float]] = field(default_factory=list)
    boundary_poly: Polygon | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if "boundary_poly" in d:
            d["boundary_poly"] = None
        return d


@dataclass
class DwellTimeWindow:
    pocket_length_x_mm: float
    conveyor_speed_m_per_min: float
    dwell_time_sec: float
    min_compliant_dwell_sec: float = 2.5
    max_compliant_dwell_sec: float = 5.5
    is_compliant: bool = True
    status_summary: str = "PASS"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TitaniumInsertsResult:
    thin_walls_detected: int
    blades: list[TitaniumBlade] = field(default_factory=list)
    dwell_window: DwellTimeWindow | None = None
    stats: dict[str, Any] = field(default_factory=dict)


def calculate_wave_dwell_window(
    pocket_length_x_mm: float,
    conveyor_speed_m_per_min: float = 1.1,
    min_dwell_sec: float = 2.5,
    max_dwell_sec: float = 5.5,
) -> DwellTimeWindow:
    """依据走板轴 X 向上锡开口有效行程计算波峰焊接接触时间 (Dwell Time)。"""
    speed_mm_per_sec = (conveyor_speed_m_per_min * 1000.0) / 60.0
    dwell = round(pocket_length_x_mm / max(1.0, speed_mm_per_sec), 2)
    compliant = min_dwell_sec <= dwell <= max_dwell_sec

    if dwell < min_dwell_sec:
        summary = f"TOO_SHORT (浸锡仅 {dwell:.2f}s < {min_dwell_sec}s，透锡不足与虚焊风险)"
    elif dwell > max_dwell_sec:
        summary = f"TOO_LONG (浸锡长达 {dwell:.2f}s > {max_dwell_sec}s，基板热冲击分层风险)"
    else:
        summary = f"COMPLIANT ({dwell:.2f}s 在 IPC 标准 {min_dwell_sec}~{max_dwell_sec}s 窗口内)"

    return DwellTimeWindow(
        pocket_length_x_mm=pocket_length_x_mm,
        conveyor_speed_m_per_min=conveyor_speed_m_per_min,
        dwell_time_sec=dwell,
        min_compliant_dwell_sec=min_dwell_sec,
        max_compliant_dwell_sec=max_dwell_sec,
        is_compliant=compliant,
        status_summary=summary,
    )


def detect_knife_edge_walls_and_inserts(
    solder_polys: list[Polygon],
    params: TitaniumInsertParams | None = None,
) -> TitaniumInsertsResult:
    """检测相邻上锡开孔之间的狭窄薄壁，并自动规划钛合金加固刀片嵌件与 M2 紧固孔。"""
    p = params or TitaniumInsertParams()
    blades: list[TitaniumBlade] = []
    thin_count = 0

    # 1. 检查各开孔间距
    valid_polys = [poly for poly in solder_polys if poly and not poly.is_empty]
    for i in range(len(valid_polys)):
        for j in range(i + 1, len(valid_polys)):
            p1, p2 = valid_polys[i], valid_polys[j]
            dist = p1.distance(p2)
            if 0.1 <= dist <= p.knife_edge_threshold_mm:
                thin_count += 1
                # 生成嵌件刀片
                bx0, by0, bx1, by1 = p1.bounds
                ox0, oy0, ox1, oy1 = p2.bounds
                # 判断是水平相邻还是垂直相邻
                mid_x = (max(bx0, ox0) + min(bx1, ox1)) / 2.0
                mid_y = (max(by0, oy0) + min(by1, oy1)) / 2.0
                is_horiz = abs(bx0 - ox0) < abs(by0 - oy0)

                length = max(15.0, (bx1 - bx0) if is_horiz else (by1 - by0))
                half_l = length / 2.0

                if is_horiz:
                    b_box = box(mid_x - half_l, mid_y - p.blade_thickness_mm / 2,
                                mid_x + half_l, mid_y + p.blade_thickness_mm / 2)
                    screws = [(round(mid_x - half_l / 2, 2), round(mid_y, 2)),
                              (round(mid_x + half_l / 2, 2), round(mid_y, 2))]
                    ori = "horizontal"
                else:
                    b_box = box(mid_x - p.blade_thickness_mm / 2, mid_y - half_l,
                                mid_x + p.blade_thickness_mm / 2, mid_y + half_l)
                    screws = [(round(mid_x, 2), round(mid_y - half_l / 2, 2)),
                              (round(mid_x, 2), round(mid_y + half_l / 2, 2))]
                    ori = "vertical"

                blades.append(
                    TitaniumBlade(
                        blade_id=f"TI_BLADE_{thin_count}",
                        center_x_mm=round(mid_x, 2),
                        center_y_mm=round(mid_y, 2),
                        length_mm=round(length, 1),
                        thickness_mm=p.blade_thickness_mm,
                        orientation=ori,
                        screw_holes=screws,
                        boundary_poly=b_box,
                    )
                )

    # 2. 计算最大上锡开孔行程的浸润时间
    max_len_x = 0.0
    for poly in valid_polys:
        bx0, _, bx1, _ = poly.bounds
        max_len_x = max(max_len_x, bx1 - bx0)

    dwell_win = calculate_wave_dwell_window(max_len_x, conveyor_speed_m_per_min=p.conveyor_speed_m_per_min) if max_len_x > 0 else None

    stats = {
        "thin_walls_detected": thin_count,
        "titanium_blades_planned": len(blades),
        "blade_thickness_mm": p.blade_thickness_mm,
        "screw_hole_dia_mm": p.fixing_screw_hole_dia_mm,
    }

    return TitaniumInsertsResult(
        thin_walls_detected=thin_count,
        blades=blades,
        dwell_window=dwell_win,
        stats=stats,
    )


def export_titanium_inserts_to_dxf(msp, result: TitaniumInsertsResult) -> None:
    """输出钛合金耐磨隔锡刀片嵌件与 M2 螺丝孔到 DXF 专用图层。"""
    layer_name = "钛合金嵌件"

    for b in result.blades:
        # 1. 钛合金刀片外形
        if b.boundary_poly and not b.boundary_poly.is_empty:
            pts = list(b.boundary_poly.exterior.coords)
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})

        # 2. M2 沉头固定螺丝孔 (Φ2.2mm)
        for sx, sy in b.screw_holes:
            msp.add_circle((sx, sy), radius=1.1, dxfattribs={"layer": layer_name})

        # 3. 工程注记
        msp.add_text(
            f"TITANIUM BLADE ({b.blade_id}, t={b.thickness_mm}mm)",
            dxfattribs={"layer": layer_name, "height": 2.0, "insert": (b.center_x_mm + 2.0, b.center_y_mm + 2.0)},
        )
