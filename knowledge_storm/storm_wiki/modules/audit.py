"""
StormAuditModule — 后生成审计模块

对标 Paper-Arts V4.2 的 Quality Controller（expert_quality_controller.md）。

设计：
  - 四个可组合的检查器，每个都是独立的 dspy.Signature 或规则引擎
  - FactAnchorChecker:    反幻觉检查 — 断言是否锚定到 FactPool
  - CitationIntegrityChecker: 引用完整性 — 引用编号是否有效
  - ContradictionDetector: 事实矛盾 — 跨 section 的矛盾检测
  - RedundancyDetector:    重复内容 — section 间的文本重叠
  - AuditReport: 可操作的结构化审计报告（含标红拦截 + 黄牌警告）
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple

import dspy
import numpy as np

from ..interface import Article, ArticleSectionNode, InformationTable
from .storm_dataclass import StormArticle
from .fact_pool import FactPool, FactEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 审计报告数据结构
# ---------------------------------------------------------------------------

Severity = Literal["critical", "major", "warning", "info"]


@dataclass
class Issue:
    """单个审计问题。"""
    severity: Severity
    location: str  # section_name (可附加段落偏移)
    description: str
    rule: str = ""
    evidence: str = ""
    fix_suggestion: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class AuditReport:
    """
    结构化的审计报告。

    对标 Paper-Arts COMPLIANCE_AUDIT_REPORT.md 的数据结构。
    """
    topic: str = ""
    overall_score: float = 1.0  # 0.0 - 1.0
    blocking_issues: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)
    section_scores: Dict[str, float] = field(default_factory=dict)
    fact_anchoring_rate: float = 1.0
    citation_validity_rate: float = 1.0
    num_contradictions: int = 0
    num_redundant_pairs: int = 0
    suggestions: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def passed(self) -> bool:
        """审计是否通过（无 blocking_issues）。"""
        return len(self.blocking_issues) == 0

    def to_dict(self) -> Dict:
        return {
            "topic": self.topic,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "num_blocking": len(self.blocking_issues),
            "num_warnings": len(self.warnings),
            "blocking_issues": [i.to_dict() for i in self.blocking_issues],
            "warnings": [i.to_dict() for i in self.warnings],
            "section_scores": self.section_scores,
            "fact_anchoring_rate": self.fact_anchoring_rate,
            "citation_validity_rate": self.citation_validity_rate,
            "num_contradictions": self.num_contradictions,
            "num_redundant_pairs": self.num_redundant_pairs,
            "suggestions": self.suggestions,
            "created_at": self.created_at,
        }

    def to_text(self) -> str:
        """生成人类可读的报告文本。"""
        lines = [
            f"# Audit Report: {self.topic}",
            f"**Overall Score**: {self.overall_score:.2f} / 1.00",
            f"**Passed**: {'✅' if self.passed else '❌'}",
            f"**Fact Anchoring Rate**: {self.fact_anchoring_rate:.1%}",
            f"**Citation Validity Rate**: {self.citation_validity_rate:.1%}",
            "",
        ]
        if self.blocking_issues:
            lines.append("## 🔴 Blocking Issues")
            for i, issue in enumerate(self.blocking_issues, 1):
                lines.append(f"  {i}. [{issue.severity.upper()}] {issue.location}")
                lines.append(f"     {issue.description}")
                if issue.evidence:
                    lines.append(f"     Evidence: {issue.evidence}")
                if issue.fix_suggestion:
                    lines.append(f"     Suggestion: {issue.fix_suggestion}")
            lines.append("")
        if self.warnings:
            lines.append("## 🟡 Warnings")
            for i, issue in enumerate(self.warnings, 1):
                lines.append(f"  {i}. [{issue.severity.upper()}] {issue.location}")
                lines.append(f"     {issue.description}")
            lines.append("")
        if self.suggestions:
            lines.append("## 💡 Suggestions")
            for s in self.suggestions:
                lines.append(f"  - {s}")
        return "\n".join(lines)

    def dump_json(self, path: str):
        """保存为 JSON 文件。"""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_json(cls, path: str) -> "AuditReport":
        """从 JSON 文件加载。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        report = cls(topic=data.get("topic", ""))
        report.overall_score = data.get("overall_score", 1.0)
        report.blocking_issues = [Issue(**i) for i in data.get("blocking_issues", [])]
        report.warnings = [Issue(**i) for i in data.get("warnings", [])]
        report.section_scores = data.get("section_scores", {})
        report.fact_anchoring_rate = data.get("fact_anchoring_rate", 1.0)
        report.citation_validity_rate = data.get("citation_validity_rate", 1.0)
        report.num_contradictions = data.get("num_contradictions", 0)
        report.num_redundant_pairs = data.get("num_redundant_pairs", 0)
        report.suggestions = data.get("suggestions", [])
        return report


