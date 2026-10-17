"""波峰焊助焊剂防积液排液槽与高温蒸汽泄压排气孔引擎 (Flux Puddling Drainage & Vapor Pressure Relief).

工业背景与工艺标准：
- AGICORP §4.3《Wave Solder Pallet Design Guidelines》与 SMTA 缺陷预防手册：
  在波峰焊喷雾涂覆助焊剂（Nordson / Sono-Tek 超声波喷雾）工序中，雾化助焊剂附着在治具底面。
  治具底面的深沉孔与避位腔（深度 ≥ 3.0mm）：
  1. 若四周为垂直立壁且无排液泄槽，残留液体助焊剂将在腔体死角聚集形成积液（Flux Puddling）；
     治具进入 100°C~150°C 预热段与 260°C 锡波时，积聚的助焊剂溶剂瞬间剧烈沸腾爆炸，
     将熔融焊锡炸成微米级锡珠飞溅附着在板面上造成大面积电气短路（Solder Ball / Flux Spatter，
     违背 IPC-A-610G §5.2.7.1 洁净度与焊锡球缺陷判定标准）。
  2. 封闭或半封闭腔室在 260°C 高温波峰下，腔内密封空气急剧热膨胀（查理定律膨胀率达 ~79%），
     若缺少通大气的微型排气泄压孔（Breathing Weep Hole，标准 Φ2.0~2.5mm），高压气体将从
     开孔边缘喷薄而出，把液态锡波冲散吹出空洞造成大面积虚焊。
- 工业规范：
  - 每个深度 ≥ 3.0mm 的避位槽必须开凿 45° 倒坡泄流槽（Weep Groove，宽 2.0mm）引流至外围；
  - 腔室顶端必须保留贯通上盖或通大气的安全呼吸排气孔（Φ2.0mm~2.5mm）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon, box


@dataclass
class WeepChannel:
    pocket_id: str
    start_x_mm: float
    start_y_mm: float
    end_x_mm: float
    end_y_mm: float
    channel_width_mm: float = 2.0
    draft_angle_deg: float = 45.0
    channel_poly: Polygon | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if "channel_poly" in d:
            d["channel_poly"] = None
        return d


@dataclass
class VaporReliefPort:
    pocket_id: str
    x_mm: float
    y_mm: float
    diameter_mm: float = 2.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FluxDrainageResult:
    pockets_analyzed: int
    pockets_requiring_drainage: int
    weep_channels: list[WeepChannel] = field(default_factory=list)
    vapor_ports: list[VaporReliefPort] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["weep_channels"] = [w.to_dict() for w in self.weep_channels]
        d["vapor_ports"] = [v.to_dict() for v in self.vapor_ports]
        return d


def generate_flux_drainage_and_vapor_ports(
    avoid_polys: list[Polygon],
    outer_poly: Polygon | None = None,
    min_pocket_depth_mm: float = 3.0,
    weep_channel_width_mm: float = 2.0,
) -> FluxDrainageResult:
    """为避位腔体生成 45° 倒坡排液导流槽与 Φ2.5mm 防气爆泄压排气孔。"""
    valid_pockets = [p for p in avoid_polys if p and not p.is_empty]
    weep_channels: list[WeepChannel] = []
    vapor_ports: list[VaporReliefPort] = []
    req_count = 0

    for idx, poly in enumerate(valid_pockets):
        _bx0, by0, bx1, by1 = poly.bounds
        ph = by1 - by0

        # 面积超过 50mm² 的深槽均被认定为易发生积液的高危腔体
        if poly.area >= 50.0:
            req_count += 1
            # 1. 在腔体几何中心规划防气爆泄压通气孔 (Φ2.5mm)
            c = poly.centroid
            vapor_ports.append(
                VaporReliefPort(
                    pocket_id=f"AVOID_{idx+1}",
                    x_mm=round(c.x, 2),
                    y_mm=round(c.y, 2),
                    diameter_mm=2.5,
                )
            )

            # 2. 从腔体低侧向外开凿 45° 倒坡排液槽 (长 8mm, 宽 2mm)
            # 假定出板向右下重力泄流
            sx = bx1
            sy = by0 + ph / 2.0
            ex = bx1 + 8.0
            ey = sy

            ch_box = box(sx, sy - weep_channel_width_mm / 2.0, ex, sy + weep_channel_width_mm / 2.0)
            weep_channels.append(
                WeepChannel(
                    pocket_id=f"AVOID_{idx+1}",
                    start_x_mm=round(sx, 2),
                    start_y_mm=round(sy, 2),
                    end_x_mm=round(ex, 2),
                    end_y_mm=round(ey, 2),
                    channel_width_mm=weep_channel_width_mm,
                    draft_angle_deg=45.0,
                    channel_poly=ch_box,
                )
            )

    stats = {
        "pockets_analyzed": len(valid_pockets),
        "high_risk_pockets": req_count,
        "weep_channels_count": len(weep_channels),
        "vapor_ports_count": len(vapor_ports),
        "weep_width_mm": weep_channel_width_mm,
    }

    return FluxDrainageResult(
        pockets_analyzed=len(valid_pockets),
        pockets_requiring_drainage=req_count,
        weep_channels=weep_channels,
        vapor_ports=vapor_ports,
        stats=stats,
    )


def export_flux_drainage_to_dxf(msp, result: FluxDrainageResult) -> None:
    """输出助焊剂排液导流槽外框、中心线与排气孔到 DXF 专用图层。"""
    layer_name = "助焊剂排液"

    # 1. 导出防积液排液槽
    for ch in result.weep_channels:
        if ch.channel_poly and not ch.channel_poly.is_empty:
            pts = list(ch.channel_poly.exterior.coords)
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})
        msp.add_line((ch.start_x_mm, ch.start_y_mm), (ch.end_x_mm, ch.end_y_mm), dxfattribs={"layer": layer_name})

    # 2. 导出高温防气爆泄压排气孔 (Φ2.5mm)
    for vp in result.vapor_ports:
        msp.add_circle((vp.x_mm, vp.y_mm), radius=vp.diameter_mm / 2.0, dxfattribs={"layer": layer_name})

    if result.weep_channels:
        w0 = result.weep_channels[0]
        msp.add_text(
            f"WEEP DRAIN (45 DEG, N={result.pockets_requiring_drainage})",
            dxfattribs={"layer": layer_name, "height": 2.0, "insert": (w0.end_x_mm + 1.0, w0.end_y_mm)},
        )
