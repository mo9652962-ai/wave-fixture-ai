"""
波峰焊治具 AI 设计助手 — Web 服务
拖 Gerber → 生成治具 DXF → 预览 PNG → 下载

启动: python web_server.py [--port 8000]
"""

from __future__ import annotations

import json
import logging
import re
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fixture-web")

# FastAPI 导入（延迟到 main 判断，便于直接跑脚本测试核心函数）
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fixture_3d import Fixture3DParams, build_fixture_3d, export_glb, export_stl
from nl_adjust import parse_adjust_command

app = FastAPI(title="波峰焊治具 AI 设计助手", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_web_dir() -> Path:
    """定位前端静态目录，兼容源码运行与 pip 安装两种布局。

    - 源码：<repo>/web/index.html（与 web_server.py 同级）
    - 安装（data-files）：<sys.prefix>/share/wave-fixture-ai/index.html
    找不到时返回源码路径（让 StaticFiles 在启动时报出清晰的缺目录错误）。
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here / "web",  # 源码布局
        Path(sys.prefix) / "share" / "wave-fixture-ai",  # venv 安装（实测位置）
        Path(sys.base_prefix) / "share" / "wave-fixture-ai",  # 系统级安装
        here.parent.parent / "share" / "wave-fixture-ai",  # site-packages 上两级（兼容布局）
    ]
    # 最可靠：按发行版元数据定位（pip 安装时 data-files 的相对位置由安装器决定）
    try:
        from importlib.metadata import distribution

        dist = distribution("wave-fixture-ai")
        for f in dist.files or []:
            if str(f).replace("\\", "/").endswith("share/wave-fixture-ai/index.html"):
                candidates.insert(0, Path(str(dist.locate_file(f))).parent)
                break
    except Exception as e:
        log.debug("importlib.metadata 定位跳过: %s", e)
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    log.warning(f"  未找到前端静态目录，候选: {[str(c) for c in candidates]}")
    return candidates[0]


WEB_DIR = _resolve_web_dir()
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
REVIEW_DIR = Path(__file__).parent / "reviews-data"

# 上传临时目录
TMP_DIR = Path(tempfile.gettempdir()) / "fixture-uploads"
TMP_DIR.mkdir(exist_ok=True)


def _extract_upload(files: list[UploadFile]) -> Path:
    """把上传的多个 Gerber 文件解压到一个临时目录，返回目录路径"""
    job_id = f"job_{int(time.time() * 1000)}"
    workdir = TMP_DIR / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    for f in files:
        data = f.file.read()
        raw_name = Path(f.filename or "unknown").name
        name = re.sub(r"[^\w\-.]", "_", raw_name)
        # 支持 zip 包
        if name.lower().endswith(".zip"):
            zpath = workdir / name
            zpath.write_bytes(data)
            try:
                with zipfile.ZipFile(zpath) as z:
                    for member in z.infolist():
                        # 防止 zip slip 路径穿越
                        target = (workdir / member.filename).resolve()
                        if target.is_relative_to(workdir.resolve()):
                            z.extract(member, workdir)
            except Exception as e:
                log.warning(f"  zip 解压失败: {e}")
            continue
        # 普通 Gerber/DRL 文件
        (workdir / name).write_bytes(data)
    return workdir


# 会话参数状态（job_id → 参数覆盖 dict）
_SESSION_PARAMS: dict = {}


@app.post("/api/interference")
async def api_interference(
    files: list[UploadFile] = File(default=[]),
    job_id: str | None = Form(None),
    height_overrides: str = Form("{}"),
):
    """上传 Gerber + KiCad .kicad_pcb → 3D 治具 + 元件干涉分析（支持高度覆盖与可疑元件交互）"""
    try:
        workdir = None
        if job_id:
            safe_id = Path(job_id).name
            candidate = (TMP_DIR / safe_id).resolve()
            if candidate.is_relative_to(TMP_DIR.resolve()) and candidate.is_dir():
                workdir = candidate
                job_id = safe_id
                if files:
                    for f in files:
                        data = f.file.read()
                        raw_name = Path(f.filename or "unknown").name
                        name = re.sub(r"[^\w\-.]", "_", raw_name)
                        if name.lower().endswith(".zip"):
                            zpath = workdir / name
                            zpath.write_bytes(data)
                            try:
                                with zipfile.ZipFile(zpath) as z:
                                    for member in z.infolist():
                                        target = (workdir / member.filename).resolve()
                                        if target.is_relative_to(workdir.resolve()):
                                            z.extract(member, workdir)
                            except Exception as e:
                                log.warning(f"  zip 解压失败: {e}")
                        else:
                            (workdir / name).write_bytes(data)

        if workdir is None:
            if not files:
                raise HTTPException(400, "必须上传文件或提供有效的 job_id")
            workdir = _extract_upload(files)
            job_id = workdir.name

        # 解析用户高度覆盖
        overrides_dict: dict[str, float] = {}
        if height_overrides:
            try:
                raw_ov = (
                    json.loads(height_overrides)
                    if isinstance(height_overrides, str)
                    else dict(height_overrides)
                )
                for k, v in raw_ov.items():
                    try:
                        overrides_dict[str(k).strip()] = float(v)
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                log.warning(f"  height_overrides 解析失败: {e}")

        # 找 .kicad_pcb 文件
        pcb_files = list(Path(workdir).rglob("*.kicad_pcb"))
        if not pcb_files:
            return JSONResponse(
                {
                    "ok": False,
                    "job_id": job_id,
                    "message": "未找到 .kicad_pcb 文件——干涉分析需要 KiCad 工程文件（含元件位置）。Gerber 只有焊盘几何，没有元件高度信息。",
                }
            )
        pcb_path = pcb_files[0]

        # 生成治具 3D
        from shapely.ops import unary_union as _uu

        from fixture_3d import Fixture3DParams, build_fixture_3d, export_stl
        from fixture_phase1 import FixtureParams, make_sink_region, parse_gerber
        from fixture_phase2 import run_phase2

        board_polys, _drills = parse_gerber(str(workdir))
        if not board_polys:
            raise HTTPException(422, "未找到外形层")
        board = _uu(board_polys)
        sink = make_sink_region(board, FixtureParams())
        result2 = run_phase2(str(workdir), None)
        if result2 is None:
            raise HTTPException(422, "治具生成失败")
        mesh = build_fixture_3d(
            sink, result2.avoid_polys, result2.solder_polys, result2.outer_poly, Fixture3DParams()
        )
        stl_path = OUTPUT_DIR / f"{job_id}-interf.stl"
        export_stl(mesh, str(stl_path))

        # 元件解析 + 干涉分析（带坐标变换：KiCad → Gerber）
        from interference import (
            analyze_interference,
            get_pcb_board_bounds,
            get_suspicious_components,
            parse_kicad_pcb,
        )

        comps = parse_kicad_pcb(str(pcb_path), height_overrides=overrides_dict)
        # pcb 板范围（优先用板框 gr_rect，否则用元件范围）
        pcb_bounds = get_pcb_board_bounds(str(pcb_path))
        if pcb_bounds is None and comps:
            pcb_bounds = (
                min(c["x"] for c in comps) - 5,
                min(c["y"] for c in comps) - 5,
                max(c["x"] for c in comps) + 5,
                max(c["y"] for c in comps) + 5,
            )
        # gerber 板范围（沉板区 = PCB 区域）
        gerber_bounds = sink.bounds if sink is not None else None
        reports = analyze_interference(
            str(stl_path),
            comps,
            pcb_bounds=pcb_bounds,
            gerber_bounds=gerber_bounds,
            avoid_polys=result2.avoid_polys,
        )
        suspicious_comps = get_suspicious_components(
            comps,
            reports,
            pcb_bounds=pcb_bounds,
            gerber_bounds=gerber_bounds,
        )

        # 导出 GLB 供前端 3D 可视化
        glb_path = OUTPUT_DIR / f"{job_id}-interf.glb"
        try:
            from fixture_3d import export_glb

            export_glb(mesh, str(glb_path))
            glb_url = f"/dl/{job_id}-interf.glb"
        except Exception:
            glb_url = None

        # 干涉元件盒数据（前端 three.js 叠加高亮）
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

        return JSONResponse(
            {
                "ok": True,
                "job_id": job_id,
                "component_count": len(comps),
                "interference_count": len(reports),
                "interferences": reports,
                "interference_boxes": interference_boxes,
                "suspicious_components": suspicious_comps,
                "height_overrides": overrides_dict,
                "glb_url": glb_url,
                "message": f"分析完成：{len(comps)} 个元件，{len(reports)} 个干涉"
                if reports
                else f"分析完成：{len(comps)} 个元件，✅ 无干涉",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"干涉分析失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"干涉分析失败: {e}")


@app.post("/api/adjust")
async def api_adjust(instruction: str = Form(""), files: list[UploadFile] = File(...)):
    """自然语言调整治具参数 → 重新生成 DXF + 调整报告"""
    if not instruction.strip():
        raise HTTPException(400, "请输入调整指令")
    try:
        workdir = _extract_upload(files)
        job_id = workdir.name

        # 当前参数（从会话状态继承，或默认）
        from fixture_phase1 import FixtureParams
        from fixture_phase2 import Phase2Params

        p1 = _SESSION_PARAMS.get(job_id, {}).get(
            "p1", {k: v for k, v in FixtureParams().__dict__.items()}
        )
        p2 = _SESSION_PARAMS.get(job_id, {}).get(
            "p2", {k: v for k, v in Phase2Params().__dict__.items()}
        )

        # 解析调整
        r = parse_adjust_command(instruction, p1, p2)
        if not r.matched:
            return JSONResponse(
                {
                    "ok": False,
                    "message": f"未识别的指令：「{instruction}」。支持如「避位区外扩1mm」「治具外形倒角改5mm」「沉板区外扩0.5mm」等",
                }
            )

        # 应用调整
        if r.param in p1:
            p1[r.param] = r.new_value
        elif r.param in p2:
            p2[r.param] = r.new_value

        # 保存会话状态
        _SESSION_PARAMS[job_id] = {"p1": p1, "p2": p2, "gerber_dir": str(workdir)}

        # 用调整后参数重新生成
        from fixture_phase2 import run_phase2

        dxf_path = OUTPUT_DIR / f"{job_id}-adjusted.dxf"
        png_path = OUTPUT_DIR / f"{job_id}-adjusted.png"
        # 只传被修改的参数（覆盖默认值）
        result = run_phase2(str(workdir), str(dxf_path), params1_override=p1, params2_override=p2)
        if result is None:
            raise HTTPException(422, "调整后生成失败")

        # 渲染 PNG
        try:
            import matplotlib

            matplotlib.use("Agg")
            import ezdxf
            import matplotlib.pyplot as plt
            from ezdxf.addons.drawing import Frontend, RenderContext
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

            doc = ezdxf.readfile(str(dxf_path))
            ctx = RenderContext(doc)
            fig, ax = plt.subplots(figsize=(16, 10))
            backend = MatplotlibBackend(ax)
            Frontend(ctx, backend).draw_layout(doc.modelspace(), finalize=True)
            ax.set_aspect("equal")
            fig.savefig(str(png_path), dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception as e:
            log.warning(f"  PNG 渲染失败: {e}")

        return JSONResponse(
            {
                "ok": True,
                "matched": True,
                "param": r.param,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "action": r.action,
                "message": r.message,
                "dxf_url": f"/dl/{job_id}-adjusted.dxf",
                "png_url": f"/dl/{job_id}-adjusted.png",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"调整失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"调整失败: {e}")


@app.post("/api/generate3d")
async def api_generate3d(files: list[UploadFile] = File(...)):
    """上传 Gerber → 生成治具 3D（STL + GLB）+ 干涉分析"""
    if not files:
        raise HTTPException(400, "未收到文件")
    try:
        workdir = _extract_upload(files)
        # 先用 phase2 得到 2D 几何
        from shapely.ops import unary_union as _uu

        from fixture_phase1 import FixtureParams, make_sink_region, parse_gerber
        from fixture_phase2 import run_phase2

        board_polys, _drills = parse_gerber(str(workdir))
        if not board_polys:
            raise HTTPException(422, "未找到外形层")
        board = _uu(board_polys)
        sink = make_sink_region(board, FixtureParams())
        result2 = run_phase2(str(workdir), None)
        if result2 is None:
            raise HTTPException(422, "治具 2D 生成失败")
        outer = result2.outer_poly
        avoid = result2.avoid_polys
        solder = result2.solder_polys

        # 构建 3D
        mesh = build_fixture_3d(sink, avoid, solder, outer, Fixture3DParams())
        stl_path = OUTPUT_DIR / f"{workdir.name}-3d.stl"
        glb_path = OUTPUT_DIR / f"{workdir.name}-3d.glb"
        export_stl(mesh, str(stl_path))
        try:
            export_glb(mesh, str(glb_path))
            glb_ok = True
        except Exception:
            glb_ok = False

        # 干涉分析（无元件高度数据时返回空，提示需 KiCad 3D 模型）
        return JSONResponse(
            {
                "ok": True,
                "stl_url": f"/dl/{workdir.name}-3d.stl",
                "glb_url": f"/dl/{workdir.name}-3d.glb" if glb_ok else None,
                "stats": {
                    "volume_mm3": round(mesh.volume, 0),
                    "vertices": len(mesh.vertices),
                    "faces": len(mesh.faces),
                    "avoid_holes": len(avoid),
                    "solder_holes": len(solder),
                },
                "interference": {
                    "note": "干涉分析需要 PCB 元件 3D 高度数据（KiCad .kicad_pcb 的 3D 模型或 step 文件），当前仅提供 3D 几何预览。"
                },
                "message": "3D 治具生成成功",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"3D 生成失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"3D 生成失败: {e}")


@app.post("/api/generate")
async def api_generate(files: list[UploadFile] = File(...)):
    """上传 Gerber → 生成治具 DXF + PNG"""
    if not files:
        raise HTTPException(400, "未收到文件")
    try:
        workdir = _extract_upload(files)
        # 生成 DXF
        dxf_path = OUTPUT_DIR / f"{workdir.name}.dxf"
        png_path = OUTPUT_DIR / f"{workdir.name}.png"
        # 渲染函数
        from shapely.ops import unary_union as _uu

        from fixture_phase1 import FixtureParams, make_sink_region, parse_gerber
        from fixture_phase2 import run_phase2 as _run2

        # phase1（取手/压扣/定位销）→ phase2（避位/上锡/外形）
        board_polys, drills = parse_gerber(str(workdir))
        if not board_polys:
            raise HTTPException(422, "未找到外形层（Edge_Cuts/GM1）")
        board = _uu(board_polys)
        p1 = FixtureParams()
        sink, dogbone_corners = make_sink_region(board, p1, return_corners=True)

        from fixture_phase1 import make_handles, make_pins, make_screws

        r1 = SimpleNamespace(
            board_poly=board,
            sink_poly=sink,
            handles=make_handles(sink, p1),
            screws=make_screws(sink, p1),
            pins=make_pins(drills, p1, sink_poly=sink),
            dogbone_corners=dogbone_corners,
        )
        result = _run2(str(workdir), str(dxf_path))
        if result is None:
            raise HTTPException(422, "治具生成失败：未找到外形层或解析错误")

        # ── DRC 生产安全门禁（blocking/error → 只出带水印预览版）──
        from drc import apply_watermark, gate, run_drc

        issues = run_drc(r1, result)
        verdict = gate(issues)
        dxf_url = f"/dl/{workdir.name}.dxf"
        if not verdict["allowed"]:
            preview = apply_watermark(dxf_path)
            dxf_url = f"/dl/{Path(preview).name}"
            log.warning(f"  DRC 门禁未通过（{verdict['counts']}），已输出水印预览版")

        # 渲染 PNG 预览
        try:
            import matplotlib

            matplotlib.use("Agg")
            import ezdxf
            import matplotlib.pyplot as plt
            from ezdxf.addons.drawing import Frontend, RenderContext
            from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

            doc = ezdxf.readfile(str(dxf_path))
            ctx = RenderContext(doc)
            fig, ax = plt.subplots(figsize=(16, 10))
            backend = MatplotlibBackend(ax)
            Frontend(ctx, backend).draw_layout(doc.modelspace(), finalize=True)
            ax.set_aspect("equal")
            fig.savefig(str(png_path), dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception as e:
            log.warning(f"  PNG 渲染失败(不影响 DXF): {e}")

        # 统计信息
        stats = {
            "board_size": _safe(getattr(result, "outer_poly", None)),
            "avoid_count": len(getattr(result, "avoid_polys", [])),
            "solder_count": len(getattr(result, "solder_polys", [])),
            "cap_hole_count": len(getattr(result, "cap_holes", [])),
            "dogbone_count": len(getattr(result, "dogbone_corners", [])) or len(dogbone_corners),
        }
        msg = "治具生成成功"
        if not verdict["allowed"]:
            msg = (
                f"DRC 门禁未通过（blocking {verdict['counts']['blocking']} / "
                f"error {verdict['counts']['error']}）——仅提供带水印预览版，修正后可出生产版"
            )
        return JSONResponse(
            {
                "ok": True,
                "dxf_url": dxf_url,
                "png_url": f"/dl/{workdir.name}.png",
                "job_id": workdir.name,
                "stats": stats,
                "drc": {
                    "allowed": verdict["allowed"],
                    "counts": verdict["counts"],
                    "worst": verdict["worst"],
                    "total": verdict["total"],
                    "issues": issues,
                },
                "message": msg,
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"生成失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"生成失败: {e}")


@app.post("/api/review/confirm")
async def api_review_confirm(
    job_id: str = Form(...),
    review_id: str = Form(...),
    operator: str = Form(...),
    answer: str = Form(...),
):
    """工程师确认一条 review（低置信度/缺数据人工闭环），写入审计日志。"""
    try:
        from review import confirm_review

        hit = confirm_review(REVIEW_DIR, job_id, review_id, operator, answer)
        return JSONResponse({"ok": True, "review": hit})
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        log.error(f"review 确认失败: {e}")
        raise HTTPException(500, f"review 确认失败: {e}")


def _safe(poly) -> str:
    """多边形 → 尺寸字符串（容错）"""
    try:
        if poly is None:
            return ""
        b = poly.bounds
        w = round(b[2] - b[0], 1)
        h = round(b[3] - b[1], 1)
        return f"{w}×{h}mm"
    except Exception:
        return ""


@app.get("/dl/{fname}")
async def api_download(fname: str):
    """下载生成的文件（DXF/PNG/STL/GLB）。

    路径安全：用 Path.relative_to() 做**结构化**包含判断，而非字符串前缀比较——
    后者在 cwd 变化/同名前缀目录（如 output-old）时会误判或漏判。
    """
    base = OUTPUT_DIR.resolve()
    try:
        p = (base / fname).resolve()
    except (OSError, ValueError):
        raise HTTPException(400, "非法文件名")
    try:
        p.relative_to(base)  # 不在 output 目录下会抛 ValueError
    except ValueError:
        raise HTTPException(400, "非法文件名")
    if not p.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(p), filename=fname)


@app.get("/api/health")
async def api_health():
    return {"ok": True, "service": "fixture-ai"}


# 静态前端
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="波峰焊治具 AI Web 服务")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    import uvicorn

    print(f"🚀 波峰焊治具 AI 已启动: http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
