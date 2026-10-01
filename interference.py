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
from pathlib import Path

import trimesh

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("interference")

# 封装名 → (宽, 高, 厚) 典型尺寸 mm（不含引脚）
# 参考：IPC/JEDEC 标准封装尺寸 + 主流厂商 datasheet 典型值
FOOTPRINT_DIMS = {
    # ── 电阻 / 电容（公制）──
    "r_0201": (0.6, 0.3, 0.23),
    "c_0201": (0.6, 0.3, 0.3),
    "r_0402": (1.0, 0.5, 0.35),
    "c_0402": (1.0, 0.5, 0.5),
    "r_0603": (1.6, 0.8, 0.45),
    "c_0603": (1.6, 0.8, 0.9),
    "r_0805": (2.0, 1.25, 0.5),
    "c_0805": (2.0, 1.25, 1.25),
    "r_1206": (3.2, 1.6, 0.6),
    "c_1206": (3.2, 1.6, 1.5),
    "r_1210": (3.2, 2.5, 0.65),
    "c_1210": (3.2, 2.5, 1.8),
    "r_2010": (5.0, 2.5, 0.65),
    "c_2010": (5.0, 2.5, 2.0),
    "r_2512": (6.3, 3.2, 0.65),
    "c_2512": (6.3, 3.2, 2.5),
    # ── 钽电容（A/B/C/D/E 型）──
    "tantalum_a": (3.2, 1.6, 1.6),
    "tantalum_b": (3.5, 2.8, 1.9),
    "tantalum_c": (6.0, 3.2, 2.5),
    "tantalum_d": (7.3, 4.3, 2.9),
    "tantalum_e": (7.3, 4.3, 4.0),
    # ── 铝电解（SMD）──
    "alum_5x5": (5.0, 5.0, 5.4),
    "alum_6x6": (6.3, 6.3, 5.4),
    "alum_8x8": (8.0, 8.0, 10.0),
    "alum_10x10": (10.0, 10.0, 10.0),
    # ── 二极管 / 稳压 ──
    "sod-123": (2.7, 1.6, 1.2),
    "sod-323": (1.8, 1.3, 1.0),
    "sod-523": (1.6, 0.8, 0.8),
    "sod-80": (3.5, 1.6, 1.6),
    "sma": (4.6, 2.6, 2.1),
    "smb": (4.6, 3.6, 2.3),
    "smc": (7.0, 6.0, 2.6),
    # ── LED ──
    "led_0402": (1.0, 0.5, 0.6),
    "led_0603": (1.6, 0.8, 1.1),
    "led_0805": (2.0, 1.25, 1.3),
    "led_1206": (3.2, 1.6, 1.5),
    "led_plcc": (3.5, 2.8, 1.9),
    # ── 晶体管 / 稳压 ──
    "sot-23": (2.9, 1.6, 1.1),
    "sot-223": (6.5, 3.5, 1.7),
    "sot-89": (4.5, 2.5, 1.5),
    "sot-143": (2.9, 2.4, 1.0),
    "sot-353": (2.1, 1.3, 1.0),
    "sot-363": (2.1, 1.3, 1.0),
    "dpa": (6.5, 6.1, 2.4),
    "dpak": (6.5, 6.1, 2.4),
    "d2pa": (10.4, 9.4, 4.8),
    "to-252": (6.5, 6.1, 2.4),
    "to-263": (10.4, 9.4, 4.8),
    "to-220": (10.4, 4.6, 9.0),
    # ── 电感 / 磁珠 ──
    "ind_0402": (1.0, 0.5, 0.5),
    "ind_0603": (1.6, 0.8, 0.8),
    "ind_0805": (2.0, 1.25, 1.3),
    "ind_1206": (3.2, 1.6, 1.8),
    "ind_1210": (3.2, 2.5, 2.0),
    "ind_2520": (2.5, 2.0, 1.2),
    "ind_3216": (3.2, 1.6, 1.6),
    "ind_3225": (3.2, 2.5, 2.0),
    "ind_4516": (4.5, 1.6, 1.6),
    "ind_5020": (5.0, 2.0, 2.0),
    "ind_6028": (6.0, 2.8, 2.8),
    "ind_8040": (8.0, 4.0, 4.0),
    # ── 晶振 / 振荡器 ──
    "xtal_3215": (3.2, 1.5, 0.8),
    "xtal_3225": (3.2, 2.5, 0.8),
    "xtal_5032": (5.0, 3.2, 1.2),
    "xtal_7050": (7.0, 5.0, 1.3),
    # ── IC：SOIC / SOP / SSOP / TSSOP / MSOP ──
    "soic-8": (5.0, 4.0, 1.75),
    "soic-14": (8.75, 4.0, 1.75),
    "soic-16": (10.0, 4.0, 1.75),
    "soic-20": (12.8, 7.5, 2.65),
    "soic-24": (15.4, 7.5, 2.65),
    "soic-28": (18.1, 7.5, 2.65),
    "sop-8": (5.0, 4.0, 1.75),
    "sop-16": (10.0, 4.0, 1.75),
    "ssop-8": (5.0, 4.0, 1.75),
    "ssop-16": (6.2, 5.3, 1.75),
    "ssop-20": (7.2, 5.3, 1.75),
    "tssop-8": (3.0, 4.4, 1.2),
    "tssop-14": (5.0, 4.4, 1.2),
    "tssop-16": (5.0, 4.4, 1.2),
    "tssop-20": (6.5, 4.4, 1.2),
    "tssop-28": (9.7, 4.4, 1.2),
    "tssop-48": (12.5, 6.1, 1.2),
    "msop-8": (3.0, 3.0, 1.1),
    "msop-10": (3.0, 3.0, 1.1),
    # ── IC：QFN / QFP / LQFP / TQFP ──
    "qfn-16": (3.0, 3.0, 0.9),
    "qfn-20": (4.0, 4.0, 0.9),
    "qfn-24": (4.0, 4.0, 0.9),
    "qfn-28": (4.0, 4.0, 0.9),
    "qfn-32": (5.0, 5.0, 0.9),
    "qfn-48": (6.0, 6.0, 0.9),
    "qfn-64": (9.0, 9.0, 0.9),
    "qfp-44": (10.0, 10.0, 2.7),
    "qfp-64": (14.0, 14.0, 2.7),
    "lqfp-32": (7.0, 7.0, 1.4),
    "lqfp-48": (7.0, 7.0, 1.4),
    "lqfp-64": (10.0, 10.0, 1.4),
    "lqfp-100": (14.0, 14.0, 1.4),
    "lqfp-144": (20.0, 20.0, 1.4),
    "tqfp-32": (7.0, 7.0, 1.0),
    "tqfp-44": (10.0, 10.0, 1.0),
    "tqfp-64": (10.0, 10.0, 1.0),
    "tqfp-100": (14.0, 14.0, 1.0),
    # ── IC：BGA / LGA ──
    "bga-48": (7.0, 7.0, 1.2),
    "bga-64": (8.0, 8.0, 1.2),
    "bga-100": (10.0, 10.0, 1.3),
    "bga-144": (12.0, 12.0, 1.3),
    "bga-256": (17.0, 17.0, 1.4),
    "lga-8": (2.5, 2.0, 0.9),
    # ── 连接器 / 接口 ──
    "pinheader": (20.0, 5.0, 8.5),
    "type-c": (9.4, 7.3, 3.2),
    "usb": (13.1, 8.0, 3.0),
    "hdmi": (14.5, 12.0, 5.5),
    "rj45": (16.0, 13.5, 13.5),
    "audio_jack": (12.0, 12.0, 8.0),
    "sd_card": (15.2, 14.0, 1.8),
    "sim_card": (18.0, 16.0, 1.5),
    "fpc_conn": (10.0, 6.0, 2.0),
    "sw_smd": (3.9, 3.0, 2.0),
    "sw_tact": (6.0, 6.0, 4.0),
    "sw_dip": (7.5, 4.5, 4.0),
    # ── 模块 / 特殊 ──
    "esp32": (18.0, 25.5, 3.2),
    "esp32s3": (18.0, 25.5, 3.2),
    "nrf52": (15.8, 9.8, 1.0),
    "wifi_module": (16.0, 24.0, 3.0),
    "bt_module": (13.0, 16.0, 2.0),
    "gps_module": (17.0, 22.0, 3.0),
    "sensor_module": (7.0, 7.0, 2.5),
    # ── 保险丝 / 其它 ──
    "fuse_0603": (1.6, 0.8, 0.7),
    "fuse_1206": (3.2, 1.6, 1.0),
    "fuse_2410": (6.1, 2.5, 2.5),
    "pptc_0603": (1.6, 0.8, 0.8),
    "pptc_1206": (3.2, 1.6, 1.0),
    "zener_smd": (1.6, 0.8, 0.8),
    "schottky_smd": (2.0, 1.25, 0.9),
    "test_point": (2.0, 2.0, 2.0),
    "jumper": (3.0, 1.5, 1.5),
    "coil": (8.0, 8.0, 5.0),
}


