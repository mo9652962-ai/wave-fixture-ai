"""Golden Sample 验证框架测试 + 定位销选点算法测试 + Review 闭环测试。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import box

import golden
import review
from pin_select import qualifies, score_drill, select_locating_pins


# ── Golden Sample ────────────────────────────────────────────────
def _pair(scale: float = 1.0):
    """构造 phase 结果对；scale 控制几何偏差。"""
    board = box(0, 0, 100, 80)
    sink = box(-0.2, -0.2, 100.2, 80.2)
    outer = box(-20, -30, 140, 140)
    r1 = SimpleNamespace(
        board_poly=board, sink_poly=sink,
        handles=[box(-19, 20, 1, 60), box(99, 20, 119, 60)],
        screws=[(-10.0, -10.0), (110.0, -10.0), (-10.0, 90.0), (110.0, 90.0)],
        pins=[(5.0, 5.0, 1.4), (95.0, 75.0, 1.4)],
    )
    r2 = SimpleNamespace(
        outer_poly=outer if scale == 1.0 else box(-20, -30, 140 + scale, 140),
        avoid_polys=[box(30, 30, 40, 40)], solder_polys=[box(60, 20, 70, 30)],
        cap_holes=[(50.0, 50.0, 2.45)], tin_holes=[], tin_strip_lines=[],
    )
    return r1, r2


def test_export_and_compare_identical_run_passes(tmp_path):
    r1, r2 = _pair()
    g = golden.export_golden(r1, r2)
    p = golden.save_golden(g, tmp_path / "golden.json")
    report = golden.compare_run(r1, r2, golden.load_golden(p))
    assert report["overall"] == "pass", report["items"]
    assert all(i["ok"] for i in report["items"])


def test_iou_below_threshold_fails(tmp_path):
    r1, r2 = _pair()
    g = golden.export_golden(r1, r2)
    # 基准外框膨胀 20mm → IoU 下降、Hausdorff 超限
    g["outer_wkt"] = box(-40, -50, 160, 160).wkt
    report = golden.compare_run(r1, r2, g)
    assert report["overall"] == "fail"
    assert any(i["item"] == "outer_iou" and not i["ok"] for i in report["items"])


def test_hausdorff_threshold_documented():
    assert golden.IOU_MIN == 0.9
    assert golden.HAUSDORFF_MAX_MM == 0.5


def test_circle_matching_detects_missing_pin():
    actual = [(5.0, 5.0, 1.4)]            # 少一个销
    gold = [(5.0, 5.0, 1.4), (95.0, 75.0, 1.4)]
    m = golden._match_circles(actual, gold, 0.2, 0.1)
    assert m["ok"] is False and m["matched"] == 1


def test_circle_position_tolerance():
    actual = [(5.15, 5.0, 1.4), (95.0, 75.0, 1.4)]  # 偏移 0.15mm ≤ 0.2 容差
    gold = [(5.0, 5.0, 1.4), (95.0, 75.0, 1.4)]
    assert golden._match_circles(actual, gold, 0.2, 0.1)["ok"] is True


def test_run_golden_check_scans_case_dir(tmp_path):
    r1, r2 = _pair()
    case = tmp_path / "case_esp32"
    golden.save_golden(golden.export_golden(r1, r2), case / "golden.json")
    res = golden.run_golden_check(r1, r2, tmp_path)
    assert "case_esp32" in res and res["case_esp32"]["overall"] == "pass"


# ── 定位销选点 ───────────────────────────────────────────────────
SINK_BOUNDS = (-0.2, -0.2, 100.2, 80.2)


def test_pin_scoring_prefers_standard_hole_near_edge():
    c = score_drill(5.0, 5.0, 3.0, SINK_BOUNDS)
    assert c.score >= 7.0  # 孔径 +4、靠边 +3
    assert qualifies(c)


def test_pin_scoring_penalizes_slot_and_big_hole():
    assert score_drill(50, 50, 3.0, SINK_BOUNDS, is_slot=True).score < 0
    assert score_drill(50, 50, 6.0, SINK_BOUNDS).score < 0


def test_nthp_qualifies_with_relaxed_threshold():
    c = score_drill(50, 50, 2.2, SINK_BOUNDS, nthp=True)
    assert qualifies(c)  # NPTH 且 ≥2.0mm


def test_select_pins_picks_max_diagonal_pair():
    drills = [(5.0, 5.0, 3.0), (95.0, 75.0, 3.0), (50.0, 40.0, 3.0)]
    picked = select_locating_pins(drills, SINK_BOUNDS)
    assert len(picked) == 2
    coords = {(c.x, c.y) for c in picked}
    assert coords == {(5.0, 5.0), (95.0, 75.0)}  # 对角线最大的一对


def test_select_pins_returns_few_when_insufficient_qualified():
    drills = [(50.0, 40.0, 6.0)]  # 唯一孔不合格
    assert select_locating_pins(drills, SINK_BOUNDS) == []


# ── Review 闭环 ──────────────────────────────────────────────────
def _r1r2():
    return _pair()


def test_collect_review_items_when_layers_missing():
    r1, r2 = _r1r2()
    parsed = {"has_bottom_mask": False, "has_top_mask": False, "has_drills": False, "parse_confidence": "low"}
    items = review.collect_review_items(parsed, r1, r2)
    types = {i.type for i in items}
    assert types == set(review.MANDATORY_TYPES)
    assert review.pending_blocking([i.__dict__ for i in items]) is True


def test_no_review_items_when_all_layers_present():
    r1, r2 = _r1r2()
    items = review.collect_review_items({"has_bottom_mask": True, "has_top_mask": True,
                                         "has_drills": True, "parse_confidence": "high"}, r1, r2)
    assert items == []
    assert review.pending_blocking([]) is False


def test_confirm_review_flips_status_and_writes_audit(tmp_path):
    r1, r2 = _r1r2()
    sha = review.geometry_sha(r1, r2)
    parsed = {"has_bottom_mask": False, "has_top_mask": True, "has_drills": True, "parse_confidence": "high"}
    items = review.collect_review_items(parsed, r1, r2)
    review.save_pending(items, tmp_path, sha)

    assert review.pending_blocking(review.load_pending(tmp_path, sha)) is True
    hit = review.confirm_review(tmp_path, sha, items[0].id, operator="sora", answer="确认该板无底面贴片")
    assert hit["status"] == "confirmed" and hit["operator"] == "sora"
    assert review.pending_blocking(review.load_pending(tmp_path, sha)) is False

    audit = json.loads((Path(tmp_path) / "reviews" / sha[:8] / "layer_mapping.json").read_text(encoding="utf-8"))
    assert audit["entries"][0]["operator"] == "sora"
    assert audit["entries"][0]["answer"] == "确认该板无底面贴片"


def test_geometry_sha_changes_with_geometry():
    r1a, r2a = _r1r2()
    r1b, r2b = _r1r2()
    r2b.outer_poly = box(-20, -30, 141, 140)
    assert review.geometry_sha(r1a, r2a) != review.geometry_sha(r1b, r2b)


def test_confirm_unknown_review_raises(tmp_path):
    r1, r2 = _r1r2()
    sha = review.geometry_sha(r1, r2)
    review.save_pending(review.collect_review_items(
        {"has_bottom_mask": False, "has_top_mask": True, "has_drills": True, "parse_confidence": "high"}, r1, r2),
        tmp_path, sha)
    with pytest.raises(KeyError):
        review.confirm_review(tmp_path, sha, "review-deadbeef-nope", operator="x", answer="y")
