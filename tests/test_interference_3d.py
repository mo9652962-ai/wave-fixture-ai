"""干涉分析 / 3D 拉伸 / 坐标变换测试。"""

from shapely.geometry import box

from fixture_3d import interference_check, polygon_to_extrude
from interference import _fp_key, _is_through_hole, transform_pcb_to_gerber


def test_polygon_to_extrude_volume():
    poly = box(0, 0, 20, 10)
    mesh = polygon_to_extrude(poly, 0.0, 5.0)
    assert mesh is not None
    assert abs(mesh.volume - 20 * 10 * 5) < 1e-3  # 长方体体积 1000mm³


def test_polygon_to_extrude_none_safe():
    assert polygon_to_extrude(None, 0, 5) is None


def test_interference_check_detects_overlap():
    # 治具底板：100×80 矩形拉伸（z 0~5）
    plate = box(0, 0, 100, 80)
    fixture = polygon_to_extrude(plate, 0.0, 5.0)
    # 元件在治具范围内且 z 与治具重叠 → 报干涉
    boxes = [(30, 30, 10, 10, 3.0, "C_TALL")]
    reports = interference_check(fixture, boxes)
    assert any(r["name"] == "C_TALL" for r in reports)


def test_interference_check_passes_clear_component():
    plate = box(0, 0, 100, 80)
    fixture = polygon_to_extrude(plate, 0.0, 5.0)
    # 元件 xy 在治具范围之外 → 无重叠（元件 z 自 PCB 表面向上生长，必与 z∈[0,5] 治具在 z 向交叠）
    boxes = [(120, 30, 10, 10, 3.0, "C_CLEAR")]
    reports = interference_check(fixture, boxes)
    assert not any(r["name"] == "C_CLEAR" for r in reports)


def test_fp_key_normalizes_separators():
    assert _fp_key("SOP-8_Seeed") is not None
    assert _fp_key("totally-unknown-thing") is None


def test_is_through_hole_categories():
    assert _is_through_hole("PinHeader_2x3")
    assert _is_through_hole("Connector_USB_A")
    assert _is_through_hole("DIP-8")
    assert not _is_through_hole("C_0603")
    assert not _is_through_hole("R_0805")


def test_transform_pcb_to_gerber_flips_y():
    """KiCad → Gerber 的 Y 轴翻转与平移"""
    #pcb_bounds=(0,0,100,80), gerber_bounds=(0,0,100,80) → y 翻转
    x, y = transform_pcb_to_gerber(30, 10, (0, 0, 100, 80), (0, 0, 100, 80))
    assert x == 30
    assert y == 70  # 80 - 10