def _fp_key(footprint_name: str) -> str:
    """封装名 → 查表 key（提取关键型号，兼容 _/- 分隔）"""
    name = footprint_name.lower().replace("_", "-")
    # 优先精确匹配子串（key 也统一为连字符形式）
    for key in FOOTPRINT_DIMS:
        key_h = key.replace("_", "-")
        if key_h in name:
            return key
    return None


def transform_pcb_to_gerber(x: float, y: float, pcb_bounds=None, gerber_bounds=None) -> tuple[float, float]:
    """
    KiCad .kicad_pcb 坐标 → Gerber 坐标变换。

    KiCad 导出 Gerber 时 Y 轴翻转（KiCad 的板坐标系 Y 向下，
    Gerber 标准 Y 向上）。用板中心对齐消除平移差异。

    pcb_bounds: (xmin, ymin, xmax, ymax) pcb 板范围
    gerber_bounds: (xmin, ymin, xmax, ymax) gerber 板范围
    若提供 bounds 用中心对齐；否则仅翻转 y。
    """
    # y 翻转
    y_t = -y
    if pcb_bounds and gerber_bounds:
        # 中心对齐
        pcb_cx = (pcb_bounds[0] + pcb_bounds[2]) / 2
        pcb_cy = (pcb_bounds[1] + pcb_bounds[3]) / 2
        ger_cx = (gerber_bounds[0] + gerber_bounds[2]) / 2
        ger_cy = (gerber_bounds[1] + gerber_bounds[3]) / 2
        return x + (ger_cx - pcb_cx), y_t + (ger_cy - (-pcb_cy))
    return x, y_t


