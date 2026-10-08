"""
波峰焊治具 AI 设计助手 — Phase 2
PDF 步骤 6-9：避位区 / 上锡区 / 盖板弹力柱孔 / 治具外形+挡锡条

技术栈：gerbonara(解析) + shapely(几何) + ezdxf(DXF)
"""

from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ezdxf
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union


def layer_pts_from_files(gerber_dir: str, key: str) -> list[tuple[float, float, float]]:
    """按层名直接从文件读点（绕过 LayerStack 的 KiCad10 命名歧义）。

    key: 'bottom mask' | 'top mask' | 'bottom silk' | 'top silk'
    文件名匹配：bottom→*.gbs / top→*.gts（mask），bottom silk→*.gbo / top silk→*.gto
    """
    d = Path(gerber_dir)
    side_ext = {
        "bottom mask": ".gbs",
        "top mask": ".gts",
        "bottom silk": ".gbo",
        "top silk": ".gto",
    }
    ext = side_ext.get(key, ".gbs")
    # 找该扩展名文件（KiCad10 命名如 dev-board-B_Mask.gbs）
    for f in sorted(d.rglob(f"*{ext}")):
        try:
            from gerbonara.rs274x import GerberFile

            gf = GerberFile.open(str(f))
            return objects_to_points(gf)
        except Exception as e:
            log.warning(f"  层文件 {f.name} 解析失败: {e}")
    return []


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fixture2")


# ─────────────────────────────────────────────────────────────
# Phase 2 参数（PDF + 行业规范）
# ─────────────────────────────────────────────────────────────
@dataclass
class Phase2Params:
    # 步骤6: 避位区（BOT 贴片）
    avoid_fillet_r: float = 1.5  # 包围线框倒角 R1.5
    avoid_group_gap: float = 3.0  # 焊盘分组距离阈值（mm）——覆盖模块焊盘间距(≤2.54mm)把同元件合并
    avoid_pad_extra: float = 2.0  # 焊盘外扩包围——覆盖元件体(焊盘→封装外沿)防压margin
    # 步骤7: 上锡区（TOP 插件）
    solder_fillet_r: float = 2.0  # 倒角 R2
    solder_min_gap: float = 3.0  # 焊脚距线框边 ≥3mm（PDF）
    solder_tight_gap: float = 0.7  # 与避位区最小间距 0.7mm（PDF）
    solder_group_gap: float = 4.0  # 插件焊脚分组距离
    # 步骤8: 盖板弹力柱孔
    cap_hole_r: float = 2.45  # 半径 2.45mm（PDF）
    # 步骤9: 治具外形
    ext_left_right: float = 20.0  # 左右外扩 20mm
    ext_top_bottom: float = 30.0  # 上下外扩 30mm
    outer_fillet_r: float = 5.0  # 外形倒角 R5
    rail_width: float = 5.0  # 轨道边宽 5mm（虚线）
    tin_strip_w: float = 10.0  # 挡锡条宽 10mm
    tin_hole_r: float = 1.6  # 挡锡条圆孔 R1.6
    # 步骤10: 拼版阵列（企业级：小板一治具多片，Macaos Panelizer 同款能力）
    panel_cols: int = 1  # X 向片数
    panel_rows: int = 1  # Y 向片数
    panel_gap: float = 5.0  # 片间距 mm（挡锡墙，行业下限 3mm）
    # 步骤11: 气孔与导气 (Gas Venting, AGICORP §4.2)
    enable_vent_holes: bool = True  # 开启闭合避位腔排气孔
    vent_hole_r: float = 1.0  # 排气孔半径 1.0mm (Φ2.0mm，机加工标准钻头)
    min_vent_cavity_area: float = 50.0  # 需要排气孔的最小腔体面积 mm²
    # 步骤12: 铰链式防翘曲上盖 (Hinged Top Hat Cover, AGICORP §2.0)
    enable_top_hat: bool = False  # 开启铰链式压紧上盖生成
    # 步骤13: 治具底部热平衡减重开槽 (SMTA 热剖面平衡规范)
    enable_lightening: bool = True  # 开启底部减重散热沉槽
    lightening_depth_mm: float = 5.0  # 减重开槽深度 (mm)


