"""治具出厂检验 AQL 抽样与放行单生成 (Outgoing QC AQL Sampling & Release Note).

工业背景与检验基准：
- ISO 2859-1 / GB/T 2828.1《计数抽样检验程序》：批量交付治具按
  **一般检验水平 II、正常检验一次抽样**执行：
  1. 批量 → 样本量字码 (A~Q) → 样本量阶梯 {2,3,5,8,13,20,32,50,80,125,200,315,500,800,1250}；
  2. 接受判定采用工程惯用的 **Ac=2 锚点法**：取使 AQL% × n ≥ 1.25 的最小样本量 → Ac=2 / Re=3
     （经典配对：AQL 1.0 → n=125、AQL 2.5 → n=50、AQL 4.0 → n=32、AQL 0.65 → n=200）；
     阶梯内无满足锚点的样本量时退化为全检 (n=批量) Ac=0 / Re=1；
  3. 出厂检验项：外形尺寸 (±0.1mm)、密封面平面度 (≤0.2mm)、嵌件拉拔力 (≥100N)、
     ESD 表面阻抗 (10⁶~10⁹Ω)、标识完整 (MES 条码/方向键)、五金扭矩 (M3 0.6 N·m)。
- 放行单 (Release Note) 随货同行：批次/数量/抽样方案/检验项记录/签署栏，绑定 IATF 16949 出厂放行流程。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# 样本量阶梯 (ISO 2859-1 一般检验水平 II)
SAMPLE_LADDER = (2, 3, 5, 8, 13, 20, 32, 50, 80, 125, 200, 315, 500, 800, 1250)

# 批量 → 字码 (Level II)：上界含
LOT_CODE_TABLE: tuple[tuple[int, str], ...] = (
    (8, "A"), (15, "B"), (25, "C"), (50, "D"), (90, "E"), (150, "F"),
    (280, "G"), (500, "H"), (1200, "J"), (3200, "K"), (10000, "L"),
    (35000, "M"), (150000, "N"), (500000, "P"),
)


@dataclass
class AQLPlan:
    lot_size: int
    code_letter: str
    sample_size: int
    accept_number: int  # Ac
    reject_number: int  # Re = Ac + 1
    aql_pct: float
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutgoingQCReport:
    job_name: str
    lot_size: int
    aql_plan: AQLPlan
    checklist: list[dict[str, str]] = field(default_factory=list)
    markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_name": self.job_name,
            "lot_size": self.lot_size,
            "aql_plan": self.aql_plan.to_dict(),
            "checklist": self.checklist,
        }


def plan_aql_sampling(lot_size: int, aql_pct: float = 2.5) -> AQLPlan:
    """ISO 2859-1 Level II 一次抽样：Ac=2 锚点法 (AQL% × n ≥ 1.25 的最小样本量)。"""
    lot = max(1, int(lot_size))
    aql = max(0.01, float(aql_pct))

    code = "Q"
    for upper, letter in LOT_CODE_TABLE:
        if lot <= upper:
            code = letter
            break

    # Ac=2 锚点：阶梯内最小 n 使 AQL% × n ≥ 1.25
    # (经典配对: AQL 1.0→n125 / 2.5→n50 / 4.0→n32 / 0.65→n200, 均为 Ac 2 Re 3)
    for n in SAMPLE_LADDER:
        if aql / 100.0 * n >= 1.25:
            return AQLPlan(
                lot_size=lot, code_letter=code, sample_size=min(n, lot),
                accept_number=2, reject_number=3, aql_pct=aql,
                method=f"ISO 2859-1 Level II 一次正常抽样, Ac=2 锚点 (AQL {aql:g}% → n={min(n, lot)})",
            )
    # 阶梯耗尽仍不满足 → 全检
    return AQLPlan(
        lot_size=lot, code_letter=code, sample_size=lot,
        accept_number=0, reject_number=1, aql_pct=aql,
        method=f"ISO 2859-1 Level II 一次正常抽样, 全检 Ac=0/Re=1 (AQL {aql:g}% 锚点超出阶梯)",
    )


def generate_outgoing_qc_report(
    job_name: str = "FIXTURE",
    lot_size: int = 1,
    aql_pct: float = 2.5,
    material_name: str = "Durostone 合成石",
) -> OutgoingQCReport:
    """生成出厂检验抽样方案 + 检验项清单 + 放行单 (Markdown)。"""
    plan = plan_aql_sampling(lot_size, aql_pct)

    checklist = [
        {"item": "外形尺寸 (W×H×T)", "spec": "±0.1mm", "method": "游标卡尺/三坐标"},
        {"item": "密封面平面度", "spec": "≤0.2mm", "method": "大理石平台+塞尺"},
        {"item": "嵌件拉拔力", "spec": "≥100N", "method": "推拉力计"},
        {"item": "ESD 表面阻抗", "spec": "10⁶~10⁹ Ω", "method": "表面阻抗测试仪"},
        {"item": "标识完整 (MES 条码/方向键)", "spec": "无缺损/方向唯一", "method": "目视 + 扫码验证"},
        {"item": "五金锁紧扭矩", "spec": "M3 0.6 N·m / M4 1.2 N·m", "method": "扭矩扳手"},
        {"item": "开孔壁无挂锡毛刺", "spec": "无毛刺/崩缺", "method": "10x 放大镜"},
    ]

    md = [
        f"# 治具出厂检验放行单 — {job_name}",
        "",
        f"- **材料**: {material_name} · **批量**: {plan.lot_size} 件",
        f"- **抽样方案**: {plan.method}",
        f"- **样本量**: {plan.sample_size} 件 · **接受/拒收**: Ac={plan.accept_number} / Re={plan.reject_number}",
        "- **判定规则**: 样本中不合格数 ≤ Ac 放行整批；≥ Re 整批退回返修并加严检验",
        "",
        "| 检验项 | 规格限 | 检验方法 | 实测 | 判定 |",
        "|:---|:---|:---|:---|:---|",
    ]
    for c in checklist:
        md.append(f"| {c['item']} | {c['spec']} | {c['method']} | ______ | ☐合格 ☐不合格 |")

    md += [
        "",
        "| 签署 | 姓名 | 日期 |",
        "|:---|:---|:---|",
        "| 检验员 | ________ | ________ |",
        "| QA 放行 | ________ | ________ |",
    ]

    return OutgoingQCReport(
        job_name=job_name,
        lot_size=plan.lot_size,
        aql_plan=plan,
        checklist=checklist,
        markdown="\n".join(md),
    )
