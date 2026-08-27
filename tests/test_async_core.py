import asyncio
import os
import sys
import shutil
import tempfile
from pathlib import Path

# 添加当前目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core.models import (
    Persona,
    FactEntry,
    FactPool,
    SearchSnippet,
    OutlineSection,
    Outline,
    DialogueTurn,
    ArticleDraft,
)
from knowledge_storm.async_core.state_manager import WorkflowStateManager, TaskCheckpoint


def test_models_and_factpool():
    print("--> Test 1: Pydantic Models & FactPool...")
    pool = FactPool()
    f1 = pool.add_fact(claim="DeepSeek-R1 uses pure RL.", url="https://arxiv.org/abs/1", title="R1 Paper", perspective="Architect")
    f2 = pool.add_fact(claim="Vibe coding coined by Karpathy.", url="https://wikipedia.org/wiki/vibe", title="Wikipedia", perspective="Historian")
    
    assert len(pool.facts) == 2
    assert pool.url_to_index["https://arxiv.org/abs/1"] == 1
    assert pool.url_to_index["https://wikipedia.org/wiki/vibe"] == 2
    
    citations = pool.get_citations_dict()
    assert 1 in citations and 2 in citations
    assert citations[1]["title"] == "R1 Paper"
    print("  ✓ Models and FactPool passed.")


def test_state_manager_and_checkpoints():
    print("--> Test 2: WorkflowStateManager SQLite Checkpoint & Resume...")
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "test_workflow.db")
    
    try:
        mgr = WorkflowStateManager(db_path=db_file)
        
        # 1. 写入初始阶段
        cp = TaskCheckpoint(
            task_id="test_task_001",
            topic="Quantum Computing",
            stage="INIT",
        )
        mgr.save_checkpoint(cp)
        
        # 2. 读取并验证
        loaded = mgr.load_checkpoint("test_task_001")
        assert loaded is not None
        assert loaded.topic == "Quantum Computing"
        assert loaded.stage == "INIT"
        
        # 3. 更新为 CURATION 阶段并写入 FactPool
        loaded.stage = "CURATION"
        loaded.fact_pool.add_fact(claim="Qubits exhibit superposition.", url="https://nature.com/qubit", title="Nature")
        mgr.save_checkpoint(loaded)
        
        # 4. 再次恢复验证
        reloaded = mgr.load_checkpoint("test_task_001")
        assert reloaded.stage == "CURATION"
        assert len(reloaded.fact_pool.facts) == 1
        assert reloaded.fact_pool.facts[0].claim == "Qubits exhibit superposition."
        print("  ✓ SQLite Checkpoint & Resume passed.")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    print("=" * 50)
    print("Running Async Core Integrity & Resumability Tests")
    print("=" * 50)
    test_models_and_factpool()
    test_state_manager_and_checkpoints()
    print("\nALL ASYNC CORE TESTS PASSED SUCCESSFULLY! 🚀")


if __name__ == "__main__":
    main()
