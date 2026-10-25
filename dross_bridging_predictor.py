"""波峰焊锡渣桥连与拖锡尖峰预测器 (Dross Bridging & Icicle Predictor) 引擎。

工业权威依据（Macaos / Sierra Circuits / APTPCB / ElePCB 2024~2025 综述）:
- Sierra Circuits《Making Sense of Wave Soldering》:
  波峰焊质量取决于"板对锡波的稳定性"与"受控离波"——离波区 (peel-off) 的
  拖锡是桥连与冰柱 (icicle) 的首要根因：离波角不足时，熔融锡液在引脚末端
  因表面张力缩颈失败而拉出尖峰；相邻引脚间距 <0.8mm 时尖峰搭接成桥连。
- Macaos Selective Guidelines §2 & APTPCB:
  治具开孔需"贴近板外形"，开孔过大 → 板底暴露面过大 → 拖锡面积大 →
  桥连/锡珠概率陡增；开孔过大同时增大锡渣生成面积 (液面暴露 × 波动)。
- 锡渣生成模型 (Kester/Alpha 数据手册):
  锡渣速率 ∝ 液面暴露面积 × 波动扰动系数；氮气保护削减 85~90%；
  双波峰 (ChipWave) 湍波比平波高 2~3×。
- 拖锡冰柱判据 (Sierra Circuits / Bob Willis):
  离波角 (peel-off angle) >= 4° 时表面张力自然缩颈；治具出板尾端坡度或
  锡波倾角不足 → 冰柱。引脚末端离波速度 > 锡液回流速度是必要条件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BRIDGE_GAP_RISK_MM = 0.8  # 引脚间距低于此值桥连高危
MIN_PEEL_OFF_ANGLE_DEG = 4.0
MAX_EXPOSED_AREA_RATIO = 0.6  # 治具开孔暴露面积/沉板区面积上限


@dataclass
class DrossBridgingResult:
    """锡渣/桥连/冰柱综合预测与整改建议。"""

    exposed_area_mm2: float = 0.0
    exposed_ratio: float = 0.0
    is_exposure_ok: bool = True
    dross_rate_kg_per_day: float = 0.0
    is_dross_ok: bool = True
    min_pin_gap_mm: float = 99.0
    bridge_risk_pins: list[str] = field(default_factory=list)
    peel_off_angle_deg: float = 0.0
    icicle_risk: bool = False
    has_nitrogen: bool = True
    risk_level: str = "low"
    violations: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "Macaos Selective §2 & Sierra Circuits & APTPCB Peel-off Guidelines"

    def to_dict(self) -> dict[str, Any]:
        return {
            "exposed_area_mm2": round(self.exposed_area_mm2, 0),
            "exposed_ratio": round(self.exposed_ratio, 2),
            "is_exposure_ok": self.is_exposure_ok,
            "dross_rate_kg_per_day": round(self.dross_rate_kg_per_day, 2),
            "is_dross_ok": self.is_dross_ok,
            "min_pin_gap_mm": (
                round(self.min_pin_gap_mm, 2) if self.min_pin_gap_mm < 99 else None
            ),
            "bridge_risk_pins": self.bridge_risk_pins,
            "peel_off_angle_deg": round(self.peel_off_angle_deg, 1),
            "icicle_risk": self.icicle_risk,
            "has_nitrogen": self.has_nitrogen,
            "risk_level": self.risk_level,
            "violations": self.violations,
            "corrective_actions": self.corrective_actions,
            "compliance_standard": self.compliance_standard,
        }


def predict_dross_bridging(
    sink_area_mm2: float = 5000.0,
    solder_openings_area_mm2: float = 2500.0,
    min_pin_gap_mm: float = 1.2,
    pin_labels: list[tuple[str, float]] | None = None,
    peel_off_angle_deg: float = 4.5,
    has_nitrogen: bool = True,
    wave_type: str = "laminar",
    pot_capacity_kg: float = 300.0,
) -> DrossBridgingResult:
    """预测锡渣生成速率、桥连高危引脚与离波冰柱风险。

    Args:
        sink_area_mm2: 沉板区面积 (mm²)
        solder_openings_area_mm2: 上锡开孔暴露总面积 (mm²)
        min_pin_gap_mm: 最小引脚间距 (mm)
        pin_labels: [(位号, 间距mm)] 可选——低于 0.8mm 的位号将列名预警
        peel_off_angle_deg: 离波角 (治具尾端坡度或锡波倾角, °)
        has_nitrogen: 是否氮气保护
        wave_type: 'laminar' 平波 | 'turbulent' 湍波 (ChipWave)
        pot_capacity_kg: 锡炉容量 (kg)

    Returns:
        DrossBridgingResult: 锡渣速率/桥连名单/冰柱判定与整改
    """
    violations: list[str] = []
    actions: list[str] = []

    exposure_ratio = solder_openings_area_mm2 / max(1.0, sink_area_mm2)
    exposure_ok = exposure_ratio <= MAX_EXPOSED_AREA_RATIO

    # 锡渣速率: 液面暴露 (dm²) × 扰动系数 × 氮气削减
    exposed_dm2 = solder_openings_area_mm2 / 100.0
    turb_mult = {"laminar": 1.0, "turbulent": 2.5}.get(wave_type, 1.0)
    dross_rate = exposed_dm2 * 0.05 * turb_mult * pot_capacity_kg / 300.0
    if has_nitrogen:
        dross_rate *= 0.12  # 削减 ~88%
    dross_ok = dross_rate <= 1.5  # kg/day 上限 (300kg 炉典型 1.2~2.5 无氮)

    if not exposure_ok:
        violations.append(
            f"治具开孔暴露比 {exposure_ratio:.0%} > 60% 上限：板底暴露面过大，"
            "拖锡面积与锡渣生成面积同步放大（Macaos §2：开孔须贴近板外形）。"
        )
        actions.append("收窄上锡开孔至焊盘群包络 + 3mm，减少无谓暴露。")
    if not dross_ok:
        violations.append(
            f"锡渣生成 {dross_rate:.2f}kg/日 > 1.5kg 预算：锡渣卷入波峰将造成氧化夹渣虚焊。"
        )
        if not has_nitrogen:
            actions.append("开启氮气保护：锡渣削减 85~90% 是最有效的单一措施（Kester/Alpha 数据）。")

    bridge_pins: list[str] = []
    if min_pin_gap_mm < BRIDGE_GAP_RISK_MM:
        if pin_labels:
            bridge_pins = [ref for ref, gap in pin_labels if gap < BRIDGE_GAP_RISK_MM]
        else:
            bridge_pins = ["<未命名细间距引脚群>"]
        violations.append(
            f"最小引脚间距 {min_pin_gap_mm:.2f}mm < 0.8mm：离波拖锡尖峰将搭接成桥连"
            + (f"，高危位号 {', '.join(bridge_pins[:4])}" if bridge_pins else "")
            + "（Sierra Circuits 离波判据）。"
        )
        actions.append("对细间距引脚群采用选择焊点对点补焊替代整波；或加锡珠挡片隔栏。")

    icicle = peel_off_angle_deg < MIN_PEEL_OFF_ANGLE_DEG
    if icicle:
        violations.append(
            f"离波角 {peel_off_angle_deg:.1f}° < 4°：表面张力无法自然缩颈，"
            "引脚末端将拖出冰柱（icicle）；离波速度低于锡液回流速度所致。"
        )
        actions.append("增大治具出板尾端坡度/锡波倾角至 ≥4°，或提高传送带离波段速度。")

    risk = "high" if (icicle or bridge_pins or not dross_ok) else ("moderate" if not exposure_ok else "low")

    if not violations:
        actions.append("暴露比、锡渣速率、引脚间距与离波角全部合规，维持当前波峰配方。")

    return DrossBridgingResult(
        exposed_area_mm2=solder_openings_area_mm2,
        exposed_ratio=exposure_ratio,
        is_exposure_ok=exposure_ok,
        dross_rate_kg_per_day=dross_rate,
        is_dross_ok=dross_ok,
        min_pin_gap_mm=min_pin_gap_mm,
        bridge_risk_pins=bridge_pins,
        peel_off_angle_deg=peel_off_angle_deg,
        icicle_risk=icicle,
        has_nitrogen=has_nitrogen,
        risk_level=risk,
        violations=violations,
        corrective_actions=actions,
        compliance_standard="Macaos Selective §2 & Sierra Circuits & APTPCB Peel-off Guidelines",
    )
