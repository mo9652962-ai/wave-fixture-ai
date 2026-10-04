"""波峰焊真机档案库——把"已投入使用的设备"规格固化为可校验的机台画像。

工业定位（对标商业治具软件的 Machine Library）：治具不是在真空里生产——
它必须放进某台具体的波峰焊机里过波。机台画像约束三件事：
  1. 轨距（process width）：治具短边必须放得进前后导轨之间
  2. 载荷（conveyor load）：治具+PCB 总重不得超过传送链承载
  3. 传送高度（SMEMA/IPC-9851）：治具垫高 PCB 后，板底高度须兼容上下游设备

数据出处（每台带来源；官方数据优先，行业常见值显式标注）：
- Electrovert VectraES/VectraElite/Electra：ITW EAE 官方 datasheet
  （VectraES conveyor max load 50lb=22.7kg；VectraElite process width 457mm
  标配/508mm 选配、Heavy Duty Conveyor 91kg；Electra process width 610mm、
  HD conveyor 91kg / 标准载荷 100lb=43.4kg）
- 传送高度：IPC-SMEMA-9851（SMEMA 1.2 后继标准）——输送高度 940-965mm
  （37-38in），前轨固定、后轨调宽
- 劲拓（国产主流）官方参数表未公开索引：按行业常见区间标注"以随机手册为准"
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

log = logging.getLogger("fixture-equipment")

# IPC-SMEMA-9851 传送高度窗口（floor → PCB 底面）
SMEMA_HEIGHT_MM = (940.0, 965.0)
SMEMA_RAIL_NOTE = "前轨固定，后轨调宽（IPC-SMEMA-9851 §2.2）"


@dataclass
class MachineProfile:
    """单一波峰焊机台画像。"""

    key: str
    vendor: str
    model: str
    name_cn: str
    process_width_min_mm: float  # 轨距下限
    process_width_max_mm: float  # 轨距上限（治具短边必须 ≤ 上限）
    conveyor_load_kg: float  # 传送链最大均布载荷
    conveyor_height_mm: tuple = SMEMA_HEIGHT_MM  # SMEMA/IPC-9851 窗口
    rail_arrangement: str = SMEMA_RAIL_NOTE
    official: bool = True  # False = 行业常见值，未经官方手册核实
    source: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["conveyor_height_mm"] = list(self.conveyor_height_mm)
        return d


MACHINES: dict[str, MachineProfile] = {
    "electrovert_vectra_es": MachineProfile(
        key="electrovert_vectra_es",
        vendor="Electrovert (ITW EAE)",
        model="VectraES",
        name_cn="Electrovert VectraES",
        process_width_min_mm=50.0,
        process_width_max_mm=400.0,
        conveyor_load_kg=22.7,  # 50 lb 官方 datasheet
        official=True,
        source="ITW EAE VectraES Wave Soldering Machine datasheet",
        note="低中量产线主力机型；厚板+治具重量为设计考量点（官方原文）。",
    ),
    "electrovert_vectra_elite": MachineProfile(
        key="electrovert_vectra_elite",
        vendor="Electrovert (ITW EAE)",
        model="VectraElite",
        name_cn="Electrovert VectraElite",
        process_width_min_mm=50.0,
        process_width_max_mm=457.0,  # 18in 标配（508mm 选配）
        conveyor_load_kg=91.0,  # Heavy Duty Conveyor 官方 datasheet
        official=True,
        source="ITW EAE VectraElite Wave Soldering Machine datasheet",
        note="457mm 标配/508mm 选配；91kg 为 Heavy Duty Conveyor 选配值。",
    ),
    "electrovert_electra": MachineProfile(
        key="electrovert_electra",
        vendor="Electrovert (ITW EAE)",
        model="Electra",
        name_cn="Electrovert Electra",
        process_width_min_mm=50.0,
        process_width_max_mm=610.0,  # 24in 官方 datasheet
        conveyor_load_kg=43.4,  # 100lb 标准均布（HD 选配 91kg）
        official=True,
        source="ITW EAE Electra Wave Soldering Machine datasheet",
        note="大板幅机型；Heavy Duty 选配可达 91kg。",
    ),
    "jt_350": MachineProfile(
        key="jt_350",
        vendor="劲拓自动化",
        model="JT-350 系",
        name_cn="劲拓 350 波峰焊",
        process_width_min_mm=50.0,
        process_width_max_mm=450.0,
        conveyor_load_kg=10.0,
        official=False,
        source="行业常见规格区间（官方手册未公开索引）",
        note="国产主流机型；轨距与载荷按行业常见值，投产前以随机手册核对。",
    ),
    "generic_350": MachineProfile(
        key="generic_350",
        vendor="—",
        model="Generic 350",
        name_cn="通用 350mm 轨距",
        process_width_min_mm=50.0,
        process_width_max_mm=350.0,
        conveyor_load_kg=10.0,
        official=False,
        source="保守缺省（对应 drc.py RAIL_MAX_MM 历史缺省）",
        note="未指明机台时的保守缺省画像。",
    ),
}

DEFAULT_MACHINE = "generic_350"


def get_machine(key: str | None) -> MachineProfile:
    """按 key 取机台画像；缺省/未知回退 generic_350（不抛异常）。"""
    if not key:
        return MACHINES[DEFAULT_MACHINE]
    m = MACHINES.get(key.lower().strip())
    if m is None:
        log.warning(f"  未知机台 '{key}'，回退 {DEFAULT_MACHINE}")
        return MACHINES[DEFAULT_MACHINE]
    return m


if __name__ == "__main__":
    for k, m in MACHINES.items():
        print(
            f"{k:26s} {m.name_cn:22s} 轨距≤{m.process_width_max_mm}mm "
            f"载荷{m.conveyor_load_kg}kg official={m.official}"
        )
