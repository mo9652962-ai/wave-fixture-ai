"""自然语言参数调整测试（确定性规则解析，不用 LLM）。"""

from nl_adjust import apply_adjustments, parse_adjust_command


def _p1() -> dict:
    return {
        "sink_expand_mm": 0.2,
        "sink_fillet_r": 1.85,
        "handle_w": 20.0,
        "handle_h": 40.0,
        "handle_overlap": 1.0,
        "handle_fillet_r": 2.0,
        "screw_d": 3.4,
        "screw_offset": 10.0,
        "pin_inset": 0.1,
    }


def _p2() -> dict:
    return {
        "avoid_fillet_r": 2.0,
        "avoid_group_gap": 3.0,
        "avoid_pad_extra": 0.5,
        "solder_fillet_r": 2.0,
        "solder_min_gap": 1.0,
        "solder_tight_gap": 0.5,
        "solder_group_gap": 3.0,
        "cap_hole_r": 1.225,
        "ext_left_right": 5.0,
        "ext_top_bottom": 5.0,
        "outer_fillet_r": 5.0,
        "rail_width": 10.0,
        "tin_strip_w": 8.0,
        "tin_hole_r": 1.0,
    }


def test_parse_increase_with_number():
    r = parse_adjust_command("避位区外扩1mm", _p1(), _p2())
    assert r.matched
    assert r.param == "avoid_pad_extra"
    assert r.action == "increase"
    assert r.new_value == 1.5  # 0.5 + 1


def test_parse_set_action():
    r = parse_adjust_command("治具外形倒角改为5mm", _p1(), _p2())
    assert r.matched
    assert r.param == "outer_fillet_r"
    assert r.action == "set"
    assert r.new_value == 5.0


def test_parse_decrease_clamps_at_zero():
    p2 = _p2()
    p2["avoid_pad_extra"] = 0.3
    #「外扩」别名 +「缩小」动词 → decrease（缩小判断优先）
    r = parse_adjust_command("避位区外扩缩小1mm", _p1(), p2)
    assert r.matched and r.action == "decrease"
    assert r.new_value == 0.0  # max(0, 0.3-1)


def test_parse_prefers_decrease_over_expand():
    #「缩小」含「小」——缩小判断必须优先于「外扩」词表（同一句话同时含两者）
    r = parse_adjust_command("沉板区外扩缩小1mm", _p1(), _p2())
    assert r.matched and r.action == "decrease"


def test_apply_adjustments_multi_command_and_remap():
    p1, p2 = _p1(), _p2()
    p1["sink_expand_mm"] = 0.2
    text = "沉板区外扩0.5mm；避位区外扩2mm"
    new1, new2, reports = apply_adjustments(text, p1, p2)
    assert len(reports) == 2
    assert new1["sink_expand_mm"] == 0.7
    assert new2["avoid_pad_extra"] == 2.5


def test_apply_unmatched_text_noop():
    p1, p2 = _p1(), _p2()
    before = dict(p1)
    _n1, _n2, reports = apply_adjustments("今天天气不错", p1, p2)
    assert reports == []
    assert p1 == before