@dataclass
class Phase2Result:
    avoid_polys: list = field(default_factory=list)  # 避位区
    solder_polys: list = field(default_factory=list)  # 上锡区
    cap_holes: list = field(default_factory=list)  # 盖板孔 (x,y,r)
    outer_poly: Polygon | None = None  # 治具外形
    rail_lines: list = field(default_factory=list)  # 轨道边虚线
    tin_strip_lines: list = field(default_factory=list)  # 挡锡条
    tin_holes: list = field(default_factory=list)  # 挡锡条孔
    sink_poly: Polygon | None = None  # 沉板区（3D 用）
    dogbone_corners: list = field(default_factory=list)  # 狗骨头减隙刀路 (DogboneCorner)
    panel_grid: dict | None = None  # 拼版网格信息（panelize.PanelGrid.to_dict()）
    vent_holes: list = field(default_factory=list)  # 避位腔排气孔 (x,y,r)
    flow_arrow_lines: list = field(default_factory=list)  # 过板流向箭头 (AGICORP §2.1)
    top_hat: Any | None = None  # 铰链上盖结果 (top_hat.TopHatResult)
    dimensions: list = field(default_factory=list)  # 关键尺寸工程标尺图元
    chamfers: list = field(default_factory=list)  # 底面 60°/45° 波峰导流倒角与脱锡槽
    stiffener: Any | None = None  # 大跨度防下垂加强横梁 (stiffener_bar.StiffenerResult)
    gold_shields: list = field(
        default_factory=list
    )  # 板边金手指防爬锡遮罩压条 (gold_finger_mask.GoldFingerShield)
    lightening: Any | None = None  # 底部热平衡减重开槽 (lightening_pockets.LighteningPocketResult)
    thermal_profile: Any | None = (
        None  # 热电偶测温孔通道与传感器感应切角 (thermal_profile.ThermalProfileResult)
    )


# ─────────────────────────────────────────────────────────────
# 通用：图形对象 → shapely 点集
# ─────────────────────────────────────────────────────────────
def objects_to_points(layer) -> list[tuple[float, float, float]]:
    """层对象 → [(x, y, 尺寸)]：Flash 给中心点+尺寸，Line 给中点"""
    pts = []
    for o in layer.objects:
        cls = o.__class__.__name__
        if cls == "Flash":
            try:
                dia = o.aperture.diameter if o.aperture else 0.5
                pts.append((float(o.x), float(o.y), float(dia)))
            except Exception:
                pts.append((float(o.x), float(o.y), 0.5))
        elif cls == "Line":
            pts.append(((o.x1 + o.x2) / 2, (o.y1 + o.y2) / 2, 0.1))
        elif cls == "Arc":
            try:
                pts.append((float(o.center_x), float(o.center_y), 0.1))
            except Exception as e:
                log.debug("Arc 中心点提取失败: %s", e)
    return pts


def group_points(points: list[tuple], gap: float) -> list[list[tuple]]:
    """按距离阈值分组（贪心聚类）"""
    groups: list[list[tuple]] = []
    for p in points:
        placed = False
        for g in groups:
            # 与组内任一点距离 < gap 则并入
            for gp in g:
                dx = p[0] - gp[0]
                dy = p[1] - gp[1]
                if math.hypot(dx, dy) < gap:
                    g.append(p)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            groups.append([p])
    return groups


