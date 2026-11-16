# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> This changelog was started on 2026-11-16. The 0.5.6–0.5.9 entries are
> reconstructed from the git tag history; earlier releases (0.2.1–0.5.5)
> predate it and are recorded in the git tags only.

## [Unreleased]

### Added

- **Design-rule profiles** (`docs/rule-profiles/`): Kaisertech, MB
  Manufacturing and CN-general wave-pallet rule sets transcribed side by
  side as machine-readable JSON, each with its source. The profiles are
  parallel references, not interchangeable; `drc.py` does not consume
  them yet.

### Fixed

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
