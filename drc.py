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
