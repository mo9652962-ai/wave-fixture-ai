"""
KiCad Action Plugin for Wave Fixture AI
Integrates Wave Fixture AI into KiCad PCB Editor (Pcbnew).
"""

from __future__ import annotations

import os
import webbrowser

try:
    import pcbnew
except ImportError:
    pcbnew = None


class WaveFixturePlugin(pcbnew.ActionPlugin if pcbnew else object):
    def defaults(self):
        self.name = "Wave Fixture AI"
        self.category = "Manufacturing / CAM"
        self.description = "Generate wave soldering pallets, 3D models, and CNC G-code from board layout"
        self.show_on_toolbar = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Run(self):
        showcase_url = "https://mo9652962-ai.github.io/wave-fixture-ai/"
        webbrowser.open(showcase_url)


if pcbnew:
    WaveFixturePlugin().register()
