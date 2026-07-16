"""
PipelineState — 管线状态持久化与断点续跑协议

对标 Paper-Arts V4.2 §5 的 Checkpoint & Resume Protocol。

核心设计：
  1. 每个阶段完成后自动落盘 pipeline_state.json
  2. resume=True 时自动检测已完成阶段，跳过重跑
  3. 状态文件包含各阶段产物路径、LM 成本、时间戳
  4. 支持手动指定从特定阶段恢复
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

# 阶段常量
Phase = Literal[
    "idle",
    "research_done",
    "outline_done",
    "article_done",
    "polish_done",
    "audit_done",
]

PHASE_ORDER: List[Phase] = [
    "idle",
    "research_done",
    "outline_done",
    "article_done",
    "polish_done",
    "audit_done",
]


@dataclass
class PipelineState:
    """管线状态快照。"""

    topic: str = ""
    phase: Phase = "idle"
    output_dir: str = ""
    fact_pool_path: Optional[str] = None
    conversation_log_path: Optional[str] = None
    outline_path: Optional[str] = None
    article_path: Optional[str] = None
    polished_article_path: Optional[str] = None
    audit_report_path: Optional[str] = None
    checkpoint_time: str = ""
    lm_cost_so_far: Dict[str, Dict] = field(default_factory=dict)
    rm_cost_so_far: Dict[str, int] = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: Dict) -> "PipelineState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class PipelineStateManager:
    """
    管线状态管理器。

    负责:
      - 保存/加载 pipeline_state.json
      - 判断某个阶段是否已完成
      - 查找可恢复的 checkpoint
    """

    STATE_FILENAME = "pipeline_state.json"

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.state_path = os.path.join(output_dir, self.STATE_FILENAME)
        self._state: Optional[PipelineState] = None

    # -----------------------------------------------------------------------
    # 状态存取
    # -----------------------------------------------------------------------

    def load(self) -> Optional[PipelineState]:
        """从磁盘加载状态文件。"""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = PipelineState.from_dict(data)
                logger.info(f"Loaded pipeline state: phase={self._state.phase}")
                return self._state
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load pipeline state: {e}")
        return None

    def save(self, state: PipelineState):
        """保存状态到磁盘。"""
        state.checkpoint_time = datetime.now().isoformat()
        os.makedirs(self.output_dir, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        self._state = state
        logger.info(f"Saved pipeline state: phase={state.phase}")

    # -----------------------------------------------------------------------
    # 阶段检查
    # -----------------------------------------------------------------------

    def is_phase_complete(self, phase: Phase) -> bool:
        """检查指定阶段是否已完成。"""
        if self._state is None:
            return False
        try:
            current_idx = PHASE_ORDER.index(self._state.phase)
            target_idx = PHASE_ORDER.index(phase)
            return current_idx >= target_idx
        except ValueError:
            return False

    def get_next_incomplete_phase(self) -> Optional[Phase]:
        """返回下一个未完成的阶段。"""
        if self._state is None:
            return "idle"
        try:
            current_idx = PHASE_ORDER.index(self._state.phase)
            if current_idx < len(PHASE_ORDER) - 1:
                return PHASE_ORDER[current_idx + 1]
            return None  # 全部完成
        except ValueError:
            return "idle"

    def update_phase(self, phase: Phase, **extra_fields):
        """更新当前阶段并保存。"""
        if self._state is None:
            self._state = PipelineState(output_dir=self.output_dir)
        self._state.phase = phase
        for k, v in extra_fields.items():
            if hasattr(self._state, k):
                setattr(self._state, k, v)
        self.save(self._state)

    # -----------------------------------------------------------------------
    # 产物路径推断
    # -----------------------------------------------------------------------

    @staticmethod
    def expected_fact_pool_path(output_dir: str) -> str:
        return os.path.join(output_dir, "fact_pool.json")

    @staticmethod
    def expected_conversation_log_path(output_dir: str) -> str:
        return os.path.join(output_dir, "conversation_log.json")

    @staticmethod
    def expected_outline_path(output_dir: str) -> str:
        return os.path.join(output_dir, "storm_gen_outline.txt")

    @staticmethod
    def expected_article_path(output_dir: str) -> str:
        return os.path.join(output_dir, "storm_gen_article.txt")

    @staticmethod
    def expected_polished_article_path(output_dir: str) -> str:
        return os.path.join(output_dir, "storm_gen_article_polished.txt")

    @staticmethod
    def expected_audit_report_path(output_dir: str) -> str:
        return os.path.join(output_dir, "audit_report.json")

    def summary(self) -> str:
        """返回可读的状态摘要。"""
        if self._state is None:
            return "No pipeline state found."
        s = self._state
        lines = [
            f"Topic: {s.topic}",
            f"Phase: {s.phase}",
            f"Output: {s.output_dir}",
            f"Checkpoint: {s.checkpoint_time}",
        ]
        if s.lm_cost_so_far:
            total_tokens = sum(
                v.get("prompt_tokens", 0) + v.get("completion_tokens", 0)
                for v in s.lm_cost_so_far.values()
            )
            lines.append(f"LM tokens used so far: {total_tokens}")
        return "\n".join(lines)
