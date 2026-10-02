"""Web 服务下载端点测试——路径安全与文件可见性。

背景（2026-10-02 真板 Web 全流程验证暴露）：
`/dl/{fname}` 的路径安全用**字符串前缀比较** `str(p).startswith(str(OUTPUT_DIR.resolve()))`，
而 OUTPUT_DIR 经 `Path(__file__).parent` 解析后受 cwd 影响；实测服务以不同 cwd 启动时，
**已生成的文件被判为非法/不存在 → 下载 404**（文件明明在磁盘上）。
改用 `Path.relative_to()` 结构化判断后修复，同时保持路径穿越防护。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web_server


@pytest.fixture
def client(tmp_path, monkeypatch):
    """把 OUTPUT_DIR 指向临时目录，避免污染真实 output。"""
    monkeypatch.setattr(web_server, "OUTPUT_DIR", tmp_path)
    tmp_path.mkdir(exist_ok=True)
    return TestClient(web_server.app), tmp_path


def test_download_existing_file(client):
    c, out = client
    (out / "job_test.dxf").write_text("0\nSECTION\n", encoding="utf-8")
    r = c.get("/dl/job_test.dxf")
    assert r.status_code == 200, "已存在的文件必须可下载（原前缀比较实现会 404）"
    assert "SECTION" in r.text


def test_download_missing_file_404(client):
    c, _out = client
    assert c.get("/dl/nope.dxf").status_code == 404


def test_download_rejects_traversal(client):
    """路径穿越必须被拒（相对路径 ../ 与绝对路径两种）。"""
    c, _out = client
    for bad in ("../web_server.py", "..%2Fweb_server.py", "sub/../../web_server.py"):
        r = c.get(f"/dl/{bad}")
        assert r.status_code in (400, 404), f"{bad} 未被拒绝（{r.status_code}）"


def test_download_rejects_sibling_prefix_dir(client, tmp_path):
    """同名前缀目录（output-old）不能被前缀比较误判为合法。"""
    c, out = client
    sibling = out.parent / (out.name + "-old")
    sibling.mkdir(exist_ok=True)
    (sibling / "leak.dxf").write_text("secret", encoding="utf-8")
    r = c.get("/dl/../" + sibling.name + "/leak.dxf")
    assert r.status_code in (400, 404), "同名前缀目录被误判为合法（前缀比较漏洞）"


def test_download_works_after_cwd_change(client, tmp_path, monkeypatch):
    """cwd 变化后仍能下载（原实现依赖 resolve() 的 cwd 敏感性）。"""
    c, out = client
    (out / "job_cwd.dxf").write_text("ok", encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)
    assert c.get("/dl/job_cwd.dxf").status_code == 200
