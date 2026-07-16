"""
Manifest — 施工蓝图系统

对标 Paper-Arts V4.2 的 MANIFEST.md 6-Tag Protocol。

设计：
  - SectionBlueprint: 每章的施工图纸（6 标签）
  - Manifest: 全局蓝图（topic + sections + global constraints）
  - ManifestBuilder: 从 outline + FactPool + topic type 构建 Manifest

6-Tag Protocol 映射：
  1. Constraint_Check    → constraint_check: List[str]
  2. Reference_Standard  → reference_standard: str
  3. Data_Anchor         → data_anchors: List[DataAnchor]  (指向 FactPool 事实 ID)
  4. TRIZ_Requirement    → triz_requirement: Optional[str]
  5. 排版豁免            → exemption_notes: List[str]
  6. Chart_Requirement   → chart_requirements: List[ChartSpec]
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from ..interface import ArticleSectionNode
from .storm_dataclass import StormArticle
from .fact_pool import FactPool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class DataAnchor:
    """数据锚点 — 指向 FactPool 中的具体事实。"""
    fact_id: int
    description: str
    purpose: str = ""


@dataclass
class ChartSpec:
    """图表规格。"""
    chart_id: str
    chart_type: str  # flowchart, sequenceDiagram, classDiagram, etc.
    description: str
    data_source: str = ""


@dataclass
class SectionBlueprint:
    """
    单章施工图纸（对标 Paper-Arts 6-Tag Protocol）。

    6 个硬性标签 -> 6 个字段映射：
      Constraint_Check    → constraint_check
      Reference_Standard  → reference_standard
      Data_Anchor         → data_anchors
      TRIZ_Requirement    → triz_requirement
      排版豁免            → exemption_notes
      Chart_Requirement   → chart_requirements
    """
    section_name: str
    constraint_check: List[str] = field(default_factory=list)
    reference_standard: str = "GB/T 7714 numeric referencing"
    data_anchors: List[DataAnchor] = field(default_factory=list)
    triz_requirement: Optional[str] = None
    exemption_notes: List[str] = field(default_factory=list)
    chart_requirements: List[ChartSpec] = field(default_factory=list)

    def to_dict(self) -> Dict:
        result = {"section_name": self.section_name}
        if self.constraint_check:
            result["constraint_check"] = self.constraint_check
        if self.reference_standard:
            result["reference_standard"] = self.reference_standard
        if self.data_anchors:
            result["data_anchors"] = [
                {"fact_id": a.fact_id, "description": a.description, "purpose": a.purpose}
                for a in self.data_anchors
            ]
        if self.triz_requirement:
            result["triz_requirement"] = self.triz_requirement
        if self.exemption_notes:
            result["exemption_notes"] = self.exemption_notes
        if self.chart_requirements:
            result["chart_requirements"] = [
                {"chart_id": c.chart_id, "chart_type": c.chart_type,
                 "description": c.description, "data_source": c.data_source}
                for c in self.chart_requirements
            ]
        return result


@dataclass
class Manifest:
    """
    全局施工蓝图（对标 Paper-Arts MANIFEST.md）。

    Attributes:
        topic: 研究主题
        topic_type: topic 类型（来自 TopicClassifier）
        sections: 各章的 SectionBlueprint 列表
        global_constraints: 全局约束引用
    """
    topic: str
    topic_type: str = "general"
    sections: List[SectionBlueprint] = field(default_factory=list)
    global_constraints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "topic": self.topic,
            "topic_type": self.topic_type,
            "num_sections": len(self.sections),
            "sections": [s.to_dict() for s in self.sections],
            "global_constraints": self.global_constraints,
        }

    def to_text(self) -> str:
        """生成可读的 MARKDOWN 格式蓝图。"""
        lines = [
            f"# MANIFEST — {self.topic}",
            f"**Topic Type**: {self.topic_type}",
            f"**Sections**: {len(self.sections)}",
            "",
            "## Global Constraints",
        ]
        for c in self.global_constraints:
            lines.append(f"- {c}")
        lines.append("")

        for i, section in enumerate(self.sections, 1):
            lines.append(f"---")
            lines.append(f"## Section {i}: {section.section_name}")
            lines.append("")
            if section.constraint_check:
                lines.append("### Constraint_Check")
                for c in section.constraint_check:
                    lines.append(f"- [ ] {c}")
                lines.append("")
            if section.reference_standard:
                lines.append(f"### Reference_Standard")
                lines.append(f"{section.reference_standard}")
                lines.append("")
            if section.data_anchors:
                lines.append("### Data_Anchor")
                for a in section.data_anchors:
                    lines.append(f"- Fact #{a.fact_id}: {a.description} ({a.purpose})")
                lines.append("")
            if section.triz_requirement:
                lines.append(f"### TRIZ_Requirement")
                lines.append(f"{section.triz_requirement}")
                lines.append("")
            if section.exemption_notes:
                lines.append("### Exemption_Notes")
                for e in section.exemption_notes:
                    lines.append(f"- {e}")
                lines.append("")
            if section.chart_requirements:
                lines.append("### Chart_Requirement")
                for c in section.chart_requirements:
                    lines.append(f"- {c.chart_id} ({c.chart_type}): {c.description}")
                lines.append("")

        return "\n".join(lines)

    def dump_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# ManifestBuilder
# ---------------------------------------------------------------------------

class ManifestBuilder:
    """
    从 outline + FactPool + topic type 构建 Manifest。

    为每个 section 自动生成:
      - 基础约束（引用格式、事实锚定）
      - 数据锚点（从 FactPool 中推荐与 section 名称相关的事实）
      - 默认图表规格
    """

    def __init__(self, fact_pool: Optional[FactPool] = None):
        self.fact_pool = fact_pool

    def build(
        self,
        topic: str,
        outline: StormArticle,
        topic_type: str = "general",
    ) -> Manifest:
        """
        从 outline 构建 Manifest。

        Args:
            topic: 主题
            outline: StormArticle outline
            topic_type: 来自 TopicClassifier 的类型

        Returns:
            Manifest 实例
        """
        manifest = Manifest(
            topic=topic,
            topic_type=topic_type,
            global_constraints=self._get_global_constraints(topic_type),
        )

        for child in outline.root.children:
            blueprint = self._build_section_blueprint(child)
            manifest.sections.append(blueprint)

        return manifest

    def _get_global_constraints(self, topic_type: str) -> List[str]:
        """根据 topic 类型返回全局约束。"""
        constraints = [
            "All citations must follow GB/T 7714 numeric referencing style",
            "All numerical claims should be anchored to FactPool entries",
            "Maintain encyclopedic tone (third-person, objective)",
        ]
        if topic_type == "technology":
            constraints.append("Include architecture/flow diagrams where applicable")
        elif topic_type == "scientific_concept":
            constraints.append("Include mechanism illustrations where applicable")
        elif topic_type == "historical_event":
            constraints.append("Maintain chronological narrative structure")
        return constraints

    def _build_section_blueprint(self, node: ArticleSectionNode) -> SectionBlueprint:
        """从单个 section node 构建蓝图。"""
        blueprint = SectionBlueprint(section_name=node.section_name)

        # 基本约束
        blueprint.constraint_check = [
            f"Check citation format in '{node.section_name}'",
            "Check fact anchoring for numerical claims",
        ]

        # 从 FactPool 推荐数据锚点
        if self.fact_pool:
            # 使用关键词匹配：检查 FactPool 中哪些事实与 section 名称相关
            section_keywords = set(node.section_name.lower().split())
            for fact in self.fact_pool.get_all_facts():
                fact_keywords = set(fact.content.lower().split())
                overlap = section_keywords & fact_keywords
                if len(overlap) >= 2:  # 至少 2 个关键词重叠
                    blueprint.data_anchors.append(DataAnchor(
                        fact_id=fact.fact_id,
                        description=fact.content[:100],
                        purpose=f"Supporting evidence for '{node.section_name}'",
                    ))

            # 限制数据锚点数量
            if len(blueprint.data_anchors) > 5:
                blueprint.data_anchors = blueprint.data_anchors[:5]

        return blueprint

    def add_triz_requirement(self, blueprint: SectionBlueprint,
                              contradiction_type: str = "technical",
                              principle: str = ""):
        """为 section 添加 TRIZ 要求（对标 Paper-Arts 的 TRIZ 骨架）。"""
        if contradiction_type == "technical":
            blueprint.triz_requirement = (
                f"Apply TRIZ technical contradiction resolution. "
                f"Identify the conflicting parameters and apply "
                f"{principle or 'appropriate 40 Inventive Principles'}."
            )
        elif contradiction_type == "physical":
            blueprint.triz_requirement = (
                f"Apply TRIZ physical contradiction resolution. "
                f"Use separation principles (space/time/condition) "
                f"{principle or ''}."
            )
        else:
            blueprint.triz_requirement = contradiction_type

    def add_chart_requirement(
        self,
        blueprint: SectionBlueprint,
        chart_id: str,
        chart_type: str,
        description: str,
    ):
        """为 section 添加图表要求。"""
        blueprint.chart_requirements.append(ChartSpec(
            chart_id=chart_id,
            chart_type=chart_type,
            description=description,
        ))
