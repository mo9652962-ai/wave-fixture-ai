"""波峰焊传送带链爪拖曳摩擦力与电机驱动扭矩校核 (Conveyor Chain Drag & Motor Torque) 引擎。

工业权威依据：
- Kurtz Ersa PowerFlow / SEHO MWS 2300 / 劲拓 JT-WS 波峰焊机传动机构规范：
  波峰焊传送链（双侧钛合金链爪或不锈钢销轴链条）在 5.5° 爬坡角下连续运行。
  随着治具托盘连续进板（整线同时承载 4 ~ 10 具治具），链爪导轨滑移摩擦力显著累积：
    F_total = N_pallets × [m_pallet × g × (sin(θ) + μ_friction × cos(θ))]
  其中：
    * 爬坡倾角 θ: 典型 4.5° ~ 7.0°（默认 5.5°）。
    * 高温摩擦系数 μ_friction:
      - 合成石基板 vs 不锈钢链爪: μ ≈ 0.28 ~ 0.35。
      - 带 6061-T6 硬质阳极氧化耐磨导轨: μ ≈ 0.18 ~ 0.22。
      - 钛合金耐磨滑条: μ ≈ 0.15 ~ 0.18。
- 驱动电机过载与链爪跳齿卡轨风险 (Drive Motor Stall & Chain Jamming):
  典型工业波峰焊主机驱动电机额定功率为 180W ~ 370W，链轮传动额定输出扭矩为 15.0 ~ 35.0 N·m。
  若重型治具（单具 > 6.0kg）多片连续进板且未安装耐磨导轨条（摩擦阻力剧增 60% 以上），
  总拖曳拉力超越链爪最大抗拉承载力（F_chain_max ≈ 600N）或电机额定扭矩储备（安全系数 SF < 1.5），
  将导致链条跳齿爬轨、走板顿挫抖动（剧烈抖动导致波峰液面锡波荡漾、焊点拉尖桥连），甚至烧毁传动减速机。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("conveyor-drag-torque")

GRAVITY_M_S2 = 9.81
MAX_CHAIN_PULL_CAPACITY_N = 650.0  # 典型波峰焊滚子链安全拉力上限 (N)
MIN_MOTOR_TORQUE_SAFETY_FACTOR = 1.5 # 传动电机最小安全储备系数


@dataclass
class ConveyorDragTorqueParams:
    """传送带拖曳力学核算参数。"""

    enabled: bool = True
    conveyor_incline_deg: float = 5.5   # 传送带爬坡倾角 (4.5°~7.0°)
    pallets_on_line_count: int = 6      # 炉内同时承载运行的治具最大数量
    drive_sprocket_pitch_radius_mm: float = 65.0  # 主动链轮节圆半径 (mm)
    motor_rated_torque_nm: float = 25.0 # 驱动减速电机额定输出扭矩 (N·m)
    has_wear_rails: bool = False        # 是否安装低摩擦金属耐磨导轨条


@dataclass
class ConveyorDragTorqueResult:
    """拖曳拉力、电机负载率与链条安全校核结果。"""

    single_pallet_mass_kg: float = 5.5
    pallets_on_line_count: int = 6
    friction_coefficient: float = 0.30
    total_drag_force_n: float = 0.0
    drive_torque_demanded_nm: float = 0.0
    motor_torque_safety_factor: float = 0.0
    chain_pull_utilization_pct: float = 0.0
    is_motor_safe: bool = True
    is_chain_pull_safe: bool = True
    violations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    compliance_standard: str = "Ersa & SEHO Wave Conveyor Drive Transmission Standards"

    def to_dict(self) -> dict[str, Any]:
        return {
            "single_pallet_mass_kg": round(self.single_pallet_mass_kg, 2),
            "pallets_on_line_count": self.pallets_on_line_count,
            "friction_coefficient": round(self.friction_coefficient, 2),
            "total_drag_force_n": round(self.total_drag_force_n, 1),
            "drive_torque_demanded_nm": round(self.drive_torque_demanded_nm, 2),
            "motor_torque_safety_factor": round(self.motor_torque_safety_factor, 2),
            "chain_pull_utilization_pct": round(self.chain_pull_utilization_pct, 1),
            "is_motor_safe": self.is_motor_safe,
            "is_chain_pull_safe": self.is_chain_pull_safe,
            "violations": self.violations,
            "recommendations": self.recommendations,
            "compliance_standard": self.compliance_standard,
        }


def calculate_conveyor_drag_torque(
    pallet_mass_kg: float = 5.5,
    params: ConveyorDragTorqueParams | None = None,
) -> ConveyorDragTorqueResult:
    """核算波峰焊炉内多治具连续爬坡传输总阻力与驱动电机扭矩储备。

    Args:
        pallet_mass_kg: 单具治具整备质量 (kg)。
        params: 传送动力学参数。

    Returns:
        ConveyorDragTorqueResult: 总拉力、轴端扭矩、电机安全系数与跳齿预警。
    """
    if params is None:
        params = ConveyorDragTorqueParams()

    # 高温摩擦系数：安装硬质阳极耐磨导轨可降至 0.18，裸合成石摩擦为 0.30
    mu = 0.18 if params.has_wear_rails else 0.30
    theta_rad = math.radians(params.conveyor_incline_deg)

    # 单具治具沿链条切向重力分量与法向摩擦阻力
    # F_single = m * g * (sin(theta) + mu * cos(theta))
    g = GRAVITY_M_S2
    f_single = pallet_mass_kg * g * (math.sin(theta_rad) + mu * math.cos(theta_rad))

    # 炉内全负荷总拖曳拉力 (N)
    f_total = f_single * max(1, params.pallets_on_line_count)

    # 主动链轮所需轴端驱动扭矩 (N·m)
    # T = F_total * r_sprocket
    r_sprocket_m = params.drive_sprocket_pitch_radius_mm / 1000.0
    torque_demanded = f_total * r_sprocket_m

    # 电机扭矩安全系数 SF = T_rated / T_demanded
    sf = params.motor_rated_torque_nm / max(1e-4, torque_demanded)
    motor_ok = sf >= MIN_MOTOR_TORQUE_SAFETY_FACTOR

    # 链条拉力利用率
    util_pct = (f_total / MAX_CHAIN_PULL_CAPACITY_N) * 100.0
    chain_ok = f_total <= MAX_CHAIN_PULL_CAPACITY_N

    violations: list[str] = []
    recs: list[str] = []

    if not motor_ok:
        violations.append(
            f"传送链电机扭矩安全系数 SF={sf:.2f} < 1.5 工业安全底线（需求扭矩 {torque_demanded:.1f} N·m "
            f"> 额定 {params.motor_rated_torque_nm:.1f} N·m 之 67%），电机存在重载发热堵转风险。"
        )
        recs.append("治具双侧边缘加装 6061-T6 硬质阳极耐磨导轨条 (摩擦系数从 0.30 骤降至 0.18) 以降低 40% 拖曳负荷。")

    if not chain_ok:
        violations.append(
            f"炉内 {params.pallets_on_line_count} 具治具总拖曳拉力达 {f_total:.1f}N > 链条额定极限 650N "
            f"(负载率 {util_pct:.0f}%)，链爪存在跳齿脱轨与链条拉伸疲劳断裂高危。"
        )
        recs.append("实施治具轻量化减重或将炉内同时运行治具节拍调大（减少瞬时在炉连线治具数量）。")

    if motor_ok and chain_ok:
        recs.append("传送带拖曳拉力与驱动扭矩裕量充沛 (SF >= 1.5)，链条运行平稳无跳齿卡轨风险。")

    return ConveyorDragTorqueResult(
        single_pallet_mass_kg=pallet_mass_kg,
        pallets_on_line_count=params.pallets_on_line_count,
        friction_coefficient=mu,
        total_drag_force_n=f_total,
        drive_torque_demanded_nm=torque_demanded,
        motor_torque_safety_factor=sf,
        chain_pull_utilization_pct=util_pct,
        is_motor_safe=motor_ok,
        is_chain_pull_safe=chain_ok,
        violations=violations,
        recommendations=recs,
        compliance_standard="Ersa & SEHO Wave Conveyor Drive Transmission Standards",
    )
