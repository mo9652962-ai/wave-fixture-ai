"""治具防反向装载非对称切角 (Pallet Orientation Keying Chamfer).

工业背景与防错基准：
- Ersa / SEHO / 劲拓波峰焊机上下板机与轨道挡板结构前后近似对称：
  当治具外形本身也接近对称 (长宽比 0.85~1.15 或前后端特征雷同) 时，
  装板工/自动上板机极易将治具 **180° 反向**推入轨道——波峰流向随即反转，
  上锡开孔位置整板镜像，迎锡侧变脱锡侧，直接造成整板漏焊/桥连批量报废。
- 工业防错惯例 (Poka-Yoke)：
  在治具**出板侧右下角**切除 15×15mm 的 45° 非对称大倒角作为方向键 (Orientation Key)，
  上板机挡块仅允许一个方向贴合推送；同时与常规外形 5mm R 角形成显著视觉区分。
  切角轮廓同步进入 CNC 外形精铣刀路与 DXF 防呆图层。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon


@dataclass
class PalletKeyingParams:
    chamfer_mm: float = 15.0  # 方向键 45° 切角直角边长 (mm)
    corner: str = "front_right"  # 出板侧右下角 (front_right / front_left / back_right / back_left)


@dataclass
class PalletKeyingResult:
    keyed_poly: Polygon
    chamfer_lines: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)
    chamfer_mm: float = 15.0
    corner: str = "front_right"
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["keyed_poly"] = None  # 几何对象不序列化
        return d


def generate_pallet_keying(
    outer_poly: Polygon,
    params: PalletKeyingParams | None = None,
) -> PalletKeyingResult:
    """在治具外形指定角切除 45° 非对称方向键倒角，返回新外形与切角线段。"""
    p = params or PalletKeyingParams()
    c = max(5.0, float(p.chamfer_mm))
    ox0, oy0, ox1, oy1 = outer_poly.bounds

    # 切角点序：按角位置替换对应外角顶点为两个斜切点
    if p.corner == "front_right":
        pts = [(ox0, oy0), (ox1 - c, oy0), (ox1, oy0 + c), (ox1, oy1), (ox0, oy1)]
    elif p.corner == "front_left":
        pts = [(ox0 + c, oy0), (ox1, oy0), (ox1, oy1), (ox0, oy1), (ox0, oy0 + c)]
    elif p.corner == "back_right":
        pts = [(ox0, oy0), (ox1, oy0), (ox1, oy1 - c), (ox1 - c, oy1), (ox0, oy1)]
    else:  # back_left
        pts = [(ox0, oy0), (ox1, oy0), (ox1, oy1), (ox0 + c, oy1), (ox0, oy1 - c)]

    keyed = Polygon(pts)
    if not keyed.is_valid:
        keyed = outer_poly

    # 切角斜边线段（进入 CNC 刀路与 DXF 防呆图层）
    idx_map = {
        "front_right": [(1, 2)],
        "front_left": [(4, 0)],
        "back_right": [(2, 3)],
        "back_left": [(3, 4)],
    }
    coords = list(keyed.exterior.coords)
    chamfer_lines = []
    for i, j in idx_map.get(p.corner, [(1, 2)]):
        if j < len(coords):
            chamfer_lines.append(((coords[i][0], coords[i][1]), (coords[j][0], coords[j][1])))

    return PalletKeyingResult(
        keyed_poly=keyed,
        chamfer_lines=chamfer_lines,
        chamfer_mm=c,
        corner=p.corner,
        stats={
            "chamfer_mm": c,
            "corner": p.corner,
            "area_removed_mm2": round(outer_poly.area - keyed.area, 1),
        },
    )


def export_pallet_keying_to_dxf(msp, result: PalletKeyingResult) -> None:
    """输出方向键切角轮廓与工程注记到 DXF 专用图层「防呆切角」。"""
    layer_name = "防呆切角"

    if result.keyed_poly and not result.keyed_poly.is_empty:
        msp.add_lwpolyline(list(result.keyed_poly.exterior.coords), close=True, dxfattribs={"layer": layer_name})

    for p1, p2 in result.chamfer_lines:
        msp.add_line(p1, p2, dxfattribs={"layer": layer_name})

    if result.chamfer_lines:
        (x1, y1), (x2, y2) = result.chamfer_lines[0]
        msp.add_text(
            f"ORIENTATION KEY {result.chamfer_mm:g}x{result.chamfer_mm:g} ({result.corner})",
            dxfattribs={"layer": layer_name, "height": 2.5, "insert": ((x1 + x2) / 2 + 2.0, (y1 + y2) / 2)},
        )
