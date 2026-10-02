"""拼版阵列（Panelization）引擎——小治具多片板一次过波峰。

工业背景（出处见 drc.py 头注与 README「拼版」节）：
- 小尺寸 PCB 逐片过波效率低、治具开模成本高，行业惯例是一套治具放 2×2 / 2×3 阵列
  （Macaos Solder Pallet Designer 内置 Panelizer 同款能力）。
- 片间距 ≥5mm（挡锡墙），阵列后治具总宽不得超过波峰焊轨道上限（DRC RAIL_WIDTH_OVERFLOW）。

实现方式：先生成单片全部几何（沉板/避位/上锡/销/压扣/狗骨头），再按 (dx, dy) 平移复制
N×M 份并重建外形与取手——几何一致性由单一数据源保证。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

log = logging.getLogger("fixture-panelize")

DEFAULT_PANEL_GAP = 5.0  # 片间距 mm（挡锡墙）
MIN_PANEL_GAP = 3.0  # 行业下限：低于 3mm 挡锡墙易挂锡


@dataclass
class PanelGrid:
    """拼版网格描述。"""

    cols: int
    rows: int
    gap: float
    offsets: list[tuple[float, float]]  # 每片原点偏移 (dx, dy)
    unit_w: float  # 单片占位宽（含间距）
    unit_h: float
    total_w: float  # 阵列总占位
    total_h: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "cols": self.cols,
            "rows": self.rows,
            "gap": self.gap,
            "copies": len(self.offsets),
            "unit": [round(self.unit_w, 2), round(self.unit_h, 2)],
            "total": [round(self.total_w, 2), round(self.total_h, 2)],
        }


def build_grid(
    board_bounds: tuple[float, float, float, float],
    cols: int,
    rows: int,
    gap: float = DEFAULT_PANEL_GAP,
) -> PanelGrid:
    """由单片外形 bounds 生成 N×M 平移网格。cols/rows <1 按 1 处理。"""
    cols = max(int(cols), 1)
    rows = max(int(rows), 1)
    gap = max(float(gap), 0.0)
    minx, miny, maxx, maxy = board_bounds
    w, h = maxx - minx, maxy - miny
    # 复制时以原点为基准平移，第 (i, j) 片偏移 = (i*(w+gap), j*(h+gap))
    # 同时整体回移，使阵列原点回到单片原位置（下游 bounds/外形逻辑不变）
    offsets = []
    for j in range(rows):
        for i in range(cols):
            dx = i * (w + gap)
            dy = j * (h + gap)
            offsets.append((dx, dy))
    total_w = cols * w + (cols - 1) * gap
    total_h = rows * h + (rows - 1) * gap
    return PanelGrid(
        cols=cols,
        rows=rows,
        gap=gap,
        offsets=offsets,
        unit_w=w,
        unit_h=h,
        total_w=total_w,
        total_h=total_h,
    )


def _shift_geom(geom, dx: float, dy: float):
    """平移任意 shapely 几何（Polygon/MultiPolygon/LineString）。"""
    return _apply_translation(geom, dx, dy)


def _apply_translation(geom, dx: float, dy: float):
    """shapely 2.x 通用平移（支持 Polygon/MultiPolygon/LineString/LinearRing）。"""
    if geom is None:
        return None
    from shapely.affinity import translate

    return translate(geom, xoff=dx, yoff=dy)


def panelize_geometry(
    board_bounds,
    sink,
    avoid_polys: list,
    solder_polys: list,
    cap_holes: list,
    pins: list,
    handles: list,
    screws: list,
    dogbone_corners: list,
    cols: int,
    rows: int,
    gap: float = DEFAULT_PANEL_GAP,
) -> tuple[PanelGrid, Any, list, list, list, list, list, list, list]:
    """把单片整套治具几何按 N×M 复制。

    返回: (grid, paneled_sink, avoid_polys, solder_polys, cap_holes, pins, handles, screws, dogbone_corners)
    - sink 取并集（拼版后多片沉板可能相接触，外形重建需要单一几何）
    - pins/cap_holes/dogbone_corners 为坐标元组/对象，按偏移重建
    - handles/screws 由调用方用拼版后的 sink 重建（位置依赖整体外形）
    """
    grid = build_grid(board_bounds, cols, rows, gap)
    if len(grid.offsets) <= 1:
        return (
            grid,
            sink,
            list(avoid_polys),
            list(solder_polys),
            list(cap_holes),
            list(pins),
            list(handles),
            list(screws),
            list(dogbone_corners),
        )

    sinks, avoids, solders, caps, new_pins, new_handles, new_screws, new_corners = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for dx, dy in grid.offsets:
        sinks.append(_apply_translation(sink, dx, dy))
        avoids.extend(_apply_translation(a, dx, dy) for a in avoid_polys)
        solders.extend(_apply_translation(s, dx, dy) for s in solder_polys)
        caps.extend((x + dx, y + dy, r) for (x, y, r) in cap_holes)
        new_pins.extend((x + dx, y + dy, r) for (x, y, r) in pins)
        new_handles.extend(_apply_translation(h, dx, dy) for h in handles)
        new_screws.extend((x + dx, y + dy) for (x, y) in screws)
        for db in dogbone_corners:
            new_corners.append(_shift_corner(db, dx, dy))

    paneled_sink = unary_union(sinks) if sinks else sink
    log.info(
        f"  拼版 {grid.cols}×{grid.rows}（间距 {grid.gap}mm）→ "
        f"{len(grid.offsets)} 片，总占位 {grid.total_w:.0f}×{grid.total_h:.0f}mm"
    )
    return grid, paneled_sink, avoids, solders, caps, new_pins, new_handles, new_screws, new_corners


def _shift_corner(db, dx: float, dy: float):
    """平移 DogboneCorner（保留原 dataclass 字段语义）。"""
    from dogbone import DogboneCorner

    if isinstance(db, DogboneCorner):
        vx, vy = db.vertex
        cx, cy = db.center
        (x0, y0), (x1, y1) = db.lead_in_line
        return DogboneCorner(
            index=db.index,
            vertex=(vx + dx, vy + dy),
            center=(cx + dx, cy + dy),
            cutter_r=db.cutter_r,
            bisector=db.bisector,
            angle_deg=db.angle_deg,
            style=db.style,
            lead_in_line=((x0 + dx, y0 + dy), (x1 + dx, y1 + dy)),
        )
    # 容错：dict 形式
    if isinstance(db, dict):
        out = dict(db)
        if "vertex" in out:
            out["vertex"] = (out["vertex"][0] + dx, out["vertex"][1] + dy)
        if "center" in out:
            out["center"] = (out["center"][0] + dx, out["center"][1] + dy)
        return out
    return db


def replicate_components(components: list[dict], grid: PanelGrid) -> list[dict]:
    """拼版后复制元件列表（干涉分析用）：每片平移一份，位号加 -Pij 后缀去重。"""
    if len(grid.offsets) <= 1:
        return components
    out = []
    for (dx, dy), tag in zip(grid.offsets, _copy_tags(grid)):
        for c in components:
            cc = dict(c)
            cc["x"] = c["x"] + dx
            cc["y"] = c["y"] + dy
            if len(grid.offsets) > 1:
                cc["ref"] = f"{c['ref']}{tag}"
            out.append(cc)
    return out


def _copy_tags(grid: PanelGrid) -> list[str]:
    tags = []
    for j in range(grid.rows):
        for i in range(grid.cols):
            if len(grid.offsets) == 1:
                tags.append("")
            else:
                tags.append(f"[{i + 1}{j + 1}]")
    return tags


if __name__ == "__main__":
    demo = Polygon([(0, 0), (60, 0), (60, 40), (0, 40)])
    g = build_grid(demo.bounds, 2, 2, 5.0)
    print(g.to_dict())
