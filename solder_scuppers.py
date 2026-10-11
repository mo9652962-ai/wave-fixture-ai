"""出板尾端沥锡引流缺口与防拖锡回流斜槽 (Trailing Edge Solder Run-Off Scuppers & Drainage Ramps).

工业背景与工艺标准：
- AGICORP §4.4《Wave Solder Pallet Design Guidelines》与 SEHO / Ersa 波峰焊手册：
  托盘以 4°~7° 仰角驶离液态锡波峰时，PCB 与托盘底面会带出大量残留液态锡 (Drag-out Solder)。
  在脱锡区 (Peel-back Region / Trailing Edge)，如果托盘尾梁 (Trailing Rail / Exit Lip)
  是垂直平直立壁，滞留的锡液将积聚在尾端无法及时流回锡炉，并被带入出板冷却风道，
  滴落在链条滚轮与光电传感器上导致卡板与机构污染；同时尾端积锡还会引起 PCB 尾部引脚
  严重的拖锡拉尖 (Solder Icicles) 与后缘引脚焊锡桥连短路 (IPC-A-610G §7.5)。
- 工业标配沥锡设计规范：
  1. 沥锡导流斜坡 (Drainage Run-Off Ramp)：出板尾梁底面铣削 30°~45° 倒坡，加速熔融锡脱附；
  2. 沥锡引流缺口 (Solder Scuppers)：沿尾梁开设宽度 12~18mm、深 3~4mm 的贯通泄锡凹槽，
     槽间距 ≤ 70mm，使尾部熔融锡液在表面张力打破前迅速顺流回落至锡锅；
  3. 安全密封边距：沥锡槽前缘距沉板区开孔边缘必须保持 ≥ 4.0mm 密封台阶，
     防止液态锡波在过板冲力下沿沥锡槽反灌入沉板区。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon, box


@dataclass
class SolderScuppersParams:
    scupper_width_mm: float = 15.0  # 沥锡引流槽宽度 (mm)
    scupper_depth_mm: float = 3.0  # 沥锡槽下沉深度 (mm)
    ramp_angle_deg: float = 30.0  # 尾梁沥锡倒坡角度 (度)
    max_scupper_pitch_mm: float = 70.0  # 相邻沥锡槽最大跨距 (mm)
    min_clearance_to_sink_mm: float = 5.0  # 沥锡槽距沉板区最小密封边距 (mm)
    flow_direction: str = "X+"  # 过板流向: "X+" (左至右出板) | "Y+" (下至上出板)


@dataclass
class SolderScupper:
    scupper_id: str
    center_x_mm: float
    center_y_mm: float
    width_mm: float
    length_mm: float
    box_poly: Polygon | None = None
    ramp_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if "box_poly" in d:
            d["box_poly"] = None
        return d


@dataclass
class SolderScuppersResult:
    scupper_count: int
    scuppers: list[SolderScupper] = field(default_factory=list)
    scupper_polys: list[Polygon] = field(default_factory=list)
    ramp_angle_deg: float = 30.0
    flow_direction: str = "X+"
    min_clearance_found_mm: float = 999.0
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scuppers"] = [s.to_dict() for s in self.scuppers]
        d["scupper_polys"] = []
        return d


def generate_trailing_solder_scuppers(
    outer_poly: Polygon,
    sink_poly: Polygon | None = None,
    params: SolderScuppersParams | None = None,
) -> SolderScuppersResult:
    """在治具出板尾梁生成 30° 沥锡斜坡与阵列式沥锡引流缺口。"""
    p = params or SolderScuppersParams()
    ox0, oy0, ox1, oy1 = outer_poly.bounds
    pallet_w = ox1 - ox0
    pallet_h = oy1 - oy0

    scuppers: list[SolderScupper] = []
    scupper_polys: list[Polygon] = []
    min_clr = 999.0

    # 假定 X+ 流向：出板尾端在 ox1 (右侧轨边)；若 Y+ 则在 oy1 (上侧边)
    is_x_flow = "X" in p.flow_direction.upper()

    if is_x_flow:
        trailing_span = pallet_h - 20.0  # 两侧导轨留 10mm
        n = max(1, math.ceil(trailing_span / p.max_scupper_pitch_mm))
        step = trailing_span / (n + 1)
        slot_len = 12.0  # 沿 X 轴向内开槽深度

        for i in range(1, n + 1):
            cy = oy0 + 10.0 + i * step
            cx = ox1 - slot_len / 2.0
            s_box = box(ox1 - slot_len, cy - p.scupper_width_mm / 2.0, ox1, cy + p.scupper_width_mm / 2.0)
            scupper_polys.append(s_box)

            # 30° 沥锡斜坡投影线
            ramp_l1 = ((ox1 - slot_len, cy - p.scupper_width_mm / 2.0), (ox1, cy - p.scupper_width_mm / 4.0))
            ramp_l2 = ((ox1 - slot_len, cy + p.scupper_width_mm / 2.0), (ox1, cy + p.scupper_width_mm / 4.0))

            if sink_poly and not sink_poly.is_empty:
                dist = s_box.distance(sink_poly)
                min_clr = min(min_clr, dist)

            scuppers.append(
                SolderScupper(
                    scupper_id=f"SCUPPER_{i}",
                    center_x_mm=round(cx, 2),
                    center_y_mm=round(cy, 2),
                    width_mm=p.scupper_width_mm,
                    length_mm=slot_len,
                    box_poly=s_box,
                    ramp_lines=[ramp_l1, ramp_l2],
                )
            )
    else:
        trailing_span = pallet_w - 20.0
        n = max(1, math.ceil(trailing_span / p.max_scupper_pitch_mm))
        step = trailing_span / (n + 1)
        slot_len = 12.0

        for i in range(1, n + 1):
            cx = ox0 + 10.0 + i * step
            cy = oy1 - slot_len / 2.0
            s_box = box(cx - p.scupper_width_mm / 2.0, oy1 - slot_len, cx + p.scupper_width_mm / 2.0, oy1)
            scupper_polys.append(s_box)

            ramp_l1 = ((cx - p.scupper_width_mm / 2.0, oy1 - slot_len), (cx - p.scupper_width_mm / 4.0, oy1))
            ramp_l2 = ((cx + p.scupper_width_mm / 2.0, oy1 - slot_len), (cx + p.scupper_width_mm / 4.0, oy1))

            if sink_poly and not sink_poly.is_empty:
                dist = s_box.distance(sink_poly)
                min_clr = min(min_clr, dist)

            scuppers.append(
                SolderScupper(
                    scupper_id=f"SCUPPER_{i}",
                    center_x_mm=round(cx, 2),
                    center_y_mm=round(cy, 2),
                    width_mm=p.scupper_width_mm,
                    length_mm=slot_len,
                    box_poly=s_box,
                    ramp_lines=[ramp_l1, ramp_l2],
                )
            )

    stats = {
        "scupper_count": len(scuppers),
        "scupper_width_mm": p.scupper_width_mm,
        "ramp_angle_deg": p.ramp_angle_deg,
        "flow_direction": p.flow_direction,
        "min_clearance_to_sink_mm": round(min_clr, 2) if min_clr < 900.0 else None,
    }

    return SolderScuppersResult(
        scupper_count=len(scuppers),
        scuppers=scuppers,
        scupper_polys=scupper_polys,
        ramp_angle_deg=p.ramp_angle_deg,
        flow_direction=p.flow_direction,
        min_clearance_found_mm=round(min_clr, 2) if min_clr < 900.0 else 0.0,
        stats=stats,
    )


def export_solder_scuppers_to_dxf(msp, result: SolderScuppersResult) -> None:
    """输出尾梁沥锡槽外框、30° 沥锡导流斜坡线及工程注记到 DXF 专用图层。"""
    layer_name = "沥锡导流"

    for sc in result.scuppers:
        if sc.box_poly and not sc.box_poly.is_empty:
            pts = list(sc.box_poly.exterior.coords)
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})
        for p1, p2 in sc.ramp_lines:
            msp.add_line(p1, p2, dxfattribs={"layer": layer_name})

    if result.scuppers:
        s0 = result.scuppers[0]
        msp.add_text(
            f"RUN-OFF SCUPPER ({result.ramp_angle_deg:.0f} DEG RAMP, N={result.scupper_count})",
            dxfattribs={"layer": layer_name, "height": 2.2, "insert": (s0.center_x_mm - 6.0, s0.center_y_mm)},
        )
