"""
STORM Async Core — 异步知识策展流水线 (AsyncSTORMPipeline)
升级集成轻量进阶能力：
  1. 视角发现 (Perspective Discovery)
  2. 动态递归知识策展与混合检索 (Deep Exploration Tree & Hybrid RRF)
  3. 大纲拓扑生成 (Outline Generation)
  4. 章节并行起草、机制图表生成与事实图谱构建 (Writing with Diagrams & Fact Graph)
  5. 学术红蓝对抗评审与自适应反思修正 (Academic Review & Reflexion)
  6. 多渠道全格式一键导出与本地知识库沉淀 (Multi-Format Export & Local Knowledge Hub)
"""

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Callable, Any, Union

from .models import (
    Persona,
    FactEntry,
    FactPool,
    SearchSnippet,
    OutlineSection,
    Outline,
    DialogueTurn,
    ArticleDraft,
)
from .llm import AsyncLLM
from .retriever import AsyncSearXNG
from .hybrid_retriever import HybridRetriever
from .deep_exploration import DynamicExplorationTree
from .fact_graph import FactGraph, ContradictionReconciler
from .state_manager import WorkflowStateManager, TaskCheckpoint
from .diagram_generator import DiagramGenerator
from .reviewer import AcademicReviewer, AcademicReviewReport
from .exporter import MultiFormatExporter
from .local_knowledge_hub import LocalKnowledgeHub

logger = logging.getLogger(__name__)


