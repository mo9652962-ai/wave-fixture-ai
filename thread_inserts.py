"""治具螺纹孔黄铜埋植嵌件规划 (Brass Threaded Insert Planner).

工业背景与紧固基准：
- 合成石 (Durostone/Ricocel) 与玻璃纤维板 (FR-4) 为玻璃纤维增强树脂基体，
  直接攻丝 (M3/M4 自攻) 的螺纹在反复装拆下寿命仅 ~50 次即滑丝——
  而治具盖板/铰链/压扣螺钉每批次首检与换型都要反复装拆；
- 工业惯例：在螺纹孔内压入/热熔 **黄铜埋植嵌件** (Brass Press-fit / Heat-stake Insert，
  如 M3×5.0×4.0 六角/滚花嵌件)，寿命 >500 次装拆，且耐温 260°C 波峰环境无松动；
- 嵌件规划：对每处受力螺纹孔 (压扣 M3 / 上盖铰链 M4 / 定位销压板 M3) 生成
  嵌件规格 (螺纹 × 外径 × 沉孔深度)，同步输出 DXF 嵌件轮廓层与报价五金行。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from shapely.geometry import Polygon, box


@dataclass
class InsertSpec:
    thread: str  # "M3" / "M4"
    outer_dia_mm: float  # 嵌件外径 (压入沉孔直径)
    install_depth_mm: float  # 压入深度
    hole_dia_mm: float  # 预钻孔径 (基材孔)
    life_cycles: int = 500  # 额定装拆寿命


@dataclass
class ThreadInsertPlan:
    inserts: list[InsertSpec] = field(default_factory=list)
    positions: list[tuple[float, float]] = field(default_factory=list)
    insert_polys: list[Polygon] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inserts": [asdict(i) for i in self.inserts],
            "positions": self.positions,
            "stats": self.stats,
        }


INSERT_LIBRARY: dict[str, InsertSpec] = {
    "M3": InsertSpec(thread="M3", outer_dia_mm=4.6, install_depth_mm=4.9, hole_dia_mm=4.2),
    "M4": InsertSpec(thread="M4", outer_dia_mm=6.0, install_depth_mm=6.3, hole_dia_mm=5.5),
}


def plan_thread_inserts(
    screw_holes: list[tuple[float, float]],
    hinge_holes: list[tuple[float, float]] | None = None,
    insert_thread: str = "M3",
) -> ThreadInsertPlan:
    """为压扣/铰链螺纹孔规划黄铜埋植嵌件：输出嵌件规格、坐标与 DXF 轮廓。

    screw_holes: 压扣孔位 (Φ3.4 沉孔中心) 列表 —— M3 嵌件
    hinge_holes: 上盖铰链 M4 沉孔中心列表 —— M4 嵌件 (可选)
    """
    plan = ThreadInsertPlan()

    m3 = INSERT_LIBRARY["M3"]
    m4 = INSERT_LIBRARY["M4"]

    for x, y in screw_holes or []:
        plan.positions.append((float(x), float(y)))
        plan.inserts.append(m3)
        plan.insert_polys.append(
            box(float(x) - m3.outer_dia_mm / 2, float(y) - m3.outer_dia_mm / 2,
                float(x) + m3.outer_dia_mm / 2, float(y) + m3.outer_dia_mm / 2)
        )

    for x, y in hinge_holes or []:
        plan.positions.append((float(x), float(y)))
        plan.inserts.append(m4)
        plan.insert_polys.append(
            box(float(x) - m4.outer_dia_mm / 2, float(y) - m4.outer_dia_mm / 2,
                float(x) + m4.outer_dia_mm / 2, float(y) + m4.outer_dia_mm / 2)
        )

    plan.stats = {
        "insert_count": len(plan.inserts),
        "m3_count": sum(1 for i in plan.inserts if i.thread == "M3"),
        "m4_count": sum(1 for i in plan.inserts if i.thread == "M4"),
        "thread_life_cycles": m3.life_cycles,
    }
    return plan


def export_thread_inserts_to_dxf(msp, plan: ThreadInsertPlan) -> None:
    """输出嵌件外径轮廓 + 中心十字 + 工程注记到 DXF 专用图层「嵌件螺母」。"""
    layer_name = "嵌件螺母"

    for poly in plan.insert_polys:
        if poly and not poly.is_empty:
            msp.add_lwpolyline(list(poly.exterior.coords), close=True, dxfattribs={"layer": layer_name})

    for (x, y) in plan.positions:
        msp.add_line((x - 1.5, y), (x + 1.5, y), dxfattribs={"layer": layer_name})
        msp.add_line((x, y - 1.5), (x, y + 1.5), dxfattribs={"layer": layer_name})

    if plan.positions:
        x0, y0 = plan.positions[0]
        msp.add_text(
            f"BRASS INSERT ({plan.stats['m3_count']}xM3 / {plan.stats['m4_count']}xM4)",
            dxfattribs={"layer": layer_name, "height": 2.5, "insert": (x0 + 4.0, y0 + 4.0)},
        )
