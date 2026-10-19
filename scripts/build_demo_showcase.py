"""
Pre-generate static demo assets for GitHub Pages Zero-Friction showcase.
Builds complete 2D/3D CAM artifacts for case_001, case_002, case_003 into web/demo/.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import matplotlib
from shapely.ops import unary_union as _uu

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

from cnc_gcode import generate_gcode
from drc import apply_watermark, gate, run_drc
from fixture_3d import Fixture3DParams, build_fixture_3d, export_glb, export_stl
from fixture_phase1 import (
    FixtureParams,
    make_handles,
    make_pins,
    make_screws,
    make_sink_region,
    parse_gerber,
)
from fixture_phase2 import run_phase2
from interference import (
    analyze_interference,
    compute_sink_depth,
    get_pcb_board_bounds,
    get_suspicious_components,
    parse_kicad_pcb,
)
from materials import (
    blank_area,
    estimate_cost,
    estimate_weight,
    get_material,
    nearest_sheet_thickness,
)
from process_card import generate_process_card_markdown
from report import build_report, write_report

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("demo-showcase")

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = REPO_ROOT / "cases"
WEB_DIR = REPO_ROOT / "web"
DEMO_DIR = WEB_DIR / "demo"


def _safe_str(geom) -> str:
    if geom is None:
        return "未知"
    try:
        b = geom.bounds
        return f"{b[2]-b[0]:.1f} × {b[3]-b[1]:.1f} mm"
    except Exception:
        return "未知"


def process_case(case_name: str, case_folder: str, title: str, description: str):
    case_path = CASES_DIR / case_folder
    out_dir = DEMO_DIR / case_name
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"=== Processing {case_name}: {title} ===")

    # 1. Parse Gerber & Phase 1
    board_polys, drills = parse_gerber(str(case_path))
    if not board_polys:
        raise ValueError(f"No board outline found in {case_path}")
    board = _uu(board_polys)
    p1 = FixtureParams()
    sink, dogbone_corners = make_sink_region(board, p1, return_corners=True)

    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=make_handles(sink, p1),
        screws=make_screws(sink, p1),
        pins=make_pins(drills, p1, sink_poly=sink),
        dogbone_corners=dogbone_corners,
    )

    # 2. Phase 2 (Pockets, Solder openings, Outer boundary)
    dxf_path = out_dir / "fixture.dxf"
    result = run_phase2(str(case_path), str(dxf_path))
    if result is None:
        raise ValueError(f"Phase 2 failed for {case_path}")

    # 3. DRC Manufacturing Gate
    material_key = "durostone"
    mat = get_material(material_key)
    pallet_thickness = 10.0
    board_thickness = 1.6

    issues = run_drc(
        r1,
        result,
        material_key=material_key,
        pallet_thickness=pallet_thickness,
    )
    verdict = gate(issues)
    log.info(f"DRC verdict: allowed={verdict['allowed']}, counts={verdict['counts']}")

    actual_dxf_name = "fixture.dxf"
    if not verdict["allowed"]:
        preview_dxf = apply_watermark(dxf_path)
        actual_dxf_name = Path(preview_dxf).name

    # 4. Render 2D Preview PNG
    png_path = out_dir / "fixture.png"
    doc = ezdxf.readfile(str(dxf_path))
    ctx = RenderContext(doc)
    fig, ax = plt.subplots(figsize=(16, 10))
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(doc.modelspace(), finalize=True)
    ax.set_aspect("equal")
    fig.savefig(str(png_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 5. G-Code & Material & Reports
    sheet_t = nearest_sheet_thickness(pallet_thickness, mat)
    outer_bounds = getattr(result.outer_poly, "bounds", None) or board.bounds
    ob_w = outer_bounds[2] - outer_bounds[0]
    ob_h = outer_bounds[3] - outer_bounds[1]
    weight_kg = estimate_weight(blank_area((ob_w, ob_h)), sheet_t, mat)

    sink_info = {}
    pcb_files = list(case_path.rglob("*.kicad_pcb"))
    has_kicad = len(pcb_files) > 0
    if has_kicad:
        try:
            sink_info = compute_sink_depth(str(pcb_files[0]), board_thickness=board_thickness)
        except Exception as e:
            log.warning(f"compute_sink_depth warning: {e}")

    gcode_path = out_dir / "fixture.nc"
    gcode_stats = generate_gcode(
        result.sink_poly,
        result.avoid_polys,
        result.solder_polys,
        result.cap_holes,
        r1.pins,
        r1.handles,
        result.outer_poly,
        str(gcode_path),
        material_key=mat.key,
        pallet_thickness=pallet_thickness,
        board_thickness=board_thickness,
        sink_depth=sink_info.get("sink_depth_mm"),
        vent_holes=getattr(result, "vent_holes", []),
        job_name=case_name,
        parent_hint=out_dir,
    )
    gcode_stats["thickness"] = sheet_t
    cost = estimate_cost(weight_kg, mat, gcode_stats.get("machining_minutes", 0.0))

    report_path = out_dir / "report.md"
    report_md = build_report(
        case_name,
        r1,
        result,
        drc_verdict=verdict,
        material={
            "key": mat.key,
            "thickness": sheet_t,
            "board_pocket_depth": gcode_stats.get("board_pocket_depth"),
            "sink_depth": sink_info,
        },
        weight_kg=weight_kg,
        cost=cost,
        gcode_stats=gcode_stats,
        output_urls={
            "DXF 工程图": f"demo/{case_name}/{actual_dxf_name}",
            "PNG 预览": f"demo/{case_name}/fixture.png",
            "CNC G 代码": f"demo/{case_name}/fixture.nc",
        },
        process_key="lead_free",
    )
    write_report(report_path, report_md, parent_hint=out_dir)

    fai_path = out_dir / "fai.md"
    fai_md = generate_process_card_markdown(
        case_name,
        pallet_size_str=_safe_str(getattr(result, "outer_poly", None)),
        material_name=f"{mat.name_cn} {sheet_t}mm",
        machine_name="通用 350mm 轨距",
        fasteners_count={
            "clamps": len(getattr(r1, "screws", []) or []),
            "pins": len(getattr(r1, "pins", []) or []),
            "dams": len(getattr(result, "tin_strip_lines", []) or []),
        },
    )
    write_report(fai_path, fai_md, parent_hint=out_dir)

    # 6. Build Watertight 3D Mesh (STL & GLB)
    mesh = build_fixture_3d(
        sink,
        result.avoid_polys,
        result.solder_polys,
        result.outer_poly,
        Fixture3DParams(),
    )
    stl_path = out_dir / "fixture.stl"
    glb_path = out_dir / "fixture.glb"
    export_stl(mesh, str(stl_path))
    export_glb(mesh, str(glb_path))
    log.info(f"Exported 3D mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")

    # 7. Interference Analysis (if KiCad PCB present)
    comps = []
    reports = []
    suspicious_comps = []
    interference_boxes = []

    if has_kicad:
        pcb_path = pcb_files[0]
        comps = parse_kicad_pcb(str(pcb_path))
        pcb_bounds = get_pcb_board_bounds(str(pcb_path))
        if pcb_bounds is None and comps:
            pcb_bounds = (
                min(c["x"] for c in comps) - 5,
                min(c["y"] for c in comps) - 5,
                max(c["x"] for c in comps) + 5,
                max(c["y"] for c in comps) + 5,
            )
        gerber_bounds = sink.bounds if sink is not None else None
        reports = analyze_interference(
            str(stl_path),
            comps,
            pcb_bounds=pcb_bounds,
            gerber_bounds=gerber_bounds,
            avoid_polys=result.avoid_polys,
        )
        suspicious_comps = get_suspicious_components(
            comps,
            reports,
            pcb_bounds=pcb_bounds,
            gerber_bounds=gerber_bounds,
        )
        interference_boxes = [
            {
                "ref": r["ref"],
                "name": r["name"],
                "x": r["x"],
                "y": r["y"],
                "w": r["w"],
                "h": r["h"],
                "height": r["height"],
                "overlap_mm3": r["overlap_mm3"],
                "interfering": True,
            }
            for r in reports
        ]

    # 8. Package Case Metadata for Frontend Zero-Friction Replay
    stats = {
        "board_size": _safe_str(getattr(result, "outer_poly", None)),
        "avoid_count": len(getattr(result, "avoid_polys", [])),
        "solder_count": len(getattr(result, "solder_polys", [])),
        "cap_hole_count": len(getattr(result, "cap_holes", [])),
        "vent_count": len(getattr(result, "vent_holes", [])),
        "dogbone_count": len(getattr(result, "dogbone_corners", [])) or len(dogbone_corners),
    }

    material_stats = {
        "key": mat.key,
        "name": mat.name_cn,
        "sheet_thickness": sheet_t,
        "weight_kg": weight_kg,
        "cost": cost,
        "sink_depth": sink_info,
    }

    case_payload = {
        "case_id": case_name,
        "title": title,
        "description": description,
        "generate": {
            "ok": True,
            "job_id": case_name,
            "dxf_url": f"demo/{case_name}/{actual_dxf_name}",
            "png_url": f"demo/{case_name}/fixture.png",
            "gcode_url": f"demo/{case_name}/fixture.nc",
            "report_url": f"demo/{case_name}/report.md",
            "fai_url": f"demo/{case_name}/fai.md",
            "stl_url": f"demo/{case_name}/fixture.stl",
            "glb_url": f"demo/{case_name}/fixture.glb",
            "material": material_stats,
            "gcode_stats": gcode_stats,
            "stats": stats,
            "drc": {
                "allowed": verdict["allowed"],
                "counts": verdict["counts"],
                "worst": verdict["worst"],
                "total": verdict["total"],
                "issues": issues,
            },
            "message": "治具生成成功" if verdict["allowed"] else "DRC 门禁已拦截（出具预览版）",
        },
        "interference": {
            "ok": True,
            "job_id": case_name,
            "has_kicad": has_kicad,
            "component_count": len(comps),
            "interference_count": len(reports),
            "interferences": reports,
            "interference_boxes": interference_boxes,
            "suspicious_components": suspicious_comps,
            "glb_url": f"demo/{case_name}/fixture.glb",
            "message": (
                f"分析完成：{len(comps)} 个元件，{len(reports)} 个干涉"
                if reports
                else (f"分析完成：{len(comps)} 个元件，✅ 无干涉" if has_kicad else "纯 Gerber 模式，仅展示 3D 几何")
            ),
        },
    }

    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Saved {case_name} payload to {meta_path}\n")
    return case_payload


def main():
    cases = [
        (
            "case_003",
            "case_003_stm32_4layer",
            "STM32 工业四层板 (旗舰展示)",
            "4层高密度板，含多种贴片与插装元件、沉板清角与 3D 实体干涉高亮",
        ),
        (
            "case_002",
            "case_002_aircon_kicad",
            "空调主控电源板 (混装大板)",
            "大跨度混装板，高电解电容与继电器避位，波峰焊防渣导流与钛合金嵌件",
        ),
        (
            "case_001",
            "case_001_espmh",
            "ESP32 物联网模块 (微型板)",
            "紧凑型外形，R1.85 狗骨头自动清角与高密度 DRC 生产安全门禁验证",
        ),
    ]

    all_cases_meta = []
    for cid, folder, title, desc in cases:
        _ = process_case(cid, folder, title, desc)
        all_cases_meta.append({
            "id": cid,
            "title": title,
            "description": desc,
            "path": f"demo/{cid}/meta.json",
        })

    index_path = DEMO_DIR / "cases.json"
    index_path.write_text(json.dumps(all_cases_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"Generated demo index at {index_path}")


if __name__ == "__main__":
    main()
