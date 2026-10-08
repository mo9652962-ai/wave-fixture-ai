"""大板跨度治具中支撑加强筋 (Center Support Stiffener Bar) 引擎。

工业权威依据：
- MB Manufacturing / AGICORP Wave Pallet Engineering Guidelines:
  合成石托盘在 260°C 熔融焊锡槽中连续受热且承受 PCB 自重，
  当治具跨距尺寸大于 250mm 时，托盘中心部位会产生 0.5mm~1.5mm 的重力热下垂 (Thermal Sagging)。
  下垂会导致中心焊点吃锡深度显著失控，引起溢锡短路。
- 行业解决方案：
  在治具中线跨距处安装特氟龙或高刚性阳极氧化铝合金加强梁 (Center Stiffener Bar)，
  跨过托盘并在两侧边框通过 M4 不锈钢沉头螺钉加固，有效控制下垂形变在 0.15mm 以内。
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon, box

log = logging.getLogger("fixture-stiffener")

SAG_THRESHOLD_SPAN_MM = 250.0  # 治具跨距下垂风险临界阈值 (mm)


@dataclass
class StiffenerBarParams:
    """加强横梁设计参数。"""

    enabled: bool = True
    span_threshold_mm: float = SAG_THRESHOLD_SPAN_MM  # 触发加强筋的最小跨距 (mm)
    bar_width_mm: float = 12.0  # 加强筋横梁宽度 (mm, 常用 12~15mm)
    bar_thickness_mm: float = 8.0  # 加强筋厚度 (mm)
    screw_hole_d: float = 4.2  # M4 固定沉孔直径 (mm)
    screw_margin_mm: float = 8.0  # 螺栓距边框边缘距离 (mm)
    material: str = "aluminum_6061"  # 加强筋材质 (高刚性铝合金 6061 / 钛合金)


@dataclass
class StiffenerResult:
    """加强横梁生成结果。"""

    needed: bool = False
    max_span_mm: float = 0.0
    bar_polys: list[Polygon] = field(default_factory=list)
    screw_holes: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y, r)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_stiffener_bars(
    outer_poly: Polygon,
    sink_poly: Polygon | None = None,
    params: StiffenerBarParams | None = None,
) -> StiffenerResult:
    """根据治具外框尺寸自动评估下垂风险并在大跨度中心布置加强筋与 M4 固定孔。"""
    p = params or StiffenerBarParams()
    if outer_poly is None or outer_poly.is_empty:
        return StiffenerResult()

    ox0, oy0, ox1, oy1 = outer_poly.bounds
    ow = ox1 - ox0
    oh = oy1 - oy0
    max_span = max(ow, oh)

    # 评估是否达到需要加强筋的跨距门槛
    if not p.enabled or max_span < p.span_threshold_mm:
        return StiffenerResult(
            needed=False,
            max_span_mm=round(max_span, 1),
            stats={"span_mm": round(max_span, 1), "needed": False},
        )

    bars: list[Polygon] = []
    screws: list[tuple[float, float, float]] = []
    screw_r = p.screw_hole_d / 2.0

    # 沿较长跨距的方向居中跨接加强横梁
    if ow >= oh:
        # 东西向大跨度 -> 南北中线布置竖直加强横梁
        mid_x = (ox0 + ox1) / 2.0
        bar = box(mid_x - p.bar_width_mm / 2.0, oy0, mid_x + p.bar_width_mm / 2.0, oy1)
        bars.append(bar)
        # 上下两端各打 1~2 颗 M4 固定沉孔
        screws.append((round(mid_x, 2), round(oy0 + p.screw_margin_mm, 2), screw_r))
        screws.append((round(mid_x, 2), round(oy1 - p.screw_margin_mm, 2), screw_r))
    else:
        # 南北向大跨度 -> 东西中线布置水平加强横梁
        mid_y = (oy0 + oy1) / 2.0
        bar = box(ox0, mid_y - p.bar_width_mm / 2.0, ox1, mid_y + p.bar_width_mm / 2.0)
        bars.append(bar)
        screws.append((round(ox0 + p.screw_margin_mm, 2), round(mid_y, 2), screw_r))
        screws.append((round(ox1 - p.screw_margin_mm, 2), round(mid_y, 2), screw_r))

    stats = {
        "span_mm": round(max_span, 1),
        "needed": True,
        "bar_count": len(bars),
        "screws_count": len(screws),
        "material": p.material,
        "note": f"跨距 {max_span:.0f}mm ≥ {p.span_threshold_mm:.0f}mm，已布置防下垂变形加强梁",
    }
    log.info(f"✅ 大板防下垂加强梁生成完成: 跨距={max_span:.0f}mm, 固定沉孔={len(screws)} 颗")

    return StiffenerResult(
        needed=True,
        max_span_mm=round(max_span, 1),
        bar_polys=bars,
        screw_holes=screws,
        stats=stats,
    )


def export_stiffeners_to_dxf(msp, stiffener: StiffenerResult, layer: str = "加强筋") -> None:
    """将加强横梁与固定孔写入 DXF 图纸。"""
    if not stiffener.needed:
        return
    from fixture_phase2 import poly_to_dxf_polyline

    for b in stiffener.bar_polys:
        poly_to_dxf_polyline(msp, b, layer)
    for x, y, r in stiffener.screw_holes:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": layer})
