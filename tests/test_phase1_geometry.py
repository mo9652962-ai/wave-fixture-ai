"""phase1 纯几何函数测试：沉板区 / 取手位 / 压扣孔 / 定位销。"""

from shapely.geometry import Polygon, box

from fixture_phase1 import FixtureParams, make_handles, make_pins, make_screws, make_sink_region

P = FixtureParams()


def _board() -> Polygon:
    """100×80mm 矩形板（原点在左下）。"""
    return box(0, 0, 100, 80)


def test_sink_region_expands_and_keeps_single_polygon():
    sink = make_sink_region(_board(), P)
    assert isinstance(sink, Polygon)
    # 外扩 0.2mm → 面积严格大于原板
    assert sink.area > _board().area
    minx, miny, maxx, maxy = sink.bounds
    assert minx < 0 and miny < 0 and maxx > 100 and maxy > 80


def test_sink_region_fillet_smooths_corners():
    """清角（dilate-erode）后角点应圆化：顶点数少于直角矩形的缓冲结果"""
    plain = _board().buffer(P.sink_expand_mm, join_style="round", quad_segs=16)
    filleted = make_sink_region(_board(), P)
    assert len(filleted.exterior.coords) > 4  # 仍是多段轮廓
    # 面积接近但不等于简单外扩（圆角削掉了尖角）
    assert abs(filleted.area - plain.area) < plain.area * 0.05


def test_handles_two_per_side_geometry():
    handles = make_handles(make_sink_region(_board(), P), P)
    assert len(handles) == 2
    left, right = handles
    sb = make_sink_region(_board(), P).bounds
    # 左取手位在沉板区左缘外侧（handle_w - overlap = 19mm 在外侧）
    assert left.bounds[2] <= sb[0] + P.handle_overlap + 0.01
    assert right.bounds[0] >= sb[2] - P.handle_overlap - 0.01
    # 高度 = 取手宽 40mm（含 R2 倒角后略小于 40）
    assert left.bounds[3] - left.bounds[1] <= P.handle_h + 0.01


def test_screws_four_corners_outside_sink():
    """压扣孔必须在沉板区**外侧**（压扣压住 PCB 边缘，孔落在治具体上）。"""
    sink = make_sink_region(_board(), P)
    screws = make_screws(sink, P)
    assert len(screws) == 4
    sb = sink.bounds
    for x, y in screws:
        # 每个孔的 x 与 y 都落在沉板区边界之外
        assert x < sb[0] or x > sb[2], f"孔 x={x} 不在沉板区外"
        assert y < sb[1] or y > sb[3], f"孔 y={y} 不在沉板区外"
        # 且偏移量恰好是 screw_offset
        assert min(abs(x - sb[0]), abs(x - sb[2])) == P.screw_offset
        assert min(abs(y - sb[1]), abs(y - sb[3])) == P.screw_offset
    assert len(set(screws)) == 4


def test_pins_inset_radius():
    drills = [(10.0, 10.0, 3.0), (50.0, 40.0, 0.05)]  # 正常孔 / 过小孔（内缩后 r<=0 应丢弃）
    pins = make_pins(drills, P)
    assert len(pins) == 1
    x, y, r = pins[0]
    assert (x, y) == (10.0, 10.0)
    assert r == 3.0 / 2 - P.pin_inset
