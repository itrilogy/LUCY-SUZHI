import asyncio
import os
import sys
import tempfile
import json
from pathlib import Path

# 添加工程根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core import (
    AsyncLLM,
    AsyncSearXNG,
    AsyncSTORMPipeline,
    WorkflowStateManager,
    LocalKnowledgeHub,
)
from knowledge_storm.async_core.models import SearchSnippet


class MockLLM(AsyncLLM):
    """用于端到端离线全流程测试的高性能 Mock LLM。"""

    def __init__(self):
        super().__init__(model="mock-model", api_key="mock-key", api_base="http://mock")

    async def generate(self, prompt: str, **kwargs) -> str:
        self.total_tokens_used += 100
        p_lower = prompt.lower()
        # 1. 视角发现
        if "distinct personas/experts" in p_lower:
            return "1. Technical Architect: Underlying mechanism analysis\n2. Systems Engineer: Scalability and benchmark evaluation\n3. Security Auditor: Vulnerability and risk assessment"
        # 2. 深度探索下钻子问题
        elif "knowledge gaps" in p_lower:
            return "1. Latency Bottleneck: Why pipeline latency spikes\n2. Memory Footprint: Memory overhead under high concurrency"
        # 3. 事实提取与信息增益
        elif "atomic factual statements" in p_lower:
            return "[GAIN]: 0.85\n[FACTS]:\n- DeepSeek R1 achieves SOTA performance via pure RL without cold start.\n- Async pipeline reduces total I/O blocking by 80%."
        # 4. 大纲生成
        elif "article outline" in p_lower:
            return "## Overview and Background\n### Historical Context\n## Core Architecture and Mechanisms\n### Dynamic Exploration Tree\n## Empirical Evaluation and Benchmarks\n## Challenges and Future Outlook"
        # 5. 事实图谱三元组与冲突
        elif "entity-relation triples" in p_lower:
            return json.dumps({
                "triples": [
                    {"source": "Async Engine", "relation": "reduces", "target": "IO Blocking", "claim": "Reduces 80% blocking", "source_index": 1}
                ],
                "discrepancies": [
                    {
                        "topic_aspect": "Throughput Scaling",
                        "source_a_claim": "Paper A claims 2x gain",
                        "source_a_index": 1,
                        "source_b_claim": "Paper B claims 5x gain",
                        "source_b_index": 1,
                        "reconciliation_analysis": "Different batch size evaluation settings."
                    }
                ]
            })
        # 6. Mermaid 流程图生成
        elif "mermaid diagram" in p_lower:
            return "```mermaid\nflowchart TD\n  A[Async Core] --> B[Task Dispatcher]\n  B --> C[Fact Pool]\n```"
        # 7. 学术评审
        elif "senior editor-in-chief" in p_lower:
            return json.dumps({
                "overall_score": 92,
                "dimension_scores": [
                    {"dimension": "Factual Rigor", "score": 95, "feedback": "Rigorous grounding"},
                    {"dimension": "Citation Density", "score": 90, "feedback": "Exact citations"}
                ],
                "flawed_sections": [],
                "critical_suggestions": []
            })
        # 8. 正文写作
        else:
            return "Modern software architectures increasingly rely on asynchronous event-driven pipelines [1]. This significantly mitigates global interpreter lock contentions [1]."


class MockRetriever:
    """Mock 检索引擎。"""
    async def search(self, query: str, top_k: int = 5):
        return [
            SearchSnippet(
                url="https://arxiv.org/abs/2501.12948",
                title="DeepSeek-R1 Technical Report",
                content="DeepSeek-R1 demonstrates reasoning capabilities through large-scale reinforcement learning.",
                engine="mock_searxng",
            )
        ]


async def run_end_to_end_test():
    print("--> Running End-to-End STORM Full Pipeline Integration Test...")
    with tempfile.TemporaryDirectory() as temp_dir:
        state_db = Path(temp_dir) / "test_workflow.db"
        state_mgr = WorkflowStateManager(db_path=state_db)
        llm = MockLLM()
        retriever = MockRetriever()

        pipeline = AsyncSTORMPipeline(
            llm=llm,
            retriever=retriever,
            output_dir=temp_dir,
            state_manager=state_mgr,
            deep_research=True,
            max_depth=2,
            enable_review=True,
            enable_diagrams=True,
        )

        stages_visited = []

        def progress_cb(stage: str, data: any):
            stages_visited.append(stage)

        task_id = "test_e2e_task_001"
        topic = "DeepSeek R1 and Asynchronous AI Agent Architectures"

        article = await pipeline.run(
            topic=topic,
            task_id=task_id,
            progress_callback=progress_cb,
        )

        # 验证文章产出
        assert article is not None
        assert len(article.content) > 200
        assert "## Overview and Background" in article.content
        assert "```mermaid" in article.content  # 图表成功生成
        assert "References" in article.content  # 参考文献成功生成
        assert "多信源争议与分歧对照分析" in article.content  # 矛盾矩阵成功嵌入

        # 验证文件系统导出物
        out_dir = Path(temp_dir) / task_id
        assert (out_dir / "article.md").exists()
        assert (out_dir / "outline.md").exists()
        assert (out_dir / "citations.json").exists()
        assert (out_dir / "slides.marp.md").exists()
        assert (out_dir / "report_standalone.html").exists()

        # 验证 SQLite 状态机持久化
        cp = state_mgr.load_checkpoint(task_id)
        assert cp is not None
        assert cp.stage == "COMPLETED"

        # 验证本地知识库索引
        kb = LocalKnowledgeHub(db_path=Path(temp_dir) / "kb.db")
        kb.index_completed_research(cp)
        prior_facts = kb.search_prior_knowledge("DeepSeek", limit=5)
        assert len(prior_facts) >= 1

        print(f"  ✓ Full Pipeline E2E Test Passed! (Visited stages: {len(stages_visited)})")


def main():
    print("=" * 60)
    print("Executing STORM End-to-End Functionality & Usability Test")
    print("=" * 60)
    asyncio.run(run_end_to_end_test())
    print("\nALL FUNCTIONALITY & USABILITY INTEGRITY TESTS PASSED! 🏆")


if __name__ == "__main__":
    main()
