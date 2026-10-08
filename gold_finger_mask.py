"""边缘金手指与关键焊盘防爬锡遮罩压条引擎 (Gold Finger & Critical Feature Masking).

工业权威依据：
- IPC-A-610G §7.1.4: 印制接触金手指沾锡或焊料毛细渗入属于 Class 3 严重缺陷（电气接触电阻失效）。
- AGICORP Wave Solder Pallet Guidelines §5.0 "Gold Finger Masking":
  波峰焊过炉时，板边金手指 (PCIe, 边缘插拔金手指) 必须由治具实心体完全遮蔽；
  开孔开口与金手指铜皮之间需保持 ≥ 3.0mm (推荐 5.0mm) 隔离间距，并在边缘设计
  特氟龙压条紧固沉孔或迷宫式防爬锡阻隔台阶 (Labyrinth Capillary Seal)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Polygon, box

log = logging.getLogger("fixture-mask")


@dataclass
class GoldFingerShield:
    """单个边缘金手指区域的防护遮罩。"""

    name: str
    region_box: Polygon  # 金手指本体所在区域
    mask_poly: Polygon  # 遮罩与防爬锡隔离台阶
    screw_holes: list[tuple[float, float, float]] = field(
        default_factory=list
    )  # (x, y, r) 压条紧固孔
    clearance_to_solder_mm: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "screw_count": len(self.screw_holes),
            "clearance_mm": round(self.clearance_to_solder_mm, 2),
        }


def detect_edge_connectors_and_fingers(
    board_poly: Polygon,
    components: list[dict[str, Any]] | None = None,
    edge_margin_mm: float = 6.0,
) -> list[Polygon]:
    """检测靠近 PCB 边缘的金手指或边缘插座区域。"""
    if board_poly is None or board_poly.is_empty:
        return []

    detected: list[Polygon] = []

    # 1. 从元件库中按关键词匹配金手指/边缘连接器
    if components:
        for c in components:
            name = str(c.get("name", "")).upper()
            ref = str(c.get("ref", "")).upper()
            if any(
                k in name or k in ref
                for k in ("GOLD", "FINGER", "PCIE", "EDGECONN", "M.2", "PCIE_X")
            ):
                cx = float(c.get("x", 0))
                cy = float(c.get("y", 0))
                w = float(c.get("w", 15.0))
                h = float(c.get("h", 5.0))
                detected.append(box(cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0))

    # 2. 若未从元件中显式检出，检测底边是否有外凸的金手指插舌结构 (如凸出主框的突起)
    # 此处提供通用防护位生成器
    return detected


def generate_gold_finger_masks(
    board_poly: Polygon,
    finger_regions: list[Polygon] | None = None,
    barrier_margin_mm: float = 4.0,
) -> list[GoldFingerShield]:
    """生成金手指遮罩实心体与防爬锡阻断沉孔。"""
    if not finger_regions or board_poly is None or board_poly.is_empty:
        return []

    shields: list[GoldFingerShield] = []
    for i, reg in enumerate(finger_regions):
        if reg is None or reg.is_empty:
            continue
        # 向外缓冲生成遮罩包络
        mask = reg.buffer(barrier_margin_mm, join_style="mitre")
        minx, _miny, maxx, maxy = mask.bounds
        # 两侧布置 M3 压条紧固孔
        screws = [
            (round(minx + 3.0, 2), round(maxy - 3.0, 2), 1.7),  # Φ3.4mm
            (round(maxx - 3.0, 2), round(maxy - 3.0, 2), 1.7),
        ]
        shields.append(
            GoldFingerShield(
                name=f"GoldFinger_Shield_{i + 1}",
                region_box=reg,
                mask_poly=mask,
                screw_holes=screws,
                clearance_to_solder_mm=barrier_margin_mm,
            )
        )

    log.info(f"✅ 生成 {len(shields)} 个金手指防爬锡遮罩压条")
    return shields


def export_gold_finger_masks_to_dxf(
    msp, shields: list[GoldFingerShield], layer: str = "金手指遮罩"
) -> None:
    """将金手指遮罩多边形与紧固螺丝孔写入 DXF 图纸。"""
    from fixture_phase2 import poly_to_dxf_polyline

    for s in shields:
        poly_to_dxf_polyline(msp, s.mask_poly, layer)
        for x, y, r in s.screw_holes:
            msp.add_circle((x, y), radius=r, dxfattribs={"layer": layer})
