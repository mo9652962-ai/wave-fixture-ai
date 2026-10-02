"""定位销选点算法——从钻孔中打分挑选最优对角双销。

评分规则（对标竞品 test_locating_pin_selection.py 的打分体系）：
- 腰圆槽（obround 槽孔）：-10（销钉无法约束槽孔）
- 孔径 2.5–4.5mm：+4（标准定位销直径窗口）
- 孔径 > 5mm：-3（孔太大，销钉定位精度差）
- 靠边 ≤ 15mm：+3（靠近板边，便于人手对位）
- NPTH（非金属化孔）：+4（无铜环干扰，配合精度最高）——需上游传入 plated 标志
- 合格线：score ≥ 4.0（或 NPTH 且孔径 ≥ 2.0mm）
- 选点：合格候选中选**对角线距离最大**的一对（约束刚度最优）
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PinCandidate:
    x: float
    y: float
    dia: float
    score: float
    reasons: list[str]
    nthp: bool = False  # 非金属化孔（上游标注）


def score_drill(x: float, y: float, dia: float, sink_bounds: tuple,
                nthp: bool = False, is_slot: bool = False) -> PinCandidate:
    reasons: list[str] = []
    score = 0.0

    if is_slot:
        score -= 10.0
        reasons.append("腰圆槽 -10")
    if 2.5 <= dia <= 4.5:
        score += 4.0
        reasons.append("孔径 2.5-4.5 +4")
    if dia > 5.0:
        score -= 3.0
        reasons.append("孔径>5 -3")
    minx, miny, maxx, maxy = sink_bounds
    edge = min(abs(x - minx), abs(x - maxx), abs(y - miny), abs(y - maxy))
    if edge <= 15.0:
        score += 3.0
        reasons.append("靠边≤15mm +3")
    if nthp:
        score += 4.0
        reasons.append("NPTH +4")
    if dia < 2.0:
        score -= 2.0
        reasons.append("孔径<2 -2")
    return PinCandidate(x=x, y=y, dia=dia, score=round(score, 2), reasons=reasons, nthp=nthp)


def qualifies(c: PinCandidate) -> bool:
    """合格线：score ≥ 4.0，或 NPTH 且孔径 ≥ 2.0mm。"""
    return c.score >= 4.0 or (c.nthp and c.dia >= 2.0)


def select_locating_pins(drills: list[tuple[float, float, float]],
                         sink_bounds: tuple,
                         nthp_flags: list[bool] | None = None) -> list[PinCandidate]:
    """打分 → 过滤合格候选 → 选对角距离最大的一对。"""
    cands: list[PinCandidate] = []
    for i, (x, y, dia) in enumerate(drills):
        nthp = bool(nthp_flags[i]) if nthp_flags else False
        c = score_drill(x, y, dia, sink_bounds, nthp=nthp)
        if qualifies(c):
            cands.append(c)
    if len(cands) < 2:
        return cands
    best_pair, best_d = [cands[0], cands[1]], -1.0
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            d = math.hypot(cands[i].x - cands[j].x, cands[i].y - cands[j].y)
            if d > best_d:
                best_d = d
                best_pair = [cands[i], cands[j]]
    return best_pair
