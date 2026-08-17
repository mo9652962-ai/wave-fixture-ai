# -*- coding: utf-8 -*-
"""
interference — 干涉分析：PCB 元件 vs 治具 3D

输入：KiCad .kicad_pcb（元件位置+尺寸）+ 治具 3D 实体（STL）
流程：
1. 解析 .kicad_pcb：提取每个 footprint 的 (位置, 包围盒尺寸, 元件名)
2. 元件高度：从封装名查表（R_0603→0.45mm, C_0603→0.9mm, LED→1.1mm 等）
3. 元件 3D 包围盒 vs 治具 STL 布尔交集 → 干涉报告

高度表（标准 SMD 封装典型高度，mm）：
- 0603 电阻/电容: 0.45 / 0.9
- 0805 电阻/电容: 0.5 / 1.25
- SOT-223: 1.7
- SOIC-8: 1.75
- QFP/QFN: 1.4
- 连接器: 2.5+
- ESP32 模块: 3.2
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("interference")

# 封装名 → (宽, 高, 厚) 典型尺寸 mm（不含引脚）
FOOTPRINT_DIMS = {
    "r_0603": (1.6, 0.8, 0.45),
    "c_0603": (1.6, 0.8, 0.9),
    "r_0805": (2.0, 1.25, 0.5),
    "c_0805": (2.0, 1.25, 1.25),
    "r_1206": (3.2, 1.6, 0.6),
    "c_1206": (3.2, 1.6, 1.5),
    "led_0603": (1.6, 0.8, 1.1),
    "sot-223": (6.5, 3.5, 1.7),
    "sot-23": (2.9, 1.6, 1.1),
    "soic-8": (5.0, 4.0, 1.75),
    "soic-16": (10.0, 4.0, 1.75),
    "tssop": (6.4, 4.4, 1.2),
    "qfn": (4.0, 4.0, 0.9),
    "qfp": (7.0, 7.0, 1.4),
    "esp32": (18.0, 25.5, 3.2),
    "type-c": (9.4, 7.3, 3.2),
    "pinheader": (20.0, 5.0, 8.5),
    "usb": (13.1, 8.0, 3.0),
    "sw-smd": (3.9, 3.0, 2.0),
    "sw": (6.0, 6.0, 4.0),
}


def _fp_key(footprint_name: str) -> str:
    """封装名 → 查表 key（提取关键型号）"""
    name = footprint_name.lower()
    # 优先精确匹配子串
    for key in FOOTPRINT_DIMS:
        if key in name:
            return key
    return None


def parse_kicad_pcb(pcb_path: str) -> list[dict]:
    """
    解析 KiCad .kicad_pcb → 元件列表 [{name, x, y, w, h, height, ref}]
    """
    txt = Path(pcb_path).read_text(encoding="utf-8", errors="replace")
    components = []

    # 按 footprint 块切分
    # footprint 块形如: (footprint "lib:name" (layer "F.Cu") (at x y angle) ... (property "Reference" "R1") ...)
    # 用正则逐步扫描
    pos = 0
    fp_re = re.compile(r'\(footprint "([^"]+)"')
    while True:
        m = fp_re.search(txt, pos)
        if not m:
            break
        start = m.start()
        fp_name = m.group(1)
        # 找到匹配的右括号（简单计数）
        depth = 0
        i = start
        while i < len(txt):
            if txt[i] == "(":
                depth += 1
            elif txt[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = txt[start:i + 1]
        pos = i + 1

        # 提取位置 (at x y angle)
        at_m = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", block)
        if not at_m:
            continue
        x, y = float(at_m.group(1)), float(at_m.group(2))

        # 参考号
        ref_m = re.search(r'\(property "Reference" "([^"]+)"', block)
        ref = ref_m.group(1) if ref_m else "?"

        # 元件尺寸
        key = _fp_key(fp_name)
        if key:
            w, h, height = FOOTPRINT_DIMS[key]
        else:
            # 未知封装：用 pads 范围估算（粗略）
            pad_xs = [float(v) for v in re.findall(r'\(at ([-\d.]+) [-\d.]+', block)]
            pad_ys = [float(v) for v in re.findall(r'\(at [-\d.]+ ([-\d.]+)', block)]
            if len(pad_xs) >= 2:
                w = (max(pad_xs) - min(pad_xs)) + 0.5
                h = (max(pad_ys) - min(pad_ys)) + 0.5
                height = 1.5
            else:
                w, h, height = 2.0, 1.0, 1.0
            key = "unknown"

        components.append({
            "name": fp_name.split(":")[-1],
            "ref": ref,
            "x": x, "y": y,
            "w": w, "h": h,
            "height": height,
            "fp_key": key,
        })

    return components


def build_component_meshes(components: list[dict], pcb_thickness: float = 1.6) -> trimesh.Trimesh:
    """元件 3D 包围盒合体（PCB 表面 z=pcb_thickness 向上）"""
    meshes = []
    for c in components:
        box = trimesh.creation.box(extents=[c["w"], c["h"], c["height"]])
        # 元件中心在 PCB 表面 + 高度一半
        box.apply_translation([c["x"], c["y"], pcb_thickness + c["height"] / 2])
        meshes.append(box)
    return trimesh.util.concatenate(meshes) if meshes else None


def analyze_interference(
    fixture_stl: str,
    components: list[dict],
    pcb_thickness: float = 1.6,
) -> list[dict]:
    """
    干涉分析：每个元件包围盒 vs 治具实体。

    治具在 z=0..thickness，PCB 表面在 z=pcb_thickness（沉板区下沉）。
    元件在 PCB 上方 → 若元件超出避位区通孔高度 → 与治具实体干涉。
    返回: [{ref, name, x, y, w, h, height, overlap_mm3}]
    """
    fixture = trimesh.load(fixture_stl)
    reports = []
    for c in components:
        comp = trimesh.creation.box(extents=[c["w"], c["h"], c["height"]])
        comp.apply_translation([c["x"], c["y"], pcb_thickness + c["height"] / 2])
        try:
            inter = fixture.intersection(comp, engine="manifold")
            vol = inter.volume if inter is not None else 0.0
            if vol > 0.05:  # 容差：>0.05 mm³ 视为干涉
                reports.append({
                    **c,
                    "overlap_mm3": round(vol, 2),
                })
        except Exception as e:
            log.warning(f"  干涉检测 {c['ref']} 失败: {e}")
    return reports


if __name__ == "__main__":
    import sys
    # 自测：ESP32 dev 板
    pcb = r"D:\kicad-test-board\basic-esp32s3-dev-board\dev-board.kicad_pcb"
    comps = parse_kicad_pcb(pcb)
    print(f"解析元件: {len(comps)} 个")
    for c in comps[:8]:
        print(f"  {c['ref']:6s} {c['name'][:35]:35s} {c['w']:.1f}x{c['h']:.1f} h={c['height']:.2f}")
    # 未知封装统计
    unknowns = [c for c in comps if c["fp_key"] == "unknown"]
    print(f"未知封装: {len(unknowns)} 个")
