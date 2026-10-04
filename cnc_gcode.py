"""CNC G 代码直出——把治具几何直接变成机床可执行的 .nc 程序。

工业定位：商业治具软件（Macaos Solder Pallet Designer €1500/年模块）的交付闭环是
「设计 → 机加工文件」。本模块补齐 wave-fixture-ai 的最后一公里：DXF 之外直接输出
RS-274 G 代码（mm/G21 绝对坐标），覆盖治具全部加工特征：

  1. T 钻孔组：定位销孔（分段模拟啄钻，按孔径分组自动换刀）
  2. 挖腔组：避位区 / 上锡区 / 盖板孔 / 沉板槽 / 取手位
     （行距光栅粗铣 + 轮廓精铣壁，分层切深按材料预设）
  3. 外形铣：治具外轮廓整体落料（刀具中心内缩 tool_r，切边落在边界上）

工艺语义（与 drc.py / README 工业规则一致）：
  - 沉板槽深度 = board_thickness + 0.3（PCB 沉入后顶面近齐平，底面留 0.5mm 离板隙）
  - 避位区 / 上锡区 / 取手位 = 贯穿切（深度 = 板厚 + 1mm 破底）
  - 坐标系：治具 DXF 同坐标（mm），Z0 = 治具顶面，负向进刀

安全：输出路径统一经 resolve + 白名单后缀校验，禁止越出指定父目录。
"""

from __future__ import annotations

import logging
import math
import time as _time
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import LineString, Polygon

from materials import MaterialPreset, get_material

log = logging.getLogger("fixture-gcode")

SAFE_Z = 5.0  # 安全高度 mm
RAPID_MM_MIN = 3000.0  # G0 估算速度（时间估算用）
TOOL_CHANGE_S = 6.0  # 换刀耗时（时间估算用）
BOARD_DEPTH_CLEARANCE = 0.3  # 沉板槽底部余隙
BREAK_THROUGH = 1.0  # 贯穿切破底量

ALLOWED_SUFFIXES = {".nc", ".gcode", ".tap", ".txt", ".cnc"}


def resolve_safe_out_path(out_path: str | Path, parent_hint: str | Path | None = None) -> Path:
    """规范化输出路径：绝对化 + 后缀白名单 +（提供父目录时）包含性校验。"""
    p = Path(out_path).resolve()
    if p.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"G 代码输出后缀须为 {sorted(ALLOWED_SUFFIXES)}，收到: {p.suffix!r}")
    if parent_hint is not None:
        base = Path(parent_hint).resolve()
        if not p.is_relative_to(base):
            raise ValueError("G 代码输出路径越出允许目录")
    return p


@dataclass
class ToolInfo:
    number: int
    kind: str  # "drill" | "endmill"
    dia_mm: float
    feed_xy: float
    feed_z: float
    rpm: float


class GCodeBuilder:
    """轻量 G 代码文本构造器（RS-274, mm/G21 绝对坐标）。"""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.path_len: float = 0.0  # G1 切削路径累计 mm
        self.rapid_len: float = 0.0  # G0 快移累计 mm
        self.feed_time_min: float = 0.0  # 切削耗时累计 min
        self._pos: tuple[float, float, float] | None = None
        self._feed: float = 0.0

    def comment(self, text: str) -> None:
        import unicodedata

        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        safe = ascii_text.replace("(", "[").replace(")", "]")
        self.lines.append(f"({safe})")

    def raw(self, line: str) -> None:
        self.lines.append(line)

    def rapid(self, x: float, y: float, z: float | None = None) -> None:
        cmd = f"G0 X{_fmt(x)} Y{_fmt(y)}"
        if z is not None:
            cmd += f" Z{_fmt(z)}"
        self.lines.append(cmd)
        if self._pos is not None:
            dx, dy = x - self._pos[0], y - self._pos[1]
            dz = (z if z is not None else self._pos[2]) - self._pos[2]
            self.rapid_len += math.sqrt(dx * dx + dy * dy + dz * dz)
        self._pos = (x, y, z if z is not None else (self._pos[2] if self._pos else z))

    def feed_to(
        self, x: float, y: float, z: float | None = None, feed: float | None = None
    ) -> None:
        f = feed if feed is not None else self._feed
        cmd = f"G1 X{_fmt(x)} Y{_fmt(y)}"
        if z is not None:
            cmd += f" Z{_fmt(z)}"
        if f:
            cmd += f" F{_fmt(f)}"
        self.lines.append(cmd)
        if self._pos is not None:
            dx, dy = x - self._pos[0], y - self._pos[1]
            dz = (z if z is not None else self._pos[2]) - self._pos[2]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            self.path_len += dist
            effective_feed = f if f > 0 else 600.0
            self.feed_time_min += dist / effective_feed
        self._pos = (x, y, z if z is not None else (self._pos[2] if self._pos else z))
        if feed:
            self._feed = feed

    def stats(self, tool_change_count: int = 0) -> dict:
        t_rapid = self.rapid_len / RAPID_MM_MIN
        t_tools = tool_change_count * TOOL_CHANGE_S / 60.0
        return {
            "cut_len_mm": round(self.path_len, 1),
            "rapid_len_mm": round(self.rapid_len, 1),
            "machining_minutes": round(self.feed_time_min + t_rapid + t_tools, 1),
        }