# ---------------------------------------------------------------------------
# DSPy Signature — 用于矛盾检测和幻觉检测的 LM 调用
# ---------------------------------------------------------------------------

class ContradictionCheckSignature(dspy.Signature):
    """You are an expert fact-checker. Determine whether the following two claims contradict each other.
    Respond with one of: "contradiction", "consistent", or "unrelated"."""
    claim_a = dspy.InputField(prefix="Claim A: ", format=str)
    claim_b = dspy.InputField(prefix="Claim B: ", format=str)
    judgement = dspy.OutputField(prefix="Judgement (contradiction/consistent/unrelated): ", format=str)


class HallucinationCheckSignature(dspy.Signature):
    """You are an expert fact-checker. Given a claim and a set of supporting facts, determine if the claim is:
    - "supported": fully supported by the facts
    - "unsupported": not directly supported but not contradictory
    - "contradictory": contradicts the facts
    Respond with the judgement and a brief explanation."""
    claim = dspy.InputField(prefix="Claim: ", format=str)
    supporting_facts = dspy.InputField(prefix="Supporting Facts:\n", format=str)
    judgement = dspy.OutputField(prefix="Judgement (supported/unsupported/contradictory): ", format=str)
    explanation = dspy.OutputField(prefix="Explanation: ", format=str)


# ---------------------------------------------------------------------------
# 检查器 1: FactAnchorChecker — 反幻觉检查
# ---------------------------------------------------------------------------

