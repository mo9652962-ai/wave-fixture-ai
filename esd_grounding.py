"""工业防静电 ESD 接地端子 (ESD Grounding Snaps & Dissipation Path) 规划引擎。

工业权威依据：
- ANSI/ESD S20.20-2021 (Protection of Electrical and Electronic Parts, Assemblies and Equipment):
  电子制造车间对静电放电敏感元器件 (ESDS, 如 MOSFET、BGA、高速通信芯片) 提出了严格的防静电控制要求。
  波峰焊治具在预热区高温热风吹拂与链条高速传输摩擦过程中，极易积聚上千伏的摩擦静电位 (Triboelectric Charge)。
  若治具缺乏可靠接地通道，在锡波浸润或人员取板瞬间将发生急剧静电放电击穿敏感半导体结。
  ANSI/ESD S20.20 强制规范：防静电载具的对地电阻 (Point-to-Ground Resistance, Rg) 必须 < 1.0×10⁹ Ω，
  静电衰减时间 (Decay Time, ±1000V → ±100V) 必须 < 2.0 秒。
- IEC 61340-5-1 (Electrostatics - Protection of electronic devices from electrostatic phenomena):
  防静电合成石 (如 Röchling Durostone CFR 767 / Ricocel ES-3261A) 为碳纤维复合抗静电材质，
  表面电阻率范围通常为 10⁵ ~ 10⁹ Ω/sq。
  为确保治具与波峰焊机接地板或金属链爪形成连续闭合接地回路，治具在走板接触侧必须压入专用
  黄铜或不锈钢蘑菇头接地触钉 (ESD Grounding Buttons / Snaps，Φ8.0mm 头部，Φ4.0mm 沉孔压配)，
  且每侧至少布置 2 处触点（首尾冗余），保证治具在过链轮交接时对地通路不发生毫秒级中断。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon

log = logging.getLogger("esd-grounding")


@dataclass
class ESDGroundingParams:
    """ESD 接地与静电耗散规划参数。"""

    enabled: bool = True
    button_head_dia_mm: float = 8.0  # 接地蘑菇头触钉外径 (mm)
    shank_drill_dia_mm: float = 4.0  # 压配柄部钻孔直径 (mm)
    corner_offset_mm: float = 25.0  # 距导轨转角端部的安装安全退让边距 (mm)
    surface_resistivity_ohm_sq: float = 1.0e7  # 基材表面电阻率 (Ω/sq, Durostone CFR767 标称 10⁵~10⁹)
    max_allowed_rg_ohm: float = 1.0e9  # ANSI/ESD S20.20 对地电阻上限 (1.0×10⁹ Ω)
    conveyor_axis: str = "Y"  # 走板行进轴向: 'Y' (触钉位于左右承载轨) 或 'X' (触钉位于上下轨)


@dataclass
class ESDContactPoint:
    """单个 ESD 金属接地触钉物理坐标与接触边。"""

    x: float
    y: float
    head_dia_mm: float
    shank_dia_mm: float
    side: str  # 'left' | 'right' | 'top' | 'bottom'


@dataclass
class ESDGroundingResult:
    """ESD 接地系统规划与 ANSI/ESD S20.20 合规性核算结果。"""

    contact_points: list[ESDContactPoint] = field(default_factory=list)
    total_point_count: int = 0
    estimated_point_to_ground_rg_ohm: float = 0.0
    decay_time_sec: float = 0.0
    is_compliant: bool = True
    compliance_standard: str = "ANSI/ESD S20.20-2021 & IEC 61340-5-1"
    bom_items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_point_count": self.total_point_count,
            "estimated_point_to_ground_rg_ohm": f"{self.estimated_point_to_ground_rg_ohm:.2e}",
            "decay_time_sec": round(self.decay_time_sec, 3),
            "is_compliant": self.is_compliant,
            "compliance_standard": self.compliance_standard,
            "contact_points": [
                {
                    "x": round(cp.x, 2),
                    "y": round(cp.y, 2),
                    "head_dia_mm": cp.head_dia_mm,
                    "shank_dia_mm": cp.shank_dia_mm,
                    "side": cp.side,
                }
                for cp in self.contact_points
            ],
            "bom_items": self.bom_items,
        }


def plan_esd_grounding(
    outer_poly: Polygon | None,
    params: ESDGroundingParams | None = None,
) -> ESDGroundingResult:
    """在治具导轨边框规划首尾冗余的黄铜 ESD 接地触钉，并核算静电泄放对地电阻。

    Args:
        outer_poly: 治具外形边界多边形
        params: ESD 规划参数配置

    Returns:
        ESDGroundingResult: 接地触点坐标、对地电阻评估与 BOM
    """
    if params is None:
        params = ESDGroundingParams()

    if not params.enabled or outer_poly is None or outer_poly.is_empty:
        return ESDGroundingResult()

    minx, miny, maxx, maxy = outer_poly.bounds

    pts: list[ESDContactPoint] = []
    offset = max(10.0, params.corner_offset_mm)

    if params.conveyor_axis.upper() == "Y":
        # 走板 Y 轴向：接地触点位于左右两侧轨 (各前后 2 点，共 4 点)
        # 距侧边 4.0mm (轨边缘中心)
        lx = minx + 4.0
        rx = maxx - 4.0
        # 左前、左后
        pts.append(
            ESDContactPoint(
                x=lx,
                y=miny + offset,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="left",
            )
        )
        pts.append(
            ESDContactPoint(
                x=lx,
                y=maxy - offset,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="left",
            )
        )
        # 右前、右后
        pts.append(
            ESDContactPoint(
                x=rx,
                y=miny + offset,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="right",
            )
        )
        pts.append(
            ESDContactPoint(
                x=rx,
                y=maxy - offset,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="right",
            )
        )
    else:
        # 走板 X 轴向：接地触点位于上下两侧轨
        by = miny + 4.0
        ty = maxy - 4.0
        pts.append(
            ESDContactPoint(
                x=minx + offset,
                y=by,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="bottom",
            )
        )
        pts.append(
            ESDContactPoint(
                x=maxx - offset,
                y=by,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="bottom",
            )
        )
        pts.append(
            ESDContactPoint(
                x=minx + offset,
                y=ty,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="top",
            )
        )
        pts.append(
            ESDContactPoint(
                x=maxx - offset,
                y=ty,
                head_dia_mm=params.button_head_dia_mm,
                shank_dia_mm=params.shank_drill_dia_mm,
                side="top",
            )
        )

    # 物理模型估算：
    # 对地电阻 Rg 包含金属触钉接触电阻 (Rc ≈ 10~50 Ω) 与基材有效体积/表面泄放网络并联
    # 典型 Durostone CFR 767 在多点并联下，实测 Rg 约为表面方块电阻率的 0.1~0.3 倍
    n = len(pts)
    contact_r = 25.0 / max(1, n)
    bulk_dissipation_r = (params.surface_resistivity_ohm_sq * 0.15) / max(1, n)
    total_rg = contact_r + bulk_dissipation_r

    # 静电消散时间衰减模型 (RC 积分): t = -R * C * ln(100/1000) = 2.303 * R * C
    # 典型工装对地杂散电容 C ≈ 100 pF (100e-12 F)
    c_stray = 100e-12
    decay_t = 2.303 * total_rg * c_stray

    is_compliant = total_rg <= params.max_allowed_rg_ohm and decay_t <= 2.0

    bom_items = [
        {
            "part": "ESD-GROUND-BUTTON-BRASS",
            "description": f"Φ{params.button_head_dia_mm:g}mm 黄铜蘑菇头防静电接地压配触钉 (柄部 Φ{params.shank_drill_dia_mm:g}mm)",
            "quantity": n,
            "unit": "颗",
        }
    ]

    return ESDGroundingResult(
        contact_points=pts,
        total_point_count=n,
        estimated_point_to_ground_rg_ohm=total_rg,
        decay_time_sec=decay_t,
        is_compliant=is_compliant,
        compliance_standard="ANSI/ESD S20.20-2021 & IEC 61340-5-1",
        bom_items=bom_items,
    )


def export_esd_grounding_to_dxf(msp, result: ESDGroundingResult) -> None:
    """输出 ESD 金属接地触钉图元与标示到 DXF 专用图层。"""
    layer_name = "防静电接地"

    for cp in result.contact_points:
        # 外蘑菇头 Φ8.0mm (r=4.0mm)
        msp.add_circle((cp.x, cp.y), radius=cp.head_dia_mm / 2.0, dxfattribs={"layer": layer_name})
        # 压配柄孔 Φ4.0mm (r=2.0mm)
        msp.add_circle((cp.x, cp.y), radius=cp.shank_dia_mm / 2.0, dxfattribs={"layer": layer_name, "linetype": "DASHED"})
        # 标示文字
        msp.add_text("ESD-GND", dxfattribs={"layer": layer_name, "height": 2.5}).set_placement((cp.x + 3.0, cp.y - 1.25))

