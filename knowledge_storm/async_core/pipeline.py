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
            _notify("OUTLINE_COMPLETE", {"outline": outline.model_dump()})

        # ── 阶段 4: 事实图谱抽取与章节并行写作 ──
        if checkpoint.stage in ("OUTLINE",):
            _notify("WRITING_START")
            _notify("FACT_GRAPH_EXTRACTING")
            fact_graph = await self.reconciler.extract_graph_and_reconcile(topic, checkpoint.fact_pool)

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
                _notify("REVIEW_COMPLETE", {"score": review_report.overall_score, "passed": review_report.is_passed})
                if not review_report.is_passed:
                    _notify("REFLEXION_ACTIVE", {"suggestions": review_report.critical_suggestions})
                    checkpoint.article_draft = await self.reviewer.apply_reflexion_patch(
                        checkpoint.article_draft, review_report, checkpoint.fact_pool
                    )

            _notify("POLISH_START")
            polished_draft = await self._stage_polish_article(checkpoint.article_draft)
            checkpoint.article_draft = polished_draft
            checkpoint.stage = "COMPLETED"
            self.state_manager.save_checkpoint(checkpoint)
            _notify("COMPLETED", {"tokens_used": self.llm.total_tokens_used})

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

                search_query = f"{topic} {question}"[:80]
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
        facts_summary = "\n".join([f"- {f.claim[:150]}" for f in fact_pool.facts[:30]])
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
                if title.lower() not in ("references", "see also"):
                    sections.append(OutlineSection(level=1, title=title))
            elif line.startswith("### ") and sections:
                title = line.replace("### ", "").strip()
                sections[-1].subsections.append(OutlineSection(level=2, title=title))

        if not sections:
            sections = [
                OutlineSection(level=1, title="Overview and Background"),
                OutlineSection(level=1, title="Key Mechanisms and Architecture"),
                OutlineSection(level=1, title="Applications and Impact"),
                OutlineSection(level=1, title="Challenges and Future Directions"),
            ]

        return Outline(topic=topic, sections=sections)

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

        async def _write_single_section(sec: OutlineSection, is_core_sec: bool = False) -> str:
            sub_titles = ", ".join([sub.title for sub in sec.subsections])
            sub_hint = f" Cover subtopics: {sub_titles}." if sub_titles else ""
            prompt = f"""Topic: {topic}
Section Title: {sec.title}{sub_hint}
Available Citations and Source Evidence:
{sources_text[:3500]}

Write a thorough, professional, and deep section on this topic.
Requirements:
1. Every major fact or claim MUST be cited with the exact citation number like [1], [2], etc., matching the provided sources above.
2. Maintain high academic rigor, avoiding empty filler.
3. Write 400-800 words. Start directly with the section body."""

            content = await self.llm.generate(prompt=prompt, max_tokens=1500)

            # 若启用图表生成且为核心架构章节，自动生成 Mermaid 流程图
            diagram_md = ""
            if self.enable_diagrams and is_core_sec:
                d_block = await self.diagram_gen.generate_mermaid_diagram(topic, content)
                if d_block:
                    diagram_md = f"\n\n{d_block}\n\n"

            if progress_cb:
                progress_cb("SECTION_WRITTEN", {"section": sec.title})
            return f"## {sec.title}\n\n{content}\n{diagram_md}"

        section_tasks = []
        for idx, s in enumerate(outline.sections):
            is_core = idx in (1, 2)  # 通常第 2、3 章节为核心机制章节
            section_tasks.append(_write_single_section(s, is_core))

        section_texts = await asyncio.gather(*section_tasks)
        full_article = f"# {topic}\n\n" + "\n\n".join(section_texts)

        if fact_graph and fact_graph.discrepancies:
            full_article += fact_graph.render_discrepancy_table_markdown()

        bib_lines = ["\n\n## References\n"]
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
        cleaned = draft.content.replace("$", "\\$")
        draft.polished_content = cleaned
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
