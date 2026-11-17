# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> This changelog was started on 2026-11-16. The 0.5.6–0.5.9 entries are
> reconstructed from the git tag history; earlier releases (0.2.1–0.5.5)
> predate it and are recorded in the git tags only.

## [Unreleased]

### Added

- **Type checking gate.** The shipped modules now pass `mypy` with no
  errors (87 baseline findings fixed across `drc`, `fixture_phase1`,
  `fixture_phase2`, `fixture_3d`, `interference`, `panelize`, `review`,
  `web_server`, `mcp_server`, `cnc_gcode`, `odb_parser`). Config lives
  in `pyproject.toml` (`mypy` joins the dev extra). shapely/gerbonara
  and the other stub-less libraries are treated as Any
  (`follow_imports = "skip"`) because the geometry layer is duck-typed
  by design; the repo's own dataclasses, return contracts and call
  sites are checked strictly. The geometry guards `_poly_ok` /
  `_shape_ok` are now `TypeGuard`s, `make_sink_region` has precise
  overloads for its `return_corners` forms, and `run_phase2`'s
  `out_dxf` is honestly `str | None`. AGENTS.md lists the command
  beside the test runner.
- **Design-rule profiles** (`docs/rule-profiles/`): Kaisertech, MB
  Manufacturing and CN-general wave-pallet rule sets transcribed side by
  side as machine-readable JSON, each with its source. The profiles are
  parallel references, not interchangeable; `drc.py` does not consume
  them yet.
- **Selective-solder nozzle profile is now reachable.** `Phase2Params`
  declares the `selective_*` parameter family (`selective_nozzle_dia_mm`,
  default `None` = disabled, plus pump speed / hole diameter / measured
  dwell / nozzle age). Previously the trigger existed only as a
  `getattr` read, so the hasattr-gated parameter override silently
  dropped it and `Phase2Result.selective_nozzle_profile` was always
  `None`, leaving DRC section BC without input. New integration tests
  pin the default-off behavior, the mounted result, and the BC
  violation end to end.

### Changed

- **`drc.py` split: `run_drc` is no longer a single ~1,840-line
  function.** The 62 check sections (A-BJ) are now module-level
  `_check_*` functions sharing state through a `_DrcContext` dataclass
  (extracted geometry, source constants, the findings list, and the
  eight cross-section hand-off values). `run_drc` itself only
  assembles the context, calls the sections in the original order,
  and returns the findings. No rule code, threshold or message
  changed; equivalence was verified by diffing the full findings
  lists of the old and new implementations on all three golden cases
  (plain, with material/machine profiles, and with a nozzle profile).

### Fixed

- **RFID cavity metal keepouts were never applied.** In
  `fixture_phase2`, the keepout collection read `stiffener.poly` and
  `ti_res.blade_polys` — fields that do not exist on `StiffenerResult`
  / `TitaniumInsertsResult` — so the getattr guards always failed and
  the RFID embed cavity was planned with an empty keepout list. It
  now collects `stiffener.bar_polys` and the titanium blades'
  `boundary_poly`.
- Documentation numbers reconciled with the code: the DRC rule count is
  87 (the badge alt text said 73); coverage is 89% (measured 88.85% over
  the 18 modules CI gates on) where the badge said 85% and the quickstart
  comment said 84% and 130 tests (the suite collects 435).
- `CITATION.cff` version aligned to the packaged release: 0.5.9
  (was 1.0.0, which matches no release tag), with the v0.5.9 tag date.

## [0.5.9] - 2026-10-28

### Added

- Dual-wave chip de-bridging baffle and ergonomic recessed grips;
  DRC rules 86–87.

## [0.5.8] - 2026-10-27

### Added

- Dual-step labyrinth solder seal and anti-derailment guide snubbers;
  DRC rules 84–85.

## [0.5.7] - 2026-10-26

### Added

- AOI camera FOV chamfer windows and conveyor chain drag torque solver;
  DRC rules 82–83.

## [0.5.6] - 2026-10-26

### Added

- Selective nozzle immersion/dwell windows and dross bridging predictor;
  DRC rules 80–81.
