"""治具量产成本报价引擎 (Fixture Volume Cost Quotation Engine).

工业背景与商业基准：
- 材料成本：按 Röchling Durostone 标准大板 (1020 × 1220mm) 嵌料排版 (Grid Nesting)，
  双朝向取最大排样数；整板利用率 = (排样数 × 单件毛料面积) / 大板面积，
  不足整板的尾单按单件毛料 + 15% 切割损耗计价。
- CNC 加工成本：与 cnc_setup_sheet / cnc_toolpath_opt 工时预算同源，
  加工费 = 工时(min) / 60 × 机时费率 (三轴立加 ¥120/h，四轴 ¥180/h 行业常见报价)。
- 五金 BOM 成本：对标 APTPCB / 淘宝工业品常见成交价 ——
  M3×16 不锈钢螺钉 ¥0.35、Φ3 硬化定位销 ¥2.8、旋转压扣 ¥4.2、
  M4 铰链 ¥6.5、钛合金刀片 ¥1.2/cm。
- 数量阶梯折扣 (Volume Discount Tiers)：1 / 5 / 20 / 50 件 → 1.00 / 0.92 / 0.85 / 0.78
  （对标 Macaos 报价与国内治具厂阶梯报价惯例），报价单价 = 成本 × 1.35 毛利系数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from materials import MATERIALS

# Durostone / Ricocel 标准大板尺寸 (Röchling 供货规格)
STANDARD_SHEET_W_MM = 1020.0
STANDARD_SHEET_H_MM = 1220.0
SINGLE_CUT_WASTE_FACTOR = 1.15  # 尾单单件切割损耗系数

# 数量阶梯折扣：(最小数量, 折扣系数)
QUANTITY_DISCOUNT_TIERS: tuple[tuple[int, float], ...] = ((1, 1.00), (5, 0.92), (20, 0.85), (50, 0.78))

DEFAULT_MARGIN_FACTOR = 1.35
MACHINE_HOURLY_RATE_CNY = 120.0  # 三轴立式加工中心机时费率 (¥/h)

# 标准五金单价 (¥/件，工业品渠道常见成交价)
HARDWARE_UNIT_PRICES_CNY: dict[str, float] = {
    "screw_m3x16": 0.35,  # M3×16 不锈钢螺钉
    "locating_pin_d3": 2.80,  # Φ3 硬化定位销
    "turn_lock_clamp": 4.20,  # 弹簧旋转压扣
    "hinge_m4": 6.50,  # M4 铰链
    "titanium_blade_per_cm": 1.20,  # 钛合金隔锡刀片 (每 cm 长度)
    "brass_insert_m3": 0.45,  # 黄铜埋植嵌件 M3 (螺纹强化, >500 次装拆)
}


@dataclass
class CostLine:
    item: str
    qty: float
    unit_price_cny: float
    subtotal_cny: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "qty": self.qty,
            "unit_price_cny": round(self.unit_price_cny, 3),
            "subtotal_cny": round(self.subtotal_cny, 2),
        }


@dataclass
class QuotationResult:
    material_key: str
    quantity: int
    blanks_per_sheet: int
    sheet_utilization_pct: float
    cost_lines: list[CostLine] = field(default_factory=list)
    material_cost_cny: float = 0.0
    cnc_cost_cny: float = 0.0
    hardware_cost_cny: float = 0.0
    cost_per_pc_cny: float = 0.0
    discount_factor: float = 1.0
    quote_unit_price_cny: float = 0.0
    quote_total_cny: float = 0.0
    markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_key": self.material_key,
            "quantity": self.quantity,
            "blanks_per_sheet": self.blanks_per_sheet,
            "sheet_utilization_pct": self.sheet_utilization_pct,
            "cost_lines": [c.to_dict() for c in self.cost_lines],
            "material_cost_cny": round(self.material_cost_cny, 2),
            "cnc_cost_cny": round(self.cnc_cost_cny, 2),
            "hardware_cost_cny": round(self.hardware_cost_cny, 2),
            "cost_per_pc_cny": round(self.cost_per_pc_cny, 2),
            "discount_factor": self.discount_factor,
            "quote_unit_price_cny": round(self.quote_unit_price_cny, 2),
            "quote_total_cny": round(self.quote_total_cny, 2),
        }


def nest_blanks_on_sheet(
    blank_w_mm: float,
    blank_h_mm: float,
    sheet_w_mm: float = STANDARD_SHEET_W_MM,
    sheet_h_mm: float = STANDARD_SHEET_H_MM,
    kerf_mm: float = 5.0,
) -> tuple[int, float]:
    """Grid Nesting 排样：横放/竖放双朝向取最大排样数，返回 (排样数, 大板利用率)。"""
    kw = blank_w_mm + kerf_mm
    kh = blank_h_mm + kerf_mm
    if kw <= 0 or kh <= 0:
        return 0, 0.0

    def grid(cols_space: float, rows_space: float) -> int:
        cols = max(0, int((cols_space + kerf_mm) // kw))
        rows = max(0, int((rows_space + kerf_mm) // kh))
        return cols * rows

    n_normal = grid(sheet_w_mm, sheet_h_mm)
    n_rotated = grid(sheet_h_mm, sheet_w_mm)
    best = max(n_normal, n_rotated)
    if best == 0:
        return 0, 0.0
    util = min(100.0, best * blank_w_mm * blank_h_mm / (sheet_w_mm * sheet_h_mm) * 100.0)
    return best, round(util, 1)


def _discount_factor(qty: int) -> float:
    factor = 1.0
    for min_qty, f in QUANTITY_DISCOUNT_TIERS:
        if qty >= min_qty:
            factor = f
    return factor


def estimate_quotation(
    material_key: str = "durostone",
    pallet_w_mm: float = 300.0,
    pallet_h_mm: float = 200.0,
    pallet_thickness_mm: float = 10.0,
    machining_time_min: float = 0.0,
    hardware_counts: dict[str, float] | None = None,
    quantity: int = 1,
    machine_hourly_rate_cny: float = MACHINE_HOURLY_RATE_CNY,
    margin_factor: float = DEFAULT_MARGIN_FACTOR,
) -> QuotationResult:
    """按「材料嵌料排版 + CNC 工时 + 五金 BOM + 阶梯折扣」输出量产报价。"""
    mat = MATERIALS.get(material_key) or MATERIALS["durostone"]
    q = max(1, int(quantity))
    hw = dict(hardware_counts or {})

    # 1. 材料成本（嵌料排版整板摊销 / 尾单损耗）
    per_sheet, util_pct = nest_blanks_on_sheet(pallet_w_mm, pallet_h_mm)
    if per_sheet == 0:
        # 治具大于标准大板：按单件整板材料计价
        per_sheet, util_pct = 1, round(pallet_w_mm * pallet_h_mm / (STANDARD_SHEET_W_MM * STANDARD_SHEET_H_MM) * 100.0, 1)

    def _area_cost(area_mm2: float, t_mm: float) -> float:
        vol_cm3 = area_mm2 * t_mm / 1000.0
        return vol_cm3 * mat.density_g_cm3 / 1000.0 * mat.price_per_kg

    sheet_cost = _area_cost(STANDARD_SHEET_W_MM * STANDARD_SHEET_H_MM, pallet_thickness_mm)
    blank_cost = _area_cost(pallet_w_mm * pallet_h_mm, pallet_thickness_mm)

    used_sheets = math.ceil(q / per_sheet)
    if q >= per_sheet:
        material_total = used_sheets * sheet_cost
    else:
        material_total = blank_cost * q * SINGLE_CUT_WASTE_FACTOR

    # 2. CNC 加工成本
    cnc_total = (machining_time_min / 60.0) * machine_hourly_rate_cny * q

    # 3. 五金 BOM 成本 (单件数量 × 单价 × 数量)
    cost_lines: list[CostLine] = [
        CostLine(f"材料-{mat.name_cn}({pallet_w_mm:g}×{pallet_h_mm:g}×{pallet_thickness_mm:g}mm)", q, material_total / q, material_total),
        CostLine(f"CNC 加工({machining_time_min:.0f}min × ¥{machine_hourly_rate_cny:g}/h)", q, cnc_total / q, cnc_total),
    ]
    hardware_total = 0.0
    for item, price in HARDWARE_UNIT_PRICES_CNY.items():
        n = float(hw.get(item, 0.0))  # 单件用量
        if n <= 0:
            continue
        sub = n * price * q
        hardware_total += sub
        cost_lines.append(CostLine(item, n * q, price, sub))

    total_cost = material_total + cnc_total + hardware_total
    cost_per_pc = total_cost / q
    df = _discount_factor(q)
    unit_quote = cost_per_pc * df * margin_factor

    md = [
        f"# 治具量产报价单 — {mat.name_cn} × {q} 件",
        "",
        f"- **大板嵌料排版**: {per_sheet} 件/张 (1020×1220mm)，利用率 {util_pct}%，用板 {used_sheets} 张",
        f"- **成本单价**: ¥{cost_per_pc:,.2f}（材料 {material_total / q:,.2f} + CNC {cnc_total / q:,.2f} + 五金 {hardware_total / q:,.2f}）",
        f"- **阶梯折扣**: ×{df:g}（{q} 件档）",
        f"- **报价单价**: ¥{unit_quote:,.2f}（含 {margin_factor:g} 毛利系数）",
        f"- **报价总额**: ¥{unit_quote * q:,.2f}",
        "",
        "| 成本项 | 数量 | 单价 ¥ | 小计 ¥ |",
        "|:---|:---|:---|:---|",
    ]
    for c in cost_lines:
        md.append(f"| {c.item} | {c.qty:g} | {c.unit_price_cny:,.3f} | {c.subtotal_cny:,.2f} |")

    return QuotationResult(
        material_key=mat.key,
        quantity=q,
        blanks_per_sheet=per_sheet,
        sheet_utilization_pct=util_pct,
        cost_lines=cost_lines,
        material_cost_cny=material_total,
        cnc_cost_cny=cnc_total,
        hardware_cost_cny=hardware_total,
        cost_per_pc_cny=cost_per_pc,
        discount_factor=df,
        quote_unit_price_cny=unit_quote,
        quote_total_cny=unit_quote * q,
        markdown="\n".join(md),
    )