def convex_hull_buffer(points: list[tuple], extra: float, fillet_r: float) -> Polygon:
    """点集凸包 + 外扩 + 圆角"""
    from shapely.geometry import MultiPoint

    if len(points) < 3:
        # 单点/两点：用缓冲圆/缓冲线
        pts = [Point(x, y).buffer(extra, quad_segs=8) for x, y, _ in points]
        base = unary_union(pts)
    else:
        mp = MultiPoint([(x, y) for x, y, _ in points])
        base = mp.convex_hull.buffer(extra, join_style="round", quad_segs=8)
    # 圆角
    return base.buffer(fillet_r, join_style="round", quad_segs=12).buffer(
        -fillet_r, join_style="round", quad_segs=12
    )


# ─────────────────────────────────────────────────────────────
# 步骤 6: 避位区（BOT 贴片）
# ─────────────────────────────────────────────────────────────
def make_avoid_regions(stack_or_dir, drills: list, p: Phase2Params) -> list[Polygon]:
    """BOT+TOP 面贴片 → 避位区（成片包围）。

    stack_or_dir: LayerStack 或 Gerber 目录字符串（后者用文件名直读层，兼容 KiCad10）
    """
    # 贴片焊盘来源：bottom+top mask Flash（阻焊开窗=贴片/插件焊盘）
    if isinstance(stack_or_dir, str):
        pad_pts_bot = layer_pts_from_files(stack_or_dir, "bottom mask")
        pad_pts_top = layer_pts_from_files(stack_or_dir, "top mask")
        pad_pts = pad_pts_bot + pad_pts_top
    else:
        pad_pts = objects_to_points(stack_or_dir["bottom mask"])
        try:
            pad_pts += objects_to_points(stack_or_dir["top mask"])
        except Exception as e:
            log.debug("top mask 层缺失: %s", e)

    # 判定插件：焊盘中心附近有钻孔 = 插件脚（排除出避位区）
    drill_pts = [(x, y) for x, y, r in drills]
    smd_pts = []
    for x, y, d in pad_pts:
        is_pth = any(math.hypot(x - dx, y - dy) < 1.5 for dx, dy in drill_pts)
        if not is_pth:
            smd_pts.append((x, y, d))

    log.info(f"  步骤6 贴片焊盘: {len(smd_pts)} 个（排除插件 {len(pad_pts) - len(smd_pts)}）")

    groups = group_points(smd_pts, p.avoid_group_gap)
    polys = []
    for g in groups:
        if len(g) < 1:
            continue
        poly = convex_hull_buffer(g, p.avoid_pad_extra, p.avoid_fillet_r)
        if poly.area > 0:
            polys.append(poly)
    # 合并相邻避位区（同一元件多组焊盘 → 一个完整避位区）
    # 先各自外扩 union_gap，让相邻组重叠，再 unary_union 融合，最后收回
    if len(polys) > 1:
        from shapely.ops import unary_union as _union

        union_gap = 1.0  # 外扩量（mm）：相邻组间距<2mm 时重叠→合并
        try:
            expanded = [poly.buffer(union_gap, join_style="round") for poly in polys]
            merged = _union(expanded)
            merged = merged.buffer(-union_gap, join_style="round")
            if merged.geom_type == "MultiPolygon":
                polys = [m for m in merged.geoms if m.area > 0]
            else:
                polys = [merged] if merged.area > 0 else []
        except Exception as e:
            log.warning("避位区合并失败，使用独立区域: %s", e)
    log.info(f"  步骤6 避位区: {len(polys)} 个区域（合并后）")
    return polys


