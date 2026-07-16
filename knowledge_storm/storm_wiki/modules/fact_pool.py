"""
FactPool — 行级事实池抽象层

对标 Paper-Arts V4.2 的 Fact_Pool.md 与 Synthetic_Fact_Pool.md 设计。
为 STORM 提供按事实粒度（而非对话轮次粒度）的知识组织与锚定能力。

核心设计：
  - FactEntry: 单条事实的不可变原子单元（含源 URL、原文片段、置信度、矛盾追踪）
  - FactPool: 事实池容器（含反向索引、事实间矛盾追踪、统计摘要）
  - 与 StormInformationTable 的双向转换接口

设计决策：
  1. 事实 ID 全局唯一且不可变 — 断开后重跑时同一 URL snippet 可复用 ID
  2. 事实锚定双向化 — 既可从 source URL 找到事实，也可从事实找到 source URL
  3. 矛盾追踪链表 — fact.contradictions 字段记录与哪些事实存在矛盾
  4. 置信度三级制 — verified (有可靠 URL 来源) / inferred (从对话演绎) / unverified (LLM 生成未证实)
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 事实置信度类型
# ---------------------------------------------------------------------------

FactConfidence = Literal["verified", "inferred", "unverified"]


# ---------------------------------------------------------------------------
# FactEntry — 单条事实
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class FactEntry:
    """
    知识的最小不可分割原子单元。

    每条事实包含:
      - fact_id:       全局唯一不可变 ID（基于 URL + snippet 的内容哈希）
      - content:       单条原子事实的描述文本
      - source_url:    来源 URL（为空表示合成/演绎事实）
      - source_snippet:原文片段（从 retriever 返回的 snippet 原文）
      - perspective:   来源视角（如 "history", "technology"）
      - turn_id:       来源对话轮次（若来自 ConvSimulator）
      - confidence:    置信度分级
      - contradictions:与此事实矛盾的其他 fact_id 列表
      - metadata:      扩展元数据（可存储 P 值、干扰变量等额外信息）

    不可变性:
      - fact_id 在构造后不可变更
      - 其余字段允许更新（如 contradictions 在冲突检测后追加）
    """

    fact_id: int
    content: str
    source_url: str = ""
    source_snippet: str = ""
    perspective: Optional[str] = None
    turn_id: Optional[int] = None
    confidence: FactConfidence = "unverified"
    contradictions: List[int] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            "fact_id": self.fact_id,
            "content": self.content,
            "source_url": self.source_url,
            "source_snippet": self.source_snippet,
            "perspective": self.perspective,
            "turn_id": self.turn_id,
            "confidence": self.confidence,
            "contradictions": self.contradictions,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "FactEntry":
        return cls(**d)

    def __hash__(self) -> int:
        return hash(self.fact_id)

    def __eq__(self, other) -> bool:
        return isinstance(other, FactEntry) and self.fact_id == other.fact_id


# ---------------------------------------------------------------------------
# FactPool — 事实池容器
# ---------------------------------------------------------------------------

class FactPool:
    """
    事实池容器。提供:
      - 事实的增删查改
      - URL → [FactEntry] 反向索引
      - perspective → [FactEntry] 聚簇索引
      - 事实间矛盾追踪
      - 统计摘要
      - JSON 序列化/反序列化
    """

    def __init__(self, topic: str = ""):
        self.topic = topic
        self._facts: Dict[int, FactEntry] = {}        # fact_id → FactEntry
        self._next_id: int = 1                         # 自动递增 ID 生成器
        self._url_to_fact_ids: Dict[str, Set[int]] = {}  # URL → {fact_id, ...}
        self._perspective_to_fact_ids: Dict[str, Set[int]] = {}  # perspective → {fact_id, ...}

    # -----------------------------------------------------------------------
    # 核心增删改查
    # -----------------------------------------------------------------------

    def add_fact(self, fact: FactEntry) -> int:
        """
        将事实加入池。若 fact_id 尚未分配（为 0），自动分配。
        返回事实的 fact_id。
        """
        if fact.fact_id == 0:
            fact.fact_id = self._next_id
            self._next_id += 1
        elif fact.fact_id >= self._next_id:
            self._next_id = fact.fact_id + 1

        self._facts[fact.fact_id] = fact

        # 更新 URL 反向索引
        if fact.source_url:
            if fact.source_url not in self._url_to_fact_ids:
                self._url_to_fact_ids[fact.source_url] = set()
            self._url_to_fact_ids[fact.source_url].add(fact.fact_id)

        # 更新 perspective 聚簇索引
        if fact.perspective:
            if fact.perspective not in self._perspective_to_fact_ids:
                self._perspective_to_fact_ids[fact.perspective] = set()
            self._perspective_to_fact_ids[fact.perspective].add(fact.fact_id)

        return fact.fact_id

    def get_fact(self, fact_id: int) -> Optional[FactEntry]:
        return self._facts.get(fact_id)

    def get_facts_by_url(self, url: str) -> List[FactEntry]:
        fact_ids = self._url_to_fact_ids.get(url, set())
        return [self._facts[fid] for fid in fact_ids if fid in self._facts]

    def get_facts_by_perspective(self, perspective: str) -> List[FactEntry]:
        fact_ids = self._perspective_to_fact_ids.get(perspective, set())
        return [self._facts[fid] for fid in fact_ids if fid in self._facts]

    def get_all_facts(self) -> List[FactEntry]:
        return list(self._facts.values())

    def num_facts(self) -> int:
        return len(self._facts)

    def register_contradiction(self, fact_a_id: int, fact_b_id: int):
        """标记两个事实为矛盾关系（双向注册）。"""
        if fact_a := self._facts.get(fact_a_id):
            if fact_b_id not in fact_a.contradictions:
                fact_a.contradictions.append(fact_b_id)
        if fact_b := self._facts.get(fact_b_id):
            if fact_a_id not in fact_b.contradictions:
                fact_b.contradictions.append(fact_a_id)

    # -----------------------------------------------------------------------
    # 统计摘要
    # -----------------------------------------------------------------------

    def summary(self) -> Dict:
        """返回事实池的统计摘要。"""
        all_facts = self.get_all_facts()
        conf_counts = {"verified": 0, "inferred": 0, "unverified": 0}
        for f in all_facts:
            conf_counts[f.confidence] = conf_counts.get(f.confidence, 0) + 1
        return {
            "topic": self.topic,
            "total_facts": len(all_facts),
            "unique_urls": len(self._url_to_fact_ids),
            "unique_perspectives": len(self._perspective_to_fact_ids),
            "confidence_distribution": conf_counts,
            "contradiction_pairs": sum(
                len(f.contradictions) for f in all_facts
            ) // 2,
        }

    # -----------------------------------------------------------------------
    # 锚定检查
    # -----------------------------------------------------------------------

    def anchor_rate(self, claims: List[str], threshold: float = 0.75) -> float:
        """
        计算给定断言列表中有多少比例能锚定到事实池。
        使用简单的关键词重叠匹配（后续可升级为 embedding 语义匹配）。

        Args:
            claims: 从文章中提取的断言列表
            threshold: 关键词重叠率阈值（默认 0.75）

        Returns:
            锚定比例 (0.0 - 1.0)
        """
        if not claims:
            return 1.0

        from ..interface import Information  # 延迟导入避免循环

        def _keyword_overlap(claim: str, fact_content: str) -> float:
            """计算两个文本的关键词重叠度。"""
            import re
            claim_words = set(re.findall(r'\b\w+\b', claim.lower()))
            fact_words = set(re.findall(r'\b\w+\b', fact_content.lower()))
            if not claim_words:
                return 0.0
            # 排除通用停用词
            stopwords = {
                "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
                "to", "for", "of", "with", "by", "and", "or", "not", "that",
                "this", "it", "from", "as", "be", "has", "have", "do", "does",
                "will", "would", "could", "should", "may", "might",
                "的", "是", "在", "了", "和", "与", "对", "为", "从", "被",
                "有", "不", "这", "那", "也", "就", "都", "而", "及", "或",
            }
            claim_words -= stopwords
            if not claim_words:
                return 0.0
            overlap = claim_words & fact_words
            return len(overlap) / len(claim_words)

        anchored = 0
        for claim in claims:
            # 检查是否与任一事实重叠度超过阈值
            for fact in self.get_all_facts():
                overlap = _keyword_overlap(claim, fact.content)
                if overlap >= threshold:
                    anchored += 1
                    break
        return anchored / len(claims)

    # -----------------------------------------------------------------------
    # 序列化
    # -----------------------------------------------------------------------

    def to_dict(self) -> Dict:
        return {
            "topic": self.topic,
            "facts": [f.to_dict() for f in self._facts.values()],
            "url_to_fact_ids": {
                url: list(fids) for url, fids in self._url_to_fact_ids.items()
            },
            "perspective_to_fact_ids": {
                p: list(fids) for p, fids in self._perspective_to_fact_ids.items()
            },
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "FactPool":
        pool = cls(topic=d.get("topic", ""))
        for fact_dict in d.get("facts", []):
            entry = FactEntry.from_dict(fact_dict)
            pool._facts[entry.fact_id] = entry
            if entry.source_url:
                pool._url_to_fact_ids.setdefault(entry.source_url, set()).add(entry.fact_id)
            if entry.perspective:
                pool._perspective_to_fact_ids.setdefault(entry.perspective, set()).add(entry.fact_id)
        # 恢复 next_id
        if pool._facts:
            pool._next_id = max(pool._facts.keys()) + 1
        return pool

    def dump_json(self, path: str):
        """保存为 JSON 文件。"""
        from ...utils import FileIOHelper
        FileIOHelper.dump_json(self.to_dict(), path)

    @classmethod
    def load_json(cls, path: str) -> "FactPool":
        """从 JSON 文件加载。"""
        from ...utils import FileIOHelper
        data = FileIOHelper.load_json(path)
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# 事实抽取工具函数
# ---------------------------------------------------------------------------

def extract_facts_from_information(
    info: "Information",
    perspective: Optional[str] = None,
    turn_id: Optional[int] = None,
    existing_pool: Optional[FactPool] = None,
) -> List[FactEntry]:
    """
    从 Information 对象中提取事实。

    将 Information 的每个 snippet 拆分为独立事实。
    使用 URL + snippet 的内容哈希作为事实 ID 的稳定基。

    Args:
        info: Information 对象（来自 retriever 的搜索结果）
        perspective: 来源视角（如 "history"）
        turn_id: 来源对话轮次
        existing_pool: 已有的事实池（用于去重和 ID 复用）

    Returns:
        FactEntry 列表
    """

    def _snippet_hash(snippet: str) -> int:
        return int(hashlib.md5(snippet.encode("utf-8")).hexdigest()[:8], 16)

    facts = []
    for i, snippet in enumerate(info.snippets):
        snippet_str = snippet if isinstance(snippet, str) else str(snippet)
        fact_id = _snippet_hash(f"{info.url}:{i}:{snippet_str[:80]}")

        # 检测是否与已有事实重复
        if existing_pool and existing_pool.get_fact(fact_id):
            continue

        entry = FactEntry(
            fact_id=fact_id,
            content=snippet_str.strip(),
            source_url=info.url,
            source_snippet=snippet_str.strip(),
            perspective=perspective,
            turn_id=turn_id,
            confidence="verified" if info.url else "unverified",
        )
        facts.append(entry)

    return facts


def extract_facts_from_dialogue_turn(
    turn: "DialogueTurn",
    perspective: Optional[str] = None,
    turn_id: Optional[int] = None,
    existing_pool: Optional[FactPool] = None,
) -> List[FactEntry]:
    """
    从对话轮次中提取事实。

    Args:
        turn: 对话轮次（含 agent_utterance, search_results 等）
        perspective: 来源视角
        turn_id: 轮次编号
        existing_pool: 已有事实池（去重）

    Returns:
        提取的所有事实
    """
    facts = []
    if turn.search_results:
        for info in turn.search_results:
            info_facts = extract_facts_from_information(
                info, perspective=perspective, turn_id=turn_id, existing_pool=existing_pool
            )
            facts.extend(info_facts)
    return facts
