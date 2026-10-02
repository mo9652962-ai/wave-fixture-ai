"""Golden Sample 验证框架——治具几何的回归断言。

指标（对标竞品 validation/ 框架）：
- IoU（交并比）≥ 0.9 合格
- Hausdorff 距离 ≤ 0.5mm
- 圆孔（压扣/定位销/盖板孔）：位置误差 ≤ 0.2mm、半径误差 ≤ 0.1mm，双向 best-match

用法：
  export_golden(r1, r2) → dict（可 JSON 存盘为 golden 基准）
  run_golden_check(r1, r2, golden) → report（逐项 pass/fail + overall）
"""
from __future__ import annotations

import json
from pathlib import Path

IOU_MIN = 0.9
HAUSDORFF_MAX_MM = 0.5
CIRCLE_POS_TOL_MM = 0.2
CIRCLE_R_TOL_MM = 0.1


def iou(a, b) -> float:
    """两个多边形的交并比。"""
    try:
        if a is None or b is None or a.is_empty or b.is_empty:
            return 0.0
        inter = a.intersection(b).area
        union = a.union(b).area
        return inter / union if union > 0 else 0.0
    except Exception:
        return 0.0


def hausdorff(a, b) -> float:
    """双向 Hausdorff 距离（mm）。"""
    try:
        if a is None or b is None or a.is_empty or b.is_empty:
            return float("inf")
        return a.hausdorff_distance(b)
    except Exception:
        return float("inf")


def _poly_wkt(poly) -> str | None:
    return poly.wkt if poly is not None else None


def export_golden(r1, r2) -> dict:
    """从 phase1/phase2 结果导出 golden 基准（WKT + 圆孔列表）。"""
    return {
        "board_wkt": _poly_wkt(getattr(r1, "board_poly", None)),
        "sink_wkt": _poly_wkt(getattr(r1, "sink_poly", None)),
        "handles_wkt": [_poly_wkt(h) for h in (getattr(r1, "handles", []) or [])],
        "screws": [list(s) for s in (getattr(r1, "screws", []) or [])],
        "pins": [list(p) for p in (getattr(r1, "pins", []) or [])],
        "outer_wkt": _poly_wkt(getattr(r2, "outer_poly", None)),
        "avoid_wkt": [_poly_wkt(a) for a in (getattr(r2, "avoid_polys", []) or [])],
        "solder_wkt": [_poly_wkt(s) for s in (getattr(r2, "solder_polys", []) or [])],
        "cap_holes": [list(c) for c in (getattr(r2, "cap_holes", []) or [])],
    }


