"""波峰焊薄板与大跨度 PCB 二次回流防热塌陷托块 (Thermal Sag Support Pillars) 引擎。

工业权威依据：
- SMTA Wave Soldering Handbook & Kurtz Ersa / SEHO 载具设计规范：
  当印制板厚度较薄 (t <= 1.2mm) 或板面跨距较大 (跨度 >= 160mm) 时，PCB 在浸入 260°C 液态锡流过程中，
  基板温度瞬间超越环氧树脂玻璃化转变温度 (Tg 130°C~170°C)。FR-4 弹性模量在热态下急剧跌落 80% 以上，
  在板载重型元器件 (电源变压器、共模电感、大电解电容) 重力及液面动压作用下发生严重的热塌陷与中央下垂
  (最大挠度下垂量往往 > 1.5mm)。中央下垂会导致波峰锡液漫过板面正面造成大面积连锡短路，或局部脱焊漏焊。
- 中跨防下垂支承立柱规范 (Anti-Sag Support Posts / Pillars)：
  工业级防塌陷标准：在沉板区中央开阔无焊盘安全禁布区 (距通孔焊盘与走线边缘保持 >= 2.0mm 绝缘距离)，
  规划 Φ5.0mm ~ Φ8.0mm 的合成石支承托块 (Support Pillars) 或耐高温特氟龙弹性支承柱，
  将大跨度板卡最大自由挠曲跨距缩短 50% 以上，严格将高温过炉动态挠度控制在 <= 0.50mm 以内 (IPC-A-610G)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Point, Polygon

log = logging.getLogger("thermal-sag-support")


@dataclass
class ThermalSagSupportParams:
    """防热塌陷托块规划参数。"""

    enabled: bool = True
    trigger_span_mm: float = 160.0  # 触发支承托块规划的最小跨距 (mm)
    trigger_thin_thickness_mm: float = 1.2  # 触发薄板刚度补强的厚度上限 (mm)
    pillar_diameter_mm: float = 6.0  # 支承托块外径 (mm, 5.0~8.0mm)
    min_clearance_to_solder_mm: float = 2.5  # 托块边缘距上锡开孔最小安全绝缘净距 (mm)
    min_clearance_to_avoid_mm: float = 2.0  # 托块边缘距底面避位贴片元件的间隙 (mm)
    target_max_sag_deflection_mm: float = 0.50  # 允许的最大受热塌陷挠度 (mm)


@dataclass
class SagPillar:
    """单个中跨防热塌陷支承立柱物理坐标与属性。"""

    pillar_id: str
    x: float
    y: float
    diameter_mm: float
    poly: Polygon


@dataclass
class ThermalSagSupportResult:
    """防热塌陷托块整体规划与高温挠度校核结果。"""

    pillars: list[SagPillar] = field(default_factory=list)
    total_pillar_count: int = 0
    estimated_unsupported_span_mm: float = 0.0
    estimated_thermal_sag_mm: float = 0.0
    is_sag_deflection_acceptable: bool = True
    compliance_standard: str = "SMTA Wave Soldering Handbook & Ersa Anti-Sag Guidelines"

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_pillar_count": self.total_pillar_count,
            "estimated_unsupported_span_mm": round(self.estimated_unsupported_span_mm, 1),
            "estimated_thermal_sag_mm": round(self.estimated_thermal_sag_mm, 2),
            "is_sag_deflection_acceptable": self.is_sag_deflection_acceptable,
            "compliance_standard": self.compliance_standard,
            "pillars": [
                {
                    "pillar_id": p.pillar_id,
                    "x": round(p.x, 2),
                    "y": round(p.y, 2),
                    "diameter_mm": p.diameter_mm,
                }
                for p in self.pillars
            ],
        }


def plan_thermal_sag_supports(
    sink_poly: Polygon | None,
    solder_polys: list[Polygon] | None = None,
    avoid_polys: list[Polygon] | None = None,
    pcb_thickness_mm: float = 1.6,
    params: ThermalSagSupportParams | None = None,
) -> ThermalSagSupportResult:
    """分析板面跨距与热态刚度，在大跨度或薄板中央开阔区规划防塌陷支承托块。

    Args:
        sink_poly: 沉板区几何多边形
        solder_polys: 上锡开孔列表 (托块必须远离上锡开孔以防阻挡液态锡浸润)
        avoid_polys: 底面贴片避位开孔列表 (托块严禁压到贴片阻容)
        pcb_thickness_mm: PCB 板厚 (mm)
        params: 防热塌参数配置

    Returns:
        ThermalSagSupportResult: 托块坐标、估算受热挠度与合规评估
    """
    if params is None:
        params = ThermalSagSupportParams()

    if not params.enabled or sink_poly is None or sink_poly.is_empty:
        return ThermalSagSupportResult()

    minx, miny, maxx, maxy = sink_poly.bounds
    w = maxx - minx
    h = maxy - miny
    max_span = max(w, h)

    # 简化的热态板挠度梁模型: delta ≈ (5 * q * L^4) / (384 * E_hot * I)
    # FR-4 在 260°C 下 E_hot 较常温降至约 2.5 GPa
    e_ratio = 1.0 if pcb_thickness_mm >= 1.6 else (1.6 / max(0.6, pcb_thickness_mm)) ** 3
    raw_sag_mm = 0.08 * ((max_span / 100.0) ** 3) * e_ratio

    pillars: list[SagPillar] = []
    r_pillar = params.pillar_diameter_mm / 2.0

    needs_support = (max_span >= params.trigger_span_mm) or (pcb_thickness_mm <= params.trigger_thin_thickness_mm)

    if needs_support:
        # 在中央 1/3 ~ 2/3 区域寻找落脚点
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0

        candidate_points = [
            (cx, cy),
            (cx - w * 0.2, cy),
            (cx + w * 0.2, cy),
            (cx, cy - h * 0.2),
            (cx, cy + h * 0.2),
        ]

        valid_solders = [p for p in (solder_polys or []) if p and not p.is_empty]
        valid_avoids = [p for p in (avoid_polys or []) if p and not p.is_empty]

        p_idx = 1
        for px, py in candidate_points:
            pt = Point(px, py)
            pillar_circle = pt.buffer(r_pillar)

            # 1. 必须在沉板区内
            if not sink_poly.contains(pt):
                continue

            # 2. 距上锡区必须保持安全绝缘间隙
            clash_solder = any(
                s.intersects(pillar_circle.buffer(params.min_clearance_to_solder_mm))
                for s in valid_solders
            )
            if clash_solder:
                continue

            # 3. 距避位贴片区保持间隙
            clash_avoid = any(
                a.intersects(pillar_circle.buffer(params.min_clearance_to_avoid_mm))
                for a in valid_avoids
            )
            if clash_avoid:
                continue

            pillars.append(
                SagPillar(
                    pillar_id=f"SAG_PIL_{p_idx}",
                    x=px,
                    y=py,
                    diameter_mm=params.pillar_diameter_mm,
                    poly=pillar_circle,
                )
            )
            p_idx += 1
            if len(pillars) >= 3:
                break

    # 若安装了支撑托块，跨距减半，挠度按 L^3 缩减至原来的 1/8
    final_sag = raw_sag_mm * (0.25 if len(pillars) > 0 else 1.0)
    is_acceptable = final_sag <= params.target_max_sag_deflection_mm

    return ThermalSagSupportResult(
        pillars=pillars,
        total_pillar_count=len(pillars),
        estimated_unsupported_span_mm=max_span if len(pillars) == 0 else max_span / 2.0,
        estimated_thermal_sag_mm=final_sag,
        is_sag_deflection_acceptable=is_acceptable,
        compliance_standard="SMTA Wave Soldering Handbook & Ersa Anti-Sag Guidelines",
    )


def export_thermal_sag_supports_to_dxf(
    msp, result: ThermalSagSupportResult
) -> None:
    """输出防热塌支承托块圆孔与安全标识至 DXF 专用图层。"""
    layer_name = "防热塌托块"

    for p in result.pillars:
        r = p.diameter_mm / 2.0
        # 支承托块外径轮廓
        msp.add_circle((p.x, p.y), radius=r, dxfattribs={"layer": layer_name})
        # 中心十字标记
        msp.add_line((p.x - r, p.y), (p.x + r, p.y), dxfattribs={"layer": layer_name})
        msp.add_line((p.x, p.y - r), (p.x, p.y + r), dxfattribs={"layer": layer_name})

    if result.pillars:
        p0 = result.pillars[0]
        msp.add_text(
            f"SAG-PILLAR (SAG<={result.estimated_thermal_sag_mm:.2f}mm)",
            dxfattribs={"layer": layer_name, "height": 2.5},
        ).set_placement((p0.x + 4.0, p0.y - 1.25))
