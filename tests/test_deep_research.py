import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path

# 添加当前工程路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core.hybrid_retriever import LocalBM25Index, HybridRetriever
from knowledge_storm.async_core.deep_exploration import DynamicExplorationTree, ExplorationNode
from knowledge_storm.async_core.fact_graph import FactGraph, GraphNode, GraphEdge, DiscrepancyItem
from knowledge_storm.async_core.models import SearchSnippet, Persona, FactPool


def test_bm25_index():
    print("--> Test 1: Local BM25 Indexing & Search...")
    index = LocalBM25Index()
    index.add_document("DeepSeek R1 adopts multi-stage reinforcement learning without cold start.", "Paper A", "http://arxiv/1")
    index.add_document("Vibe coding emphasizes guiding LLM generated source code interactively.", "Wiki B", "http://wiki/2")
    index._finalize_index()

    results = index.search("reinforcement learning", top_k=2)
    assert len(results) >= 1
    assert "arxiv" in results[0].url
    print("  ✓ BM25 Index passed.")


def test_fact_graph_and_discrepancy_table():
    print("--> Test 2: FactGraph and Discrepancy Matrix...")
    graph = FactGraph()
    graph.add_relation("Vibe Coding", "Technical Debt", "increases", "Reduces refactoring frequency", "http://wsj.com")
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 1

    # 添加分歧项
    graph.discrepancies.append(
        DiscrepancyItem(
            topic_aspect="Developer Productivity",
            source_a_claim="METR study found 19% slowdown for experienced devs",
            source_a_url="https://metr.org/eval",
            source_b_claim="YC reported 4x faster MVP delivery",
            source_b_url="https://ycombinator.com/report",
            reconciliation_analysis="Difference arises from codebase complexity (greenfield MVP vs complex enterprise repo).",
        )
    )
    md_table = graph.render_discrepancy_table_markdown()
    assert "多信源争议与分歧对照分析" in md_table
    assert "METR" in md_table
    assert "YC reported" in md_table
    print("  ✓ FactGraph & Discrepancy Matrix passed.")


def main():
    print("=" * 55)
    print("Running Phase 2 Deep Research Modules Integrity Tests")
    print("=" * 55)
    test_bm25_index()
    test_fact_graph_and_discrepancy_table()
    print("\nALL PHASE 2 UNIT TESTS PASSED SUCCESSFULLY! 🌲")


if __name__ == "__main__":
    main()
