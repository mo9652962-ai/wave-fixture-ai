"""波峰焊治具人机工程学重量与安全抓握门禁 (Ergonomic Handling & Weight Limit) 引擎。

工业权威依据：
- ISO 11228-1 (Ergonomics - Manual handling - Part 1: Lifting and carrying):
  在电子制造 SMT/THT 波峰焊车间中，操作工每班次需进行上百次治具的手工上下板与搬运循环（每 30~90 秒一次）。
  ISO 11228-1 与中国国家标准 GB/T 18079 明确界定高频重复性双手动工安全限值：
    * 推荐安全总重 ≤ 5.0 kg (11.0 lbs)：男女操作工均可单人轻松安全搬运。
    * 警戒区间 5.0 kg ~ 8.0 kg：强制要求在治具双侧开设人机工程学舒适握持把手
      （把手开孔宽度 ≥ 100mm，高度 ≥ 35mm，内角倒圆角 R8），分散掌心压强并预防滑脱。
    * 严禁单人搬运 > 8.0 kg (17.6 lbs)：超出 OSHA / ISO 单人安全极限，必须使用机械吊臂助力或双人抬运。
- AGICORP §2.4 (Pallet Handling & Weight Limitations for Electronic Assembly):
  治具总重量包含：合成石基体、沉板挖空后净余质量、PCB 装配体质量、铰链式防翘曲上盖 (Top Hat)、
  边缘旋转压扣、加强横梁以及导轨耐磨金属配件。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon, box

log = logging.getLogger("ergonomic-handling")

# 常用治具材质密度 (g/cm³)
MATERIAL_DENSITIES_G_CM3: dict[str, float] = {
    "durostone": 1.95,  # Durostone CFR 767 / CAS 761
    "ricocel": 1.85,  # Ricocel ES-3261A
    "fr4": 1.90,  # 环氧玻纤板
    "aluminum": 2.70,  # 6061-T6 铝合金
    "titanium": 4.51,  # Grade 2 纯钛
}


@dataclass
class ErgonomicHandlingParams:
    """人机工程学质量与把手规划参数。"""

    enabled: bool = True
    pallet_thickness_mm: float = 12.0  # 治具基板厚度 (mm)
    material_key: str = "durostone"  # 基材密度标识
    pcb_estimated_mass_kg: float = 0.35  # PCB 与插装器件估算质量 (kg)
    handle_width_mm: float = 105.0  # 舒适抓握开孔宽度 (mm, ISO 11228-1: >=100mm)
    handle_height_mm: float = 38.0  # 握持开孔高度 (mm, >=35mm)
    handle_fillet_r_mm: float = 8.0  # 握持内角圆角 (mm, R8 防硌手)
    max_safe_single_operator_kg: float = 5.0  # 连续手工搬运安全上限 (5.0 kg)
    max_absolute_single_operator_kg: float = 8.0  # 单人极限重量 (8.0 kg)


@dataclass
class ErgonomicHandlingResult:
    """质量核算、人机工程评估与舒适握手开孔结果。"""

    pallet_base_mass_kg: float = 0.0
    hardware_mass_kg: float = 0.0
    pcb_mass_kg: float = 0.0
    total_mass_kg: float = 0.0
    is_within_safe_weight: bool = True
    requires_ergonomic_handles: bool = False
    exceeds_manual_limit: bool = False
    handles_provided: bool = False
    handle_polys: list[Polygon] = field(default_factory=list)
    compliance_standard: str = "ISO 11228-1 & OSHA Section VII Repetitive Lifting Standards"
    mass_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pallet_base_mass_kg": round(self.pallet_base_mass_kg, 2),
            "hardware_mass_kg": round(self.hardware_mass_kg, 2),
            "pcb_mass_kg": round(self.pcb_mass_kg, 2),
            "total_mass_kg": round(self.total_mass_kg, 2),
            "is_within_safe_weight": self.is_within_safe_weight,
            "requires_ergonomic_handles": self.requires_ergonomic_handles,
            "exceeds_manual_limit": self.exceeds_manual_limit,
            "handles_provided": self.handles_provided,
            "handle_count": len(self.handle_polys),
            "compliance_standard": self.compliance_standard,
            "mass_breakdown": {k: round(v, 3) for k, v in self.mass_breakdown.items()},
        }


def evaluate_ergonomic_handling(
    outer_poly: Polygon | None,
    sink_poly: Polygon | None = None,
    params: ErgonomicHandlingParams | None = None,
    top_hat_enabled: bool = False,
    clamp_count: int = 0,
    stiffener_enabled: bool = False,
    wear_rail_count: int = 0,
) -> ErgonomicHandlingResult:
    """评估治具整备质量，核算是否符合 ISO 11228-1 单人搬运工效学，必要时规划舒适把手。

    Args:
        outer_poly: 治具外形边界多边形
        sink_poly: 沉板区多边形
        params: 工效学参数
        top_hat_enabled: 是否安装铰链防翘曲上盖
        clamp_count: 旋转压扣数量
        stiffener_enabled: 是否安装防下垂加强梁
        wear_rail_count: 耐磨导轨条数量

    Returns:
        ErgonomicHandlingResult: 质量分解、合规性及舒适握手多边形
    """
    if params is None:
        params = ErgonomicHandlingParams()

    if not params.enabled or outer_poly is None or outer_poly.is_empty:
        return ErgonomicHandlingResult()

    density_g_cm3 = MATERIAL_DENSITIES_G_CM3.get(
        params.material_key.lower(), 1.95
    )
    density_kg_mm3 = density_g_cm3 * 1.0e-6

    # 1. 基体体积与净余基材质量计算
    outer_area = outer_poly.area
    sink_area = sink_poly.area if sink_poly and not sink_poly.is_empty else 0.0

    # 沉板深度约占板厚的 50%~60% (默认按 6.0mm 挖深)
    sink_depth = min(6.0, params.pallet_thickness_mm * 0.5)
    base_volume_mm3 = (outer_area * params.pallet_thickness_mm) - (
        sink_area * sink_depth
    )
    pallet_base_mass = max(0.1, base_volume_mm3 * density_kg_mm3)

    # 2. 附加五金与装配体质量
    hw_top_hat = 0.95 if top_hat_enabled else 0.0  # 上盖铝合金/合成石质量
    hw_clamps = clamp_count * 0.035  # 每个压扣五金约 35g
    hw_stiffener = 0.28 if stiffener_enabled else 0.0  # 加强筋五金
    hw_wear_rails = wear_rail_count * 0.12  # 耐磨导轨条
    total_hw_mass = hw_top_hat + hw_clamps + hw_stiffener + hw_wear_rails

    pcb_mass = max(0.05, params.pcb_estimated_mass_kg)
    total_mass = pallet_base_mass + total_hw_mass + pcb_mass

    safe = total_mass <= params.max_safe_single_operator_kg
    needs_handles = total_mass > params.max_safe_single_operator_kg
    exceeds_limit = total_mass > params.max_absolute_single_operator_kg

    # 3. 规划人机工程舒适手柄 (两端对称开孔)
    handle_polys: list[Polygon] = []
    minx, miny, maxx, maxy = outer_poly.bounds
    w = maxx - minx

    hw = params.handle_width_mm
    hh = params.handle_height_mm
    fr = params.handle_fillet_r_mm

    # 左右两侧把手位 (位于外形左右外框外扩区)
    if w >= hw + 40.0:
        cy = (miny + maxy) / 2.0
        # 左把手
        left_box = box(minx + 8.0, cy - hh / 2.0, minx + 8.0 + hw, cy + hh / 2.0)
        # R8 倒圆角
        left_filleted = left_box.buffer(fr, join_style="round").buffer(-fr, join_style="round")
        handle_polys.append(left_filleted)

        # 右把手
        right_box = box(maxx - 8.0 - hw, cy - hh / 2.0, maxx - 8.0, cy + hh / 2.0)
        right_filleted = right_box.buffer(fr, join_style="round").buffer(-fr, join_style="round")
        handle_polys.append(right_filleted)

    mass_bd = {
        "pallet_composite_body": pallet_base_mass,
        "pcb_and_components": pcb_mass,
        "top_hat_cover": hw_top_hat,
        "hold_down_clamps": hw_clamps,
        "stiffener_bars": hw_stiffener,
        "conveyor_wear_rails": hw_wear_rails,
    }

    return ErgonomicHandlingResult(
        pallet_base_mass_kg=pallet_base_mass,
        hardware_mass_kg=total_hw_mass,
        pcb_mass_kg=pcb_mass,
        total_mass_kg=total_mass,
        is_within_safe_weight=safe,
        requires_ergonomic_handles=needs_handles,
        exceeds_manual_limit=exceeds_limit,
        handles_provided=len(handle_polys) >= 2,
        handle_polys=handle_polys,
        compliance_standard="ISO 11228-1 & OSHA Section VII Repetitive Lifting Standards",
        mass_breakdown=mass_bd,
    )


def export_ergonomic_handling_to_dxf(
    msp, result: ErgonomicHandlingResult
) -> None:
    """输出人机工程舒适手柄握孔多边形至 DXF 专用图层。"""
    layer_name = "人机工程手柄"

    for poly in result.handle_polys:
        if poly and not poly.is_empty:
            pts = list(poly.exterior.coords)
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})

    if result.handle_polys:
        for p in result.handle_polys:
            b = p.bounds
            msp.add_text(
                f"HAND-GRIP (M={result.total_mass_kg:.1f}kg)",
                dxfattribs={"layer": layer_name, "height": 3.0},
            ).set_placement((b[0] + 5.0, (b[1] + b[3]) / 2.0 - 1.5))
