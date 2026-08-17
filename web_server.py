# -*- coding: utf-8 -*-
"""
波峰焊治具 AI 设计助手 — Web 服务
拖 Gerber → 生成治具 DXF → 预览 PNG → 下载

启动: python web_server.py [--port 8000]
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("fixture-web")

# FastAPI 导入（延迟到 main 判断，便于直接跑脚本测试核心函数）
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fixture_phase2 import run_phase2
from fixture_3d import build_fixture_3d, export_stl, export_glb, Fixture3DParams
from nl_adjust import parse_adjust_command, apply_adjustments

app = FastAPI(title="波峰焊治具 AI 设计助手", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).parent / "web"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 上传临时目录
TMP_DIR = Path(tempfile.gettempdir()) / "fixture-uploads"
TMP_DIR.mkdir(exist_ok=True)


def _extract_upload(files: list[UploadFile]) -> Path:
    """把上传的多个 Gerber 文件解压到一个临时目录，返回目录路径"""
    job_id = f"job_{int(time.time()*1000)}"
    workdir = TMP_DIR / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    for f in files:
        data = f.file.read()
        name = f.filename or "unknown"
        # 支持 zip 包
        if name.lower().endswith(".zip"):
            zpath = workdir / name
            zpath.write_bytes(data)
            try:
                with zipfile.ZipFile(zpath) as z:
                    z.extractall(workdir)
            except Exception as e:
                log.warning(f"  zip 解压失败: {e}")
            continue
        # 普通 Gerber/DRL 文件
        (workdir / name).write_bytes(data)
    return workdir


# 会话参数状态（job_id → 参数覆盖 dict）
_SESSION_PARAMS: dict = {}


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
        p1 = _SESSION_PARAMS.get(job_id, {}).get("p1", {k: v for k, v in FixtureParams().__dict__.items()})
        p2 = _SESSION_PARAMS.get(job_id, {}).get("p2", {k: v for k, v in Phase2Params().__dict__.items()})

        # 解析调整
        r = parse_adjust_command(instruction, p1, p2)
        if not r.matched:
            return JSONResponse({
                "ok": False,
                "message": f"未识别的指令：「{instruction}」。支持如「避位区外扩1mm」「治具外形倒角改5mm」「沉板区外扩0.5mm」等",
            })

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
        result = run_phase2(str(workdir), str(dxf_path),
                            params1_override=p1, params2_override=p2)
        if result is None:
            raise HTTPException(422, "调整后生成失败")

        # 渲染 PNG
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import ezdxf
            from ezdxf.addons.drawing import RenderContext, Frontend
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

        return JSONResponse({
            "ok": True,
            "matched": True,
            "param": r.param,
            "old_value": r.old_value,
            "new_value": r.new_value,
            "action": r.action,
            "message": r.message,
            "dxf_url": f"/dl/{job_id}-adjusted.dxf",
            "png_url": f"/dl/{job_id}-adjusted.png",
        })
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
        from fixture_phase1 import parse_gerber, make_sink_region, FixtureParams
        from fixture_phase2 import run_phase2, Phase2Params
        from shapely.ops import unary_union as _uu

        board_polys, drills = parse_gerber(str(workdir))
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
        return JSONResponse({
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
        })
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
        result = run_phase2(str(workdir), str(dxf_path))
        if result is None:
            raise HTTPException(422, "治具生成失败：未找到外形层或解析错误")

        # 渲染 PNG 预览
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import ezdxf
            from ezdxf.addons.drawing import RenderContext, Frontend
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
        }
        return JSONResponse({
            "ok": True,
            "dxf_url": f"/dl/{workdir.name}.dxf",
            "png_url": f"/dl/{workdir.name}.png",
            "job_id": workdir.name,
            "stats": stats,
            "message": "治具生成成功",
        })
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"生成失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"生成失败: {e}")


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
    """下载生成的文件（DXF/PNG）"""
    # 安全：只允许 output 目录内的文件
    p = (OUTPUT_DIR / fname).resolve()
    if not str(p).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(400, "非法文件名")
    if not p.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(p), filename=fname)


@app.get("/api/health")
async def api_health():
    return {"ok": True, "service": "fixture-ai"}


# 静态前端
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="波峰焊治具 AI Web 服务")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    import uvicorn
    print(f"🚀 波峰焊治具 AI 已启动: http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
