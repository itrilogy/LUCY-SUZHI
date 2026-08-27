"""
STORM Async Core — 事实图谱与多信源冲突裁决引擎 (FactGraph & ContradictionReconciler)
功能：
1. 结构化实体-关系-主张三元组图谱 (Entity-Relation-Claim Knowledge Graph)
2. 跨信源事实矛盾与数据差异检测 (Cross-source Contradiction Detection)
3. 自动生成学术级“信源分歧对照分析矩阵 (Discrepancy Matrix)”注入报告
"""

import json
import logging
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from .models import FactEntry, FactPool
from .llm import AsyncLLM

logger = logging.getLogger(__name__)


class GraphNode(BaseModel):
    """图谱实体节点"""
    entity_id: str
    name: str
    category: str = "Concept"  # Concept | Metric | Method | Organization | Person
    attributes: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """图谱关系边"""
    source_id: str
    target_id: str
    relation: str  # e.g. "outperforms", "contradicts", "part_of", "created_by"
    claim: str
    source_url: str
    confidence: float = 1.0


class DiscrepancyItem(BaseModel):
    """单项信源冲突/分歧记录"""
    topic_aspect: str = Field(description="冲突涉及的具体指标或技术主张")
    source_a_claim: str = Field(description="信源 A 的主张与数据")
    source_a_url: str
    source_b_claim: str = Field(description="信源 B 的主张与数据")
    source_b_url: str
    reconciliation_analysis: str = Field(description="学术分析与分歧原因推导")


class FactGraph(BaseModel):
    """结构化事实图谱"""
    nodes: Dict[str, GraphNode] = Field(default_factory=dict)
    edges: List[GraphEdge] = Field(default_factory=list)
    discrepancies: List[DiscrepancyItem] = Field(default_factory=list)

    def add_entity(self, name: str, category: str = "Concept") -> GraphNode:
        entity_id = f"ent_{len(self.nodes) + 1}"
        if name not in [n.name for n in self.nodes.values()]:
            node = GraphNode(entity_id=entity_id, name=name, category=category)
            self.nodes[entity_id] = node
            return node
        for n in self.nodes.values():
            if n.name == name:
                return n
        return GraphNode(entity_id=entity_id, name=name, category=category)

    def add_relation(self, source_name: str, target_name: str, relation: str, claim: str, source_url: str):
        src = self.add_entity(source_name)
        tgt = self.add_entity(target_name)
        edge = GraphEdge(
            source_id=src.entity_id,
            target_id=tgt.entity_id,
            relation=relation,
            claim=claim,
            source_url=source_url,
        )
        self.edges.append(edge)

    def render_discrepancy_table_markdown(self) -> str:
        """渲染 Markdown 格式的信源分歧对照表"""
        if not self.discrepancies:
            return ""

        lines = [
            "\n\n### ⚖️ 多信源争议与分歧对照分析 (Source Discrepancy Analysis)\n",
            "| 争议维度 / 指标 | 信源 A 观点与数据 | 信源 B 观点与数据 | 学术裁决与成因分析 |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for d in self.discrepancies:
            sa = f"{d.source_a_claim} ([来源]({d.source_a_url}))"
            sb = f"{d.source_b_claim} ([来源]({d.source_b_url}))"
            lines.append(f"| **{d.topic_aspect}** | {sa} | {sb} | {d.reconciliation_analysis} |")
        lines.append("\n")
        return "\n".join(lines)


class ContradictionReconciler:
    """事实冲突检测与图谱裁决器。"""

    def __init__(self, llm: AsyncLLM):
        self.llm = llm

    async def extract_graph_and_reconcile(self, topic: str, fact_pool: FactPool) -> FactGraph:
        """从事实池中抽取实体关系，并检测跨信源矛盾与数据分歧。"""
        graph = FactGraph()
        if not fact_pool.facts:
            return graph

        # 整理带来源的事实文本
        facts_text_list = []
        for idx, f in enumerate(fact_pool.facts[:35], start=1):
            facts_text_list.append(f"[{idx}] (Source: {f.source_url}) {f.claim}")
        facts_block = "\n".join(facts_text_list)

        prompt = f"""Topic: {topic}
Collected Factual Evidence:
{facts_block[:3500]}

Your Task:
1. Extract 3-5 core entity-relation triples (e.g. Entity A -> [relationship] -> Entity B).
2. Scan for any discrepancies, conflicting performance numbers, or opposing claims between different sources.
   If conflicting claims exist, output them in the discrepancy section.

Output strictly in JSON format matching this schema:
{{
  "triples": [
    {{"source": "Entity A", "relation": "relationship", "target": "Entity B", "claim": "context claim", "source_index": 1}}
  ],
  "discrepancies": [
    {{
      "topic_aspect": "Metric / Feature controversy",
      "source_a_claim": "Claim A",
      "source_a_index": 1,
      "source_b_claim": "Claim B",
      "source_b_index": 2,
      "reconciliation_analysis": "Why these numbers or viewpoints differ (e.g. experimental setup vs real-world)"
    }}
  ]
}}"""

        res = await self.llm.generate(
            prompt=prompt,
            response_format={"type": "json_object"},
        )

        try:
            data = json.loads(res)
            # 解析三元组
            for t in data.get("triples", []):
                s_idx = t.get("source_index", 1)
                url = fact_pool.facts[s_idx - 1].source_url if 0 < s_idx <= len(fact_pool.facts) else "https://storm-synthesis.org"
                graph.add_relation(
                    source_name=t.get("source", "Concept A"),
                    target_name=t.get("target", "Concept B"),
                    relation=t.get("relation", "relates_to"),
                    claim=t.get("claim", ""),
                    source_url=url,
                )

            # 解析矛盾项
            for d in data.get("discrepancies", []):
                idx_a = d.get("source_a_index", 1)
                idx_b = d.get("source_b_index", 1)
                url_a = fact_pool.facts[idx_a - 1].source_url if 0 < idx_a <= len(fact_pool.facts) else "#"
                url_b = fact_pool.facts[idx_b - 1].source_url if 0 < idx_b <= len(fact_pool.facts) else "#"
                graph.discrepancies.append(
                    DiscrepancyItem(
                        topic_aspect=d.get("topic_aspect", "Technical Metric"),
                        source_a_claim=d.get("source_a_claim", ""),
                        source_a_url=url_a,
                        source_b_claim=d.get("source_b_claim", ""),
                        source_b_url=url_b,
                        reconciliation_analysis=d.get("reconciliation_analysis", ""),
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to parse graph and discrepancies: {e}")

        return graph
