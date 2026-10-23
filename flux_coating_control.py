"""波峰焊助焊剂喷雾涂覆量与比重控制 (Flux Spray Coating Weight & Specific Gravity Control) 引擎。

工业权威依据：
- SMTA Wave Soldering Handbook & 助焊剂供应商工艺窗口 (Alpha / Indium / Kester 水基免清洗剂):
  波峰焊前喷雾式助焊剂涂覆量必须精确控制在 300 ~ 1200 μg/cm² (以固体树脂计) 窗口内：
    * 涂覆不足 (< 300 μg/cm²): 助焊剂活化剂不足以清除焊盘与引脚氧化膜，产生不润湿/假焊与
      通孔顶端爬锡不足 (毛细不良)，是波峰焊最高频的批量性虚焊根因。
    * 涂覆过量 (> 1200 μg/cm²): 多余残留腐蚀性活化剂在免清洗工艺下留板，吸潮后漏电流上升，
      且预热时爆沸飞溅污染预热器加热管；超过 1500 μg/cm² 触发离子污染 (ROSE) 超限风险。
- 助焊剂浓度/比重闭环控制 (Baumé / refractometer):
  水基免清洗助焊剂在开放喷涂循环中溶剂持续挥发，固含量 (以折光仪 °Bx 或比重 g/cm³ 表征)
  逐步升高。典型控制窗口：比重 0.995 ~ 1.015 g/cm³ (25°C)。比重超窗口须补加去离子水
  稀释并重新标定涂覆量；折光仪读数漂移 ±2 °Bx 即需修正。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 涂覆量窗口 (μg/cm²，以固体树脂计)
MIN_COATING_UG_CM2 = 300.0
MAX_COATING_UG_CM2 = 1200.0
CRITICAL_OVER_COATING_UG_CM2 = 1500.0

# 比重控制窗口 (g/cm³ @ 25°C，水基免清洗助焊剂)
SG_MIN = 0.995
SG_MAX = 1.015


@dataclass
class FluxCoatingResult:
    """助焊剂涂覆量与比重核算、缺陷风险与修正方案。"""

    coating_weight_ug_cm2: float = 0.0
    is_within_window: bool = True
    flux_specific_gravity: float = 1.005
    is_sg_within_window: bool = True
    top_side_fillet_risk: str = "low"  # 'low' | 'moderate' | 'high' 不良爬锡风险
    ionic_residue_risk: bool = False
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "SMTA Wave Soldering Handbook & Flux Vendor Process Window (Alpha/Indium/Kester)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "coating_weight_ug_cm2": round(self.coating_weight_ug_cm2, 1),
            "is_within_window": self.is_within_window,
            "flux_specific_gravity": round(self.flux_specific_gravity, 4),
            "is_sg_within_window": self.is_sg_within_window,
            "top_side_fillet_risk": self.top_side_fillet_risk,
            "ionic_residue_risk": self.ionic_residue_risk,
            "corrective_actions": self.corrective_actions,
            "compliance_standard": self.compliance_standard,
        }


def control_flux_coating(
    spray_rate_ml_per_min: float = 55.0,
    conveyor_speed_m_per_min: float = 1.20,
    spray_width_mm: float = 350.0,
    flux_solids_content_pct: float = 2.5,
    flux_specific_gravity: float = 1.005,
    deposited_weight_override_ug_cm2: float | None = None,
) -> FluxCoatingResult:
    """按喷雾速率、走带速度与固含量核算板面助焊剂涂覆量并校核比重窗口。

    Args:
        spray_rate_ml_per_min: 喷雾泵总流量 (mL/min)
        conveyor_speed_m_per_min: 传送带速度 (m/min)
        spray_width_mm: 喷雾幅宽 (mm)
        flux_solids_content_pct: 助焊剂固体含量 (wt%，典型 2.0~3.5)
        flux_specific_gravity: 折光仪/比重计实测助焊剂比重 (g/cm³ @ 25°C)
        deposited_weight_override_ug_cm2: 可选——以称重法实测的板面涂覆量直接覆盖模型值

    Returns:
        FluxCoatingResult: 涂覆量合规性、爬锡/离子残留风险与修正动作
    """
    actions: list[str] = []

    if deposited_weight_override_ug_cm2 is not None and deposited_weight_override_ug_cm2 > 0:
        coating = float(deposited_weight_override_ug_cm2)
    else:
        # 面积通量模型: 板面每分钟经过面积 = width × speed; 固体质量流速 = rate × SG × solids
        if conveyor_speed_m_per_min <= 0 or spray_width_mm <= 0:
            return FluxCoatingResult(
                is_within_window=False,
                corrective_actions=["传送带速度或喷雾幅宽非法，涂覆量无法核算。"],
            )
        area_cm2_per_min = (spray_width_mm / 10.0) * (conveyor_speed_m_per_min * 100.0)
        solids_g_per_min = spray_rate_ml_per_min * flux_specific_gravity * (flux_solids_content_pct / 100.0)
        coating = (solids_g_per_min * 1e6) / area_cm2_per_min  # μg/cm²

    is_in_window = MIN_COATING_UG_CM2 <= coating <= MAX_COATING_UG_CM2

    # 爬锡风险：涂覆不足 → 顶端毛细不良
    if coating < MIN_COATING_UG_CM2:
        risk = "high" if coating < MIN_COATING_UG_CM2 * 0.6 else "moderate"
        deficit_pct = (MIN_COATING_UG_CM2 - coating) / MIN_COATING_UG_CM2 * 100.0
        actions.append(
            f"涂覆量 {coating:.0f} μg/cm² 低于 300 下限 (缺口 {deficit_pct:.0f}%)；活化剂不足以破除氧化膜，"
            "通孔顶端爬锡不足将批量虚焊——提升喷雾泵速或降低走带速度并复称重验证（SMTA 工艺窗口）。"
        )
    elif coating > MAX_COATING_UG_CM2:
        risk = "low"  # 爬锡本身充足
        excess_pct = (coating - MAX_COATING_UG_CM2) / MAX_COATING_UG_CM2 * 100.0
        actions.append(
            f"涂覆量 {coating:.0f} μg/cm² 高于 1200 上限 (超出 {excess_pct:.0f}%)；残留活化剂将推高板面"
            "离子污染，且预热爆沸飞溅污染加热管——降低泵速/提高走带速度，或稀释固含量后重标定。"
        )
    else:
        risk = "low"
        actions.append("涂覆量处于 300~1200 μg/cm² 工艺窗口内，维持当前喷雾参数。")

    ionic_risk = coating > CRITICAL_OVER_COATING_UG_CM2
    if ionic_risk:
        actions.append(
            f"涂覆量 {coating:.0f} μg/cm² 已超 1500 临界值，免清洗残留将直接触发 ROSE 离子污染超限 (IPC-CH-65)，须立即下调并复检。"
        )

    sg_ok = SG_MIN <= flux_specific_gravity <= SG_MAX
    if not sg_ok:
        if flux_specific_gravity > SG_MAX:
            actions.append(
                f"助焊剂比重 {flux_specific_gravity:.4f} g/cm³ 高于 {SG_MAX} 窗口，溶剂挥发致固含量偏高；"
                "补加去离子水至标定比重并以折光仪复测 °Bx 后重算涂覆量。"
            )
        else:
            actions.append(
                f"助焊剂比重 {flux_specific_gravity:.4f} g/cm³ 低于 {SG_MIN} 窗口，助焊剂被清洗水/冷凝水稀释；"
                "排放部分稀液并补充原液至标定比重，否则活化剂浓度不足引发假焊。"
            )

    return FluxCoatingResult(
        coating_weight_ug_cm2=coating,
        is_within_window=is_in_window,
        flux_specific_gravity=flux_specific_gravity,
        is_sg_within_window=sg_ok,
        top_side_fillet_risk=risk,
        ionic_residue_risk=ionic_risk,
        corrective_actions=actions,
        compliance_standard="SMTA Wave Soldering Handbook & Flux Vendor Process Window (Alpha/Indium/Kester)",
    )
