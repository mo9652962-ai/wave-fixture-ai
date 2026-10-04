"""选择性波峰焊喷嘴避障分析与运动轨迹引擎 (Selective Wave Soldering Engine)。

工业定位（对标 ERSA Versaflow 3/45、SEHO SelectLine、Kurtz Ersa 行业真机规范）：
在现代 PCBA 混装产线中，选择性波峰焊使用微型浸润/微孔喷嘴（常见外径 Φ4mm、Φ6mm、Φ8mm、Φ10mm）
在托盘开口下方沿 XYZ 轴点对点移动上锡。
行业核心痛点：
  1. 喷嘴外沿与治具内壁碰撞：喷嘴外沿在移动进出开孔时，必须与治具侧壁保持 ≥3.0mm（高立件处 ≥5.0mm）
     的避空安全距离（ERSA 官方应用指南 & Macaos Selective Guidelines §3）。
  2. 助焊剂涂覆与浸润行程规划：计算各焊点的进出入点与停留轨迹。

本模块提供：
  - 工业真机喷嘴档案库（ERSA / SEHO / 通用喷嘴规格）
  - 喷嘴开孔通过性与治具侧壁避障几何校验
  - 选择焊机器人点到点运动路径规划 (Selective Soldering Path Generation)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from shapely.geometry import Polygon

log = logging.getLogger("fixture-selective")


@dataclass
class SelectiveNozzleProfile:
    """选择焊喷嘴机台画像。"""

    key: str
    vendor: str
    model: str
    inner_dia_mm: float           # 喷嘴内径 (锡波接触径)
    outer_dia_mm: float           # 喷嘴物理外径
    clearance_envelope_mm: float  # 动态避障包络外径 (含防刮伤安全裕量)
    recommended_clearance_mm: float  # 推荐离壁安全间隙 (mm)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


NOZZLE_PROFILES: dict[str, SelectiveNozzleProfile] = {
    "ersa_4mm": SelectiveNozzleProfile(
        key="ersa_4mm",
        vendor="Kurtz Ersa",
        model="Versaflow 4mm Micro-Nozzle",
        inner_dia_mm=4.0,
        outer_dia_mm=6.5,
        clearance_envelope_mm=9.5,
        recommended_clearance_mm=3.0,
        source="Ersa Versaflow 3/45 Application Note (Micro Nozzle Set)",
    ),
    "ersa_6mm": SelectiveNozzleProfile(
        key="ersa_6mm",
        vendor="Kurtz Ersa",
        model="Versaflow 6mm Standard Nozzle",
        inner_dia_mm=6.0,
        outer_dia_mm=9.0,
        clearance_envelope_mm=12.0,
        recommended_clearance_mm=3.0,
        source="Ersa Versaflow Standard Selective Soldering Nozzles",
    ),
    "seho_8mm": SelectiveNozzleProfile(
        key="seho_8mm",
        vendor="SEHO Systems",
        model="SelectLine 8mm Power Nozzle",
        inner_dia_mm=8.0,
        outer_dia_mm=12.0,
        clearance_envelope_mm=16.0,
        recommended_clearance_mm=4.0,
        source="SEHO SelectLine Multi-nozzle Tooling Guide",
    ),
    "generic_5mm": SelectiveNozzleProfile(
        key="generic_5mm",
        vendor="Generic",
        model="Universal 5mm Selective Nozzle",
        inner_dia_mm=5.0,
        outer_dia_mm=8.0,
        clearance_envelope_mm=11.0,
        recommended_clearance_mm=3.0,
        source="Macaos Selective Soldering Guidelines §3",
    ),
}

DEFAULT_NOZZLE = "ersa_6mm"


def get_nozzle(key: str | None = None) -> SelectiveNozzleProfile:
    """按 key 取喷嘴画像，缺省回退 ersa_6mm。"""
    if not key:
        return NOZZLE_PROFILES[DEFAULT_NOZZLE]
    return NOZZLE_PROFILES.get(key.lower().strip(), NOZZLE_PROFILES[DEFAULT_NOZZLE])


def verify_selective_solder_clearance(
    solder_polys: list[Polygon],
    avoid_polys: list[Polygon],
    nozzle_key: str = DEFAULT_NOZZLE,
    min_clearance_mm: float = 3.0,
) -> list[dict[str, Any]]:
    """校验选择焊喷嘴进出各上锡开孔时的几何避障间隙。

    规则出处：ERSA Versaflow 指南 & Macaos 规范——喷嘴外沿必须与侧壁保持 ≥ 3.0mm 间距。
    返回冲突列表 (如间隙不足则输出告警对象)。
    """
    nozzle = get_nozzle(nozzle_key)
    violations: list[dict[str, Any]] = []

    for si, s_poly in enumerate(solder_polys):
        if s_poly is None or s_poly.is_empty:
            continue
        minx, miny, maxx, maxy = s_poly.bounds
        w = maxx - minx
        h = maxy - miny
        min_dim = min(w, h)

        # 检查开孔尺寸是否容纳喷嘴外径 + 双侧安全间隙
        required_opening = nozzle.outer_dia_mm + 2 * min_clearance_mm
        if min_dim < required_opening:
            violations.append({
                "code": "SELECTIVE_NOZZLE_COLLISION",
                "title": "选择焊喷嘴避障间隙不足",
                "detail": (
                    f"上锡开孔 #{si + 1} 最小跨度 {min_dim:.2f}mm < 所需安全间隙 {required_opening:.2f}mm "
                    f"({nozzle.vendor} {nozzle.model} 外径 {nozzle.outer_dia_mm}mm + 双侧避让 {min_clearance_mm}mm)，"
                    "喷嘴移动时存在碰撞治具侧壁风险。"
                ),
                "severity": "warning",
                "current": round(min_dim, 2),
                "required": round(required_opening, 2),
                "unit": "mm",
                "object_id": f"solder-{si + 1}",
                "source": nozzle.source,
            })

    return violations


def compute_selective_nozzle_toolpath(
    solder_polys: list[Polygon],
    nozzle_key: str = DEFAULT_NOZZLE,
    dip_z_mm: float = -2.5,
    travel_z_mm: float = 10.0,
) -> list[dict[str, Any]]:
    """计算选择焊机器人的点位焊接路径 (XYZ 轨迹点)。"""
    nozzle = get_nozzle(nozzle_key)
    path: list[dict[str, Any]] = []

    # 按 X 坐标排序减少空程
    sorted_polys = sorted(
        [p for p in solder_polys if p is not None and not p.is_empty],
        key=lambda p: (p.centroid.x, p.centroid.y),
    )

    for i, p in enumerate(sorted_polys):
        c = p.centroid
        path.append({
            "index": i + 1,
            "x": round(c.x, 3),
            "y": round(c.y, 3),
            "approach_z": travel_z_mm,
            "solder_z": dip_z_mm,
            "dwell_time_s": 2.5,  # 典型接触停留时间
            "nozzle": nozzle.model,
        })

    return path
