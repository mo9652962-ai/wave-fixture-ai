"""Unit tests for materials.py (material presets and cost estimation) and panelize.py (grid replication)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from materials import (
    MATERIALS,
    blank_area,
    estimate_cost,
    estimate_weight,
    get_material,
    nearest_sheet_thickness,
)
from panelize import (
    build_grid,
    panelize_geometry,
    replicate_components,
)


class TestMaterials:
    def test_registry_contains_standards(self):
        assert "durostone" in MATERIALS
        assert "ricocel" in MATERIALS
        assert "fr4_high_tg" in MATERIALS
        assert "aluminum" in MATERIALS

    def test_get_material_default(self):
        mat = get_material(None)
        assert mat.key == "durostone"
        assert mat.esd_safe is True
        assert mat.max_service_temp_c >= 280.0

    def test_nearest_sheet_thickness(self):
        mat = get_material("durostone")
        assert nearest_sheet_thickness(5.2, mat) == 6.0
        assert nearest_sheet_thickness(3.0, mat) == 3.0
        assert nearest_sheet_thickness(14.0, mat) == 15.0

    def test_estimate_weight_and_cost(self):
        mat = get_material("durostone")
        # 100mm x 100mm = 10,000 mm^2, 10mm thickness => 100 cm^3
        # density = 1.9 g/cm^3 => 190g = 0.19 kg
        area = 10000.0
        th = 10.0
        w_kg = estimate_weight(area, th, mat)
        assert w_kg == pytest.approx(0.19, abs=0.01)

        cost = estimate_cost(w_kg, mat, machining_minutes=15.0)
        assert cost["material_cost"] > 0
        assert cost["machining_cost"] > 0
        assert cost["currency"] == "CNY"

    def test_blank_area(self):
        area = blank_area((100.0, 50.0), margin_mm=10.0)
        # (100 + 20) * (50 + 20) = 120 * 70 = 8400 mm^2
        assert area == 8400.0


class TestPanelize:
    def test_build_grid_offsets(self):
        bounds = (0.0, 0.0, 50.0, 40.0)
        grid = build_grid(bounds, cols=2, rows=2, gap=5.0)
        assert grid.cols == 2
        assert grid.rows == 2
        assert len(grid.offsets) == 4
        # (0, 0), (55, 0), (0, 45), (55, 45)
        assert (0.0, 0.0) in grid.offsets
        assert (55.0, 0.0) in grid.offsets
        assert (0.0, 45.0) in grid.offsets
        assert (55.0, 45.0) in grid.offsets

    def test_panelize_geometry(self):
        b = box(0, 0, 10, 10)
        grid, p_sink, _avoids, _solders, _caps, pins, _handles, _screws, _corners = panelize_geometry(
            board_bounds=(0.0, 0.0, 10.0, 10.0),
            sink=b,
            avoid_polys=[box(1, 1, 9, 9)],
            solder_polys=[],
            cap_holes=[],
            pins=[(5.0, 5.0, 1.5)],
            handles=[],
            screws=[],
            dogbone_corners=[],
            cols=2,
            rows=1,
            gap=5.0,
        )

        assert grid.cols == 2
        assert len(grid.offsets) == 2
        assert p_sink.area == pytest.approx(200.0)
        assert len(pins) == 2
        assert pins[0] == (5.0, 5.0, 1.5)
        assert pins[1] == (20.0, 5.0, 1.5)  # 5 + 10 + 5

    def test_replicate_components(self):
        comps = [{"ref": "R1", "x": 5.0, "y": 5.0, "height": 1.0}]
        grid = build_grid((0.0, 0.0, 10.0, 10.0), cols=2, rows=1, gap=5.0)
        reps = replicate_components(comps, grid)
        assert len(reps) == 2
        assert reps[0]["ref"] == "R1[11]"
        assert reps[1]["ref"] == "R1[21]"
        assert reps[1]["x"] == 20.0