def _fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


def raster_passes(poly: Polygon, tool_r: float, stepover: float) -> list[list[tuple[float, float]]]:
    """区域光栅刀路：水平扫描线与内缩区域求交，蛇形排序。"""
    inner = poly.buffer(-tool_r * 0.98)  # 留 2% 余量给精铣壁
    if inner.is_empty or inner.area <= 0:
        return []
    minx, miny, maxx, maxy = inner.bounds
    rows: list[list[tuple[float, float]]] = []
    y = miny + stepover / 2.0
    while y <= maxy + 1e-6:
        scan = LineString([(minx - 1.0, y), (maxx + 1.0, y)])
        inter = scan.intersection(inner)
        segs = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
        for s in segs:
            if isinstance(s, LineString) and s.length > 0.05:
                rows.append([(round(cx, 3), round(cy, 3)) for cx, cy in s.coords])
        y += stepover
    # 蛇形：奇数行反转，减少抬刀空程
    return [list(reversed(pts)) if i % 2 else pts for i, pts in enumerate(rows)]


def contour_ring(poly: Polygon, tool_r: float) -> list[tuple[float, float]]:
    """轮廓精铣刀路：区域边界内缩 tool_r 的外环。"""
    inner = poly.buffer(-tool_r)
    if inner.is_empty or inner.area <= 0 or not isinstance(inner, Polygon):
        return []
    return [(round(cx, 3), round(cy, 3)) for cx, cy in inner.exterior.coords]


def _emit_pocket(
    b: GCodeBuilder,
    poly: Polygon,
    depth: float,
    tool: ToolInfo,
    mat: MaterialPreset,
    stepover: float,
) -> int:
    """单个挖腔：分层（粗铣 raster + 每层轮廓）→ 返回执行环数。"""
    raster = raster_passes(poly, tool.dia_mm / 2.0, stepover)
    ring = contour_ring(poly, tool.dia_mm / 2.0)
    if not raster and not ring:
        return 0
    passes = 0
    z = 0.0
    while z > -depth + 1e-9:
        z = max(z - mat.stepdown_mm, -depth)
        # 每层粗铣
        for pts in raster:
            x0, y0 = pts[0]
            b.rapid(x0, y0, SAFE_Z)
            b.rapid(x0, y0, z + 0.5)
            b.feed_to(x0, y0, z, feed=tool.feed_z)  # 下刀
            for px, py in pts[1:]:
                b.feed_to(px, py, z, feed=tool.feed_xy)
            b.rapid(x0, y0, SAFE_Z)
            passes += 1
        # 每层轮廓精铣
        if ring and len(ring) > 2:
            cx, cy = ring[0]
            b.rapid(cx, cy, SAFE_Z)
            b.rapid(cx, cy, z + 0.5)
            b.feed_to(cx, cy, z, feed=tool.feed_z)
            for px, py in ring[1:]:
                b.feed_to(px, py, z, feed=tool.feed_xy)
            b.rapid(cx, cy, SAFE_Z)
            passes += 1
    return passes


