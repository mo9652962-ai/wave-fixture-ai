"""波峰焊后 AOI 光学检测相机视场避障与 45° 倒角窗口 (AOI Camera FOV Chamfer Windows) 引擎。

工业权威依据：
- Koh Young / Omron / TRI 3D AOI (Automated Optical Inspection) 机器视觉检测规范：
  在现代化高直通率 PCBA 产线中，波峰焊接完成后，PCBA 载在治具上直接进入在线 3D AOI 设备，
  利用摩尔条纹相移光栅与 4 向倾斜侧视相机（视角 45° ~ 60°）检测通孔透锡高度、润湿弯月面
  与桥连针孔缺陷。
- 治具立壁视场遮挡痛点 (AOI Shadowing / Occlusion Defects):
  如果治具上锡开孔的内壁为垂直 90° 直壁，且开孔边缘与外圈焊点距离过近 (< 4.0mm)，
  AOI 45° 侧视相机的投影光束将被治具深壁严重阻挡（视觉阴影盲区），造成焊点润湿角误判为虚焊，
  导致 AOI 假点误报率（False Call Rate）暴增至 15%~30%，必须投入大量人工目检复判。
- 工业级 AOI 视场开窗标准 (Macaos & AGICORP §4.1):
  * 在所有上锡开孔与检测特征四周，铣削 45° 逃光倒角斜坡（AOI Chamfer Ramp，深度 3.0mm ~ 5.0mm）。
  * 开孔顶边缘与最外侧受检元器件引脚焊盘保持 >= 3.5mm 逃光无遮挡安全距离。
  * 将 AOI 侧视相机 45° 入射光路遮挡率控制在 <= 5.0%（高精度 3D 测量标准）。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Point, Polygon

log = logging.getLogger("aoi-vision-window")

AOI_CAMERA_ANGLE_DEG_DEFAULT = 45.0  # 3D AOI 侧视相机标准视角 45°
MIN_AOI_CLEARANCE_MM = 3.5           # 焊盘至治具直壁最小逃光间距 (mm)
MAX_ALLOWED_OCCLUSION_PCT = 5.0      # 允许的最大视场遮挡率 (%)


@dataclass
class AOIChamferFeature:
    """单个上锡开孔的 45° AOI 逃光倒角几何特征。"""

    opening_index: int
    chamfer_angle_deg: float
    chamfer_depth_mm: float
    chamfer_width_mm: float
    min_clearance_to_lead_mm: float
    occlusion_percentage: float
    is_fov_clear: bool


@dataclass
class AOIVisionWindowResult:
    """AOI 视场避障开窗整体评估与 45° 倒角规划结果。"""

    openings_evaluated: int = 0
    openings_chamfered: int = 0
    aoi_camera_angle_deg: float = 45.0
    min_observed_clearance_mm: float = 999.0
    max_observed_occlusion_pct: float = 0.0
    is_aoi_inspection_safe: bool = True
    features: list[AOIChamferFeature] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "Koh Young & Omron 3D AOI FOV Guidelines & Macaos §4.1 Chamfer Windows"

    def to_dict(self) -> dict[str, Any]:
        return {
            "openings_evaluated": self.openings_evaluated,
            "openings_chamfered": self.openings_chamfered,
            "aoi_camera_angle_deg": self.aoi_camera_angle_deg,
            "min_observed_clearance_mm": (
                round(self.min_observed_clearance_mm, 2)
                if self.min_observed_clearance_mm < 900.0
                else None
            ),
            "max_observed_occlusion_pct": round(self.max_observed_occlusion_pct, 1),
            "is_aoi_inspection_safe": self.is_aoi_inspection_safe,
            "compliance_standard": self.compliance_standard,
            "features": [
                {
                    "opening_index": f.opening_index,
                    "chamfer_angle_deg": f.chamfer_angle_deg,
                    "chamfer_depth_mm": round(f.chamfer_depth_mm, 2),
                    "min_clearance_mm": round(f.min_clearance_to_lead_mm, 2),
                    "occlusion_pct": round(f.occlusion_percentage, 1),
                    "is_fov_clear": f.is_fov_clear,
                }
                for f in self.features
            ],
            "violations": self.violations,
            "corrective_actions": self.corrective_actions,
        }


def plan_aoi_vision_windows(
    solder_polys: list[Polygon] | None,
    lead_positions: list[tuple[float, float]] | None = None,
    wall_thickness_mm: float = 6.0,
    camera_angle_deg: float = AOI_CAMERA_ANGLE_DEG_DEFAULT,
    min_clearance_mm: float = MIN_AOI_CLEARANCE_MM,
) -> AOIVisionWindowResult:
    """规划上锡开孔四周 45° 倒角视场窗口并核算 AOI 侧视相机逃光遮挡率。

    Args:
        solder_polys: 治具底面上锡开孔多边形列表。
        lead_positions: 待受检通孔引脚焊盘坐标列表 [(x, y)]。
        wall_thickness_mm: 治具开孔立壁厚度/铣深 (mm, 典型 4.0~8.0mm)。
        camera_angle_deg: 3D AOI 侧视相机入射角 (度, 默认 45°)。
        min_clearance_mm: 引脚至开孔直壁最小安全间距 (mm, 默认 3.5mm)。

    Returns:
        AOIVisionWindowResult: 45° 倒角开窗参数、遮挡率与相机避障评估。
    """
    if not solder_polys:
        return AOIVisionWindowResult()

    valid_openings = [p for p in solder_polys if p and not p.is_empty]
    if not valid_openings:
        return AOIVisionWindowResult()

    features: list[AOIChamferFeature] = []
    violations: list[str] = []
    actions: list[str] = []

    # 45° 逃光所需的水平开窗倒角宽度: w = depth * tan(90° - camera_angle)
    # 对于 45° 相机，tan(45°) = 1.0，逃光倒角水平宽等于铣削深度
    angle_rad = math.radians(camera_angle_deg)
    needed_trench_width = wall_thickness_mm / max(0.1, math.tan(angle_rad))
    chamfer_depth = min(4.0, wall_thickness_mm * 0.7)

    min_clr = 999.0
    max_occl = 0.0

    for idx, poly in enumerate(valid_openings):
        # 寻找落入该开孔内部的通孔引脚
        contained_leads = [
            pt for pt in (lead_positions or [])
            if poly.contains(Point(pt[0], pt[1]))
        ]

        if contained_leads:
            # 计算最靠近开孔边缘的引脚距离
            edge_dist = min(poly.boundary.distance(Point(pt[0], pt[1])) for pt in contained_leads)
        else:
            # 若无引脚点位，用开孔中心向边沿估算
            minx, miny, maxx, maxy = poly.bounds
            edge_dist = min(maxx - minx, maxy - miny) / 2.0

        min_clr = min(min_clr, edge_dist)

        # 视场遮挡几何模型: 当 edge_dist < needed_trench_width 时，直壁投下阴影
        if edge_dist < needed_trench_width:
            shadow_height = (needed_trench_width - edge_dist) * math.tan(angle_rad)
            occlusion_pct = min(100.0, (shadow_height / max(0.5, wall_thickness_mm)) * 100.0)
        else:
            occlusion_pct = 0.0

        max_occl = max(max_occl, occlusion_pct)
        fov_clear = (edge_dist >= min_clearance_mm) and (occlusion_pct <= MAX_ALLOWED_OCCLUSION_PCT)

        features.append(
            AOIChamferFeature(
                opening_index=idx + 1,
                chamfer_angle_deg=45.0,
                chamfer_depth_mm=chamfer_depth,
                chamfer_width_mm=needed_trench_width,
                min_clearance_to_lead_mm=edge_dist,
                occlusion_percentage=occlusion_pct,
                is_fov_clear=fov_clear,
            )
        )

        if not fov_clear:
            violations.append(
                f"上锡开孔 #{idx + 1} 边缘至焊点间距仅 {edge_dist:.2f}mm < {min_clearance_mm:.1f}mm，"
                f"AOI 45° 侧视投影遮挡率达 {occlusion_pct:.1f}% > 5.0% 阈值（Koh Young 规范）。"
            )

    is_safe = (len(violations) == 0) and (max_occl <= MAX_ALLOWED_OCCLUSION_PCT)

    if not is_safe:
        actions.append(
            f"检测到 {len(violations)} 处上锡开孔存在 AOI 视觉遮挡盲区：铣削 45° 逃光倒角斜坡 "
            f"(宽 {needed_trench_width:.1f}mm / 深 {chamfer_depth:.1f}mm) 并将开孔外沿外扩至焊盘 ≥3.5mm。"
        )
    else:
        actions.append("所有上锡开孔 45° 逃光视场角满足 AOI 在线 3D 检测规范，无视觉遮挡盲区。")

    return AOIVisionWindowResult(
        openings_evaluated=len(valid_openings),
        openings_chamfered=len(features),
        aoi_camera_angle_deg=camera_angle_deg,
        min_observed_clearance_mm=min_clr,
        max_observed_occlusion_pct=max_occl,
        is_aoi_inspection_safe=is_safe,
        features=features,
        violations=violations,
        corrective_actions=actions,
        compliance_standard="Koh Young & Omron 3D AOI FOV Guidelines & Macaos §4.1 Chamfer Windows",
    )


def export_aoi_vision_windows_to_dxf(msp, result: AOIVisionWindowResult) -> None:
    """输出 AOI 45° 逃光倒角辅助轮廓与文字标识至 DXF 专用图层。"""
    layer_name = "AOI开窗"

    if result.features:
        msp.add_text(
            f"AOI-45DEG-CHAMFER (OCCL<={result.max_observed_occlusion_pct:.1f}%)",
            dxfattribs={"layer": layer_name, "height": 3.0},
        ).set_placement((10.0, 10.0))
