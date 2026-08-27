"""
STORM Async Core — 动态递归探索树 (Dynamic Exploration Tree / Tree-of-Thoughts)
实现自适应深度下钻，突破固定轮数遍历限制：
1. 基于信息增益率自发评估知识缺口 (Knowledge Gap Assessment)
2. 针对关键技术疑点与争议自发派生分支子任务 (Recursive Sub-query Generation)
3. 知识饱和度阈值自适应收敛判定 (Information Gain Convergence Check)
"""

import asyncio
import logging
from typing import List, Dict, Optional, Callable, Any, Set
from pydantic import BaseModel, Field

from .models import Persona, FactEntry, FactPool, SearchSnippet, DialogueTurn
from .llm import AsyncLLM

logger = logging.getLogger(__name__)


class ExplorationNode(BaseModel):
    """探索树节点"""
    node_id: str
    depth: int = 0
    parent_id: Optional[str] = None
    query: str
    rationale: str = Field(description="提出该探索子问题的物理/逻辑原因")
    perspective: str = "General"
    status: str = "PENDING"  # PENDING | EXPLORING | SATURATED | FAILED
    information_gain_score: float = 1.0  # 0.0 ~ 1.0 信息增益评分
    snippets: List[SearchSnippet] = Field(default_factory=list)
    extracted_facts: List[str] = Field(default_factory=list)


