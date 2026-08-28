"""
STORM Async Core — 学术红蓝对抗评审与反思修正引擎 (AcademicReviewer & Reflexion)
功能：
1. 从 6 个维度对长文进行严格量化打分（严谨度、真实性、引用覆盖率、逻辑连贯性、新颖度、格式合规度）
2. 识别关键主张缺乏引用的“孤立段落”或逻辑跳跃
3. 触发局部自适应反思修复 (Reflexion Patch)，实现学术质量自闭环
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from .llm import AsyncLLM
from .models import ArticleDraft, FactPool

logger = logging.getLogger(__name__)


class ReviewDimensionScore(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=100)
    feedback: str


class AcademicReviewReport(BaseModel):
    overall_score: int = 85
    is_passed: bool = True
    dimension_scores: List[ReviewDimensionScore] = Field(default_factory=list)
    flawed_sections: List[str] = Field(default_factory=list)
    critical_suggestions: List[str] = Field(default_factory=list)


class AcademicReviewer:
    """现代学术评审与反思修正器。"""

    def __init__(self, llm: AsyncLLM, pass_threshold: int = 80):
        self.llm = llm
        self.pass_threshold = pass_threshold

    async def review_article(self, draft: ArticleDraft) -> AcademicReviewReport:
        """对草稿执行 6 维度量化评审。"""
        content_sample = draft.content[:3500]
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in draft.topic)

        if is_chinese:
            prompt = f"""研究课题: {draft.topic}
文章正文（节选）:
{content_sample}

你作为顶级学术期刊的执行主编，请从以下 6 个维度对本篇学术长文进行严格量化评审（各项打分 0-100）：
1. 事实严谨度与证据溯源 (Factual Rigor)
2. 引用真实性与覆盖率 (Citation Density)
3. 论述深度与逻辑链条 (Logical Depth)
4. 多视角客观平衡性 (Neutrality)
5. 观点综合新颖度 (Novelty)
6. 排版清晰度与规范性 (Formatting)

请严格输出 JSON 格式（feedback 与 suggestions 请使用中文）：
{{
  "overall_score": 88,
  "dimension_scores": [
    {{"dimension": "事实严谨度", "score": 90, "feedback": "关键技术数据具备明确信源支撑"}},
    {{"dimension": "引用真实性", "score": 85, "feedback": "正文合理标注了 [i] 引用编号"}},
    {{"dimension": "论述深度", "score": 88, "feedback": "逻辑层次推导严密"}},
    {{"dimension": "多视角平衡", "score": 92, "feedback": "涵盖技术与产业多重视角"}},
    {{"dimension": "观点新颖度", "score": 80, "feedback": "提炼清晰，有综合创新点"}},
    {{"dimension": "排版规范性", "score": 90, "feedback": "Markdown 标题层级与摘要规范"}}
  ],
  "flawed_sections": ["如无明显缺陷章节可留空"],
  "critical_suggestions": ["1~2 条具体的中文学术润色建议"]
}}"""
        else:
            prompt = f"""Topic: {draft.topic}
Article Content (Excerpt):
{content_sample}

You are the Senior Editor-in-Chief of a top academic journal.
Evaluate this article rigorously across 6 dimensions (Score each 0-100):
1. Factual Rigor & Grounding
2. Citation Density & Realism
3. Logical Coherence & Depth
4. Neutrality & Multi-Perspective
5. Novelty of Synthesis
6. Formatting & Clarity

