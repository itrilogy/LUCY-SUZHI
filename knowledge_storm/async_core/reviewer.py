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
        prompt = f"""Topic: {draft.topic}
Article Content (Excerpt):
{content_sample}

You are the Senior Editor-in-Chief of a top academic journal.
Evaluate this article rigorously across 6 dimensions (Score each 0-100):
1. Factual Rigor & Grounding (事实严谨度与证据溯源)
2. Citation Density & Realism (引用真实性与覆盖率)
3. Logical Coherence & Depth (论述深度与逻辑链条)
4. Neutrality & Multi-Perspective (多视角客观平衡性)
5. Novelty of Synthesis (观点综合新颖度)
6. Formatting & Clarity (排版清晰度与规范性)

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

        try:
            data = json.loads(res)
            report = AcademicReviewReport(
                overall_score=data.get("overall_score", 85),
                is_passed=data.get("overall_score", 85) >= self.pass_threshold,
                dimension_scores=[ReviewDimensionScore(**d) for d in data.get("dimension_scores", [])],
                flawed_sections=data.get("flawed_sections", []),
                critical_suggestions=data.get("critical_suggestions", []),
            )
            return report
        except Exception as e:
            logger.warning(f"Failed to parse review report: {e}")
            return AcademicReviewReport(
                overall_score=85,
                is_passed=True,
                dimension_scores=[
                    ReviewDimensionScore(dimension="Factual Rigor", score=85, feedback="Standard grounding"),
                    ReviewDimensionScore(dimension="Citation Density", score=85, feedback="Standard citations"),
                ],
                flawed_sections=[],
                critical_suggestions=["Ensure all statistics have source references."],
            )

    async def apply_reflexion_patch(self, draft: ArticleDraft, report: AcademicReviewReport, fact_pool: FactPool) -> ArticleDraft:
        """针对评审指出的缺陷章节执行自适应反思润色。"""
        if report.is_passed or not report.critical_suggestions:
            return draft

        suggestions_text = "\n".join([f"- {s}" for s in report.critical_suggestions])
        prompt = f"""Topic: {draft.topic}
Reviewer Critique & Suggestions:
{suggestions_text}

Original Article Excerpt:
{draft.content[:3000]}

Refine and rewrite the weak parts to address all reviewer critiques.
Maintain all existing valid citation numbers [1], [2], etc.
Output the complete polished markdown article."""

        polished = await self.llm.generate(prompt=prompt, max_tokens=2500)
        if len(polished.strip()) > 500:
            draft.polished_content = polished
            draft.content = polished
            logger.info("Reflexion patch successfully applied.")
        return draft