class AsyncSTORMPipeline:
    """现代纯异步知识策展与文章生成流水线。"""

    def __init__(
        self,
        llm: AsyncLLM,
        retriever: Union[AsyncSearXNG, HybridRetriever],
        output_dir: str = "./results_async",
        state_manager: Optional[WorkflowStateManager] = None,
        max_conv_turns: int = 3,
        max_perspectives: int = 4,
        search_top_k: int = 4,
        deep_research: bool = True,
        max_depth: int = 2,
        enable_review: bool = True,
        enable_diagrams: bool = True,
    ):
        self.llm = llm
        self.retriever = retriever
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_manager = state_manager or WorkflowStateManager()
        self.max_conv_turns = max_conv_turns
        self.max_perspectives = max_perspectives
        self.search_top_k = search_top_k
        self.deep_research = deep_research
        self.max_depth = max_depth
        self.enable_review = enable_review
        self.enable_diagrams = enable_diagrams

        self.reconciler = ContradictionReconciler(llm=self.llm)
        self.diagram_gen = DiagramGenerator(llm=self.llm)
        self.reviewer = AcademicReviewer(llm=self.llm)
        self.exporter = MultiFormatExporter()
        self.kb_hub = LocalKnowledgeHub()

    async def run(
        self,
        topic: str,
        task_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str, Any], None]] = None,
    ) -> ArticleDraft:
        """运行或恢复全流程研究任务。"""
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"

        def _notify(stage_name: str, payload: Any = None):
            if progress_callback:
                progress_callback(stage_name, payload)
            logger.info(f"[{task_id}] Stage: {stage_name}")

        # 检查是否存在已有的 Checkpoint
        checkpoint = self.state_manager.load_checkpoint(task_id)
        if not checkpoint:
            checkpoint = TaskCheckpoint(task_id=task_id, topic=topic, stage="INIT")
            self.state_manager.save_checkpoint(checkpoint)
        else:
            _notify(f"RESUMING_FROM_{checkpoint.stage}", {"task_id": task_id})

        # ── 阶段 1: 视角与角色发现 ──
        if checkpoint.stage in ("INIT",):
            _notify("DISCOVERY_START")
            personas = await self._stage_discover_perspectives(topic)
            checkpoint.personas = personas
            checkpoint.stage = "DISCOVERY"
            self.state_manager.save_checkpoint(checkpoint)
            _notify("DISCOVERY_COMPLETE", {"personas": [p.model_dump() for p in personas]})

        # ── 阶段 2: 知识策展 (动态递归探索树 / 混合多源检索) ──
        if checkpoint.stage in ("DISCOVERY",):
            _notify("CURATION_START")
            if self.deep_research:
                _notify("DEEP_RESEARCH_TREE_ACTIVE")
                fact_pool, dialogues = await self._stage_curate_deep_exploration(
                    topic, checkpoint.personas, progress_callback
                )
            else:
                fact_pool, dialogues = await self._stage_curate_knowledge_standard(
                    topic, checkpoint.personas, progress_callback
                )
            checkpoint.fact_pool = fact_pool
            checkpoint.dialogues = dialogues
            checkpoint.stage = "CURATION"
            self.state_manager.save_checkpoint(checkpoint)
            _notify("CURATION_COMPLETE", {"fact_count": len(fact_pool.facts)})

        # ── 阶段 3: 大纲生成 ──
        if checkpoint.stage in ("CURATION",):
            _notify("OUTLINE_START")
            outline = await self._stage_generate_outline(topic, checkpoint.fact_pool)
            checkpoint.outline = outline
            checkpoint.stage = "OUTLINE"
            self.state_manager.save_checkpoint(checkpoint)
            _notify("OUTLINE_COMPLETE", {
                "outline": outline.model_dump(),
                "section_titles": [s.title for s in outline.sections]
            })

        # ── 阶段 4: 事实图谱抽取与章节并行写作 ──
        if checkpoint.stage in ("OUTLINE",):
            _notify("WRITING_START")
            _notify("FACT_GRAPH_EXTRACTING")
            fact_graph = await self.reconciler.extract_graph_and_reconcile(topic, checkpoint.fact_pool)
            _notify("FACT_GRAPH_COMPLETE", {
                "triples_count": len(fact_graph.edges),
                "sample_triples": [f"{e.source_id} -[{e.relation}]-> {e.target_id}" for e in fact_graph.edges[:3]],
                "conflicts_count": len(fact_graph.discrepancies)
            })

            article_draft = await self._stage_write_article(
                topic, checkpoint.outline, checkpoint.fact_pool, fact_graph, progress_callback
            )
            checkpoint.article_draft = article_draft
            checkpoint.stage = "WRITING"
            self.state_manager.save_checkpoint(checkpoint)
            _notify("WRITING_COMPLETE", {"article_len": len(article_draft.content), "triples_count": len(fact_graph.edges)})

        # ── 阶段 5: 学术红蓝对抗评审与反思修正 ──
        if checkpoint.stage in ("WRITING",):
            _notify("REVIEW_START")
            if self.enable_review:
                review_report = await self.reviewer.review_article(checkpoint.article_draft)
                _notify("REVIEW_COMPLETE", {
                    "score": review_report.overall_score,
                    "passed": review_report.is_passed,
                    "dimension_scores": [d.model_dump() for d in review_report.dimension_scores],
                    "suggestions": review_report.critical_suggestions[:2]
                })
                if not review_report.is_passed:
                    _notify("REFLEXION_ACTIVE", {"suggestions": review_report.critical_suggestions})
                    checkpoint.article_draft = await self.reviewer.apply_reflexion_patch(
                        checkpoint.article_draft, review_report, checkpoint.fact_pool
                    )
                    _notify("REFLEXION_PATCH_APPLIED", {"new_len": len(checkpoint.article_draft.content)})

            _notify("POLISH_START")
            polished_draft = await self._stage_polish_article(checkpoint.article_draft)
            checkpoint.article_draft = polished_draft
            checkpoint.stage = "COMPLETED"
            self.state_manager.save_checkpoint(checkpoint)
            _notify("COMPLETED", {"tokens_used": self.llm.total_tokens_used, "article_len": len(checkpoint.article_draft.content)})

        # 自动落盘与多格式导出、知识库索引
        self._dump_results_and_exports(checkpoint)
        return checkpoint.article_draft

    # ── 阶段具体实现 ──────────────────────────────────────────────────────

    async def _stage_discover_perspectives(self, topic: str) -> List[Persona]:
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in topic)
        lang_prompt = "请使用纯中文回复。" if is_chinese else "Respond in English."

        prompt = f"""Topic of interest: {topic}

You need to select {self.max_perspectives} distinct personas/experts who will research this topic together from diverse angles (e.g. Technical Architect, Domain Historian, Industry Analyst, Security/Governance Expert).
{lang_prompt}

Format your output strictly as numbered lines:
1. Persona Name: Short description of their expertise and research focus
2. Persona Name: Short description of their expertise and research focus
..."""

        res = await self.llm.generate(prompt=prompt)
        personas: List[Persona] = []
        for line in res.split("\n"):
            match = re.search(r"^\d+[\.\、\s]+([^:]+?)[:：]\s*(.+)$", line.strip())
            if match:
                personas.append(Persona(name=match.group(1).strip(), description=match.group(2).strip()))

        if not personas:
            if is_chinese:
                personas = [
                    Persona(name="核心技术专家", description="聚焦底层架构、工艺配方与核心运作机制"),
                    Persona(name="产业与市场分析师", description="关注全球市场规模、商业化落地与产业竞争格局"),
                    Persona(name="政策监管与风险研判员", description="评估合规框架、法律准入、安全性挑战与未来趋势"),
                ]
            else:
                personas = [
                    Persona(name="Core Technologist", description="Focuses on underlying architecture and mechanisms"),
                    Persona(name="Industry Specialist", description="Focuses on industry impact and real-world adoption"),
                    Persona(name="Critical Analyst", description="Focuses on limitations, security risks, and challenges"),
                ]
        return personas[: self.max_perspectives]

    async def _stage_curate_deep_exploration(
        self,
        topic: str,
        personas: List[Persona],
        progress_cb: Optional[Callable[[str, Any], None]],
    ) -> tuple[FactPool, List[DialogueTurn]]:
        tree = DynamicExplorationTree(
            llm=self.llm,
            max_depth=self.max_depth,
            max_breadth=3,
            gain_threshold=0.2,
        )
        fact_pool = FactPool()

        async def _retriever_adapter(query: str):
            return await self.retriever.search(query, top_k=self.search_top_k)

        dialogues = await tree.explore_topic_recursively(
            topic=topic,
            personas=personas,
            retriever_func=_retriever_adapter,
            fact_pool=fact_pool,
            progress_cb=progress_cb,
        )
        return fact_pool, dialogues

    async def _stage_curate_knowledge_standard(
        self,
        topic: str,
        personas: List[Persona],
        progress_cb: Optional[Callable[[str, Any], None]],
    ) -> tuple[FactPool, List[DialogueTurn]]:
        fact_pool = FactPool()
        dialogues: List[DialogueTurn] = []

        async def _run_persona_dialogue(persona: Persona) -> List[DialogueTurn]:
            p_dialogues = []
            history = []
            for turn in range(self.max_conv_turns):
                q_prompt = f"""Topic: {topic}
Your Persona: {persona.name} ({persona.description})
Previous Conversation:
{chr(10).join(history) if history else 'None'}

Ask a specific, insightful research question related to the topic from your persona's perspective. Output only the question."""
                question = await self.llm.generate(prompt=q_prompt)
                if not question:
                    break

                clean_topic = topic.replace("的研究", "").replace("的作用", "").strip()[:20]
                clean_q = question.replace("？", "").replace("?", "").strip()[:20]
                search_query = f"{clean_topic} {clean_q}".strip()[:35]
                snippets = await self.retriever.search(search_query, top_k=self.search_top_k)

                snippets_text = "\n".join([f"[{s.title}] {s.content}" for s in snippets])
                a_prompt = f"""Topic: {topic}
Question: {question}
Source Materials:
{snippets_text[:2000] if snippets_text else 'No search results available.'}

Synthesize a factual, informative response answering the question with source evidence. Output only the answer."""
                answer = await self.llm.generate(prompt=a_prompt)

                for s in snippets:
                    if s.content.strip():
                        fact_pool.add_fact(
                            claim=s.content[:300],
                            url=s.url,
                            title=s.title,
                            perspective=persona.name,
                            source_quality=getattr(s, "source_quality", 1.0),
                            confidence=1.0,
                        )

                turn_record = DialogueTurn(
                    persona=persona.name,
                    question=question,
                    queries_issued=[search_query],
                    search_snippets=snippets,
                    answer=answer,
                )
                p_dialogues.append(turn_record)
                history.append(f"Q: {question}\nA: {answer[:200]}")

                if progress_cb:
                    progress_cb("DIALOGUE_TURN", {"persona": persona.name, "turn": turn + 1})

            return p_dialogues

        results = await asyncio.gather(*[_run_persona_dialogue(p) for p in personas])
        for r in results:
            dialogues.extend(r)

        return fact_pool, dialogues

    async def _stage_generate_outline(self, topic: str, fact_pool: FactPool) -> Outline:
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in topic)
        facts_summary = "\n".join([f"- {f.claim[:150]}" for f in fact_pool.facts[:30]])

        if is_chinese:
            prompt = f"""研究课题: {topic}
已采集的核心事实与线索:
{facts_summary[:3000] if facts_summary else '（初步探索阶段）'}

请为该课题设计一份严谨、具备深度学术/产业洞察价值的文章大纲。
要求：
1. 包含 4-6 个核心一级章节（## 章节名）和若干二级小节（### 小节名）。
2. 章节标题必须使用规范专业的中文，严禁使用英文占位符或中英混杂。
3. 严格以 Markdown 标题层级格式输出，不要包含前言废话。"""
        else:
            prompt = f"""Topic: {topic}
Key Facts & Insights Collected:
{facts_summary[:3000]}

Generate a comprehensive, academic-grade article outline.
Format as Markdown headings (## Section Title, ### Subsection Title). Do not include introductory notes or conclusions in the section titles. Include 4-6 main sections."""

        res = await self.llm.generate(prompt=prompt)
        sections: List[OutlineSection] = []
        for line in res.split("\n"):
            line = line.strip()
            if line.startswith("## ") and not line.startswith("###"):
                title = line.replace("## ", "").strip()
                if title.lower() not in ("references", "see also", "参考文献", "引用"):
                    sections.append(OutlineSection(level=1, title=title))
            elif line.startswith("### ") and sections:
                title = line.replace("### ", "").strip()
                sections[-1].subsections.append(OutlineSection(level=2, title=title))

        if not sections:
            if is_chinese:
                sections = [
                    OutlineSection(level=1, title="一、产业背景与技术起源"),
                    OutlineSection(level=1, title="二、核心作用机理与工艺架构"),
                    OutlineSection(level=1, title="三、全球市场格局与商业化进展"),
                    OutlineSection(level=1, title="四、合规监管与未来演进趋势"),
                ]
            else:
                sections = [
                    OutlineSection(level=1, title="Overview and Background"),
                    OutlineSection(level=1, title="Key Mechanisms and Architecture"),
                    OutlineSection(level=1, title="Applications and Impact"),
                    OutlineSection(level=1, title="Challenges and Future Directions"),
                ]

        return Outline(topic=topic, sections=sections)

    async def _stage_generate_abstract(self, topic: str, full_content: str) -> str:
        """为全篇研报生成结构化学术摘要与关键词。"""
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in topic)
        content_sample = full_content[:3000]

        if is_chinese:
            prompt = f"""研究课题: {topic}
研报核心正文摘录:
{content_sample}

请为本篇深度研报提炼撰写一段结构化摘要（200-300字）与 3-5 个核心关键词。
格式严格遵循：
> **摘要**：[此处为200-300字的研究背景、核心机制、主要结论与未来趋势综述]
> 
> **关键词**：词1；词2；词3；词4"""
        else:
            prompt = f"""Topic: {topic}
Article Excerpt:
{content_sample}

Write a structured executive abstract (150-250 words) and 3-5 keywords.
Format:
> **Abstract**: [150-250 words summary]
> 
> **Keywords**: kw1, kw2, kw3"""

        abstract_text = await self.llm.generate(prompt=prompt)
        return abstract_text.strip()

    async def _stage_write_article(
        self,
        topic: str,
        outline: Outline,
        fact_pool: FactPool,
        fact_graph: Optional[FactGraph],
        progress_cb: Optional[Callable[[str, Any], None]],
    ) -> ArticleDraft:
        citations = fact_pool.get_citations_dict()
        url_to_idx = fact_pool.url_to_index

        indexed_sources = []
        for url, idx in url_to_idx.items():
            snippets = [f.claim for f in fact_pool.facts if f.source_url == url]
            content = " ".join(snippets)[:500]
            title = fact_pool.url_to_title.get(url, url)
            indexed_sources.append(f"[{idx}] {title}: {content}")
        sources_text = "\n".join(indexed_sources[:40])

        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in topic)

        async def _write_single_section(sec: OutlineSection, is_core_sec: bool = False) -> str:
            if progress_cb:
                progress_cb("SECTION_WRITING_START", {"section": sec.title, "is_core": is_core_sec})

            sub_titles = ", ".join([sub.title for sub in sec.subsections])
            sub_hint = f"（重点阐述子课题：{sub_titles}）" if sub_titles else ""

            if is_chinese:
                prompt = f"""研究课题: {topic}
章节标题: {sec.title}{sub_hint}
可用参考文献与客观事实证据:
{sources_text[:3500] if sources_text else '（请基于该领域的权威专业知识、行业数据与科学机制进行深入推导论述）'}

请为本章节撰写专业、严谨、深度的长文学术论述。
要求：
1. 紧扣章节主题，深度阐述核心机制、发展脉络、行业现状或技术指标，严禁空话套话或占位符。
2. 若上方提供了文献证据并包含编号（如 [1], [2]），请在关键事实与数据处准确标注标号；若无特定文献，请直接进行逻辑严密的正文论述。
3. 篇幅 600-1200 字，语言地道专业。直接输出 Markdown 正文段落，不要重复输出章节主标题。"""
            else:
                prompt = f"""Topic: {topic}
Section Title: {sec.title}{sub_hint}
Available Citations and Source Evidence:
{sources_text[:3500] if sources_text else '(Synthesize from established domain knowledge)'}

Write a thorough, professional, and deep academic section.
Requirements:
1. Ground facts and arguments deeply, avoiding fluff.
2. Cite references like [1], [2] if available.
3. Write 500-1000 words. Start directly with the section body."""

            content = await self.llm.generate(prompt=prompt, max_tokens=2000)

            # 若模型偶发返回字数不足，触发带指导的二次重试
            if len(content.strip()) < 80:
                retry_prompt = f"请针对主题《{topic}》中的《{sec.title}》章节，撰写一篇至少 600 字的深度学术与产业分析正文，包含具体的背景、机制与未来研判。"
                content = await self.llm.generate(prompt=retry_prompt, max_tokens=2000)

            # 1. 标题净化守卫：剥离大模型在正文开头自主生成的重复标题行
            clean_content = content.strip()
            clean_content = re.sub(r'^(?:#{1,3}\s+[^\n]+\n+)+', '', clean_content).strip()

            # 2. 截断智能探测与自动收尾：若末尾以未完成字符结束，做一次平滑闭合
            if clean_content and clean_content[-1] not in ('。', '！', '？', '.', '!', '?', '"', '”', '`', '\n'):
                # 检查末尾是否处于断句状态
                last_line = clean_content.splitlines()[-1] if clean_content.splitlines() else ""
                if len(last_line) > 10 and not any(last_line.endswith(p) for p in ('。', '！', '？', '.', '!', '?')):
                    closure_prompt = f"请为以下学术论述段落续写最后一句完整的总结句（不超过 50 字，以句号完整结束）：\n{clean_content[-200:]}"
                    try:
                        closure = await self.llm.generate(prompt=closure_prompt, max_tokens=100)
                        closure_clean = closure.strip().replace("\n", " ")
                        if closure_clean:
                            clean_content += " " + closure_clean
                    except Exception:
                        clean_content += "。"

            # 若启用图表生成且为核心架构章节，自动生成 Mermaid 流程图
            diagram_md = ""
            if self.enable_diagrams and is_core_sec:
                d_block = await self.diagram_gen.generate_mermaid_diagram(topic, clean_content)
                if d_block:
                    diagram_md = f"\n\n{d_block}\n\n"

            if progress_cb:
                progress_cb("SECTION_WRITTEN", {
                    "section": sec.title,
                    "char_count": len(clean_content),
                    "has_diagram": bool(diagram_md)
                })
            return f"## {sec.title}\n\n{clean_content}\n{diagram_md}"

        section_tasks = []
        for idx, s in enumerate(outline.sections):
            is_core = idx in (1, 2)  # 通常第 2、3 章节为核心机制章节
            section_tasks.append(_write_single_section(s, is_core))

        section_texts = await asyncio.gather(*section_tasks)
        full_body = "\n\n".join(section_texts)

        # 生成学术摘要并挂载至根标题下方
        abstract_block = await self._stage_generate_abstract(topic, full_body)
        full_article = f"# {topic}\n\n{abstract_block}\n\n" + full_body

        if fact_graph and fact_graph.discrepancies:
            full_article += fact_graph.render_discrepancy_table_markdown()

        ref_title = "## 参考文献" if is_chinese else "## References"
        bib_lines = [f"\n\n{ref_title}\n"]
        for idx, item in sorted(citations.items(), key=lambda x: x[0]):
            bib_lines.append(f"[{idx}] [{item['title']}]({item['url']})")
        full_article += "\n".join(bib_lines)

        return ArticleDraft(
            topic=topic,
            outline=outline,
            content=full_article,
            citations=citations,
        )

    async def _stage_polish_article(self, draft: ArticleDraft) -> ArticleDraft:
        """执行结构一致性润色、全局标题去重与段落排版规范化。"""
        draft.record_version("Before final polish")
        cleaned = draft.content
        # 1. 物理级抹平连续重复的 Markdown 标题（例如连续出现两次 ## 一、xxx）
        cleaned = re.sub(r'^(#{1,3}\s+[^\n]+)\n+(?:#{1,3}\s+[^\n]+\n+)+', r'\1\n\n', cleaned, flags=re.MULTILINE)
        # 2. 保证段落间空行规范
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        draft.polished_content = cleaned
        draft.content = cleaned
        return draft

    def _dump_results_and_exports(self, checkpoint: TaskCheckpoint):
        """全量落盘并导出 Slides、离线 HTML 与知识库沉淀。"""
        task_dir = self.output_dir / checkpoint.task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        if checkpoint.article_draft:
            (task_dir / "article.md").write_text(checkpoint.article_draft.content, encoding="utf-8")
            (task_dir / "citations.json").write_text(
                json.dumps(checkpoint.article_draft.citations, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            # 导出 Marp 幻灯片
            slides_md = self.exporter.generate_marp_slides_markdown(checkpoint.article_draft)
            (task_dir / "slides.marp.md").write_text(slides_md, encoding="utf-8")

            # 导出自包含离线 HTML 研报
            report_html = self.exporter.generate_standalone_html_report(checkpoint.article_draft)
            (task_dir / "report_standalone.html").write_text(report_html, encoding="utf-8")

        if checkpoint.outline:
            (task_dir / "outline.md").write_text(checkpoint.outline.to_markdown(), encoding="utf-8")
        if checkpoint.fact_pool:
            (task_dir / "fact_pool.json").write_text(
                checkpoint.fact_pool.model_dump_json(indent=2), encoding="utf-8"
            )

        # 沉淀至本地 SQLite 知识库
        self.kb_hub.index_completed_research(checkpoint)
        logger.info(f"Task {checkpoint.task_id} all exports generated and indexed.")
