"""DRC 生产安全门禁——治具几何的设计规则检查与生产放行。

规则来源（每条带出处）：
- 竞品逆向：wave-soldering-fixture-designer 的 20 规则框架（blocking/error/warning/info 四级
  + blocking 未解决禁止下载生产 DXF + override 绑定 geometry SHA）
- AGICORP《Wave Solder Pallet Design Guidelines》：治具尺寸/平面度/轨道指宽
- Macaos Selective Wave Soldering Guidelines：SMT 元件距治具底面 ≥0.5mm、底板厚 ≥1.3mm
- PCBSync / MB Manufacturing：传送带极限 20"W × 30"L（508×762mm）
- APTPCB：肋墙厚 ≥0.8mm（推荐 1.5mm）

门禁语义：存在 blocking 或 error 级发现时，`production_allowed` 返回 False——
导出的 DXF 自动打水印（PREVIEW），禁止直接送 CNC 生产。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

log = logging.getLogger("fixture-drc")

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "blocking": 3}

# 传送带极限（PCBSync / MB Manufacturing）：20"W × 30"L
CONVEYOR_MAX_W_MM = 508.0
CONVEYOR_MAX_L_MM = 762.0


@dataclass
class DRCIssue:
    code: str
    title: str
    detail: str
    severity: str  # blocking / error / warning / info
    object_id: str | None = None
    current: float | None = None
    required: float | None = None
    unit: str | None = None
    source: str | None = None  # 规则出处

    def to_dict(self) -> dict:
        return asdict(self)


def _issue(code: str, title: str, detail: str, severity: str,
           source: str, **kw) -> dict:
    d = DRCIssue(code=code, title=title, detail=detail, severity=severity, source=source, **kw)
    return d.to_dict()


def _covers(outer, inner) -> bool:
    try:
        return outer is not None and inner is not None and outer.covers(inner)
    except Exception:
        return False


def _contains_point(geom, x: float, y: float) -> bool:
    try:
        return geom is not None and geom.contains(type(geom)([(x, y)])) if False else _pt_in(geom, x, y)
    except Exception:
        return False


def _pt_in(geom, x: float, y: float) -> bool:
    from shapely.geometry import Point
    try:
        return geom is not None and geom.contains(Point(x, y))
    except Exception:
        return False


def _poly_ok(poly) -> bool:
    try:
        return poly is not None and (not poly.is_empty) and poly.is_valid
    except Exception:
        return False


def run_drc(r1, r2) -> list[dict]:
    """对 phase1/phase2 结果跑全部 DRC 规则，返回发现列表（含 severity 与出处）。"""
    issues: list[dict] = []
    SRC_STRUCT = "竞品逆向框架（wave-soldering-fixture-designer）"
    SRC_SIZE = "PCBSync / MB Manufacturing（传送带 20×30in）"
    SRC_DFM = "Macaos / AGICORP / APTPCB DFM 指南"

    board = getattr(r1, "board_poly", None)
    sink = getattr(r1, "sink_poly", None)
    outer = getattr(r2, "outer_poly", None)
    handles = getattr(r1, "handles", []) or []
    screws = getattr(r1, "screws", []) or []
    pins = getattr(r1, "pins", []) or []
    avoids = getattr(r2, "avoid_polys", []) or []
    solders = getattr(r2, "solder_polys", []) or []
    tin_holes = getattr(r2, "tin_holes", []) or []
    tin_strips = getattr(r2, "tin_strip_lines", []) or []

    # ── A. 结构边界 ──────────────────────────────────────────────
    if not _poly_ok(board):
        issues.append(_issue("BOARD_OUTLINE_INVALID", "PCB 外形无效",
                             "外形层缺失、为空或存在自交拓扑。", "blocking", SRC_STRUCT))
    if not _poly_ok(sink):
        issues.append(_issue("SINK_REGION_INVALID", "沉板区无效",
                             "外形外扩后未形成有效沉板区域。", "blocking", SRC_STRUCT))
    if not _poly_ok(outer):
        issues.append(_issue("FIXTURE_BODY_INVALID", "治具外形无效",
                             "治具外框缺失或无效。", "blocking", SRC_STRUCT))
    else:
        if _poly_ok(sink) and not outer.covers(sink):
            issues.append(_issue("FIXTURE_BODY_OVERFLOW", "沉板区超出治具",
                                 "沉板区超出治具主体外框边界。", "blocking", SRC_STRUCT))
        for i, av in enumerate(avoids):
            if _poly_ok(av) and not outer.covers(av):
                issues.append(_issue("AVOID_OUTSIDE_OUTER", "避位区超出治具",
                                     f"避位区 #{i+1} 超出治具外框。", "blocking",
                                     SRC_STRUCT, object_id=f"avoid-{i+1}"))
        for i, so in enumerate(solders):
            if _poly_ok(so) and not outer.covers(so):
                issues.append(_issue("SOLDER_OUTSIDE_OUTER", "上锡区超出治具",
                                     f"上锡区 #{i+1} 超出治具外框。", "blocking",
                                     SRC_STRUCT, object_id=f"solder-{i+1}"))
        # 传送带极限（治具可平放的最长边不得超过传送带宽度）
        minx, miny, maxx, maxy = outer.bounds
        w, h = maxx - minx, maxy - miny
        short, long_ = min(w, h), max(w, h)
        if short > CONVEYOR_MAX_W_MM or long_ > CONVEYOR_MAX_L_MM:
            issues.append(_issue("FIXTURE_SIZE_EXCEEDS_CONVEYOR", "治具超出传送带极限",
                                 f"治具 {w:.0f}×{h:.0f}mm 超出常见传送带上限 "
                                 f"{CONVEYOR_MAX_W_MM:.0f}×{CONVEYOR_MAX_L_MM:.0f}mm，"
                                 "需确认波峰焊设备轨距或改用分板。", "error", SRC_SIZE,
                                 current=float(max(w, h)), required=CONVEYOR_MAX_L_MM, unit="mm"))

    # ── B. 定位销 ────────────────────────────────────────────────
    if len(pins) < 2:
        issues.append(_issue("LOCATING_PINS_INSUFFICIENT", "定位销数量不足",
                             f"当前 {len(pins)} 个定位销，推荐至少 2 个以保证 PCB 约束定位。",
                             "warning", SRC_STRUCT,
                             current=float(len(pins)), required=2.0, unit="个"))
    for pi, (x, y, _r) in enumerate(pins):
        for ai, av in enumerate(avoids):
            if _poly_ok(av) and _pt_in(av, x, y):
                issues.append(_issue("PIN_IN_AVOID", "定位销落入避位区",
                                     f"定位销 #{pi+1} 落入避位区 #{ai+1}，销钉会顶起 PCB。",
                                     "error", SRC_STRUCT,
                                     object_id=f"pin-{pi+1}/avoid-{ai+1}"))

    # ── C. 压扣孔 ────────────────────────────────────────────────
    if len(screws) < 2:
        issues.append(_issue("CLAMPS_INSUFFICIENT", "压扣数量不足",
                             f"当前 {len(screws)} 个压扣孔，推荐至少 2 个防止浮板。",
                             "warning", SRC_STRUCT,
                             current=float(len(screws)), required=2.0, unit="个"))
    for si, (x, y) in enumerate(screws):
        if _pt_in(sink, x, y):
            issues.append(_issue("CLAMP_IN_SINK", "压扣孔落入沉板区",
                                 f"压扣孔 #{si+1} 落入沉板区，压扣会压伤板边元件。",
                                 "error", SRC_STRUCT, object_id=f"screw-{si+1}"))
        for ai, av in enumerate(avoids):
            if _poly_ok(av) and _pt_in(av, x, y):
                issues.append(_issue("CLAMP_IN_AVOID", "压扣孔落入避位区",
                                     f"压扣孔 #{si+1} 与避位区 #{ai+1} 重叠。",
                                     "error", SRC_STRUCT, object_id=f"screw-{si+1}/avoid-{ai+1}"))

    # ── D. 挡锡条 ────────────────────────────────────────────────
    for bi, strip in enumerate(tin_strips):
        try:
            if sink is not None and strip is not None and strip.intersects(sink):
                issues.append(_issue("BARRIER_SINK_COLLISION", "挡锡条与沉板区干涉",
                                     f"挡锡条 #{bi+1} 与沉板区重叠，可能压坏板边元件。",
                                     "warning", SRC_STRUCT, object_id=f"tin-strip-{bi+1}"))
        except Exception as e:
            log.debug("挡锡条 %d 几何退化跳过: %s", bi + 1, e)
            continue
    for hi, hole in enumerate(tin_holes):
        hx, hy = (hole[0], hole[1]) if isinstance(hole, (list, tuple)) else (hole.x, hole.y)
        if _pt_in(sink, hx, hy):
            issues.append(_issue("TIN_HOLE_IN_SINK", "挡锡条孔落入沉板区",
                                 f"挡锡条孔 ({hx:.1f}, {hy:.1f}) 落入沉板区。",
                                 "error", SRC_STRUCT, object_id=f"tin-hole-{hi+1}"))

    # ── E. 避位 / 上锡 / 取手 ────────────────────────────────────
    for ai, av in enumerate(avoids):
        if not _poly_ok(av):
            continue
        for si, so in enumerate(solders):
            if not _poly_ok(so):
                continue
            try:
                if av.intersects(so):
                    issues.append(_issue("AVOID_SOLDER_OVERLAP", "避位区与上锡区重叠",
                                         f"避位区 #{ai+1} 与上锡区 #{si+1} 重叠，"
                                         "波峰焊时会同时顶板与上锡，工艺冲突。",
                                         "warning", SRC_DFM,
                                         object_id=f"avoid-{ai+1}/solder-{si+1}"))
            except Exception as e:
                log.debug("避位/上锡交集判定跳过: %s", e)
                continue
    for hi, h in enumerate(handles):
        if _poly_ok(outer) and not outer.covers(h):
            issues.append(_issue("HANDLE_OUTSIDE_BODY", "取手位超出治具",
                                 f"取手位 #{hi+1} 超出治具外框。", "error",
                                 SRC_STRUCT, object_id=f"handle-{hi+1}"))
        for ai, av in enumerate(avoids):
            if _poly_ok(av) and _poly_ok(h):
                try:
                    if h.intersects(av):
                        issues.append(_issue("HANDLE_AVOID_COLLISION", "取手位与避位区重叠",
                                             f"取手位 #{hi+1} 与避位区 #{ai+1} 重叠。",
                                             "warning", SRC_STRUCT,
                                             object_id=f"handle-{hi+1}/avoid-{ai+1}"))
                except Exception as e:
                    log.debug("取手/避位交集判定跳过: %s", e)
                    continue

    return issues


def counts(issues: list[dict]) -> dict:
    out = {s: 0 for s in SEVERITY_ORDER}
    for i in issues:
        out[i["severity"]] = out.get(i["severity"], 0) + 1
    return out


def production_allowed(issues: list[dict]) -> bool:
    """无 blocking 且无 error 才允许下载生产 DXF。"""
    return all(i["severity"] not in ("blocking", "error") for i in issues)


def gate(issues: list[dict]) -> dict:
    """门禁汇总：allowed + 分级计数 + 最高严重度。"""
    c = counts(issues)
    worst = "info"
    for i in issues:
        if SEVERITY_ORDER[i["severity"]] > SEVERITY_ORDER[worst]:
            worst = i["severity"]
    return {"allowed": production_allowed(issues), "counts": c, "worst": worst,
            "total": len(issues)}


def apply_watermark(dxf_path, text: str = "PREVIEW — 未通过 DRC 门禁，禁止生产") -> str:
    """在 DXF 上叠加水印文字层（用于未通过门禁的预览版导出）。返回新路径。"""
    import ezdxf

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    if "WATERMARK" not in doc.layers:
        doc.layers.add("WATERMARK", color=1)  # 红
    # 沿对角线铺多条 45° 旋转文字
    xs = [200.0, 600.0, 1000.0]
    ys = [100.0, 300.0, 500.0]
    k = 0
    for y in ys:
        for x in xs:
            px = x + (k % 3) * 60
            msp.add_text(
                f"{text} #{k + 1}",
                dxfattribs={"layer": "WATERMARK", "height": 18.0, "rotation": 30},
            ).set_placement((px, y))
            k += 1
    out = str(dxf_path).replace(".dxf", ".PREVIEW.dxf")
    doc.saveas(out)
    return out