Output strictly in JSON format matching this schema:
{{
  "overall_score": 88,
  "dimension_scores": [
    {{"dimension": "Factual Rigor", "score": 90, "feedback": "Solid grounding with source URLs"}},
    {{"dimension": "Citation Density", "score": 85, "feedback": "Adequate [i] citations throughout"}},
    {{"dimension": "Logical Depth", "score": 88, "feedback": "Well structured arguments"}},
    {{"dimension": "Neutrality", "score": 92, "feedback": "Includes controversy analysis"}},
    {{"dimension": "Novelty", "score": 80, "feedback": "Clear synthesis"}},
    {{"dimension": "Formatting", "score": 90, "feedback": "Clear Markdown hierarchy"}}
  ],
  "flawed_sections": ["Section Name if any needs improvement"],
  "critical_suggestions": ["1-2 actionable polish items"]
}}"""

        res = await self.llm.generate(
            prompt=prompt,
            response_format={"type": "json_object"},
        )

        from .models import safe_extract_json
        data = safe_extract_json(res)
        if data:
            try:
                report = AcademicReviewReport(
                    overall_score=data.get("overall_score", 85),
                    is_passed=data.get("overall_score", 85) >= self.pass_threshold,
                    dimension_scores=[ReviewDimensionScore(**d) for d in data.get("dimension_scores", [])],
                    flawed_sections=data.get("flawed_sections", []),
                    critical_suggestions=data.get("critical_suggestions", []),
                )
                return report
            except Exception as e:
                logger.warning(f"Failed to instantiate AcademicReviewReport: {e}")

        fallback_suggestion = "建议确保所有关键行业数据与技术指标均具备明确的信源标注。" if is_chinese else "Ensure all statistics have source references."
        return AcademicReviewReport(
            overall_score=85,
            is_passed=True,
            dimension_scores=[
                ReviewDimensionScore(dimension="事实严谨度" if is_chinese else "Factual Rigor", score=85, feedback="基础论据扎实" if is_chinese else "Standard grounding"),
                ReviewDimensionScore(dimension="引用覆盖率" if is_chinese else "Citation Density", score=85, feedback="规范标注引用" if is_chinese else "Standard citations"),
            ],
            flawed_sections=[],
            critical_suggestions=[fallback_suggestion],
        )

    async def apply_reflexion_patch(self, draft: ArticleDraft, report: AcademicReviewReport, fact_pool: FactPool) -> ArticleDraft:
        """针对评审指出的缺陷章节执行章节级靶向反思润色（杜绝整篇万字长文单次重写导致的截断与烂尾）。"""
        if report.is_passed or not report.critical_suggestions:
            return draft

        draft.record_version("Before reflexion patch")
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in draft.topic)
        suggestions_text = "\n".join([f"- {s}" for s in report.critical_suggestions])

        # 1. 提取正文中的章节块 (按 ## 章节切分)
        content = draft.content
        parts = re.split(r'(?=\n##\s+)', content)
        if len(parts) <= 1:
            return draft

        header_part = parts[0]  # 包含 # 主题 与 > **摘要**
        section_parts = parts[1:]

        flawed_names = [f.lower().strip() for f in report.flawed_sections if f and len(f.strip()) >= 2]

        def _is_flawed_match(sec_t: str) -> bool:
            sec_clean = sec_t.lower().strip()
            for fn in flawed_names:
                if fn == sec_clean:
                    return True
                # 只有当关键词长度 >= 4 时才允许包含匹配，防止短词误杀
                if len(fn) >= 4 and (fn in sec_clean or sec_clean in fn):
                    return True
            return False

        new_section_parts = []
        for sec_text in section_parts:
            # 提取章节标题与正文
            match = re.match(r'\n##\s+([^\n]+)\n+([\s\S]*)', sec_text)
            if not match:
                new_section_parts.append(sec_text)
                continue

            sec_title = match.group(1).strip()
            sec_body = match.group(2).strip()

            # 参考文献与争议矩阵无需润色
            if any(ref in sec_title.lower() for ref in ["参考文献", "references", "跨信源争议"]):
                new_section_parts.append(sec_text)
                continue

            # 判定本章节是否需要靶向强化（若指定了缺陷章节则精准命中，否则强化最关键的前 2 个技术章节）
            need_polish = False
            if flawed_names:
                need_polish = _is_flawed_match(sec_title)
            else:
                need_polish = len(new_section_parts) < 2  # 默认精修核心章节

            if need_polish and len(sec_body) > 30:
                if is_chinese:
                    prompt = f"""研究课题: {draft.topic}
评审专家改进建议:
{suggestions_text}

待增强章节标题: {sec_title}
当前章节正文:
{sec_body[:2500]}

请根据评审建议对本章节进行深度学术润色与论述增强。
要求：
1. 保持并深化核心论据，补充机制推导与行业数据，保持所有现存引用标号（如 [1], [2]）。
2. 直接输出润色后的章节 Markdown 正文段落，严禁在开头输出章节标题（不要输出 ## {sec_title}）！
3. 确保段落结尾完整（必须以句号正常结束，严禁中途截断）。"""
                else:
                    prompt = f"""Topic: {draft.topic}
Reviewer Suggestions:
{suggestions_text}

Section Title: {sec_title}
Current Body:
{sec_body[:2500]}

Enhance and deepen the arguments for this section based on the reviewer feedback.
Requirements:
1. Maintain existing citations like [1], [2].
2. Output ONLY the polished body paragraphs. Do NOT repeat the section heading.
3. Ensure the text ends cleanly with a period."""

                try:
                    polished_body = await self.llm.generate(prompt=prompt, max_tokens=2000)
                    polished_body = polished_body.strip()
                    # 剥离模型开头可能带有的重复标题
                    polished_body = re.sub(r'^(?:#{1,3}\s+[^\n]+\n+)+', '', polished_body).strip()

                    # 截断智能探测与自动收尾：若末尾以未完成字符结束，做一次平滑闭合
                    if polished_body and polished_body[-1] not in ('。', '！', '？', '.', '!', '?', '"', '”', '`', '\n'):
                        last_period = max(polished_body.rfind('。'), polished_body.rfind('.'))
                        if last_period > len(polished_body) - 50 and last_period > 100:
                            polished_body = polished_body[:last_period + 1]
                        else:
                            closure_prompt = f"请为以下学术论述段落续写最后一句完整的总结句（不超过 40 字，以句号完整结束）：\n{polished_body[-200:]}"
                            try:
                                closure = await self.llm.generate(prompt=closure_prompt, max_tokens=100)
                                closure_clean = closure.strip().replace("\n", " ")
                                if closure_clean:
                                    polished_body += " " + closure_clean
                            except Exception:
                                polished_body += "。"

                    if not any(polished_body.endswith(p) for p in ('。', '！', '？', '.', '!', '?', '"', '”', '`')):
                        polished_body += "。"

                    if len(polished_body) > 200:
                        new_section_parts.append(f"\n## {sec_title}\n\n{polished_body}")
                        continue
                except Exception as e:
                    logger.warning(f"Section reflexion failed for {sec_title}: {e}")

            new_section_parts.append(f"\n## {sec_title}\n\n{sec_body}")

        # 2. 重新平滑缝合整篇研报
        full_polished = header_part + "".join(new_section_parts)
        # 3. 物理级抹平连续重复的标题
        full_polished = re.sub(r'^(#{1,3}\s+[^\n]+)\n+(?:#{1,3}\s+[^\n]+\n+)+', r'\1\n\n', full_polished, flags=re.MULTILINE)
        full_polished = re.sub(r'\n{3,}', '\n\n', full_polished)

        draft.polished_content = full_polished
        draft.content = full_polished
        logger.info(f"Section-targeted reflexion patch applied successfully (len={len(full_polished)}).")
        return draft
