"""波峰焊工艺窗口参考库——让生产工单成为真正的作业指导书。

工艺参数出处（每项带来源，均为行业公开推荐窗口）：
- Yint Electronic《Recommended wave soldering parameters》：
  有铅 Sn63Pb37 锡炉 260°C±5°C、预热 100-130°C、接触 2-5s；峰值引脚温度 ≤260°C 超 10s
- Kester 助焊剂规格书（NF1060-VF）：板底预热温度上限、接触时间指南
- Highqualitypcb《Wave Soldering Temperature Profile》：无铅峰值 255-265°C、预热 90-120°C
- D. Shangguan（EPP Europe）：无铅锡炉 255-265°C
- 行业共识：无铅接触时间 4-8s；升温斜率 1-3°C/s；预热 80-150s

工业交叉校验（drc.py MATERIAL_TEMP_WINDOW 使用）：
治具底部直接接触波峰焊料，材料长期使用温度必须 ≥ 波峰温度——
Durostone/Ricocel（280°C）满足无铅波峰（265°C 峰值）；高 Tg FR-4（180°C）不满足，
选型时必须警告（这也是行业选合成石不选 FR-4 做双波治具的核心原因）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ProcessWindow:
    """单一焊料类型的波峰焊工艺窗口。"""

    key: str  # "leaded" | "lead_free"
    name_cn: str
    solder_alloy: str  # 合金
    pot_temp_c: tuple[float, float]  # 锡炉温度窗口
    preheat_top_c: tuple[float, float]  # 预热（板面/板底）温度窗口
    preheat_time_s: tuple[float, float]
    dwell_time_s: tuple[float, float]  # 波峰接触时间
    ramp_c_per_s: tuple[float, float]  # 升温斜率
    peak_limit_c: float  # 峰值引脚温度上限
    peak_limit_duration_s: float  # 峰值允许时长
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


PROCESS_WINDOWS: dict[str, ProcessWindow] = {
    "leaded": ProcessWindow(
        key="leaded",
        name_cn="有铅波峰焊（Sn63Pb37）",
        solder_alloy="Sn63/Pb37",
        pot_temp_c=(255.0, 265.0),  # 260 ±5
        preheat_top_c=(100.0, 130.0),
        preheat_time_s=(80.0, 150.0),
        dwell_time_s=(2.0, 5.0),
        ramp_c_per_s=(1.0, 3.0),
        peak_limit_c=260.0,
        peak_limit_duration_s=10.0,
        source="Yint Electronic《Recommended wave soldering parameters》",
    ),
    "lead_free": ProcessWindow(
        key="lead_free",
        name_cn="无铅波峰焊（SAC305）",
        solder_alloy="SAC305 (Sn96.5/Ag3.0/Cu0.5)",
        pot_temp_c=(255.0, 265.0),
        preheat_top_c=(90.0, 120.0),
        preheat_time_s=(80.0, 150.0),
        dwell_time_s=(4.0, 8.0),
        ramp_c_per_s=(1.0, 3.0),
        peak_limit_c=260.0,
        peak_limit_duration_s=10.0,
        source="Highqualitypcb 波峰焊温度剖面 + D. Shangguan (EPP Europe)",
    ),
}

# 无铅波峰温度下限（材料耐温交叉校验阈值）
LEAD_FREE_POT_MIN_C = 255.0


def get_process(key: str | None = "lead_free") -> ProcessWindow:
    """按 key 取工艺窗口；缺省无铅（当前行业主流）。未知回退无铅。"""
    if not key:
        return PROCESS_WINDOWS["lead_free"]
    p = PROCESS_WINDOWS.get(key.lower().strip())
    if p is None:
        return PROCESS_WINDOWS["lead_free"]
    return p


def material_process_compat(material_max_temp_c: float) -> tuple[bool, str]:
    """材料耐温 vs 无铅波峰温度交叉校验。

    返回 (兼容?, 说明)。治具底面直接接触波峰焊料，
    材料长期使用温度须 ≥ 无铅波峰下限 255°C。
    """
    if material_max_temp_c >= LEAD_FREE_POT_MIN_C:
        return True, (
            f"材料耐温 {material_max_temp_c:.0f}°C ≥ 无铅波峰下限 "
            f"{LEAD_FREE_POT_MIN_C:.0f}°C，兼容有铅/无铅双工艺"
        )
    return False, (
        f"材料耐温 {material_max_temp_c:.0f}°C < 无铅波峰下限 "
        f"{LEAD_FREE_POT_MIN_C:.0f}°C——仅适用于有铅工艺（260°C 短时接触需工艺验证），"
        "无铅产线请改用 Durostone/Ricocel 合成石"
    )


def process_section_markdown(process_key: str = "lead_free") -> str:
    """生产工单「波峰焊工艺窗口」章节（Markdown 表格）。"""
    p = get_process(process_key)
    L = [
        f"### {p.name_cn}（{p.solder_alloy}）",
        "",
        "| 参数 | 推荐窗口 |",
        "|---|---|",
        f"| 锡炉温度 | {p.pot_temp_c[0]:.0f} – {p.pot_temp_c[1]:.0f} °C |",
        f"| 预热温度（板面） | {p.preheat_top_c[0]:.0f} – {p.preheat_top_c[1]:.0f} °C |",
        f"| 预热时间 | {p.preheat_time_s[0]:.0f} – {p.preheat_time_s[1]:.0f} s |",
        f"| 升温斜率 | {p.ramp_c_per_s[0]:.0f} – {p.ramp_c_per_s[1]:.0f} °C/s |",
        f"| 波峰接触时间 | {p.dwell_time_s[0]:.0f} – {p.dwell_time_s[1]:.0f} s |",
        f"| 峰值引脚温度 | ≤ {p.peak_limit_c:.0f} °C（不超过 {p.peak_limit_duration_s:.0f} s） |",
        "",
        f"<sub>治具会吸热并遮挡预热——量产前须**带治具实测**板顶温度曲线并按需调 profile。出处：{p.source}</sub>",
        "",
    ]
    return "\n".join(L)


if __name__ == "__main__":
    for k, w in PROCESS_WINDOWS.items():
        print(k, w.name_cn, w.pot_temp_c, w.dwell_time_s)
    print(material_process_compat(280.0))
    print(material_process_compat(180.0))
