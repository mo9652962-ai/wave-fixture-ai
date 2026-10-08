"""波峰焊测温板热电偶测温孔通道 (Thermocouple Profiling Channels) 与 SMEMA 传感器感应缺口引擎。

工业权威依据：
- SMTA Wave Soldering Thermal Profiling Guidelines:
  在量产前调校炉温曲线（使用 KIC Explorer / ECD M.O.L.E. 炉温测试仪）时，必须将多路 K 型
  热电偶 (Thermocouple, TC) 探头穿过治具紧贴关键引脚焊盘与热敏感元器件。
  若治具未预留测温通道，工艺人员往往现场手工野蛮打孔，极易破坏支撑骨架或导致熔融锡液倒灌。
  工业级治具标准规范（AGICORP & KIC 规范）：
  在关键上锡区和避位深腔旁预留 Φ2.5mm 测温穿线孔，并在顶面加工 2.5mm 宽 × 2.0mm 深的
  热电偶引线沉线槽 (Wire Routing Channels) 及 M3 耐热高温胶带/压线片固定位，避免引线悬空刮擦炉膛。
- SMEMA / IPC-SMEMA-9851 自动化导轨传感器配合规范：
  自动化波峰焊进出料口配有漫反射/对射式光电感应传感器（如 Omron / Keyence 传感器）。
  治具入板前缘角部若无标准 45° 感应倒角或 15mm×5mm 光电遮断缺口 (Optical Sensor Notch)，
  容易导致光电传感器检测误触发或入板定位抖动。
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon

log = logging.getLogger("fixture-thermal-profile")


@dataclass
class ThermocoupleChannel:
    """单个热电偶测温孔与引线走线槽图元。"""

    index: int
    tc_type: str  # "SOLDER_JOINT" (焊点测温) | "COMPONENT_BODY" (元件体测温)
    hole_pos: tuple[float, float]  # 穿线孔中心 (x, y)
    hole_radius: float = 1.25  # Φ2.5mm 穿线孔
    channel_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )
    fixture_edge_exit: tuple[float, float] | None = None  # 出线槽边缘出口

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tc_type": self.tc_type,
            "hole_pos": (round(self.hole_pos[0], 2), round(self.hole_pos[1], 2)),
            "hole_radius": self.hole_radius,
            "channel_segments": len(self.channel_lines),
        }


@dataclass
class ThermalProfileResult:
    """热电偶测温通道与传感器感应切角结果。"""

    tc_holes: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y, r)
    wire_channel_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )
    sensor_notches: list[tuple[tuple[float, float], tuple[float, float]]] = field(
        default_factory=list
    )
    channels: list[ThermocoupleChannel] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_thermocouple_channels(
    solder_polys: list[Polygon],
    outer_poly: Polygon,
    sink_poly: Polygon | None = None,
    channel_width_mm: float = 2.5,
    tc_hole_dia_mm: float = 2.5,
) -> ThermalProfileResult:
    """自动在上锡开孔关键点与治具边缘之间规划热电偶测温通道与走线槽。"""
    if not solder_polys or outer_poly is None or outer_poly.is_empty:
        return ThermalProfileResult()

    ox0, oy0, ox1, oy1 = outer_poly.bounds
    tc_r = tc_hole_dia_mm / 2.0
    tc_holes: list[tuple[float, float, float]] = []
    channel_lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    channel_objs: list[ThermocoupleChannel] = []

    # 选取代表性上锡区域 (最多选取前 3~4 个关键焊点区布置测温孔)
    valid_solders = [sp for sp in solder_polys if sp and not sp.is_empty][:4]

    for idx, sp in enumerate(valid_solders):
        c = sp.centroid
        hx, hy = c.x + 2.0, c.y + 2.0  # 紧挨焊点开孔边缘，偏置 2mm 打穿线孔
        tc_holes.append((round(hx, 2), round(hy, 2), tc_r))

        # 走线槽引线：从测温孔直接水平引至最近的治具外沿 (便于连接炉温测试仪)
        exit_x = ox0 + 4.0 if (hx - ox0) < (ox1 - hx) else ox1 - 4.0
        line_seg = ((round(hx, 2), round(hy, 2)), (round(exit_x, 2), round(hy, 2)))
        channel_lines.append(line_seg)

        channel_objs.append(
            ThermocoupleChannel(
                index=idx + 1,
                tc_type="SOLDER_JOINT",
                hole_pos=(round(hx, 2), round(hy, 2)),
                hole_radius=tc_r,
                channel_lines=[line_seg],
                fixture_edge_exit=(round(exit_x, 2), round(hy, 2)),
            )
        )

    # 生成 SMEMA 前缘传感器感应切角线 (入板角 45° 倒角感应)
    # 位于治具左上角与左下角 (入板侧)
    notch_size = 12.0
    sensor_notches = [
        ((ox0, oy1 - notch_size), (ox0 + notch_size, oy1)),  # 左上入板 45° 倒角
        ((ox0, oy0 + notch_size), (ox0 + notch_size, oy0)),  # 左下入板 45° 倒角
    ]

    stats = {
        "tc_hole_count": len(tc_holes),
        "channel_count": len(channel_lines),
        "hole_dia_mm": tc_hole_dia_mm,
        "channel_width_mm": channel_width_mm,
        "sensor_notch_count": len(sensor_notches),
        "standard_ref": "SMTA Thermal Profiling Guidelines & IPC-SMEMA-9851",
    }
    log.info(
        f"✅ 生成 {len(tc_holes)} 个热电偶测温孔通道与 {len(sensor_notches)} 个 SMEMA 传感器感应倒角"
    )

    return ThermalProfileResult(
        tc_holes=tc_holes,
        wire_channel_lines=channel_lines,
        sensor_notches=sensor_notches,
        channels=channel_objs,
        stats=stats,
    )


def export_thermal_profile_to_dxf(msp, result: ThermalProfileResult, layer: str = "测温孔") -> None:
    """将热电偶测温孔、走线槽及传感器感应倒角写入 DXF 图纸。"""
    for x, y, r in result.tc_holes:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": layer})
    for p1, p2 in result.wire_channel_lines:
        msp.add_line(p1, p2, dxfattribs={"layer": layer, "linetype": "DASHED"})
    for p1, p2 in result.sensor_notches:
        msp.add_line(p1, p2, dxfattribs={"layer": "工程注记"})
