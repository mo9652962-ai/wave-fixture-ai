"""波峰焊治具铰链式防变形压紧上盖（Top Hat / Hinged Solder Pallet Cover）生成引擎。

工业定位（对标高端治具制造商 AGICORP / MB Manufacturing 复杂上盖机构）：
对于超薄板 (厚度 ≤ 1.2mm)、大尺寸板或连接器密集插装板，在 260°C 高温波峰焊熔锡浮力与热应力下，
PCB 极易发生向上翘曲（Warping），导致吃锡不均或虚焊。工业级治具标准解决方案是在托盘后侧加装
铰链与旋转/碰锁锁扣，配合弹力顶针阵列向下压紧 PCB 板边与关键基准点，并在顶板开设观察与散热视窗。

本模块提供完整的上盖参数化建模与 CAM 输出：
  1. 上盖板框生成（与治具外形对齐，内缩 2mm 防磕碰）
  2. 观察视窗与散热开孔（Over-sink Clearance Windows）
  3. 铰链安装位（后导轨侧 2× M4 铰链沉孔）
  4. 旋转碰锁 / 凸轮锁扣安装位（前导轨侧 1~2× M3 锁扣安装孔）
  5. 压板弹簧顶针柱阵列定位（Press-down Plungers）
  6. DXF 专用图层输出（"上盖外形"、"上盖开孔"、"铰链位"、"锁扣位"）及 3D STL 实体建模
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon, box

log = logging.getLogger("fixture-tophat")


@dataclass
class TopHatParams:
    """铰链式压紧上盖设计参数。"""

    enabled: bool = True
    cover_thickness_mm: float = 6.0  # 上盖板厚 (mm, 常用 6mm ESD FR-4 / 铝板)
    cover_inset_mm: float = 2.0  # 上盖相比治具底座外形内缩 (mm, 防开合磕碰)
    window_inset_mm: float = 12.0  # 观察视窗边缘距沉板区内缩 (mm)
    hinge_margin_mm: float = 10.0  # 铰链距上边缘距离 (mm)
    hinge_spacing_mm: float = 60.0  # 双铰链水平间距基准 (mm)
    hinge_hole_d: float = 4.2  # M4 铰链安装螺栓孔径 (mm)
    latch_hole_d: float = 3.4  # M3 锁扣固定螺栓孔径 (mm)
    latch_margin_mm: float = 10.0  # 锁扣距下边缘距离 (mm)
    hold_down_pin_r: float = 1.25  # 弹力压柱半径 (mm, Φ2.5mm)
    material_key: str = "fr4_high_tg"  # 上盖材质 (常用高强度玻纤板或铝合金)


@dataclass
class TopHatResult:
    """上盖建模与几何结果。"""

    cover_poly: Polygon | None = None  # 上盖主体板框
    window_polys: list[Polygon] = field(default_factory=list)  # 观察开窗与避空
    hinge_holes: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y, r)
    latch_holes: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y, r)
    press_pins: list[tuple[float, float, float]] = field(default_factory=list)  # 压紧点 (x, y, r)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_cover": self.cover_poly is not None and not self.cover_poly.is_empty,
            "window_count": len(self.window_polys),
            "hinge_count": len(self.hinge_holes),
            "latch_count": len(self.latch_holes),
            "press_pin_count": len(self.press_pins),
            "stats": self.stats,
        }


def generate_top_hat(
    outer_poly: Polygon,
    sink_poly: Polygon,
    board_poly: Polygon,
    cap_holes: list[tuple[float, float, float]] | None = None,
    params: TopHatParams | None = None,
) -> TopHatResult:
    """根据治具外框与沉板区生成完整的铰链压紧上盖工程几何。"""
    p = params or TopHatParams()
    if not p.enabled or outer_poly is None or outer_poly.is_empty:
        return TopHatResult()

    minx, miny, maxx, maxy = outer_poly.bounds
    w = maxx - minx
    h = maxy - miny

    # 1. 上盖主体轮廓（外框内缩 2mm）
    cover_box = box(
        minx + p.cover_inset_mm,
        miny + p.cover_inset_mm,
        maxx - p.cover_inset_mm,
        maxy - p.cover_inset_mm,
    )
    # 与外框交集确保倒角对齐
    cover_poly = outer_poly.buffer(-p.cover_inset_mm)
    if cover_poly.is_empty:
        cover_poly = cover_box

    # 2. 观察视窗 (Clearance Window)
    # 在沉板区中心上方开设观察/散热窗，让操作员能目测器件是否就位
    window_polys: list[Polygon] = []
    if sink_poly and not sink_poly.is_empty:
        s_minx, s_miny, s_maxx, s_maxy = sink_poly.bounds
        s_w = s_maxx - s_minx
        s_h = s_maxy - s_miny
        if s_w > 2 * p.window_inset_mm and s_h > 2 * p.window_inset_mm:
            win = box(
                s_minx + p.window_inset_mm,
                s_miny + p.window_inset_mm,
                s_maxx - p.window_inset_mm,
                s_maxy - p.window_inset_mm,
            )
            win_r = win.buffer(4.0, join_style="round").buffer(-4.0, join_style="round")
            if isinstance(win_r, Polygon) and not win_r.is_empty:
                window_polys.append(win_r)

    # 3. 铰链安装孔（上侧轨道导轨边缘 2 组）
    hinge_y = maxy - p.hinge_margin_mm
    mid_x = (minx + maxx) / 2.0
    spacing = min(p.hinge_spacing_mm, w * 0.4)
    hinge_r = p.hinge_hole_d / 2.0
    hinge_holes = [
        (round(mid_x - spacing / 2.0, 2), round(hinge_y, 2), hinge_r),
        (round(mid_x + spacing / 2.0, 2), round(hinge_y, 2), hinge_r),
    ]

    # 4. 旋转碰锁 / 凸轮锁扣安装孔（下侧边缘）
    latch_y = miny + p.latch_margin_mm
    latch_r = p.latch_hole_d / 2.0
    latch_holes = [
        (round(mid_x, 2), round(latch_y, 2), latch_r),
    ]

    # 5. 弹力压柱点位（优先复用 cap_holes，否则在 PCB 四周对角安全位布置 4 点）
    press_pins: list[tuple[float, float, float]] = []
    if cap_holes:
        press_pins = [(x, y, p.hold_down_pin_r) for (x, y, _) in cap_holes]
    elif board_poly and not board_poly.is_empty:
        b_minx, b_miny, b_maxx, b_maxy = board_poly.bounds
        press_pins = [
            (round(b_minx + 5.0, 2), round(b_miny + 5.0, 2), p.hold_down_pin_r),
            (round(b_maxx - 5.0, 2), round(b_miny + 5.0, 2), p.hold_down_pin_r),
            (round(b_minx + 5.0, 2), round(b_maxy - 5.0, 2), p.hold_down_pin_r),
            (round(b_maxx - 5.0, 2), round(b_maxy - 5.0, 2), p.hold_down_pin_r),
        ]

    stats = {
        "cover_size_mm": f"{w - 2 * p.cover_inset_mm:.1f} × {h - 2 * p.cover_inset_mm:.1f}",
        "thickness_mm": p.cover_thickness_mm,
        "material": p.material_key,
        "hinges": len(hinge_holes),
        "latches": len(latch_holes),
        "windows": len(window_polys),
        "press_pins": len(press_pins),
    }

    log.info(
        f"✅ 铰链式上盖生成完成: 尺寸={stats['cover_size_mm']}, 厚度={p.cover_thickness_mm}mm, "
        f"铰链={len(hinge_holes)}孔, 锁扣={len(latch_holes)}孔, 压柱={len(press_pins)}点"
    )

    return TopHatResult(
        cover_poly=cover_poly,
        window_polys=window_polys,
        hinge_holes=hinge_holes,
        latch_holes=latch_holes,
        press_pins=press_pins,
        stats=stats,
    )


def export_top_hat_to_dxf(msp, top_hat: TopHatResult, layer_prefix: str = "上盖") -> None:
    """将上盖几何元素写入 DXF modelspace。"""
    if top_hat.cover_poly is None or top_hat.cover_poly.is_empty:
        return

    # 板框
    from fixture_phase2 import poly_to_dxf_polyline

    poly_to_dxf_polyline(msp, top_hat.cover_poly, f"{layer_prefix}外形")

    # 视窗
    for win in top_hat.window_polys:
        poly_to_dxf_polyline(msp, win, f"{layer_prefix}开孔")

    # 铰链孔
    for x, y, r in top_hat.hinge_holes:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": "铰链位"})

    # 锁扣孔
    for x, y, r in top_hat.latch_holes:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": "锁扣位"})

    # 弹力压柱点位
    for x, y, r in top_hat.press_pins:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": f"{layer_prefix}压柱"})
