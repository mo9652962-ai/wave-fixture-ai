"""批量作业引擎——YAML 作业规格（Job Spec）驱动多板治具流水生产。

工业定位（对标 KiBot/KiKit 的声明式 YAML 管线惯例）：
企业产线不会一块板一块板地点界面——工程师写一份 job.yaml（可进 git 版本化、
可 review），一条命令把整批板的治具 DXF/G 代码/生产工单全部产出，并汇总成批次报告。

作业规格格式（job.yaml）：
    batch: "2026-W40 空调主板批"
    defaults:
      material: durostone
      pallet_thickness: 10.0
      panel_cols: 1
      panel_rows: 1
      panel_gap: 5.0
      board_thickness: 1.6
    jobs:
      - name: aircon-main
        gerber_dir: cases/case_002_aircon_kicad
      - name: stm32-carrier
        gerber_dir: cases/case_003_stm32_4layer
        panel_cols: 2
        material: ricocel

安全：所有输出路径经 resolve + 父目录包含校验（与 cnc_gcode/report 同一套约束）；
单个作业失败不中断批次（退出码汇总，企业 CI 可直接当门禁）。
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import yaml

from materials import get_material, nearest_sheet_thickness

log = logging.getLogger("fixture-batch")

ALLOWED_SPEC_SUFFIXES = {".yaml", ".yml"}


@dataclass
class BatchJob:
    """单个作业条目（已合并 defaults）。"""

    name: str
    gerber_dir: str
    material: str = "durostone"
    pallet_thickness: float = 10.0
    board_thickness: float = 1.6
    panel_cols: int = 1
    panel_rows: int = 1
    panel_gap: float = 5.0
    out_dir: str | None = None  # 缺省用批级 out_dir


@dataclass
class BatchResult:
    """批次执行结果（单作业失败不中断批次）。"""

    batch_name: str
    out_dir: str
    succeeded: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return not self.failed

    def summary_markdown(self) -> str:
        L = [
            f"# 治具批次生产汇总 · {self.batch_name}",
            "",
            f"> 生成时间：{_time.strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"> 作业数：{len(self.succeeded) + len(self.failed)}（成功 {len(self.succeeded)} / 失败 {len(self.failed)}）",
            "",
        ]
        if self.succeeded:
            L += [
                "| 作业 | 材料 | 治具外形 | 毛坯重量 | 成本估算 | 加工估时 | 产物 |",
                "|---|---|---|---|---|---|---|",
            ]
            for s in self.succeeded:
                mat = s.get("material", {})
                files = "、".join(
                    f"[{k.split()[0]}]({Path(v).name})" for k, v in s.get("outputs", {}).items()
                )
                L.append(
                    f"| {s['name']} | {mat.get('name', '-')} | {s.get('size', '-')} "
                    f"| {mat.get('weight_kg', '-')}kg | ¥{mat.get('cost', {}).get('total', '-')} "
                    f"| {s.get('machining_minutes', '-')}min | {files} |"
                )
            L.append("")
        if self.failed:
            L += ["## 失败作业", ""]
            for f in self.failed:
                L.append(f"- **{f['name']}**: {f.get('error', '未知错误')}")
            L.append("")
        return "\n".join(L)


def load_job_spec(spec_path: str | Path) -> tuple[str, list[BatchJob], Path]:
    """解析 YAML 作业规格 → (批次名, 作业列表, 输出目录)。

    规格路径本身受后缀白名单约束；gerber_dir/out_dir 相对规格文件所在目录解析。
    """
    sp = Path(spec_path)
    if sp.suffix.lower() not in ALLOWED_SPEC_SUFFIXES:
        raise ValueError(
            f"作业规格须为 YAML（{sorted(ALLOWED_SPEC_SUFFIXES)}），收到: {sp.suffix!r}"
        )
    spec = yaml.safe_load(sp.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or "jobs" not in spec:
        raise ValueError("作业规格缺少顶层 jobs 列表")

    base = sp.parent.resolve()
    defaults = spec.get("defaults") or {}
    out_dir = (base / (spec.get("out_dir") or "batch-out")).resolve()

    jobs: list[BatchJob] = []
    for i, raw in enumerate(spec["jobs"]):
        if not isinstance(raw, dict) or "gerber_dir" not in raw:
            raise ValueError(f"jobs[{i}] 缺少 gerber_dir")
        name = str(raw.get("name") or Path(raw["gerber_dir"]).name)
        merged = {**defaults, **{k: v for k, v in raw.items() if k != "name"}}
        j = BatchJob(
            name=name,
            gerber_dir=str((base / merged["gerber_dir"]).resolve()),
            material=str(merged.get("material", "durostone")),
            pallet_thickness=float(merged.get("pallet_thickness", 10.0)),
            board_thickness=float(merged.get("board_thickness", 1.6)),
            panel_cols=max(int(merged.get("panel_cols", 1)), 1),
            panel_rows=max(int(merged.get("panel_rows", 1)), 1),
            panel_gap=max(float(merged.get("panel_gap", 5.0)), 0.0),
            out_dir=str((base / merged["out_dir"]).resolve()) if merged.get("out_dir") else None,
        )
        jobs.append(j)
    batch_name = str(spec.get("batch") or sp.stem)
    return batch_name, jobs, out_dir


def run_batch(spec_path: str | Path, out_dir: str | Path | None = None) -> BatchResult:
    """执行批量作业：每作业产出 DXF + G 代码 + 生产工单，汇总批次报告。

    单作业失败记录进 failed（不中断批次）；返回 BatchResult 供 CI 门禁判断。
    """
    batch_name, jobs, spec_out = load_job_spec(spec_path)
    base_out = Path(out_dir).resolve() if out_dir else spec_out
    base_out.mkdir(parents=True, exist_ok=True)

    from shapely.ops import unary_union

    from cnc_gcode import generate_gcode
    from drc import gate, run_drc
    from fixture_phase1 import (
        FixtureParams,
        make_handles,
        make_pins,
        make_screws,
        make_sink_region,
        parse_gerber,
    )
    from fixture_phase2 import run_phase2
    from report import build_report, write_report

    br = BatchResult(batch_name=batch_name, out_dir=str(base_out))

    for j in jobs:
        try:
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in j.name)
            out = Path(j.out_dir) if j.out_dir else base_out / safe_name
            out.mkdir(parents=True, exist_ok=True)

            board_polys, drills = parse_gerber(j.gerber_dir)
            if not board_polys:
                raise ValueError(f"未找到外形层: {j.gerber_dir}")
            board = unary_union(board_polys)
            p1 = FixtureParams()
            sink, corners = make_sink_region(board, p1, return_corners=True)
            r1 = SimpleNamespace(
                board_poly=board,
                sink_poly=sink,
                handles=make_handles(sink, p1),
                screws=make_screws(sink, p1),
                pins=make_pins(drills, p1, sink_poly=sink),
                dogbone_corners=corners,
            )
            params2 = {}
            if j.panel_cols > 1 or j.panel_rows > 1:
                params2 = {
                    "panel_cols": j.panel_cols,
                    "panel_rows": j.panel_rows,
                    "panel_gap": j.panel_gap,
                }
            r2 = run_phase2(j.gerber_dir, str(out / f"{safe_name}.dxf"), params2_override=params2)
            if r2 is None:
                raise ValueError("治具生成失败")

            issues = run_drc(r1, r2, material_key=j.material)
            verdict = gate(issues)

            mat = get_material(j.material)
            sheet_t = nearest_sheet_thickness(j.pallet_thickness, mat)
            ob = getattr(r2.outer_poly, "bounds", None) or board.bounds
            from materials import blank_area, estimate_cost, estimate_weight

            weight = estimate_weight(blank_area((ob[2] - ob[0], ob[3] - ob[1])), sheet_t, mat)

            gstats = generate_gcode(
                r2.sink_poly,
                r2.avoid_polys,
                r2.solder_polys,
                r2.cap_holes,
                r1.pins,
                r1.handles,
                r2.outer_poly,
                str(out / f"{safe_name}.nc"),
                material_key=mat.key,
                pallet_thickness=j.pallet_thickness,
                board_thickness=j.board_thickness,
                job_name=j.name,
                parent_hint=out,
            )
            cost = estimate_cost(weight, mat, gstats.get("machining_minutes", 0.0))
            report_md = build_report(
                j.name,
                r1,
                r2,
                verdict,
                material={
                    "key": mat.key,
                    "thickness": sheet_t,
                    "board_pocket_depth": gstats.get("board_pocket_depth"),
                },
                weight_kg=weight,
                cost=cost,
                gcode_stats=gstats,
                process_key="lead_free",
            )
            write_report(out / f"{safe_name}-report.md", report_md, parent_hint=out)

            br.succeeded.append(
                {
                    "name": j.name,
                    "size": f"{ob[2] - ob[0]:.0f}×{ob[3] - ob[1]:.0f}mm",
                    "material": {"name": mat.name_cn, "weight_kg": weight, "cost": cost},
                    "machining_minutes": gstats.get("machining_minutes"),
                    "outputs": {
                        "DXF": str(out / f"{safe_name}.dxf"),
                        "G 代码": str(out / f"{safe_name}.nc"),
                        "工单": str(out / f"{safe_name}-report.md"),
                    },
                }
            )
            log.info(
                f"  ✅ {j.name}: {br.succeeded[-1]['size']} "
                f"({mat.name_cn} {sheet_t}mm, {gstats.get('machining_minutes')}min)"
            )
        except Exception as e:
            log.warning(f"  ❌ {j.name}: {e}")
            br.failed.append({"name": j.name, "error": str(e)})

    summary = base_out / "batch-summary.md"
    summary.write_text(br.summary_markdown(), encoding="utf-8")
    log.info(f"  批次汇总: {summary}（成功 {len(br.succeeded)} / 失败 {len(br.failed)}）")
    return br


def main() -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="治具批量作业（YAML 作业规格）")
    ap.add_argument("spec", help="作业规格 YAML 路径")
    ap.add_argument("-o", "--out", default=None, help="批次输出目录（覆盖规格内 out_dir）")
    args = ap.parse_args()
    br = run_batch(args.spec, args.out)
    return 0 if br.all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
