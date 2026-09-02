"""
STORM Async Core — 动态递归探索树 (Dynamic Exploration Tree / Tree-of-Thoughts)
实现自适应深度下钻，突破固定轮数遍历限制：
1. 基于信息增益率自发评估知识缺口 (Knowledge Gap Assessment)
2. 针对关键技术疑点与争议自发派生分支子任务 (Recursive Sub-query Generation)
3. 知识饱和度阈值自适应收敛判定 (Information Gain Convergence Check)
"""

import asyncio
import logging
import re
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

        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in topic)

        # 1. 初始化根层节点（使用 LLM 精准提炼专业搜索词，彻底废弃超长字符串拼接）
        root_nodes: List[ExplorationNode] = []
        for p in personas:
            distilled_queries = await self._distill_initial_queries(topic, p, is_chinese)
            for q_text, rat_text in distilled_queries:
                root_node = ExplorationNode(
                    node_id=f"node_{node_counter}",
                    depth=0,
                    query=q_text,
                    rationale=rat_text,
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
            if progress_cb:
                progress_cb("SEARCH_ISSUED", {"query": current_node.query, "perspective": current_node.perspective, "depth": current_node.depth})
            
            snippets: List[SearchSnippet] = await retriever_func(current_node.query)
            current_node.snippets = snippets

            if not snippets:
                current_node.information_gain_score = 0.0
                current_node.status = "SATURATED"
                if progress_cb:
                    progress_cb(
                        "DECISION_SATURATE",
                        {"reason": "本轮没有可用信源，不下钻。", "gain": 0.0, "perspective": current_node.perspective},
                    )
                continue

            if progress_cb and snippets:
                sample_sources = [{"title": s.title or "Web Source", "url": s.url} for s in snippets[:2]]
                progress_cb("SEARCH_HITS", {"query": current_node.query, "count": len(snippets), "samples": sample_sources})

            # 2.2 提炼事实并计算本轮信息增益（强相关性约束）
            snippets_text = "\n".join([f"[{s.title}] {s.content}" for s in snippets])
            
            if is_chinese:
                extract_prompt = f"""研究课题: {topic}
专家视角: {current_node.perspective}
当前检索词: {current_node.query}
参考资料片段:
{snippets_text[:2500] if snippets_text else '（暂无外部检索直接命中，请结合该领域权威公理与学术事实）'}

请从参考资料中提炼出 3~5 条与《{topic}》直接相关的具体、客观的原子事实陈述。
【严格相关性审查红线】：
1. 若上述参考资料是无关的软件下载中心（如各种下载站、杀毒中心）、账号登录、显示器刷新率等噪音，请直接判定 [GAIN]: 0.0，并在 [FACTS] 下输出“无有效相关事实”，严禁将无关噪音当做事实提炼！
2. 只有当材料真正包含与研究主题相关的技术机制、架构、数据或观点时，才提炼事实并给出高增益评分 (0.5~1.0)。

输出格式严格遵循：
[GAIN]: 0.85
[FACTS]:
- 事实要点 1
- 事实要点 2"""
            else:
                extract_prompt = f"""Topic: {topic}
Perspective: {current_node.perspective}
Query: {current_node.query}
Source Materials:
{snippets_text[:2500] if snippets_text else 'No content.'}

Extract 3-5 distinct, atomic factual statements strictly relevant to '{topic}'.
[RELEVANCE RULE]:
If the sources are irrelevant noise (e.g. software download centers, unrelated OS settings, login pages), output [GAIN]: 0.0 and no facts. Do not extract spam facts!

Output format strictly:
[GAIN]: 0.85
[FACTS]:
- Fact 1
- Fact 2"""

            res = await self.llm.generate(prompt=extract_prompt)
            gain_score, extracted_facts = self._parse_gain_and_facts(res, is_chinese=is_chinese)
            
            # 主题相关性二次防线：过滤完全不包含主题核心关键词的噪音事实
            valid_facts = []
            topic_keywords = [w for w in re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', topic) if len(w) >= 2]
            for f in extracted_facts:
                if any(bad in f for bad in ["免费软件", "软件下载", "杀毒检测", "绿色软件", "软件宝库", "刷新率", "账号登录"]):
                    continue
                # 必须与主题有至少一定语义关联，或者当外部资料为空时生成的公理
                if not snippets or any(kw in f for kw in topic_keywords) or len(f) > 15:
                    valid_facts.append(f)

            current_node.information_gain_score = gain_score if valid_facts else 0.0
            current_node.extracted_facts = valid_facts

            if progress_cb:
                progress_cb(
                    "FACTS_EXTRACTED",
                    {
                        "query": current_node.query,
                        "gain_score": current_node.information_gain_score,
                        "facts": valid_facts[:3],
                        "perspective": current_node.perspective,
                    },
                )

            # 2.3 录入全局事实池（信源智能对齐与权威度精准继承）
            for fact in valid_facts:
                best_snip = None
                if snippets:
                    fact_keywords = [w.lower() for w in re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{3,}', fact) if len(w) >= 2]
                    best_overlap = 0
                    for snip in snippets:
                        snip_text = (snip.title + " " + snip.content).lower()
                        overlap = sum(1 for kw in fact_keywords if kw in snip_text)
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_snip = snip
                    if not best_snip:
                        continue

                fact_pool.add_fact(
                    claim=fact,
                    url=best_snip.url,
                    title=best_snip.title,
                    perspective=current_node.perspective,
                    source_quality=best_snip.source_quality,
                    confidence=1.0,
                    engine=getattr(best_snip, "engine", "") or "",
                )

            # 记录对话轮次
            answer_text = "\n".join([f"• {f}" for f in extracted_facts])
            dialogues.append(
                DialogueTurn(
                    persona=current_node.perspective,
                    question=current_node.query,
                    queries_issued=[current_node.query],
                    search_snippets=snippets,
                    answer=answer_text or "已沉淀核心事实论据。",
                )
            )

            # 2.4 判断是否需要深度下钻 (Branch & Deep Dive)
            if current_node.depth < self.max_depth and gain_score >= self.gain_threshold:
                # 依据当前发现的事实，自发评估知识缺口并派生下钻子问题
                child_queries = await self._generate_sub_queries(
                    topic=topic,
                    parent_node=current_node,
                    extracted_facts=extracted_facts,
                    is_chinese=is_chinese,
                )
                if progress_cb and child_queries:
                    progress_cb(
                        "DECISION_BRANCH",
                        {
                            "parent_query": current_node.query,
                            "depth": current_node.depth + 1,
                            "gain": gain_score,
                            "derived_queries": [q for q, _ in child_queries[: self.max_breadth]],
                        },
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
                if progress_cb:
                    progress_cb(
                        "DECISION_SATURATE",
                        {
                            "query": current_node.query,
                            "depth": current_node.depth,
                            "gain": gain_score,
                            "reason": "信息增益饱和或达到最大下钻深度，执行剪枝收敛",
                        },
                    )
                logger.info(
                    f"Node {current_node.node_id} saturated (gain={gain_score:.2f}, depth={current_node.depth})"
                )

        return dialogues

    async def _distill_initial_queries(self, topic: str, persona: Persona, is_chinese: bool = True) -> List[tuple[str, str]]:
        """使用 LLM 针对特定专家视角提纯出精简、高质量的搜索引擎关键词（长度 6-18 字）。"""
        if is_chinese:
            prompt = f"""研究课题: {topic}
专家角色: {persona.name} ({persona.description})

请基于上述研究课题与专家视角，提炼出 1~2 个最精准的搜索引擎检索短语。
要求：
1. 必须是简短、专业的高效搜索词（6~18 字），严禁输出长句或自然语言问句！
2. 剥离“对于...的作用”、“机制”等虚词，组合核心技术术语（如："知识图谱 脚手架 LLM"、"代码生成 软件脚手架 知识建模"）。
3. 格式严格为：
1. [搜索短语]: 检索动机
2. [搜索短语]: 检索动机"""
        else:
            prompt = f"""Topic: {topic}
Expert Persona: {persona.name} ({persona.description})

Distill 1-2 focused, high-precision search queries (3-6 words) for this perspective.
Requirements:
1. Output concise keywords suitable for academic search engines. Avoid long sentences.
2. Format:
1. Search Keywords: Rationale
2. Search Keywords: Rationale"""

        res = await self.llm.generate(prompt=prompt)
        queries = []
        for line in res.split("\n"):
            line = line.strip()
            if ":" in line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
                parts = line.split(":", 1)
                q = parts[0].lstrip("0123456789.-•*、[] ").rstrip("] )）'\"").strip()
                r = parts[1].strip()
                if 4 <= len(q) <= 30 and not any(bad in q.lower() for bad in ["placeholder", "具体搜索短语", "关键词", "sub-query"]):
                    queries.append((q, r))

        if not queries:
            # 兜底生成精炼词
            clean_t = topic.replace("的研究", "").replace("的作用", "").replace("应用", "").strip()[:18]
            queries = [(f"{clean_t} {persona.name}", f"从 {persona.name} 视角展开核心概念检索")]

        return queries[:2]

    async def _generate_sub_queries(
        self, topic: str, parent_node: ExplorationNode, extracted_facts: List[str], is_chinese: bool = True
    ) -> List[tuple[str, str]]:
        """基于已知事实发现技术盲区/争议，生成深度下钻问题（杜绝占位符泄露）。"""
        facts_summary = "\n".join([f"- {f}" for f in extracted_facts[:5]])
        if is_chinese:
            prompt = f"""研究课题: {topic}
专家视角: {parent_node.perspective}
当前检索线索: {parent_node.query}
已沉淀事实摘要:
{facts_summary if facts_summary else '（初步探索）'}

请基于上述内容，精准提炼出 1~2 个最值得深入检索挖掘的技术疑点、争议焦点或量化指标关键词。
要求：
1. 必须是真实的搜索引擎搜索短语（长度 6-25 字），严禁输出 'Sub-Query'、'关键词' 等占位符！
2. 格式严格为：
1. [具体搜索短语]: 探究该方向的核心动机
2. [具体搜索短语]: 探究该方向的核心动机"""
        else:
            prompt = f"""Topic: {topic}
Perspective: {parent_node.perspective}
Parent Query: {parent_node.query}
Facts Discovered So Far:
{facts_summary if facts_summary else 'Initial overview'}

Identify 1-2 specific search queries for deeper investigation.
Requirements: Must be realistic search keywords. Never use 'Sub-Query' placeholder.
Format strictly as:
1. Specific Search Query: Rationale
2. Specific Search Query: Rationale"""

        res = await self.llm.generate(prompt=prompt)
        sub_queries = []
        for line in res.split("\n"):
            line = line.strip()
            if ":" in line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
                parts = line.split(":", 1)
                q = parts[0].lstrip("0123456789.-•、[] ").strip()
                r = parts[1].strip()
                # 过滤占位符与无意义词
                if len(q) >= 4 and not any(bad in q.lower() for bad in ["sub-query", "subquery", "placeholder", "具体搜索短语", "关键词"]):
                    sub_queries.append((q, r))

        # 若模型生成异常，提供可靠的自适应 Fallback 检索词（精简控制在 15 字以内）
        if not sub_queries:
            clean_t = topic.replace("的研究", "").replace("的作用", "").replace("在", " ").replace("中的应用", "").strip()[:14]
            if is_chinese:
                sub_queries = [
                    (f"{clean_t} {parent_node.perspective} 关键技术", "深入挖掘核心机制"),
                    (f"{clean_t} {parent_node.perspective} 实践架构", "分析工程实践与架构落地"),
                ]
            else:
                sub_queries = [
                    (f"{clean_t} {parent_node.perspective} mechanism", "Deep dive into mechanism"),
                    (f"{clean_t} {parent_node.perspective} architecture", "Quantitative architecture"),
                ]

        return sub_queries

    def _parse_gain_and_facts(self, text: str, is_chinese: bool = True, fallback_topic: str = "") -> tuple[float, List[str]]:
        """解析增益与事实。解析失败增益为 0，不编造套话入池。"""
        import re
        gain = 0.0
        facts = []
        cleaned_text = re.sub(r'<think>[\s\S]*?<\/think>', '', text or "").strip()
        lines = cleaned_text.split("\n")
        in_facts = False
        parsed_gain = False

        for line in lines:
            line_s = line.strip()
            if "[GAIN]:" in line_s or "GAIN:" in line_s:
                try:
                    gain_match = re.search(r'GAIN\]?:\s*([0-9.]+)', line_s)
                    if gain_match:
                        gain = float(gain_match.group(1))
                        parsed_gain = True
                except Exception:
                    gain = 0.0
            elif "[FACTS]" in line_s or line_s.upper().startswith("FACTS:"):
                in_facts = True
            elif in_facts and (line_s.startswith("-") or line_s.startswith("•") or line_s.startswith("*") or (line_s and line_s[0].isdigit())):
                clean_fact = line_s.lstrip("0123456789.-•*、[] ").strip()
                if len(clean_fact) >= 6 and "无有效相关事实" not in clean_fact:
                    facts.append(clean_fact)

        if not facts:
            for l in lines:
                l_s = l.strip()
                if (l_s.startswith("-") or l_s.startswith("•") or l_s.startswith("*")) and len(l_s) >= 8:
                    clean_f = l_s.lstrip("0123456789.-•*、[] ").strip()
                    if len(clean_f) >= 8 and not any(tag in clean_f.upper() for tag in ["GAIN", "FACTS", "TOPIC"]):
                        facts.append(clean_f)

        if not facts:
            return 0.0, []
        if not parsed_gain:
            gain = 0.0
        return max(0.0, min(1.0, gain)), facts