def _emit_helical_bore(
    b: GCodeBuilder,
    cx: float,
    cy: float,
    hole_r: float,
    depth: float,
    tool: ToolInfo,
    mat: MaterialPreset,
) -> int:
    """圆形孔螺旋铣孔（孔径 > 刀径）：刀心绕孔心做螺旋下降。"""
    path_r = hole_r - tool.dia_mm / 2.0
    if path_r <= 0.2:
        # 孔径接近刀径：中心直落下刀（小孔，合成石可承受）
        b.rapid(cx, cy, SAFE_Z)
        b.rapid(cx, cy, 0.5)
        b.feed_to(cx, cy, -depth, feed=tool.feed_z)
        b.rapid(cx, cy, SAFE_Z)
        return 1
    z = 0.0
    revolutions = 0
    while z > -depth + 1e-9:
        layer = min(mat.stepdown_mm, z + depth)
        if layer <= 1e-9:
            break
        z_target = max(-depth, z - layer)
        steps = max(int(16 * (layer / 0.5)) if layer > 0 else 16, 16)
        b.rapid(cx + path_r, cy, SAFE_Z)
        b.rapid(cx + path_r, cy, z + 0.5)
        b.feed_to(cx + path_r, cy, z, feed=tool.feed_z)
        for s in range(1, steps + 1):
            ang = 2 * math.pi * s / steps
            zt = z + (z_target - z) * s / steps
            b.feed_to(
                cx + path_r * math.cos(ang), cy + path_r * math.sin(ang), zt, feed=tool.feed_xy
            )
            revolutions += 1
        z = z_target
    b.rapid(cx + path_r, cy, SAFE_Z)
    return max(revolutions // 16, 1)


def generate_gcode(
    sink,
    avoid_polys: list,
    solder_polys: list,
    cap_holes: list,
    pins: list,
    handles: list,
    outer_poly,
    out_path: str,
    material_key: str = "durostone",
    pallet_thickness: float = 10.0,
    board_thickness: float = 1.6,
    sink_depth: float | None = None,
    vent_holes: list | None = None,
    endmill_dia: float = 3.7,
    job_name: str = "wave-fixture",
    parent_hint: str | Path | None = None,
) -> dict:
    """生成完整治具加工 G 代码。返回统计 dict（含加工时长估算）。

    sink_depth: 沉板槽深（mm）。None 时按 board_thickness + 0.3 旧公式；
    推荐由 interference.compute_sink_depth() 按底面元件高度计算后传入
    （底面最高元件 + 0.5mm 离板气隙，AptPCB/PCBSync 公式）。
    vent_holes: 可选排气孔列表 [(x,y,r)]（AGICORP §4.2 导气通道，自动归入钻孔组）。

    加工顺序：钻孔(定位销+排气孔) → 小腔(盖板/上锡/避位) → 沉板槽 → 取手位 → 外形落料。
    """
    safe_out = resolve_safe_out_path(out_path, parent_hint)
    mat = get_material(material_key)
    effective_sink_depth = round(
        sink_depth if sink_depth is not None else board_thickness + BOARD_DEPTH_CLEARANCE, 3
    )
    tool_r = endmill_dia / 2.0
    stepover = endmill_dia * mat.stepover_pct / 100.0

    b = GCodeBuilder()

    # ── 程序头 ────────────────────────────────────────────────
    b.comment(f"Wave Fixture AI CNC program: {job_name}")
    b.comment(f"Generated: {_time.strftime('%Y-%m-%d %H:%M:%S')}")
    b.comment(
        f"Material: {mat.name_en} (key={mat.key}) rho={mat.density_g_cm3}g/cm3 Tmax={mat.max_service_temp_c}C"
    )
    b.comment(
        f"Pallet thickness: {pallet_thickness}mm  Board pocket depth: {effective_sink_depth}mm"
    )
    b.comment("Units: mm (G21)  Abs (G90)  WCS G54  Z0 = pallet top face")
    b.comment("NOTE: plunge is straight-down; swap to helical ramp if material chipping observed")
    b.comment("NOTE: dust extraction required for synthetic stone machining")
    b.comment("Tools: see T commands below")

    # ── T1..Tn 钻孔组（定位销 + 闭合避位腔排气孔，按孔径分组）──────────────────
    tool_no = 1
    pin_groups: dict[float, list[tuple[float, float]]] = {}
    all_drills = list(pins) + list(vent_holes or [])
    for x, y, r in all_drills:
        pin_groups.setdefault(round(2 * r, 2), []).append((x, y))

    drill_tools: list[ToolInfo] = []
    for dia in sorted(pin_groups):
        t = ToolInfo(
            number=tool_no,
            kind="drill",
            dia_mm=dia,
            feed_xy=mat.feed_plunge_mm_min,
            feed_z=mat.feed_plunge_mm_min,
            rpm=mat.spindle_rpm,
        )
        drill_tools.append(t)
        tool_no += 1

    endmill = ToolInfo(
        number=tool_no,
        kind="endmill",
        dia_mm=endmill_dia,
        feed_xy=mat.feed_xy_mm_min,
        feed_z=mat.feed_plunge_mm_min,
        rpm=mat.spindle_rpm,
    )

    b.raw("")
    b.comment("=== TOOL CHANGE: drills for locating pins ===")
    drill_depth = -(pallet_thickness + BREAK_THROUGH)
    for t in drill_tools:
        b.raw(f"T{t.number} M6")
        b.raw(f"S{_fmt(t.rpm)} M3")
        b.raw("G54")
        b.raw("G21 G90 G17")
        b.comment(f"T{t.number}: drill D{t.dia_mm}mm F{t.feed_z} Z-depth {drill_depth}")
        for x, y in pin_groups[round(t.dia_mm, 2)]:
            b.rapid(x, y, SAFE_Z)
            b.feed_to(x, y, drill_depth / 2.0, feed=t.feed_z)  # 分两段模拟啄钻
            b.feed_to(x, y, drill_depth, feed=t.feed_z)
            b.rapid(x, y, SAFE_Z)
    if not drill_tools:
        b.comment("(no locating pins - drill group skipped)")

    # ── 挖腔组（统一 endmill）──────────────────────────────────
    b.raw("")
    b.raw(f"T{endmill.number} M6")
    b.raw(f"S{_fmt(endmill.rpm)} M3")
    b.raw("G54 G21 G90 G17")
    b.comment(
        f"T{endmill.number}: endmill D{endmill_dia}mm  Fxy={endmill.feed_xy} Fz={endmill.feed_z}"
    )

    through_depth = pallet_thickness + BREAK_THROUGH
    ops = 0

    # 盖板孔（螺旋铣孔）
    b.comment("=== POCKETS: cap holes (helical bore, through) ===")
    for i, (x, y, r) in enumerate(cap_holes):
        b.comment(f"cap hole #{i + 1} at ({x:.2f}, {y:.2f})")
        ops += _emit_helical_bore(b, x, y, r, through_depth, endmill, mat)

    # 上锡区（贯穿）
    b.comment("=== POCKETS: solder openings (through) ===")
    for i, poly in enumerate(solder_polys):
        if poly is None or poly.is_empty:
            continue
        b.comment(f"solder region #{i + 1} through-cut")
        ops += _emit_pocket(b, poly, through_depth, endmill, mat, stepover)

    # 避位区（贯穿）
    b.comment("=== POCKETS: avoid regions (through) ===")
    for i, poly in enumerate(avoid_polys):
        if poly is None or poly.is_empty:
            continue
        b.comment(f"avoid region #{i + 1} through-cut")
        ops += _emit_pocket(b, poly, through_depth, endmill, mat, stepover)

    # 沉板槽（板厚 + 0.3，不贯穿）
    b.comment(f"=== SINK pocket depth {effective_sink_depth}mm (board sits flush) ===")
    b.comment(
        "NOTE: AGICORP guideline - 60 deg bottom-side chamfers on solder openings "
        "maximize wave contact; add chamfer pass if wave coverage insufficient"
    )
    if sink is not None and not sink.is_empty:
        sink_parts = list(sink.geoms) if hasattr(sink, "geoms") else [sink]
        for i, sp in enumerate(sink_parts):
            b.comment(f"sink part #{i + 1}")
            ops += _emit_pocket(b, sp, effective_sink_depth, endmill, mat, stepover)

    # 取手位（贯穿）
    b.comment("=== HANDLES through-cut ===")
    for i, h in enumerate(handles):
        if h is None or h.is_empty:
            continue
        b.comment(f"handle #{i + 1}")
        ops += _emit_pocket(b, h, through_depth, endmill, mat, stepover)

    # ── 外形落料 ──────────────────────────────────────────────
    b.comment("=== OUTER profile full-depth cut (cutter center inset by tool radius) ===")
    profile_ops = 0
    if outer_poly is not None and not outer_poly.is_empty:
        inner_path = outer_poly.buffer(-tool_r)
        if not inner_path.is_empty and isinstance(inner_path, Polygon):
            pts = [(round(cx, 3), round(cy, 3)) for cx, cy in inner_path.exterior.coords]
            if len(pts) > 2:
                z = 0.0
                while z > -through_depth + 1e-9:
                    z = max(z - mat.stepdown_mm, -through_depth)
                    x0, y0 = pts[0]
                    b.rapid(x0, y0, SAFE_Z)
                    b.rapid(x0, y0, z + 0.5)
                    b.feed_to(x0, y0, z, feed=endmill.feed_z)
                    for px, py in pts[1:]:
                        b.feed_to(px, py, z, feed=endmill.feed_xy)
                    b.feed_to(x0, y0, z, feed=endmill.feed_xy)  # 闭环
                    b.rapid(x0, y0, SAFE_Z)
                    profile_ops += 1

    # ── 程序尾 ────────────────────────────────────────────────
    b.raw("")
    b.raw("M5")
    b.raw("G0 Z50")
    b.raw("M30")
    b.comment("EOF")

    stats = b.stats(tool_change_count=len(drill_tools))
    text = "\n".join(b.lines) + "\n"
    safe_out.write_text(text, encoding="utf-8")

    result = {
        "gcode_path": str(safe_out),
        "material": mat.key,
        "pallet_thickness": pallet_thickness,
        "board_pocket_depth": round(effective_sink_depth, 2),
        "pocket_ops": ops,
        "profile_passes": profile_ops,
        "drill_groups": len(drill_tools),
        "tools": [
            {"number": t.number, "kind": t.kind, "dia_mm": t.dia_mm, "rpm": t.rpm}
            for t in (*drill_tools, endmill)
        ],
        "line_count": len(b.lines),
        **stats,
    }
    log.info(
        f"  G-code 已生成: {safe_out}（{len(b.lines)} 行，"
        f"挖腔 {ops} 环，估时 {stats['machining_minutes']} min）"
    )
    return result