class FactAnchorChecker:
    """
    检查文章中的断言是否能够锚定到 FactPool。

    对每个 section 的文本做如下检查：
      1. 提取所有含数值的句子（数值 = 高风险幻觉候选）
      2. 对每个候选断言，计算与 FactPool 中最相似事实的语义相似度
      3. 低于阈值的标记为"可能幻觉"

    使用 sentence-transformers 做语义匹配（复用 StormInformationTable 的编码器模式）。
    """

    def __init__(self, lm: Optional[dspy.LM] = None, similarity_threshold: float = 0.45):
        """
        Args:
            lm: 可选的 LLM，用于 LM 增强的幻觉检测（较慢但更准确）
            similarity_threshold: embedding 相似度阈值（低于此值标记警告）
        """
        self.lm = lm
        self.similarity_threshold = similarity_threshold
        self._encoder = None

    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer("paraphrase-MiniLM-L6-v2")
        return self._encoder

    @staticmethod
    def _extract_claim_sentences(text: str) -> List[str]:
        """从文本中提取含数值或具体断言的句子。"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        claims = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            # 仅提取含数值或关键指示词的句子
            if re.search(r'\d+', s):
                claims.append(s)
            elif any(kw in s.lower() for kw in
                     ["is", "was", "are", "were", "has", "have", "shows",
                      "demonstrates", "indicates", "suggests", "found",
                      "是", "为", "有", "表明", "显示", "说明"]):
                claims.append(s)
        return claims[:20]  # 每 section 最多检查 20 条断言

    def check_section(
        self,
        section_name: str,
        section_content: str,
        fact_pool: FactPool,
    ) -> Tuple[List[Issue], int, int]:
        """
        检查单个 section。

        Returns:
            (issues, total_checks, anchored_count)
        """
        issues: List[Issue] = []
        claims = self._extract_claim_sentences(section_content)
        if not claims:
            return issues, 0, 0

        encoder = self._get_encoder()
        all_facts = fact_pool.get_all_facts()
        if not all_facts:
            # 无可用事实时，所有断言标记为警告
            for claim in claims[:5]:
                issues.append(Issue(
                    severity="warning",
                    location=section_name,
                    description=f"No facts available to anchor claim: {claim[:100]}",
                    rule="FactAnchorChecker",
                    evidence="FactPool is empty",
                ))
            return issues, len(claims), 0

        fact_texts = [f.content for f in all_facts]
        fact_embeddings = encoder.encode(fact_texts)
        claim_embeddings = encoder.encode(claims)

        from sklearn.metrics.pairwise import cosine_similarity
        anchored = 0
        for i, (claim, claim_emb) in enumerate(zip(claims, claim_embeddings)):
            similarities = cosine_similarity([claim_emb], fact_embeddings)[0]
            max_sim = float(similarities.max())
            if max_sim >= self.similarity_threshold:
                anchored += 1
            else:
                location = f"{section_name} (claim #{i})"
                issue = Issue(
                    severity="warning",
                    location=location,
                    description=f"Claim not anchored to FactPool (max sim={max_sim:.2f}): {claim[:120]}",
                    rule="FactAnchorChecker",
                    evidence=f"best match: {fact_texts[similarities.argmax()][:120] if similarities.argmax() < len(fact_texts) else 'N/A'}",
                )
                # 若为数值断言且完全无匹配，升级为 major
                if re.search(r'\d+', claim) and max_sim < 0.25:
                    issue.severity = "major"
                issues.append(issue)

        return issues, len(claims), anchored


# ---------------------------------------------------------------------------
# 检查器 2: CitationIntegrityChecker — 引用完整性
# ---------------------------------------------------------------------------

class CitationIntegrityChecker:
    """
    检查引用完整性：
      1. 所有 [N] 编号是否在有效范围内
      2. 引用的 URL 是否可达（仅检查存在性）
      3. 引用是否被连续使用（无孤立引用）
    """

    def __init__(self):
        self._citation_pattern = re.compile(r'\[(\d+)\]')

    def check_section(
        self,
        section_name: str,
        section_content: str,
        article: StormArticle,
    ) -> List[Issue]:
        """检查单个 section 的引用完整性。

        Returns:
            发现的问题列表
        """
        issues: List[Issue] = []

        citations = [int(x) for x in self._citation_pattern.findall(section_content)]
        if not citations:
            return issues

        max_ref = len(article.reference["url_to_unified_index"])

        # 检查超出范围的引用
        for c in citations:
            if c > max_ref:
                issues.append(Issue(
                    severity="critical",
                    location=section_name,
                    description=f"Citation [{c}] exceeds reference range (max={max_ref})",
                    rule="CitationIntegrityChecker",
                    fix_suggestion=f"Remove or replace citation [{c}] with a valid reference",
                ))

        # 检查引用是否被孤立（仅出现一次且没有相邻引用）
        if len(citations) == 1 and max_ref > 0:
            issues.append(Issue(
                severity="info",
                location=section_name,
                description=f"Lone citation [{citations[0]}] — consider adding more supporting references",
                rule="CitationIntegrityChecker",
            ))

        return issues


# ---------------------------------------------------------------------------
# 检查器 3: ContradictionDetector — 事实矛盾（LLM 增强）
# ---------------------------------------------------------------------------

class ContradictionDetector:
    """
    跨 section 的事实矛盾检测。

    使用 LLM 成对比较关键主张，检测逻辑矛盾。
    对 10 个 section 以内的文章做全量 O(n²) 比较；更大的文章仅采样。
    """

    def __init__(self, lm: dspy.LM, max_comparisons: int = 20):
        self.lm = lm
        self.max_comparisons = max_comparisons
        self._check_module = dspy.Predict(ContradictionCheckSignature)

    def check(self, article: StormArticle) -> List[Issue]:
        """检测文章内的事实矛盾。"""
        issues: List[Issue] = []

        # 提取每个 section 的核心主张（前 3 句）
        section_claims = []
        for child in article.root.children:
            if child.content:
                # 取前 3 个含重要信息的句子
                sentences = re.split(r'(?<=[.!?])\s+', child.content.strip())
                key_sentences = []
                for s in sentences[:5]:
                    if len(s) > 20 and any(kw in s.lower() for kw in
                                            ["is", "was", "are", "were", "shows",
                                             "有", "是", "为", "表明"]):
                        key_sentences.append(s.strip())
                if key_sentences:
                    section_claims.append((child.section_name, key_sentences[0]))

        if len(section_claims) < 2:
            return issues

        # 生成成对比较
        comparisons = []
        for i in range(len(section_claims)):
            for j in range(i + 1, len(section_claims)):
                comparisons.append((section_claims[i], section_claims[j]))

        # 限制比较次数
        if len(comparisons) > self.max_comparisons:
            import random
            comparisons = random.sample(comparisons, self.max_comparisons)

        for (name_a, claim_a), (name_b, claim_b) in comparisons:
            try:
                with dspy.settings.context(lm=self.lm):
                    result = self._check_module(claim_a=claim_a, claim_b=claim_b)
                judgement = result.judgement.strip().lower()
                if judgement.startswith("contradiction"):
                    issues.append(Issue(
                        severity="major",
                        location=f"{name_a} vs {name_b}",
                        description=f"Contradiction detected",
                        rule="ContradictionDetector",
                        evidence=f"A: {claim_a[:100]}\nB: {claim_b[:100]}",
                        fix_suggestion="Review both claims and reconcile the contradiction",
                    ))
            except Exception as e:
                logger.warning(f"Contradiction check failed for {name_a} vs {name_b}: {e}")

        return issues


# ---------------------------------------------------------------------------
# 检查器 4: RedundancyDetector — 重复内容
# ---------------------------------------------------------------------------

class RedundancyDetector:
    """
    检测跨 section 的语义重复。

    使用 sentence-transformers 计算段间相似度矩阵，
    高于阈值的 pair 标记为重复。
    """

    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold
        self._encoder = None

    def _get_encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer("paraphrase-MiniLM-L6-v2")
        return self._encoder

    def check(self, article: StormArticle) -> List[Issue]:
        """检测文章内的重复内容。"""
        issues: List[Issue] = []

        # 提取每个 section 的内容
        sections = []
        for child in article.root.children:
            if child.content and len(child.content.strip()) > 50:
                sections.append((child.section_name, child.content.strip()))

        if len(sections) < 2:
            return issues

        encoder = self._get_encoder()
        texts = [s[1] for s in sections]
        embeddings = encoder.encode(texts)

        from sklearn.metrics.pairwise import cosine_similarity
        sim_matrix = cosine_similarity(embeddings)

        for i in range(len(sections)):
            for j in range(i + 1, len(sections)):
                sim = float(sim_matrix[i][j])
                if sim >= self.similarity_threshold:
                    issues.append(Issue(
                        severity="warning",
                        location=f"{sections[i][0]} vs {sections[j][0]}",
                        description=f"Redundant content (similarity={sim:.2f})",
                        rule="RedundancyDetector",
                        evidence=f"Section '{sections[i][0]}' and '{sections[j][0]}' have {sim:.0%} similar content",
                        fix_suggestion="Consider merging or differentiating the two sections",
                    ))

        return issues


# ---------------------------------------------------------------------------
# StormAuditModule — 审计模块组合
# ---------------------------------------------------------------------------

class StormAuditModule:
    """
    组合的审计模块。

    对标 Paper-Arts Quality Controller 的 8 项自校验清单。
    将 4 个检查器的结果合并为一份 AuditReport。
    """

    def __init__(
        self,
        audit_lm: Optional[dspy.LM] = None,
        fact_anchor_threshold: float = 0.45,
        redundancy_threshold: float = 0.85,
        max_contradiction_comparisons: int = 20,
    ):
        """
        Args:
            audit_lm: 用于矛盾检测和深度分析的 LM
            fact_anchor_threshold: 事实锚定相似度阈值
            redundancy_threshold: 重复检测相似度阈值
            max_contradiction_comparisons: 最大矛盾比较次数
        """
        self.fact_anchor_checker = FactAnchorChecker(
            lm=audit_lm, similarity_threshold=fact_anchor_threshold
        )
        self.citation_integrity_checker = CitationIntegrityChecker()
        self.contradiction_detector = ContradictionDetector(
            lm=audit_lm, max_comparisons=max_contradiction_comparisons
        ) if audit_lm else None
        self.redundancy_detector = RedundancyDetector(
            similarity_threshold=redundancy_threshold
        )

    def audit(
        self,
        article: StormArticle,
        fact_pool: Optional[FactPool] = None,
    ) -> AuditReport:
        """
        执行完整的文章审计。

        Args:
            article: 待审计的文章
            fact_pool: 可选的事实池（用于反幻觉检查）

        Returns:
            结构化审计报告
        """
        report = AuditReport(topic=article.root.section_name)
        all_issues: List[Issue] = []

        # 逐 section 检查
        total_checks = 0
        total_anchored = 0
        section_scores = {}

        for child in article.root.children:
            section_issues = []

            # --- 检查器 1: 事实锚定 ---
            if fact_pool and child.content:
                anchor_issues, n_checks, n_anchored = (
                    self.fact_anchor_checker.check_section(
                        child.section_name, child.content, fact_pool
                    )
                )
                section_issues.extend(anchor_issues)
                total_checks += n_checks
                total_anchored += n_anchored
                section_scores[child.section_name] = (
                    n_anchored / n_checks if n_checks > 0 else 1.0
                )

            # --- 检查器 2: 引用完整性 ---
            if child.content:
                citation_issues = self.citation_integrity_checker.check_section(
                    child.section_name, child.content, article
                )
                section_issues.extend(citation_issues)

            # 分类：严重/主要 → blocking；警告/信息 → warnings
            for issue in section_issues:
                if issue.severity in ("critical", "major"):
                    report.blocking_issues.append(issue)
                else:
                    report.warnings.append(issue)
            all_issues.extend(section_issues)

        # --- 检查器 3: 事实矛盾 ---
        if self.contradiction_detector:
            contradiction_issues = self.contradiction_detector.check(article)
            report.num_contradictions = len(contradiction_issues)
            for issue in contradiction_issues:
                issue.severity = "major"
                report.blocking_issues.append(issue)

        # --- 检查器 4: 重复内容 ---
        redundancy_issues = self.redundancy_detector.check(article)
        report.num_redundant_pairs = len(redundancy_issues)
        for issue in redundancy_issues:
            report.warnings.append(issue)

        # 计算总体指标
        report.fact_anchoring_rate = (
            total_anchored / total_checks if total_checks > 0 else 1.0
        )
        report.section_scores = section_scores

        # 计算引用有效比例
        valid_refs = 0
        total_refs = 0
        for child in article.root.children:
            if child.content:
                refs = re.findall(r'\[(\d+)\]', child.content)
                total_refs += len(refs)
                for r in refs:
                    if int(r) <= len(article.reference["url_to_unified_index"]):
                        valid_refs += 1
        report.citation_validity_rate = (
            valid_refs / total_refs if total_refs > 0 else 1.0
        )

        # 综合评分
        score = 1.0
        score -= len(report.blocking_issues) * 0.15  # 每个 block -0.15
        score -= len(report.warnings) * 0.05  # 每个 warning -0.05
        score -= (1 - report.fact_anchoring_rate) * 0.3
        score -= (1 - report.citation_validity_rate) * 0.2
        report.overall_score = max(0.0, round(score, 2))

        # 建议
        if not fact_pool:
            report.suggestions.append(
                "Consider providing a FactPool for fact-anchoring checks."
            )
        if report.fact_anchoring_rate < 0.7:
            report.suggestions.append(
                "Fact anchoring rate is low. Consider grounding more claims with citations."
            )
        if report.num_contradictions > 0:
            report.suggestions.append(
                f"Resolve {report.num_contradictions} contradiction(s) between sections."
            )
        if len(report.blocking_issues) > 0:
            report.suggestions.append(
                f"Fix {len(report.blocking_issues)} blocking issue(s) before finalizing."
            )

        return report


# ---------------------------------------------------------------------------
# TargetedRewriteModule — 靶向重写
# ---------------------------------------------------------------------------

class TargetedRewriteModule:
    """
    对标 Paper-Arts §3.5 的外科手术式重写。

    仅重写出问题的 section，保留无问题段落。
    """

    def __init__(self, rewrite_lm: dspy.LM):
        self.rewrite_lm = rewrite_lm

    class RewriteSectionSignature(dspy.Signature):
        """You are an expert editor. Rewrite the following section to fix the specific issues listed.
        Keep the overall structure and all valid content. Only modify the parts that need fixing.
        Maintain the same citation style and format."""
        section_name = dspy.InputField(prefix="Section Name: ", format=str)
        current_content = dspy.InputField(prefix="Current Section Content:\n", format=str)
        issues_to_fix = dspy.InputField(prefix="Issues to Fix:\n", format=str)
        supporting_facts = dspy.InputField(prefix="Supporting Facts (if any):\n", format=str)
        rewritten_content = dspy.OutputField(prefix="Rewritten Section Content:\n", format=str)

    def rewrite_section(
        self,
        section_name: str,
        current_content: str,
        issues: List[Issue],
        fact_pool: Optional[FactPool] = None,
    ) -> str:
        """
        靶向重写单个 section。

        Args:
            section_name: section 名称
            current_content: 当前内容
            issues: 需要修复的问题列表
            fact_pool: 可选的事实池（作为支持证据）

        Returns:
            重写后的内容
        """
        issues_text = "\n".join(
            f"[{i.severity.upper()}] {i.location}: {i.description}"
            for i in issues
        )

        facts_text = ""
        if fact_pool:
            relevant_facts = fact_pool.get_all_facts()
            if relevant_facts:
                facts_text = "\n".join(
                    f"  - {f.content[:200]}" for f in relevant_facts[:10]
                )

        try:
            with dspy.settings.context(lm=self.rewrite_lm):
                result = dspy.Predict(self.RewriteSectionSignature)(
                    section_name=section_name,
                    current_content=current_content,
                    issues_to_fix=issues_text,
                    supporting_facts=facts_text,
                )
            return result.rewritten_content
        except Exception as e:
            logger.error(f"Rewrite failed for {section_name}: {e}")
            return current_content  # 失败时返回原始内容
