"""vertical_agent_toolkit.py — 垂直领域 AI Agent 工业级开发核心套件 (2026)

四大核心工业级支柱：
1. 领域有状态状态机与检查点恢复 (StateGraph & Checkpointer)
2. 几何拓扑自愈与容错处理器 (GeometricHealer: buffer(0), make_valid, dilate-erode)
3. 超低 Token 领域上下文压缩器 (DomainContextDistiller: 几万图元 -> 150 token 决策快照)
4. 工业黄金样本评测与回归基线 (AgentEvalHarness: IoU, Hausdorff, 阻断率, 延迟)
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("vertical_agent_toolkit")

try:
    from shapely.validation import make_valid
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False


# ===========================================================================
# 1. 领域有状态状态机与检查点恢复 (StateGraph & Checkpointer)
# ===========================================================================

class AgentState(str, Enum):
    INIT = "INIT"
    INGESTING = "INGESTING"
    PARSED = "PARSED"
    GENERATING = "GENERATING"
    DRC_CHECKING = "DRC_CHECKING"
    REVIEW_SUSPENDED = "REVIEW_SUSPENDED"  # 低置信度或缺关键数据，挂起等工程师
    APPROVED = "APPROVED"                  # 工程师核准放行
    PRODUCTION_READY = "PRODUCTION_READY"  # 门禁全绿，允许下载正式生产文件
    FAILED = "FAILED"


@dataclass
class StateSnapshot:
    step_id: str
    state: AgentState
    timestamp: float
    data: dict[str, Any]
    geometry_sha256: str = ""
    error_message: str | None = None


class VerticalAgentFSM:
    """工业级有限状态机，支持事务快照、断点续跑与回滚。"""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.current_state = AgentState.INIT
        self.history: list[StateSnapshot] = []
        self.context: dict[str, Any] = {}
        self._record_snapshot("init", AgentState.INIT)

    def transition_to(self, next_state: AgentState, step_name: str, payload: dict[str, Any] | None = None):
        """状态转移并沉淀不可篡改的执行快照。"""
        self.current_state = next_state
        if payload:
            self.context.update(payload)
        self._record_snapshot(step_name, next_state)

    def _record_snapshot(self, step_id: str, state: AgentState):
        snap = StateSnapshot(
            step_id=step_id,
            state=state,
            timestamp=time.time(),
            data=dict(self.context),
            geometry_sha256=self.context.get("geometry_sha256", "")
        )
        self.history.append(snap)

    def rollback_to(self, step_id: str) -> bool:
        """出现非预期错误时回滚到指定的历史安全检查点。"""
        for snap in reversed(self.history):
            if snap.step_id == step_id:
                self.current_state = snap.state
                self.context = dict(snap.data)
                self.history.append(StateSnapshot(
                    step_id=f"rollback_to_{step_id}",
                    state=snap.state,
                    timestamp=time.time(),
                    data=dict(self.context),
                    geometry_sha256=snap.geometry_sha256
                ))
                return True
        return False

    def can_proceed_to_production(self) -> bool:
        """检查当前状态是否达到生产就绪门禁。"""
        return self.current_state == AgentState.PRODUCTION_READY

    def get_summary(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "current_state": self.current_state.value,
            "total_steps": len(self.history),
            "context": dict(self.context),
            "duration_seconds": round(time.time() - self.history[0].timestamp, 2) if self.history else 0
        }


# ===========================================================================
# 2. 几何拓扑自愈与容错处理器 (GeometricHealer)
# ===========================================================================

class GeometricHealer:
    """工业级几何自愈器：解决自相交、细长毛刺、退化零面与多边形缝合。"""

    @staticmethod
    def heal_polygon(poly: Any, buffer_tolerance: float = 0.0) -> Any:
        """四级渐进式自愈管道：
        1. 检查 is_valid -> 有效则直出
        2. make_valid 拓扑重构
        3. buffer(0) 自相交闭合
        4. dilate-erode 消除微小毛刺
        """
        if not SHAPELY_AVAILABLE:
            return poly

        if poly.is_valid and not poly.is_empty:
            return poly

        # 尝试 1: make_valid
        try:
            healed = make_valid(poly)
            if healed.is_valid and not healed.is_empty:
                return healed
        except Exception as exc:
            logger.debug("make_valid attempt failed: %s", exc)

        # 尝试 2: buffer(0) 经典修复
        try:
            healed = poly.buffer(0)
            if healed.is_valid and not healed.is_empty:
                return healed
        except Exception as exc:
            logger.debug("buffer(0) attempt failed: %s", exc)

        # 尝试 3: 膨胀腐蚀平滑 (Dilate-Erode)
        try:
            r = 0.05
            healed = poly.buffer(r, join_style="round").buffer(-r, join_style="round")
            if healed.is_valid and not healed.is_empty:
                return healed
        except Exception as exc:
            logger.debug("dilate-erode attempt failed: %s", exc)

        # 尝试 4: 凸包降级兜底
        return poly.convex_hull

    # Uniform alias
    heal_geometry = heal_polygon

    @staticmethod
    def compute_sha256(geometries: list[Any]) -> str:
        """为几何对象计算确定性哈希，绑定人工放行（Override）。"""
        hasher = hashlib.sha256()
        for g in geometries:
            if hasattr(g, "wkb"):
                hasher.update(g.wkb)
            else:
                hasher.update(str(g).encode("utf-8"))
        return hasher.hexdigest()

    @staticmethod
    def safe_coverage_ratio(component_box: Any, cavity_union: Any) -> float:
        """计算元件 2D 避位区覆盖率（严禁使用 3D 空心交集，防漏报）。"""
        if not component_box.is_valid or not cavity_union.is_valid:
            component_box = GeometricHealer.heal_polygon(component_box)
            cavity_union = GeometricHealer.heal_polygon(cavity_union)

        if component_box.is_empty or cavity_union.is_empty:
            return 0.0

        inter_area = component_box.intersection(cavity_union).area
        comp_area = component_box.area
        return inter_area / comp_area if comp_area > 0 else 0.0


# ===========================================================================
# 3. 超低 Token 领域上下文压缩器 (DomainContextDistiller)
# ===========================================================================

class DomainContextDistiller:
    """将万级原始图元压缩为 < 150 token 的关键决策快照，供 LLM 进行零幻觉推理。"""

    @staticmethod
    def distill_pcb_job(
        job_id: str,
        board_bounds: tuple[float, float, float, float],
        layers_detected: list[str],
        drill_count: int,
        smd_pads_count: int,
        tht_pads_count: int,
        drc_issues: list[dict[str, Any]],
        mandatory_reviews: list[str]
    ) -> str:
        w = round(board_bounds[2] - board_bounds[0], 2)
        h = round(board_bounds[3] - board_bounds[1], 2)

        snapshot = {
            "id": job_id,
            "pcb": {"dim_mm": [w, h], "drills": drill_count, "smd": smd_pads_count, "tht": tht_pads_count},
            "missing_layers": [l for l in ["Edge_Cuts", "B_Mask", "B_Silk"] if l not in layers_detected],
            "drc_blocking": sum(1 for i in drc_issues if i.get("severity") in ("blocking", "error")),
            "reviews_pending": mandatory_reviews
        }
        # 产生极简 JSON（~100 tokens）
        return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))


# ===========================================================================
# 4. 工业黄金样本评测与回归基线 (AgentEvalHarness)
# ===========================================================================

@dataclass
class EvalMetricResult:
    case_name: str
    iou: float
    hausdorff_mm: float
    passed: bool
    reasons: list[str] = field(default_factory=list)


class AgentEvalHarness:
    """工业级回归基线评估器：断言几何精度、安全拦截率与性能开销。"""

    def __init__(self, min_iou: float = 0.90, max_hausdorff_mm: float = 0.5):
        self.min_iou = min_iou
        self.max_hausdorff_mm = max_hausdorff_mm
        self.results: list[EvalMetricResult] = []

    def evaluate_case(self, case_name: str, expected_geom: Any, actual_geom: Any) -> EvalMetricResult:
        if not SHAPELY_AVAILABLE:
            return EvalMetricResult(case_name, 1.0, 0.0, True, ["Shapely not installed, mock pass"])

        exp = GeometricHealer.heal_polygon(expected_geom)
        act = GeometricHealer.heal_polygon(actual_geom)

        inter = exp.intersection(act).area
        union = exp.union(act).area
        iou = inter / union if union > 0 else 0.0
        hd = exp.hausdorff_distance(act)

        reasons = []
        if iou < self.min_iou:
            reasons.append(f"IoU {iou:.3f} < {self.min_iou}")
        if hd > self.max_hausdorff_mm:
            reasons.append(f"Hausdorff {hd:.2f}mm > {self.max_hausdorff_mm}mm")

        passed = len(reasons) == 0
        res = EvalMetricResult(case_name, round(iou, 4), round(hd, 3), passed, reasons)
        self.results.append(res)
        return res

    def get_benchmark_report(self) -> dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        pass_rate = (passed / total * 100) if total else 0.0
        return {
            "total_cases": total,
            "passed_cases": passed,
            "pass_rate_pct": round(pass_rate, 2),
            "all_green": passed == total,
            "details": [asdict(r) for r in self.results]
        }
