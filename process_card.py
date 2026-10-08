"""波峰焊工装首件检验卡 (First Article Inspection Checklist, FAI) 与工艺指导卡引擎。

工业权威依据：
- IATF 16949 / ISO 9001 质量管理体系：工装夹具投入批量生产前，必须完成首件检验 (FAI)
  并签署受控检验卡，包含机械装配公差检验、运动部件阻尼、接触绝缘与首件过炉焊接质量。
- IPC-A-610G 电子组件可接受性标准：首件焊接透锡率 (PTH 垂直填充率 ≥75% Class 2 / ≥100% Class 3)、
  润湿角 (<90°)、桥连短路与锡珠飞溅评估。
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger("fixture-process-card")


@dataclass
class FAIChecklistItem:
    """单个首件检验项目。"""

    index: int
    category: str  # "机械尺寸" | "装配功能" | "过炉工艺" | "焊接质量"
    check_item: str  # 检验项目名
    specification: str  # 标准技术规范要求
    tool_required: str  # 所需量具/工具 (如塞尺/扭力计/通止规/金相显微镜)
    critical_level: str  # "CRITICAL" | "MAJOR" | "MINOR"
    acceptance: str  # 判定基准 (Pass/Fail)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


STANDARD_FAI_ITEMS: list[FAIChecklistItem] = [
    FAIChecklistItem(
        index=1,
        category="机械尺寸",
        check_item="沉板贴合间隙 (Pocket Gap)",
        specification="PCB 放入沉板槽后，四周侧壁间隙 0.2±0.05mm；底面无悬空翘曲，塞尺测缝 ≤ 0.15mm",
        tool_required="厚薄塞尺 (Feeler Gauge 0.15mm)",
        critical_level="CRITICAL",
        acceptance="塞尺无法穿入沉板配合底面",
    ),
    FAIChecklistItem(
        index=2,
        category="装配功能",
        check_item="阶梯定位销通止配合 (Guide Pin Fitting)",
        specification="定位销与 PCB 定位孔滑动配合良好，无卡滞、无毛刺划伤基板孔壁",
        tool_required="销式通止规 / 手感检验",
        critical_level="CRITICAL",
        acceptance="轻推即入，晃动量 ≤ 0.08mm",
    ),
    FAIChecklistItem(
        index=3,
        category="装配功能",
        check_item="旋转压扣扭力与锁合 (Turn Clamp Torque)",
        specification="压扣顺时针旋转压平 PCB 板边，转动阻尼适中无松脱滑丝，下压力约 3~5N",
        tool_required="扭力螺丝刀 (0.3 N·m)",
        critical_level="MAJOR",
        acceptance="板边完全贴伏槽底，过炉振动不脱落",
    ),
    FAIChecklistItem(
        index=4,
        category="机械尺寸",
        check_item="金手指防爬锡密封 (Gold Finger Seal)",
        specification="特氟龙压条严密覆压金手指接触面，与沉板边缘台阶贴合紧密无透光缝隙",
        tool_required="强光透光目测",
        critical_level="CRITICAL",
        acceptance="无任何透光间隙，完全阻断毛细爬锡",
    ),
    FAIChecklistItem(
        index=5,
        category="机械尺寸",
        check_item="闭合腔排气通孔畅通度 (Vent Hole)",
        specification="Φ2.0mm 顶面贯穿排气孔无 CNC 切削毛刺堵塞，气流通畅",
        tool_required="Φ1.8mm 通条 / 气枪吹气",
        critical_level="MAJOR",
        acceptance="孔眼全数通畅透亮",
    ),
    FAIChecklistItem(
        index=6,
        category="机械尺寸",
        check_item="导流斜面与内角清角 (Chamfer & Dogbone)",
        specification="上锡开口 60°/45° 导流斜面平滑无台阶接刀痕；内凹拐角清角无残料",
        tool_required="10倍放大镜目视",
        critical_level="MAJOR",
        acceptance="斜面过渡均匀平滑",
    ),
    FAIChecklistItem(
        index=7,
        category="装配功能",
        check_item="传送带平行度与走板顺畅 (Conveyor Transit)",
        specification="治具外边框两导轨边平行度偏差 ≤ 0.2mm，进出波峰焊轨道平稳顺畅无卡轨",
        tool_required="游标卡尺 / 产线轨道试走",
        critical_level="CRITICAL",
        acceptance="轨道平滑滑行无卡顿",
    ),
    FAIChecklistItem(
        index=8,
        category="过炉工艺",
        check_item="吃锡深度基准调校 (Solder Wave Depth)",
        specification="波峰压锡深度为治具底面向上接触 PCB 板厚的 1/3 ~ 1/2 (约 0.5~0.8mm)",
        tool_required="感温试纸 / 钢皮尺",
        critical_level="CRITICAL",
        acceptance="锡波平稳浸润焊盘引脚，无翻锡溢入板面",
    ),
    FAIChecklistItem(
        index=9,
        category="焊接质量",
        check_item="通孔引脚垂直透锡率 (Through-hole Fill)",
        specification="符合 IPC-A-610G Class 2 (≥75% 焊料填充满) 或 Class 3 (100% 满充)",
        tool_required="目视显微镜 (20x) / X-ray 抽检",
        critical_level="CRITICAL",
        acceptance="顶部焊环润湿角完整且透锡率达标",
    ),
    FAIChecklistItem(
        index=10,
        category="焊接质量",
        check_item="连锡与锡珠缺陷筛查 (Bridging & Solder Ball)",
        specification="细间距排针与相邻贴片焊盘 100% 无桥连拉丝短路、无散落锡珠",
        tool_required="显微镜全检",
        critical_level="CRITICAL",
        acceptance="0 连锡，0 飞溅锡珠",
    ),
]


def generate_process_card_markdown(
    job_name: str,
    pallet_size_str: str = "120.0×100.0mm",
    material_name: str = "Durostone 合成石 10mm",
    machine_name: str = "通用 350mm 轨距",
    target_alloy: str = "无铅 SAC305 (260°C)",
    fasteners_count: dict[str, int] | None = None,
) -> str:
    """生成符合 ISO 9001 / IATF 16949 规范的工装首件检验与工艺指导卡片 (Markdown)。"""
    fc = fasteners_count or {}
    L = [
        "# 波峰焊工装首件检验卡 (FAI Checklist) 与工艺指导卡",
        f"> 受控单号：`FAI-{job_name[:18].upper()}` | 状态：**待首件签核 (Pending Sign-off)**",
        f"> 生成时间：{_time.strftime('%Y-%m-%d %H:%M:%S')} | 体系标准：**IATF 16949 / ISO 9001 / IPC-A-610G**",
        "",
        "## 一、工装与机台受控参数表",
        "",
        "| 参数项目 | 受控规格设定 | 检验/执行标准 |",
        "|---|---|---|",
        f"| 工装治具编号 | **{job_name}** | 治具激光打标/机械刻字对齐 |",
        f"| 治具外形尺寸 | **{pallet_size_str}** | 轨道行进方向对齐 'FLOW ===>' 箭头 |",
        f"| 治具基体材质 | **{material_name}** | 耐温 ≥ 280°C，表面阻抗 ESD 静电耗散 |",
        f"| 匹配波峰焊机台 | **{machine_name}** | 导轨开合宽度与爪链间隙匹配 |",
        f"| 焊料合金与锡温 | **{target_alloy}** | 锡锅实测温度 260.0 ± 3.0 °C |",
        f"| 标准五金配置 | 压扣×{fc.get('clamps', 4)}，定位销×{fc.get('pins', 2)}，挡锡条×{fc.get('dams', 2)} | 紧固件 100% 完整无缺失 |",
        "",
        "## 二、首件检验 10 大准则 (First Article Inspection)",
        "",
        "| 序号 | 检验类别 | 检验项目 | 质量技术标准 | 检验量具 | 严重级别 | 判定 | 签核 |",
        "|---|---|---|---|---|---|:---:|:---:|",
    ]

    for item in STANDARD_FAI_ITEMS:
        L.append(
            f"| {item.index} | {item.category} | **{item.check_item}** | {item.specification} | "
            f"{item.tool_required} | `{item.critical_level}` | [ ] Pass | ____ |"
        )

    L.extend(
        [
            "",
            "## 三、批量生产放行签字栏",
            "",
            "| 岗位责任人 | 判定结论 | 签字 / 工号 | 签核日期与时间 |",
            "|---|---|---|---|",
            "| **治具制作/CAM 工程师** | 尺寸符合图纸，G 代码首件校验通过 | ________________ | ______________ |",
            "| **SMT/波峰焊工艺工程师** | 预热曲线与吃锡深度首检合格 | ________________ | ______________ |",
            "| **IPQC 质检巡检员** | IPC-A-610 Class 3 首检合格，允许批量过炉 | ________________ | ______________ |",
            "",
            "---",
            "<sub>注：本卡为质量受控文件，首检不合格时严禁批量开线。每批次试机板必须留样归档。</sub>",
        ]
    )

    return "\n".join(L) + "\n"