def save_golden(data: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_golden(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _wkt_poly(wkt):
    from shapely import wkt as _wkt

    return _wkt.loads(wkt) if wkt else None


def _circle3(item) -> tuple[float, float, float]:
    """统一圆条目为 (x, y, r)；二元组（如压扣孔 (x,y)）半径取 0（只校验位置）。"""
    seq = list(item)
    if len(seq) >= 3:
        return float(seq[0]), float(seq[1]), float(seq[2])
    if len(seq) == 2:
        return float(seq[0]), float(seq[1]), 0.0
    raise ValueError(f"非法圆条目: {item!r}")


def _match_circles(actual: list, golden: list, pos_tol: float, r_tol: float) -> dict:
    """双向 best-match：每个 golden 圆找最近 actual 圆；半径仅在双方都带半径时校验。"""
    golden3 = [_circle3(g) for g in golden]
    actual3 = [_circle3(a) for a in actual]
    unmatched_a = list(actual3)
    matched = 0
    errs = []
    for gx, gy, gr in golden3:
        best = None
        for ai, (ax, ay, ar) in enumerate(unmatched_a):
            d = ((gx - ax) ** 2 + (gy - ay) ** 2) ** 0.5
            if best is None or d < best[0]:
                best = (d, ai)
        if best is None:
            continue
        ax, ay, ar = unmatched_a[best[1]]
        radius_ok = (gr == 0.0 and ar == 0.0) or abs(ar - gr) <= r_tol
        if best[0] <= pos_tol and radius_ok:
            matched += 1
            errs.append(best[0])
            unmatched_a.pop(best[1])
    return {"golden_total": len(golden3), "actual_total": len(actual3),
            "matched": matched, "missing": len(golden3) - matched,
            "extra": len(actual3) - matched,
            "max_pos_err_mm": round(max(errs), 4) if errs else 0.0,
            "ok": matched == len(golden3) and len(actual3) == len(golden3)}


def compare_run(r1, r2, golden: dict) -> dict:
    """当前 run 与 golden 基准逐项对比。"""
    report: dict = {"items": [], "overall": "pass"}

    def _item(name, ok, detail):
        report["items"].append({"item": name, "ok": ok, "detail": detail})
        if not ok:
            report["overall"] = "fail"

    # 面状几何：IoU + Hausdorff
    for name, actual_poly, golden_wkt in (
        ("board", getattr(r1, "board_poly", None), golden.get("board_wkt")),
        ("sink", getattr(r1, "sink_poly", None), golden.get("sink_wkt")),
        ("outer", getattr(r2, "outer_poly", None), golden.get("outer_wkt")),
    ):
        g = _wkt_poly(golden_wkt)
        if g is None:
            continue
        v = iou(actual_poly, g)
        hd = hausdorff(actual_poly, g)
        ok = v >= IOU_MIN and hd <= HAUSDORFF_MAX_MM
        _item(f"{name}_iou", v >= IOU_MIN, f"IoU={v:.4f} (≥{IOU_MIN})")
        _item(f"{name}_hausdorff", hd <= HAUSDORFF_MAX_MM, f"{hd:.4f}mm (≤{HAUSDORFF_MAX_MM})")

    # 多边形组（避位/上锡/取手）：逐个 best-match IoU
    for name, actual_list, golden_list in (
        ("avoid", getattr(r2, "avoid_polys", []) or [], [_wkt_poly(w) for w in golden.get("avoid_wkt", [])]),
        ("solder", getattr(r2, "solder_polys", []) or [], [_wkt_poly(w) for w in golden.get("solder_wkt", [])]),
        ("handles", getattr(r1, "handles", []) or [], [_wkt_poly(w) for w in golden.get("handles_wkt", [])]),
    ):
        if not golden_list:
            continue
        matched = 0
        for gp in golden_list:
            best = max((iou(ap, gp) for ap in actual_list), default=0.0)
            if best >= IOU_MIN:
                matched += 1
        ok = matched == len(golden_list) and len(actual_list) == len(golden_list)
        _item(f"{name}_count", len(actual_list) == len(golden_list),
              f"actual={len(actual_list)} golden={len(golden_list)}")
        _item(f"{name}_match", ok, f"best-match IoU≥{IOU_MIN}: {matched}/{len(golden_list)}")

    # 圆孔组：压扣 / 定位销 / 盖板
    for name, actual_c, golden_c in (
        ("screws", getattr(r1, "screws", []) or [], golden.get("screws", [])),
        ("pins", getattr(r1, "pins", []) or [], golden.get("pins", [])),
        ("cap_holes", getattr(r2, "cap_holes", []) or [], golden.get("cap_holes", [])),
    ):
        if not golden_c:
            continue
        m = _match_circles(actual_c, golden_c, CIRCLE_POS_TOL_MM, CIRCLE_R_TOL_MM)
        _item(f"{name}_circles", m["ok"], json.dumps(m, ensure_ascii=False))

    return report


def run_golden_check(r1, r2, case_dir: str | Path) -> dict:
    """跑 cases/<case>/golden.json 基准（目录内全部 case）。"""
    base = Path(case_dir)
    results = {}
    for gj in sorted(base.glob("**/golden.json")):
        case = gj.parent.name
        results[case] = compare_run(r1, r2, load_golden(gj))
    return results