# ─────────────────────────────────────────────────────────────
# 步骤 7: 上锡区（TOP 插件焊脚包围）
# ─────────────────────────────────────────────────────────────
def make_solder_regions(
    stack_or_dir, drills: list, avoid_polys: list, p: Phase2Params
) -> list[Polygon]:
    """插件焊脚 → 上锡区（与避位区保持 ≥0.7mm）"""
    if isinstance(stack_or_dir, str):
        pad_pts = layer_pts_from_files(stack_or_dir, "bottom mask")
    else:
        pad_pts = objects_to_points(stack_or_dir["bottom mask"])
    drill_pts = [(x, y) for x, y, r in drills]

    # 插件判定：mask 焊盘中心 + 有钻孔 = 插件焊脚
    pth_pts = []
    for x, y, d in pad_pts:
        is_pth = any(math.hypot(x - dx, y - dy) < 1.5 for dx, dy in drill_pts)
        if is_pth:
            pth_pts.append((x, y, d))

    log.info(f"  步骤7 插件焊脚: {len(pth_pts)} 个")

    # 分组包围（插件焊脚间距近的合并成片）
    groups = group_points(pth_pts, p.solder_group_gap)
    polys = []
    for g in groups:
        if len(g) < 1:
            continue
        poly = convex_hull_buffer(g, 1.0, p.solder_fillet_r)
        # 与避位区冲突检查：至少保持 0.7mm
        if avoid_polys:
            avoid_union = unary_union(avoid_polys)
            if poly.intersects(avoid_union.buffer(-p.solder_tight_gap)):
                # 冲突时缩小（buffer 负方向）
                poly = poly.buffer(-0.5)
        if poly.area > 0:
            polys.append(poly)
    log.info(f"  步骤7 上锡区: {len(polys)} 个区域")
    return polys


# ─────────────────────────────────────────────────────────────
# 步骤 8: 盖板弹力柱孔（TOP 插件丝印中心）
# ─────────────────────────────────────────────────────────────
def make_cap_holes(stack_or_dir, p: Phase2Params) -> list[tuple[float, float, float]]:
    """TOP 丝印(GTO) → 每个丝印元素中心 → Φ2.45（半径）圆"""
    if isinstance(stack_or_dir, str):
        silk_pts = layer_pts_from_files(stack_or_dir, "top silk")
    else:
        silk_pts = objects_to_points(stack_or_dir["top silk"])
    holes = []
    for x, y, _ in silk_pts:
        holes.append((x, y, p.cap_hole_r))
    log.info(f"  步骤8 盖板弹力柱孔: {len(holes)} 个（半径 {p.cap_hole_r}mm）")
    return holes


# ─────────────────────────────────────────────────────────────
# 步骤 8.5: 闭合避位腔排气孔（AGICORP §4.2 气流通道）
# ─────────────────────────────────────────────────────────────
def make_vent_holes(
    avoid_polys: list,
    solder_polys: list,
    p: Phase2Params,
) -> list[tuple[float, float, float]]:
    """闭合避位腔排气孔（AGICORP §4.2: 防止截留助焊剂气体导致虚焊/漏焊）。

    对面积 ≥ min_vent_cavity_area 的闭合避位腔，在其内部安全点放置 Φ2.0mm 排气孔（通至治具顶面）。
    返回 [(x, y, r)]
    """
    if not p.enable_vent_holes:
        return []
    holes: list[tuple[float, float, float]] = []
    from shapely.ops import unary_union

    solder_union = unary_union(solder_polys) if solder_polys else None

    for av in avoid_polys:
        if av is None or av.is_empty or av.area < p.min_vent_cavity_area:
            continue
        # 若已与上锡区大面积相交贯通，气体可从上锡口排出，无需额外打孔
        if solder_union and av.intersection(solder_union).area > 15.0:
            continue
        inner = av.buffer(-1.5)
        pt = inner.representative_point() if not inner.is_empty else av.representative_point()
        holes.append((round(pt.x, 3), round(pt.y, 3), p.vent_hole_r))
    if holes:
        log.info(
            f"  步骤8.5 排气孔: {len(holes)} 个（半径 {p.vent_hole_r}mm，AGICORP §4.2 导气通道）"
        )
    return holes


