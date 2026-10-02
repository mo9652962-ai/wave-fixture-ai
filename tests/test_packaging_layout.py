"""前端静态目录定位测试——源码布局与 pip 安装布局。

真实验证背景（第 16 个缺陷，发布阻断级）：
wheel 用 data-files 把 index.html 装到 `<venv>/share/wave-fixture-ai/`，
而 web_server 原用 `Path(__file__).parent / "web"` → pip 安装后目录不存在
→ FastAPI StaticFiles 构造时抛 RuntimeError → **装完根本起不来服务**。
修复：多候选路径 + importlib.metadata 精确定位。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web_server import _resolve_web_dir


def test_source_layout_resolves():
    """源码运行时必须解析到 <repo>/web（含 index.html）。"""
    d = _resolve_web_dir()
    assert (d / "index.html").is_file(), f"未解析到前端目录: {d}"


def test_resolved_dir_has_expected_assets():
    d = _resolve_web_dir()
    html = (d / "index.html").read_text(encoding="utf-8")
    # 关键 UI 元素必须在（防止打包了错误/占位文件）
    assert "波峰焊治具" in html
    assert "生成治具" in html
    assert "DRC 门禁" in html, "前端缺少 DRC 门禁展示（缺陷⑨的修复点）"


def test_share_layout_is_a_candidate(monkeypatch, tmp_path):
    """模拟 pip 安装布局：site-packages 无 web/ 时，应回退到 sys.prefix/share。"""
    import web_server as ws

    share = tmp_path / "share" / "wave-fixture-ai"
    share.mkdir(parents=True)
    (share / "index.html").write_text("<html>pip-installed</html>", encoding="utf-8")

    # 让源码候选失效（指向不存在的目录），并让 sys.prefix 指向 tmp
    fake_here = tmp_path / "site-packages"
    fake_here.mkdir()
    monkeypatch.setattr(ws, "__file__", str(fake_here / "web_server.py"))
    monkeypatch.setattr(ws.sys, "prefix", str(tmp_path))

    d = ws._resolve_web_dir()
    assert (d / "index.html").is_file()
    assert "pip-installed" in (d / "index.html").read_text(encoding="utf-8")


def test_missing_everywhere_falls_back_without_crash(monkeypatch, tmp_path):
    """全部候选都不存在时，不得抛异常——返回候选路径并告警（由 StaticFiles 报清晰错误）。"""
    import web_server as ws

    fake_here = tmp_path / "nowhere"
    fake_here.mkdir()
    monkeypatch.setattr(ws, "__file__", str(fake_here / "web_server.py"))
    monkeypatch.setattr(ws.sys, "prefix", str(tmp_path / "no-prefix"))
    monkeypatch.setattr(ws.sys, "base_prefix", str(tmp_path / "no-base"))
    d = ws._resolve_web_dir()  # 不抛异常即通过
    assert isinstance(d, Path)


@pytest.mark.skipif(
    not (ROOT / "dist").glob("*.whl") if (ROOT / "dist").exists() else True,
    reason="无构建产物",
)
def test_wheel_contains_index_html():
    """构建产物必须包含前端资源（否则 pip 安装后无界面）。"""
    import zipfile

    whl = next((ROOT / "dist").glob("*.whl"))
    names = zipfile.ZipFile(whl).namelist()
    assert any(n.endswith("index.html") for n in names), f"wheel 缺 index.html: {names}"
