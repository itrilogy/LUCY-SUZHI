"""
DiffEngine — FactPool 差异计算与增量更新

对标 Vibe Coding 元工具论的"知识可演化"理念。
支持对同一 topic 的增量更新，而非每次全量重建。

设计：
  1. 比较新旧两个 FactPool 的差异（新增/移除/更新的事实）
  2. 确定哪些 sections 受事实变化影响需要重写
  3. 增量合并策略：冲突检测 + 版本标记
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .fact_pool import FactPool, FactEntry
from .manifest import Manifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 差异类型
# ---------------------------------------------------------------------------

@dataclass
class FactDiff:
    """单条事实的差异。"""
    fact_id: int
    diff_type: str  # "added", "removed", "updated"
    old_fact: Optional[FactEntry] = None
    new_fact: Optional[FactEntry] = None


@dataclass
class PoolDiff:
    """两个 FactPool 之间的完整差异。"""
    added_facts: List[FactDiff] = field(default_factory=list)
    removed_facts: List[FactDiff] = field(default_factory=list)
    updated_facts: List[FactDiff] = field(default_factory=list)
    num_total_old: int = 0
    num_total_new: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.added_facts or self.removed_facts or self.updated_facts)

    def summary(self) -> str:
        parts = []
        if self.added_facts:
            parts.append(f"+{len(self.added_facts)} added")
        if self.removed_facts:
            parts.append(f"-{len(self.removed_facts)} removed")
        if self.updated_facts:
            parts.append(f"~{len(self.updated_facts)} updated")
        return f"FactPool diff: {', '.join(parts) if parts else 'no changes'}"


# ---------------------------------------------------------------------------
# DiffEngine
# ---------------------------------------------------------------------------

class DiffEngine:
    """
    差异计算引擎。

    比较新旧 FactPool，确定：
      - 新增、移除、更新的事实
      - 受影响的 sections
      - 是否需要全量重跑
    """

    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold

    # -----------------------------------------------------------------------
    # 池间差异
    # -----------------------------------------------------------------------

    def compute_pool_diff(self, old_pool: FactPool, new_pool: FactPool) -> PoolDiff:
        """
        计算两个 FactPool 之间的差异。

        Args:
            old_pool: 已有的事实池
            new_pool: 新的事实池

        Returns:
            结构化的差异报告
        """
        old_facts = {f.fact_id: f for f in old_pool.get_all_facts()}
        new_facts = {f.fact_id: f for f in new_pool.get_all_facts()}

        old_ids = set(old_facts.keys())
        new_ids = set(new_facts.keys())

        diff = PoolDiff(
            num_total_old=len(old_ids),
            num_total_new=len(new_ids),
        )

        # 新增的事实（仅在新池中）
        for fid in new_ids - old_ids:
            diff.added_facts.append(FactDiff(
                fact_id=fid,
                diff_type="added",
                new_fact=new_facts[fid],
            ))

        # 移除的事实（仅在旧池中）
        for fid in old_ids - new_ids:
            diff.removed_facts.append(FactDiff(
                fact_id=fid,
                diff_type="removed",
                old_fact=old_facts[fid],
            ))

        # 更新的的事新（ID 相同但内容不同）
        for fid in old_ids & new_ids:
            old_fact = old_facts[fid]
            new_fact = new_facts[fid]
            if old_fact.content != new_fact.content:
                diff.updated_facts.append(FactDiff(
                    fact_id=fid,
                    diff_type="updated",
                    old_fact=old_fact,
                    new_fact=new_fact,
                ))

        return diff

    # -----------------------------------------------------------------------
    # 影响分析
    # -----------------------------------------------------------------------

    def compute_affected_sections(
        self,
        diff: PoolDiff,
        manifest: Manifest,
    ) -> Set[str]:
        """
        根据 FactPool 的差异和 Manifest 的蓝图，
        确定哪些 sections 需要重写。

        Args:
            diff: FactPool 差异
            manifest: 当前的施工蓝图

        Returns:
            需要重写的 section 名称集合
        """
        affected = set()

        if not diff.has_changes:
            return affected

        # 收集变化事实的 ID
        changed_ids = set()
        for fd in diff.added_facts:
            changed_ids.add(fd.fact_id)
        for fd in diff.removed_facts:
            changed_ids.add(fd.fact_id)
        for fd in diff.updated_facts:
            changed_ids.add(fd.fact_id)

        # 检查 Manifest 中哪些 section 引用了变化的事实
        for blueprint in manifest.sections:
            for anchor in blueprint.data_anchors:
                if anchor.fact_id in changed_ids:
                    affected.add(blueprint.section_name)
                    break  # 一个 section 只标记一次

        # 若变化过大（>50% 的事实都变了），标记全部 sections
        total_facts = diff.num_total_old + diff.num_total_new
        if total_facts > 0:
            change_ratio = len(changed_ids) / max(diff.num_total_new, 1)
            if change_ratio > 0.5:
                logger.warning(
                    f"Large-scale fact changes ({change_ratio:.0%}), "
                    f"marking ALL sections for rewrite"
                )
                return {s.section_name for s in manifest.sections}

        return affected

    # -----------------------------------------------------------------------
    # 版本标记
    # -----------------------------------------------------------------------

    @staticmethod
    def version_fact(fact: FactEntry, version_tag: str) -> FactEntry:
        """为事实附加版本标记。"""
        fact.metadata["version"] = version_tag
        fact.metadata["versioned_at"] = __import__("datetime").datetime.now().isoformat()
        return fact