# ─────────────────────────────────────────────────────────────
# 步骤 9: 治具外形 + 轨道边 + 挡锡条
# ─────────────────────────────────────────────────────────────
def make_outer(sink_poly: Polygon, p: Phase2Params) -> Phase2Result:
    """沉板区外扩 → 整数化外形 + R5 倒角 + 轨道虚线 + 挡锡条"""
    minx, miny, maxx, maxy = sink_poly.bounds

    # 外扩
    ox = minx - p.ext_left_right
    step = 5.0
    raw_left = minx - p.ext_left_right
    raw_right = maxx + p.ext_left_right
    raw_bot = miny - p.ext_top_bottom
    raw_top = maxy + p.ext_top_bottom

    ox = math.floor(raw_left / step) * step
    oy = math.floor(raw_bot / step) * step
    right = math.ceil(raw_right / step) * step
    top = math.ceil(raw_top / step) * step
    ow_int = right - ox
    oh_int = top - oy

    outer = box(ox, oy, right, top)
    # R5 倒角
    outer_r = outer.buffer(p.outer_fillet_r, join_style="round", quad_segs=12).buffer(
        -p.outer_fillet_r, join_style="round", quad_segs=12
    )

    result = Phase2Result(outer_poly=outer_r)

    # 上下顶边轨道虚线（宽 5mm 虚线区域）
    top_y = oy + oh_int
    bot_y = oy
    result.rail_lines = [
        (ox, top_y - p.rail_width, ox + ow_int, top_y),  # 上轨道边
        (ox, bot_y, ox + ow_int, bot_y + p.rail_width),  # 下轨道边
    ]

    # 挡锡条：左右齐边 + 上下四边框内 10mm 宽（简化为四条边线）
    result.tin_strip_lines = [
        (ox, oy + oh_int - p.tin_strip_w, ox + ow_int, oy + oh_int - p.tin_strip_w),  # 上
        (ox, oy + p.tin_strip_w, ox + ow_int, oy + p.tin_strip_w),  # 下
        (ox + p.tin_strip_w, oy, ox + p.tin_strip_w, oy + oh_int),  # 左
        (ox + ow_int - p.tin_strip_w, oy, ox + ow_int - p.tin_strip_w, oy + oh_int),  # 右
    ]

    # 挡锡条圆孔 R1.6，每条边 3 个（上/下边均匀分布）
    for strip_y in (oy + oh_int - p.tin_strip_w / 2, oy + p.tin_strip_w / 2):
        for i in range(1, 4):
            x = ox + ow_int * i / 4
            result.tin_holes.append((x, strip_y, p.tin_hole_r))

    # 过板方向指示箭头（AGICORP §2.1）：上导轨处雕刻流向箭头
    mid_x = ox + ow_int / 2.0
    arrow_y = top_y - p.rail_width / 2.0
    result.flow_arrow_lines = [
        (mid_x - 15.0, arrow_y, mid_x + 15.0, arrow_y),
        (mid_x + 15.0, arrow_y, mid_x + 9.0, arrow_y + 3.0),
        (mid_x + 15.0, arrow_y, mid_x + 9.0, arrow_y - 3.0),
    ]

    log.info(f"  步骤9 治具外形: {ow_int:.0f}x{oh_int:.0f}mm 整数化 + R{p.outer_fillet_r} 倒角")
    log.info(f"       轨道边 2 条 + 挡锡条 4 条 + 挡锡条孔 {len(result.tin_holes)} 个")
    return result


