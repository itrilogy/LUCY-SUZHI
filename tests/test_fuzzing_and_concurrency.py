"""
STORM 测试套件 7 — Fuzzing 异常鲁棒性与并发多任务隔离测试
验证建议书 6.1 (LLM 异常防御) 与 6.2 (并发隔离与状态机互不污染)。
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 注入项目根路径
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from knowledge_storm.async_core import (
    safe_extract_json,
    FactPool,
    ArticleDraft,
    Outline,
    WorkflowStateManager,
    TaskCheckpoint,
)


class TestFuzzingAndConcurrency(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_concurrent.db")
        self.state_mgr = WorkflowStateManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_safe_extract_json_fuzzing(self):
        """测试极端与恶意 LLM 返回格式下的 JSON 抽取能力。"""
        # 1. 包含 <think> 推理标签
        think_text = "<think>Here is some deep thought</think>\n```json\n{\"status\": \"OK\", \"count\": 42}\n```"
        res1 = safe_extract_json(think_text)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.get("count"), 42)

        # 2. 纯代码块包裹
        md_text = "```\n{\"key\": \"value\"}\n```"
        res2 = safe_extract_json(md_text)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get("key"), "value")

        # 3. 前后带大量废话的裸括号
        noisy_text = "Here is your JSON response: {\"valid\": true, \"items\": [1, 2]} Hope this helps!"
        res3 = safe_extract_json(noisy_text)
        self.assertIsNotNone(res3)
        self.assertTrue(res3.get("valid"))

        # 4. 空字符串与非字符串防御
        self.assertIsNone(safe_extract_json(""))
        self.assertIsNone(safe_extract_json(None))
        self.assertIsNone(safe_extract_json("Invalid non-json string"))

    async def test_fact_pool_deduplication(self):
        """测试事实池智能去重。"""
        pool = FactPool()
        # 相同事实添加 3 次
        f1 = pool.add_fact("尼古丁袋是口含烟替代品", "https://example.com/1", "T1")
        f2 = pool.add_fact("尼古丁袋是口含烟替代品。", "https://example.com/1", "T1")
        f3 = pool.add_fact("  尼古丁袋是口含烟替代品  ", "https://example.com/1", "T1")
        # 不同事实添加 1 次
        f4 = pool.add_fact("尼古丁袋在欧洲市场占有率持续攀升", "https://example.com/2", "T2")

        self.assertEqual(len(pool.facts), 2)
        self.assertEqual(f1.fact_id, f2.fact_id)
        self.assertEqual(f1.fact_id, f3.fact_id)
        self.assertNotEqual(f1.fact_id, f4.fact_id)

    async def test_concurrent_tasks_state_isolation(self):
        """测试多任务高并发写入与状态快照隔离。"""
        task_ids = [f"task_iso_{i}" for i in range(5)]
        
        async def _run_task_worker(t_id: str, topic: str):
            cp = TaskCheckpoint(task_id=t_id, topic=topic, stage="INIT")
            self.state_mgr.save_checkpoint(cp)
            
            # 阶段 1
            cp.stage = "DISCOVERY"
            self.state_mgr.save_checkpoint(cp)
            await asyncio.sleep(0.01)
            
            # 阶段 2
            pool = FactPool()
            pool.add_fact(f"Unique fact for {t_id}", f"https://example.com/{t_id}", f"Title {t_id}")
            cp.fact_pool = pool
            cp.stage = "CURATION"
            self.state_mgr.save_checkpoint(cp)
            await asyncio.sleep(0.01)
            
            # 阶段 3
            cp.stage = "COMPLETED"
            draft = ArticleDraft(
                topic=topic,
                outline=Outline(topic=topic),
                content=f"# {topic}\n\nContent for {t_id}",
            )
            draft.record_version("v1")
            cp.article_draft = draft
            self.state_mgr.save_checkpoint(cp)

        # 5 个任务并发执行
        tasks = [_run_task_worker(t_id, f"Topic for {t_id}") for t_id in task_ids]
        await asyncio.gather(*tasks)

        # 校验各自独立性与完整性
        for t_id in task_ids:
            loaded_cp = self.state_mgr.load_checkpoint(t_id)
            self.assertIsNotNone(loaded_cp)
            self.assertEqual(loaded_cp.stage, "COMPLETED")
            self.assertEqual(len(loaded_cp.fact_pool.facts), 1)
            self.assertEqual(loaded_cp.fact_pool.facts[0].claim, f"Unique fact for {t_id}")
            self.assertIn(f"Content for {t_id}", loaded_cp.article_draft.content)
            self.assertEqual(len(loaded_cp.article_draft.history_versions), 1)


if __name__ == "__main__":
    unittest.main()
