"""CNC 加工刀路分组与最短空程优化引擎 (Toolpath Grouping & Rapid Travel Optimizer).

工业背景与工艺标准：
- ISO 6983 / RS-274 CNC 编程规范与 GibbsCAM / Fusion 360 CAM 后处理惯例：
  波峰焊治具为典型多特征零件（外形轮廓 / 沉板挖腔 / 盖板孔 / 排气孔 / 狗骨头清角），
  需要多种直径立铣刀与钻头。CNC 机床每次换刀（ATC Tool Change）耗时 5~10s 且带来
  对刀误差累积风险，量产经济性要求：
  1. 同直径刀具的加工特征必须成组连续加工（Tool Grouping），严格减少换刀次数；
  2. 组内特征按「最近邻 (Nearest Neighbor)」排序，最小化 G00 快速定位空程；
  3. 刀具排序遵循「先小后大、先钻后铣、轮廓收尾」惯例（小刀先钻定位孔，大刀粗铣，
     轮廓精铣收尾保证装夹刚性到最后）。
- 加工时间预算（Manufacturing Economics）：
  t_total = Σ(t_cut) + Σ(t_rapid) + N_tool × t_change (标准 ATC 8s/次)
  单件治具 CNC 加工时间 > 45min 即触发产能预警（对标 Macaos 报价工艺库工时基线）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CNCOp:
    """单个 CNC 加工特征（孔/腔/轮廓/清角）。"""

    op_id: str
    op_type: str  # "drill" / "pocket" / "profile" / "dogbone"
    tool_dia_mm: float
    path_len_mm: float
    start: tuple[float, float]


@dataclass
class ToolpathOptResult:
    sequence: list[CNCOp] = field(default_factory=list)
    tool_order: list[float] = field(default_factory=list)
    tool_change_count: int = 0
    rapid_travel_mm: float = 0.0
    cutting_time_min: float = 0.0
    rapid_time_min: float = 0.0
    tool_change_time_min: float = 0.0
    total_time_min: float = 0.0
    naive_rapid_mm: float = 0.0  # 优化前（输入顺序）的空程，用于收益对比
    stats: dict[str, Any] = field(default_factory=dict)


def _feed_mm_per_min(tool_dia: float) -> float:
    """经验进给：F ≈ 250 × D (mm/min)，2mm 刀 ≈ 500mm/min，6mm 刀 ≈ 1500mm/min。"""
    return max(120.0, 250.0 * tool_dia)


def _rapid_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _nearest_neighbor_order(ops: list[CNCOp], origin: tuple[float, float]) -> list[CNCOp]:
    """最近邻贪心排序（治具特征量 < 数百，贪心与 2-opt 差距 < 3%，够用且快）。"""
    remaining = list(ops)
    ordered: list[CNCOp] = []
    cur = origin
    while remaining:
        best_i = min(range(len(remaining)), key=lambda i: _rapid_dist(cur, remaining[i].start))
        nxt = remaining.pop(best_i)
        ordered.append(nxt)
        cur = nxt.start
    return ordered


def optimize_cnc_toolpath(
    ops: list[CNCOp],
    origin: tuple[float, float] = (0.0, 0.0),
    rapid_rate_mm_min: float = 6000.0,
    tool_change_sec: float = 8.0,
) -> ToolpathOptResult:
    """按「先小后大、先钻后铣、轮廓收尾」分组排序，输出换刀次数 / 空程 / 工时预算。

    排序规则：
      1. op_type 优先级: drill(0) < dogbone(1) < pocket(2) < profile(3)
      2. 同类型内按刀具直径升序（小刀先钻定位）
      3. 组内最近邻排序最小化 G00 空程
    """
    if not ops:
        return ToolpathOptResult()

    type_rank = {"drill": 0, "dogbone": 1, "pocket": 2, "profile": 3}
    naive_rapid = 0.0
    prev = origin
    for op in ops:
        naive_rapid += _rapid_dist(prev, op.start)
        prev = op.start

    grouped: dict[tuple[int, float], list[CNCOp]] = {}
    for op in ops:
        key = (type_rank.get(op.op_type, 9), round(op.tool_dia_mm, 3))
        grouped.setdefault(key, []).append(op)

    sequence: list[CNCOp] = []
    tool_order: list[float] = []
    cur = origin
    for key in sorted(grouped.keys()):
        group = _nearest_neighbor_order(grouped[key], cur)
        if not tool_order or abs(tool_order[-1] - key[1]) > 1e-6:
            tool_order.append(key[1])
        sequence.extend(group)
        cur = group[-1].start

    # 工时核算
    tool_change_count = len(tool_order)
    rapid_travel = 0.0
    prev = origin
    cutting_time = 0.0
    for op in sequence:
        rapid_travel += _rapid_dist(prev, op.start)
        cutting_time += op.path_len_mm / _feed_mm_per_min(op.tool_dia_mm)
        prev = op.start

    rapid_time = rapid_travel / max(1.0, rapid_rate_mm_min)
    change_time = tool_change_count * tool_change_sec / 60.0
    total = cutting_time + rapid_time + change_time

    return ToolpathOptResult(
        sequence=sequence,
        tool_order=tool_order,
        tool_change_count=tool_change_count,
        rapid_travel_mm=round(rapid_travel, 1),
        cutting_time_min=round(cutting_time, 2),
        rapid_time_min=round(rapid_time, 2),
        tool_change_time_min=round(change_time, 2),
        total_time_min=round(total, 2),
        naive_rapid_mm=round(naive_rapid, 1),
        stats={
            "op_count": len(sequence),
            "distinct_tools": tool_change_count,
            "rapid_saving_pct": round(
                max(0.0, (naive_rapid - rapid_travel) / naive_rapid * 100.0), 1
            ) if naive_rapid > 0 else 0.0,
        },
    )


def export_toolpath_order_to_dxf(msp, result: ToolpathOptResult) -> None:
    """输出加工顺序号标注到 DXF 专用图层「刀路序号」（车间操作员按序装夹加工）。"""
    layer_name = "刀路序号"
    for idx, op in enumerate(result.sequence, start=1):
        msp.add_text(
            f"{idx:02d}·{op.op_type}",
            dxfattribs={"layer": layer_name, "height": 2.2, "insert": (op.start[0] + 1.0, op.start[1] + 1.0)},
        )
