"""Tests for fixture volume cost quotation engine."""

from quotation import (
    HARDWARE_UNIT_PRICES_CNY,
    estimate_quotation,
    nest_blanks_on_sheet,
)


def test_nest_blanks_on_sheet():
    """Verify grid nesting counts and utilization for standard Durostone sheet."""
    # 300x200mm blank on 1020x1220 sheet: ~3 cols x 5 rows with kerf
    n, util = nest_blanks_on_sheet(300.0, 200.0)
    assert n >= 12
    assert 40.0 <= util <= 100.0

    # Oversized blank falls back to 1
    n1, _util1 = nest_blanks_on_sheet(1500.0, 800.0)
    assert n1 == 0  # cannot fit even one


def test_material_cost_sheet_amortization_vs_single_cut():
    """Verify quantity >= per_sheet uses sheet amortization; small qty uses waste factor."""
    small = estimate_quotation(quantity=2, machining_time_min=0)
    bulk = estimate_quotation(quantity=15, machining_time_min=0)

    # Per-pc material cost must be lower in bulk (sheet amortization) than 2-pc tail order
    mat_small = small.cost_lines[0].subtotal_cny / 2
    mat_bulk = bulk.cost_lines[0].subtotal_cny / 15
    assert mat_bulk < mat_small
    assert bulk.blanks_per_sheet >= 12


def test_cnc_and_hardware_cost_lines():
    """Verify CNC machining cost and hardware BOM line items."""
    q = estimate_quotation(
        quantity=1,
        machining_time_min=30.0,
        hardware_counts={
            "screw_m3x16": 4.0,
            "locating_pin_d3": 2.0,
            "turn_lock_clamp": 4.0,
        },
    )
    # CNC: 30min * 120/h = 60 CNY
    assert abs(q.cnc_cost_cny - 60.0) < 0.01
    # Hardware: 4*0.35 + 2*2.8 + 4*4.2 = 1.4 + 5.6 + 16.8 = 23.8
    assert abs(q.hardware_cost_cny - 23.8) < 0.01
    assert len(q.cost_lines) == 5  # material + cnc + 3 hardware


def test_quantity_discount_and_margin():
    """Verify tiered discount lowers unit price and margin factor applies."""
    q1 = estimate_quotation(quantity=1, machining_time_min=30.0)
    q50 = estimate_quotation(quantity=50, machining_time_min=30.0)

    assert q1.discount_factor == 1.00
    assert q50.discount_factor == 0.78
    assert q50.quote_unit_price_cny < q1.quote_unit_price_cny

    # Quote = cost_per_pc * discount * 1.35
    expect = q50.cost_per_pc_cny * 0.78 * 1.35
    assert abs(q50.quote_unit_price_cny - expect) < 0.5
    assert abs(q50.quote_total_cny - q50.quote_unit_price_cny * 50) < 0.5


def test_quotation_markdown_output():
    """Verify markdown quote contains header, nesting info, and cost table."""
    q = estimate_quotation(quantity=20, machining_time_min=25.0, hardware_counts={"titanium_blade_per_cm": 24.0})
    md = q.markdown
    assert "治具量产报价单" in md
    assert "大板嵌料排版" in md
    assert "阶梯折扣" in md
    assert HARDWARE_UNIT_PRICES_CNY["titanium_blade_per_cm"] > 0
    assert "titanium_blade_per_cm" in md
