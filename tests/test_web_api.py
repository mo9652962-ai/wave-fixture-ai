"""Web API 端点测试——覆盖全部 7 个端点的契约与错误路径。

背景：真机端到端验证暴露的前 13 个缺陷里有 3 个在 API/UI 层
（matplotlib 漏声明、前端未渲染 drc、下载端点路径比较），
但 API 层此前**零测试**——本文件补齐契约测试。

设计：用 FastAPI TestClient + 真实 Gerber 文件（cases/case_003，最小且完整），
不 mock 几何计算（真跑），只隔离输出目录与临时上传区。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_server

CASE = ROOT / "cases" / "case_003_stm32_4layer"


def _files_for_upload() -> list[tuple[str, tuple[str, bytes, str]]]:
    """构造 multipart 上传文件列表（真实板文件）。"""
    out = []
    for name in ("board-Edge_Cuts.gm1", "board-B_Mask.gbs", "board-F_Mask.gts", "board.drl"):
        p = CASE / name
        if p.exists():
            out.append(("files", (name, p.read_bytes(), "text/plain")))
    return out


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, "OUTPUT_DIR", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    return TestClient(web_server.app)


pytestmark = pytest.mark.skipif(
    not (CASE / "board-Edge_Cuts.gm1").exists(),
    reason="case_003 真实板文件缺失",
)


# ── /api/health ─────────────────────────────────────────────────
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["service"] == "fixture-ai"


# ── /api/generate ───────────────────────────────────────────────
def test_generate_returns_full_contract(client):
    """生成端点必须返回前端渲染所需的**全部**字段（drc 曾漏渲染即此契约缺失）。"""
    r = client.post("/api/generate", files=_files_for_upload())
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("ok", "dxf_url", "png_url", "job_id", "stats", "drc", "message"):
        assert key in d, f"响应缺少字段 {key}"
    assert d["ok"] is True
    # DRC 契约：门禁结论 + 分级计数 + 问题清单（含出处）
    drc = d["drc"]
    for k in ("allowed", "counts", "worst", "total", "issues"):
        assert k in drc
    assert isinstance(drc["allowed"], bool)
    assert set(drc["counts"]) >= {"blocking", "error", "warning", "info"}
    # stats 契约
    for k in ("board_size", "avoid_count", "solder_count", "cap_hole_count"):
        assert k in d["stats"]


def test_generate_artifacts_downloadable(client):
    """生成后 dxf/png 必须可下载（真机曾因路径判断 404）。"""
    d = client.post("/api/generate", files=_files_for_upload()).json()
    assert client.get(d["dxf_url"]).status_code == 200
    assert client.get(d["png_url"]).status_code == 200


def test_generate_rejects_empty_upload(client):
    assert client.post("/api/generate", files=[]).status_code in (400, 422)


def test_generate_rejects_no_outline(client):
    """只传 mask 无外形层 → 必须报错而非产出空治具。"""
    only_mask = [("files", ("board-B_Mask.gbs", (CASE / "board-B_Mask.gbs").read_bytes(), "text/plain"))]
    r = client.post("/api/generate", files=only_mask)
    assert r.status_code in (400, 422, 500)
    assert "外形" in r.text or "outline" in r.text.lower()


# ── /api/generate3d ─────────────────────────────────────────────
def test_generate3d_returns_stl_and_glb(client):
    r = client.post("/api/generate3d", files=_files_for_upload())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["stl_url"] and d["glb_url"], "3D 端点必须同时给出 STL 与 GLB（前端可视化依赖 GLB）"
    assert client.get(d["stl_url"]).status_code == 200
    assert client.get(d["glb_url"]).status_code == 200
    assert d["stats"]["volume_mm3"] > 0


# ── /api/adjust ─────────────────────────────────────────────────
def test_adjust_natural_language_roundtrip(client):
    """自然语言调整：识别 → 改参 → 重新生成 → 返回新产物。"""
    r = client.post(
        "/api/adjust",
        data={"instruction": "避位区外扩1mm"},
        files=_files_for_upload(),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True and d["matched"] is True
    assert d["param"] == "avoid_pad_extra"
    assert d["action"] == "increase"
    assert d["new_value"] > d["old_value"]
    assert client.get(d["dxf_url"]).status_code == 200


def test_adjust_rejects_unrecognized_instruction(client):
    """无法识别的指令必须明确拒绝并提示可用示例（不静默忽略）。"""
    r = client.post("/api/adjust", data={"instruction": "今天天气不错"}, files=_files_for_upload())
    d = r.json()
    assert d["ok"] is False
    assert "未识别" in d["message"]


def test_adjust_rejects_empty_instruction(client):
    r = client.post("/api/adjust", data={"instruction": "  "}, files=_files_for_upload())
    assert r.status_code == 400


# ── /api/review/confirm ─────────────────────────────────────────
def test_review_confirm_reports_missing(tmp_path, monkeypatch):
    """确认不存在的 review → 404（不静默成功）。"""
    monkeypatch.setattr(web_server, "REVIEW_DIR", tmp_path / "reviews")
    r = client_post_review(web_server, tmp_path, "job-x", "review-deadbeef-nope", "op", "ans")
    assert r.status_code == 404


def client_post_review(mod, tmp_path, job_id, review_id, operator, answer):
    """独立构造一个 TestClient 发请求（review 用独立 session 状态）。"""
    with TestClient(mod.app) as c:
        return c.post(
            "/api/review/confirm",
            data={"job_id": job_id, "review_id": review_id, "operator": operator, "answer": answer},
        )


def test_review_confirm_success_path(tmp_path, monkeypatch):
    """已有 pending review 时确认成功并写审计。"""
    import review as review_mod

    base = tmp_path / "reviews-data"
    monkeypatch.setattr(web_server, "REVIEW_DIR", base)
    # 造一条 pending
    sha = "abcdef12" + "0" * 56
    items = [review_mod.ReviewItem(id=f"review-{sha[:8]}-no_smd_confirm",
                                   type="NO_SMD_CONFIRM", reason="测试用")]
    review_mod.save_pending(items, base, sha)
    with TestClient(web_server.app) as c:
        r = c.post("/api/review/confirm", data={
            "job_id": sha, "review_id": items[0].id, "operator": "sora", "answer": "确认无贴片",
        })
    assert r.status_code == 200, r.text
    assert r.json()["review"]["status"] == "confirmed"


# ── /api/interference ───────────────────────────────────────────
def test_interference_requires_kicad_pcb(client):
    """无 .kicad_pcb 时必须明确提示（Gerber 无元件高度信息）。

    契约：业务性拒绝用 HTTP 200 + {ok: false, message}（非协议错误，不用 4xx）。
    这是刻意的 API 设计——前端据 ok=false 显示提示而非抛异常。
    """
    r = client.post("/api/interference", files=_files_for_upload())
    assert r.status_code == 200, "业务性拒绝应为 200 + ok:false"
    d = r.json()
    assert d["ok"] is False
    assert "kicad_pcb" in d["message"] or "KiCad" in d["message"]
    assert "元件" in d["message"], "提示必须说明原因（Gerber 缺元件高度信息）"


def test_interference_with_real_kicad(client):
    """带 .kicad_pcb 的真实板：返回干涉清单 + 高亮盒 + GLB（前端可视化三件套）。"""
    files = _files_for_upload()
    pcb = CASE / "board.kicad_pcb"
    if not pcb.exists():
        pytest.skip("case_003 无 kicad_pcb")
    files.append(("files", ("board.kicad_pcb", pcb.read_bytes(), "text/plain")))
    r = client.post("/api/interference", files=files)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert "component_count" in d and "interference_count" in d
    assert d["glb_url"], "干涉结果必须带 GLB（前端 3D 可视化依赖）"
    assert client.get(d["glb_url"]).status_code == 200
    if d["interference_count"]:
        b = d["interference_boxes"][0]
        for k in ("ref", "name", "x", "y", "w", "h", "height", "overlap_mm3"):
            assert k in b, f"高亮盒缺少字段 {k}"
