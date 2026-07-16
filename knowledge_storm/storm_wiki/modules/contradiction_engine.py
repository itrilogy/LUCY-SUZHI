"""
ContradictionEngine — 多视角矛盾检测与 TRIZ 式冲突分析

对标 Paper-Arts V4.2 的 TRIZ 矛盾矩阵（rule_TRIZ_Innovation.md）。

设计：
  1. 跨视角聚类：将同一 sub-topic 下不同视角的 Facts 聚类
  2. 语义矛盾检测：NLI 模型判断是否构成 contradiction
  3. 分类为物理矛盾 vs 技术矛盾
  4. 基于 TRIZ 40 发明原理库给出解决路径建议
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import dspy

from .fact_pool import FactPool, FactEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Contradiction:
    """检测到的一对事实矛盾。"""
    fact_a: FactEntry
    fact_b: FactEntry
    contradiction_type: str  # "physical" (物理矛盾) or "technical" (技术矛盾)
    description: str
    shared_topic: str = ""  # 共享的子主题
    resolution_suggestions: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DSPy Signatures
# ---------------------------------------------------------------------------

class ContradictionClassificationSignature(dspy.Signature):
    """You are an expert in TRIZ contradiction analysis. Given two facts that may contradict each other,
    classify the contradiction type:

    - 'physical': The same entity has opposite requirements (e.g., both hot and cold, both fast and accurate)
    - 'technical': Improving one parameter causes another to deteriorate (e.g., faster but less accurate)
    - 'contradictory_claim': The two facts make logically inconsistent claims about the same subject
    - 'not_contradictory': The facts are compatible or unrelated

    Respond with ONE type and a brief justification."""
    fact_a = dspy.InputField(prefix="Fact A: ", format=str)
    fact_b = dspy.InputField(prefix="Fact B: ", format=str)
    judgement = dspy.OutputField(prefix="Contradiction Type + Justification: ", format=str)


class TRIZResolutionSignature(dspy.Signature):
    """You are a TRIZ (Theory of Inventive Problem Solving) expert.
    Given a contradiction between two facts, suggest resolution strategies
    using the 40 Inventive Principles.
    List 2-3 specific principles that could resolve this contradiction,
    with a brief explanation for each."""
    contradiction_type = dspy.InputField(prefix="Contradiction Type: ", format=str)
    description = dspy.InputField(prefix="Contradiction Description: ", format=str)
    fact_a = dspy.InputField(prefix="Fact A: ", format=str)
    fact_b = dspy.InputField(prefix="Fact B: ", format=str)
    resolutions = dspy.OutputField(prefix="TRIZ Resolution Strategies: \n", format=str)


# ---------------------------------------------------------------------------
# ContradictionEngine
# ---------------------------------------------------------------------------

class ContradictionEngine:
    """
    事实矛盾检测与 TRIZ 式冲突分析引擎。

    对标 Paper-Arts rule_TRIZ_Innovation.md 中的：
      - 物理矛盾检测（同一对象相反需求）
      - 技术矛盾检测（改善 A 恶化 B）
      - TRIZ 40 发明原理解决路径
    """

    def __init__(
        self,
        lm: dspy.dsp.LM,
        max_pairs: int = 50,
    ):
        """
        Args:
            lm: 用于矛盾分类和解决建议的 LM
            max_pairs: 最大比较的事实对数（超出时随机采样）
        """
        self.lm = lm
        self.max_pairs = max_pairs
        self._classifier = dspy.Predict(ContradictionClassificationSignature)
        self._resolver = dspy.Predict(TRIZResolutionSignature)

    # -----------------------------------------------------------------------
    # 核心方法
    # -----------------------------------------------------------------------

    def detect_contradictions(self, fact_pool: FactPool) -> List[Contradiction]:
        """
        检测 FactPool 中的事实矛盾。

        步骤：
          1. 跨视角聚类：将同一 sub-topic 下不同视角的 Facts 聚类
          2. 语义矛盾检测：LLM 判断是否构成 contradiction
          3. 分类为 物理矛盾、技术矛盾 或 矛盾主张

        Args:
            fact_pool: 事实池

        Returns:
            检测到的矛盾列表
        """
        contradictions: List[Contradiction] = []

        # Step 1: 跨视角聚类
        perspectives = self._get_perspectives(fact_pool)
        if len(perspectives) < 2:
            return contradictions  # 单视角无矛盾

        # 按子主题聚类：提取所有事实的 keywords 并分组
        clusters = self._cluster_by_subtopic(fact_pool)

        # Step 2 & 3: 在每个聚类内进行跨视角矛盾检测
        for cluster_topic, cluster_facts in clusters.items():
            # 按视角分组
            by_perspective: Dict[str, List[FactEntry]] = {}
            for fact in cluster_facts:
                p = fact.perspective or "default"
                by_perspective.setdefault(p, []).append(fact)

            perspective_list = list(by_perspective.keys())
            if len(perspective_list) < 2:
                continue

            # 跨视角成对比较
            pairs = []
            for i in range(len(perspective_list)):
                for j in range(i + 1, len(perspective_list)):
                    for fa in by_perspective[perspective_list[i]][:2]:  # 每个视角取前 2 条
                        for fb in by_perspective[perspective_list[j]][:2]:
                            pairs.append((fa, fb))

            # 限制比较对数
            if len(pairs) > self.max_pairs:
                import random
                pairs = random.sample(pairs, self.max_pairs)

            for fa, fb in pairs:
                if fa.fact_id in fb.contradictions:
                    # 已经是标记过的矛盾
                    continue

                contradiction = self._classify_contradiction(fa, fb, cluster_topic)
                if contradiction is not None:
                    contradictions.append(contradiction)

        return contradictions

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    @staticmethod
    def _get_perspectives(fact_pool: FactPool) -> List[str]:
        """获取 FactPool 中的所有视角。"""
        perspectives = set()
        for fact in fact_pool.get_all_facts():
            if fact.perspective:
                perspectives.add(fact.perspective)
        return list(perspectives)

    @staticmethod
    def _cluster_by_subtopic(fact_pool: FactPool) -> Dict[str, List[FactEntry]]:
        """
        将事实按子主题聚类。

        使用简单关键词重叠分组（后续可升级为 embedding 聚类）。
        """
        facts = fact_pool.get_all_facts()

        # 提取每一条事实的关键词
        def extract_keywords(content: str) -> set:
            words = re.findall(r'\b[a-zA-Z]{3,}\b', content.lower())
            return set(words)

        # 按关键词重叠聚类
        clusters: Dict[str, List[FactEntry]] = {}
        assigned: set = set()

        for i, fact in enumerate(facts):
            if fact.fact_id in assigned:
                continue
            kw_i = extract_keywords(fact.content)
            # 找同聚类的事实
            cluster_facts = [fact]
            assigned.add(fact.fact_id)

            for j in range(i + 1, len(facts)):
                f2 = facts[j]
                if f2.fact_id in assigned:
                    continue
                kw_j = extract_keywords(f2.content)
                if len(kw_i & kw_j) >= 3:  # 至少 3 个公共关键词
                    cluster_facts.append(f2)
                    assigned.add(f2.fact_id)

            if len(cluster_facts) >= 2:  # 聚类至少包含 2 条事实
                # 用共同关键词作为聚类名
                common_kw = kw_i
                for cf in cluster_facts:
                    common_kw &= extract_keywords(cf.content)
                cluster_name = ", ".join(sorted(common_kw)[:5]) if common_kw else fact.content[:50]
                clusters[cluster_name] = cluster_facts

        return clusters

    def _classify_contradiction(
        self,
        fa: FactEntry,
        fb: FactEntry,
        cluster_topic: str,
    ) -> Optional[Contradiction]:
        """使用 LLM 分类一对事实的矛盾类型。"""
        try:
            with dspy.settings.context(lm=self.lm):
                result = self._classifier(fact_a=fa.content[:300], fact_b=fb.content[:300])
            judgement = result.judgement.strip().lower()

            # 解析结果
            if "not_contradictory" in judgement or "not contradictory" in judgement:
                return None

            contradiction_type = "contradictory_claim"
            if "physical" in judgement:
                contradiction_type = "physical"
            elif "technical" in judgement:
                contradiction_type = "technical"

            # 生成解决路径
            resolution_suggestions = self._suggest_resolutions(
                contradiction_type, f"{fa.content[:150]} vs {fb.content[:150]}", fa, fb
            )

            # 在 FactPool 中注册矛盾
            # (调用者需执行 pool.register_contradiction())

            return Contradiction(
                fact_a=fa,
                fact_b=fb,
                contradiction_type=contradiction_type,
                description=judgement[:200],
                shared_topic=cluster_topic,
                resolution_suggestions=resolution_suggestions,
            )

        except Exception as e:
            logger.warning(f"Contradiction classification failed: {e}")
            return None

    def _suggest_resolutions(
        self,
        contradiction_type: str,
        description: str,
        fa: FactEntry,
        fb: FactEntry,
    ) -> List[str]:
        """基于 TRIZ 40 发明原理生成解决路径。"""
        try:
            with dspy.settings.context(lm=self.lm):
                result = self._resolver(
                    contradiction_type=contradiction_type,
                    description=description,
                    fact_a=fa.content[:200],
                    fact_b=fb.content[:200],
                )
            raw = result.resolutions.strip()
            suggestions = [s.strip() for s in raw.split("\n") if s.strip()]
            return suggestions[:5]
        except Exception as e:
            logger.warning(f"TRIZ resolution failed: {e}")
            return []

    # -----------------------------------------------------------------------
    # 批量处理
    # -----------------------------------------------------------------------

    def register_contradictions(self, fact_pool: FactPool,
                                 contradictions: List[Contradiction]):
        """将检测到的矛盾注册到 FactPool 中。"""
        for c in contradictions:
            fact_pool.register_contradiction(c.fact_a.fact_id, c.fact_b.fact_id)
