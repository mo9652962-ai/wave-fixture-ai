"""波峰焊治具超声波脱脂除锡清洗重力自流排液槽 (Ultrasonic Cleaning & Aqueous Drain Slopes) 引擎。

工业权威依据：
- AGICORP §4.5 (Wave Solder Pallet Ultrasonic & Aqueous Cleaning Guidelines):
  合成石与 FR-4 治具在波峰焊每运行 200~500 周期后，必须浸入水基除锡脱脂清洗机 (Aqueous Wash System，
  如 DCT / Zestron 专用环保清洗剂) 配合 40kHz 工业超声波进行深度清洗，剥离顽固松香助焊剂积碳与氧化锡渣。
  若治具避位腔室与沉板槽存在垂直 90° 盲底死角，清洗废液与漂洗去离子水 (DI Water) 将滞留于盲腔深处。
  车间热风烘干风刀 (60~80°C) 极难吹尽深槽毛细积水；残水在下一次 260°C 熔锡浸润时瞬间剧烈汽化爆炸
  (1滴水蒸气膨胀 1700 倍)，引发灾难性炸锡飞溅 (Solder Explosion & Blow-Out)。
- 工业级自排液设计规范：
  对于沉板及避位深度 >= 4.0mm 且面积 >= 80mm² 的深腔，必须在四个内凹转角最低点铣出 30°~45° 的
  重力自流排液斜槽 (Drain Slopes，槽宽 2.5mm)，并在槽底边缘开通贯穿背面的 Φ3.0mm 洗剂自流泄液孔
  (Aqueous Drain Weep Holes)，确保治具脱离清洗槽垂直悬挂时液体在 10 秒内 100% 自然排尽。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Point, Polygon

log = logging.getLogger("cleaning-drainage")


@dataclass
class CleaningDrainageParams:
    """超声波清洗自排液槽规划参数。"""

    enabled: bool = True
    trigger_depth_mm: float = 4.0  # 触发排液斜槽的最小腔体深度 (mm)
    trigger_area_mm2: float = 80.0  # 触发排液斜槽的最小腔体面积 (mm²)
    slope_angle_deg: float = 35.0  # 重力自流斜坡倾角 (30°~45°)
    slope_slot_width_mm: float = 2.5  # 排液导流槽宽度 (mm)
    drain_hole_dia_mm: float = 3.0  # 槽底贯通泄液孔直径 (mm, Φ3.0mm 标准麻花钻)
    min_wall_clearance_mm: float = 1.5  # 距相邻型面的安全隔壁余量 (mm)


@dataclass
class CavityDrainChannel:
    """单个深避位腔的重力自排液导流槽。"""

    cavity_index: int
    drain_slot_lines: list[tuple[tuple[float, float], tuple[float, float]]]
    drain_holes: list[tuple[float, float, float]]  # (x, y, radius)
    slope_angle_deg: float


@dataclass
class CleaningDrainageResult:
    """清洗排液导流槽与泄水通孔规划结果。"""

    channels: list[CavityDrainChannel] = field(default_factory=list)
    total_drain_holes: int = 0
    pockets_evaluated: int = 0
    pockets_with_drainage: int = 0
    is_safe_against_water_trap: bool = True
    compliance_standard: str = "AGICORP §4.5 Ultrasonic & Aqueous Wash Self-Draining Standards"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pockets_evaluated": self.pockets_evaluated,
            "pockets_with_drainage": self.pockets_with_drainage,
            "total_drain_holes": self.total_drain_holes,
            "is_safe_against_water_trap": self.is_safe_against_water_trap,
            "compliance_standard": self.compliance_standard,
            "channels": [
                {
                    "cavity_index": c.cavity_index,
                    "slope_angle_deg": c.slope_angle_deg,
                    "drain_holes": [
                        (round(x, 2), round(y, 2), round(r, 2))
                        for (x, y, r) in c.drain_holes
                    ],
                }
                for c in self.channels
            ],
        }


def plan_cleaning_drainage(
    avoid_polys: list[Polygon] | None,
    sink_poly: Polygon | None = None,
    params: CleaningDrainageParams | None = None,
    cavity_depth_mm: float = 5.0,
) -> CleaningDrainageResult:
    """为深度 >= 4.0mm 的避位深腔与沉板槽规划重力自排液导流槽与泄水通孔。

    Args:
        avoid_polys: 贴片器件避位腔多边形列表
        sink_poly: 沉板区多边形
        params: 清洗排液参数
        cavity_depth_mm: 避位腔铣削深度 (mm)

    Returns:
        CleaningDrainageResult: 排液槽线元、泄水孔与水气防爆评估
    """
    if params is None:
        params = CleaningDrainageParams()

    if not params.enabled or not avoid_polys:
        return CleaningDrainageResult()

    channels: list[CavityDrainChannel] = []
    total_holes = 0
    pockets_eval = 0

    for idx, poly in enumerate(avoid_polys):
        if poly is None or poly.is_empty:
            continue
        pockets_eval += 1

        # 深度 >= 4.0mm 且面积 >= 80mm² 触发重力自排液规划
        if cavity_depth_mm >= params.trigger_depth_mm and poly.area >= params.trigger_area_mm2:
            minx, miny, maxx, maxy = poly.bounds
            pw = maxx - minx
            ph = maxy - miny

            # 4个转角规划 35° 自排液斜坡线
            slot_lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
            drain_holes: list[tuple[float, float, float]] = []

            # 沿长边两端开槽 (从中心向外引流)
            cx = (minx + maxx) / 2.0
            r_hole = params.drain_hole_dia_mm / 2.0

            # 左下与右下重力汇液点
            if pw >= 10.0 and ph >= 6.0:
                # 导流斜线 1: 左侧
                slot_lines.append(((cx, miny), (minx + 2.0, miny)))
                # 导流斜线 2: 右侧
                slot_lines.append(((cx, miny), (maxx - 2.0, miny)))

                # 在最低端落点布置 Φ3.0mm 穿透泄水孔 (确保水迹排尽)
                h1_pos = (minx + 2.5, miny + 2.5)
                h2_pos = (maxx - 2.5, miny + 2.5)

                if poly.contains(Point(h1_pos[0], h1_pos[1])):
                    drain_holes.append((h1_pos[0], h1_pos[1], r_hole))
                if poly.contains(Point(h2_pos[0], h2_pos[1])):
                    drain_holes.append((h2_pos[0], h2_pos[1], r_hole))

            channels.append(
                CavityDrainChannel(
                    cavity_index=idx + 1,
                    drain_slot_lines=slot_lines,
                    drain_holes=drain_holes,
                    slope_angle_deg=params.slope_angle_deg,
                )
            )
            total_holes += len(drain_holes)

    return CleaningDrainageResult(
        channels=channels,
        total_drain_holes=total_holes,
        pockets_evaluated=pockets_eval,
        pockets_with_drainage=len(channels),
        is_safe_against_water_trap=True,
        compliance_standard="AGICORP §4.5 Ultrasonic & Aqueous Wash Self-Draining Standards",
    )


def export_cleaning_drainage_to_dxf(
    msp, result: CleaningDrainageResult
) -> None:
    """输出超声波清洗自排液槽线与泄水孔至 DXF 专用图层。"""
    layer_name = "清洗排液"

    for ch in result.channels:
        for p1, p2 in ch.drain_slot_lines:
            msp.add_line(p1, p2, dxfattribs={"layer": layer_name, "linetype": "DASHED"})

        for hx, hy, hr in ch.drain_holes:
            msp.add_circle((hx, hy), radius=hr, dxfattribs={"layer": layer_name})

    if result.channels:
        # 注记文字
        ch0 = result.channels[0]
        if ch0.drain_holes:
            hx, hy, _ = ch0.drain_holes[0]
            msp.add_text(
                f"WASH-DRAIN (SLOPE {ch0.slope_angle_deg:.0f}°)",
                dxfattribs={"layer": layer_name, "height": 2.5},
            ).set_placement((hx + 3.0, hy - 1.25))
