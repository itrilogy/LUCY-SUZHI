"""
TopicClassifier — 范式路由雏形

对标 Paper-Arts V4.2 §0.2 的 5 种论文类型路由表。

核心设计：
  1. 零样本 TopicClassifier 将 topic 分类为预定义类型
  2. PARADIGM_OUTLINE_HINTS 为不同类型提供 outline 结构偏好
  3. 分类结果注入到 OutlineGeneration 的 prompt 中

Topic 分类体系：
  - biography:       人物传记
  - historical_event: 历史事件
  - scientific_concept: 科学概念
  - technology:      技术/方法
  - organization:    组织机构
  - geography:       地理
  - creative_work:   作品
  - general:         通用（fallback）
"""

import logging
from typing import Dict, List, Optional

import dspy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DSPy Signature
# ---------------------------------------------------------------------------

class ClassifyTopicSignature(dspy.Signature):
    """Classify the given topic into one of the predefined categories.
    Respond with ONLY the category name."""
    topic = dspy.InputField(prefix="Topic: ", format=str)
    categories = dspy.InputField(prefix="Available categories: ", format=str)
    category = dspy.OutputField(prefix="Category: ", format=str)


# ---------------------------------------------------------------------------
# 类型定义与 Outline 提示
# ---------------------------------------------------------------------------

TOPIC_TAXONOMY = [
    "biography",
    "historical_event",
    "scientific_concept",
    "technology",
    "organization",
    "geography",
    "creative_work",
    "general",
]

PARADIGM_OUTLINE_HINTS: Dict[str, str] = {
    "biography": (
        "This is a biography. Include sections covering: "
        "Early life and education, Career and achievements, "
        "Personal life, Legacy and influence."
    ),
    "historical_event": (
        "This is a historical event. Include sections covering: "
        "Background and context, Timeline of events, "
        "Causes and contributing factors, Consequences and impact, "
        "Historiography and interpretations."
    ),
    "scientific_concept": (
        "This is a scientific concept. Include sections covering: "
        "Definition and overview, History of discovery, "
        "Core mechanisms and principles, Applications and use cases, "
        "Related concepts and comparisons, Limitations."
    ),
    "technology": (
        "This is a technology or method. Include sections covering: "
        "History and background, Technical details and architecture, "
        "Applications and use cases, Comparisons with alternatives, "
        "Limitations and challenges."
    ),
    "organization": (
        "This is an organization. Include sections covering: "
        "History and founding, Structure and governance, "
        "Products and services, Impact and recognition, "
        "Criticism and controversies."
    ),
    "geography": (
        "This is a geographic entity. Include sections covering: "
        "Geography and climate, History, Demographics, "
        "Economy, Culture and attractions."
    ),
    "creative_work": (
        "This is a creative work. Include sections covering: "
        "Background and creation, Plot or content summary, "
        "Themes and analysis, Reception and criticism, Legacy."
    ),
    "general": (
        "This is a general topic. Create a well-structured outline "
        "with sections covering: Introduction/Background, "
        "Core content organized by subtopics, Related concepts, "
        "Conclusions or significance."
    ),
}


# ---------------------------------------------------------------------------
# TopicClassifier
# ---------------------------------------------------------------------------

class TopicClassifier(dspy.Module):
    """
    零样本 topic 类型分类器。

    将 topic 分类到 TOPIC_TAXONOMY 中的类型之一。
    返回类型名称及对应的 outline 提示。
    """

    def __init__(self, engine: Optional[dspy.dsp.LM] = None):
        super().__init__()
        self._classifier = dspy.Predict(ClassifyTopicSignature)
        self.engine = engine

    def forward(self, topic: str) -> dspy.Prediction:
        """
        对 topic 进行分类。

        Args:
            topic: 研究主题

        Returns:
            dspy.Prediction 包含:
              - category: 分类结果
              - outline_hint: 对应类型的 outline 提示
              - confidence: 置信度（仅摘要分类器才有意义，此处固定为 1.0）
        """
        categories_str = ", ".join(TOPIC_TAXONOMY)

        lm_context = {}
        if self.engine:
            lm_context = {"lm": self.engine}

        with dspy.settings.context(**lm_context):
            try:
                result = self._classifier(topic=topic, categories=categories_str)
                category = result.category.strip().lower()

                # 验证分类结果
                if category not in TOPIC_TAXONOMY:
                    logger.warning(
                        f"Classifier returned unknown category '{category}', "
                        f"falling back to 'general'"
                    )
                    category = "general"
            except Exception as e:
                logger.error(f"Topic classification failed: {e}")
                category = "general"

        outline_hint = PARADIGM_OUTLINE_HINTS.get(category, PARADIGM_OUTLINE_HINTS["general"])

        return dspy.Prediction(
            category=category,
            outline_hint=outline_hint,
            confidence=1.0,
        )


# ---------------------------------------------------------------------------
# 便利函数
# ---------------------------------------------------------------------------

def get_outline_hint(topic_type: str) -> str:
    """根据 topic 类型获取 outline 提示。"""
    return PARADIGM_OUTLINE_HINTS.get(topic_type, PARADIGM_OUTLINE_HINTS["general"])
