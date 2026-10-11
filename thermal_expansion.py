"""治具-PCB 热膨胀失配间隙校核 (CTE Mismatch Expansion Gap Solver).

工业背景与材料科学基准：
- 波峰焊时治具与 PCB 同时从室温 (~25°C) 升至液态锡波温度 (~260°C, ΔT≈235K)，
  两者线膨胀系数 (CTE) 不同 → 沉板槽与 PCB 边缘的设计间隙 (常温 0.2mm) 会被热膨胀差吃掉：
      ΔL = L × (CTE_pallet − CTE_pcb) × ΔT
  差值 > 常温设计间隙时，PCB 在高温下被沉板槽壁顶死 → 拱起变形、密封面离缝渗锡、
  冷却后卡板无法取出 (板厂现场高频缺陷)。
- 线膨胀系数 (CTE, ppm/K，厂商 datasheet 与行业手册)：
  * Durostone (Röchling C253/C151): ~22 (面内)
  * Ricocel: ~22
  * 高 Tg FR-4 治具板: ~15
  * 铝合金 6061: 23.6
  * PCB 用 FR-4 (Tg 130~180, 面内 T<Tg): ~14~17，取 15
- 计算示例：200mm 沉板跨度 × (22−15)ppm/K × 235K ≈ 0.33mm > 0.2mm 常温间隙 —— 必须预警。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# 材料 CTE (ppm/K, 面内) —— Röchling / 行业手册
CTE_PPM_K: dict[str, float] = {
    "durostone": 22.0,
    "ricocel": 22.0,
    "fr4_high_tg": 15.0,
    "aluminum": 23.6,
}
PCB_FR4_CTE_PPM_K = 15.0  # PCB FR-4 面内 CTE (T<Tg)
WAVE_DELTA_T_C = 235.0  # 室温 25°C → 波峰 260°C
DEFAULT_SINK_CLEARANCE_MM = 0.2  # 常温设计单边间隙 (fixture_phase1 沉板外扩值)


@dataclass
class ExpansionGapResult:
    pallet_len_mm: float
    pallet_expansion_mm: float
    pcb_len_mm: float
    pcb_expansion_mm: float
    differential_mm: float
    design_clearance_mm: float
    clearance_consumed_pct: float
    at_risk: bool
    material_key: str
    ipc_standard: str = "Röchling Durostone Datasheet CTE / IPC-2141A Thermal Mechanics"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_expansion_gap(
    pallet_len_mm: float,
    pcb_len_mm: float | None = None,
    material_key: str = "durostone",
    pcb_cte_ppm_k: float = PCB_FR4_CTE_PPM_K,
    delta_t_c: float = WAVE_DELTA_T_C,
    design_clearance_mm: float = DEFAULT_SINK_CLEARANCE_MM,
) -> ExpansionGapResult:
    """计算波峰温度下治具与 PCB 的热膨胀差，并校核常温设计间隙是否被吃掉。

    pcb_len_mm 缺省取 pallet_len_mm 的 0.92 (典型沉板跨度占治具长度比例)。
    """
    cte_pallet = CTE_PPM_K.get(material_key, CTE_PPM_K["durostone"])
    pl = max(1.0, float(pallet_len_mm))
    bl = float(pcb_len_mm) if pcb_len_mm else pl * 0.92

    d_pallet = pl * cte_pallet * 1e-6 * delta_t_c
    d_pcb = bl * float(pcb_cte_ppm_k) * 1e-6 * delta_t_c
    diff = d_pallet - d_pcb

    clearance = max(0.01, float(design_clearance_mm))
    consumed = diff / clearance * 100.0

    return ExpansionGapResult(
        pallet_len_mm=round(pl, 2),
        pallet_expansion_mm=round(d_pallet, 3),
        pcb_len_mm=round(bl, 2),
        pcb_expansion_mm=round(d_pcb, 3),
        differential_mm=round(diff, 3),
        design_clearance_mm=clearance,
        clearance_consumed_pct=round(consumed, 1),
        at_risk=diff > clearance,
        material_key=material_key,
    )
