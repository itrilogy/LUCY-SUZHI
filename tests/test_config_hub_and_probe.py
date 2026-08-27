import asyncio
import os
import sys
import tempfile
from pathlib import Path

# 添加工程根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core.config_hub import (
    ConfigHub,
    StormSystemConfig,
    probe_llm_endpoint,
    probe_search_endpoint,
)
from knowledge_storm.async_core.retriever import SearchCacheManager, SearchSnippet


def test_config_hub_load_and_mask():
    print("--> Test 1: ConfigHub Loading & Masking...")
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as tf:
        tf_path = Path(tf.name)

    hub = ConfigHub(config_path=tf_path)
    masked = hub.get_masked_config()
    assert "deepseek" in masked["llm_providers"]
    assert "searxng" in masked["search_providers"]
    assert "api_key_masked" in masked["llm_providers"]["deepseek"]

    # 测试保存
    cfg = hub.system_config
    cfg.active_llm_provider = "siliconflow"
    hub.save_config(cfg)

    # 重新加载验证
    hub2 = ConfigHub(config_path=tf_path)
    assert hub2.system_config.active_llm_provider == "siliconflow"
    tf_path.unlink(missing_ok=True)
    print("  ✓ ConfigHub load/save/mask passed.")


def test_search_cache():
    print("--> Test 2: SQLite Search Cache...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = Path(tf.name)

    cache = SearchCacheManager(db_path=db_path, ttl_seconds=3600)
    query = "Transformer scaling laws"
    assert cache.get(query) is None

    test_snips = [
        SearchSnippet(url="http://arxiv/1", title="Scaling Law", content="Evidence content", engine="searxng")
    ]
    cache.set(query, test_snips)

    cached_res = cache.get(query)
    assert cached_res is not None
    assert len(cached_res) == 1
    assert cached_res[0].url == "http://arxiv/1"

    db_path.unlink(missing_ok=True)
    print("  ✓ Search Cache passed.")


async def test_async_probe():
    print("--> Test 3: Endpoint Probe...")
    res = await probe_llm_endpoint(base_url="http://127.0.0.1:9999", timeout=0.5)
    assert res["status"] in ("OFFLINE", "HTTP_ERROR")
    print("  ✓ Async Probe passed.")


def main():
    print("=" * 55)
    print("Running ConfigHub & Search Cache Integration Tests")
    print("=" * 55)
    test_config_hub_load_and_mask()
    test_search_cache()
    asyncio.run(test_async_probe())
    print("\nALL CONFIGHUB TESTS PASSED SUCCESSFULLY! ⚙️")


if __name__ == "__main__":
    main()
