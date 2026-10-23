"""波峰焊锡炉熔锡污染健康监控 (Solder Pot Contamination Health Monitor) 引擎。

工业权威依据：
- IPC J-STD-001 (Requirements for Soldered Electrical and Electronic Assemblies) §5.2 / ANSI/J-STD-001E:
  波峰焊锡炉中的熔融无铅焊料 (SAC305) 在持续高温 (250~265°C) 运行下会不断溶解 PCB 通孔筒壁、
  焊盘与元件引脚基材中的铜。铜含量随产量累积上升，当 Cu 含量超过 0.85 wt%（J-STD-001 污染上限）
  时将显著改变焊料液相线温度与润湿特性，产生颗粒状灰暗焊点与桥连/拉尖缺陷，必须排掉部分旧料
  并补充纯锡锭稀释，或整体换炉。
  其他关键杂质上限（wt%）: Pb ≤ 0.10（无铅兼容）、Fe ≤ 0.020、Ni ≤ 0.010、Zn ≤ 0.003、Cd ≤ 0.002。
- SMTA / Kurtz Ersa 锡炉维护规范：
  锡渣 (Dross) 生成速率与液面暴露面积、波峰扰动强度成正比，典型工业连续双波产线每 8 小时
  生成 1.2~2.5 kg 锡渣/每百公斤锡炉；锡渣不及时捞除将卷入波峰造成氧化夹渣虚焊。
  标准维护节拍：每 4 小时捞渣一次、每 40 小时化验一次光谱成分。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# J-STD-001 SAC305 杂质上限 (wt%)
IMPURITY_LIMITS_WT_PCT: dict[str, float] = {
    "copper": 0.85,
    "lead": 0.10,
    "iron": 0.020,
    "nickel": 0.010,
    "zinc": 0.003,
    "cadmium": 0.002,
    "antimony": 0.50,
    "bismuth": 0.25,
    "silver": 0.75,  # SAC305 名义 3.0，允许波动上限按名义 +0.75 过量计
}


@dataclass
class SolderPotHealthParams:
    """锡炉健康监控参数。"""

    pot_capacity_kg: float = 300.0  # 锡炉总容量 (kg)
    operating_temp_c: float = 255.0  # 熔锡工作温度 (°C)
    boards_per_day: int = 800  # 日产量 (板/天)
    dross_removal_interval_h: float = 4.0  # 捞渣周期 (h)
    assay_interval_h: float = 40.0  # 光谱化验周期 (h)


@dataclass
class SolderPotHealthResult:
    """锡炉杂质核算、稀释方案与捞渣排程结果。"""

    impurity_wt_pct: dict[str, float] = field(default_factory=dict)
    violations: list[dict[str, Any]] = field(default_factory=list)
    copper_trend_days_to_limit: float | None = None
    required_dilution_kg: float = 0.0
    dross_generated_kg_per_day: float = 0.0
    dross_removal_schedule_h: float = 4.0
    next_assay_due_h: float = 40.0
    is_pot_healthy: bool = True
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "IPC J-STD-001 §5.2 Solder Pot Purity & SMTA Pot Maintenance"

    def to_dict(self) -> dict[str, Any]:
        return {
            "impurity_wt_pct": {k: round(v, 4) for k, v in self.impurity_wt_pct.items()},
            "violations": self.violations,
            "copper_trend_days_to_limit": (
                round(self.copper_trend_days_to_limit, 1)
                if self.copper_trend_days_to_limit is not None
                else None
            ),
            "required_dilution_kg": round(self.required_dilution_kg, 1),
            "dross_generated_kg_per_day": round(self.dross_generated_kg_per_day, 2),
            "dross_removal_schedule_h": self.dross_removal_schedule_h,
            "next_assay_due_h": self.next_assay_due_h,
            "is_pot_healthy": self.is_pot_healthy,
            "corrective_actions": self.corrective_actions,
            "compliance_standard": self.compliance_standard,
        }


def monitor_solder_pot_health(
    impurity_wt_pct: dict[str, float] | None = None,
    copper_accumulation_rate_wt_pct_per_day: float = 0.0,
    params: SolderPotHealthParams | None = None,
) -> SolderPotHealthResult:
    """核算锡炉杂质含量与 J-STD-001 上限，输出稀释换料量、捞渣与化验排程。

    Args:
        impurity_wt_pct: 最新光谱化验各杂质含量 (wt%)，键为 IMPURITY_LIMITS_WT_PCT 子集
        copper_accumulation_rate_wt_pct_per_day: 铜含量日增速 (wt%/天，按历史化验回归)
        params: 锡炉运行参数

    Returns:
        SolderPotHealthResult: 杂质违规、稀释补锡量、锡渣产量与维护排程
    """
    if params is None:
        params = SolderPotHealthParams()

    measured = {k: float(v) for k, v in (impurity_wt_pct or {}).items() if k in IMPURITY_LIMITS_WT_PCT}
    violations: list[dict[str, Any]] = []
    actions: list[str] = []

    for name, val in measured.items():
        limit = IMPURITY_LIMITS_WT_PCT[name]
        if val > limit:
            violations.append(
                {
                    "element": name,
                    "measured_wt_pct": round(val, 4),
                    "limit_wt_pct": limit,
                    "severity": "critical" if name in ("copper", "iron", "zinc", "cadmium") else "major",
                }
            )

    # 铜超限稀释量: 排出 m_out kg 旧料后 Cu 质量 (m*cu - m_out*cu) / m = limit → 解 m_out
    dilution_kg = 0.0
    cu = measured.get("copper", 0.0)
    cu_limit = IMPURITY_LIMITS_WT_PCT["copper"]
    if cu > cu_limit:
        # (cu * M - cu * x) / M = limit  →  x = M * (1 - limit / cu)
        dilution_kg = params.pot_capacity_kg * (1.0 - cu_limit / max(1e-6, cu))
        actions.append(
            f"排掉 {dilution_kg:.0f} kg 污染旧锡并补入等量纯 SAC305 锭，使铜含量从 {cu:.3f}% 稀释回 {cu_limit:.2f}% 上限内（J-STD-001 §5.2）。"
        )

    # 铜增长趋势预测
    trend_days: float | None = None
    if copper_accumulation_rate_wt_pct_per_day > 0 and cu < cu_limit:
        trend_days = (cu_limit - cu) / copper_accumulation_rate_wt_pct_per_day
        if trend_days <= 5.0:
            actions.append(
                f"按当前增速 {copper_accumulation_rate_wt_pct_per_day:.4f}%/天，铜含量将在 {trend_days:.1f} 天内触及 0.85% 上限，请提前安排稀释换料。"
            )

    # 锡渣产量模型: 每日 0.4~0.8% 炉容 × (产量因子)
    load_factor = min(2.0, max(0.4, params.boards_per_day / 1000.0))
    dross_per_day = params.pot_capacity_kg * 0.005 * load_factor

    # 维护排程建议
    if params.dross_removal_interval_h > 4.0:
        actions.append("捞渣周期超过 4h 标准节拍，锡渣卷入波峰将造成氧化夹渣虚焊，收紧至每 4 小时一次（SMTA 维护规范）。")
    if params.assay_interval_h > 40.0:
        actions.append("光谱化验周期超过 40h 标准，杂质漂移无法及时发现，收紧至每 40 小时一次。")
    if not actions and not violations:
        actions.append("锡炉杂质与维护节拍均合规，维持现有捞渣/化验排程。")

    cited = "IPC J-STD-001 §5.2 Solder Purity & SMTA/Ersa Pot Maintenance Guidelines"

    return SolderPotHealthResult(
        impurity_wt_pct=measured,
        violations=violations,
        copper_trend_days_to_limit=trend_days,
        required_dilution_kg=dilution_kg,
        dross_generated_kg_per_day=dross_per_day,
        dross_removal_schedule_h=params.dross_removal_interval_h,
        next_assay_due_h=params.assay_interval_h,
        is_pot_healthy=(len(violations) == 0),
        corrective_actions=actions,
        compliance_standard=cited,
    )
