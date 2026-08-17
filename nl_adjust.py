# -*- coding: utf-8 -*-
"""
nl_adjust — 自然语言对话调整治具参数

用户输入中文指令（如「避位区外扩1mm」「治具外形加大20mm」「沉板区倒角改2mm」）
→ 解析意图 → 调整 FixtureParams / Phase2Params → 返回调整报告

规则解析（确定性，不用 LLM——工程参数调整要精确可复现）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 参数 → 中文别名 映射
PARAM_ALIASES = {
    # 参数名 → (所属类, 别名列表)
    "sink_expand_mm": ("phase1", ["沉板区外扩", "沉板外扩", "外形外扩", "沉板区扩大"]),
    "sink_fillet_r": ("phase1", ["沉板区倒角", "清角", "沉板倒角"]),
    "handle_w": ("phase1", ["取手长", "取手位长", "取手宽"]),
    "handle_h": ("phase1", ["取手高", "取手位高", "取手宽度"]),
    "handle_overlap": ("phase1", ["取手重叠", "取手搭接"]),
    "handle_fillet_r": ("phase1", ["取手倒角"]),
    "screw_d": ("phase1", ["压扣孔直径", "螺丝孔径", "压扣孔"]),
    "screw_offset": ("phase1", ["压扣孔边距", "螺丝孔边距", "压扣孔偏移"]),
    "pin_inset": ("phase1", ["定位销内缩", "定位销偏移"]),
    "avoid_fillet_r": ("phase2", ["避位区倒角", "避位倒角"]),
    "avoid_group_gap": ("phase2", ["避位区分组", "贴片分组距离"]),
    "avoid_pad_extra": ("phase2", ["避位区外扩", "避位区扩大", "避位包围"]),
    "solder_fillet_r": ("phase2", ["上锡区倒角"]),
    "solder_min_gap": ("phase2", ["焊脚边距", "上锡区边距"]),
    "solder_tight_gap": ("phase2", ["上锡避位间距", "上锡区间距"]),
    "solder_group_gap": ("phase2", ["插件分组距离", "上锡区分组"]),
    "cap_hole_r": ("phase2", ["盖板孔径", "弹力柱孔径", "盖板孔"]),
    "ext_left_right": ("phase2", ["左右外扩", "治具左右"]),
    "ext_top_bottom": ("phase2", ["上下外扩", "治具上下"]),
    "outer_fillet_r": ("phase2", ["治具外形倒角", "外形倒角", "治具倒角"]),
    "rail_width": ("phase2", ["轨道宽", "轨道边宽"]),
    "tin_strip_w": ("phase2", ["挡锡条宽", "挡锡条"]),
    "tin_hole_r": ("phase2", ["挡锡条孔径", "挡锡条孔"]),
}


@dataclass
class AdjustResult:
    """一次调整的结果"""
    matched: bool = False
    param: str = ""
    old_value: float = 0.0
    new_value: float = 0.0
    action: str = ""          # 设为/加大/缩小/外扩
    message: str = ""
    unmatched_text: str = ""


def _extract_number(text: str) -> float | None:
    """从文本提取数值（支持 '1mm' '1.5' '20'）"""
    m = re.search(r"(\d+\.?\d*)", text)
    return float(m.group(1)) if m else None


def _extract_action(text: str) -> str:
    """判断动作类型"""
    if any(k in text for k in ["加大", "扩大", "外扩", "增加", "增大", "放大", "加宽"]):
        return "increase"
    if any(k in text for k in ["缩小", "减小", "减少", "缩小", "变窄", "调小"]):
        return "decrease"
    if any(k in text for k in ["改为", "改成", "设为", "设置为", "调整为", "调成"]):
        return "set"
    # 默认：有数字就设为
    return "set"


def parse_adjust_command(text: str, params1: dict, params2: dict) -> AdjustResult:
    """
    解析一条自然语言调整指令。

    params1/params2: 当前参数值 dict（键=参数名）
    返回 AdjustResult（含匹配的参数+新值）
    """
    result = AdjustResult(unmatched_text=text)

    for param, (cls_name, aliases) in PARAM_ALIASES.items():
        # 找别名是否出现在文本中
        matched_alias = None
        for alias in aliases:
            if alias in text:
                matched_alias = alias
                break
        if not matched_alias:
            continue

        # 当前值
        cur = (params1 if cls_name == "phase1" else params2).get(param)
        if cur is None:
            continue

        num = _extract_number(text)
        action = _extract_action(text)

        result.matched = True
        result.param = param
        result.old_value = float(cur)
        result.action = action

        if action == "set" and num is not None:
            result.new_value = num
        elif action == "increase" and num is not None:
            result.new_value = float(cur) + num
        elif action == "decrease" and num is not None:
            result.new_value = max(0.0, float(cur) - num)
        else:
            # 无法解析动作/数值
            result.new_value = float(cur)

        result.message = f"「{matched_alias}」{param}: {result.old_value} → {result.new_value}"
        return result

    return result


def apply_adjustments(text: str, params1: dict, params2: dict) -> tuple[dict, dict, list[AdjustResult]]:
    """
    解析可能含多条指令的文本（分号/换行/逗号分隔），逐条应用。
    返回 (新 params1, 新 params2, 调整报告列表)
    """
    # 按分隔符拆成多条指令
    parts = re.split(r"[;；\n。]", text)
    reports = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        r = parse_adjust_command(part, params1, params2)
        if r.matched:
            # 应用到对应 dict
            if r.param in params1:
                params1[r.param] = r.new_value
            elif r.param in params2:
                params2[r.param] = r.new_value
            reports.append(r)
    return params1, params2, reports


if __name__ == "__main__":
    # 自测
    from fixture_phase1 import FixtureParams
    from fixture_phase2 import Phase2Params
    p1 = {k: v for k, v in FixtureParams().__dict__.items()}
    p2 = {k: v for k, v in Phase2Params().__dict__.items()}

    tests = [
        "避位区外扩1mm",
        "治具外形倒角改为5mm",
        "沉板区外扩0.5mm",
        "盖板孔径改3mm",
        "左右外扩加大20mm",
    ]
    for t in tests:
        r = parse_adjust_command(t, p1, p2)
        if r.matched:
            print(f"✅ {t} → {r.message}")
        else:
            print(f"❌ {t} → 未匹配")
