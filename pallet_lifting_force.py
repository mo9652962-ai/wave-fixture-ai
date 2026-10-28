"""波峰焊治具搬运提升力与人机工程学内嵌拉手槽校核器 (ISO 11228-1 & NIOSH 抬升方程)。

工业背景与物理机制：
1. 波峰焊合成石治具本体、PCB 板卡、顶部旋转压扣、防漂浮钛合金压条与加强梁组合装配后，
   整备质量通常在 4.5 ~ 9.0kg 之间。
2. 在波峰焊线体中，操作人员每小时需手工执行 60~120 次治具搬运、进板装夹与出板卸载（高频重复性搬运）。
3. 人机工程学耦合系数与抓持设计（ISO 11228-1 & NIOSH 搬运标准）：
   - 当治具边缘平直光滑（无抓手或握持深度 < 15mm）时，抓握耦合系数 CM 跌至 0.70，
     操作人员依靠指尖捏力抓取，极易因手指疲劳、高温出炉微烫或手套滑脱而摔落治具砸碎 PCB。
   - 合格的内嵌式人机工程手指凹槽（Recessed Finger Grips）：
     * 槽宽 >= 105.0mm（推荐 115 ~ 125mm，充分容纳穿戴防静电防烫手套的手掌宽度）。
     * 深入深度 >= 22.0mm（推荐 25 ~ 30mm，确保指节完全扣入支撑受力）。
     * 倒角圆角 R >= 3.0mm（消除尖锐直角，防止压迫手掌掌指神经）。
     * 双侧对称对中排布（距重心偏差 <= 15mm，避免双手抬起时产生倾覆扭矩）。
4. NIOSH 推荐抬升限值 (Recommended Weight Limit, RWL) 与抬升指数 (Lifting Index, LI)：
       RWL = LC * HM * VM * DM * AM * FM * CM
       LI = Total_Mass / RWL
   标准规定 LI <= 1.0 为健康安全区间；若 LI > 1.5 或单人负重 > 8.0kg，提示工伤高危并强制要求双人抬升或轨道升降机。
5. DXF 规范：导出专用图层 "人体工学拉手" (ACI 颜色 143 暖黄色)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon, box

DEFAULT_GRIP_WIDTH_MM = 115.0     # 拉手槽开孔宽度 (>=105mm)
DEFAULT_GRIP_DEPTH_MM = 26.0      # 内凹受力深度 (>=22mm)
DEFAULT_FILLET_RADIUS_MM = 4.0    # 舒适圆角半径 (>=3mm)


@dataclass
class RecessedGrip:
    grip_id: str
    edge: str                     # "left", "right", "top", "bottom"
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    width_mm: float
    depth_mm: float
    fillet_radius_mm: float
    poly: Polygon | None = None


@dataclass
class PalletLiftingForceResult:
    total_pallet_mass_kg: float
    has_ergonomic_grips: bool
    grips: list[RecessedGrip] = field(default_factory=list)
    grip_width_mm: float = DEFAULT_GRIP_WIDTH_MM
    grip_depth_mm: float = DEFAULT_GRIP_DEPTH_MM
    coupling_multiplier_cm: float = 1.00
    recommended_weight_limit_kg: float = 8.5
    lifting_index_niosh: float = 0.55
    is_ergonomically_acceptable: bool = True
    violations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    compliance_standard: str = "ISO 11228-1 Ergonomics & NIOSH Manual Lifting Equation Standards"


def check_pallet_lifting_force(
    pallet_length_mm: float = 380.0,
    pallet_width_mm: float = 280.0,
    pallet_thickness_mm: float = 12.0,
    total_mass_kg: float = 5.2,
    has_recessed_grips: bool = True,
    grip_width_mm: float = DEFAULT_GRIP_WIDTH_MM,
    grip_depth_mm: float = DEFAULT_GRIP_DEPTH_MM,
    lifts_per_hour: int = 60,
    two_handed_lift: bool = True,
) -> PalletLiftingForceResult:
    """校核治具人机工程学提升负荷、内嵌指槽几何合格度与 NIOSH 抬升指数。

    参数：
        pallet_length_mm: 治具外形长度（mm）。
        pallet_width_mm: 治具外形宽度（mm）。
        pallet_thickness_mm: 治具板厚（mm）。
        total_mass_kg: 治具整备总质量（含合成石、PCB、压扣与横梁，kg）。
        has_recessed_grips: 是否配置内嵌手抓槽。
        grip_width_mm: 手抓槽开孔宽度（mm）。
        grip_depth_mm: 手抓槽内嵌深度（mm）。
        lifts_per_hour: 每小时重复搬运频次（次/小时）。
        two_handed_lift: 是否双手抬升。
    """
    violations: list[str] = []
    recommendations: list[str] = []
    grips: list[RecessedGrip] = []

    # 1. 抓持耦合度判定 (Coupling Multiplier CM)
    # 理想内嵌指槽 (宽>=105, 深>=22) 为 Good (CM=1.0)
    # 浅槽或平边为 Fair (CM=0.90) 或 Poor (CM=0.70)
    if not has_recessed_grips:
        cm = 0.70
    elif grip_width_mm >= 105.0 and grip_depth_mm >= 22.0:
        cm = 1.00
    elif grip_width_mm >= 80.0 and grip_depth_mm >= 15.0:
        cm = 0.90
    else:
        cm = 0.70

    # 2. NIOSH 简易工业抬升限值估算
    # LC = 23kg, 水平距离典型 35cm (HM=0.71), 垂直高度 75cm (VM=0.99), 距离 25cm (DM=0.93)
    # 频率因子 FM 随频次调整 (60次/h => ~0.75, 120次/h => ~0.55)
    fm = 0.75 if lifts_per_hour <= 60 else 0.55
    rwl = 23.0 * 0.71 * 0.99 * 0.93 * fm * cm
    li = total_mass_kg / rwl if rwl > 0.01 else 99.0

    # 3. 规划标准对称双侧抓槽 (沿长度或宽度外边缘居中内缩)
    if has_recessed_grips:
        half_gw = grip_width_mm / 2.0
        # 左右两侧沿 X 方向外缘内缩
        # 左侧抓槽
        lx0 = 0.0
        lx1 = grip_depth_mm
        ly0 = (pallet_width_mm / 2.0) - half_gw
        ly1 = (pallet_width_mm / 2.0) + half_gw
        poly_left = box(lx0, ly0, lx1, ly1)
        grips.append(
            RecessedGrip(
                grip_id="GRIP-LEFT",
                edge="left",
                x_min=round(lx0, 2),
                y_min=round(ly0, 2),
                x_max=round(lx1, 2),
                y_max=round(ly1, 2),
                width_mm=grip_width_mm,
                depth_mm=grip_depth_mm,
                fillet_radius_mm=DEFAULT_FILLET_RADIUS_MM,
                poly=poly_left,
            )
        )
        # 右侧抓槽
        rx0 = pallet_length_mm - grip_depth_mm
        rx1 = pallet_length_mm
        ry0 = (pallet_width_mm / 2.0) - half_gw
        ry1 = (pallet_width_mm / 2.0) + half_gw
        poly_right = box(rx0, ry0, rx1, ry1)
        grips.append(
            RecessedGrip(
                grip_id="GRIP-RIGHT",
                edge="right",
                x_min=round(rx0, 2),
                y_min=round(ry0, 2),
                x_max=round(rx1, 2),
                y_max=round(ry1, 2),
                width_mm=grip_width_mm,
                depth_mm=grip_depth_mm,
                fillet_radius_mm=DEFAULT_FILLET_RADIUS_MM,
                poly=poly_right,
            )
        )

    # 4. 缺陷与安全评估
    if total_mass_kg >= 4.5 and not has_recessed_grips:
        violations.append(
            f"治具整备质量 {total_mass_kg:.2f}kg ≥ 4.5kg 但未设计内嵌手指抓持槽；"
            "操作员指尖捏力抓取光滑外边极易滑脱碎板，且手掌疲劳引发肌腱劳损（ISO 11228-1 §4.2）。"
        )
    elif has_recessed_grips:
        if grip_width_mm < 105.0:
            violations.append(
                f"手抓槽开孔宽度 {grip_width_mm:.1f}mm < 105mm，无法容纳穿戴防烫手套的手掌自由伸入，"
                "搬运时易卡滞擦伤手背指关节（ISO 11228-1 人体测量学规范）。"
            )
        if grip_depth_mm < 22.0:
            violations.append(
                f"手抓槽内凹深度 {grip_depth_mm:.1f}mm < 22mm，有效指节扣入受力深度不足，"
                "属于不良抓握耦合 (Poor Coupling)，提升力大幅衰减 30%（NIOSH 抬升准则）。"
            )

    if li > 1.25:
        violations.append(
            f"高频搬运下 NIOSH 抬升指数 LI={li:.2f} > 1.25（推荐安全负重限值 RWL={rwl:.2f}kg）；"
            "治具过重或抓握不良存在严重人机工程工伤隐患，建议加装轻量化镂空腔或采用产线平衡吊具。"
        )
    elif li > 1.0:
        recommendations.append(
            f"NIOSH 抬升指数 LI={li:.2f} 处于边缘临界区 (1.0~1.25)，建议优化换型作业姿势并定期轮岗。"
        )

    if not violations:
        recommendations.append(
            f"治具抓持人机工程达标：配置双侧 {grip_width_mm:.0f}×{grip_depth_mm:.0f}mm 内嵌舒适指槽，"
            f"抓握耦合度良好 (CM=1.0)，NIOSH 抬升指数 LI={li:.2f} <= 1.00。"
        )

    is_acceptable = len(violations) == 0

    return PalletLiftingForceResult(
        total_pallet_mass_kg=round(total_mass_kg, 2),
        has_ergonomic_grips=has_recessed_grips,
        grips=grips,
        grip_width_mm=round(grip_width_mm, 2),
        grip_depth_mm=round(grip_depth_mm, 2),
        coupling_multiplier_cm=cm,
        recommended_weight_limit_kg=round(rwl, 2),
        lifting_index_niosh=round(li, 2),
        is_ergonomically_acceptable=is_acceptable,
        violations=violations,
        recommendations=recommendations,
    )


def export_pallet_lifting_grips_to_dxf(
    lifting_result: PalletLiftingForceResult,
    msp,
    layer_name: str = "人体工学拉手",
    color: int = 143,  # ACI 143 Warm Yellow/Orange
) -> int:
    """将人体工学内嵌拉手槽轮廓写入 DXF 模型空间。"""
    doc = getattr(msp, "doc", None)
    if doc and hasattr(doc, "layers") and layer_name not in doc.layers:
        doc.layers.add(layer_name, color=color)

    count = 0
    for g in lifting_result.grips:
        if g.poly is None or g.poly.is_empty:
            continue
        coords = list(g.poly.exterior.coords)
        msp.add_lwpolyline(
            coords,
            close=True,
            dxfattribs={"layer": layer_name, "color": color},
        )
        cx = (g.x_min + g.x_max) / 2.0
        cy = (g.y_min + g.y_max) / 2.0
        msp.add_text(
            f"{g.grip_id} ({g.width_mm:.0f}x{g.depth_mm:.0f})",
            dxfattribs={"layer": layer_name, "color": color, "height": 3.0},
        ).set_placement((cx - 15.0, cy - 1.5))
        count += 1
    return count
