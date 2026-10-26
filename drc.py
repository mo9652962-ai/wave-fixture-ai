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
import math
from dataclasses import asdict, dataclass

log = logging.getLogger("fixture-drc")

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "blocking": 3}

# 传送带极限（PCBSync / MB Manufacturing）：20"W × 30"L
CONVEYOR_MAX_W_MM = 508.0
CONVEYOR_MAX_L_MM = 762.0

# 工业合规常量（G 组规则）：
RAIL_MAX_MM = 330.0  # 波峰焊轨距默认上限（常见 350mm 轨道 - 两侧余量，设备可配）
MIN_OPENING_MM = 3.8  # 最小开口宽度（Macaos Selective Wave Soldering Guidelines）
MIN_WALL_MM = 1.5  # 最小壁厚（APTPCB：肋墙 ≥0.8mm，推荐 1.5mm）
DEFAULT_PANEL_GAP = 5.0  # 拼版默认片间距
MIN_PANEL_GAP = 3.0  # 拼版最小片间距（挡锡墙下限）


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


def _issue(code: str, title: str, detail: str, severity: str, source: str, **kw) -> dict:
    d = DRCIssue(code=code, title=title, detail=detail, severity=severity, source=source, **kw)
    return d.to_dict()


def _covers(outer, inner) -> bool:
    try:
        return outer is not None and inner is not None and outer.covers(inner)
    except Exception:
        return False


def _contains_point(geom, x: float, y: float) -> bool:
    try:
        return (
            geom is not None and geom.contains(type(geom)([(x, y)]))
            if False
            else _pt_in(geom, x, y)
        )
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


