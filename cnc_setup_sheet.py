"""CNC 加工准备单 (Setup Sheet) 生成器与标准刀具梯校核 (Machining Setup Sheet & Tool Ladder Check).

工业背景与工艺标准：
- ISO 6983 / RS-274 与 Fusion 360 / GibbsCAM CAM 后处理标准惯例：
  治具送机加工前必须随附《CNC 加工准备单》，机加工车间凭单装夹对刀：
  1. 毛料尺寸 (Stock)：治具外形 + 四周夹持余量 (标准 10mm/侧)，向上取整 5mm；
  2. 工件坐标系：G54 WCS，原点定义在治具左下角上表面 (X0 Y0 Z0)；
  3. 刀具表 (Tool Table)：T01~Tnn 按加工顺序列出刀径/类型/特征数/切削长度/预估时间；
  4. 工时汇总：切削 + 空程 + 换刀总预算 (与 cnc_toolpath_opt 同源)。
- 标准刀具梯 (Standard Tool Ladder)：
  立铣刀/钻头采购按标准梯 {1.0, 1.5, 2.0, 2.5, 3.175, 3.5, 4.0, 5.0, 6.0}mm 备库；
  使用非标准直径将触发刀具定制采购 (交期 2~4 周 + 单价 2~3 倍)，量产治具应强制归梯。
- 毛料下料校核：毛料边长 < 治具 + 2×10mm 夹持边 → 无法装夹，报 error。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from cnc_toolpath_opt import ToolpathOptResult

# 标准刀具梯 (mm) —— 立铣刀/钻头常备库规格
STANDARD_TOOL_LADDER = (1.0, 1.5, 2.0, 2.5, 3.175, 3.5, 4.0, 5.0, 6.0)

CLAMP_MARGIN_MM = 10.0  # 虎钳/压板夹持余量 (每侧)
STOCK_ROUND_TO_MM = 5.0  # 毛料下料尺寸向上取整网格


@dataclass
class ToolRow:
    tool_id: str  # T01, T02...
    dia_mm: float
    op_types: list[str] = field(default_factory=list)
    op_count: int = 0
    total_cut_len_mm: float = 0.0
    est_time_min: float = 0.0
    is_standard: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "dia_mm": self.dia_mm,
            "op_types": self.op_types,
            "op_count": self.op_count,
            "total_cut_len_mm": self.total_cut_len_mm,
            "est_time_min": self.est_time_min,
            "is_standard": self.is_standard,
        }


@dataclass
class SetupSheetResult:
    stock_width_mm: float
    stock_height_mm: float
    stock_thickness_mm: float
    min_stock_width_mm: float
    min_stock_height_mm: float
    wcs: str = "G54"
    origin_desc: str = "治具左下角上表面 (X0 Y0 Z0)"
    tools: list[ToolRow] = field(default_factory=list)
    total_time_min: float = 0.0
    nonstandard_tools: list[float] = field(default_factory=list)
    markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_width_mm": self.stock_width_mm,
            "stock_height_mm": self.stock_height_mm,
            "stock_thickness_mm": self.stock_thickness_mm,
            "min_stock_width_mm": self.min_stock_width_mm,
            "min_stock_height_mm": self.min_stock_height_mm,
            "wcs": self.wcs,
            "origin_desc": self.origin_desc,
            "tools": [t.to_dict() for t in self.tools],
            "total_time_min": self.total_time_min,
            "nonstandard_tools": self.nonstandard_tools,
        }


def generate_cnc_setup_sheet(
    tpo: ToolpathOptResult,
    outer_width_mm: float,
    outer_height_mm: float,
    stock_thickness_mm: float = 10.0,
    job_name: str = "FIXTURE",
) -> SetupSheetResult:
    """从刀路优化结果生成机加工车间准备单：毛料 / G54 / 刀具表 / 工时汇总。"""
    min_w = outer_width_mm + 2.0 * CLAMP_MARGIN_MM
    min_h = outer_height_mm + 2.0 * CLAMP_MARGIN_MM
    stock_w = math.ceil(min_w / STOCK_ROUND_TO_MM) * STOCK_ROUND_TO_MM
    stock_h = math.ceil(min_h / STOCK_ROUND_TO_MM) * STOCK_ROUND_TO_MM

    # 刀具表：按 tpo.tool_order（已按先小后大排序）逐刀汇总
    tools: list[ToolRow] = []
    nonstandard: list[float] = []
    for i, dia in enumerate(tpo.tool_order, start=1):
        ops = [op for op in tpo.sequence if abs(op.tool_dia_mm - dia) < 1e-6]
        cut_len = sum(op.path_len_mm for op in ops)
        est_min = sum(op.path_len_mm / max(120.0, 250.0 * op.tool_dia_mm) for op in ops)
        is_std = any(abs(dia - s) < 1e-6 for s in STANDARD_TOOL_LADDER)
        if not is_std:
            nonstandard.append(dia)
        tools.append(
            ToolRow(
                tool_id=f"T{i:02d}",
                dia_mm=dia,
                op_types=sorted({op.op_type for op in ops}),
                op_count=len(ops),
                total_cut_len_mm=round(cut_len, 1),
                est_time_min=round(est_min, 2),
                is_standard=is_std,
            )
        )

    lines = [
        f"# CNC 加工准备单 — {job_name}",
        "",
        (
            f"- **毛料尺寸**: {stock_w:.0f} × {stock_h:.0f} × {stock_thickness_mm:.0f} mm"
            f"（最小 {min_w:.1f} × {min_h:.1f} mm，含四周 {CLAMP_MARGIN_MM:.0f}mm 夹持余量）"
        ),
        f"- **工件坐标系**: {tools and 'G54'} · 原点 = 治具左下角上表面 (X0 Y0 Z0)",
        f"- **预估总工时**: {tpo.total_time_min:.1f} min（切削 {tpo.cutting_time_min:.2f} + 空程 {tpo.rapid_time_min:.2f} + 换刀 {tpo.tool_change_time_min:.2f}）",
        "",
        "| 刀具 | 直径 mm | 特征类型 | 特征数 | 切削长度 mm | 预估 min | 标准梯 |",
        "|:---|:---|:---|:---|:---|:---|:---|",
    ]
    for t in tools:
        lines.append(
            f"| {t.tool_id} | {t.dia_mm:g} | {'/'.join(t.op_types)} | {t.op_count} | "
            f"{t.total_cut_len_mm} | {t.est_time_min} | {'✅' if t.is_standard else '⚠️ 定制'} |"
        )
    lines += [
        "",
        "| 顺序 | 操作 | 刀具 | 起点 |",
        "|:---|:---|:---|:---|",
    ]
    tool_of = {}
    for i, dia in enumerate(tpo.tool_order, start=1):
        for op in tpo.sequence:
            if abs(op.tool_dia_mm - dia) < 1e-6 and op.op_id not in tool_of:
                tool_of[op.op_id] = f"T{i:02d}"
    for idx, op in enumerate(tpo.sequence, start=1):
        lines.append(f"| {idx:02d} | {op.op_id} ({op.op_type}) | {tool_of.get(op.op_id, '-')} | {op.start[0]:g}, {op.start[1]:g} |")

    return SetupSheetResult(
        stock_width_mm=float(stock_w),
        stock_height_mm=float(stock_h),
        stock_thickness_mm=float(stock_thickness_mm),
        min_stock_width_mm=round(min_w, 1),
        min_stock_height_mm=round(min_h, 1),
        tools=tools,
        total_time_min=tpo.total_time_min,
        nonstandard_tools=nonstandard,
        markdown="\n".join(lines),
    )
