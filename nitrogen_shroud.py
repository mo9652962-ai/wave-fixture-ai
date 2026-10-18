"""波峰焊治具氮气保护微环境导流罩 (Nitrogen Inerting Blanket Shroud) 规划引擎。

工业权威依据：
- SMTA Wave Soldering Handbook & Ersa PowerFlow / SEHO MWS 2300 氮气波峰焊技术规范：
  在现代化高品质无铅波峰焊接工艺中，引入高纯度氮气 (N₂，纯度 99.999%，残氧量 O₂ < 500 ppm，
  严苛军工/汽车级要求 O₂ < 100 ppm) 可显著降低熔融 SAC305 焊料的表面张力，使通孔焊点垂直爬锡高度提升 30%~50%，
  并将锡渣产生量大幅削减 85%~90%，从根源上杜绝拉尖、连锡桥连与微细空洞缺陷。
- 托盘微环境密闭气帘设计 (Pallet Nitrogen Shroud / Skirt Cavity)：
  对于通过氮气隧道炉或局部氮气刀喷嘴的工装治具，治具底面各上锡开孔外围需开设 2.5~3.5mm 深度的
  环形氮气汇集气罩 (Nitrogen Blanket Shroud)，配合微孔均流缝，在熔锡接触区形成稳定的富氮正压微气室，
  防止传送带扰流将外部氧气卷入锡波接触面。
  气罩外边缘与导轨、治具边框保持 ≥ 5.0mm 密封间隙，防止氮气无序逸散浪费气源。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

log = logging.getLogger("nitrogen-shroud")


@dataclass
class NitrogenShroudParams:
    """氮气保护罩与微气室规划参数。"""

    enabled: bool = True
    shroud_depth_mm: float = 3.0  # 氮气汇集沉槽深度 (mm, 2.5~3.5mm)
    shroud_expansion_mm: float = 8.0  # 上锡开孔群组向外扩展气罩余量 (mm)
    min_seal_land_mm: float = 5.0  # 气罩距治具边框与导轨的最小密封陆地宽度 (mm)
    diffuser_slot_width_mm: float = 2.0  # 均流防憋气排气微槽宽度 (mm)
    target_residual_o2_ppm: float = 500.0  # 目标残氧量 (ppm)


@dataclass
class NitrogenShroudResult:
    """氮气气罩多边形轮廓、密封状态与耗气评估结果。"""

    shroud_polys: list[Polygon] = field(default_factory=list)
    shroud_area_mm2: float = 0.0
    shroud_depth_mm: float = 3.0
    min_seal_clearance_mm: float = 999.0
    is_seal_compliant: bool = True
    target_residual_o2_ppm: float = 500.0
    diffuser_slots: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )
    compliance_standard: str = "SMTA Wave Soldering Handbook & Ersa PowerFlow N2 Guidelines"

    def to_dict(self) -> dict[str, Any]:
        return {
            "shroud_count": len(self.shroud_polys),
            "shroud_area_mm2": round(self.shroud_area_mm2, 2),
            "shroud_depth_mm": self.shroud_depth_mm,
            "min_seal_clearance_mm": (
                round(self.min_seal_clearance_mm, 2)
                if self.min_seal_clearance_mm < 900.0
                else None
            ),
            "is_seal_compliant": self.is_seal_compliant,
            "target_residual_o2_ppm": self.target_residual_o2_ppm,
            "compliance_standard": self.compliance_standard,
        }


def generate_nitrogen_shroud(
    solder_polys: list[Polygon] | None,
    outer_poly: Polygon | None,
    params: NitrogenShroudParams | None = None,
) -> NitrogenShroudResult:
    """根据上锡开孔区域外扩生成氮气保护汇集气罩并核算边框密封间隙。

    Args:
        solder_polys: 上锡开孔多边形列表
        outer_poly: 治具外形边界多边形
        params: 氮气气罩规划参数

    Returns:
        NitrogenShroudResult: 气罩几何多边形、均流缝与密封合规评估
    """
    if params is None:
        params = NitrogenShroudParams()

    if (
        not params.enabled
        or not solder_polys
        or outer_poly is None
        or outer_poly.is_empty
    ):
        return NitrogenShroudResult()

    valid_solders = [p for p in solder_polys if p is not None and not p.is_empty]
    if not valid_solders:
        return NitrogenShroudResult()

    # 将上锡开孔群联合并并向外扩展形成氮气气室
    merged_solder = unary_union(valid_solders)
    raw_shroud = merged_solder.buffer(params.shroud_expansion_mm, join_style="round")

    # 限制气室必须在治具外形内缩 min_seal_land_mm 内部，保证周边气密
    safe_zone = outer_poly.buffer(-params.min_seal_land_mm)
    clipped_shroud = raw_shroud.intersection(safe_zone)

    if clipped_shroud.is_empty:
        return NitrogenShroudResult()

    polys: list[Polygon] = []
    if clipped_shroud.geom_type == "Polygon":
        polys.append(clipped_shroud)
    elif clipped_shroud.geom_type == "MultiPolygon":
        polys.extend(clipped_shroud.geoms)

    total_area = sum(p.area for p in polys)

    # 计算气罩与治具外形边缘的最小密封边距
    min_clr = 999.0
    for p in polys:
        dist = outer_poly.boundary.distance(p)
        min_clr = min(min_clr, dist)

    is_compliant = min_clr >= params.min_seal_land_mm - 1e-4

    # 生成均流排气微槽 (前缘至尾缘均压通道)
    diffuser_slots: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for p in polys:
        minx, miny, maxx, maxy = p.bounds
        cx = (minx + maxx) / 2.0
        # 纵向微槽：从槽底到槽顶
        diffuser_slots.append(((cx, miny), (cx, maxy)))

    return NitrogenShroudResult(
        shroud_polys=polys,
        shroud_area_mm2=total_area,
        shroud_depth_mm=params.shroud_depth_mm,
        min_seal_clearance_mm=min_clr,
        is_seal_compliant=is_compliant,
        target_residual_o2_ppm=params.target_residual_o2_ppm,
        diffuser_slots=diffuser_slots,
        compliance_standard="SMTA Wave Soldering Handbook & Ersa PowerFlow N2 Guidelines",
    )


def export_nitrogen_shroud_to_dxf(msp, result: NitrogenShroudResult) -> None:
    """输出氮气保护气罩外框与均流槽至 DXF 专用图层。"""
    layer_name = "氮气保护"

    for poly in result.shroud_polys:
        if poly and not poly.is_empty:
            pts = list(poly.exterior.coords)
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})

    for p1, p2 in result.diffuser_slots:
        msp.add_line(p1, p2, dxfattribs={"layer": layer_name, "linetype": "DASHED"})

    if result.shroud_polys:
        b = result.shroud_polys[0].bounds
        msp.add_text(
            f"N2-SHROUD ({result.shroud_depth_mm:g}mm DP / <{result.target_residual_o2_ppm:.0f}ppm O2)",
            dxfattribs={"layer": layer_name, "height": 3.0},
        ).set_placement((b[0], b[1] - 4.0))