def get_pcb_board_bounds(pcb_path: str) -> tuple | None:
    """从 .kicad_pcb 提取板框（Edge.Cuts gr_rect）范围 → (xmin, ymin, xmax, ymax)"""
    try:
        txt = Path(pcb_path).read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\(gr_rect[\s\S]*?\(start ([-\d.]+) ([-\d.]+)\)[\s\S]*?\(end ([-\d.]+) ([-\d.]+)\)", txt):
            x1, y1, x2, y2 = map(float, m.groups())
            return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    except Exception as e:
        log.warning(f"  提取板框失败: {e}")
    return None


def parse_kicad_pcb(pcb_path: str) -> list[dict]:
    """
    解析 KiCad .kicad_pcb → 元件列表 [{name, x, y, w, h, height, ref}]
    坐标保持原始 pcb 坐标（分析时用 transform_pcb_to_gerber 转换）。
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


def _is_through_hole(footprint_name: str) -> bool:
    """判断是否为插件封装（贯穿治具，不参与避位区干涉检查）"""
    name = footprint_name.lower()
    th_marks = ["pinheader", "connector", "mountinghole", "terminalblock",
                "screw", "jack", "socket", "dip-", "dip_", "rj45", "usb",
                "hdmi", "type-c", "audio"]
    return any(m in name for m in th_marks)


def analyze_interference(
    fixture_stl: str,
    components: list[dict],
    pcb_thickness: float = 1.6,
    pcb_bounds=None,
    gerber_bounds=None,
    skip_through_hole: bool = True,
    avoid_polys: list | None = None,
    cover_threshold: float = 0.85,
) -> list[dict]:
    """
    干涉分析：每个元件包围盒 vs 治具实体。

    双层判定：
    1. 2D 覆盖：元件盒在避位区内的覆盖比例 < cover_threshold → 干涉
       （治具实体压到元件——避位区必须覆盖元件整体）
    2. 3D 布尔：与治具实体交集 > 阈值 → 干涉（附重叠体积）

    skip_through_hole: True 时跳过插件封装（PinHeader/Connector 等贯穿治具，
    它们由上锡区开孔处理，不应报避位区干涉）

    avoid_polys: 避位区多边形列表（用于 2D 覆盖判定）
    pcb_bounds / gerber_bounds: 提供则先做坐标变换（KiCad→Gerber）
    返回: [{ref, name, x, y, w, h, height, overlap_mm3, cover_ratio}]
    """
    from shapely.geometry import box as sbox
    from shapely.ops import unary_union
    fixture = trimesh.load(fixture_stl)
    # 避位区合并（2D 覆盖判定用）
    avoid_union = unary_union(avoid_polys) if avoid_polys else None
    reports = []
    for c in components:
        # 跳过插件（贯穿治具的正常设计）
        if skip_through_hole and _is_through_hole(c["name"]):
            continue
        # 坐标变换（KiCad → Gerber）
        tx, ty = c["x"], c["y"]
        if pcb_bounds and gerber_bounds:
            tx, ty = transform_pcb_to_gerber(c["x"], c["y"], pcb_bounds, gerber_bounds)

        # 2D 覆盖判定
        cover_ratio = 1.0
        if avoid_union is not None:
            comp_box = sbox(tx - c["w"]/2, ty - c["h"]/2, tx + c["w"]/2, ty + c["h"]/2)
            inter_area = comp_box.intersection(avoid_union).area
            cover_ratio = inter_area / comp_box.area if comp_box.area > 0 else 0

        # 3D 布尔判定
        comp = trimesh.creation.box(extents=[c["w"], c["h"], c["height"]])
        comp.apply_translation([tx, ty, pcb_thickness + c["height"] / 2])
        vol = 0.0
        try:
            inter = fixture.intersection(comp, engine="manifold")
            vol = inter.volume if inter is not None else 0.0
        except Exception as e:
            log.warning(f"  干涉检测 {c['ref']} 失败: {e}")

        # 任一判定触发即报干涉
        if vol > 5.0 or cover_ratio < cover_threshold:
            reports.append({
                **c,
                "x": tx, "y": ty,  # 返回转换后坐标（前端 3D 用）
                "overlap_mm3": round(vol, 2),
                "cover_ratio": round(cover_ratio, 2),
            })
    return reports


if __name__ == "__main__":
    # 自测：ESP32 dev 板
    pcb = r"D:\kicad-test-board\basic-esp32s3-dev-board\dev-board.kicad_pcb"
    comps = parse_kicad_pcb(pcb)
    print(f"解析元件: {len(comps)} 个")
    for c in comps[:8]:
        print(f"  {c['ref']:6s} {c['name'][:35]:35s} {c['w']:.1f}x{c['h']:.1f} h={c['height']:.2f}")
    # 未知封装统计
    unknowns = [c for c in comps if c["fp_key"] == "unknown"]
    print(f"未知封装: {len(unknowns)} 个")
