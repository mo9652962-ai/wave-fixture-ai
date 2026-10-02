"""Tests for vertical_agent_toolkit: FSM, GeometricHealer, Distiller, and EvalHarness."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vertical_agent_toolkit import (
    AgentEvalHarness,
    AgentState,
    DomainContextDistiller,
    GeometricHealer,
    VerticalAgentFSM,
)


class TestVerticalAgentFSM:
    def test_initial_state(self):
        fsm = VerticalAgentFSM("job_test_001")
        assert fsm.job_id == "job_test_001"
        assert fsm.current_state == AgentState.INIT
        assert len(fsm.history) == 1
        assert not fsm.can_proceed_to_production()

    def test_transitions_and_history(self):
        fsm = VerticalAgentFSM("job_test_002")
        fsm.transition_to(AgentState.PARSED, "parse_gerber", {"layers": 4})
        fsm.transition_to(AgentState.GENERATING, "build_geometry")
        fsm.transition_to(AgentState.DRC_CHECKING, "run_drc")
        fsm.transition_to(AgentState.PRODUCTION_READY, "drc_passed")

        assert fsm.current_state == AgentState.PRODUCTION_READY
        assert fsm.can_proceed_to_production()
        assert len(fsm.history) == 5

        summary = fsm.get_summary()
        assert summary["job_id"] == "job_test_002"
        assert summary["current_state"] == "PRODUCTION_READY"
        assert summary["context"]["layers"] == 4

    def test_review_suspended_blocks_production(self):
        fsm = VerticalAgentFSM("job_test_003")
        fsm.transition_to(AgentState.REVIEW_SUSPENDED, "low_confidence_outline")
        assert not fsm.can_proceed_to_production()
        fsm.transition_to(AgentState.APPROVED, "engineer_override")
        fsm.transition_to(AgentState.PRODUCTION_READY, "finalize")
        assert fsm.can_proceed_to_production()


class TestGeometricHealer:
    def test_heal_already_valid_polygon(self):
        p = box(0, 0, 10, 10)
        healed = GeometricHealer.heal_geometry(p)
        assert healed.is_valid
        assert healed.area == 100.0

    def test_heal_self_intersecting_bowtie(self):
        # Bowtie self-intersecting polygon
        bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
        assert not bowtie.is_valid
        healed = GeometricHealer.heal_geometry(bowtie)
        assert healed.is_valid
        assert not healed.is_empty

    def test_compute_sha256(self):
        p1 = box(0, 0, 10, 10)
        p2 = box(10, 0, 20, 10)
        h1 = GeometricHealer.compute_sha256([p1, p2])
        h2 = GeometricHealer.compute_sha256([p1, p2])
        assert h1 == h2
        assert len(h1) == 64


class TestDomainContextDistiller:
    def test_distill_pcb_job_output(self):
        drc_issues = [{"rule": "wall_thickness", "severity": "warning"}]
        reviews = ["inspect_connector_clearance"]
        distilled = DomainContextDistiller.distill_pcb_job(
            job_id="job_001",
            board_bounds=(0.0, 0.0, 50.0, 80.0),
            layers_detected=["GTO", "GTS", "GTL", "GKO", "DRL"],
            drill_count=120,
            smd_pads_count=450,
            tht_pads_count=24,
            drc_issues=drc_issues,
            mandatory_reviews=reviews,
        )
        assert "job_001" in distilled
        assert "50.0" in distilled
        assert "80.0" in distilled
        assert '"smd":450' in distilled
        assert '"tht":24' in distilled
        assert "inspect_connector_clearance" in distilled


class TestAgentEvalHarness:
    def test_evaluation_pass(self):
        harness = AgentEvalHarness(min_iou=0.9, max_hausdorff_mm=0.5)
        p_expected = box(0, 0, 10, 10)
        p_actual = box(0, 0, 10, 10)
        res = harness.evaluate_case("exact_box", p_expected, p_actual)
        assert res.passed
        assert res.iou == pytest.approx(1.0)
        assert res.hausdorff_mm == pytest.approx(0.0)

    def test_evaluation_fail_iou(self):
        harness = AgentEvalHarness(min_iou=0.9, max_hausdorff_mm=0.5)
        p_expected = box(0, 0, 10, 10)
        p_actual = box(0, 0, 5, 10)  # half the size
        res = harness.evaluate_case("small_box", p_expected, p_actual)
        assert not res.passed
        assert any("IoU" in r for r in res.reasons)

    def test_benchmark_report(self):
        harness = AgentEvalHarness()
        p1 = box(0, 0, 10, 10)
        harness.evaluate_case("c1", p1, p1)
        harness.evaluate_case("c2", p1, box(0, 0, 2, 2))
        rep = harness.get_benchmark_report()
        assert rep["total_cases"] == 2
        assert rep["passed_cases"] == 1
        assert rep["pass_rate_pct"] == 50.0
