"""波峰焊预热区升温斜率与助焊剂活化窗口合规检查器 (Preheat Ramp & Flux Activation Compliance) 引擎。

工业权威依据：
- IPC J-STD-001E §4.4 / SMTA Wave Soldering Handbook 预热工艺窗口：
  波峰焊治具载板进入锡波前必须完成充分预热，标准三段预热曲线：
    * 升温斜率 (Ramp): 1.0 ~ 4.0 °C/s（目标 2~3 °C/s）。低于 1.0°C/s 产线节拍浪费；
      高于 4.0°C/s 将造成 FR-4 芯吸分层与元件本体热冲击微裂 (IPC-A-610 §4.5)。
    * 预热出口温度 (Top-side board temp at wave entry): 100 ~ 130 °C。
      - 低于 100°C：助焊剂活化剂未完全激活即入波，溶剂突沸炸锡锡珠飞溅；
        且板体与锡波温差 >155°C 将产生剧烈热冲击导致板翘与通孔应力裂纹。
      - 高于 130°C：免清洗助焊剂 (low-solid ROL0/ROL1) 中的活性剂在入波前
        已提前挥发殆尽，通孔爬锡润湿不良、上锡不足虚焊。
    * 浸润/保温段 (Soak): 60 ~ 120 s，使板厚方向温度均匀化，减小 ΔT 内应力。
- 助焊剂供应商窗口 (Alpha/Indium/Kester 水基免清洗剂):
  预热出口温度需与助焊剂活化温度窗口匹配：水基助焊剂要求出口 105~125°C
  （水溶剂蒸发完毕且活化剂保留至波峰），挥发不完全将引发锡波表面孔洞与针孔。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RAMP_MIN_C_PER_S = 1.0
RAMP_MAX_C_PER_S = 4.0
RAMP_TARGET_MIN = 2.0
RAMP_TARGET_MAX = 3.0
EXIT_TEMP_MIN_C = 100.0
EXIT_TEMP_MAX_C = 130.0
WATER_BASED_EXIT_WINDOW = (105.0, 125.0)
SOAK_MIN_S = 60.0
SOAK_MAX_S = 120.0
MAX_TEMP_DIFF_TO_WAVE_C = 155.0  # 板-锡波允许温差（<100°C 入波即超 155°C 骤热冲击）
WAVE_TEMP_C = 255.0


@dataclass
class PreheatProfileResult:
    """预热曲线核算、逐段违规与修正建议。"""

    ramp_rate_c_per_s: float = 0.0
    is_ramp_compliant: bool = True
    exit_temp_c: float = 0.0
    is_exit_temp_compliant: bool = True
    soak_time_s: float = 0.0
    is_soak_compliant: bool = True
    thermal_shock_delta_c: float = 0.0
    is_thermal_shock_ok: bool = True
    flux_type: str = "no_clean"
    violations: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "IPC J-STD-001E §4.4 & SMTA Wave Soldering Handbook Preheat Window"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ramp_rate_c_per_s": round(self.ramp_rate_c_per_s, 2),
            "is_ramp_compliant": self.is_ramp_compliant,
            "exit_temp_c": round(self.exit_temp_c, 1),
            "is_exit_temp_compliant": self.is_exit_temp_compliant,
            "soak_time_s": round(self.soak_time_s, 1),
            "is_soak_compliant": self.is_soak_compliant,
            "thermal_shock_delta_c": round(self.thermal_shock_delta_c, 1),
            "is_thermal_shock_ok": self.is_thermal_shock_ok,
            "flux_type": self.flux_type,
            "violations": self.violations,
            "corrective_actions": self.corrective_actions,
            "compliance_standard": self.compliance_standard,
        }


def check_preheat_profile(
    preheat_length_m: float = 1.8,
    conveyor_speed_m_per_min: float = 1.2,
    preheat_zone1_temp_c: float = 110.0,
    preheat_zone2_temp_c: float = 140.0,
    ambient_temp_c: float = 25.0,
    measured_exit_temp_c: float | None = None,
    soak_time_s: float | None = None,
    flux_type: str = "no_clean",
    wave_temp_c: float = WAVE_TEMP_C,
) -> PreheatProfileResult:
    """按预热区配置或实测曲线核算升温斜率、出口温度与浸润时间合规性。

    Args:
        preheat_length_m: 预热区总长度 (m)，多段预热区之和
        conveyor_speed_m_per_min: 传送带速度 (m/min)
        preheat_zone1_temp_c / zone2_temp_c: 各预热区设定温度 (°C)
        ambient_temp_c: 入板环境温度 (°C)
        measured_exit_temp_c: 可选——炉温测试仪实测板面出口温度 (°C)，覆盖模型估算
        soak_time_s: 可选——实测浸润段时长 (s)；缺省按预热区通过时间估算
        flux_type: 'no_clean' (免清洗) / 'water_based' (水基) / 'rosin' (松香)
        wave_temp_c: 锡波温度 (°C)，默认 255 (SAC305)

    Returns:
        PreheatProfileResult: 三段窗口逐项合规与修正动作
    """
    violations: list[str] = []
    actions: list[str] = []

    # 通过预热区时长
    if conveyor_speed_m_per_min <= 0 or preheat_length_m <= 0:
        return PreheatProfileResult(
            violations=["传送带速度或预热区长度非法，曲线无法核算。"],
            corrective_actions=["核实预热区长度与带速配置。"],
        )
    transit_s = (preheat_length_m / conveyor_speed_m_per_min) * 60.0

    # 升温斜率：板温近似从环境升至 (z1+z2)/2 附近斜坡——取平均有效温升
    avg_zone_temp = (preheat_zone1_temp_c + preheat_zone2_temp_c) / 2.0
    modeled_exit = ambient_temp_c + (avg_zone_temp - ambient_temp_c) * min(1.0, transit_s / 45.0)
    # 融合模型：出口温度 = 环境温 + (平均区温-环境) × 饱和因子（45s 时间常数）
    if measured_exit_temp_c is not None and measured_exit_temp_c > 0:
        exit_temp = float(measured_exit_temp_c)
    else:
        exit_temp = modeled_exit

    ramp = (exit_temp - ambient_temp_c) / max(1.0, transit_s)

    # 浸润时间
    soak = soak_time_s if soak_time_s is not None and soak_time_s > 0 else transit_s * 0.55

    # —— 升温斜率窗口 ——
    ramp_ok = RAMP_MIN_C_PER_S <= ramp <= RAMP_MAX_C_PER_S
    if not ramp_ok:
        if ramp > RAMP_MAX_C_PER_S:
            violations.append(
                f"升温斜率 {ramp:.2f}°C/s > 4.0°C/s 上限：FR-4 芯吸分层与元件体热冲击微裂风险（IPC-A-610 §4.5）。"
            )
            actions.append("降低预热区设定温度或提高带速，把斜率压回 2~3°C/s 目标带。")
        else:
            violations.append(
                f"升温斜率 {ramp:.2f}°C/s < 1.0°C/s 下限：产线节拍浪费且助焊剂溶剂蒸发过缓。"
            )
            actions.append("提高预热区温度或降低带速，升至 2~3°C/s 目标带。")
    elif not (RAMP_TARGET_MIN <= ramp <= RAMP_TARGET_MAX):
        actions.append(f"斜率 {ramp:.2f}°C/s 在窗口内但偏离 2~3°C/s 目标带，可微调均衡。")

    # —— 出口温度窗口（按助焊剂类型适配）——
    if flux_type == "water_based":
        lo, hi = WATER_BASED_EXIT_WINDOW
        window_note = "水基助焊剂 105~125°C（溶剂蒸发完毕且活化剂保留）"
    else:
        lo, hi = EXIT_TEMP_MIN_C, EXIT_TEMP_MAX_C
        window_note = "标准 100~130°C"
    exit_ok = lo <= exit_temp <= hi
    if not exit_ok:
        if exit_temp < lo:
            violations.append(
                f"预热出口板温 {exit_temp:.0f}°C 低于 {lo:.0f}°C 下限（{window_note}）："
                "活化剂未完全激活/溶剂未蒸发即入波，将炸锡锡珠飞溅；"
                f"且与 {wave_temp_c:.0f}°C 锡波温差 >155°C 触发剧烈热冲击板翘。"
            )
            actions.append("延长预热区或提升区温，确保入波前板面达标。")
        else:
            violations.append(
                f"预热出口板温 {exit_temp:.0f}°C 高于 {hi:.0f}°C 上限（{window_note}）："
                "免清洗活化剂提前挥发殆尽，通孔爬锡润湿不良批量虚焊。"
            )
            actions.append("下调末段预热区温度或缩短预热驻留。")

    # —— 浸润时间窗口 ——
    soak_ok = SOAK_MIN_S <= soak <= SOAK_MAX_S
    if not soak_ok:
        side = "不足 60s" if soak < SOAK_MIN_S else "超过 120s"
        violations.append(f"浸润段 {soak:.0f}s {side}：板厚方向温差过大/活化剂过耗。")
        actions.append("调整带速或预热区长度使浸润段落入 60~120s。")

    # —— 热冲击温差 ——
    delta = wave_temp_c - exit_temp
    shock_ok = delta <= MAX_TEMP_DIFF_TO_WAVE_C
    if not shock_ok:
        violations.append(
            f"板温与锡波温差 {delta:.0f}°C > 130°C：入波瞬间热冲击将引发板翘与金属化孔应力裂纹。"
        )
        actions.append("提高出口板温（延长预热）以压差至 130°C 以内。")

    if not violations:
        actions.append("预热三段窗口全部合规，维持当前炉温配方。")

    return PreheatProfileResult(
        ramp_rate_c_per_s=ramp,
        is_ramp_compliant=ramp_ok,
        exit_temp_c=exit_temp,
        is_exit_temp_compliant=exit_ok,
        soak_time_s=soak,
        is_soak_compliant=soak_ok,
        thermal_shock_delta_c=delta,
        is_thermal_shock_ok=shock_ok,
        flux_type=flux_type,
        violations=violations,
        corrective_actions=actions,
        compliance_standard="IPC J-STD-001E §4.4 & SMTA Wave Soldering Handbook Preheat Window",
    )