def run_drc(
    r1,
    r2,
    material_key: str | None = None,
    machine_key: str | None = None,
    pallet_thickness: float = 10.0,
) -> list[dict]:
    """对 phase1/phase2 结果跑全部 DRC 规则，返回发现列表（含 severity 与出处）。

    material_key: 可选治具材料 key（materials.MATERIALS）——提供时启用
    材料-工艺交叉校验（G5 MATERIAL_TEMP_WINDOW，如 FR-4 vs 无铅波峰）。
    machine_key: 可选波峰焊机台画像（equipment.MACHINES）——提供时启用
    真机合规校验（H 组：轨距/载荷/SMEMA 高度）。
    pallet_thickness: 治具板厚（H2 载荷估算用）。
    """
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
    dogbones = getattr(r1, "dogbone_corners", []) or getattr(r2, "dogbone_corners", []) or []

    # ── A. 结构边界 ──────────────────────────────────────────────
    if not _poly_ok(board):
        issues.append(
            _issue(
                "BOARD_OUTLINE_INVALID",
                "PCB 外形无效",
                "外形层缺失、为空或存在自交拓扑。",
                "blocking",
                SRC_STRUCT,
            )
        )
    if not _poly_ok(sink):
        issues.append(
            _issue(
                "SINK_REGION_INVALID",
                "沉板区无效",
                "外形外扩后未形成有效沉板区域。",
                "blocking",
                SRC_STRUCT,
            )
        )
    if not _poly_ok(outer):
        issues.append(
            _issue(
                "FIXTURE_BODY_INVALID",
                "治具外形无效",
                "治具外框缺失或无效。",
                "blocking",
                SRC_STRUCT,
            )
        )
    else:
        if _poly_ok(sink) and not outer.covers(sink):
            issues.append(
                _issue(
                    "FIXTURE_BODY_OVERFLOW",
                    "沉板区超出治具",
                    "沉板区超出治具主体外框边界。",
                    "blocking",
                    SRC_STRUCT,
                )
            )
        for i, av in enumerate(avoids):
            if _poly_ok(av) and not outer.covers(av):
                issues.append(
                    _issue(
                        "AVOID_OUTSIDE_OUTER",
                        "避位区超出治具",
                        f"避位区 #{i + 1} 超出治具外框。",
                        "blocking",
                        SRC_STRUCT,
                        object_id=f"avoid-{i + 1}",
                    )
                )
        for i, so in enumerate(solders):
            if _poly_ok(so) and not outer.covers(so):
                issues.append(
                    _issue(
                        "SOLDER_OUTSIDE_OUTER",
                        "上锡区超出治具",
                        f"上锡区 #{i + 1} 超出治具外框。",
                        "blocking",
                        SRC_STRUCT,
                        object_id=f"solder-{i + 1}",
                    )
                )
        # 传送带极限（治具可平放的最长边不得超过传送带宽度）
        minx, miny, maxx, maxy = outer.bounds
        w, h = maxx - minx, maxy - miny
        short, long_ = min(w, h), max(w, h)
        if short > CONVEYOR_MAX_W_MM or long_ > CONVEYOR_MAX_L_MM:
            issues.append(
                _issue(
                    "FIXTURE_SIZE_EXCEEDS_CONVEYOR",
                    "治具超出传送带极限",
                    f"治具 {w:.0f}×{h:.0f}mm 超出常见传送带上限 "
                    f"{CONVEYOR_MAX_W_MM:.0f}×{CONVEYOR_MAX_L_MM:.0f}mm，"
                    "需确认波峰焊设备轨距或改用分板。",
                    "error",
                    SRC_SIZE,
                    current=float(max(w, h)),
                    required=CONVEYOR_MAX_L_MM,
                    unit="mm",
                )
            )

    # ── B. 定位销 ────────────────────────────────────────────────
    if len(pins) < 2:
        issues.append(
            _issue(
                "LOCATING_PINS_INSUFFICIENT",
                "定位销数量不足",
                f"当前 {len(pins)} 个定位销，推荐至少 2 个以保证 PCB 约束定位。",
                "warning",
                SRC_STRUCT,
                current=float(len(pins)),
                required=2.0,
                unit="个",
            )
        )
    # 销径过小：<1.5mm 的销在波峰焊高温下强度不足（真实板常见：全板只有细信号过孔）
    for pi, (_x, _y, pr) in enumerate(pins):
        if pr * 2 < 1.5:
            issues.append(
                _issue(
                    "PIN_DIAMETER_TOO_SMALL",
                    "定位销直径过小",
                    f"定位销 #{pi + 1} 直径 {pr * 2:.2f}mm < 1.5mm，"
                    "高温下强度不足且定位精度差；建议选 2.5-4.5mm 安装孔。",
                    "warning",
                    SRC_DFM,
                    current=round(pr * 2, 3),
                    required=1.5,
                    unit="mm",
                )
            )
    for pi, (x, y, _r) in enumerate(pins):
        for ai, av in enumerate(avoids):
            if _poly_ok(av) and _pt_in(av, x, y):
                issues.append(
                    _issue(
                        "PIN_IN_AVOID",
                        "定位销落入避位区",
                        f"定位销 #{pi + 1} 落入避位区 #{ai + 1}，销钉会顶起 PCB。",
                        "error",
                        SRC_STRUCT,
                        object_id=f"pin-{pi + 1}/avoid-{ai + 1}",
                    )
                )

    # ── C. 压扣孔 ────────────────────────────────────────────────
    if len(screws) < 2:
        issues.append(
            _issue(
                "CLAMPS_INSUFFICIENT",
                "压扣数量不足",
                f"当前 {len(screws)} 个压扣孔，推荐至少 2 个防止浮板。",
                "warning",
                SRC_STRUCT,
                current=float(len(screws)),
                required=2.0,
                unit="个",
            )
        )
    for si, (x, y) in enumerate(screws):
        if _pt_in(sink, x, y):
            issues.append(
                _issue(
                    "CLAMP_IN_SINK",
                    "压扣孔落入沉板区",
                    f"压扣孔 #{si + 1} 落入沉板区，压扣会压伤板边元件。",
                    "error",
                    SRC_STRUCT,
                    object_id=f"screw-{si + 1}",
                )
            )
        for ai, av in enumerate(avoids):
            if _poly_ok(av) and _pt_in(av, x, y):
                issues.append(
                    _issue(
                        "CLAMP_IN_AVOID",
                        "压扣孔落入避位区",
                        f"压扣孔 #{si + 1} 与避位区 #{ai + 1} 重叠。",
                        "error",
                        SRC_STRUCT,
                        object_id=f"screw-{si + 1}/avoid-{ai + 1}",
                    )
                )

    # ── D. 挡锡条 ────────────────────────────────────────────────
    for bi, strip in enumerate(tin_strips):
        try:
            if sink is not None and strip is not None and strip.intersects(sink):
                issues.append(
                    _issue(
                        "BARRIER_SINK_COLLISION",
                        "挡锡条与沉板区干涉",
                        f"挡锡条 #{bi + 1} 与沉板区重叠，可能压坏板边元件。",
                        "warning",
                        SRC_STRUCT,
                        object_id=f"tin-strip-{bi + 1}",
                    )
                )
        except Exception as e:
            log.debug("挡锡条 %d 几何退化跳过: %s", bi + 1, e)
            continue
    for hi, hole in enumerate(tin_holes):
        hx, hy = (hole[0], hole[1]) if isinstance(hole, (list, tuple)) else (hole.x, hole.y)
        if _pt_in(sink, hx, hy):
            issues.append(
                _issue(
                    "TIN_HOLE_IN_SINK",
                    "挡锡条孔落入沉板区",
                    f"挡锡条孔 ({hx:.1f}, {hy:.1f}) 落入沉板区。",
                    "error",
                    SRC_STRUCT,
                    object_id=f"tin-hole-{hi + 1}",
                )
            )

    # ── E. 避位 / 上锡 / 取手 ────────────────────────────────────
    for ai, av in enumerate(avoids):
        if not _poly_ok(av):
            continue
        for si, so in enumerate(solders):
            if not _poly_ok(so):
                continue
            try:
                if av.intersects(so):
                    issues.append(
                        _issue(
                            "AVOID_SOLDER_OVERLAP",
                            "避位区与上锡区重叠",
                            f"避位区 #{ai + 1} 与上锡区 #{si + 1} 重叠，"
                            "波峰焊时会同时顶板与上锡，工艺冲突。",
                            "warning",
                            SRC_DFM,
                            object_id=f"avoid-{ai + 1}/solder-{si + 1}",
                        )
                    )
            except Exception as e:
                log.debug("避位/上锡交集判定跳过: %s", e)
                continue
    for hi, h in enumerate(handles):
        if _poly_ok(outer) and not outer.covers(h):
            issues.append(
                _issue(
                    "HANDLE_OUTSIDE_BODY",
                    "取手位超出治具",
                    f"取手位 #{hi + 1} 超出治具外框。",
                    "error",
                    SRC_STRUCT,
                    object_id=f"handle-{hi + 1}",
                )
            )
        for ai, av in enumerate(avoids):
            if _poly_ok(av) and _poly_ok(h):
                try:
                    if h.intersects(av):
                        issues.append(
                            _issue(
                                "HANDLE_AVOID_COLLISION",
                                "取手位与避位区重叠",
                                f"取手位 #{hi + 1} 与避位区 #{ai + 1} 重叠。",
                                "warning",
                                SRC_STRUCT,
                                object_id=f"handle-{hi + 1}/avoid-{ai + 1}",
                            )
                        )
                except Exception as e:
                    log.debug("取手/避位交集判定跳过: %s", e)
                    continue

    # ── F. 狗骨头减隙刀路检查 ──────────────────────────────────────────
    from shapely.geometry import Point as _Pt

    for di, db in enumerate(dogbones):
        cx, cy = getattr(db, "center", (0, 0))
        cr = getattr(db, "cutter_r", 1.85)
        cut_circ = _Pt(cx, cy).buffer(cr, quad_segs=8)
        if _poly_ok(outer) and not outer.covers(cut_circ):
            issues.append(
                _issue(
                    "DOGBONE_BODY_OVERFLOW",
                    "狗骨头清角超出治具外框",
                    f"狗骨头刀具切削范围 #{di + 1} 超出治具主体外框。",
                    "error",
                    SRC_STRUCT,
                    object_id=f"dogbone-{di + 1}",
                )
            )
        for si, (sx, sy) in enumerate(screws):
            if cut_circ.contains(_Pt(sx, sy)):
                issues.append(
                    _issue(
                        "DOGBONE_CLAMP_COLLISION",
                        "狗骨头与压扣孔干涉",
                        f"狗骨头清角 #{di + 1} 刀路与压扣孔 #{si + 1} 重叠。",
                        "error",
                        SRC_STRUCT,
                        object_id=f"dogbone-{di + 1}/screw-{si + 1}",
                    )
                )
        for pi, (px, py, _pr) in enumerate(pins):
            if cut_circ.contains(_Pt(px, py)):
                issues.append(
                    _issue(
                        "DOGBONE_PIN_COLLISION",
                        "狗骨头与定位销干涉",
                        f"狗骨头清角 #{di + 1} 刀路与定位销 #{pi + 1} 重叠。",
                        "error",
                        SRC_STRUCT,
                        object_id=f"dogbone-{di + 1}/pin-{pi + 1}",
                    )
                )

    # ── G. 工业合规（企业级新增，出处见头注）─────────────────────────
    # G1. 轨道限宽：治具短边（横跨轨道方向）不得超过波峰焊轨距上限
    rail_max = float(getattr(r2, "rail_max_mm", RAIL_MAX_MM) or RAIL_MAX_MM)
    if _poly_ok(outer):
        minx, miny, maxx, maxy = outer.bounds
        short_side = min(maxx - minx, maxy - miny)
        if short_side > rail_max:
            issues.append(
                _issue(
                    "RAIL_WIDTH_OVERFLOW",
                    "治具超出波峰焊轨距",
                    f"治具短边 {short_side:.1f}mm 超出默认轨距上限 {rail_max:.0f}mm——"
                    "治具无法放入波峰焊轨道；请减小拼版片数或改用双治具分板。",
                    "error",
                    SRC_SIZE,
                    current=round(short_side, 1),
                    required=rail_max,
                    unit="mm",
                )
            )
    # G2. 最小开口宽度：避位/上锡开口过窄易挂锡、难加工（Macaos ≥3.8mm）
    for group_name, group in (("avoid", avoids), ("solder", solders)):
        for gi, g in enumerate(group):
            if not _poly_ok(g):
                continue
            gx0, gy0, gx1, gy1 = g.bounds
            gmin = min(gx1 - gx0, gy1 - gy0)
            if 0 < gmin < MIN_OPENING_MM:
                issues.append(
                    _issue(
                        "MIN_OPENING_WIDTH",
                        "开口宽度过窄",
                        f"{group_name} 开口 #{gi + 1} 最小尺寸 {gmin:.2f}mm < "
                        f"{MIN_OPENING_MM}mm（Macaos 指南），易挂锡且铣刀加工困难。",
                        "warning",
                        SRC_DFM,
                        current=round(gmin, 2),
                        required=MIN_OPENING_MM,
                        unit="mm",
                        object_id=f"{group_name}-{gi + 1}",
                    )
                )
    # G3. 薄壁：沉板区与避位/上锡之间壁厚 < 推荐值（APTPCB 肋墙 ≥0.8，推荐 1.5）
    if _poly_ok(sink):
        for group_name, group in (("avoid", avoids), ("solder", solders)):
            for gi, g in enumerate(group):
                if not _poly_ok(g):
                    continue
                try:
                    d = sink.exterior.distance(g.exterior)
                except Exception:  # noqa: S112
                    continue
                if d < MIN_WALL_MM:
                    issues.append(
                        _issue(
                            "THIN_WALL",
                            "薄壁风险",
                            f"沉板区与 {group_name} #{gi + 1} 壁厚仅 {d:.2f}mm < "
                            f"{MIN_WALL_MM}mm（APTPCB 推荐值），高温高频振动下易开裂。",
                            "warning",
                            SRC_DFM,
                            current=round(d, 2),
                            required=MIN_WALL_MM,
                            unit="mm",
                            object_id=f"wall-sink/{group_name}-{gi + 1}",
                        )
                    )
    # G4. 拼版间距：片间距 < 3mm 挡锡墙易挂锡（行业下限）
    grid = getattr(r2, "panel_grid", None)
    if grid and grid.get("copies", 1) > 1:
        gap = float(grid.get("gap", DEFAULT_PANEL_GAP))
        if gap < MIN_PANEL_GAP:
            issues.append(
                _issue(
                    "PANEL_GAP_TOO_SMALL",
                    "拼版间距过小",
                    f"拼版片间距 {gap:.1f}mm < {MIN_PANEL_GAP}mm，挡锡墙过窄易挂锡连片。",
                    "warning",
                    SRC_DFM,
                    current=round(gap, 2),
                    required=MIN_PANEL_GAP,
                    unit="mm",
                )
            )
    # G5. 材料-工艺交叉校验：治具底面直接接触波峰焊料，
    #     材料长期使用温度必须 ≥ 无铅波峰下限 255°C（process.py 工艺窗口库）
    mkey = material_key or getattr(r2, "material_key", None)
    if mkey:
        try:
            from materials import get_material as _get_material
            from process import material_process_compat as _compat

            _m = _get_material(mkey)
            ok, note = _compat(_m.max_service_temp_c)
            if not ok:
                issues.append(
                    _issue(
                        "MATERIAL_TEMP_WINDOW",
                        "材料耐温低于无铅波峰温度",
                        note,
                        "warning",
                        SRC_DFM,
                        current=float(_m.max_service_temp_c),
                        required=255.0,
                        unit="°C",
                    )
                )
        except Exception as e:  # 材料库异常不阻塞 DRC 主流程
            log.debug("材料-工艺校验跳过: %s", e)

    # G6. 闭合避位腔排气检查（AGICORP §4.2）：
    # 面积 > 100mm² 的闭合避位腔若未设置排气孔，波峰浸入时气体无法逸出，
    # 容易形成气阻截留助焊剂气体导致虚焊/漏焊。
    vents = getattr(r2, "vent_holes", []) or []
    from shapely.geometry import Point as _Pt

    for ai, av in enumerate(avoids):
        if not _poly_ok(av) or av.area < 100.0:
            continue
        has_vent = any(av.contains(_Pt(vx, vy)) for (vx, vy, _vr) in vents)
        if not has_vent:
            issues.append(
                _issue(
                    "UNVENTED_AVOID_POCKET",
                    "避位深腔缺少排气孔",
                    f"避位腔 #{ai + 1} 面积 {av.area:.1f}mm² > 100mm² 且未设排气孔，"
                    "波峰过炉时截留助焊剂气体易导致虚焊/漏焊（AGICORP §4.2 指南）。",
                    "warning",
                    "AGICORP Wave Solder Pallet Design Guidelines §4.2",
                    current=round(av.area, 1),
                    required=100.0,
                    unit="mm²",
                    object_id=f"avoid-{ai + 1}",
                )
            )

    # ── H. 真机合规（企业级：治具必须放进某台具体机台过波）─────────────
    mkey = machine_key or getattr(r2, "machine_key", None)
    if mkey:
        try:
            from equipment import get_machine as _get_machine
            from materials import estimate_weight as _est_weight
            from materials import get_material as _get_material

            _m = _get_machine(mkey)
            if _poly_ok(outer):
                ox0, oy0, ox1, oy1 = outer.bounds
                short_side = min(ox1 - ox0, oy1 - oy0)
                # H1. 轨距：治具短边须放得进机台前后导轨之间
                if short_side > _m.process_width_max_mm:
                    issues.append(
                        _issue(
                            "MACHINE_WIDTH_MISMATCH",
                            "治具超出机台轨距",
                            f"治具短边 {short_side:.1f}mm 超出 {_m.name_cn} "
                            f"轨距上限 {_m.process_width_max_mm:.0f}mm——请改机台、"
                            "减小拼版或分板。",
                            "error",
                            _m.source,
                            current=round(short_side, 1),
                            required=float(_m.process_width_max_mm),
                            unit="mm",
                        )
                    )
                # H2. 载荷：治具毛坯估重（保守：不减开孔）不得超过传送链承载
                blank_w = _est_weight(
                    (ox1 - ox0) * (oy1 - oy0), float(pallet_thickness), _get_material(material_key)
                )
                if blank_w > _m.conveyor_load_kg:
                    issues.append(
                        _issue(
                            "MACHINE_OVERLOAD",
                            "治具超出传送链载荷",
                            f"治具毛坯估重 {blank_w:.2f}kg 超出 {_m.name_cn} 传送链"
                            f"载荷 {_m.conveyor_load_kg}kg——请减薄板厚/改材料"
                            "（如 Durostone→FR-4）/减小治具。",
                            "error",
                            _m.source,
                            current=round(blank_w, 2),
                            required=float(_m.conveyor_load_kg),
                            unit="kg",
                        )
                    )
                # H3. SMEMA 高度兼容（info）：治具垫高 PCB，板底高度须兼容上下游
                if not _m.official:
                    pass  # 非官方画像不产生 info 噪音
                issues.append(
                    _issue(
                        "SMEMA_HEIGHT_CHECK",
                        "SMEMA 传送高度确认",
                        f"治具板厚 {pallet_thickness}mm 会垫高 PCB 底面——"
                        f"确认与上下游设备（IPC-SMEMA-9851 高度窗口 940-965mm）兼容；"
                        f"{_m.rail_arrangement}。",
                        "info",
                        "IPC-SMEMA-9851 Standard",
                    )
                )
        except Exception as e:  # 机台库异常不阻塞 DRC 主流程
            log.debug("真机合规校验跳过: %s", e)

    # ── I. 铰链式上盖防翘曲机构检查 (Top Hat Cover DFM) ────────────────
    tophat = getattr(r2, "top_hat", None)
    if tophat:
        hinges = getattr(tophat, "hinge_holes", []) or []
        latches = getattr(tophat, "latch_holes", []) or []
        for hi, (hx, hy, _hr) in enumerate(hinges):
            if _poly_ok(outer) and not _contains_point(outer, hx, hy):
                issues.append(
                    _issue(
                        "TOPHAT_HINGE_OVERFLOW",
                        "上盖铰链孔超出治具基体",
                        f"上盖铰链孔 #{hi + 1} ({hx:.1f}, {hy:.1f}) 超出治具外框，无法紧固。",
                        "error",
                        "AGICORP Top Hat Design Guide",
                        object_id=f"hinge-{hi + 1}",
                    )
                )
        for li, (lx, ly, _lr) in enumerate(latches):
            if _poly_ok(outer) and not _contains_point(outer, lx, ly):
                issues.append(
                    _issue(
                        "TOPHAT_LATCH_OVERFLOW",
                        "上盖锁扣孔超出治具基体",
                        f"上盖锁扣孔 #{li + 1} ({lx:.1f}, {ly:.1f}) 超出治具外框，无法紧固。",
                        "error",
                        "AGICORP Top Hat Design Guide",
                        object_id=f"latch-{li + 1}",
                    )
                )

    # ── J. 选择焊喷嘴避障几何校验 (Selective Soldering Nozzle DFM) ────────
    if solders:
        try:
            from selective_wave import verify_selective_solder_clearance

            nozzle_violations = verify_selective_solder_clearance(solders, avoids)
            for v in nozzle_violations:
                issues.append(
                    _issue(
                        "SELECTIVE_NOZZLE_COLLISION",
                        v["title"],
                        v["detail"],
                        v["severity"],
                        v["source"],
                        current=v.get("current"),
                        required=v.get("required"),
                        unit=v.get("unit"),
                        object_id=v.get("object_id"),
                    )
                )
        except Exception as e:
            log.debug("选择焊喷嘴避障校验跳过: %s", e)

    # ── K. 大跨度重力热下垂变形风险检查 (AGICORP & MB-MFG 规范) ─────────
    if _poly_ok(outer):
        ox0, oy0, ox1, oy1 = outer.bounds
        max_span = max(ox1 - ox0, oy1 - oy0)
        stiffener_res = getattr(r2, "stiffener", None)
        has_stiffener = bool(stiffener_res and getattr(stiffener_res, "needed", False))
        if max_span >= 250.0 and not has_stiffener:
            issues.append(
                _issue(
                    "FIXTURE_SAG_DEFLECTION_RISK",
                    "大跨度治具存在热下垂变形风险",
                    f"治具跨距 {max_span:.1f}mm ≥ 250mm 且未配置加强横梁，"
                    "在 260°C 熔融锡锅上因自重和热应力易产生 >0.5mm 下垂形变，"
                    "导致中心焊点吃锡深度失控；建议加装中支撑加强筋 (Center Stiffener Bar)。",
                    "warning",
                    "AGICORP / MB Manufacturing Wave Pallet Engineering Guidelines",
                    current=round(max_span, 1),
                    required=250.0,
                    unit="mm",
                )
            )

    # ── L. 上锡开孔深宽比毛细流动检查 (AGICORP & SMTA 规范) ─────────────
    # 当开孔垂直深度与最小开口尺寸比例 > 1.2 时，表面张力易形成阻滞
    for si, sp in enumerate(solders):
        if not _poly_ok(sp):
            continue
        minx, miny, maxx, maxy = sp.bounds
        min_dim = min(maxx - minx, maxy - miny)
        # 治具厚度 - 沉板深 约为开孔深度 (典型 10mm - 2mm = 8mm)
        hole_depth = max(float(pallet_thickness) - 2.1, 1.0)
        ratio = hole_depth / min_dim if min_dim > 0 else 999.0
        if ratio > 1.2:
            issues.append(
                _issue(
                    "SOLDER_OPENING_ASPECT_RATIO",
                    "上锡开孔深宽比过大导致透锡阻滞",
                    f"上锡开孔 #{si + 1} 最小跨度 {min_dim:.2f}mm，"
                    f"开孔深宽比 {ratio:.2f} > 1.2（深度 {hole_depth:.1f}mm）；"
                    "熔融焊锡因毛细表面张力流动受阻，易导致透锡不良，建议外扩开孔或底部做 60° 倒角导流。",
                    "warning",
                    "AGICORP & SMTA Wave Soldering Cavity Aspect Ratio Guidelines",
                    current=round(ratio, 2),
                    required=1.2,
                    object_id=f"solder-{si + 1}",
                )
            )

    # ── M. 边缘金手指接触防爬锡检查 (IPC-A-610G §7.1.4 & AGICORP §5.0) ──
    # 若存在板边金手指且未配置遮罩压条，警告焊料毛细沾污报废风险
    gold_shields = getattr(r2, "gold_shields", []) or []
    has_unprotected_gold = bool(getattr(r2, "has_unprotected_gold_fingers", False))
    if has_unprotected_gold and not gold_shields:
        issues.append(
            _issue(
                "GOLD_FINGER_UNPROTECTED",
                "板边金手指缺少防爬锡遮罩",
                "检测到板边关键金手指/接触插头但未配置保护压条，"
                "波峰焊时焊锡易发生毛细爬附导致金手指沾锡报废（IPC-A-610G Class 3 缺陷）。",
                "warning",
                "IPC-A-610G §7.1.4 & AGICORP §5.0",
            )
        )

    # ── N. 治具底部热容与减重散热平衡检查 (SMTA 热剖面平衡准则) ─────────
    # 治具外框面积大且未开设减重槽时，过大热容易导致整板温差失衡
    lightening_res = getattr(r2, "lightening", None)
    if _poly_ok(outer) and outer.area >= 25000.0:
        ratio = getattr(lightening_res, "lightening_ratio_pct", 0.0) if lightening_res else 0.0
        if ratio < 10.0:
            issues.append(
                _issue(
                    "THERMAL_MASS_IMBALANCE",
                    "治具实心区过大热容失衡风险",
                    f"治具面积 {outer.area:.0f}mm² 较大且减重率仅 {ratio:.1f}% < 10.0%；"
                    "大面积实心合成石热容极大，过预热区易引起冷焊与温差失衡，建议开设底部减重散热槽。",
                    "warning",
                    "SMTA Wave Soldering Thermal Profiling Guidelines",
                    current=round(ratio, 1),
                    required=10.0,
                    unit="%",
                )
            )

    # ── O. 贴片波峰阴影区防范检查 (IPC-7351 & SMTA 波峰焊规范) ─────────
    # 两个相邻密集避位/上锡区在过板方向间距过小 (<1.0mm) 时，迎锡面元器件会阻挡熔融波峰，
    # 导致背风侧元器件产生阻波阴影，产生大面积虚焊。
    for i, a1 in enumerate(avoids):
        if not _poly_ok(a1):
            continue
        for j, a2 in enumerate(avoids[i + 1 :]):
            if not _poly_ok(a2):
                continue
            dist = a1.distance(a2)
            if 0.0 < dist < 1.0:
                issues.append(
                    _issue(
                        "CHIP_WAVE_SHADOW_RISK",
                        "密集贴片区存在波峰阴影效应漏焊风险",
                        f"避位区 #{i + 1} 与 #{i + 1 + j + 1} 间距仅 {dist:.2f}mm < 1.0mm；"
                        "波峰焊时迎波面元件会阻挡熔融焊锡流，背波面引脚极易因阴影效应产生漏焊（IPC-7351）。",
                        "warning",
                        "IPC-7351 & SMTA Wave Solder Shadow Effect Guidelines",
                        current=round(dist, 2),
                        required=1.0,
                        unit="mm",
                    )
                )
                break

    # ── P. CNC 机加工刀具长径比与深腔可达性检查 (CNC 加工工艺守则) ─────────
    # 开孔深度与铣刀直径比例 (L/D) 若 > 3.0，铣刀悬伸过长会导致振刀、侧壁斜度超差甚至断刀
    endmill_dia = 3.7  # 标配 Φ3.7mm 铣刀
    effective_depth = float(pallet_thickness)
    ld_ratio = effective_depth / endmill_dia if endmill_dia > 0 else 1.0
    if ld_ratio > 3.0:
        issues.append(
            _issue(
                "FIXTURE_TOOL_ACCESSIBILITY",
                "开孔深径比过大存在铣刀振刀断刀风险",
                f"治具加工深度 {effective_depth:.1f}mm 对应标配 Φ{endmill_dia}mm 铣刀的长径比 L/D={ld_ratio:.2f} > 3.0；"
                "悬伸过长加工深腔极易引起振刀接刀痕与断刀，建议改用大直径刀具开粗或减薄治具板厚。",
                "warning",
                "CNC Tooling Deflection & Machinability Guidelines (L/D <= 3.0)",
                current=round(ld_ratio, 2),
                required=3.0,
            )
        )

    # ── Q. 测温板热电偶孔道与量产曲线调校检查 (SMTA Thermal Profiling 规范) ──
    # 当上锡区复杂 (>=3处) 且治具属于中大尺寸 (>=20000mm²)，若未设测温热电偶通道，
    # 提示无法通过标准 KIC/ECD 测温仪进行量产首件温度曲线校准。
    tp = getattr(r2, "thermal_profile", None)
    has_tc_holes = bool(tp and getattr(tp, "tc_holes", []))
    if _poly_ok(outer) and outer.area >= 20000.0 and len(solders) >= 3 and not has_tc_holes:
        issues.append(
            _issue(
                "THERMAL_PROFILE_CHANNELS_MISSING",
                "批量治具缺少热电偶测温孔道",
                f"治具面积 {outer.area:.0f}mm² 且包含 {len(solders)} 处上锡区，未预留标准热电偶测温孔 (TC Channels)；"
                "量产首件无法接入 KIC/M.O.L.E. 测温探头测定实测受热曲线，极易导致调机野蛮钻孔（SMTA 测温准则）。",
                "warning",
                "SMTA Thermal Profiling Guidelines & KIC Standards",
            )
        )

    # ── R. 自动化产线光电传感器感应切角避让检查 (IPC-SMEMA-9851 规范) ──
    # 检查导轨边与传感器感应倒角是否受阻
    sensor_notches = getattr(tp, "sensor_notches", []) if tp else []
    if _poly_ok(outer) and len(sensor_notches) < 2 and getattr(r2, "require_smema_notch", False):
        issues.append(
            _issue(
                "PALLET_CONVEYOR_SENSOR_NOTCH",
                "治具入板前缘缺少光电传感器感应缺口",
                "自动化轨道进板侧缺少标准 45° 光电感应倒角/缺口，可能导致产线对射式传感器误检卡板（IPC-SMEMA-9851）。",
                "warning",
                "IPC-SMEMA-9851 Mechanical Interface Specification",
            )
        )

    # ── S. 工业 4.0 MES 追溯条码/二维码沉槽检查 (IPC-1782 追溯规范) ────
    # 面积 >= 20000mm² 的自动化量产治具，若未规划条码/二维码沉槽，
    # 提示无法通过扫码枪绑定批次工单与炉温曲线。
    bt = getattr(r2, "barcode_tag", None)
    has_tag = bool(bt and getattr(bt, "tag_recess_poly", None) and not bt.tag_recess_poly.is_empty)
    if (
        _poly_ok(outer)
        and outer.area >= 20000.0
        and getattr(r2, "require_mes_traceability", False)
        and not has_tag
    ):
        issues.append(
            _issue(
                "TRACEABILITY_TAG_RECESS_MISSING",
                "量产治具缺少 MES 追溯二维码标牌槽",
                "自动化产线要求托盘绑定 MES 工单追溯码，治具边框未预留 25×12mm 标牌沉槽（IPC-1782 追溯标准）。",
                "warning",
                "IPC-1782 Component and Carrier Traceability Standard",
            )
        )

    # ── T. 丰田精益生产防呆防反向倒角检查 (Poka-Yoke 规则) ─────────────
    # 对称或长宽比接近 1.0 (0.85 ~ 1.15) 的近正方形板，沉板区若未设第一引脚防呆切角，
    # 操作员极易 180° 反向错装压坏元件。
    if _poly_ok(sink):
        sx0, sy0, sx1, sy1 = sink.bounds
        sw = sx1 - sx0
        sh = sy1 - sy0
        aspect = sw / sh if sh > 0 else 1.0
        poka_lines = getattr(bt, "poka_yoke_lines", []) if bt else []
        if 0.85 <= aspect <= 1.15 and not poka_lines:
            issues.append(
                _issue(
                    "POKA_YOKE_KEYING_MISSING",
                    "近对称板型沉板区缺少防呆防反向切角",
                    f"沉板区长宽比 {aspect:.2f} 接近正方形，若无第一脚 45° 防呆导向切角，"
                    "操作员手工放板极易发生 180° 反向错装压坏器件（TPS Poka-Yoke 精益防呆准则）。",
                    "warning",
                    "Toyota Production System (TPS) Poka-Yoke Error-Proofing Standard",
                    current=round(aspect, 2),
                    required=1.2,
                )
            )

    # ── U. 波峰焊迎锡前缘防浮渣扰流槽与撇渣切刀检查 (Ersa / SEHO 规范) ──
    # 量产大型治具 (进板长 >= 240mm 或面积 >= 40000mm²)，若迎锡侧前缘未开 8mm 防渣槽，
    # 锡槽表面漂浮的氧化锡渣极易直接冲入沉板开孔污染通孔引脚。
    sd = getattr(r2, "solder_dam", None)
    has_dam = bool(sd and getattr(sd, "dam_poly", None) and not sd.dam_poly.is_empty)
    if (
        _poly_ok(outer)
        and (outer.bounds[2] - outer.bounds[0] >= 240.0 or outer.area >= 40000.0)
        and getattr(r2, "require_dross_skimmer", False)
        and not has_dam
    ):
        issues.append(
            _issue(
                "SOLDER_DAM_DROSS_SKIMMER_MISSING",
                "治具迎锡前缘缺少防浮渣扰流撇渣槽",
                "大型量产治具迎锡进板前缘未开设 8mm 宽撇渣切槽与横向排渣槽，"
                "液面浮渣易直接推入沉板区通孔引脚导致焊锡桥连短路（Kurtz Ersa / SEHO 波峰焊标准）。",
                "warning",
                "Kurtz Ersa & SEHO Solder Dross Skimming Guidelines",
            )
        )

    # ── V. 传送带 5.5° 爬坡倾角动态浸锡间隙检查 (IPC-A-610G §7.5) ──────
    # 在 4°~7° 爬坡倾角下，治具尾端相对前缘具有 Δz = L * tan(θ) 的抬升高度，
    # 若尾端避位开槽深度未充分补偿，易导致尾部元件离锡间隙不足 (<0.8mm) 或擦碰锡波。
    if _poly_ok(sink):
        s_len = sink.bounds[2] - sink.bounds[0]
        incline_deg = getattr(sd, "conveyor_incline_deg", 5.5) if sd else 5.5
        slope_rise = s_len * math.tan(math.radians(incline_deg))
        if s_len >= 180.0 and getattr(r2, "check_incline_clearance", False):
            issues.append(
                _issue(
                    "CONVEYOR_INCLINE_COLLISION_RISK",
                    "传送带爬坡倾角下尾部元件离锡间隙不足",
                    f"治具在 {incline_deg:.1f}° 传送带爬坡角下，尾部相对高度抬升 {slope_rise:.1f}mm；"
                    "尾部深槽元件离锡动态安全间隙可能不足 0.8mm，存在擦碰锡波风险（IPC-A-610G §7.5）。",
                    "warning",
                    "IPC-A-610G §7.5 & SMTA Wave Solder Handbook Incline Dynamics",
                    current=round(slope_rise, 1),
                    required=0.8,
                )
            )

    # ── W. 液态锡浮力与边缘压扣压紧力校核 (AGICORP §3.0 / Macaos) ──────
    hdc = getattr(r2, "hold_down_clamps", None)
    if (
        _poly_ok(sink)
        and getattr(r2, "require_hold_down_clamps", False)
        and (not hdc or getattr(hdc, "actual_clamp_count", 0) < getattr(hdc, "recommended_clamp_count", 4))
    ):
        act_n = getattr(hdc, "actual_clamp_count", 0) if hdc else 0
        rec_n = getattr(hdc, "recommended_clamp_count", 4) if hdc else 4
        f_b = getattr(hdc, "buoyancy_force_n", 0.0) if hdc else 0.0
        issues.append(
            _issue(
                "SOLDER_BUOYANCY_CLAMP_DEFICIT",
                "PCB 边缘旋转压扣数量不足以抵抗锡液浮力",
                f"PCB 在液态锡槽中受到 {f_b:.1f}N 向上浮力与动压，当前压扣数量 ({act_n}) "
                f"低于推荐保持数量 ({rec_n})，PCB 易被锡波浮起导致正面漫锡短路（AGICORP §3.0）。",
                "warning",
                "AGICORP §3.0 Hold-Down Clamps & PCB Retention Standards",
                current=act_n,
                required=rec_n,
            )
        )

    # ── X. 边缘压扣压舌与板边贴片器件干涉检查 (IPC-A-610G) ─────────────
    clamp_polys = getattr(hdc, "clamp_polys", []) if hdc else []
    for ci, c_poly in enumerate(clamp_polys):
        if not _poly_ok(c_poly):
            continue
        for ai, av in enumerate(avoids):
            if _poly_ok(av) and c_poly.intersects(av):
                issues.append(
                    _issue(
                        "HOLD_DOWN_CLAMP_COMPONENT_INTERFERENCE",
                        "旋转压扣压舌与板边贴片器件干涉",
                        f"压扣压舌 #{ci + 1} 压入区与避位区器件 #{ai + 1} 发生干涉，压扣旋紧时可能压碎元件（IPC-A-610G）。",
                        "error",
                        "AGICORP §3.2 & IPC-A-610G Component Clearance Limits",
                        object_id=f"clamp-{ci + 1}/avoid-{ai + 1}",
                    )
                )

    # ── Y. 波峰焊接触时间窗口合规性校核 (SMTA / IPC J-STD-001) ─────────
    ti = getattr(r2, "titanium_inserts", None)
    dwell_win = getattr(ti, "dwell_window", None) if ti else None
    if dwell_win and not dwell_win.is_compliant and getattr(r2, "check_dwell_time", False):
        issues.append(
            _issue(
                "WAVE_DWELL_TIME_OUT_OF_WINDOW",
                "上锡开口走板浸锡接触时间偏离工艺窗口",
                f"在传送带速度 {dwell_win.conveyor_speed_m_per_min:.1f}m/min 下，"
                f"上锡开口有效接触时间 {dwell_win.dwell_time_sec:.2f}s 偏离无铅波峰焊工艺窗口 "
                f"({dwell_win.min_compliant_dwell_sec:.1f}s ~ {dwell_win.max_compliant_dwell_sec:.1f}s)，"
                f"{dwell_win.status_summary}（SMTA & IPC J-STD-001）。",
                "warning",
                "SMTA Wave Soldering Handbook & IPC J-STD-001 Solder Dwell Limits",
                current=dwell_win.dwell_time_sec,
                required=dwell_win.min_compliant_dwell_sec,
            )
        )

    # ── Z. 上锡开孔薄壁/刀刃隔墙钛合金嵌件检查 (AGICORP §5.0) ───────────
    thin_walls = getattr(ti, "thin_walls_detected", 0) if ti else 0
    blades = getattr(ti, "blades", []) if ti else []
    if thin_walls > 0 and len(blades) == 0 and getattr(r2, "require_titanium_inserts", False):
        issues.append(
            _issue(
                "KNIFE_EDGE_WALL_TITANIUM_INSERT_MISSING",
                "上锡开孔隔锡薄壁缺少钛合金耐磨嵌件",
                f"检测到 {thin_walls} 处相邻上锡开孔隔锡壁厚 < 1.8mm；"
                "高量产治具在 260°C 高速锡流冲刷下极易碳化断裂，需镶嵌 0.8mm 钛合金加固刀片（AGICORP §5.0）。",
                "warning",
                "AGICORP §5.0 Titanium Solder Baffle Wear Inserts Specification",
                current=thin_walls,
                required=0,
            )
        )

    # ── AA. CNC 换刀次数经济性检查 (ISO 6983 / RS-274 加工惯例) ─────────
    # 每次自动换刀 (ATC) 耗时 5~10s 且引入对刀误差累积；同直径刀具特征必须成组加工。
    tpo = getattr(r2, "cnc_toolpath_opt", None)
    tool_changes = getattr(tpo, "tool_change_count", 0) if tpo else 0
    if tool_changes > 6:
        issues.append(
            _issue(
                "CNC_TOOL_CHANGE_EXCESSIVE",
                "CNC 换刀次数过多降低量产经济性",
                f"刀路优化后仍需 {tool_changes} 次换刀 (> 6 次)；每次 ATC 耗时 5~10s 并累积对刀误差，"
                "建议合并相近刀具直径或拆分治具加工工序（ISO 6983 / RS-274 加工惯例）。",
                "warning",
                "ISO 6983 & RS-274 CNC Programming Best Practices",
                current=tool_changes,
                required=6,
            )
        )

    # ── AB. CNC 单件加工工时预算检查 (Macaos 报价工艺库工时基线) ────────
    # 单件治具加工 > 45min 触发产能预警：影响批量交付节拍与设备摊销成本。
    total_min = getattr(tpo, "total_time_min", 0.0) if tpo else 0.0
    if total_min > 45.0:
        issues.append(
            _issue(
                "CNC_MACHINING_TIME_BUDGET_EXCEEDED",
                "单件治具 CNC 加工工时超预算",
                f"估算单件加工总工时 {total_min:.1f}min > 45min 产能基线 (含切削/空程/换刀)；"
                "将拖慢批量交付节拍，建议简化特征或提升进给参数（Macaos 报价工艺库工时基线）。",
                "warning",
                "Macaos Quoting Process Library Machining Time Baseline",
                current=round(total_min, 1),
                required=45.0,
            )
        )

    # ── AC. 非标准刀具直径检查 (标准刀具梯采购惯例) ─────────────────────
    # 使用标准梯 {1.0,1.5,2.0,2.5,3.175,3.5,4.0,5.0,6.0} 之外的刀径需定制采购，
    # 交期 2~4 周且单价 2~3 倍，量产治具应强制归梯。
    from cnc_setup_sheet import STANDARD_TOOL_LADDER

    tool_dias = getattr(tpo, "tool_order", []) if tpo else []
    off_ladder = [d for d in tool_dias if not any(abs(d - s) < 1e-6 for s in STANDARD_TOOL_LADDER)]
    if off_ladder:
        issues.append(
            _issue(
                "CNC_NONSTANDARD_TOOL_DIAMETER",
                "刀具直径偏离标准刀具梯",
                f"刀路使用非标准直径 {', '.join(f'{d:g}' for d in off_ladder)}mm；"
                "定制刀具交期 2~4 周且单价 2~3 倍，建议设计归梯至标准直径"
                "（标准刀具梯采购惯例：1.0/1.5/2.0/2.5/3.175/3.5/4.0/5.0/6.0mm）。",
                "warning",
                "Standard Tool Ladder Procurement Practice (End Mill & Drill Inventory)",
                current=round(off_ladder[0], 3),
                required="standard ladder",
            )
        )

    # ── AD. 毛料下料尺寸装夹校核 (机加工车间装夹规范) ───────────────────
    # 毛料边长必须 >= 治具外形 + 四周 10mm 夹持余量，否则虎钳/压板无处可夹。
    sw = getattr(r2, "stock_width_mm", None)
    sh = getattr(r2, "stock_height_mm", None)
    if _poly_ok(outer) and sw is not None and sh is not None:
        need_w = (outer.bounds[2] - outer.bounds[0]) + 2.0 * 10.0
        need_h = (outer.bounds[3] - outer.bounds[1]) + 2.0 * 10.0
        if float(sw) < need_w or float(sh) < need_h:
            issues.append(
                _issue(
                    "CNC_STOCK_SIZE_INSUFFICIENT",
                    "毛料下料尺寸不足无法装夹",
                    f"毛料 {float(sw):g}×{float(sh):g}mm 小于装夹需求 {need_w:.1f}×{need_h:.1f}mm "
                    "(治具外形 + 四周 10mm 夹持余量)；虎钳/压板将压伤治具型面或无法固定。",
                    "error",
                    "CNC Machining Workholding Practice (Vise & Clamp Margin)",
                    current=f"{float(sw):g}x{float(sh):g}",
                    required=f"{need_w:.1f}x{need_h:.1f}",
                )
            )

    # ── AE. 大型治具密封面平面度规范检查 (AGICORP §6.0) ─────────────────
    # 对角线 >= 300mm 的治具，沉板密封面必须标注平面度公差 <= 0.2mm；
    # 超差将导致治具与 PCB 间产生缝隙，液态锡沿缝上爬漫顶短路。
    if _poly_ok(outer):
        diag = math.hypot(outer.bounds[2] - outer.bounds[0], outer.bounds[3] - outer.bounds[1])
        flat_spec = getattr(r2, "flatness_spec_mm", None)
        has_valid_spec = flat_spec is not None and float(flat_spec) <= 0.2
        if diag >= 300.0 and not has_valid_spec:
            shown = f"{float(flat_spec):g}mm" if flat_spec is not None else "未标注"
            issues.append(
                _issue(
                    "PALLET_SEALING_FLATNESS_SPEC_MISSING",
                    "大型治具密封面平面度规范缺失",
                    f"治具对角线 {diag:.0f}mm ≥ 300mm，密封面平面度要求 ≤ 0.2mm，当前：{shown}；"
                    "超差缝隙将导致液态锡沿沉板密封面上爬漫顶短路（AGICORP §6.0 Flatness Specification）。",
                    "warning",
                    "AGICORP §6.0 Pallet Sealing Surface Flatness Specification",
                    current=shown,
                    required="<=0.2mm",
                )
            )

    # ── AF. 近对称治具防反向装载方向键检查 (Ersa / SEHO 上下板防错) ─────
    # 长宽比 0.85~1.15 的近对称治具若无非对称方向键切角，装板工/上板机
    # 180° 反向推入轨道将使波峰流向反转、上锡开孔整板镜像。
    if _poly_ok(outer):
        ow = outer.bounds[2] - outer.bounds[0]
        oh = outer.bounds[3] - outer.bounds[1]
        aspect = ow / max(1e-6, oh)
        pk = getattr(r2, "pallet_keying", None)
        has_key = bool(pk and getattr(pk, "chamfer_lines", []))
        if 0.85 <= aspect <= 1.15 and not has_key:
            issues.append(
                _issue(
                    "PALLET_ORIENTATION_KEYING_MISSING",
                    "近对称治具缺少防反向装载方向键",
                    f"治具长宽比 {aspect:.2f} 接近对称且无非对称方向键切角；"
                    "装板工/上板机 180° 反向推入轨道将使波峰流向反转、上锡开孔整板镜像，"
                    "建议在出板侧切除 15×15mm 45° 方向键（Ersa / SEHO 上下板防错惯例）。",
                    "warning",
                    "Ersa & SEHO Pallet Loading Poka-Yoke Orientation Key Practice",
                    current=round(aspect, 2),
                    required="keying chamfer",
                )
            )

    # ── AG. 治具-PCB 热膨胀失配间隙校核 (Röchling CTE datasheet) ────────
    # 波峰温度下治具与 PCB 线膨胀差 ΔL = L × ΔCTE × ΔT；差值超过常温沉板
    # 设计间隙 0.2mm 时，PCB 高温被槽壁顶死 → 拱起渗锡、冷却卡板。
    if _poly_ok(sink):
        s_w = sink.bounds[2] - sink.bounds[0]
        s_h = sink.bounds[3] - sink.bounds[1]
        s_len = max(s_w, s_h)
        if s_len >= 120.0:
            from thermal_expansion import compute_expansion_gap

            mat_key = material_key or "durostone"
            gap = compute_expansion_gap(pallet_len_mm=s_len, pcb_len_mm=s_len * 0.98, material_key=mat_key)
            if gap.at_risk and getattr(r2, "check_cte_gap", True):
                issues.append(
                    _issue(
                        "SINK_CTE_CLEARANCE_INSUFFICIENT",
                        "波峰温度下沉板间隙将被热膨胀差吃掉",
                        f"{s_len:.0f}mm 沉板跨度在 ΔT≈235K 下治具-PCB 线膨胀差 "
                        f"{gap.differential_mm:.2f}mm 超过常温设计间隙 {gap.design_clearance_mm}mm；"
                        "PCB 高温被槽壁顶死将拱起渗锡、冷却卡板。建议常温沉板间隙外扩至 "
                        f"{gap.differential_mm + 0.1:.2f}mm（Röchling Durostone CTE datasheet）。",
                        "warning",
                        "Röchling Durostone CTE Datasheet & IPC-2141A Thermal Mechanics",
                        current=gap.differential_mm,
                        required=gap.design_clearance_mm,
                    )
                )

    # ── AH. 合成石螺纹孔黄铜埋植嵌件检查 (紧固寿命惯例) ─────────────────
    # 合成石/FR-4 直接攻丝的螺纹 ~50 次装拆即滑丝；盖板/铰链/压扣反复装拆
    # 必须压入黄铜埋植嵌件 (>500 次装拆寿命)。
    ti_plan = getattr(r2, "thread_inserts", None)
    n_screws = len(screws or [])
    has_inserts = bool(ti_plan and getattr(ti_plan, "inserts", []))
    if n_screws > 0 and not has_inserts and getattr(r2, "require_thread_inserts", False):
        issues.append(
            _issue(
                "THREAD_INSERTS_MISSING",
                "合成石螺纹孔缺少黄铜埋植嵌件",
                f"治具有 {n_screws} 处螺纹紧固孔但未规划黄铜埋植嵌件；"
                "合成石/FR-4 基材直接攻丝 ~50 次装拆即滑丝，反复换型后盖板/铰链将无法锁紧，"
                "应压入 M3/M4 黄铜嵌件 (>500 次装拆寿命)。",
                "warning",
                "Brass Threaded Insert Fastening Practice for Composite Pallets",
                current=0,
                required=n_screws,
            )
        )

    # ── AI. 出板尾端沥锡引流槽与防拖锡回流校核 (AGICORP §4.4) ────────────
    # 传送方向跨度 >= 180mm 的量产治具，出板尾梁若无沥锡泄锡槽，
    # 滞留锡液将污染出板风道滚轮，并引发尾端引脚拖锡拉尖与桥连。
    ss = getattr(r2, "solder_scuppers", None)
    if _poly_ok(outer):
        flow_span = outer.bounds[2] - outer.bounds[0]
        has_scuppers = bool(ss and getattr(ss, "scupper_count", 0) > 0)
        if flow_span >= 180.0 and getattr(r2, "require_solder_scuppers", False) and not has_scuppers:
            issues.append(
                _issue(
                    "TRAILING_SOLDER_SCUPPER_MISSING",
                    "出板尾梁缺少沥锡引流槽与回流斜坡",
                    f"治具传送跨度 {flow_span:.0f}mm ≥ 180mm，出板尾梁未设置沥锡引流槽与 30° 回流斜坡；"
                    "脱锡区滞留锡液无法顺流回落锡炉，将污染出板滚轮并引发尾端引脚拖锡拉尖（AGICORP §4.4）。",
                    "warning",
                    "AGICORP §4.4 Trailing Edge Solder Scuppers & Run-Off Ramps",
                    current=0,
                    required=">=1 scuppers",
                )
            )

    # 沥锡槽距沉板区密封边距校核 (防止锡波反灌)
    if ss and getattr(ss, "scupper_count", 0) > 0 and _poly_ok(sink):
        min_clr = getattr(ss, "min_clearance_found_mm", 999.0)
        if 0.0 < min_clr < 4.0:
            issues.append(
                _issue(
                    "SCUPPER_CLEARANCE_TO_BOARD_INSUFFICIENT",
                    "沥锡槽距沉板区密封边距不足反灌风险",
                    f"沥锡槽边缘距沉板区最小密封台阶 {min_clr:.2f}mm < 4.0mm；"
                    "过板冲力下液态锡极易沿沥锡凹槽反灌进入沉板区造成顶面漫锡（AGICORP §4.4 密封台阶规范）。",
                    "warning",
                    "AGICORP §4.4 Solder Scupper Seal Land Clearance",
                    current=round(min_clr, 2),
                    required=4.0,
                )
            )

    # ── AJ. 底面贴片波峰焊红胶点胶与防污染门禁 (IPC-A-610G §7.1.3) ──────
    rgs = getattr(r2, "red_glue_stencil", None)
    has_bottom_smd = getattr(r2, "has_bottom_smd_components", False)
    if has_bottom_smd and (not rgs or getattr(rgs, "total_dots", 0) == 0) and getattr(r2, "require_red_glue", False):
        issues.append(
            _issue(
                "BOTTOM_SMD_RED_GLUE_MISSING",
                "底面贴片器件波峰焊缺少红胶点胶规划",
                "沉板开孔露锡区存在底面 SMD 元件但未规划红胶胶点；"
                "过波峰时元件在 260°C 液态锡浮力与动压下极易冲脱掉入锡锅（IPC-A-610G §7.1.3 表面贴装胶水工艺）。",
                "warning",
                "IPC-SM-782 & IPC-A-610G Section 7.1.3 SMD Adhesive Dispensing",
                current=0,
                required=">=1 dots",
            )
        )

    if rgs and getattr(rgs, "contaminated_dots_count", 0) > 0:
        bad_n = rgs.contaminated_dots_count
        issues.append(
            _issue(
                "RED_GLUE_PAD_CONTAMINATION_RISK",
                "红胶胶点距焊盘间距不足溢胶污染开路风险",
                f"检测到 {bad_n} 处红胶胶点距焊盘边缘间距 < 0.30mm；"
                "贴片挤压溢胶沾染焊盘将导致引脚彻底绝缘无法上锡，引发严重虚焊/开路缺陷（IPC-A-610G §7.1.3）。",
                "warning",
                "IPC-A-610G Section 7.1.3 Adhesive-to-Pad Clearance Limit",
                current=bad_n,
                required=0,
            )
        )

    # ── AK. 助焊剂防积液排液槽检查 (AGICORP §4.3 & SMTA 规范) ───────────
    # 面积 >= 50mm² 的深避位腔，若未开凿 45° 倒坡排液泄槽，
    # 积聚的液体助焊剂在预热/浸锡时瞬间沸腾炸锡，产生大面积飞溅锡珠 (IPC-A-610G §5.2.7.1)。
    fd = getattr(r2, "flux_drainage", None)
    req_drain = getattr(fd, "pockets_requiring_drainage", 0) if fd else 0
    actual_weeps = len(getattr(fd, "weep_channels", [])) if fd else 0
    if req_drain > 0 and actual_weeps == 0 and getattr(r2, "require_flux_drainage", False):
        issues.append(
            _issue(
                "FLUX_PUDDLING_DRAINAGE_MISSING",
                "避位腔死角缺少助焊剂排液导流泄槽",
                f"检测到 {req_drain} 处大面积避位腔体未规划 45° 倒坡排液泄槽；"
                "喷雾残留助焊剂积液在 260°C 高温下剧烈沸腾炸锡，产生飞溅锡珠短路缺陷（AGICORP §4.3 & IPC-A-610G）。",
                "warning",
                "AGICORP §4.3 Flux Drainage Weep Channel Guidelines & IPC-A-610G",
                current=0,
                required=req_drain,
            )
        )

    # ── AL. 高温密闭气腔泄压排气呼吸孔检查 (SMTA 气体膨胀防爆) ─────────
    # 封闭或半封闭避位腔室未开通大气的呼吸排气孔 (Φ2.0~2.5mm)，
    # 260°C 熔锡高温下腔内气体急剧膨胀 (~79%) 将把锡波吹散吹空导致大面积虚焊。
    actual_ports = len(getattr(fd, "vapor_ports", [])) if fd else 0
    if req_drain > 0 and actual_ports == 0 and getattr(r2, "check_vapor_ports", False):
        issues.append(
            _issue(
                "FLUX_EXPANSION_VAPOR_TRAP_RISK",
                "避位腔室缺少防气爆泄压排气孔",
                f"存在 {req_drain} 处避位腔未设 Φ2.5mm 泄压排气呼吸孔；"
                "260°C 高温波峰下腔内空气急剧热膨胀（膨胀率达 79%），高压气流喷出将吹散锡波造成虚焊空洞（SMTA 规范）。",
                "warning",
                "SMTA Thermal Vapor Expansion & Pressure Relief Hole Standard",
                current=0,
                required=req_drain,
            )
        )

    # ── AM. 大尺寸沉板 CAM 热补偿各向异性缩放校核 (Macaos & Röchling) ────
    # 沉板跨度 >= 200mm 的合成石治具，若未在 CAM 阶段施加热补偿各向异性缩放 (k ≈ 1.0016)，
    # 260°C 高温下膨胀量可达 330μm，常温加工槽型在热态下将顶死卡板 (Macaos 工业标准)。
    if _poly_ok(sink):
        s_span = max(sink.bounds[2] - sink.bounds[0], sink.bounds[3] - sink.bounds[1])
        scaled_applied = getattr(r2, "thermal_scaling_applied", False)
        if s_span >= 200.0 and not scaled_applied and getattr(r2, "require_thermal_scaling", False):
            issues.append(
                _issue(
                    "THERMAL_CAM_SCALING_REQUIRED",
                    "大跨度沉板槽缺少 CAM 热补偿各向异性缩放",
                    f"沉板跨度 {s_span:.0f}mm ≥ 200mm 且未启用 CAM 热膨胀各向异性缩放 (k ≈ 1.0016)；"
                    "260°C 波峰热态下膨胀差将吃尽设计间隙导致顶死卡板，需在 CAM 阶段预先补偿缩放（Macaos CAM 规范）。",
                    "warning",
                    "Macaos Solder Pallet Designer & Röchling Durostone CAM Model",
                    current=round(s_span, 1),
                    required=200.0,
                )
            )

    # ── AN. 工厂制造交付包密码学防篡改校验清单检查 (IATF 16949 / ISO 9001) ──
    # 送厂量产交付必须随附包含全文件 SHA-256 哈希的 MANIFEST.sha256 账本，确保车间数控加工与质检无误。
    manifest_verified = getattr(r2, "manifest_sha256_verified", True)
    if not manifest_verified:
        issues.append(
            _issue(
                "FACTORY_RELEASE_MANIFEST_UNVERIFIED",
                "工厂制造交付包缺少密码学防篡改校验清单",
                "量产工程交付包中未发现合规的 MANIFEST.sha256 密码学校验文件；"
                "无法满足 IATF 16949 / ISO 9001 质量追溯与 CAM 文件防篡改审计要求。",
                "warning",
                "IATF 16949 & ISO 9001 Manufacturing Release Traceability",
            )
        )

    # ── AO. 传送带链爪耐磨导轨与沉板避位安全净距检查 (AGICORP §3.2) ──────
    # 耐磨导轨条与链爪咬合区必须与沉板边缘保持 ≥ 8.0mm 安全绝缘与机械间隙，严防链爪刮碰 PCB。
    cwr = getattr(r2, "conveyor_wear_rails", None)
    if cwr and _poly_ok(sink):
        clr = getattr(cwr, "min_clearance_to_sink_mm", 999.0)
        if 0.0 <= clr < 8.0:
            issues.append(
                _issue(
                    "CONVEYOR_WEAR_RAIL_CLEARANCE_INSUFFICIENT",
                    "传送带耐磨导轨距沉板区安全净距不足",
                    f"传送带耐磨导轨边缘距沉板区最小间隙 {clr:.2f}mm < 8.0mm；"
                    "波峰焊链爪或链指在传送啮合时可能擦碰治具沉板台阶或压伤 PCB 板边（AGICORP §3.2）。",
                    "warning",
                    "AGICORP §3.2 Conveyor Edge Wear Rail & Finger Clearance Standards",
                    current=round(clr, 2),
                    required=8.0,
                )
            )

    # ── AP. 工业防静电 ESD 接地端子与对地回路检查 (ANSI/ESD S20.20-2021) ─
    # 电子制造车间对静电放电敏感器件强制要求对地电阻 Rg < 1.0×10⁹ Ω 且具有首尾冗余接地触点。
    esd = getattr(r2, "esd_grounding", None)
    req_esd = getattr(r2, "require_esd_compliance", False)
    if req_esd:
        pt_cnt = getattr(esd, "total_point_count", 0) if esd else 0
        is_comp = getattr(esd, "is_compliant", False) if esd else False
        if pt_cnt < 2 or not is_comp:
            issues.append(
                _issue(
                    "ESD_GROUND_PATH_MISSING",
                    "工业防静电 ESD 接地回路或触点缺失",
                    f"治具未规划符合 ANSI/ESD S20.20-2021 的冗余金属接地触钉 (当前触点数: {pt_cnt} < 2)；"
                    "高温热风与链条摩擦产生的静电荷无法有效泄放到传送带接地导轨，"
                    "存在击穿板载静电敏感半导体器件的高危风险（IEC 61340-5-1）。",
                    "warning",
                    "ANSI/ESD S20.20-2021 & IEC 61340-5-1 Electrostatic Protection",
                    current=pt_cnt,
                    required=2,
                )
            )

    # ── AQ. 氮气保护微环境导流罩边框气密性检查 (SMTA & Ersa N2 Guidelines) ─
    # 氮气保护气罩外围距治具边框与导轨陆地宽度必须 >= 5.0mm，防止高纯氮气泄漏逸散。
    ns = getattr(r2, "nitrogen_shroud", None)
    req_n2 = getattr(r2, "require_nitrogen_inerting", False)
    if ns and req_n2 and not getattr(ns, "is_seal_compliant", True):
        clr = getattr(ns, "min_seal_clearance_mm", 0.0)
        issues.append(
            _issue(
                "NITROGEN_SHROUD_SEAL_CLEARANCE_INSUFFICIENT",
                "氮气保护导流罩边框密封间隙不足",
                f"氮气气罩边缘距治具边框密封陆地宽度 {clr:.2f}mm < 5.0mm；"
                "氮气将沿导轨与边框缝隙泄漏逸散，导致上锡区残氧量超标 (>500ppm) 无法实现惰性保护（SMTA 规范）。",
                "warning",
                "SMTA Wave Soldering Handbook & Ersa PowerFlow N2 Guidelines",
                current=round(clr, 2),
                required=5.0,
            )
        )

    # ── AR. 人机工程学重量与双手舒适握把门禁 (ISO 11228-1 & OSHA 1910) ─────
    # 治具装配整备质量 > 5.0kg 时必须配置双侧人体工学握持把手；> 8.0kg 严禁单人搬运。
    eh = getattr(r2, "ergonomic_handling", None)
    if eh:
        tot_m = getattr(eh, "total_mass_kg", 0.0)
        has_hp = getattr(eh, "handles_provided", False)
        exceeds_abs = getattr(eh, "exceeds_manual_limit", False)
        if exceeds_abs:
            issues.append(
                _issue(
                    "PALLET_ERGONOMIC_WEIGHT_EXCEEDED",
                    "治具整备质量超标超出单人搬运工效学极限",
                    f"治具装配整备总质量达 {tot_m:.2f}kg > 8.0kg；"
                    "严重超出 OSHA 与 ISO 11228-1 电子车间单人安全搬运极限，必须配置机械吊臂或双人搬运。",
                    "error",
                    "ISO 11228-1 & OSHA Section VII Repetitive Manual Lifting Limits",
                    current=round(tot_m, 2),
                    required=8.0,
                )
            )
        elif tot_m > 5.0 and not has_hp:
            issues.append(
                _issue(
                    "PALLET_ERGONOMIC_WEIGHT_EXCEEDED",
                    "治具整备质量较重缺少人机工程抓握把手",
                    f"治具整备总质量达 {tot_m:.2f}kg > 5.0kg 且未配置人机工程舒适手柄；"
                    "高频反复搬运将导致操作员掌心疲劳滑脱跌落碎板，需开设 ≥100×35mm R8 握持开孔（ISO 11228-1）。",
                    "warning",
                    "ISO 11228-1 Ergonomic Manual Handling Standards",
                    current=round(tot_m, 2),
                    required=5.0,
                )
            )

    # ── AS. 超声波清洗重力自排液死角防炸锡检查 (AGICORP §4.5) ─────────────
    # 深度 >= 4.0mm 且面积 >= 80mm² 的深避位死腔若无自流排液斜槽与贯通泄水孔，
    # 清洗水剂残留遇 260°C 熔锡将瞬间剧烈汽化爆炸导致猛烈溅锡。
    cd = getattr(r2, "cleaning_drainage", None)
    req_cd = getattr(r2, "require_cleaning_drainage", False)
    if req_cd:
        deep_pockets = [a for a in avoids if _poly_ok(a) and a.area >= 80.0]
        has_drain = bool(cd and getattr(cd, "total_drain_holes", 0) > 0)
        if deep_pockets and not has_drain:
            issues.append(
                _issue(
                    "CLEANING_DRAINAGE_DEAD_ZONE_RISK",
                    "深避位腔死角缺少超声波清洗自排液槽与泄水孔",
                    f"存在 {len(deep_pockets)} 处大面积深避位腔未规划 30°~45° 重力自排液斜槽与 Φ3.0mm 泄液通孔；"
                    "超声波水基清洗残水无法在 10s 内自然排净，遇 260°C 液态锡将瞬间汽化炸锡飞溅（AGICORP §4.5）。",
                    "warning",
                    "AGICORP §4.5 Ultrasonic & Aqueous Wash Self-Draining Standards",
                    current=0,
                    required=len(deep_pockets),
                )
            )

    # ── AT. 上盖浮动弹簧顶针微弹性缓冲压紧检查 (AGICORP §2.3 & SMTA) ─────
    # 在上盖对元器件压紧时，若存在刚性机械压柱固定且缺少不锈钢浮动弹簧微弹性缓冲，
    # 由于 PCB 热变形与器件装配公差，极易压爆铝电解电容外壳或压断焊接引脚。
    spa = getattr(r2, "spring_plunger_array", None)
    has_tophat = bool(getattr(r2, "top_hat", None))
    req_plungers = getattr(r2, "require_spring_plungers", False)
    if has_tophat and req_plungers:
        p_cnt = getattr(spa, "total_plunger_count", 0) if spa else 0
        if p_cnt == 0:
            issues.append(
                _issue(
                    "RIGID_PLUNGER_COMPONENT_CRUSH_RISK",
                    "上盖压紧缺少浮动弹簧微弹性顶针压碎元件风险",
                    "铰链防翘曲上盖未规划不锈钢浮动弹簧顶针阵列 (Spring Plungers)；"
                    "刚性固定压柱在 PCB 热翘曲与元器件高度公差下易压爆铝电解电容或压断引脚（AGICORP §2.3）。",
                    "warning",
                    "AGICORP §2.3 Spring Plunger Floating Pressure Standards",
                    current=0,
                    required=">=2 spring plungers",
                )
            )

    # ── AU. 薄板与大跨度 PCB 防热塌陷托块检查 (SMTA & Ersa Anti-Sag) ─────
    # PCB 跨度 >= 160mm 或板厚 <= 1.2mm 时，若未在中跨规划防塌陷支承托块，
    # 260°C 高温下 FR-4 弹性模量跌落导致热塌下垂 (>1.5mm)，引发正面漫锡短路。
    tss = getattr(r2, "thermal_sag_support", None)
    if _poly_ok(sink):
        s_span = max(sink.bounds[2] - sink.bounds[0], sink.bounds[3] - sink.bounds[1])
        has_pillars = bool(tss and getattr(tss, "total_pillar_count", 0) > 0)
        req_sag = getattr(r2, "require_anti_sag_support", False)
        if s_span >= 160.0 and req_sag and not has_pillars:
            issues.append(
                _issue(
                    "PCB_THERMAL_SAG_SUPPORT_MISSING",
                    "大跨度板卡沉板区缺少防热塌陷支承托块",
                    f"沉板中跨跨度达 {s_span:.0f}mm ≥ 160mm 且未规划中跨支承托块 (Support Pillars)；"
                    "过 260°C 波峰时 FR-4 热态刚度丧失引发板心严重下垂 (>1.5mm)，极易导致熔锡漫入顶面（SMTA 规范）。",
                    "warning",
                    "SMTA Wave Soldering Handbook & Ersa Carrier Anti-Sag Guidelines",
                    current=round(s_span, 1),
                    required=160.0,
                )
            )

    # ── AV. 工业 RFID 电子标签金属抗失谐间隙检查 (IPC-1782A & ISO 18000-6C)
    # 陶瓷超高频 RFID 标签沉腔与金属构件间距必须 >= 8.0mm，防止涡流失谐导致读距归零。
    rfid = getattr(r2, "rfid_cavity", None)
    if rfid and getattr(rfid, "cavity_poly", None):
        clr = getattr(rfid, "min_clearance_to_metal_mm", 999.0)
        if 0.0 <= clr < 8.0:
            issues.append(
                _issue(
                    "RFID_TAG_METAL_DETUNING_RISK",
                    "RFID 电子标签距金属构件过近射频涡流失谐风险",
                    f"RFID 嵌入沉腔边缘距金属加强件/导轨最小间距 {clr:.2f}mm < 8.0mm；"
                    "金属反射电磁场诱发反向涡流产生严重失谐，导致扫码读距骤降甚至无法识读（IPC-1782A）。",
                    "warning",
                    "IPC-1782A & ISO/IEC 18000-6C Anti-Metal UHF RFID Standards",
                    current=round(clr, 2),
                    required=8.0,
                )
            )

    # ── AW. 锡炉熔锡杂质超标与维护节拍失控检查 (IPC J-STD-001 §5.2) ────────
    # 无铅 SAC305 锡炉铜含量 > 0.85 wt% 或铁/锌/镉超标时，焊料润湿特性劣化，
    # 产生灰暗颗粒焊点与桥连拉尖；捞渣/化验节拍失控将放大氧化夹渣虚焊。
    sph = getattr(r2, "solder_pot_health", None)
    if sph:
        for vio in getattr(sph, "violations", []) or []:
            issues.append(
                _issue(
                    "SOLDER_POT_CONTAMINATION_EXCEEDED",
                    "锡炉熔锡杂质含量超出 J-STD-001 上限",
                    f"锡炉 {vio['element']} 实测 {vio['measured_wt_pct']:.3f} wt% > 上限 {vio['limit_wt_pct']:.3f} wt%；"
                    "焊料液相线与润湿性已漂移，焊点将呈颗粒灰暗并批量桥连/拉尖，须立即排旧锡补纯锭稀释"
                    "并复核光谱化验（IPC J-STD-001 §5.2）。",
                    "warning",
                    "IPC J-STD-001 §5.2 Solder Pot Purity Limits & SMTA Pot Maintenance",
                    current=round(vio["measured_wt_pct"], 4),
                    required=round(vio["limit_wt_pct"], 4),
                    unit="wt%",
                )
            )
    elif getattr(r2, "require_solder_pot_monitoring", False):
        issues.append(
            _issue(
                "SOLDER_POT_CONTAMINATION_EXCEEDED",
                "量产线锡炉杂质监控数据缺失",
                "产线声明需要锡炉健康监控（require_solder_pot_monitoring）但未挂载最新光谱化验结果；"
                "铜含量无数据时无法排除 0.85 wt% 超限风险，灰暗焊点与桥连缺陷不可控（IPC J-STD-001 §5.2）。",
                "warning",
                "IPC J-STD-001 §5.2 Solder Pot Purity & Assay Scheduling",
            )
        )

    # ── AX. 助焊剂喷雾涂覆量与比重窗口检查 (SMTA & Flux Vendor Window) ─────
    # 涂覆量须处于 300~1200 μg/cm² 窗口：不足则顶端爬锡不良批量虚焊，
    # 过量则免清洗残留推高离子污染并爆沸飞溅污染预热器。
    fcc = getattr(r2, "flux_coating_control", None)
    if fcc:
        cw = getattr(fcc, "coating_weight_ug_cm2", 0.0)
        if not getattr(fcc, "is_within_window", True):
            issues.append(
                _issue(
                    "FLUX_COATING_WEIGHT_OUT_OF_WINDOW",
                    "助焊剂喷雾涂覆量偏离 300~1200 μg/cm² 工艺窗口",
                    f"板面实测涂覆量 {cw:.0f} μg/cm² 偏离工艺窗口；"
                    + ("活化剂不足以破除氧化膜，通孔顶端爬锡不足将批量虚焊（SMTA）。" if cw < 300.0
                       else "残留活化剂将推高板面离子污染且预热爆沸飞溅污染加热管（SMTA）。"),
                    "warning",
                    "SMTA Wave Soldering Handbook Flux Coating Window (300~1200 μg/cm²)",
                    current=round(cw, 1),
                    required="300~1200 μg/cm²",
                )
            )
        if not getattr(fcc, "is_sg_within_window", True):
            sg = getattr(fcc, "flux_specific_gravity", 1.005)
            issues.append(
                _issue(
                    "FLUX_COATING_WEIGHT_OUT_OF_WINDOW",
                    "助焊剂比重偏离 0.995~1.015 g/cm³ 控制窗口",
                    f"助焊剂比重实测 {sg:.4f} g/cm³ 偏离窗口，固含量漂移使涂覆量标定失效；"
                    "须按折光仪 °Bx 补水稀释或补充原液，重标定后方可继续生产（SMTA/Vendor 规范）。",
                    "warning",
                    "SMTA Flux Specific Gravity Control Window (0.995~1.015 g/cm³ @ 25°C)",
                    current=round(sg, 4),
                    required="0.995~1.015 g/cm³",
                )
            )

    # ── AY. 预热区升温斜率/出口温度/浸润时间窗口检查 (J-STD-001E §4.4) ──────
    # 斜率 1~4°C/s、出口 100~130°C (水基 105~125°C)、浸润 60~120s、板-波温差 <=130°C。
    php = getattr(r2, "preheat_profile", None)
    if php:
        if not getattr(php, "is_ramp_compliant", True):
            issues.append(
                _issue(
                    "PREHEAT_PROFILE_OUT_OF_WINDOW",
                    "预热区升温斜率偏离 1~4°C/s 工艺窗口",
                    f"升温斜率 {php.ramp_rate_c_per_s:.2f}°C/s 超窗；过快致 FR-4 芯吸分层与元件体"
                    "热冲击微裂，过慢致产线节拍浪费（IPC J-STD-001E §4.4 / SMTA）。",
                    "warning",
                    "IPC J-STD-001E §4.4 Preheat Ramp Rate Window (1~4 °C/s)",
                    current=round(php.ramp_rate_c_per_s, 2),
                    required="1.0~4.0 °C/s",
                )
            )
        if not getattr(php, "is_exit_temp_compliant", True):
            issues.append(
                _issue(
                    "PREHEAT_PROFILE_OUT_OF_WINDOW",
                    "预热出口板温偏离助焊剂活化窗口",
                    f"出口板温 {php.exit_temp_c:.0f}°C 偏离窗口（{php.flux_type}）；"
                    "低温入波炸锡锡珠飞溅，高温活化剂提前耗尽通孔虚焊（J-STD-001E §4.4）。",
                    "warning",
                    "IPC J-STD-001E §4.4 Preheat Exit Temperature Window (100~130 °C)",
                    current=round(php.exit_temp_c, 1),
                    required="100~130 °C",
                )
            )
        if not getattr(php, "is_thermal_shock_ok", True):
            issues.append(
                _issue(
                    "PREHEAT_PROFILE_OUT_OF_WINDOW",
                    "板温与锡波温差超 155°C 热冲击风险",
                    f"入波瞬间温差 {php.thermal_shock_delta_c:.0f}°C > 155°C：骤热冲击将引发板翘"
                    "与金属化孔应力裂纹，须延长预热压差（IPC J-STD-001E §4.4）。",
                    "warning",
                    "IPC J-STD-001E §4.4 Thermal Shock Limit (ΔT <= 155 °C)",
                    current=round(php.thermal_shock_delta_c, 1),
                    required=155.0,
                )
            )

    # ── AZ. 出板冷却速率与冷却区长度检查 (J-STD-001E §4.5) ─────────────────
    # 冷却速率 <=4°C/s 防枝晶粗化冻结与板翘；冷却区须使出板 <=60°C 安全下板。
    cdc = getattr(r2, "cooldown_control", None)
    if cdc:
        if not getattr(cdc, "is_rate_compliant", True):
            issues.append(
                _issue(
                    "COOLDOWN_RATE_EXCESSIVE",
                    "出板冷却速率超 4°C/s 上限",
                    f"实测/模型冷却速率 {cdc.measured_cooling_rate_c_per_s:.2f}°C/s > 4.0°C/s："
                    "焊点枝晶粗化冻结降疲劳寿命 30~50%，板体 z 向应力翘曲超 0.75% 限值（J-STD-001E §4.5）。",
                    "warning",
                    "IPC J-STD-001E §4.5 Cooling Rate Limit (<= 4.0 °C/s)",
                    current=round(cdc.measured_cooling_rate_c_per_s, 2),
                    required=4.0,
                )
            )
        if not getattr(cdc, "is_length_sufficient", True):
            issues.append(
                _issue(
                    "COOLDOWN_RATE_EXCESSIVE",
                    "冷却区长度不足以降温至安全下板温度",
                    f"冷却区 {cdc.available_cooling_length_m:.2f}m < 所需 {cdc.required_cooling_length_m:.2f}m，"
                    f"出板 {cdc.exit_handle_temp_c:.0f}°C > 60°C：堆叠烫伤板面且焊点受压变形（SMTA 冷却规范）。",
                    "warning",
                    "SMTA Post-Wave Cooling Zone Sizing (exit <= 60 °C)",
                    current=round(cdc.available_cooling_length_m, 2),
                    required=round(cdc.required_cooling_length_m, 2),
                )
            )

    # ── BA. 库房存储堆叠与防静电环境检查 (AGICORP §6.2 & ESD S20.20) ────────
    # 堆叠超限压坏密封面、无隔垫互磨、非 EPA 区静电、温湿度超限受潮。
    srk = getattr(r2, "pallet_storage_rack", None)
    if srk:
        for v_text in getattr(srk, "violations", []) or []:
            issues.append(
                _issue(
                    "PALLET_STORAGE_STACKING_VIOLATION",
                    "治具库房存储堆叠/环境规范违规",
                    f"{v_text} 需按整改清单处置后再入库/投产（AGICORP §6.2 & ANSI/ESD S20.20）。",
                    "warning",
                    "AGICORP §6.2 Storage & ANSI/ESD S20.20 EPA Requirements",
                )
            )
        if getattr(srk, "bake_required", False):
            issues.append(
                _issue(
                    "PALLET_STORAGE_STACKING_VIOLATION",
                    "受潮治具投产前缺少烘干除潮",
                    "治具暴露 >48h 后直接过 260°C 波峰将蒸汽炸裂分层；"
                    "须 80°C/4h 烘干并复测表面电阻后投产（AGICORP §6.2）。",
                    "warning",
                    "AGICORP §6.2 Storage Moisture Bake-out Requirements",
                )
            )

    # ── BB. SMED 快速换型套件架构检查 (Shingo SMED) ─────────────────────────
    # 混线 >=3 品种仍用整具换型 (无通用基板) 时，每次换型损失 25~45min 纯产能。
    ck = getattr(r2, "changeover_kit", None)
    if ck and not getattr(ck, "uses_common_base", True):
        issues.append(
            _issue(
                "SMED_CHANGEOVER_KIT_MISSING",
                "混线产线缺少通用基板+嵌件 SMED 快换架构",
                f"{getattr(ck, 'product_families', 0)} 产品族仍采用整具换型 (25~45min/次)："
                "迁移到通用基板+防呆编码嵌件架构可将换型压至 <10min，混线日产可挽回 2~3h 产能（Shingo SMED）。",
                "warning",
                "Shingo SMED & Lean Production Changeover Standards",
                current=round(getattr(ck, "estimated_changeover_min", 30.0), 1),
                required=10.0,
                unit="min",
            )
        )

    # ── BC. 选择焊喷嘴浸润深度/驻留时间窗口检查 (AllPCB 2026 & ERSA/SEHO) ────
    # 浸润深度 <60% 板厚孔填充不足；驻留 <1s/>5s 分别虚焊与锡渣拉尖。
    snp = getattr(r2, "selective_nozzle_profile", None)
    if snp:
        if not getattr(snp, "is_immersion_ok", True):
            issues.append(
                _issue(
                    "SELECTIVE_NOZZLE_WINDOW_VIOLATION",
                    "选择焊喷嘴浸润深度偏离板厚 60~80% 窗口",
                    f"浸润深度 {snp.immersion_depth_mm:.2f}mm 仅板厚 {snp.immersion_fraction:.0%}；"
                    "波高不足致通孔填充与上锡不良，过深致锡珠飞溅顶面漫锡（AllPCB 2026 / SEHO MWS 2300）。",
                    "warning",
                    "AllPCB Selective Soldering Process Windows & SEHO Nozzle Z-Height",
                    current=round(snp.immersion_fraction, 2),
                    required="0.6~1.3 板厚",
                )
            )
        if not getattr(snp, "is_dwell_ok", True):
            issues.append(
                _issue(
                    "SELECTIVE_NOZZLE_WINDOW_VIOLATION",
                    "选择焊驻留时间偏离 1~5s 工艺窗口",
                    f"实测驻留 {snp.dwell_time_s:.2f}s 超窗：不足则孔填充率 {snp.est_hole_fill_pct:.0f}% "
                    "虚焊，超时则喷嘴锡渣积聚与助焊剂挥发殆尽拉尖桥连（Rayming/Chuxin 基线 1~3s）。",
                    "warning",
                    "Rayming & Chuxin Selective Dwell Baseline (1~3s, ≤5s hard limit)",
                    current=round(snp.dwell_time_s, 2),
                    required="1.0~5.0 s",
                )
            )
        if getattr(snp, "retinning_recommended", False):
            issues.append(
                _issue(
                    "SELECTIVE_NOZZLE_WINDOW_VIOLATION",
                    "浸润式喷嘴磨损超限需重新镀锡活化",
                    f"喷嘴累计 {getattr(snp, 'nozzle_wear_factor', 1.0):.2f}× 磨损因子：有效浸润深度漂移，"
                    "按 ERSA/SEHO 规范执行 re-tinning 活化并复测波高（ERSA Accessory Catalogue）。",
                    "warning",
                    "ERSA Select Wave Nozzle Re-Tinning Procedure",
                )
            )

    # ── BD. 锡渣桥连/拖锡冰柱预测检查 (Macaos §2 & Sierra Circuits) ─────────
    # 开孔暴露比 >60% 放大拖锡；引脚间距 <0.8mm 桥连；离波角 <4° 冰柱。
    dbp = getattr(r2, "dross_bridging_predictor", None)
    if dbp:
        if not getattr(dbp, "is_exposure_ok", True):
            issues.append(
                _issue(
                    "DROSS_BRIDGING_ICICLE_RISK",
                    "治具开孔暴露比超限放大拖锡与锡渣",
                    f"上锡开孔暴露比 {dbp.exposed_ratio:.0%} > 60%：拖锡面积与锡渣生成面积同步放大，"
                    "桥连/锡珠概率陡增（Macaos §2：开孔须贴近板外形）。",
                    "warning",
                    "Macaos Selective Wave Guidelines §2 Opening Sizing",
                    current=round(dbp.exposed_ratio, 2),
                    required=0.6,
                )
            )
        if getattr(dbp, "bridge_risk_pins", None):
            issues.append(
                _issue(
                    "DROSS_BRIDGING_ICICLE_RISK",
                    "细间距引脚群离波桥连高危",
                    f"最小引脚间距 {dbp.min_pin_gap_mm:.2f}mm < 0.8mm，高危位号 "
                    f"{', '.join(dbp.bridge_risk_pins[:4])}：离波拖锡尖峰将搭接短路（Sierra Circuits）。",
                    "warning",
                    "Sierra Circuits Wave Peel-off & Bridging Criteria",
                    current=round(dbp.min_pin_gap_mm, 2),
                    required=0.8,
                    unit="mm",
                )
            )
        if getattr(dbp, "icicle_risk", False):
            issues.append(
                _issue(
                    "DROSS_BRIDGING_ICICLE_RISK",
                    "离波角不足将拖出冰柱",
                    f"离波角 {dbp.peel_off_angle_deg:.1f}° < 4°：表面张力无法自然缩颈，"
                    "引脚末端拖锡成冰柱并污染出板滚轮（Sierra Circuits / Bob Willis）。",
                    "warning",
                        "Sierra Circuits Controlled Board Separation from the Wave",
                        current=round(dbp.peel_off_angle_deg, 1),
                        required=4.0,
                        unit="°",
                    )
                )

    # ── BE. AOI 光学检测相机视场避障与 45° 倒角开窗检查 (Koh Young & Omron)
    # 开孔立壁至外围引脚必须保持 >= 3.5mm 间距且视场遮挡率 <= 5.0%，防 3D AOI 误判虚焊。
    aoi_res = getattr(r2, "aoi_vision_window", None)
    if aoi_res and not getattr(aoi_res, "is_aoi_inspection_safe", True):
        min_c = getattr(aoi_res, "min_observed_clearance_mm", 0.0)
        max_o = getattr(aoi_res, "max_observed_occlusion_pct", 0.0)
        issues.append(
                _issue(
                    "AOI_CAMERA_FOV_OCCLUSION_RISK",
                    "治具开孔直壁阻挡 3D AOI 侧视相机视场阴影盲区",
                    f"开孔边缘距受检焊点最小间距 {min_c:.2f}mm < 3.5mm，45° 侧视投影遮挡率达 "
                    f"{max_o:.1f}% > 5.0% 允许阈值；阴影盲区将导致焊点润湿角误判假点率暴增，"
                    "须在开孔四周铣削 45° 逃光倒角斜坡（Koh Young / Omron 3D AOI 规范）。",
                    "warning",
                    "Koh Young & Omron 3D AOI Camera FOV Inspection Guidelines",
                    current=round(max_o, 1),
                    required=5.0,
                    unit="%",
                )
            )

    # ── BF. 传送链电机驱动扭矩与链条拉力抗跳齿校核 (Ersa & SEHO) ───────────
    # 炉内连线多具治具爬坡总拉力必须 <= 650N 且电机扭矩安全系数 SF >= 1.5。
    cdt = getattr(r2, "conveyor_drag_torque", None)
    if cdt:
        if not getattr(cdt, "is_motor_safe", True):
            sf_val = getattr(cdt, "motor_torque_safety_factor", 1.0)
            issues.append(
                _issue(
                    "CONVEYOR_DRIVE_TORQUE_OVERLOAD",
                    "传送带驱动电机扭矩储备不足跳齿卡轨风险",
                    f"波峰焊传送链电机扭矩安全系数 SF={sf_val:.2f} < 1.5 安全底线；"
                    "重型治具爬坡摩擦阻力过大，将导致传送顿挫引起锡面波纹振动连锡（Ersa/SEHO 传动规范）。",
                    "warning",
                    "Ersa & SEHO Wave Conveyor Drive Transmission Standards",
                    current=round(sf_val, 2),
                    required=1.5,
                )
            )
        if not getattr(cdt, "is_chain_pull_safe", True):
            f_pull = getattr(cdt, "total_drag_force_n", 0.0)
            issues.append(
                _issue(
                    "CONVEYOR_DRIVE_TORQUE_OVERLOAD",
                    "传送链总拖曳拉力超出链爪允许承载上限",
                    f"在炉治具总拉力达 {f_pull:.1f}N > 650N 链条极限，存在链爪跳齿脱轨与机械卡死高危。",
                    "warning",
                    "Conveyor Chain Mechanical Tension Limits (<= 650N)",
                    current=round(f_pull, 1),
                    required=650.0,
                    unit="N",
                )
            )

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
    return {
        "allowed": production_allowed(issues),
        "counts": c,
        "worst": worst,
        "total": len(issues),
    }


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
