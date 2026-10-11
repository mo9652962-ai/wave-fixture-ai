"""治具清洁保养与寿命预测引擎 (Cleaning Interval & Pallet Lifespan Forecaster).

工业背景与保养基准：
- Röchling《Durostone 清洁与保养指引》/ Ersa 设备维护规程：
  波峰焊治具每次过炉都会在沉板密封面与开孔内残留助焊剂 (Flux Residue) 与锡渣，
  残留物在 250°C+ 炉温下持续碳化并腐蚀合成石树脂基体，导致密封面失效渗锡与开孔壁粗糙挂锡。
  1. 清洁周期：每 200 过炉周期 (或每周，先到为准) 用水基中性清洗剂 + 尼龙刷清洗，
     禁用钢丝刷与强溶剂 (损伤表面及 ESD 耗散层)；
  2. 寿命预测：Durostone/Ricocel 合成石治具额定量产寿命 ~8000 过炉周期，
     高 Tg FR-4 仅 ~500 周期，铝治具 ~3000 周期 (需防挂锡)；
  3. 钛合金嵌件使刀刃隔锡薄壁寿命 ×3；
  4. 预防性更换提前量：到达 90% 额定寿命即触发换新预警，避免临期失效报废在制品。
- 产能换算：日产量 (板/天) × 治具占用率 → 单治具日过炉次数 → 清洁周期换算为天数。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from materials import MATERIALS

# 材料额定量产寿命 (过炉周期数) —— Röchling 产品页 + 行业惯例
MATERIAL_LIFESPAN_CYCLES: dict[str, int] = {
    "durostone": 8000,
    "ricocel": 8000,
    "fr4_high_tg": 500,
    "aluminum": 3000,
}

TITANIUM_WALL_LIFE_FACTOR = 3.0  # 钛合金嵌件对隔锡薄壁寿命增益
CLEANING_INTERVAL_CYCLES = 200  # 清洁周期 (过炉次数)
CLEANING_INTERVAL_DAYS_CAP = 7  # 清洁周期上限 (天，先到为准)
REPLACEMENT_ALERT_PCT = 90.0  # 预防性更换预警阈值 (% 额定寿命)


@dataclass
class MaintenancePlan:
    material_key: str
    rated_lifespan_cycles: int
    effective_wall_life_cycles: int
    cleaning_interval_cycles: int
    cleaning_interval_days: int
    cycles_per_day: float
    projected_replacement_date_hint: str
    replacement_alert_cycles: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_maintenance_plan(
    material_key: str = "durostone",
    boards_per_day: float = 500.0,
    boards_per_pallet_pass: float = 1.0,
    has_titanium_inserts: bool = False,
    current_cycles: int = 0,
) -> MaintenancePlan:
    """预测治具清洁周期与寿命：日过炉次数 = 日产量 / 单次过炉装载量。"""
    mat_key = material_key if material_key in MATERIAL_LIFESPAN_CYCLES else "durostone"
    rated = MATERIAL_LIFESPAN_CYCLES[mat_key]
    wall_life = int(rated * (TITANIUM_WALL_LIFE_FACTOR if has_titanium_inserts else 1.0))

    passes_per_day = max(0.01, float(boards_per_day) / max(0.01, float(boards_per_pallet_pass)))
    cleaning_days = min(CLEANING_INTERVAL_DAYS_CAP, max(1, int(CLEANING_INTERVAL_CYCLES / passes_per_day)))

    warnings: list[str] = []
    if current_cycles >= wall_life:
        warnings.append(
            f"治具已过额定寿命 {current_cycles}/{wall_life} 周期——立即停用换新，"
            "临期失效将导致密封面渗锡报废在制品（Röchling Durostone 寿命指引）。"
        )
    elif current_cycles >= int(wall_life * REPLACEMENT_ALERT_PCT / 100.0):
        warnings.append(
            f"治具已用 {current_cycles}/{wall_life} 周期 (≥{REPLACEMENT_ALERT_PCT:.0f}%)——"
            "下达预防性换新采购单，避免断线。"
        )

    remaining = max(0, wall_life - max(0, current_cycles))
    days_left = remaining / passes_per_day
    date_hint = (
        f"剩余约 {remaining} 过炉周期 / {days_left:.0f} 天 (按 {passes_per_day:.1f} 次/天)"
        if current_cycles > 0
        else f"额定 {wall_life} 过炉周期 / 约 {wall_life / passes_per_day:.0f} 天 (按 {passes_per_day:.1f} 次/天)"
    )

    return MaintenancePlan(
        material_key=mat_key,
        rated_lifespan_cycles=rated,
        effective_wall_life_cycles=wall_life,
        cleaning_interval_cycles=CLEANING_INTERVAL_CYCLES,
        cleaning_interval_days=cleaning_days,
        cycles_per_day=round(passes_per_day, 2),
        projected_replacement_date_hint=date_hint,
        replacement_alert_cycles=int(wall_life * REPLACEMENT_ALERT_PCT / 100.0),
        warnings=warnings,
    )


def render_maintenance_markdown(plan: MaintenancePlan, job_name: str = "FIXTURE") -> str:
    """输出车间张贴版《治具保养点检卡》(Markdown)。"""
    mat = MATERIALS.get(plan.material_key)
    lines = [
        f"# 治具保养点检卡 — {job_name}",
        "",
        (
            f"- **材料**: {mat.name_cn if mat else plan.material_key}"
            f" · 额定寿命 {plan.rated_lifespan_cycles} 过炉周期"
            f" · 薄壁有效寿命 {plan.effective_wall_life_cycles} 周期"
        ),
        (
            f"- **清洁周期**: 每 {plan.cleaning_interval_cycles} 过炉周期"
            f"（约 {plan.cleaning_interval_days} 天，先到为准）——水基中性清洗剂 + 尼龙刷，"
            "**禁用钢丝刷与强溶剂**"
        ),
        f"- **寿命进度**: {plan.projected_replacement_date_hint}",
        f"- **换新预警线**: {plan.replacement_alert_cycles} 周期 (90%)",
    ]
    if plan.warnings:
        lines.append("")
        for w in plan.warnings:
            lines.append(f"> ⚠️ {w}")
    lines += [
        "",
        "| 点检项 | 频次 | 合格判据 |",
        "|:---|:---|:---|",
        "| 密封面平整度 | 每次清洁后 | 无碳化黑斑、无压痕 >0.1mm |",
        "| 开孔壁/隔锡壁 | 每次清洁后 | 无挂锡毛刺、无崩缺 |",
        "| 压扣/铰链动作 | 每周 | 回弹顺畅、无松动 |",
        "| 钛合金刀片固定 | 每月 | M2 螺钉无松脱、刀片无翘曲 |",
        "| ESD 表面阻抗 | 每月 | 10⁶~10⁹ Ω (静电耗散合格) |",
    ]
    return "\n".join(lines)
