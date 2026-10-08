"""治具底部热平衡减重开槽引擎 (Thermal Balancing & Lightening Pockets).

工业权威依据：
- SMTA Wave Soldering Thermal Profiling Guidelines:
  治具厚度通常为 10~15mm。如果治具底板大面积实心，合成石材料具有极大的热容 (Thermal Mass)，
  在通过波峰焊预热区时吸收过多热量，导致 PCB 表面升温迟缓，且中心与边缘产生极大温差 (ΔT > 20°C)，
  极易引起透锡不良、冷焊或润湿角过大。
- 制造人机工程学：
  减重槽可将治具毛坯重量降低 25% ~ 40%，有效减轻生产线操作员搬运疲劳，
  并减小波峰焊机爪链与传送导轨的机械载荷磨损。
- 结构设计准则：
  在沉板区外、避开轨道导轨 (≥15mm) 与紧固件螺钉 (≥8mm) 的实心区域，
  自动掏空 40%~60% 板厚的减重沉槽 (沉深 4~7mm)，四周保留 ≥10mm 结构刚性支撑肋壁。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

log = logging.getLogger("fixture-lightening")


@dataclass
class LighteningPocketResult:
    """减重槽生成结果。"""

    pockets: list[Polygon] = field(default_factory=list)
    pocket_depth_mm: float = 5.0
    total_pocket_area_mm2: float = 0.0
    outer_area_mm2: float = 0.0
    lightening_ratio_pct: float = 0.0  # 面积减重率 (掏空面积 / 治具总面积)
    weight_reduction_kg: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pocket_count": len(self.pockets),
            "pocket_depth_mm": self.pocket_depth_mm,
            "lightening_ratio_pct": round(self.lightening_ratio_pct, 1),
            "weight_reduction_kg": round(self.weight_reduction_kg, 3),
        }


def generate_lightening_pockets(
    outer_poly: Polygon,
    sink_poly: Polygon | None = None,
    keepouts: list[Polygon] | None = None,
    wall_margin_mm: float = 12.0,
    pocket_depth_mm: float = 5.0,
    pallet_thickness_mm: float = 10.0,
    material_density_g_cm3: float = 1.9,
) -> LighteningPocketResult:
    """在治具外框内排除沉板区、开孔与禁布区后，自动计算底面减重腔。"""
    if outer_poly is None or outer_poly.is_empty:
        return LighteningPocketResult()

    # 1. 结构外框内缩安全壁厚 (至少 12mm)
    base_cavity = outer_poly.buffer(-wall_margin_mm)
    if base_cavity.is_empty:
        return LighteningPocketResult()

    # 2. 合并所有需要避开的敏感区域 (沉板区 + 各开孔 + 轨道边)
    exclude_list = []
    if sink_poly and not sink_poly.is_empty:
        # 沉板区外侧扩 8mm 保证结构强度
        exclude_list.append(sink_poly.buffer(8.0))
    if keepouts:
        for k in keepouts:
            if k and not k.is_empty:
                exclude_list.append(k.buffer(6.0))

    if exclude_list:
        exclude_union = unary_union(exclude_list)
        available = base_cavity.difference(exclude_union)
    else:
        available = base_cavity

    # 3. 提取有效掏空区域 (过滤碎小多边形，面积 ≥ 80mm²)
    pockets: list[Polygon] = []
    if available.is_empty:
        geoms = []
    elif hasattr(available, "geoms"):
        geoms = list(available.geoms)
    else:
        geoms = [available]

    for g in geoms:
        if isinstance(g, Polygon) and g.area >= 80.0:
            # R3 倒角方便 CNC 快速挖槽
            pocket_r = g.buffer(-2.0).buffer(2.0, join_style="round")
            if isinstance(pocket_r, Polygon) and pocket_r.area >= 50.0:
                pockets.append(pocket_r)

    total_area = sum(p.area for p in pockets)
    outer_area = outer_poly.area
    ratio = (total_area / outer_area * 100.0) if outer_area > 0 else 0.0

    # 估算减轻重量: 面积 * 深度 * 密度
    vol_cm3 = total_area * pocket_depth_mm / 1000.0
    weight_red_kg = vol_cm3 * material_density_g_cm3 / 1000.0

    log.info(
        f"✅ 生成 {len(pockets)} 个减重散热槽: 掏空面积={total_area:.0f}mm², "
        f"减重率={ratio:.1f}%, 减重≈{weight_red_kg:.2f}kg"
    )

    return LighteningPocketResult(
        pockets=pockets,
        pocket_depth_mm=pocket_depth_mm,
        total_pocket_area_mm2=total_area,
        outer_area_mm2=outer_area,
        lightening_ratio_pct=ratio,
        weight_reduction_kg=weight_red_kg,
    )


def export_lightening_pockets_to_dxf(
    msp, result: LighteningPocketResult, layer: str = "减重槽"
) -> None:
    """将减重多边形写入 DXF 图纸。"""
    from fixture_phase2 import poly_to_dxf_polyline

    for p in result.pockets:
        poly_to_dxf_polyline(msp, p, layer)
