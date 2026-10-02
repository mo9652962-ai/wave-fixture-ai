"""工艺窗口 / 批量作业 / DRC 材料交叉校验 测试（企业级第二轮升级）。

覆盖：
1. process：工艺窗口库完整性、材料-工艺兼容性、Markdown 章节
2. drc G5 MATERIAL_TEMP_WINDOW：FR-4 报警、Durostone 通过
3. batch_run：YAML 作业规格解析、批量执行、失败隔离、路径安全
4. report：工艺章节集成
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import box

import drc
import process as process_mod
from materials import MATERIALS
from process import PROCESS_WINDOWS, get_process, material_process_compat

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "cases"


# ── 1. process ───────────────────────────────────────────────────
def test_process_windows_complete():
    """有铅/无铅窗口齐全，数值与行业推荐一致。"""
    assert set(PROCESS_WINDOWS) == {"leaded", "lead_free"}
    lf = PROCESS_WINDOWS["lead_free"]
    assert lf.pot_temp_c == (255.0, 265.0)
    assert lf.dwell_time_s[0] >= 4.0  # 无铅接触时间 ≥4s
    pb = PROCESS_WINDOWS["leaded"]
    assert pb.pot_temp_c == (255.0, 265.0)  # 260 ±5
    assert get_process(None).key == "lead_free"
    assert get_process("不存在的").key == "lead_free"


def test_material_process_compat():
    """Durostone 兼容无铅波峰；FR-4 不兼容并给出替换建议。"""
    ok, _note = material_process_compat(MATERIALS["durostone"].max_service_temp_c)
    assert ok is True
    ok2, note2 = material_process_compat(MATERIALS["fr4_high_tg"].max_service_temp_c)
    assert ok2 is False
    assert "Durostone" in note2 or "Ricocel" in note2


def test_process_markdown_section():
    """工艺章节包含锡温/预热/接触时间与带治具实测提示。"""
    md = process_mod.process_section_markdown("lead_free")
    assert "锡炉温度" in md and "255" in md and "265" in md
    assert "带治具实测" in md


# ── 2. DRC G5 ────────────────────────────────────────────────────
def _mk_r1r2():
    board = box(10, 10, 60, 60)
    sink = board.buffer(0.2)
    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=[],
        screws=[],
        pins=[(15.0, 15.0, 1.5), (40.0, 40.0, 1.5)],
        dogbone_corners=[],
    )
    r2 = SimpleNamespace(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=box(0, 0, 120, 80),
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=sink,
        dogbone_corners=[],
        panel_grid=None,
    )
    return r1, r2


def test_drc_material_temp_window_fired_for_fr4():
    """FR-4（180°C）→ MATERIAL_TEMP_WINDOW warning。"""
    r1, r2 = _mk_r1r2()
    issues = drc.run_drc(r1, r2, material_key="fr4_high_tg")
    codes = [i["code"] for i in issues]
    assert "MATERIAL_TEMP_WINDOW" in codes
    hit = next(i for i in issues if i["code"] == "MATERIAL_TEMP_WINDOW")
    assert hit["current"] == 180.0 and hit["required"] == 255.0


def test_drc_material_temp_window_silent_for_durostone():
    """Durostone（280°C）→ 不触发。"""
    r1, r2 = _mk_r1r2()
    issues = drc.run_drc(r1, r2, material_key="durostone")
    assert "MATERIAL_TEMP_WINDOW" not in [i["code"] for i in issues]


# ── 3. batch_run ─────────────────────────────────────────────────
def _write_spec(tmp_path: Path, jobs: list[dict], **kw) -> Path:
    import yaml

    spec = {
        "batch": kw.get("batch", "测试批"),
        "out_dir": kw.get("out_dir", "batch-out"),
        "defaults": kw.get("defaults", {"material": "durostone"}),
        "jobs": jobs,
    }
    sp = tmp_path / "job.yaml"
    sp.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    return sp


def test_batch_spec_parse_and_defaults(tmp_path):
    """defaults 合并 + 相对路径解析 + 名称缺省取目录名。"""
    from batch_run import load_job_spec

    gdir = CASES / "case_003_stm32_4layer"
    if not gdir.exists():
        pytest.skip("case_003 缺失")
    spec = _write_spec(
        tmp_path,
        [{"name": "j1", "gerber_dir": str(gdir)}, {"gerber_dir": str(gdir), "panel_cols": 2}],
        defaults={"material": "ricocel", "pallet_thickness": 12},
    )
    batch_name, jobs, _out = load_job_spec(spec)
    assert batch_name == "测试批"
    assert len(jobs) == 2
    assert jobs[0].material == "ricocel" and jobs[0].pallet_thickness == 12.0
    assert jobs[1].panel_cols == 2 and jobs[1].name == "case_003_stm32_4layer"


def test_batch_spec_rejects_bad_suffix(tmp_path):
    """非 YAML 规格拒绝。"""
    from batch_run import load_job_spec

    bad = tmp_path / "spec.exe"
    bad.write_text("jobs: []", encoding="utf-8")
    with pytest.raises(ValueError):
        load_job_spec(bad)


def test_batch_run_end_to_end(tmp_path):
    """真实板批量：两作业（其一 2×1 拼版）全成功 + 汇总报告落盘。"""
    from batch_run import run_batch

    gdir = CASES / "case_003_stm32_4layer"
    if not gdir.exists():
        pytest.skip("case_003 缺失")
    spec = _write_spec(
        tmp_path,
        [
            {"name": "single", "gerber_dir": str(gdir)},
            {"name": "paneled", "gerber_dir": str(gdir), "panel_cols": 2, "panel_rows": 1},
        ],
    )
    br = run_batch(spec, tmp_path / "out")
    assert br.all_ok
    assert len(br.succeeded) == 2
    out = tmp_path / "out"
    assert (out / "single" / "single.dxf").exists()
    assert (out / "single" / "single.nc").exists()
    assert (out / "single" / "single-report.md").exists()
    assert (out / "paneled" / "paneled.nc").exists()
    summary = (out / "batch-summary.md").read_text(encoding="utf-8")
    assert "治具批次生产汇总" in summary and "成功 2 / 失败 0" in summary


def test_batch_run_isolates_failure(tmp_path):
    """单作业失败（外形缺失）不中断批次，退出判定 all_ok=False。"""
    from batch_run import run_batch

    gdir = CASES / "case_003_stm32_4layer"
    if not gdir.exists():
        pytest.skip("case_003 缺失")
    empty = tmp_path / "empty"
    empty.mkdir()
    spec = _write_spec(
        tmp_path,
        [
            {"name": "good", "gerber_dir": str(gdir)},
            {"name": "bad", "gerber_dir": str(empty)},
        ],
    )
    br = run_batch(spec, tmp_path / "out")
    assert not br.all_ok
    assert len(br.succeeded) == 1 and len(br.failed) == 1
    assert "外形" in br.failed[0]["error"]


# ── 4. report 工艺章节 ───────────────────────────────────────────
def test_report_includes_process_section():
    """生产工单包含波峰焊工艺窗口与材料兼容性结论。"""
    from report import build_report

    r1, r2 = _mk_r1r2()
    verdict = {
        "allowed": True,
        "counts": {"blocking": 0, "error": 0, "warning": 0, "info": 0},
        "worst": "info",
        "total": 0,
    }
    md = build_report(
        "proc-test",
        r1,
        r2,
        verdict,
        material={"key": "fr4_high_tg", "thickness": 10.0, "board_pocket_depth": 1.9},
        weight_kg=0.3,
        cost={
            "material_cost": 27.0,
            "machining_cost": 0.0,
            "total": 27.0,
            "currency": "CNY",
            "note": "",
        },
    )
    assert "波峰焊工艺窗口" in md
    assert "材料-工艺兼容性" in md and "⚠️" in md  # FR-4 → 不兼容警示
    assert "交付物清单" in md
