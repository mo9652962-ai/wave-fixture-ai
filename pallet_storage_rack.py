"""波峰焊治具库房存储堆叠规范 (Pallet Storage & Stacking Compliance) 引擎。

工业权威依据：
- AGICORP §6.2 (Wave Solder Pallet Storage & Handling Guidelines) / IEC 61340-5-1:
  波峰焊治具在换型间隙的库房存储直接影响下次投产良率与治具寿命：
    * 堆叠极限：合成石治具自重 4~8 kg，底部治具承受的堆叠压应力须 <= 0.5 MPa
      (合成石抗压强度 ~350 MPa 的 1/700 安全系数)，对应推荐最大堆叠层数 = 底面压应力
      反算；治具必须平放堆叠，禁止立靠 (立靠坠落导致定位销/钛嵌件崩裂)。
    * 板间隔离：堆叠层间必须垫 3~5mm EVA/珍珠棉隔垫，防止治具表面互磨划伤
      密封面平面度 (0.2mm 公差) 并缓冲取放冲击。
    * 防静电 (ANSI/ESD S20.20)：存储区与转运车必须为 EPA 接地区，治具表面
      电阻 10⁶~10⁹Ω 周期复测；非 EPA 区裸堆积累静电将击穿返修治具上的残留 ESDS。
    * 温湿度：合成石/FR-4 治具存储 <= 40°C / <= 60%RH，受潮治具直接投产将
      在 260°C 波峰产生蒸汽炸裂分层 (同 JEDEC MSL 机理)；吸潮 > 48h 须 80°C/4h 烘干。
    * 标识检索：每具治具存储位须与 RFID/条码 (IPC-1782) 双向绑定，先进先出 (FIFO)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_STACK_PRESSURE_MPA = 0.5
MAX_STACK_TOTAL_MASS_KG = 50.0  # 双人安全搬运整垛上限
MAX_STACK_PRACTICAL = 8  # 防倾倒/取放安全硬上限
MAX_STORAGE_TEMP_C = 40.0
MAX_STORAGE_RH_PCT = 60.0
REQUIRED_PAD_MM = 3.0
BAKE_C = 80.0
BAKE_H = 4.0


@dataclass
class StorageRackResult:
    """治具存储堆叠核算与库房环境合规评估。"""

    pallet_mass_kg: float = 0.0
    footprint_cm2: float = 0.0
    recommended_max_stack: int = 0
    actual_stack: int = 0
    bottom_pressure_mpa: float = 0.0
    is_stack_ok: bool = True
    has_interlayer_pads: bool = False
    is_epa_grounded: bool = False
    storage_temp_c: float = 25.0
    storage_rh_pct: float = 50.0
    is_environment_ok: bool = True
    bake_required: bool = False
    violations: list[str] = field(default_factory=list)
    corrective_actions: list[str] = field(default_factory=list)
    compliance_standard: str = "AGICORP §6.2 & ANSI/ESD S20.20 & IEC 61340-5-1 Storage Guidelines"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pallet_mass_kg": round(self.pallet_mass_kg, 1),
            "footprint_cm2": round(self.footprint_cm2, 0),
            "recommended_max_stack": self.recommended_max_stack,
            "actual_stack": self.actual_stack,
            "bottom_pressure_mpa": round(self.bottom_pressure_mpa, 3),
            "is_stack_ok": self.is_stack_ok,
            "has_interlayer_pads": self.has_interlayer_pads,
            "is_epa_grounded": self.is_epa_grounded,
            "storage_temp_c": round(self.storage_temp_c, 1),
            "storage_rh_pct": round(self.storage_rh_pct, 0),
            "is_environment_ok": self.is_environment_ok,
            "bake_required": self.bake_required,
            "violations": self.violations,
            "corrective_actions": self.corrective_actions,
            "compliance_standard": self.compliance_standard,
        }


def check_storage_rack(
    pallet_mass_kg: float = 6.0,
    footprint_w_mm: float = 350.0,
    footprint_h_mm: float = 300.0,
    actual_stack: int = 8,
    has_interlayer_pads: bool = False,
    is_epa_grounded: bool = False,
    storage_temp_c: float = 25.0,
    storage_rh_pct: float = 50.0,
    exposure_h_since_last_run: float = 24.0,
) -> StorageRackResult:
    """核算堆叠压应力上限层数并校验库房温湿度/防静电/烘干需求。

    Args:
        pallet_mass_kg: 单具治具整备质量 (kg)
        footprint_w_mm / footprint_h_mm: 治具底面支撑投影尺寸 (mm)
        actual_stack: 实际堆叠层数
        has_interlayer_pads: 层间是否有 EVA/珍珠棉隔垫
        is_epa_grounded: 存储区是否为 EPA 接地区
        storage_temp_c / storage_rh_pct: 库房温度 (°C) 与相对湿度 (%)
        exposure_h_since_last_run: 距上次过炉/烘干暴露时长 (h)

    Returns:
        StorageRackResult: 允许堆叠层数、底部压应力、环境与烘干合规评估
    """
    violations: list[str] = []
    actions: list[str] = []

    if pallet_mass_kg <= 0 or footprint_w_mm <= 0 or footprint_h_mm <= 0:
        return StorageRackResult(
            violations=["治具质量或底面投影非法。"],
            corrective_actions=["核实治具质量与外形尺寸。"],
        )

    area_cm2 = (footprint_w_mm / 10.0) * (footprint_h_mm / 10.0)
    area_m2 = area_cm2 / 1e4
    # 三重堆叠上限取最小: 压应力 / 双人搬运总质量 / 防倾倒硬上限
    per_layer_pa = (pallet_mass_kg * 9.81) / area_m2
    per_layer_mpa = per_layer_pa / 1e6
    by_pressure = int(MAX_STACK_PRESSURE_MPA / max(1e-6, per_layer_mpa))
    by_mass = int(MAX_STACK_TOTAL_MASS_KG / max(0.1, pallet_mass_kg))
    max_stack = max(1, min(by_pressure, by_mass, MAX_STACK_PRACTICAL))

    bottom_pressure = per_layer_mpa * max(1, actual_stack)
    stack_ok = actual_stack <= max_stack

    if not stack_ok:
        violations.append(
            f"堆叠 {actual_stack} 层 > 允许 {max_stack} 层 (压应力/搬运质量/防倾倒三重上限取小)："
            f"底部治具压应力 {bottom_pressure:.2f}MPa，整垛 {pallet_mass_kg * actual_stack:.0f}kg "
            "超双人安全搬运与防倾倒限值，密封面平面度将蠕变超差 (AGICORP §6.2)。"
        )
        actions.append(f"拆垛至 <= {max_stack} 层或改用多层料架分层承重。")

    if not has_interlayer_pads:
        violations.append(
            "堆叠层间无 EVA/珍珠棉隔垫：取放冲击与互磨将划伤 0.2mm 平面度密封面。"
        )
        actions.append(f"层间加垫 {REQUIRED_PAD_MM:.0f}mm EVA 隔垫并凸出治具边缘 5mm 防滑。")

    if not is_epa_grounded:
        violations.append(
            "存储区非 EPA 接地区：裸堆静电积累将击穿返修治具上的残留 ESDS 器件（ANSI/ESD S20.20）。"
        )
        actions.append("存储架/转运车接地并铺防静电桌垫，治具表面电阻 10⁶~10⁹Ω 周期复测。")

    env_ok = storage_temp_c <= MAX_STORAGE_TEMP_C and storage_rh_pct <= MAX_STORAGE_RH_PCT
    if not env_ok:
        over = []
        if storage_temp_c > MAX_STORAGE_TEMP_C:
            over.append(f"温度 {storage_temp_c:.0f}°C > 40°C")
        if storage_rh_pct > MAX_STORAGE_RH_PCT:
            over.append(f"湿度 {storage_rh_pct:.0f}%RH > 60%")
        violations.append(
            "库房环境超限 (" + "、".join(over) + ")：受潮治具直接过 260°C 波峰将蒸汽炸裂分层。"
        )
        actions.append("库房加装除湿机/空调，受潮治具投产前按 80°C/4h 烘干。")

    bake = exposure_h_since_last_run > 48.0
    if bake:
        actions.append(
            f"治具已暴露 {exposure_h_since_last_run:.0f}h > 48h：投产前须 {BAKE_C:.0f}°C/{BAKE_H:.0f}h 烘干除潮。"
        )

    if not violations and not bake:
        actions.append("堆叠、隔垫、EPA、温湿度全部合规，维持当前库房管理。")

    return StorageRackResult(
        pallet_mass_kg=pallet_mass_kg,
        footprint_cm2=area_cm2,
        recommended_max_stack=max_stack,
        actual_stack=actual_stack,
        bottom_pressure_mpa=bottom_pressure,
        is_stack_ok=stack_ok,
        has_interlayer_pads=has_interlayer_pads,
        is_epa_grounded=is_epa_grounded,
        storage_temp_c=storage_temp_c,
        storage_rh_pct=storage_rh_pct,
        is_environment_ok=env_ok,
        bake_required=bake,
        violations=violations,
        corrective_actions=actions,
        compliance_standard="AGICORP §6.2 & ANSI/ESD S20.20 & IEC 61340-5-1 Storage Guidelines",
    )
