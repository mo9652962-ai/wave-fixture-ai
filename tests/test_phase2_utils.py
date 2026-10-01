"""phase2 工具函数测试：贪心分组 / 凸包圆角。"""

from fixture_phase2 import convex_hull_buffer, group_points


def test_group_points_by_distance():
    pts = [(0, 0, 1.0), (1, 0, 1.0), (50, 50, 2.0)]  # 前两点近，第三点远
    groups = group_points(pts, gap=5.0)
    assert len(groups) == 2
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2]


def test_group_points_all_far():
    pts = [(0, 0, 1.0), (100, 0, 1.0), (200, 200, 1.0)]
    groups = group_points(pts, gap=5.0)
    assert len(groups) == 3


def test_convex_hull_buffer_three_points():

    poly = convex_hull_buffer([(0, 0, 1.0), (30, 0, 1.0), (0, 20, 1.0)], extra=1.0, fillet_r=0.5)
    assert poly.area > 0
    # 几何不变量：bounds 至少外扩 extra−0.01（0.01 = 圆角离散化的 apothem 回缩上限）
    minx, miny, maxx, maxy = poly.bounds
    assert minx <= -0.99 and miny <= -0.99
    assert maxx >= 30.99 and maxy >= 20.99


def test_convex_hull_buffer_two_points_makes_round_caps():

    poly = convex_hull_buffer([(0, 0, 1.0), (20, 0, 1.0)], extra=0.5, fillet_r=0.3)
    minx, miny, maxx, maxy = poly.bounds
    # 几何不变量：bounds 至少外扩 extra−0.01（同上，离散化容差）
    assert minx <= -0.49 and maxx >= 20.49
