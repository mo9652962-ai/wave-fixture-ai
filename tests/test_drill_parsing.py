"""钻孔解析测试（parse_drills_regex）——含单位推断与 G85 兼容。

真实验证背景：内测中钻孔解析的英寸/毫米自动识别分支（坐标 >600 则 /25.4）
从未被覆盖，而它直接决定定位销位置是否正确——错一位就是整块治具废掉。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fixture_phase1 import parse_drills_regex


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_metric_header_parsing(tmp_path):
    """METRIC 声明 + 孔径表 + 坐标行（G85 风格）。"""
    _write(tmp_path, "a.drl", """M48
;Layer: Drill
METRIC,LZ,000.000
T01C0.305
T02C0.915
%
G05
T01
X10.0Y20.0
X30.0Y40.0
T02
X50.0Y60.0
M30
""")
    drills = parse_drills_regex(tmp_path)
    assert len(drills) == 3
    # 孔径应来自对应刀具
    dias = {round(d[2], 3) for d in drills}
    assert dias == {0.305, 0.915}


def test_inch_coordinates_auto_converted(tmp_path):
    """英寸坐标（>600）应自动 /25.4（无 METRIC/INCH 声明时的启发式）。"""
    _write(tmp_path, "b.drl", """M48
T01C0.030
%
X10000Y20000
X30000Y40000
T01
""")
    drills = parse_drills_regex(tmp_path)
    assert drills, "应解析出钻孔"
    # 10000 → 393.7mm（英寸板常见坐标量级）
    xs = sorted(d[0] for d in drills)
    assert xs[0] == pytest.approx(10000 / 25.4, abs=0.1)


def test_inch_aperture_converted(tmp_path):
    """INCH 声明时孔径应 ×25.4（0.03" → 0.762mm）。"""
    _write(tmp_path, "c.drl", """M48
INCH,TZ
T01C0.0300
%
T01
X1000Y2000
""")
    drills = parse_drills_regex(tmp_path)
    assert drills
    assert drills[0][2] == pytest.approx(0.03 * 25.4, abs=0.01)


def test_dedup_same_hole(tmp_path):
    """同一孔被多段指令重复时只保留一个。"""
    _write(tmp_path, "d.drl", """M48
METRIC
T01C1.0
%
T01
X10.0Y10.0
X10.0Y10.0
T01
X10Y10
""")
    drills = parse_drills_regex(tmp_path)
    assert len(drills) == 1, f"去重失败：{drills}"


def test_empty_dir_returns_empty(tmp_path):
    assert parse_drills_regex(tmp_path) == []


def test_ignores_non_drill_files(tmp_path):
    _write(tmp_path, "readme.txt", "这不是钻孔文件")
    _write(tmp_path, "outline.GKO", "G04 Layer*\nM02*")
    # .txt 会被当候选但内容非钻孔 → 应安全返回（不崩）
    drills = parse_drills_regex(tmp_path)
    assert isinstance(drills, list)


def test_g85_multiple_holes_one_line(tmp_path):
    """KiCad 10 的 G85 写法：一行多个 X/Y 对。"""
    _write(tmp_path, "e.drl", """M48
METRIC
T01C0.8
%
T01
X1.0Y2.0X3.0Y4.0X5.0Y6.0
""")
    drills = parse_drills_regex(tmp_path)
    assert len(drills) == 3, f"单行多孔解析失败：{drills}"
    assert {round(d[0], 1) for d in drills} == {1.0, 3.0, 5.0}


def test_real_board_drill_count(tmp_path):
    """真实板（case_003）钻孔数应与 KiCad 标注一致。"""
    case = Path(__file__).resolve().parent.parent / "cases" / "case_003_stm32_4layer"
    if not case.exists():
        pytest.skip("case_003 缺失")
    drills = parse_drills_regex(case)
    assert len(drills) == 12
    # 应有 3.2mm 安装孔（用于定位销）
    assert any(abs(d[2] - 3.2) < 0.05 for d in drills)
