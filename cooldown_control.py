"""波峰焊出板后冷却速率控制 (Post-Wave Controlled Cooling Rate Limiter) 引擎。

工业权威依据：
- IPC J-STD-001E §4.5 / SMTA Wave Soldering Handbook 冷却规范：
  焊点离开锡波后的冷却速率必须受控在 <= 4.0 °C/s。过快的强制冷却（冷风直吹、
  冷水辊）会带来两类批量缺陷：
    1. 焊点内部枝晶粗大结构被"冻结"：SAC305 冷却过快时 β-Sn 树枝晶粗化不良，
       焊点机械强度与热疲劳寿命显著劣化（IPC-9701 寿命可跌 30~50%）。
    2. FR-4 板体上下表面温差应力：z 向 CTE 在 Tg 以上陡增 4~5 倍，骤冷使板面
       产生 0.5~1.0% 永久翘曲 (bow/twist 超 IPC-A-600 ≤0.75% 限值)，金属化孔壁
       被拉裂。
- 工业产线冷却区配置（Kurtz Ersa / SEHO / 劲拓标准机型）:
  标准波峰焊机出板冷却区长度 0.8~1.5 m，配变频轴流风机；PCB 从锡波出口 ~250°C
  冷却至安全下板/堆叠温度 60°C 的时间窗由带速与冷却区长度共同决定。
  最小冷却区长度 = 带速 × (250-60)/目标速率 / 60。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_COOLING_RATE_C_PER_S = 4.0
TARGET_COOLING_RATE_C_PER_S = 2.5
SAFE_HANDLE_TEMP_C = 60.0
WAVE_EXIT_TEMP_C = 250.0


@dataclass
class CooldownControlResult:
    """冷却速率核算与冷却区配置评估。"""

    measured_cooling_rate_c_per_s: float = 0.0
    is_rate_compliant: bool = True
    cooldown_time_s: float = 0.0
    required_cooling_length_m: float = 0.0
    available_cooling_length_m: float = 0.0
    is_length_sufficient: bool = True
    exit_handle_temp_c: float = 0.0
    violations: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "IPC J-STD-001E §4.5 & SMTA Post-Wave Cooling Guidelines"

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured_cooling_rate_c_per_s": round(self.measured_cooling_rate_c_per_s, 2),
            "is_rate_compliant": self.is_rate_compliant,
            "cooldown_time_s": round(self.cooldown_time_s, 1),
            "required_cooling_length_m": round(self.required_cooling_length_m, 2),
            "available_cooling_length_m": round(self.available_cooling_length_m, 2),
            "is_length_sufficient": self.is_length_sufficient,
            "exit_handle_temp_c": round(self.exit_handle_temp_c, 1),
            "violations": self.violations,
            "corrective_actions": self.corrective_actions,
            "compliance_standard": self.compliance_standard,
        }


def check_cooldown_control(
    conveyor_speed_m_per_min: float = 1.2,
    cooling_zone_length_m: float = 1.0,
    fan_speed_pct: float = 60.0,
    measured_cooling_rate_c_per_s: float | None = None,
    measured_exit_temp_c: float | None = None,
    wave_exit_temp_c: float = WAVE_EXIT_TEMP_C,
) -> CooldownControlResult:
    """核算出板冷却速率与冷却区长度是否满足 <=4°C/s 与 60°C 安全下板要求。

    Args:
        conveyor_speed_m_per_min: 传送带速度 (m/min)
        cooling_zone_length_m: 冷却区长度 (m)
        fan_speed_pct: 冷却风机转速百分比 (0~100)，线性映射冷却能力 0.8~6.0°C/s
        measured_cooling_rate_c_per_s: 可选——炉温仪实测冷却速率 (°C/s)，覆盖模型
        measured_exit_temp_c: 可选——冷却区出口实测板温 (°C)
        wave_exit_temp_c: 锡波出口板温 (°C)，默认 250

    Returns:
        CooldownControlResult: 速率合规、冷却区长度充分性与修正动作
    """
    violations: list[str] = []
    actions: list[str] = []

    if conveyor_speed_m_per_min <= 0 or cooling_zone_length_m < 0:
        return CooldownControlResult(
            violations=["传送带速度或冷却区长度配置非法。"],
            corrective_actions=["核实冷却区参数。"],
        )

    # 冷却区驻留时间
    dwell_s = (cooling_zone_length_m / conveyor_speed_m_per_min) * 60.0
    total_drop = wave_exit_temp_c - SAFE_HANDLE_TEMP_C  # 190°C

    # 模型冷却速率：风机 0~100% 线性映射 0.8~6.0 °C/s 能力，受驻留时间约束
    modeled_capacity = 0.8 + (max(0.0, min(100.0, fan_speed_pct)) / 100.0) * 5.2
    # 实际速率 = 温降需求 ÷ 可用驻留时间 与 风机能力 两者取小
    rate_by_time = total_drop / max(1.0, dwell_s)
    modeled_rate = min(modeled_capacity, rate_by_time)

    rate = (
        float(measured_cooling_rate_c_per_s)
        if measured_cooling_rate_c_per_s is not None and measured_cooling_rate_c_per_s > 0
        else modeled_rate
    )

    # 出口温度：速率 × 驻留时间 ≤ 总温降
    achieved_drop = min(total_drop, rate * dwell_s)
    exit_temp = (
        float(measured_exit_temp_c)
        if measured_exit_temp_c is not None and measured_exit_temp_c > 0
        else wave_exit_temp_c - achieved_drop
    )

    # 所需冷却区长度（按目标速率 2.5°C/s 从波温降到 60°C）
    need_time_s = total_drop / TARGET_COOLING_RATE_C_PER_S
    required_len = conveyor_speed_m_per_min * (need_time_s / 60.0)

    rate_ok = rate <= MAX_COOLING_RATE_C_PER_S
    if not rate_ok:
        violations.append(
            f"冷却速率 {rate:.2f}°C/s > 4.0°C/s 上限：焊点枝晶粗化冻结、板体 z 向应力翘曲"
            "与金属化孔壁拉裂三重风险（IPC J-STD-001E §4.5）。"
        )
        actions.append("下调冷却风机转速或提高带速，把速率压回 <=2.5°C/s 目标带。")
    elif rate < 1.0:
        actions.append(f"速率 {rate:.2f}°C/s 偏缓，产能节拍可适度上调风机至目标 2.5°C/s。")

    length_ok = cooling_zone_length_m >= required_len
    if not length_ok:
        violations.append(
            f"冷却区长度 {cooling_zone_length_m:.2f}m < 按 2.5°C/s 所需 {required_len:.2f}m："
            f"出板温度 {exit_temp:.0f}°C 高于 {SAFE_HANDLE_TEMP_C:.0f}°C 安全下板温度，"
            "堆叠将烫伤板面并使焊点在受压下变形。"
        )
        actions.append("延长冷却区、降低带速，或在机尾增设辅助冷却延长段。")

    if not violations:
        actions.append(
            f"冷却速率 {rate:.2f}°C/s 与冷却区长度均合规，出板 {exit_temp:.0f}°C ≤60°C 可安全下板。"
        )

    return CooldownControlResult(
        measured_cooling_rate_c_per_s=rate,
        is_rate_compliant=rate_ok,
        cooldown_time_s=dwell_s,
        required_cooling_length_m=required_len,
        available_cooling_length_m=cooling_zone_length_m,
        is_length_sufficient=length_ok,
        exit_handle_temp_c=exit_temp,
        violations=violations,
        corrective_actions=actions,
        compliance_standard="IPC J-STD-001E §4.5 & SMTA Post-Wave Cooling Guidelines",
    )