# ─────────────────────────────────────────────────────────────
# DXF 输出（Phase 2 图层）
# ─────────────────────────────────────────────────────────────
LAYER_COLORS2 = {
    "沉板区": 1,  # 红
    "取手位": 3,  # 绿
    "配件层": 4,  # 青
    "定位销": 5,  # 蓝
    "避位区": 6,  # 紫
    "上锡区": 2,  # 黄
    "盖板": 7,  # 白
    "治具外形": 8,  # 灰
    "清角刀路": 30,  # 橙色 (狗骨头清角刀路)
    "排气孔": 144,  # 青绿 (AGICORP §4.2 导气孔)
    "工程注记": 7,  # 白/银 (过板方向与规格文字)
    "上盖外形": 3,  # 绿 (防翘曲压紧上盖)
    "上盖开孔": 1,  # 红
    "铰链位": 4,  # 青
    "锁扣位": 6,  # 紫
    "上盖压柱": 5,  # 蓝
    "工程尺寸": 7,  # 白/银 (工程尺寸标注)
    "导流倒角": 14,  # 橄榄绿/金 (底面 60°/45° 导流斜面与脱锡槽)
    "加强筋": 8,  # 灰 (大跨度防下垂加强横梁)
    "金手指遮罩": 40,  # 金黄色 (边缘金手指防爬锡压条)
    "减重槽": 9,  # 浅灰 (底部热平衡减重开槽)
    "测温孔": 140,  # 浅蓝 (K型热电偶测温通道与走线槽)
}


def poly_to_dxf_polyline(msp, poly, layer: str):
    if poly.is_empty:
        return
    if poly.geom_type == "MultiPolygon":
        for sub in poly.geoms:
            poly_to_dxf_polyline(msp, sub, layer)
        return
    coords = list(poly.exterior.coords)
    msp.add_lwpolyline(coords, dxfattribs={"layer": layer, "flags": 1})


def export_dxf2(
    result: Phase2Result,
    out_path: str,
    sink_poly=None,
    handles=None,
    screws=None,
    pins=None,
    dogbone_corners=None,
):
    out_path = str(Path(out_path))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    for name, color in LAYER_COLORS2.items():
        doc.layers.add(name, color=color)
    if "拼版信息" not in {l.dxf.name for l in doc.layers}:
        doc.layers.add("拼版信息", color=8)

    msp = doc.modelspace()

    # 拼版信息注记（企业级：N×M 阵列 + 间距，供 CAM/生产核对）
    grid = getattr(result, "panel_grid", None)
    if grid:
        minx, _miny, _maxx, maxy = (
            result.outer_poly.bounds if result.outer_poly else (0, 0, 100, 100)
        )
        msp.add_text(
            f"PANEL {grid.get('cols', 1)}x{grid.get('rows', 1)} "
            f"gap {grid.get('gap', 0)}mm copies {grid.get('copies', 1)} "
            f"total {grid.get('total', [0, 0])[0]:.1f}x{grid.get('total', [0, 0])[1]:.1f}mm",
            dxfattribs={"layer": "拼版信息", "height": 4.0},
        ).set_placement((minx, maxy + 6))

    # Phase 1 元素
    if sink_poly:
        poly_to_dxf_polyline(msp, sink_poly, "沉板区")
    for h in handles or []:
        poly_to_dxf_polyline(msp, h, "取手位")
    for x, y in screws or []:
        msp.add_circle((x, y), radius=1.7, dxfattribs={"layer": "配件层"})
    for x, y, r in pins or []:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": "定位销"})

    # 狗骨头清角专用刀路图层
    corners = dogbone_corners or getattr(result, "dogbone_corners", None)
    if corners:
        from dogbone import add_dogbone_to_dxf

        add_dogbone_to_dxf(msp, corners, layer="清角刀路")

    # Phase 2 元素
    for a in result.avoid_polys:
        poly_to_dxf_polyline(msp, a, "避位区")
    for s in result.solder_polys:
        poly_to_dxf_polyline(msp, s, "上锡区")
    for x, y, r in result.cap_holes:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": "盖板"})
    if result.outer_poly:
        poly_to_dxf_polyline(msp, result.outer_poly, "治具外形")
    for x1, y1, x2, y2 in result.rail_lines:
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "治具外形", "linetype": "DASHED"})
    for x1, y1, x2, y2 in result.tin_strip_lines:
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "治具外形"})
    for x, y, r in result.tin_holes:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": "治具外形"})

    # 排气孔 (AGICORP §4.2 气流通道)
    for x, y, r in getattr(result, "vent_holes", []):
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": "排气孔"})

    # 工程注记与过板方向指示 (AGICORP §2.1)
    for x1, y1, x2, y2 in getattr(result, "flow_arrow_lines", []):
        msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "工程注记"})
    if getattr(result, "flow_arrow_lines", []):
        ax1, ay1, ax2, _ = result.flow_arrow_lines[0]
        msp.add_text("FLOW ===>", dxfattribs={"layer": "工程注记", "height": 3.0}).set_placement(
            ((ax1 + ax2) / 2.0 - 10.0, ay1 + 2.0)
        )

    # 铰链压紧上盖图层 (Top Hat Cover)
    tophat = getattr(result, "top_hat", None)
    if tophat:
        from top_hat import export_top_hat_to_dxf

        export_top_hat_to_dxf(msp, tophat)

    # 尺寸标注图元 (GB/T 4458.1 & ISO 129-1)
    dims = getattr(result, "dimensions", [])
    if dims:
        from fixture_dimensioning import export_dimensions_to_dxf

        export_dimensions_to_dxf(msp, dims)

    # 导流斜面与脱锡槽 (AGICORP §1.0 & SMTA)
    chamfers = getattr(result, "chamfers", [])
    if chamfers:
        from wave_chamfer import export_chamfers_to_dxf

        export_chamfers_to_dxf(msp, chamfers)

    # 大跨度防下垂加强横梁 (MB-MFG & AGICORP)
    stiffener = getattr(result, "stiffener", None)
    if stiffener and stiffener.needed:
        from stiffener_bar import export_stiffeners_to_dxf

        export_stiffeners_to_dxf(msp, stiffener)

    # 边缘金手指防爬锡遮罩压条 (IPC-A-610G & AGICORP §5.0)
    shields = getattr(result, "gold_shields", [])
    if shields:
        from gold_finger_mask import export_gold_finger_masks_to_dxf

        export_gold_finger_masks_to_dxf(msp, shields)

    # 底部热平衡减重开槽 (SMTA)
    lightening = getattr(result, "lightening", None)
    if lightening and getattr(lightening, "pockets", None):
        from lightening_pockets import export_lightening_pockets_to_dxf

        export_lightening_pockets_to_dxf(msp, lightening)

    # 热电偶测温孔通道与传感器感应切角 (SMTA & IPC-SMEMA-9851)
    tp = getattr(result, "thermal_profile", None)
    if tp:
        from thermal_profile import export_thermal_profile_to_dxf

        export_thermal_profile_to_dxf(msp, tp)

    doc.saveas(out_path)
    log.info(f"✅ DXF 已输出: {out_path}")


