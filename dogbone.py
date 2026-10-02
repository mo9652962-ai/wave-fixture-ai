"""内凹拐角「狗骨头（Dogbone Relief）」刀路与几何生成模块。

工业背景与物理意义：
在波峰焊治具（Pallet / Carrier）CNC 铣削加工中，标准圆柱形铣刀（如 Φ3.175mm / R1.85mm 铣刀）
由于刀具半径 R 的存在，在加工沉板槽（Sink Pocket）的直角/内凹拐角时，必然会在拐角处留下内凸圆角。
当具有直角边缘的矩形 PCB 放入沉板槽时，PCB 的尖角会与槽底拐角的未切削圆弧干涉阻挡，
导致 PCB 无法平整贴合槽底或发生卡滞翘起。

本模块提供工业标准的拐角减隙（Corner Relief）几何与刀路生成：
1. **Dogbone（狗骨头）**：刀具中心沿角平分线向外侧（材料内部）平移，使得铣刀切削圆的外边缘
   恰好切过拐角顶点（或带微量过切余量），在拐角两侧切出对称的“骨节耳”，用最少的切削量
   保证 PCB 锐角完全脱空。
2. **Corner Hole（角孔 / 顶点钻孔）**：以拐角顶点为圆心直接切削半径 R 的圆孔。
3. **T-Bone（丁字角）**：刀具沿其中一条边单向延伸切削，保持另一条边笔直完整。

输出：
- 沉板槽复合多边形（合并狗骨头减隙后的多边形，供 2D 轮廓与 3D 拉伸建模）
- 专用 DXF 刀路图层「清角刀路」（包含刀具下刀中心点、下刀引线与刀具包络圆）
- 拐角数据结构列表（供 CAM 审查与 DRC 校验）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union


@dataclass
class DogboneParams:
    """狗骨头清角参数配置"""

    cutter_r: float = 1.85  # 铣刀半径 (mm)，默认 1.85mm (对应行业标准 Φ3.7mm 或 R1.85 铣刀)
    style: str = "dogbone"  # 清角风格: "dogbone"(狗骨头) | "corner_hole"(角孔) | "tbone"
    clearance_mm: float = 0.05  # 刀具边缘超出顶点的微量避空余量 (mm)
    max_angle_deg: float = 135.0  # 适用清角的最大内角 (度)，钝角通常无需清角
    min_angle_deg: float = 30.0  # 适用清角的最小内角 (度)，过滤锐尖噪点
    quad_segs: int = 16  # 弧线近似精度 (圆周段数/4)


@dataclass
class DogboneCorner:
    """单个内凹拐角清角几何与刀路信息"""

    index: int  # 拐角索引
    vertex: tuple[float, float]  # PCB 拐角顶点坐标 (x, y)
    center: tuple[float, float]  # 铣刀下刀/圆心坐标 (x, y)
    cutter_r: float  # 铣刀半径 (mm)
    bisector: tuple[float, float]  # 外指角平分线单位向量 (bx, by)
    angle_deg: float  # 拐角内角 (度)
    style: str  # 清角风格
    lead_in_line: tuple[tuple[float, float], tuple[float, float]]  # 下刀引线 [(x0,y0), (xc,yc)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "vertex": [round(v, 4) for v in self.vertex],
            "center": [round(c, 4) for c in self.center],
            "cutter_r": self.cutter_r,
            "bisector": [round(b, 4) for b in self.bisector],
            "angle_deg": round(self.angle_deg, 2),
            "style": self.style,
            "lead_in_line": [[round(p[0], 4), round(p[1], 4)] for p in self.lead_in_line],
        }


def detect_concave_corners(
    poly: Polygon,
    params: DogboneParams | None = None,
) -> list[DogboneCorner]:
    """
    在多边形上检测需要清角的内凹拐角（以 PCB 放入沉板槽的视角，即凸出尖角顶点）。
    针对逆时针(CCW)外轮廓，顺时针方向折向材料侧的角。
    """
    params = params or DogboneParams()
    if poly is None or poly.is_empty:
        return []

    # 若为 MultiPolygon，取最大外圈
    if isinstance(poly, MultiPolygon):
        poly = max(poly.geoms, key=lambda g: g.area)

    coords = list(poly.exterior.coords)[:-1]
    n = len(coords)
    if n < 3:
        return []

    is_ccw = poly.exterior.is_ccw
    corners: list[DogboneCorner] = []

    for i in range(n):
        p_prev = coords[i - 1]
        p_curr = coords[i]
        p_next = coords[(i + 1) % n]

        v1 = (p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
        v2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])
        len1 = math.hypot(v1[0], v1[1])
        len2 = math.hypot(v2[0], v2[1])

        if len1 < 1e-4 or len2 < 1e-4:
            continue

        # 叉积判断转向：CCW 轮廓下，凸向外部的尖角 cross > 0
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        is_convex = (cross > 1e-4) if is_ccw else (cross < -1e-4)
        if not is_convex:
            continue

        # 单位向量（均从 p_curr 出发）
        u1 = (-v1[0] / len1, -v1[1] / len1)  # 指向 p_prev
        u2 = (v2[0] / len2, v2[1] / len2)  # 指向 p_next

        # 计算两边夹角 theta (0~180度)
        dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        angle_deg = math.degrees(math.acos(dot))

        if angle_deg > params.max_angle_deg or angle_deg < params.min_angle_deg:
            continue

        # 角平分线单位向量（指向多边形外部/材料内部）
        b_raw = (-(u1[0] + u2[0]), -(u1[1] + u2[1]))
        blen = math.hypot(b_raw[0], b_raw[1])
        if blen < 1e-4:
            continue
        bisector = (b_raw[0] / blen, b_raw[1] / blen)

        # 确定铣刀中心位置
        cutter_r = params.cutter_r
        style = params.style

        if style == "corner_hole":
            # 顶点角孔：直接以拐角顶点为刀具中心
            cx, cy = p_curr[0], p_curr[1]
        elif style == "tbone":
            # 沿第一条边向外平移切削
            d = cutter_r + params.clearance_mm
            cx = p_curr[0] + u1[0] * d
            cy = p_curr[1] + u1[1] * d
        else:
            # 标准狗骨头 (Dogbone)：
            # 刀具中心沿角平分线向外平移。
            # 为了让半径为 cutter_r 的刀具外轮廓恰好切过顶点并留有 clearance，
            # 刀心到顶点的距离应等于 (cutter_r - clearance_mm) * 缩放因子。
            # 对于标准 90 度直角，刀心距顶点为 cutter_r * 0.75 可在两壁均匀切出 ~0.5mm 减隙耳。
            # 精确几何计算：
            # 半角 alpha = theta / 2
            # 当刀心沿角平分线外移 distance 时，刀具切削圆覆盖顶点的距离为 cutter_r - distance
            # 我们希望顶点落在切削圆内部 clearance 深度处：
            # 即 distance = cutter_r - params.clearance_mm
            # 确保 0 < distance < cutter_r
            half_angle = math.radians(angle_deg / 2.0)
            # 考虑两壁间距，标准 90° 时 dist 取 cutter_r * 0.7071 ~ 0.75 最佳
            dist = max(
                0.1, min(cutter_r * 0.95, cutter_r * math.cos(half_angle) + params.clearance_mm)
            )
            cx = p_curr[0] + bisector[0] * dist
            cy = p_curr[1] + bisector[1] * dist

        center = (cx, cy)
        lead_in = (p_curr, center)

        corner = DogboneCorner(
            index=len(corners) + 1,
            vertex=p_curr,
            center=center,
            cutter_r=cutter_r,
            bisector=bisector,
            angle_deg=angle_deg,
            style=style,
            lead_in_line=lead_in,
        )
        corners.append(corner)

    return corners


def apply_dogbone_relief(
    base_poly: Polygon,
    corners: list[DogboneCorner],
    quad_segs: int = 16,
) -> Polygon:
    """
    将狗骨头刀具切削包络圆与基础多边形执行布尔合并，生成带有减隙耳朵的最终沉板区多边形。
    """
    if base_poly is None or base_poly.is_empty:
        return base_poly

    if not corners:
        return base_poly

    relief_circles = [
        Point(c.center[0], c.center[1]).buffer(c.cutter_r, quad_segs=quad_segs) for c in corners
    ]

    try:
        combined = unary_union([base_poly] + relief_circles)
        if isinstance(combined, MultiPolygon):
            combined = max(combined.geoms, key=lambda g: g.area)
        return combined
    except Exception:
        # 几何容错退回
        return base_poly


def generate_dogbone_relief(
    board_poly: Polygon,
    expand_mm: float = 0.2,
    params: DogboneParams | None = None,
) -> tuple[Polygon, list[DogboneCorner]]:
    """
    一站式生成含狗骨头减隙的沉板区几何。

    参数:
        board_poly: PCB 原始板框多边形
        expand_mm: 沉板区常规单边外扩间隙 (通常 0.2mm)
        params: 狗骨头参数配置

    返回:
        (带有狗骨头减隙的沉板槽 Polygon, 拐角刀路列表 list[DogboneCorner])
    """
    params = params or DogboneParams()
    if board_poly is None or board_poly.is_empty:
        return board_poly, []

    # 先在 PCB 原始尖锐角上检测内凹拐角（避免外扩后圆角打碎顶点）
    corners = detect_concave_corners(board_poly, params)

    # 沉板槽基体外扩
    sink_base = board_poly.buffer(expand_mm, join_style="round", quad_segs=params.quad_segs)

    # 合并狗骨头切削圆
    final_sink = apply_dogbone_relief(sink_base, corners, quad_segs=params.quad_segs)

    return final_sink, corners


def add_dogbone_to_dxf(
    msp: Any,
    corners: list[DogboneCorner],
    layer: str = "清角刀路",
    draw_lead_in: bool = True,
    draw_crosshair: bool = True,
) -> None:
    """
    在 DXF 模型空间输出「清角刀路」图层元素：
    1. 铣刀切削圆（直径 = 2 * cutter_r）
    2. 下刀引线（从拐角顶点到铣刀圆心）
    3. 刀心十字十字标（用于数控机床精确定位）
    """
    if not corners:
        return

    for c in corners:
        cx, cy = c.center
        vx, vy = c.vertex
        r = c.cutter_r

        # 刀具切削外圆
        msp.add_circle((cx, cy), radius=r, dxfattribs={"layer": layer})

        # 下刀引线
        if draw_lead_in:
            msp.add_line((vx, vy), (cx, cy), dxfattribs={"layer": layer})

        # 刀心十字微标 (±0.6mm)
        if draw_crosshair:
            ch_len = min(0.6, r * 0.4)
            msp.add_line((cx - ch_len, cy), (cx + ch_len, cy), dxfattribs={"layer": layer})
            msp.add_line((cx, cy - ch_len), (cx, cy + ch_len), dxfattribs={"layer": layer})
