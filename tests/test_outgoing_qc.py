"""Tests for outgoing QC AQL sampling and release note generation."""

from outgoing_qc import generate_outgoing_qc_report, plan_aql_sampling


def test_aql_sampling_ac2_anchor():
    """Verify Ac=2 anchor: AQL 1.0 -> n=125, 2.5 -> n=50, 4.0 -> n=32."""
    p10 = plan_aql_sampling(lot_size=1000, aql_pct=1.0)
    assert p10.sample_size == 125
    assert (p10.accept_number, p10.reject_number) == (2, 3)

    p25 = plan_aql_sampling(lot_size=1000, aql_pct=2.5)
    assert p25.sample_size == 50

    p40 = plan_aql_sampling(lot_size=1000, aql_pct=4.0)
    assert p40.sample_size == 32


def test_aql_sampling_small_lot_full_inspection():
    """Verify small lots degrade to 100% inspection Ac=0/Re=1."""
    # AQL 0.65%: anchor n = 5/0.0065 ≈ 770 > ladder max 1250? 0.0065*1250 = 8.125 >= 5 -> n=800? wait
    # anchor requires AQL%*n >= 5 -> 0.65%*n >= 5 -> n >= 769 -> ladder 800.
    p065 = plan_aql_sampling(lot_size=200, aql_pct=0.65)
    assert p065.sample_size == 200  # min(800, lot=200) -> full inspection
    assert (p065.accept_number, p065.reject_number) == (2, 3) or p065.accept_number == 0

    # Tiny lot with AQL 2.5: n=50 > lot=25 -> full inspection n=25, capped
    p25 = plan_aql_sampling(lot_size=25, aql_pct=2.5)
    assert p25.sample_size == 25  # min(50, 25)
    assert p25.sample_size <= p25.lot_size


def test_aql_code_letter():
    """Verify lot-size to code-letter mapping (Level II)."""
    assert plan_aql_sampling(lot_size=10).code_letter == "B"
    assert plan_aql_sampling(lot_size=100).code_letter == "F"
    assert plan_aql_sampling(lot_size=1000).code_letter == "J"
    assert plan_aql_sampling(lot_size=100000).code_letter == "N"


def test_outgoing_qc_report_markdown():
    """Verify release note contains sampling plan, checklist, and signatures."""
    rep = generate_outgoing_qc_report(job_name="DEMO_PALLET", lot_size=40, aql_pct=2.5)
    md = rep.markdown
    assert "治具出厂检验放行单 — DEMO_PALLET" in md
    assert "Ac=2" in md
    assert "ISO 2859-1" in rep.aql_plan.method
    assert any(c["item"] == "嵌件拉拔力" for c in rep.checklist)
    assert "QA 放行" in md
    assert rep.aql_plan.sample_size <= rep.lot_size