# ─────────────────────────────────────────────────────────────
# 主流程（Phase 1 + Phase 2 完整）
# ─────────────────────────────────────────────────────────────
def run_phase2(
    gerber_dir: str,
    out_dxf: str,
    phase1_result=None,
    params1_override: dict | None = None,
    params2_override: dict | None = None,
):
    from fixture_phase1 import (
        FixtureParams,
        make_handles,
        make_pins,
        make_screws,
        make_sink_region,
        parse_gerber,
    )

    params1 = FixtureParams()
    params2 = Phase2Params()
    # 参数覆盖（自然语言调整）
    if params1_override:
        for k, v in params1_override.items():
            if hasattr(params1, k):
                setattr(params1, k, v)
    if params2_override:
        for k, v in params2_override.items():
            if hasattr(params2, k):
                setattr(params2, k, v)

    log.info(f"📂 解析 Gerber: {gerber_dir}")
    board_polys, drills = parse_gerber(gerber_dir)
    if not board_polys:
        log.error("❌ 未找到外形层")
        return

    from shapely.ops import unary_union as _uu

    board = _uu(board_polys)

    # Phase 1 重算 (含狗骨头清角)
    sink, dogbone_corners = make_sink_region(board, params1, return_corners=True)
    handles = make_handles(sink, params1)
    screws = make_screws(sink, params1)
    pins = make_pins(drills, params1, sink_poly=sink)

    # Phase 2（直接用目录字符串，内部按文件名读层——兼容 KiCad10 无 LPC 命名）
    avoid = make_avoid_regions(gerber_dir, drills, params2)
    solder = make_solder_regions(gerber_dir, drills, avoid, params2)
    caps = make_cap_holes(gerber_dir, params2)

    # 拼版阵列（企业级）：单片几何 → N×M 复制 → 重建外形/取手/压扣
    panel_grid = None
    cols = max(int(getattr(params2, "panel_cols", 1) or 1), 1)
    rows = max(int(getattr(params2, "panel_rows", 1) or 1), 1)
    if cols * rows > 1:
        from panelize import panelize_geometry

        board_bounds = board.bounds
        grid, sink, avoid, solder, caps, pins, handles, screws, dogbone_corners = panelize_geometry(
            board_bounds,
            sink,
            avoid,
            solder,
            caps,
            pins,
            handles,
            screws,
            dogbone_corners,
            cols,
            rows,
            params2.panel_gap,
        )
        panel_grid = grid.to_dict()

    outer = make_outer(sink, params2)
    vents = make_vent_holes(avoid, solder, params2)

    tophat_res = None
    if getattr(params2, "enable_top_hat", False):
        from top_hat import generate_top_hat

        tophat_res = generate_top_hat(outer.outer_poly, sink, board, caps)

    from fixture_dimensioning import generate_fixture_dimensions
    from gold_finger_mask import detect_edge_connectors_and_fingers, generate_gold_finger_masks
    from lightening_pockets import generate_lightening_pockets
    from stiffener_bar import generate_stiffener_bars
    from thermal_profile import generate_thermocouple_channels
    from wave_chamfer import generate_wave_flow_chamfers

    dims = generate_fixture_dimensions(outer.outer_poly, sink_poly=sink, pins=pins)
    chamfers = generate_wave_flow_chamfers(solder)
    stiffener = generate_stiffener_bars(outer.outer_poly, sink_poly=sink)
    tp_res = generate_thermocouple_channels(solder, outer.outer_poly, sink_poly=sink)

    finger_regs = detect_edge_connectors_and_fingers(board)
    gold_shields = generate_gold_finger_masks(board, finger_regs)

    lightening_res = None
    if getattr(params2, "enable_lightening", True):
        lightening_res = generate_lightening_pockets(
            outer.outer_poly,
            sink_poly=sink,
            keepouts=avoid + solder,
            pocket_depth_mm=getattr(params2, "lightening_depth_mm", 5.0),
        )

    result2 = Phase2Result(
        avoid_polys=avoid,
        solder_polys=solder,
        cap_holes=caps,
        outer_poly=outer.outer_poly,
        rail_lines=outer.rail_lines,
        tin_strip_lines=outer.tin_strip_lines,
        tin_holes=outer.tin_holes,
        sink_poly=sink,
        dogbone_corners=dogbone_corners,
        panel_grid=panel_grid,
        vent_holes=vents,
        flow_arrow_lines=outer.flow_arrow_lines,
        top_hat=tophat_res,
        dimensions=dims,
        chamfers=chamfers,
        stiffener=stiffener,
        gold_shields=gold_shields,
        lightening=lightening_res,
        thermal_profile=tp_res,
    )

    if out_dxf:
        export_dxf2(
            result2,
            out_dxf,
            sink_poly=sink,
            handles=handles,
            screws=screws,
            pins=pins,
            dogbone_corners=dogbone_corners,
        )

    return result2


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="波峰焊治具 AI 设计助手 Phase 2")
    ap.add_argument("gerber_dir", help="Gerber 文件目录")
    ap.add_argument("-o", "--out", default="fixture2.dxf")
    args = ap.parse_args()
    run_phase2(args.gerber_dir, args.out)
    sys.exit(0)
