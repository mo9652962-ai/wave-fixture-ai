"""人工 Review 闭环——低置信度/缺数据挂起 → 工程师确认 → 持久化。

对标竞品 review 流程：
- 缺数据（无贴片层 / 无通孔 / 无钻孔）→ 挂起 mandatory review，不自动猜
- 工程师确认后写入 layer_mapping.json（绑定 geometry SHA + 操作人 + 时间戳）
- pending 的 mandatory review 会阻断生产放行（与 DRC 门禁串联）
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

MANDATORY_TYPES = ("NO_SMD_CONFIRM", "NO_PTH_CONFIRM", "NO_DRILLS_CONFIRM", "LOW_CONFIDENCE_LAYER")


@dataclass
class ReviewItem:
    id: str                 # review-<sha8>-<type>
    type: str               # MANDATORY_TYPES 之一
    reason: str
    status: str = "pending"  # pending / confirmed
    operator: str | None = None
    confirmed_at: str | None = None
    answer: str | None = None  # 工程师的确认结论（如「确认无贴片」）


def geometry_sha(r1, r2) -> str:
    """几何指纹——几何一变，已确认的 review 自动过期。"""
    payload = json.dumps({
        "board": getattr(r1, "board_poly", None).wkt if getattr(r1, "board_poly", None) is not None else None,
        "sink": getattr(r1, "sink_poly", None).wkt if getattr(r1, "sink_poly", None) is not None else None,
        "outer": getattr(r2, "outer_poly", None).wkt if getattr(r2, "outer_poly", None) is not None else None,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def collect_review_items(parsed: dict, r1, r2) -> list[dict]:
    """根据解析摘要收集需要人工确认的 review 项。

    parsed: {"has_bottom_mask": bool, "has_top_mask": bool, "has_drills": bool,
             "board_polys": int, "layer_count": int, "parse_confidence": "high"|"low"}
    规则（不自动猜）：
    - 无 BOT mask → NO_SMD_CONFIRM（确认这块板真的无贴片）
    - 无 PTH/插件焊脚 → NO_PTH_CONFIRM（确认无通孔插件）
    - 无钻孔 → NO_DRILLS_CONFIRM（确认无定位孔）
    - 解析置信度低 → LOW_CONFIDENCE_LAYER（层名是猜的）
    """
    sha = geometry_sha(r1, r2)[:8]
    items: list[ReviewItem] = []

    def _add(t: str, reason: str, answer: str | None = None) -> None:
        items.append(ReviewItem(id=f"review-{sha}-{t.lower()}", type=t, reason=reason, answer=answer))

    if not parsed.get("has_bottom_mask", False):
        _add("NO_SMD_CONFIRM", "未识别到 BOT mask 层——请确认该板无底面贴片元件")
    if not parsed.get("has_top_mask", False):
        _add("NO_PTH_CONFIRM", "未识别到 TOP 层——请确认该板无顶面贴片/插件")
    if not parsed.get("has_drills", False):
        _add("NO_DRILLS_CONFIRM", "未识别到钻孔层——请确认该板无定位孔")
    if parsed.get("parse_confidence") == "low":
        _add("LOW_CONFIDENCE_LAYER", "层名自动识别置信度低——请人工核对层映射")
    return items


def pending_blocking(items: list[dict]) -> bool:
    """存在 pending 的 mandatory review → 阻断生产放行。"""
    return any(i.get("type") in MANDATORY_TYPES and i.get("status") == "pending" for i in items)


def save_pending(items: list[ReviewItem], base_dir: str | Path, sha: str) -> Path:
    d = Path(base_dir) / "reviews" / sha[:8]
    d.mkdir(parents=True, exist_ok=True)
    out = d / "pending.json"
    out.write_text(json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_pending(base_dir: str | Path, sha: str) -> list[dict]:
    p = Path(base_dir) / "reviews" / sha[:8] / "pending.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def confirm_review(base_dir: str | Path, sha: str, review_id: str,
                   operator: str, answer: str) -> dict:
    """工程师确认一条 review → 状态翻转 + 记入 layer_mapping.json 审计日志。"""
    d = Path(base_dir) / "reviews" / sha[:8]
    items = load_pending(base_dir, sha)
    hit = None
    for it in items:
        if it["id"] == review_id:
            it["status"] = "confirmed"
            it["operator"] = operator
            it["answer"] = answer
            it["confirmed_at"] = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
            hit = it
            break
    if hit is None:
        raise KeyError(f"review 不存在: {review_id}")
    (d / "pending.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    # layer_mapping.json：审计日志（追加）
    lm = d / "layer_mapping.json"
    log = json.loads(lm.read_text(encoding="utf-8")) if lm.exists() else {"entries": []}
    log["entries"].append({
        "review_id": review_id, "type": hit["type"], "operator": operator,
        "answer": answer, "confirmed_at": hit["confirmed_at"],
    })
    lm.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return hit
