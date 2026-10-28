"""MCP server: tool registry, direct tool calls and a real stdio handshake.

The stdio test mirrors what directories such as Glama check: the server starts,
answers ``initialize`` and lists its tools over JSON-RPC on stdin/stdout.
"""

from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import mcp_server

REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_003 = REPO_ROOT / "cases" / "case_003_stm32_4layer"

EXPECTED_TOOLS = {
    "list_fixture_materials",
    "get_wave_process_window",
    "compute_dogbone_relief",
    "design_wave_flow_chamfers",
    "check_thermal_expansion_gap",
    "estimate_fixture_quotation",
    "check_preheat_profile",
    "predict_dross_bridging",
    "analyze_gerber_board",
    "generate_fixture_from_gerber",
}
WRITES_FILES = {"generate_fixture_from_gerber"}


def _list_tools():
    return asyncio.run(mcp_server.mcp.list_tools())


def _call(name: str, args: dict) -> dict:
    """Call a tool in-process and return its JSON payload (SDK v1 and v2 shapes)."""
    result = asyncio.run(mcp_server.mcp.call_tool(name, args))
    if isinstance(result, tuple):  # SDK v1: (content, structured)
        result = result[0]
    content = getattr(result, "content", result)  # SDK v2: CallToolResult
    assert not getattr(result, "isError", False) and not getattr(result, "is_error", False)
    return json.loads(content[0].text)


def _annotation(tool, camel: str, snake: str):
    ann = getattr(tool, "annotations", None)
    if ann is None:
        return None
    return getattr(ann, snake, None) if hasattr(ann, snake) else getattr(ann, camel, None)


def test_tools_list_matches_expected_set():
    tools = _list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t.description and len(t.description) > 40, t.name
        schema = getattr(t, "inputSchema", None) or t.input_schema
        assert schema["type"] == "object"


def test_read_only_annotations():
    for t in _list_tools():
        if getattr(t, "annotations", None) is None:  # SDK without annotation support
            continue
        assert _annotation(t, "readOnlyHint", "read_only_hint") is (t.name not in WRITES_FILES), t.name
        assert _annotation(t, "destructiveHint", "destructive_hint") is False


def test_parameters_are_described():
    tools = {t.name: t for t in _list_tools()}
    schema = getattr(tools["estimate_fixture_quotation"], "inputSchema", None) or \
        tools["estimate_fixture_quotation"].input_schema
    props = schema["properties"]
    assert set(schema["required"]) == {"pallet_width_mm", "pallet_height_mm"}
    assert all(p.get("description") for p in props.values())
    assert props["material"]["enum"] == ["durostone", "ricocel", "fr4_high_tg", "aluminum"]


def test_call_quotation():
    out = _call(
        "estimate_fixture_quotation",
        {"pallet_width_mm": 300, "pallet_height_mm": 200, "quantity": 10, "screws_m3x16": 4},
    )
    assert out["quantity"] == 10
    assert out["blanks_per_sheet"] > 0
    assert out["quote_total_cny"] > out["hardware_cost_cny"] > 0
    assert out["currency"] == "CNY"


def test_call_dogbone_relief_on_rectangle():
    out = _call("compute_dogbone_relief", {"outline": [[0, 0], [100, 0], [100, 60], [0, 60]]})
    assert out["corner_count"] == 4
    assert out["pocket_area_mm2"] > out["board_area_mm2"] == 6000.0


def test_call_thermal_expansion_flags_risk():
    out = _call("check_thermal_expansion_gap", {"pallet_length_mm": 300})
    assert out["at_risk"] is True
    assert out["differential_mm"] > 0


def test_call_process_window_with_material_check():
    out = _call("get_wave_process_window", {"solder": "lead_free", "material": "durostone"})
    assert out["process"]["key"] == "lead_free"
    assert out["material_check"]["compatible_with_lead_free"] is True


def test_call_analyze_gerber_board():
    out = _call("analyze_gerber_board", {"gerber_dir": str(CASE_003)})
    assert out["ok"] is True
    assert out["board_bounds"]["width_mm"] == pytest.approx(37.0, abs=0.5)
    assert out["drill_count"] > 0


def test_call_generate_fixture_writes_only_into_output_dir(tmp_path):
    out = _call(
        "generate_fixture_from_gerber",
        {"gerber_dir": str(CASE_003), "output_dir": str(tmp_path)},
    )
    assert out["verdict"] in {"PASS", "FAIL"}
    for key in ("dxf", "gcode", "drc_report"):
        p = Path(out["files"][key])
        assert p.is_file() and p.parent == tmp_path.resolve()
    assert out["gcode"]["machining_minutes"] > 0


def test_stdio_initialize_and_tools_list():
    """Start the server as a subprocess and speak raw JSON-RPC over stdio."""
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "mcp_server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=str(REPO_ROOT),
    )
    lines: queue.Queue[bytes] = queue.Queue()
    threading.Thread(target=lambda: [lines.put(ln) for ln in proc.stdout], daemon=True).start()

    def send(msg: dict) -> None:
        proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        proc.stdin.flush()

    def recv(msg_id: int) -> dict:
        while True:
            msg = json.loads(lines.get(timeout=60))
            if msg.get("id") == msg_id:
                return msg

    try:
        send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        })
        init = recv(1)
        assert init["result"]["serverInfo"]["name"] == "wave-fixture-ai"
        assert "tools" in init["result"]["capabilities"]

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = recv(2)
        assert {t["name"] for t in listed["result"]["tools"]} == EXPECTED_TOOLS
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
