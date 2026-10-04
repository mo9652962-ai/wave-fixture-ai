"""生产工单报告生成器——把治具设计结果沉淀为一份可归档/可传阅的 Markdown 工单。

工业定位：商业治具软件交付的是「图纸 + 报告」。本模块把 DXF/G 代码之外的关键信息
（材料选型、重量成本、加工估时、DRC 结论、狗骨头清单、拼版参数、干涉汇总）
汇总成单文件报告，工程师可直接发给 CAM/采购/客户。

安全：输出路径统一 resolve + 白名单后缀，限制在指定父目录内。
"""

from __future__ import annotations

import logging
import time as _time
from pathlib import Path

log = logging.getLogger("fixture-report")

ALLOWED_SUFFIXES = {".md", ".txt", ".html"}


def resolve_safe_report_path(out_path: str | Path, parent_hint: str | Path | None = None) -> Path:
    """规范化报告输出路径：绝对化 + 后缀白名单 +（提供父目录时）包含性校验。"""
    p = Path(out_path).resolve()
    if p.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"报告输出后缀须为 {sorted(ALLOWED_SUFFIXES)}，收到: {p.suffix!r}")
    if parent_hint is not None:
        base = Path(parent_hint).resolve()
        if not p.is_relative_to(base):
            raise ValueError("报告输出路径越出允许目录")
    return p


def _fmt_size(outer_poly) -> str:
    try:
        if outer_poly is None:
            return "-"
        b = outer_poly.bounds
        return f"{b[2] - b[0]:.1f} × {b[3] - b[1]:.1f}"
    except Exception:
        return "-"


