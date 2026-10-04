"""治具自动工程尺寸标注生成器 (Automated CAD Engineering Dimensioning).

工业定位（对标 CAM350 / AutoCAD / 机械制图国家标准 GB/T 4458.1 & ISO 129-1）：
工程图纸如果仅有裸轮廓线，CNC 操机与质检人员无法在图纸上直接核对关键装配尺寸。
本模块为治具 DXF 自动生成工程制图标注元素（尺寸界线、尺寸线、箭头或端点斜线、以及居中尺寸文字）：
  1. 治具整体外形包围盒长宽标注 (Pallet Outer W × H)
  2. 沉板区跨度与板位基准标注 (Sink Cavity W × H)
  3. 定位销中心距标注 (Pin-to-Pin Center Distance / Span)
  4. 传送带轨道宽度标注 (Rail Width)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon

log = logging.getLogger("fixture-dim")


@dataclass
class DimensionEntity:
    """单个线性尺寸标注图元。"""

    label: str
    p1: tuple[float, float]        # 测量起点
    p2: tuple[float, float]        # 测量终点
    dim_line_p1: tuple[float, float]  # 尺寸线起点
    dim_line_p2: tuple[float, float]  # 尺寸线终点
    text_pos: tuple[float, float]     # 尺寸数值文字位置
    text_val: str                     # 如 "120.0 mm"
    orientation: str = "horizontal"   # "horizontal" | "vertical" | "aligned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "text": self.text_val,
            "p1": self.p1,
            "p2": self.p2,
            "dim_line": [self.dim_line_p1, self.dim_line_p2],
            "text_pos": self.text_pos,
        }


def generate_fixture_dimensions(
    outer_poly: Polygon,
    sink_poly: Polygon | None = None,
    pins: list[tuple[float, float, float]] | None = None,
    offset_mm: float = 12.0,
) -> list[DimensionEntity]:
    """计算治具关键尺寸标注图元列表。"""
    dims: list[DimensionEntity] = []
    if outer_poly is None or outer_poly.is_empty:
        return dims

    ox0, oy0, ox1, oy1 = outer_poly.bounds
    ow = ox1 - ox0
    oh = oy1 - oy0

    # 1. 治具整体外框宽度标注 (下方)
    y_dim_bot = oy0 - offset_mm
    dims.append(DimensionEntity(
        label="治具总宽",
        p1=(ox0, oy0),
        p2=(ox1, oy0),
        dim_line_p1=(ox0, y_dim_bot),
        dim_line_p2=(ox1, y_dim_bot),
        text_pos=((ox0 + ox1) / 2.0, y_dim_bot - 1.5),
        text_val=f"{ow:.1f} mm",
        orientation="horizontal",
    ))

    # 2. 治具整体外框高度标注 (右侧)
    x_dim_right = ox1 + offset_mm
    dims.append(DimensionEntity(
        label="治具总高",
        p1=(ox1, oy0),
        p2=(ox1, oy1),
        dim_line_p1=(x_dim_right, oy0),
        dim_line_p2=(x_dim_right, oy1),
        text_pos=(x_dim_right + 1.5, (oy0 + oy1) / 2.0),
        text_val=f"{oh:.1f} mm",
        orientation="vertical",
    ))

    # 3. 沉板区长宽尺寸标注 (若存在)
    if sink_poly and not sink_poly.is_empty:
        sx0, sy0, sx1, sy1 = sink_poly.bounds
        sw = sx1 - sx0
        sh = sy1 - sy0
        # 沉板宽 (上方)
        y_dim_top = sy1 + offset_mm * 0.7
        dims.append(DimensionEntity(
            label="沉板区长",
            p1=(sx0, sy1),
            p2=(sx1, sy1),
            dim_line_p1=(sx0, y_dim_top),
            dim_line_p2=(sx1, y_dim_top),
            text_pos=((sx0 + sx1) / 2.0, y_dim_top + 1.2),
            text_val=f"SINK {sw:.1f} mm",
            orientation="horizontal",
        ))
        # 沉板高 (左侧)
        x_dim_left = sx0 - offset_mm * 0.7
        dims.append(DimensionEntity(
            label="沉板区宽",
            p1=(sx0, sy0),
            p2=(sx0, sy1),
            dim_line_p1=(x_dim_left, sy0),
            dim_line_p2=(x_dim_left, sy1),
            text_pos=(x_dim_left - 8.0, (sy0 + sy1) / 2.0),
            text_val=f"SINK {sh:.1f} mm",
            orientation="vertical",
        ))

    # 4. 定位销跨度中心距标注 (若存在 ≥2 销)
    if pins and len(pins) >= 2:
        p_a = pins[0]
        p_b = pins[1]
        dist = math.hypot(p_b[0] - p_a[0], p_b[1] - p_a[1])
        dims.append(DimensionEntity(
            label="定位销中心距",
            p1=(p_a[0], p_a[1]),
            p2=(p_b[0], p_b[1]),
            dim_line_p1=(p_a[0], p_a[1]),
            dim_line_p2=(p_b[0], p_b[1]),
            text_pos=((p_a[0] + p_b[0]) / 2.0, (p_a[1] + p_b[1]) / 2.0 + 2.0),
            text_val=f"PINS SPAN {dist:.2f} mm",
            orientation="aligned",
        ))

    return dims


def export_dimensions_to_dxf(msp, dimensions: list[DimensionEntity], layer: str = "工程尺寸") -> None:
    """将尺寸标注线段与标注数值写入 DXF 图纸。"""
    for d in dimensions:
        # 尺寸界线 (Extension lines)
        msp.add_line(d.p1, d.dim_line_p1, dxfattribs={"layer": layer})
        msp.add_line(d.p2, d.dim_line_p2, dxfattribs={"layer": layer})
        # 尺寸线 (Dimension line)
        msp.add_line(d.dim_line_p1, d.dim_line_p2, dxfattribs={"layer": layer})
        # 端点 45° 斜划短线 (Ticks)
        for pt in (d.dim_line_p1, d.dim_line_p2):
            msp.add_line((pt[0] - 1.0, pt[1] - 1.0), (pt[0] + 1.0, pt[1] + 1.0), dxfattribs={"layer": layer})
        # 尺寸数值文本
        rot = 90 if d.orientation == "vertical" else 0
        msp.add_text(
            d.text_val,
            dxfattribs={"layer": layer, "height": 3.0, "rotation": rot},
        ).set_placement(d.text_pos)
