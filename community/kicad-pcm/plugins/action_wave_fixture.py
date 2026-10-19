"""
KiCad Action Plugin for Wave Fixture AI
Integrates Wave Fixture AI into KiCad PCB Editor (Pcbnew).
Supports KiCad 8.0, 9.0, and 10.0 on Windows, Linux, and macOS.
"""

from __future__ import annotations

import os
import webbrowser

try:
    import pcbnew
except ImportError:
    pcbnew = None

try:
    import wx
except ImportError:
    wx = None

SHOWCASE_URL = "https://mo9652962-ai.github.io/wave-fixture-ai/"
LOCAL_SERVER_URL = "http://127.0.0.1:8000/"
OFFLINE_CMD = "uvx wave-fixture-ai"


class WaveFixturePlugin(pcbnew.ActionPlugin if pcbnew else object):
    def defaults(self):
        self.name = "Wave Fixture AI"
        self.category = "Manufacturing / CAM"
        self.description = "Automated wave soldering pallet, 3D clearance preview, and CNC G-code"
        self.show_on_toolbar = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")
        self.dark_icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def _get_board_summary(self, board) -> dict:
        summary = {
            "file": "",
            "width_mm": 0.0,
            "height_mm": 0.0,
            "pads": 0,
            "tracks": 0,
        }
        if not board:
            return summary

        if board is not None and hasattr(board, "GetFileName"):
            summary["file"] = os.path.basename(board.GetFileName() or "")

        if board is not None and hasattr(board, "GetBoardEdgesBoundingBox"):
            bbox = board.GetBoardEdgesBoundingBox()
            if bbox is not None:
                # KiCad internal units: nm (nanometers)
                summary["width_mm"] = round(bbox.GetWidth() / 1e6, 1)
                summary["height_mm"] = round(bbox.GetHeight() / 1e6, 1)

        if board is not None and hasattr(board, "GetPads"):
            pads = board.GetPads()
            if pads is not None:
                summary["pads"] = len(pads)

        if board is not None and hasattr(board, "GetTracks"):
            tracks = board.GetTracks()
            if tracks is not None:
                summary["tracks"] = len(tracks)

        return summary

    def _show_dialog(self, summary: dict):
        """Displays a native wx dialog inside KiCad if wx is available."""
        if not wx:
            webbrowser.open(SHOWCASE_URL)
            return

        msg = (
            f"Wave Fixture AI · 波峰焊治具助手\n\n"
            f"当前工程: {summary['file'] or '未命名板卡'}\n"
            f"板卡尺寸: {summary['width_mm']} × {summary['height_mm']} mm\n"
            f"焊盘数量: {summary['pads']} 个 (插件/贴片)\n\n"
            f"• 点击 [确定]：在浏览器中打开 3D 治具工作台与 DRC 门禁分析\n"
            f"• 离线命令：可在终端运行「{OFFLINE_CMD}」本地使用"
        )
        dlg = wx.MessageDialog(
            None,
            msg,
            "Wave Fixture AI",
            wx.OK | wx.CANCEL | wx.ICON_INFORMATION,
        )
        dlg.SetOKCancelLabels("打开 3D 治具工作台", "取消")
        ret = dlg.ShowModal()
        dlg.Destroy()

        if ret == wx.ID_OK:
            webbrowser.open(SHOWCASE_URL)

    def Run(self):
        board = None
        if pcbnew:
            try:
                board = pcbnew.GetBoard()
            except Exception:
                board = None

        summary = self._get_board_summary(board)
        self._show_dialog(summary)


if pcbnew:
    WaveFixturePlugin().register()
