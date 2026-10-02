"""
波峰焊治具 AI 设计助手 — Phase 1
PDF 10 步规则前 4 步：沉板区 / 取手位 / 压扣孔 / 定位销 → DXF 输出

输入：Gerber 目录（含外形层 GKO/GM1/Edge_Cuts + 钻孔 DRL）
输出：治具工程图 DXF（分图层：沉板区/取手位/配件层/定位销）

技术栈：gerbonara(解析) + shapely(几何) + ezdxf(DXF)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from gerbonara import ExcellonFile, LayerStack
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fixture")

# ─────────────────────────────────────────────────────────────
# 工艺参数（PDF 需求 + 行业规范核对）
# ─────────────────────────────────────────────────────────────
@dataclass
class FixtureParams:
    # 步骤2: 沉板区
    sink_expand_mm: float = 0.2        # 外形外扩 0.2mm
    sink_fillet_r: float = 1.85        # 清角圆弧 R1.85
    # 步骤3: 取手位
    handle_w: float = 20.0             # 取手长 20mm
    handle_h: float = 40.0             # 取手宽 40mm
    handle_overlap: float = 1.0        # 与沉板区重叠 1mm
    handle_fillet_r: float = 2.0       # 取手倒角 R2
    # 步骤4: 压扣螺丝孔
    screw_d: float = 3.4               # Φ3.4mm
    screw_offset: float = 10.0         # 圆心距沉板区边 10mm
    # 步骤5: 定位销
    pin_inset: float = 0.1             # 钻孔内缩 0.1mm


@dataclass
class FixtureResult:
    board_poly: Polygon | None = None       # 原始外形
    sink_poly: Polygon | None = None        # 沉板区（外扩+清角）
    handles: list[Polygon] = field(default_factory=list)   # 取手位
    screws: list[tuple[float, float]] = field(default_factory=list)  # 压扣孔 (x,y)
    pins: list[tuple[float, float, float]] = field(default_factory=list)  # 定位销 (x,y,r)


# ─────────────────────────────────────────────────────────────
# 步骤 1: 解析 Gerber
# ─────────────────────────────────────────────────────────────
def parse_drills_regex(d: Path) -> list[tuple[float, float, float]]:
    """用正则解析 DRL 钻孔文件（兼容 KiCad 10 的 G85 新语法）。

    优先尝试 gerbonara ExcellonFile（旧格式）；失败（G85 等新语法）
    则正则回退：T<code>C<dia> 孔径表 + X<coord>Y<coord> 坐标行。
    返回 [(x, y, 直径_mm)]
    """
    drills: list[tuple[float, float, float]] = []
    for f in sorted(d.rglob("*")):
        if f.suffix.lower() not in (".drl", ".txt", ".xln"):
            continue
        try:
            drl = ExcellonFile.open(str(f))
            for obj in drl.objects:
                if obj.__class__.__name__ == "Flash":
                    dia = obj.aperture.diameter  # mm
                    drills.append((float(obj.x), float(obj.y), float(dia)))
            continue  # gerbonara 成功，跳过正则
        except Exception as e:
            log.warning(f"  钻孔 {f.name} gerbonara 失败，正则回退: {e}")
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
            # 单位判断：文件头 METRIC/INCH（KiCad 默认 METRIC）
            is_metric = "METRIC" in raw.upper() or "M71" in raw.upper()
            is_inch = ("INCH" in raw.upper() or "M72" in raw.upper()) and not is_metric
            # 孔径表: T1C0.8 / T1C0.0300（英寸值很小如 0.03 → *25.4）
            ap_sizes = {}
            for m in re.finditer(r"T(\d+)C([0-9.]+)", raw):
                val = float(m.group(2))
                if is_inch:
                    ap_sizes[int(m.group(1))] = val * 25.4
                elif is_metric:
                    ap_sizes[int(m.group(1))] = val
                else:
                    # 无声明：英寸值通常 <3（0.03-0.1"），mm 值通常 >0.2
                    ap_sizes[int(m.group(1))] = val * 25.4 if val < 0.2 else val
            # G85 多段钻孔: X..Y.. X..Y.. G85X..Y..
            # KiCad 10 的 "T" 行切孔径，坐标行可能一次多个 X/Y
            cur_t = None
            for line in raw.splitlines():
                tm = re.match(r"\s*T(\d+)", line)
                if tm:
                    cur_t = int(tm.group(1))
                for m in re.finditer(r"X(-?[\d.]+)Y(-?[\d.]+)", line):
                    x, y = float(m.group(1)), float(m.group(2))
                    # KiCad 10 导出单位 mm（M71 或 header），坐标通常几百 mm
                    # 英寸板坐标会 >1000mm，若都大则按下/25.4 处理
                    if abs(x) > 600 or abs(y) > 600:
                        x, y = x / 25.4, y / 25.4  # 英寸→mm
                    dia = (ap_sizes.get(cur_t, 1.0) if cur_t else 1.0)
                    drills.append((x, y, dia))
        except Exception as e2:
            log.warning(f"  钻孔 {f.name} 正则回退也失败: {e2}")
    # 去重（同一孔可能被多段指令重复）
    seen = set()
    dedup = []
    for x, y, dia in drills:
        key = (round(x, 3), round(y, 3))
        if key not in seen:
            seen.add(key)
            dedup.append((x, y, dia))
    if len(dedup) != len(drills):
        log.info(f"  钻孔去重: {len(drills)} -> {len(dedup)}")
    return dedup


def parse_gerber(gerber_dir: str) -> tuple[list[Polygon], list[tuple[float, float, float]]]:
    """解析 Gerber 目录 → (外形多边形列表, 钻孔列表[(x,y,r)])"""
    d = Path(gerber_dir)
    # ⚠️ 排除 .drl/.txt DRL 文件——KiCad 10 的 G85 新语法会让 gerbonara 崩，
    #    钻孔单独用 _parse_drills_regex 处理
    gerber_files = [f for f in d.rglob("*")
                    if f.suffix.lower() in (".gbr", ".ger", ".gba", ".gbl", ".gbs", ".gbo",
                                             ".gtl", ".gts", ".gto", ".gtp", ".gbp",
                                             ".gm1", ".g2", ".g3", ".gko")]
    stack = None
    if gerber_files:
        # 同一逻辑层的重复文件（真实板常见：01_board_outline.GBR + 02_board_outline.GER
        # + Gerber_BoardOutline.GKO 三份等价外形）会让 gerbonara 抛 Ambiguous layer names。
        # 去重策略：同语义前缀只保留一份（优先 .gko > .gm1 > .gbr > .ger）。
        def _layer_key(p: Path):
            stem = p.stem.lower()
            if "outline" in stem or "edge" in stem:
                return ("outline",)
            return (stem,)

        def _pref(p: Path) -> int:
            order = {".gko": 0, ".gm1": 1, ".gbr": 2, ".ger": 3}
            return order.get(p.suffix.lower(), 9)

        dedup: dict[tuple, Path] = {}
        for f in gerber_files:
            k = _layer_key(f)
            if k not in dedup or _pref(f) < _pref(dedup[k]):
                dedup[k] = f
        gerber_files = sorted(dedup.values())
        log.info(f"  层文件去重: {len(gerber_files)} 份 → {[f.name for f in gerber_files]}")
        try:
            # gerbonara 的 overrides 语义：{正则(全名匹配): 层名字符串}。
            # 覆盖三类来源的命名（KiCad / EasyEDA / 通用后缀）。
            OVERRIDES = {
                r"(?i).*Edge_Cuts.*": "top silk",  # KiCad Edge_Cuts 惯例挂顶层，本体由 polygons 提取
                r"(?i).*\.gm1": "outline",
                r"(?i).*\.gko": "outline",
                r"(?i).*outline.*\.ger": "outline",
                r"(?i).*outline.*\.gbr": "outline",
                r"(?i).*B_Cu.*": "bottom copper",
                r"(?i).*F_Cu.*": "top copper",
                r"(?i).*B_Mask.*": "bottom mask",
                r"(?i).*F_Mask.*": "top mask",
                r"(?i).*B_Silkscreen.*": "bottom silk",
                r"(?i).*F_Silkscreen.*": "top silk",
            }
            stack = LayerStack.from_files(gerber_files, overrides=OVERRIDES, autoguess=False)
        except Exception as e:
            log.warning(f"  from_files 失败({e})，退 open_dir")
    else:
        log.warning("  无 Gerber 文件(.gbr 等)，改试 open_dir")
    if stack is None:
        try:
            stack = LayerStack.open_dir(str(d))
        except Exception as e:
            log.warning(f"  open_dir 失败: {e}")
            stack = None

    # 外形：从 outline 图形对象构建 shapely 多边形
    board_polys = []
    outline_objs = []
    if stack is None:
        log.warning("  ⚠️ stack 解析失败（可能目录无 Gerber 文件或格式不支持），跳过外形")
        return board_polys, parse_drills_regex(d)
    # 优先直接读 ('outline','') 图形层的对象——overrides 指定后 st.outline 属性仍为 None，
    # 只有 graphic_layers 里才有真实对象（gerbonara 的 outline 属性仅自动识别时填充）
    try:
        ol_layer = stack.graphic_layers.get(("outline", ""))
        if ol_layer is not None and list(ol_layer.objects):
            outline_objs = list(ol_layer.objects)
    except Exception as e:
        log.debug("graphic_layers 读取失败: %s", e)
    if not outline_objs:
        try:
            op = stack.outline_polygons() if callable(stack.outline_polygons) else stack.outline_polygons
            if op is not None:
                for chunk in op:
                    if isinstance(chunk, list):
                        outline_objs.extend(chunk)
                    else:
                        outline_objs.append(chunk)
        except Exception as e:
            log.warning(f"  outline_polygons 失败({e})，退回 stack.outline")
    if not outline_objs:
        try:
            outline_objs = list(stack.outline.objects) if stack.outline is not None else []
        except Exception:
            outline_objs = []

    # Line/Arc → 线段集合 → shapely LineString → 围成 Polygon
    from shapely.geometry import LineString
    lines = []
    for obj in outline_objs:
        cls = obj.__class__.__name__
        if cls == "Line":
            lines.append(LineString([(obj.x1, obj.y1), (obj.x2, obj.y2)]))
        elif cls == "Arc":
            # Arc 近似为多段线
            try:
                approx = obj.approximate(max_error=0.01)
                pts = [(a.x1, a.y1) for a in approx] + [(approx[-1].x2, approx[-1].y2)]
                lines.append(LineString(pts))
            except Exception as e:
                log.debug("Arc 近似失败 %s: %s", getattr(obj, "ref", "?"), e)
        elif cls == "Region":
            try:
                pts = [(v.x, v.y) for v in obj.vertices]
                if len(pts) >= 3:
                    board_polys.append(Polygon(pts))
            except Exception as e:
                log.debug("Region 顶点解析失败 %s: %s", getattr(obj, "ref", "?"), e)

    if lines and not board_polys:
        # 真实板的外形线段常有微缺口（本例 0.127mm：圆角端点 vs 直角端点）。
        # 工业级做法：端点链式追踪（endpoint chaining）——按「上一段终点≈下一段起点」
        # 串成有序闭合环，比 buffer/snap 更精确且能容忍小缺口。
        try:
            from shapely.ops import polygonize

            segs = [(tuple(l.coords[0]), tuple(l.coords[-1])) for l in lines]
            used = [False] * len(segs)
            chains: list[list[tuple]] = []
            tolerance = 0.5  # mm，覆盖实测 0.127mm 缺口与常见导出误差

            for start_i in range(len(segs)):
                if used[start_i]:
                    continue
                chain = [segs[start_i][0], segs[start_i][1]]
                used[start_i] = True
                extended = True
                while extended and len(chain) < len(segs) + 2:
                    extended = False
                    tail = chain[-1]
                    for j, (s0, s1) in enumerate(segs):
                        if used[j]:
                            continue
                        d0 = ((tail[0] - s0[0]) ** 2 + (tail[1] - s0[1]) ** 2) ** 0.5
                        d1 = ((tail[0] - s1[0]) ** 2 + (tail[1] - s1[1]) ** 2) ** 0.5
                        if d0 <= tolerance:
                            chain.append(s1)
                            used[j] = True
                            extended = True
                            break
                        if d1 <= tolerance:
                            chain.append(s0)
                            used[j] = True
                            extended = True
                            break
                if len(chain) >= 4:
                    gap = ((chain[-1][0] - chain[0][0]) ** 2 + (chain[-1][1] - chain[0][1]) ** 2) ** 0.5
                    if gap <= tolerance:
                        if gap > 0:  # 显式首尾闭合，消除微缺口
                            chain.append(chain[0])
                        try:
                            poly = Polygon(chain)
                            if poly.is_valid and poly.area > 0.01:
                                chains.append(chain)
                                board_polys.append(poly)
                        except Exception as e:
                            log.debug("构环失败: %s", e)

            if board_polys:
                best = max(board_polys, key=lambda p: p.area)
                board_polys = [best]
                log.info(f"  外形端点链式闭合成功 → 面积 {best.area:.1f} mm²")
            else:
                # 兜底：polygonize + 最大面
                merged = unary_union(lines)
                found = [p for p in polygonize([merged]) if p.is_valid and p.area > 0.01]
                if found:
                    board_polys = [max(found, key=lambda p: p.area)]
                    log.info(f"  外形 polygonize 兜底 → 面积 {board_polys[0].area:.1f} mm²")
                else:
                    log.warning("  外形围合失败：未能形成有效闭合环")
        except Exception as e:
            log.warning(f"  线段围合失败: {e}")

    # 钻孔：找 .drl/.txt/.xln 文件
    drills = parse_drills_regex(d)

    return board_polys, drills


# ─────────────────────────────────────────────────────────────
# 步骤 2: 沉板区（外形外扩 0.2mm + R1.85 清角）
# ─────────────────────────────────────────────────────────────
def make_sink_region(board_poly: Polygon, p: FixtureParams) -> Polygon:
    """外形外扩 + 圆角清角"""
    # 外扩 0.2mm（round join 自动圆角）
    expanded = board_poly.buffer(p.sink_expand_mm, join_style="round", quad_segs=16)
    # 再外扩 R1.85 再内缩 R1.85 实现清角圆弧（行业做法：dilate-erode 出圆角）
    filleted = expanded.buffer(p.sink_fillet_r, join_style="round", quad_segs=16) \
                       .buffer(-p.sink_fillet_r, join_style="round", quad_segs=16)
    return filleted


# ─────────────────────────────────────────────────────────────
# 步骤 3: 取手位（左右 20×40mm，重叠 1mm，R2 倒角）
# ─────────────────────────────────────────────────────────────
def make_handles(sink_poly: Polygon, p: FixtureParams) -> list[Polygon]:
    """沉板区左右各一取手位，紧贴边线，重叠 1mm"""
    minx, miny, maxx, _maxy = sink_poly.bounds
    handles = []

    for side in ("left", "right"):
        if side == "left":
            h = box(minx - p.handle_w + p.handle_overlap, miny - p.handle_h / 2,
                    minx + p.handle_overlap, miny + p.handle_h / 2)
        else:
            h = box(maxx - p.handle_overlap, miny - p.handle_h / 2,
                    maxx + p.handle_w - p.handle_overlap, miny + p.handle_h / 2)
        # 四角倒角 R2
        r = p.handle_fillet_r
        h_r = h.buffer(r, join_style="round", quad_segs=16).buffer(-r, join_style="round", quad_segs=16)
        handles.append(h_r)

    return handles


# ─────────────────────────────────────────────────────────────
# 步骤 4: 压扣螺丝孔（四角 Φ3.4，圆心距边 10mm）
# ─────────────────────────────────────────────────────────────
def make_screws(sink_poly: Polygon, p: FixtureParams) -> list[tuple[float, float]]:
    """沉板区四角**外侧**放压扣螺丝孔（压扣用于压住 PCB 边缘，孔必须在板区之外）。

    几何语义（对标竞品 generator._clamp_holes）：沿 x/y 各向外偏移 offset，
    即 (min ± offset, min ± offset) 四种组合——孔落在沉板区对角外侧的治具体上。
    """
    minx, miny, maxx, maxy = sink_poly.bounds
    cx = p.screw_offset
    corners = [
        (minx - cx, miny - cx),
        (maxx + cx, miny - cx),
        (minx - cx, maxy + cx),
        (maxx + cx, maxy + cx),
    ]
    return corners


# ─────────────────────────────────────────────────────────────
# 步骤 5: 定位销（钻孔内缩 0.1mm 生成销钉圆）
# ─────────────────────────────────────────────────────────────
def make_pins(drills: list[tuple[float, float, float]], p: FixtureParams,
              sink_poly: Polygon | None = None, *, select: bool = True) -> list[tuple[float, float, float]]:
    """定位销：从钻孔中**打分选出对角最优的一对**（而非把所有孔都变成销）。

    设计依据（对标竞品 generator._locating_pin_candidates 的「候选→打分→选中」三段式）：
    - 把全部钻孔都当销钉会污染避位区（DRC 报 PIN_IN_AVOID）且无工艺意义（100+ 个销）
    - 真实做法：按孔径窗口/靠边/NPTH 打分，取对角线跨距最大的一对，保证 PCB 定位刚度

    select=False 退回旧行为（全部钻孔，向后兼容与调试用）。
    """
    if not select:
        pins = []
        for x, y, dia in drills:
            if dia > 0:
                r = dia / 2 - p.pin_inset
                if r > 0:
                    pins.append((x, y, r))
        return pins

    if sink_poly is not None:
        bounds = sink_poly.bounds
    elif drills:
        xs = [d[0] for d in drills]
        ys = [d[1] for d in drills]
        pad = 20.0
        bounds = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    else:
        return []

    from pin_select import select_locating_pins

    chosen = select_locating_pins(drills, bounds)
    pins = [(c.x, c.y, c.dia / 2 - p.pin_inset) for c in chosen if c.dia / 2 - p.pin_inset > 0]

    if not pins and drills:
        # 无合格候选（孔径都不在窗口内）→ 退回：取最大孔径里对角跨距最大的两个
        log.warning("  无合格定位销候选（孔径不在 2.5-4.5mm 窗口且非 NPTH），退回对角最大跨距")
        import itertools

        ordered = sorted(drills, key=lambda d: -d[2])[:10]
        best, bd = None, -1.0
        for a, b in itertools.combinations(ordered, 2):
            dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
            if dist > bd:
                bd, best = dist, (a, b)
        if best:
            pins = [(x, y, max(dia / 2 - p.pin_inset, 0.5)) for x, y, dia in best]
    log.info(f"  定位销: 选中 {len(pins)} 个（候选钻孔 {len(drills)} 个）")
    return pins


# ─────────────────────────────────────────────────────────────
# DXF 输出（分图层）
# ─────────────────────────────────────────────────────────────
LAYER_COLORS = {
    "沉板区": 1,      # 红
    "取手位": 3,      # 绿
    "配件层": 4,      # 青
    "定位销": 5,      # 蓝
}

def poly_to_dxf_polyline(msp, poly: Polygon, layer: str, close: bool = True):
    """shapely Polygon → DXF POLYLINE"""
    if poly.is_empty:
        return
    if poly.geom_type == "MultiPolygon":
        for sub in poly.geoms:
            poly_to_dxf_polyline(msp, sub, layer)
        return
    coords = list(poly.exterior.coords)
    # LWPOLYLINE 用 flags 控制闭合（1=闭合）
    msp.add_lwpolyline(coords, dxfattribs={"layer": layer, "flags": 1 if close else 0})


def export_dxf(result: FixtureResult, out_path: str, params: FixtureParams):
    """生成治具工程图 DXF"""
    out_path = str(Path(out_path))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    for name, color in LAYER_COLORS.items():
        doc.layers.add(name, color=color)

    msp = doc.modelspace()

    if result.sink_poly:
        poly_to_dxf_polyline(msp, result.sink_poly, "沉板区")

    for h in result.handles:
        poly_to_dxf_polyline(msp, h, "取手位")

    for x, y in result.screws:
        msp.add_circle((x, y), radius=params.screw_d / 2, dxfattribs={"layer": "配件层"})

    for x, y, r in result.pins:
        msp.add_circle((x, y), radius=r, dxfattribs={"layer": "定位销"})

    doc.saveas(out_path)
    log.info(f"✅ DXF 已输出: {out_path}")


# ─────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────
def run(gerber_dir: str, out_dxf: str, params: FixtureParams | None = None) -> FixtureResult:
    params = params or FixtureParams()
    log.info(f"📂 解析 Gerber: {gerber_dir}")

    board_polys, drills = parse_gerber(gerber_dir)
    if not board_polys:
        log.error("❌ 未找到外形层（GKO/GM1/Edge_Cuts）")
        return FixtureResult()
    board = unary_union(board_polys)
    log.info(f"  外形: {len(board_polys)} 个多边形, 尺寸 {board.bounds[2]-board.bounds[0]:.1f}x{board.bounds[3]-board.bounds[1]:.1f}mm")
    log.info(f"  钻孔: {len(drills)} 个")

    # 步骤2: 沉板区
    sink = make_sink_region(board, params)
    log.info(f"  步骤2 沉板区: 外扩{params.sink_expand_mm}mm + 清角R{params.sink_fillet_r}")

    # 步骤3: 取手位
    handles = make_handles(sink, params)
    log.info(f"  步骤3 取手位: {len(handles)} 个")

    # 步骤4: 压扣螺丝孔
    screws = make_screws(sink, params)
    log.info(f"  步骤4 压扣孔: {len(screws)} 个")

    # 步骤5: 定位销
    pins = make_pins(drills, params, sink_poly=sink)
    log.info(f"  步骤5 定位销: {len(pins)} 个")

    result = FixtureResult(board_poly=board, sink_poly=sink, handles=handles,
                           screws=screws, pins=pins)

    if out_dxf:
        export_dxf(result, out_dxf, params)

    return result


def main():
    ap = argparse.ArgumentParser(description="波峰焊治具 AI 设计助手 Phase 1")
    ap.add_argument("gerber_dir", help="Gerber 文件目录")
    ap.add_argument("-o", "--out", default="fixture.dxf", help="输出 DXF 路径")
    args = ap.parse_args()
    run(args.gerber_dir, args.out)


if __name__ == "__main__":
    sys.exit(main())
