import asyncio
import os
import sys
import tempfile
from pathlib import Path

# 添加工程根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core.diagram_generator import DiagramGenerator
from knowledge_storm.async_core.reviewer import AcademicReviewReport, ReviewDimensionScore
from knowledge_storm.async_core.exporter import MultiFormatExporter
from knowledge_storm.async_core.local_knowledge_hub import LocalKnowledgeHub
from knowledge_storm.async_core.models import ArticleDraft, Outline, OutlineSection, FactPool
from knowledge_storm.async_core.state_manager import TaskCheckpoint


def test_diagram_generator():
    print("--> Test 1: DiagramGenerator SVG bar chart...")
    gen = DiagramGenerator(llm=None)
    svg = gen.generate_svg_comparison_bar_chart(
        title="Inference Speedup Comparison",
        labels=["Baseline (FP16)", "vLLM PagedAttn", "DeepSeek R1 (FP8)"],
        values=[1.0, 2.8, 5.2],
        unit="x",
    )
    assert "<svg" in svg
    assert "Inference Speedup Comparison" in svg
    assert "DeepSeek R1" in svg
    print("  ✓ DiagramGenerator SVG test passed.")


def test_multiformat_exporter():
    print("--> Test 2: MultiFormatExporter (Slides & Standalone HTML)...")
    exporter = MultiFormatExporter()
    outline = Outline(
        topic="Modern AI Architectures",
        sections=[OutlineSection(level=1, title="Introduction"), OutlineSection(level=1, title="Mamba vs Transformer")],
    )
    draft = ArticleDraft(
        topic="Modern AI Architectures",
        outline=outline,
        content="## Introduction\nAI systems evolve rapidly [1].\n\n## Mamba vs Transformer\nState space models show O(N) complexity [2].",
        citations={
            1: {"title": "AI Survey 2026", "url": "https://arxiv.org/1"},
            2: {"title": "Mamba Paper", "url": "https://arxiv.org/2"},
        },
    )

    # 1. 验证 Marp Slides
    slides_md = exporter.generate_marp_slides_markdown(draft)
    assert "marp: true" in slides_md
    assert "Modern AI Architectures" in slides_md
    assert "Mamba vs Transformer" in slides_md

    # 2. 验证 Standalone HTML
    html_report = exporter.generate_standalone_html_report(draft)
    assert "<!DOCTYPE html>" in html_report
    assert "Modern AI Architectures - STORM 深度研报" in html_report
    assert 'class="citation"' in html_report
    print("  ✓ MultiFormatExporter test passed.")


def test_local_knowledge_hub():
    print("--> Test 3: LocalKnowledgeHub SQLite Index & Cross-Search...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = Path(tf.name)

    hub = LocalKnowledgeHub(db_path=db_path)
    fp = FactPool()
    fp.add_fact("DeepSeek R1 adopts multi-stage RL.", "https://deepseek.com", "R1 Report", "Architecture", source_quality=1.2)
    fp.add_fact("尼古丁袋在欧美口含烟市场年复合增长率超过30%", "https://tobacco-research.org", "全球烟草减害研报", "市场监管", source_quality=1.2)

    cp = TaskCheckpoint(
        task_id="task_test_01",
        topic="尼古丁袋市场趋势与技术机理",
        stage="COMPLETED",
        fact_pool=fp,
        article_draft=ArticleDraft(
            topic="尼古丁袋市场趋势与技术机理",
            outline=Outline(topic="尼古丁袋", sections=[]),
            content="Full content",
            citations=fp.get_citations_dict(),
        ),
    )

    hub.index_completed_research(cp)

    # 1. 英文跨任务先验检索
    results_en = hub.search_prior_knowledge("DeepSeek Technical", limit=3)
    assert len(results_en) >= 1
    assert "multi-stage RL" in results_en[0]["claim"]

    # 2. 中文跨任务先验检索
    results_zh = hub.search_prior_knowledge("尼古丁袋的市场未来趋势", limit=3)
    assert len(results_zh) >= 1
    assert "年复合增长率" in results_zh[0]["claim"]

    db_path.unlink(missing_ok=True)
    print("  ✓ LocalKnowledgeHub passed (EN & ZH cross-search verified).")


def main():
    print("=" * 55)
    print("Running Advanced Plans (1, 2, 4 + Local KB) Integrity Tests")
    print("=" * 55)
    test_diagram_generator()
    test_multiformat_exporter()
    test_local_knowledge_hub()
    print("\nALL ADVANCED PLANS TESTS PASSED SUCCESSFULLY! 🚀")


if __name__ == "__main__":
    main()
