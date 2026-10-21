"""工业 4.0 耐高温陶瓷 UHF RFID 电子标签嵌入沉腔 (Embedded UHF RFID Cavity) 引擎。

工业权威依据：
- IPC-1782A (Standard for Manufacturing and Supply Chain Component Traceability):
  在工业 4.0 智慧 SMT/THT 数字化车间中，治具托盘通过嵌入式工业级超高频 (UHF EPC Gen2 / ISO/IEC 18000-6C)
  抗金属陶瓷耐高温 RFID 标签 (如 Murata Magicstrap / Xerafy Pico Plus / Omni-ID Fit 210)，实现全线自动化无感高速盘点。
  相比光学二维码 (在反复浸涂助焊剂酸雾与超声波脱脂水洗后易磨损褪色或沾染锡渣导致无法识读)，
  耐高温陶瓷 RFID 标签可在 280°C 熔锡环境下长期运行，读写寿命超 10 万次，支持 10 m/s 传送带无视线高速读取。
- 射频防金属涡流失谐与封装腔设计规范 (RF Anti-Detuning Cavity Design):
  RFID 标签陶瓷微带天线在贴近金属导电介质时，电磁场会诱发反向涡流 (Eddy Currents) 产生严重谐振失谐 (Detuning)，
  使读取距离由 2~3 米急剧衰减至零。
  工业标准要求：
    1. 在治具承载非金属边框铣出 15.0mm × 8.0mm × 3.5mm 深度的专用嵌入沉腔 (RFID Recess Pocket)。
    2. 腔体与任何金属件 (包括外沿铝导轨、不锈钢加强横梁、钛合金开孔嵌件、紧固螺栓) 保持 >= 8.0mm
       安全非导电间隙，并灌封耐 300°C 环氧胶封装，杜绝射频失谐。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon, box

log = logging.getLogger("rfid-cavity")


@dataclass
class RFIDCavityParams:
    """RFID 嵌入沉腔参数。"""

    enabled: bool = True
    cavity_width_mm: float = 15.0  # 沉腔长度 (mm, 容纳 12~14mm 陶瓷标签)
    cavity_height_mm: float = 8.0  # 沉腔宽度 (mm, 容纳 5~7mm 标签)
    cavity_depth_mm: float = 3.5  # 沉腔铣削深度 (mm, 容纳 2.5mm 标签与灌胶)
    edge_offset_x_mm: float = 25.0  # 距治具左边缘距离 (mm)
    edge_offset_y_mm: float = 8.0  # 距治具后导轨边缘距离 (mm)
    min_metal_clearance_mm: float = 8.0  # 距金属加强梁/耐磨条的抗失谐安全间隙 (mm)
    tag_protocol: str = "ISO/IEC 18000-6C (EPC Gen2)"


@dataclass
class RFIDCavityResult:
    """RFID 沉腔规划与射频金属避障合规结果。"""

    cavity_poly: Polygon | None = None
    center_pos: tuple[float, float] = (0.0, 0.0)
    cavity_dims: tuple[float, float, float] = (15.0, 8.0, 3.5)
    min_clearance_to_metal_mm: float = 999.0
    is_rf_detuning_safe: bool = True
    tag_protocol: str = "ISO/IEC 18000-6C (EPC Gen2)"
    compliance_standard: str = "IPC-1782A & ISO/IEC 18000-6C Anti-Metal UHF RFID Guidelines"

    def to_dict(self) -> dict[str, Any]:
        return {
            "center_pos": (round(self.center_pos[0], 2), round(self.center_pos[1], 2)),
            "cavity_dims": self.cavity_dims,
            "min_clearance_to_metal_mm": (
                round(self.min_clearance_to_metal_mm, 2)
                if self.min_clearance_to_metal_mm < 900.0
                else None
            ),
            "is_rf_detuning_safe": self.is_rf_detuning_safe,
            "tag_protocol": self.tag_protocol,
            "compliance_standard": self.compliance_standard,
        }


def plan_rfid_embedded_cavity(
    outer_poly: Polygon | None,
    metal_keepouts: list[Polygon] | None = None,
    params: RFIDCavityParams | None = None,
) -> RFIDCavityResult:
    """在治具边框承载区规划抗金属 UHF RFID 标签嵌入沉腔并校核金属抗失谐间隙。

    Args:
        outer_poly: 治具外形边界多边形
        metal_keepouts: 金属加强梁、钛嵌件或金属导轨多边形列表
        params: RFID 参数

    Returns:
        RFIDCavityResult: 沉腔几何、中心坐标及抗失谐合规评估
    """
    if params is None:
        params = RFIDCavityParams()

    if not params.enabled or outer_poly is None or outer_poly.is_empty:
        return RFIDCavityResult()

    minx, _miny, _maxx, maxy = outer_poly.bounds

    # 将 RFID 沉腔布置在治具左上方边框 (避开把手与导轨齿)
    cx = minx + params.edge_offset_x_mm
    cy = maxy - params.edge_offset_y_mm

    hw = params.cavity_width_mm / 2.0
    hh = params.cavity_height_mm / 2.0
    cavity_box = box(cx - hw, cy - hh, cx + hw, cy + hh)

    # 检查距金属加强件的最小间距
    valid_metals = [p for p in (metal_keepouts or []) if p and not p.is_empty]
    min_clr = 999.0
    for m in valid_metals:
        dist = cavity_box.distance(m)
        min_clr = min(min_clr, dist)

    is_safe = min_clr >= params.min_metal_clearance_mm

    return RFIDCavityResult(
        cavity_poly=cavity_box,
        center_pos=(cx, cy),
        cavity_dims=(params.cavity_width_mm, params.cavity_height_mm, params.cavity_depth_mm),
        min_clearance_to_metal_mm=min_clr,
        is_rf_detuning_safe=is_safe,
        tag_protocol=params.tag_protocol,
        compliance_standard="IPC-1782A & ISO/IEC 18000-6C Anti-Metal UHF RFID Guidelines",
    )


def export_rfid_cavity_to_dxf(msp, result: RFIDCavityResult) -> None:
    """输出 RFID 沉腔多边形与文字标示至 DXF 专用图层。"""
    layer_name = "RFID追溯"

    if result.cavity_poly and not result.cavity_poly.is_empty:
        pts = list(result.cavity_poly.exterior.coords)
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})

        # 标注文字
        cx, cy = result.center_pos
        msp.add_text("RFID-UHF", dxfattribs={"layer": layer_name, "height": 2.5}).set_placement(
            (cx - 5.0, cy - 1.25)
        )
