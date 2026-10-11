"""PCB 底面波峰焊 SMD 红胶点胶模板与防污染门禁 (SMD Red Glue Stencil & Pad Contamination Gate).

工业背景与工艺标准：
- IPC-SM-782 & IPC-A-610G §7.1.3 表面贴装胶水工艺规范：
  在混装波峰焊工艺中，PCB 底面的 SMD 片式元件（0603/0805/1206 电阻电容、SOT-23 三极管、SOP 芯片）
  直接浸入 260°C 熔融液态锡波。为防止贴片元件在高温液态锡的浮力与动压下脱落掉入锡锅，
  在 SMT 贴装前必须在两端焊盘正中的 PCB 基板裸板表面涂覆**贴片红胶 (SMD Adhesive / Red Glue)**，
  经烘烤硬化后再送入波峰焊。
- 胶点规格与点胶机参数（Camalot / Asymtek / 武藏高精度点胶机）：
  * 0603: 单胶点 Φ0.8mm，胶量 ~0.08 nl
  * 0805: 单胶点 Φ1.0mm，胶量 ~0.12 nl
  * 1206 / SOT-23: 单胶点 Φ1.2mm，胶量 ~0.20 nl
  * SOIC / SOP-8/16: 双胶点 Φ1.2mm，轴向间距 3.0~4.0mm
- 防红胶污染焊盘门禁 (Adhesive-to-Pad Clearance Gate)：
  胶点外缘距金属焊盘边缘必须保持安全距离 D_clearance ≥ 0.30mm！若胶水点偏或溢胶沾染焊盘
  (Adhesive Contamination on Pad)，波峰焊接时该引脚将彻底绝缘无法上锡，造成严重虚焊与开路缺陷 (IPC-A-610G §7.1.3)。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RedGlueDot:
    dot_id: str
    ref: str
    x_mm: float
    y_mm: float
    diameter_mm: float
    volume_nl: float
    pad_clearance_mm: float
    is_safe_from_pads: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RedGlueStencilResult:
    total_dots: int
    dots: list[RedGlueDot] = field(default_factory=list)
    contaminated_dots_count: int = 0
    csv_dispense_table: str = ""
    ipc_standard: str = "IPC-SM-782 & IPC-A-610G Section 7.1.3 SMD Adhesive Dispensing"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["dots"] = [dot.to_dict() for dot in self.dots]
        return d


DOT_PRESETS = {
    "0603": (0.8, 0.08, 0.60),  # (dia_mm, vol_nl, nominal_half_pad_span_mm)
    "0805": (1.0, 0.12, 0.85),
    "1206": (1.2, 0.20, 1.20),
    "SOT-23": (1.0, 0.12, 0.90),
    "SOIC-8": (1.2, 0.20, 1.80),
}


def generate_red_glue_dots(
    bottom_smd_components: list[dict],
    min_pad_clearance_mm: float = 0.30,
) -> RedGlueStencilResult:
    """生成底面贴片元件的红胶点胶坐标、胶量，并核算距引脚焊盘的安全防污染间隙。

    bottom_smd_components: [{ref, package, x_mm, y_mm, rotation_deg, pad_span_mm (两焊盘内侧净距)}]
    """
    dots: list[RedGlueDot] = []
    contaminated = 0
    csv_rows = ["Ref,Dot_ID,X_mm,Y_mm,Diameter_mm,Volume_nl,Package"]

    for idx, c in enumerate(bottom_smd_components):
        ref = str(c.get("ref", f"C{idx+1}"))
        pkg = str(c.get("package", "0805")).upper()
        cx = float(c.get("x_mm", 0.0))
        cy = float(c.get("y_mm", 0.0))
        rot = float(c.get("rotation_deg", 0.0))

        # 匹配预设胶点尺寸
        preset = None
        for k, v in DOT_PRESETS.items():
            if k in pkg:
                preset = v
                break
        if not preset:
            preset = (0.9, 0.10, 0.75)  # 默认 0.9mm 胶点

        dia, vol, nom_span = preset
        # 实际焊盘内边距：优先取传入值，否则取名义值
        pad_gap = float(c.get("pad_inner_gap_mm", nom_span * 2.0))
        # 胶点外边缘到焊盘内边的净距 = (两焊盘净距 - 胶点直径) / 2
        clearance = round((pad_gap - dia) / 2.0, 3)
        is_safe = clearance >= min_pad_clearance_mm
        if not is_safe:
            contaminated += 1

        is_soic = "SOIC" in pkg or "SOP" in pkg
        if is_soic:
            # 双胶点布局
            rad = math.radians(rot)
            off_x = round(1.5 * math.cos(rad), 3)
            off_y = round(1.5 * math.sin(rad), 3)
            d1 = RedGlueDot(
                dot_id=f"GLUE_{ref}_1",
                ref=ref,
                x_mm=round(cx - off_x, 3),
                y_mm=round(cy - off_y, 3),
                diameter_mm=dia,
                volume_nl=vol,
                pad_clearance_mm=clearance,
                is_safe_from_pads=is_safe,
            )
            d2 = RedGlueDot(
                dot_id=f"GLUE_{ref}_2",
                ref=ref,
                x_mm=round(cx + off_x, 3),
                y_mm=round(cy + off_y, 3),
                diameter_mm=dia,
                volume_nl=vol,
                pad_clearance_mm=clearance,
                is_safe_from_pads=is_safe,
            )
            dots.extend([d1, d2])
            csv_rows.append(f"{ref},{d1.dot_id},{d1.x_mm},{d1.y_mm},{dia},{vol},{pkg}")
            csv_rows.append(f"{ref},{d2.dot_id},{d2.x_mm},{d2.y_mm},{dia},{vol},{pkg}")
        else:
            dot = RedGlueDot(
                dot_id=f"GLUE_{ref}",
                ref=ref,
                x_mm=round(cx, 3),
                y_mm=round(cy, 3),
                diameter_mm=dia,
                volume_nl=vol,
                pad_clearance_mm=clearance,
                is_safe_from_pads=is_safe,
            )
            dots.append(dot)
            csv_rows.append(f"{ref},{dot.dot_id},{dot.x_mm},{dot.y_mm},{dia},{vol},{pkg}")

    return RedGlueStencilResult(
        total_dots=len(dots),
        dots=dots,
        contaminated_dots_count=contaminated,
        csv_dispense_table="\n".join(csv_rows),
    )


def export_red_glue_to_dxf(msp, result: RedGlueStencilResult) -> None:
    """输出红胶点胶圆形坐标轮廓与点胶编号到 DXF 专用图层。"""
    layer_name = "红胶点胶"

    for dot in result.dots:
        msp.add_circle((dot.x_mm, dot.y_mm), radius=dot.diameter_mm / 2.0, dxfattribs={"layer": layer_name})
        msp.add_text(
            dot.dot_id,
            dxfattribs={"layer": layer_name, "height": 1.2, "insert": (dot.x_mm + 0.8, dot.y_mm + 0.8)},
        )