class DynamicExplorationTree:
    """现代动态递归探索树引擎。"""

    def __init__(
        self,
        llm: AsyncLLM,
        max_depth: int = 2,
        max_breadth: int = 3,
        gain_threshold: float = 0.25,
    ):
        self.llm = llm
        self.max_depth = max_depth
        self.max_breadth = max_breadth
        self.gain_threshold = gain_threshold
        self.nodes: Dict[str, ExplorationNode] = {}
        self.explored_queries: Set[str] = set()

    async def explore_topic_recursively(
        self,
        topic: str,
        personas: List[Persona],
        retriever_func: Callable[[str], Any],
        fact_pool: FactPool,
        progress_cb: Optional[Callable[[str, Any], None]] = None,
    ) -> List[DialogueTurn]:
        """执行端到端动态递归探索。"""
        dialogues: List[DialogueTurn] = []
        node_counter = 1

        # 1. 初始化根层节点（广度初探）
        root_nodes: List[ExplorationNode] = []
        for p in personas:
            root_node = ExplorationNode(
                node_id=f"node_{node_counter}",
                depth=0,
                query=f"{topic} core concepts and fundamental mechanisms",
                rationale=f"Initial broad exploration from {p.name}",
                perspective=p.name,
            )
            self.nodes[root_node.node_id] = root_node
            root_nodes.append(root_node)
            node_counter += 1

        # 2. 递归队列处理
        queue = list(root_nodes)
        while queue:
            current_node = queue.pop(0)
            if current_node.query in self.explored_queries:
                continue
            self.explored_queries.add(current_node.query)

            if progress_cb:
                progress_cb(
                    "DEEP_EXPLORATION_NODE_START",
                    {
                        "depth": current_node.depth,
                        "query": current_node.query,
                        "perspective": current_node.perspective,
                    },
                )

            # 2.1 检索证据
            snippets: List[SearchSnippet] = await retriever_func(current_node.query)
            current_node.snippets = snippets

            # 2.2 提炼事实并计算本轮信息增益
            snippets_text = "\n".join([f"[{s.title}] {s.content}" for s in snippets])
            extract_prompt = f"""Topic: {topic}
Perspective: {current_node.perspective}
Query: {current_node.query}
Source Materials:
{snippets_text[:2500] if snippets_text else 'No content.'}

Extract distinct, atomic factual statements from the sources above.
Also estimate the Information Gain Score (0.0 to 1.0) indicating how novel and non-redundant these facts are.

Output format strictly:
[GAIN]: <score between 0.0 and 1.0>
[FACTS]:
- Fact 1
- Fact 2
..."""
            res = await self.llm.generate(prompt=extract_prompt)
            gain_score, extracted_facts = self._parse_gain_and_facts(res)
            current_node.information_gain_score = gain_score
            current_node.extracted_facts = extracted_facts

            # 2.3 录入全局事实池
            for fact in extracted_facts:
                src_url = snippets[0].url if snippets else "https://local-synthesis.org"
                src_title = snippets[0].title if snippets else "Synthesis"
                fact_pool.add_fact(
                    claim=fact,
                    url=src_url,
                    title=src_title,
                    perspective=current_node.perspective,
                )

            # 记录对话轮次
            answer_text = "\n".join([f"• {f}" for f in extracted_facts])
            dialogues.append(
                DialogueTurn(
                    persona=current_node.perspective,
                    question=current_node.query,
                    queries_issued=[current_node.query],
                    search_snippets=snippets,
                    answer=answer_text or "No new significant facts identified.",
                )
            )

            # 2.4 判断是否需要深度下钻 (Branch & Deep Dive)
            if current_node.depth < self.max_depth and gain_score >= self.gain_threshold:
                # 依据当前发现的事实，自发评估知识缺口并派生下钻子问题
                child_queries = await self._generate_sub_queries(
                    topic=topic,
                    parent_node=current_node,
                    extracted_facts=extracted_facts,
                )
                for q, rat in child_queries[: self.max_breadth]:
                    if q not in self.explored_queries:
                        child_node = ExplorationNode(
                            node_id=f"node_{node_counter}",
                            depth=current_node.depth + 1,
                            parent_id=current_node.node_id,
                            query=q,
                            rationale=rat,
                            perspective=current_node.perspective,
                        )
                        self.nodes[child_node.node_id] = child_node
                        queue.append(child_node)
                        node_counter += 1
            else:
                current_node.status = "SATURATED"
                logger.info(
                    f"Node {current_node.node_id} saturated (gain={gain_score:.2f}, depth={current_node.depth})"
                )

        return dialogues

    async def _generate_sub_queries(
        self, topic: str, parent_node: ExplorationNode, extracted_facts: List[str]
    ) -> List[tuple[str, str]]:
        """基于已知事实发现技术盲区/争议，生成深度下钻问题。"""
        facts_summary = "\n".join([f"- {f}" for f in extracted_facts[:5]])
        prompt = f"""Topic: {topic}
Perspective: {parent_node.perspective}
Parent Query: {parent_node.query}
Facts Discovered So Far:
{facts_summary}

Based on these discoveries, identify 1-2 critical knowledge gaps, technical controversies, or underlying mechanism details that require DEEPER investigation.
Format strictly as:
1. Sub-Query: Rationale for why this needs deeper investigation
2. Sub-Query: Rationale for why this needs deeper investigation"""

        res = await self.llm.generate(prompt=prompt)
        sub_queries = []
        for line in res.split("\n"):
            line = line.strip()
            if ":" in line and (line[0].isdigit() or line.startswith("-")):
                parts = line.split(":", 1)
                q = parts[0].lstrip("0123456789.-、 ").strip()
                r = parts[1].strip()
                if len(q) > 5:
                    sub_queries.append((q, r))
        return sub_queries

    def _parse_gain_and_facts(self, text: str) -> tuple[float, List[str]]:
        gain = 0.5
        facts = []
        lines = text.split("\n")
        in_facts = False
        for line in lines:
            line = line.strip()
            if line.startswith("[GAIN]:"):
                try:
                    gain_str = line.replace("[GAIN]:", "").strip()
                    gain = float(gain_str)
                except Exception:
                    gain = 0.5
            elif "[FACTS]" in line:
                in_facts = True
            elif in_facts and (line.startswith("-") or line.startswith("•") or (line and line[0].isdigit())):
                clean_fact = line.lstrip("0123456789.-•、 ").strip()
                if len(clean_fact) > 5:
                    facts.append(clean_fact)
        if not facts and lines:
            facts = [l.strip() for l in lines if len(l.strip()) > 10 and not l.startswith("[")]
        return gain, facts
