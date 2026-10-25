"""选择性波峰焊喷嘴浸润深度/驻留时间工艺窗口优化器 (Selective Nozzle Immersion & Dwell Optimizer)。

工业权威依据（2024~2025 行业资料综合）：
- AllPCB《Optimizing Your Selective Soldering Process》(2026-04)：
  浸润深度 (Immersion Depth) 是喷嘴直径的分数，须校准到 75~100% 通孔填充且无锡珠/桥连；
  喷嘴磨损随时间改变有效浸润深度，需定期检查与重新镀锡 (re-tinning)。
- 行业驻留基线 (LinkedIn/Rayming、Chuxin SMT 技术综述)：
  选择焊喷泉单点驻留典型 1~3 秒，一般不超过 5 秒——超 5s 喷嘴上方锡渣积聚
  且助焊剂挥发殆尽；低于 1s 孔填充不足 (通孔垂直爬锡 <75%)。
- ERSA 配件目录：Select Wave 浸润式喷嘴 Φ4~15mm 外径，Z 轴可调喷嘴高度，
  需专用活化剂清洁/活化浸润式喷嘴；SEHO MWS 2300 / PowerSelective 提供
  20mm 总行程软件可调喷嘴高度，做产品级波高优化。
- 小喷嘴 vs 节拍 trade-off (smtmachineline)：
  小喷嘴 (Φ4mm) 适合密集组件，但需更慢走速与更长驻留——直接影响产线节拍。
  浸润深度经验式: h = 喷嘴波高 × 0.6~0.8；波高不足 → 桥连/漏焊；波高过大 →
  锡珠飞溅与顶面漫锡风险。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIN_DWELL_S = 1.0
MAX_DWELL_S = 5.0
TARGET_DWELL_S = 2.0
MIN_FILL_PCT = 75.0
IMMERSION_FRACTION_RANGE = (0.6, 0.8)


@dataclass
class NozzleProfileResult:
    """喷嘴浸润/驻留工艺窗口核算与缺陷风险判定。"""

    nozzle_inner_dia_mm: float = 6.0
    wave_height_mm: float = 0.0
    immersion_depth_mm: float = 0.0
    immersion_fraction: float = 0.0
    is_immersion_ok: bool = True
    dwell_time_s: float = 0.0
    is_dwell_ok: bool = True
    est_hole_fill_pct: float = 0.0
    meets_fill: bool = True
    nozzle_wear_factor: float = 1.0
    retinning_recommended: bool = False
    violations: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "AllPCB 2026 & ERSA Select Wave & SEHO MWS 2300 Process Windows"

    def to_dict(self) -> dict[str, Any]:
        return {
            "nozzle_inner_dia_mm": self.nozzle_inner_dia_mm,
            "wave_height_mm": round(self.wave_height_mm, 2),
            "immersion_depth_mm": round(self.immersion_depth_mm, 2),
            "immersion_fraction": round(self.immersion_fraction, 2),
            "is_immersion_ok": self.is_immersion_ok,
            "dwell_time_s": round(self.dwell_time_s, 2),
            "is_dwell_ok": self.is_dwell_ok,
            "est_hole_fill_pct": round(self.est_hole_fill_pct, 0),
            "meets_fill": self.meets_fill,
            "nozzle_wear_factor": round(self.nozzle_wear_factor, 2),
            "retinning_recommended": self.retinning_recommended,
            "violations": self.violations,
            "corrective_actions": self.corrective_actions,
            "compliance_standard": self.compliance_standard,
        }


def optimize_selective_nozzle_profile(
    nozzle_inner_dia_mm: float = 6.0,
    pump_speed_pct: float = 60.0,
    pcb_thickness_mm: float = 1.6,
    plated_hole_dia_mm: float = 0.9,
    measured_dwell_s: float | None = None,
    nozzle_age_cycles: int = 0,
    has_nitrogen: bool = True,
) -> NozzleProfileResult:
    """核算选择焊喷嘴浸润深度与驻留时间窗口，输出缺陷风险与节拍优化。

    Args:
        nozzle_inner_dia_mm: 喷嘴内径 (mm, ERSA Φ4~15)
        pump_speed_pct: 锡泵转速百分比 (0~100)——决定波高
        pcb_thickness_mm: 板厚 (mm)
        plated_hole_dia_mm: 镀覆孔直径 (mm)
        measured_dwell_s: 实测驻留时间 (s)；缺省按波高/孔径模型估算
        nozzle_age_cycles: 喷嘴累计过炉周期 (磨损评估)
        has_nitrogen: 是否氮气保护 (提升爬锡 30~50%)

    Returns:
        NozzleProfileResult: 浸润/驻留/填充率核算与修正动作
    """
    violations: list[str] = []
    actions: list[str] = []

    # 波高模型: 60% 泵速 → 标称波高 ≈ 喷嘴内径 × 0.35，随泵速线性缩放
    wave_height = nozzle_inner_dia_mm * 0.35 * max(0.2, min(1.5, pump_speed_pct / 60.0))
    # 浸润深度 = 板底面进入波面深度 = 波高 × 目标分数 (0.6~0.8 带内取 0.7)
    immersion = wave_height * 0.7
    fraction = immersion / max(0.1, pcb_thickness_mm)

    immersion_ok = IMMERSION_FRACTION_RANGE[0] <= fraction <= IMMERSION_FRACTION_RANGE[1] * 1.6
    if not immersion_ok:
        if fraction < IMMERSION_FRACTION_RANGE[0]:
            violations.append(
                f"浸润深度 {immersion:.2f}mm 仅板厚 {fraction:.0%} (<60%)：波高不足，"
                "通孔顶部热量与锡量供给不够，孔填充与上锡不良（AllPCB 2026）。"
            )
            actions.append("上调锡泵转速提高波高，或降低喷嘴 Z 轴 (SEHO 20mm 行程软件可调)。")
        else:
            violations.append(
                f"浸润深度 {immersion:.2f}mm 达板厚 {fraction:.0%} 过深：锡珠飞溅与"
                "顶面漫锡风险（波峰涌动溢出治具开口）。"
            )
            actions.append("下调泵速或抬升喷嘴 Z 轴，把浸润压回板厚 60~80% 带内。")

    # 驻留时间: 经验式 t ≈ k × 孔径/板厚因子，氮气加持缩短需求
    fill_factor = plated_hole_dia_mm / max(0.4, pcb_thickness_mm)
    est_fill = min(100.0, 55.0 + 40.0 * fill_factor + (12.0 if has_nitrogen else 0.0))
    if measured_dwell_s is not None and measured_dwell_s > 0:
        dwell = float(measured_dwell_s)
    else:
        dwell = max(1.0, TARGET_DWELL_S * (0.30 / max(0.2, plated_hole_dia_mm)) ** 0.5)
    dwell_ok = MIN_DWELL_S <= dwell <= MAX_DWELL_S
    # 驻留修正填充率
    if dwell < MIN_DWELL_S:
        est_fill *= dwell / MIN_DWELL_S
    if dwell > MAX_DWELL_S:
        est_fill = min(100.0, est_fill * 1.05)

    if not dwell_ok:
        if dwell < MIN_DWELL_S:
            violations.append(
                f"驻留 {dwell:.2f}s < 1.0s 下限：孔填充不足 {est_fill:.0f}% (<{MIN_FILL_PCT:.0f}% 目标)，"
                "垂直爬锡不良（Rayming/Chuxin 行业基线 1~3s）。"
            )
            actions.append("降低走速或延长停留，使单点驻留进入 1~3s 窗口。")
        else:
            violations.append(
                f"驻留 {dwell:.2f}s > 5.0s 上限：喷嘴上方锡渣积聚、助焊剂活化剂挥发殆尽，"
                "拉尖与桥连风险陡增。"
            )
            actions.append("提高走速分摊节拍，或分段多次短驻留替代单点长驻留。")

    meets_fill = est_fill >= MIN_FILL_PCT
    if not meets_fill:
        violations.append(f"估算孔填充率 {est_fill:.0f}% < 75% 目标：氮气缺失或波高/驻留双重不足。")
        if not has_nitrogen:
            actions.append("开启氮气保护 (残氧 <500ppm)——爬锡高度提升 30~50% 是最经济的第一手段。")

    # 喷嘴磨损: 每 2 万周期浸润效率衰减 ~1%；>5 万周期建议 re-tin
    wear = 1.0 + min(0.15, nozzle_age_cycles * 0.05e-6)
    retin = nozzle_age_cycles >= 50_000
    if retin:
        actions.append(
            f"喷嘴已累计 {nozzle_age_cycles} 周期：按 ERSA/SEHO 规范重新镀锡 (re-tinning) 活化，"
            "恢复有效浸润深度。"
        )

    if not violations:
        actions.append("浸润深度、驻留时间与孔填充率全部在工艺窗口内，维持当前配方。")

    return NozzleProfileResult(
        nozzle_inner_dia_mm=nozzle_inner_dia_mm,
        wave_height_mm=wave_height,
        immersion_depth_mm=immersion,
        immersion_fraction=fraction,
        is_immersion_ok=immersion_ok,
        dwell_time_s=dwell,
        is_dwell_ok=dwell_ok,
        est_hole_fill_pct=est_fill,
        meets_fill=meets_fill,
        nozzle_wear_factor=wear,
        retinning_recommended=retin,
        violations=violations,
        corrective_actions=actions,
        compliance_standard="AllPCB 2026 & ERSA Select Wave & SEHO MWS 2300 Process Windows",
    )