def build_report(
    job_name: str,
    r1,
    r2,
    drc_verdict: dict,
    material: dict,
    weight_kg: float,
    cost: dict,
    gcode_stats: dict | None = None,
    interference_summary: dict | None = None,
    output_urls: dict | None = None,
    process_key: str = "lead_free",
    include_process: bool = True,
    machine_key: str | None = None,
) -> str:
    """构造 Markdown 生产工单。所有输入均为已算好的 dict/对象（无 IO）。"""
    from materials import get_material

    mat = get_material(material.get("key") if isinstance(material, dict) else material)
    stats = getattr(r2, "panel_grid", None)
    drc_counts = drc_verdict.get("counts", {})
    drc_ok = drc_verdict.get("allowed", False)

    # 真机画像（可选）：机台行进入规格表与工艺章节
    machine = None
    if machine_key:
        from equipment import get_machine

        machine = get_machine(machine_key)

    # 动态章节编号（CNC 节与工艺节按可用性增减）
    sec = {"spec": 1, "mat": 2, "cnc": 3, "drc": 4, "interf": 5, "proc": 6, "dl": 7}
    if not gcode_stats:
        sec = {k: (v - 1 if v >= 3 else v) for k, v in sec.items()}
    if not include_process:
        sec = {k: (v - 1 if v >= 6 else v) for k, v in sec.items()}

    L: list[str] = []
    ap = L.append
    ap(f"# 波峰焊治具生产工单 · {job_name}")
    ap("")
    ap(f"> 生成时间：{_time.strftime('%Y-%m-%d %H:%M:%S')}  ")
    ap(f"> DRC 门禁：{'✅ 通过（可生产）' if drc_ok else '⛔ 未通过（仅预览版）'}  ")
    ap(f"> 材料方案：**{mat.name_cn}**（{mat.name_en}），厚度 {material.get('thickness', '-')}mm")
    ap("")

    ap(f"## {sec['spec']}. 治具规格")
    ap("")
    ap("| 项目 | 数值 |")
    ap("|---|---|")
    ap(f"| 治具外形 | {_fmt_size(getattr(r2, 'outer_poly', None))} mm |")
    ap(f"| 沉板槽深 | {material.get('board_pocket_depth', '-')} mm |")
    if material.get("sink_depth"):
        sd = material["sink_depth"]
        ap(
            f"| 沉板深度依据 | {'底面最高元件 ' + str(sd.get('max_bottom_standoff_mm')) + 'mm（' + ','.join(sd.get('bottom_components', [])[:3]) + '）+ 0.5mm 离板气隙' if sd.get('has_bottom_components') else '无底面元件——板底留 0.5mm 气隙'} · 出处: {sd.get('rule_source', '-')} |"
        )
    if stats:
        ap(
            f"| 拼版阵列 | {stats.get('cols', 1)} × {stats.get('rows', 1)}（间距 {stats.get('gap', 0)}mm，共 {stats.get('copies', 1)} 片）|"
        )
        ap(
            f"| 板阵列占位 | {stats.get('total', ['-', '-'])[0]} × {stats.get('total', ['-', '-'])[1]} mm（不含治具边框）|"
        )
    ap(f"| 避位区 | {len(getattr(r2, 'avoid_polys', []) or [])} 处 |")
    if machine:
        official = "" if machine.official else "（行业常见值，以随机手册为准）"
        ap(
            f"| 目标机台 | **{machine.name_cn}**（{machine.vendor} {machine.model}）· "
            f"轨距 ≤{machine.process_width_max_mm:.0f}mm · 传送链载荷 {machine.conveyor_load_kg}kg{official} |"
        )
    ap(f"| 上锡区 | {len(getattr(r2, 'solder_polys', []) or [])} 处 |")
    ap(f"| 盖板孔 | {len(getattr(r2, 'cap_holes', []) or [])} 个 |")
    ap(f"| 定位销 | {len(getattr(r1, 'pins', []) or [])} 个 |")
    ap(f"| 压扣孔 | {len(getattr(r1, 'screws', []) or [])} 个 |")
    ap(
        f"| 狗骨头清角 | {len(getattr(r1, 'dogbone_corners', []) or getattr(r2, 'dogbone_corners', []) or [])} 处 |"
    )
    ap("")

    ap(f"## {sec['mat']}. 材料与成本")
    ap("")
    ap("| 项目 | 数值 |")
    ap("|---|---|")
    ap(f"| 材料 | {mat.name_cn}（{mat.color}{'，ESD 静电耗散' if mat.esd_safe else ''}）|")
    ap(f"| 密度 | {mat.density_g_cm3} g/cm³ |")
    ap(f"| 耐温上限 | {mat.max_service_temp_c} °C |")
    ap(f"| 常规板厚档位 | {'/'.join(str(t) for t in mat.thickness_options_mm)} mm |")
    ap(f"| 毛坯估算重量 | **{weight_kg} kg** |")
    ap(f"| 材料费估算 | {cost.get('material_cost', '-')} {cost.get('currency', 'CNY')} |")
    if gcode_stats:
        ap(f"| 加工估时 | {gcode_stats.get('machining_minutes', '-')} min |")
        ap(f"| 机加工费估算 | {cost.get('machining_cost', '-')} {cost.get('currency', 'CNY')} |")
    ap(f"| 合计估算 | **{cost.get('total', '-')} {cost.get('currency', 'CNY')}** |")
    ap("")
    ap(f"<sub>{cost.get('note', '')} 数据出处：{mat.source}</sub>")
    ap("")

    if gcode_stats:
        ap(f"## {sec['cnc']}. CNC 加工程序")
        ap("")
        ap("| 项目 | 数值 |")
        ap("|---|---|")
        tools_str = "、".join(
            f"T{t['number']} D{t['dia_mm']}mm" for t in gcode_stats.get("tools", [])
        )
        ap(f"| 刀具组 | {len(gcode_stats.get('tools', []))} 组（{tools_str}）|")
        ap(f"| 挖腔操作 | {gcode_stats.get('pocket_ops', '-')} 环 |")
        ap(f"| 外形落料 | {gcode_stats.get('profile_passes', '-')} 层 |")
        ap(f"| 切削路径 | {gcode_stats.get('cut_len_mm', '-')} mm |")
        ap(f"| 程序行数 | {gcode_stats.get('line_count', '-')} |")
        ap("")

    ap(f"## {sec['drc']}. DRC 生产门禁结论")
    ap("")
    ap(
        f"- blocking: **{drc_counts.get('blocking', 0)}** · error: **{drc_counts.get('error', 0)}** "
        f"· warning: {drc_counts.get('warning', 0)} · info: {drc_counts.get('info', 0)}"
    )
    ap(
        f"- 结论：{'✅ 允许生产（DXF 无水印）' if drc_ok else '⛔ 不允许生产——仅提供带水印预览版，修正后重新生成'}"
    )
    ap("")

    if interference_summary:
        ap(f"## {sec['interf']}. 元件干涉分析")
        ap("")
        ap(f"- 分析元件：{interference_summary.get('component_count', '-')} 个")
        ap(f"- 实体干涉：{interference_summary.get('interference_count', 0)} 处")
        susp = interference_summary.get("suspicious") or []
        if susp:
            ap(f"- 高度可疑：{len(susp)} 个（顶部 5）")
            ap("")
            ap("| 位号 | 高度 | 原因 |")
            ap("|---|---|---|")
            for s in susp[:5]:
                ap(
                    f"| {s.get('ref', '?')} | {s.get('height', '-')}mm | {s.get('suspicious_reason', '-')} |"
                )
        ap("")

    # 波峰焊工艺窗口（作业指导书章节）
    if include_process:
        from process import material_process_compat, process_section_markdown

        proc_name = "有铅" if process_key == "leaded" else "无铅"
        ap(f"## {sec['proc']}. 波峰焊工艺窗口（{proc_name}参考）")
        ap("")
        ap(process_section_markdown(process_key))
        ok, note = material_process_compat(mat.max_service_temp_c)
        ap(f"- **材料-工艺兼容性**：{'✅ ' if ok else '⚠️ '}{note}")
        ap("")

    urls = output_urls or {}
    ap(f"## {sec['dl']}. 交付物清单")
    ap("")
    urls = output_urls or {}
    if urls:
        for k, v in urls.items():
            ap(f"- {k}: {v}")
    else:
        ap("- DXF / PNG / STL / GLB / G 代码（.nc）/ 本报告")
    ap("")
    ap("---")
    ap(
        "<sub>由 wave-fixture-ai 自动生成 · DRC 规则与材料数据出处见 drc.py / materials.py 头注</sub>"
    )
    ap("")
    return "\n".join(L)


def write_report(out_path: str | Path, content: str, parent_hint: str | Path | None = None) -> str:
    """写报告文件（路径安全校验）。返回实际路径字符串。"""
    p = resolve_safe_report_path(out_path, parent_hint)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    log.info(f"  生产报告已生成: {p}")
    return str(p)
