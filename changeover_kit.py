"""SMED 治具快速换型套件规划器 (Single-Minute Exchange of Die Changeover Kit Planner) 引擎。

工业权威依据：
- 新乡重夫 (Shigeo Shingo) SMED 快速换模法 / 精益生产 (Lean Production) 标准:
  多品种混线波峰焊产线的换型时间 (Changeover Time) 是最大的产能损失源之一；
  SMED 目标是把换型压缩到 10 分钟以内 (Single-Minute)，核心手法：
    1. 内部作业外部化 (External → Internal): 一切能在停线前完成的准备 (备料、
       预热嵌件、程序调用) 移到线外。外部化率目标 >= 70%。
    2. 通用基板 + 产品专用嵌件 (Common Base + Product Insert):
       通用基板 (含导轨咬合边、RFID、ESD 接地、压扣/定位销座) 跨产品族共用，
       每个产品只做一块轻量嵌件 (定位衬套 + 沉板框)，换型只换嵌件不拆基板。
       嵌件与基板用防呆编码定位销 (每个产品族唯一销位组合) 杜绝装错。
    3. 并行作业与标准化: 双工位预组装、换型步骤卡 (SOP)、扭矩预设电动螺丝刀。
- 工业换型时间基线 (SMTA 产线调研):
  传统整具换型 (吊出/吊入/重校): 25~45 min/次；
  嵌件式 SMED 换型: 4~8 min/次；外部化率每提升 10% ≈ 换型时间 -8%。
  混线日产 8 个品种时，SMED 每天可挽回 2~3 小时纯产能。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 内部/外部作业典型耗时基线 (min)
LEGACY_FULL_CHANGE_MIN = 30.0
SMED_INSERT_CHANGE_MIN = 6.0
EXTERNALIZATION_SAVING_PER_PCT = 0.08  # 每外部化 1% 换型时间 -8%


@dataclass
class ChangeoverKitResult:
    """SMED 换型套件规划与产能挽回测算。"""

    product_families: int = 0
    uses_common_base: bool = False
    poka_yoke_pin_codes: list[str] = field(default_factory=list)
    internal_steps: list[str] = field(default_factory=list)
    external_steps: list[str] = field(default_factory=list)
    externalization_rate: float = 0.0
    estimated_changeover_min: float = 0.0
    daily_changeovers: int = 0
    daily_time_saved_min: float = 0.0
    summary: str = ""
    compliance_standard: str = "Shingo SMED & Lean Production Changeover Standards (SMTA baseline)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_families": self.product_families,
            "uses_common_base": self.uses_common_base,
            "poka_yoke_pin_codes": self.poka_yoke_pin_codes,
            "internal_steps": self.internal_steps,
            "external_steps": self.external_steps,
            "externalization_rate": round(self.externalization_rate, 3),
            "estimated_changeover_min": round(self.estimated_changeover_min, 1),
            "daily_changeovers": self.daily_changeovers,
            "daily_time_saved_min": round(self.daily_time_saved_min, 0),
            "summary": self.summary,
            "compliance_standard": self.compliance_standard,
        }


def plan_changeover_kit(
    product_families: int = 3,
    daily_changeovers: int = 4,
    uses_common_base: bool = True,
    has_poka_yoke_pins: bool = True,
    externalization_rate: float = 0.7,
    current_changeover_min: float | None = None,
) -> ChangeoverKitResult:
    """规划通用基板+专用嵌件 SMED 换型套件并测算换型时间与日产能挽回。

    Args:
        product_families: 混线产品族数量 (需制作的专用嵌件数)
        daily_changeovers: 每日换型次数
        uses_common_base: 是否采用通用基板 + 嵌件架构 (False = 传统整具换型)
        has_poka_yoke_pins: 嵌件是否带防呆编码定位销
        externalization_rate: 作业外部化率 0~1 (SMED 目标 >= 0.7)
        current_changeover_min: 当前实测换型时间 (min)；缺省按架构基线

    Returns:
        ChangeoverKitResult: 内外部作业清单、预估换型时间与日挽回产能
    """
    if product_families <= 0 or daily_changeovers < 0:
        return ChangeoverKitResult(
            summary="产品族数或换型次数非法。",
        )

    ext_rate = max(0.0, min(0.9, externalization_rate))

    internal_steps = [
        "停线 → 旋出嵌件固定螺钉 (电动螺丝刀预设扭矩)",
        "取出上产品嵌件、放入下产品嵌件 (防呆销对位)",
        "调用下产品炉温/带速/喷雾程序配方",
    ]
    if not uses_common_base:
        internal_steps = [
            "停线 → 吊出整具 (行车/双人抬)",
            "重新吊入下产品整具并校准导轨咬合",
            "重校 RFID/ESD/压扣与全部定位销",
            "调用下产品炉温/带速/喷雾程序配方",
        ]
    external_steps = [
        "线外预检嵌件密封面平面度与清洁度",
        "线外预热下一产品嵌件 (80°C 烘干柜)",
        "备齐隔垫/螺钉/扭矩刀并核对换型 SOP 卡",
    ]

    base_min = current_changeover_min if (current_changeover_min and current_changeover_min > 0) else (
        SMED_INSERT_CHANGE_MIN if uses_common_base else LEGACY_FULL_CHANGE_MIN
    )
    # 外部化率折减：est = base × (1 - 0.08 × ext%)，ext=0.7 时折减 5.6%
    est_min = base_min * (1.0 - EXTERNALIZATION_SAVING_PER_PCT * ext_rate)
    est_min = max(2.5, est_min)

    legacy_daily = LEGACY_FULL_CHANGE_MIN * daily_changeovers
    saved = max(0.0, legacy_daily - est_min * daily_changeovers)

    pin_codes: list[str] = []
    if has_poka_yoke_pins and uses_common_base:
        # 每产品族唯一 3 销位组合编码 (A-L 网格 12 位取 3)
        import itertools as _it

        grid = list("ABCDEFGHIJKL")
        combos = list(_it.combinations(grid, 3))
        for i in range(product_families):
            c = combos[i % len(combos)]
            pin_codes.append(f"FAM{i + 1}:" + "-".join(c))

    summary = (
        f"{product_families} 产品族 × 通用基板+防呆嵌件架构：预估换型 {est_min:.1f}min/次 "
        f"(外部化率 {ext_rate * 100:.0f}%)，按日产 {daily_changeovers} 次换型每日挽回 "
        f"{saved / 60.0:.1f}h 产能。"
        if uses_common_base
        else f"传统整具换型基线 {est_min:.1f}min/次——迁移到通用基板+嵌件架构可将换型压至 <10min。"
    )

    return ChangeoverKitResult(
        product_families=product_families,
        uses_common_base=uses_common_base,
        poka_yoke_pin_codes=pin_codes,
        internal_steps=internal_steps,
        external_steps=external_steps,
        externalization_rate=ext_rate,
        estimated_changeover_min=est_min,
        daily_changeovers=daily_changeovers,
        daily_time_saved_min=saved,
        summary=summary,
        compliance_standard="Shingo SMED & Lean Production Changeover Standards (SMTA baseline)",
    )
