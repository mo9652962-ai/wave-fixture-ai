"""CAM 热膨胀各向异性补偿缩放引擎 (CAM Thermal Expansion Anisotropic Scaling Engine).

工业背景与物理建模：
- Macaos Solder Pallet Designer & Röchling Durostone CAM 指南：
  当波峰焊治具沉板跨度大 (>= 150mm ~ 200mm) 时，在常温 (20°C) 下加工出的沉板槽，
  进入 260°C 液态锡波峰时，由于合成石与 PCB 的线膨胀系数差 (ΔCTE = CTE_pallet − CTE_pcb)：
      k_x = 1.0 + (CTE_pallet_x − CTE_pcb_x) × 1e-6 × ΔT
      k_y = 1.0 + (CTE_pallet_y − CTE_pcb_y) × 1e-6 × ΔT
  治具底座发生微米级热膨胀。高端 CAM 系统的标准解法不是人工去猜偏移量，
  而是在 CAM 导出与 CNC 刀路生成阶段直接施加**各向异性热补偿缩放系数 (Thermal Scale Factor)**：
  - Durostone (CTE=22 ppm/K) vs FR-4 (CTE=15 ppm/K), ΔT=235K:
    ΔCTE = 7 ppm/K → k = 1 + 7e-6 × 235 = 1.001645 (即千分之 1.65 缩放量)。
  - 对 200mm 沉板槽应用 1.00165 缩放后，常温下加工尺寸为 200.33mm，
    高温 260°C 下治具膨胀与 PCB 膨胀后两者的间隙恰好精准吻合标称设计值 0.15mm，
    从源头上消除高温顶死拱起与冷却卡板风险！
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from shapely.affinity import scale
from shapely.geometry import Polygon

from thermal_expansion import CTE_PPM_K, PCB_FR4_CTE_PPM_K, WAVE_DELTA_T_C


@dataclass
class ThermalScalingResult:
    material_key: str
    pallet_cte_ppm_k: float
    pcb_cte_ppm_k: float
    delta_t_c: float
    scale_factor_x: float
    scale_factor_y: float
    nominal_span_x_mm: float
    nominal_span_y_mm: float
    scaled_span_x_mm: float
    scaled_span_y_mm: float
    hot_state_compensation_um_x: float
    hot_state_compensation_um_y: float
    is_scaling_recommended: bool
    ipc_standard: str = "Macaos CAM Thermal Scaling Model & Röchling Durostone Guidelines"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calculate_thermal_expansion_scaling(
    span_x_mm: float,
    span_y_mm: float,
    material_key: str = "durostone",
    pcb_cte_ppm_k: float = PCB_FR4_CTE_PPM_K,
    delta_t_c: float = WAVE_DELTA_T_C,
) -> ThermalScalingResult:
    """计算 CAM 各向异性热膨胀缩放系数 (k_x, k_y)。"""
    mat_cte = CTE_PPM_K.get(material_key, CTE_PPM_K["durostone"])
    diff_cte = mat_cte - pcb_cte_ppm_k

    # 缩放系数 k = 1 + ΔCTE * ΔT
    k_val = 1.0 + (diff_cte * 1e-6 * delta_t_c)
    k_x = round(k_val, 6)
    k_y = round(k_val, 6)

    scaled_x = round(span_x_mm * k_x, 3)
    scaled_y = round(span_y_mm * k_y, 3)

    comp_x_um = round((scaled_x - span_x_mm) * 1000.0, 1)
    comp_y_um = round((scaled_y - span_y_mm) * 1000.0, 1)

    # 跨度 >= 150mm 且补偿量 >= 150μm 时强烈建议启用 CAM 缩放
    rec = max(span_x_mm, span_y_mm) >= 150.0 and max(comp_x_um, comp_y_um) >= 150.0

    return ThermalScalingResult(
        material_key=material_key,
        pallet_cte_ppm_k=mat_cte,
        pcb_cte_ppm_k=pcb_cte_ppm_k,
        delta_t_c=delta_t_c,
        scale_factor_x=k_x,
        scale_factor_y=k_y,
        nominal_span_x_mm=round(span_x_mm, 2),
        nominal_span_y_mm=round(span_y_mm, 2),
        scaled_span_x_mm=scaled_x,
        scaled_span_y_mm=scaled_y,
        hot_state_compensation_um_x=comp_x_um,
        hot_state_compensation_um_y=comp_y_um,
        is_scaling_recommended=rec,
    )


def apply_thermal_scaling_to_polygon(
    poly: Polygon,
    scale_factor_x: float,
    scale_factor_y: float,
) -> Polygon:
    """以几何中心为原点，对沉板或避位多边形施加热补偿各向异性缩放。"""
    if poly is None or poly.is_empty:
        return poly
    c = poly.centroid
    scaled_p = scale(poly, xfact=scale_factor_x, yfact=scale_factor_y, origin=(c.x, c.y))
    return scaled_p if scaled_p.is_valid else poly
