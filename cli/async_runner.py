#!/usr/bin/env python3
"""
STORM Async Runner — 现代纯异步深度研究 CLI 执行入口 (Phase 2 Deep Research)
支持动态递归探索树 (Deep Tree-of-Thoughts)、本地与 Web 混合检索 (RRF) 与事实图谱冲突裁决。

用法:
  python3 -m cli.async_runner --topic "Vibe Coding in Software Engineering"
  python3 -m cli.async_runner --topic "..." --local-docs-dir ./raw_sources --deep-research
  python3 -m cli.async_runner --topic "..." --resume task_12345678
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 确保能加载当前工程模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core import (
    AsyncLLM,
    AsyncSearXNG,
    HybridRetriever,
    AsyncSTORMPipeline,
    WorkflowStateManager,
)


def load_config():
    """与 Web 共用 ConfigHub；失败时回退环境变量。"""
    try:
        from knowledge_storm.async_core import ConfigHub
        hub = ConfigHub()
        llm = hub.get_active_llm()
        search = hub.get_active_search()
        return {
            "llm": {
                "api_key": llm.api_key,
                "api_base": llm.base_url,
                "model": llm.model,
            },
            "search": {
                "params": {
                    "searxng_api_url": search.api_url,
                    "searxng_api_key": search.api_key,
                    "engines_academic": search.engines_academic,
                    "engines_chinese": search.engines_chinese,
                    "engines_general": search.engines_general,
                }
            },
        }
    except Exception:
        return {
            "llm": {
                "api_key": os.environ.get("DEEPSEEK_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
                "api_base": os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
                "model": "deepseek-chat",
            },
            "search": {
                "params": {
                    "searxng_api_url": os.environ.get("SEARXNG_API_URL", "https://search.nunch.uk/search"),
                    "searxng_api_key": "",
                }
            },
        }


async def main_async():
    parser = argparse.ArgumentParser(description="STORM 现代异步深度研究引擎 CLI (Deep Research)")
    parser.add_argument("--topic", type=str, required=True, help="研究论文或研报的主题")
    parser.add_argument("--resume", type=str, default=None, help="从指定的 task_id 断点继续执行")
    parser.add_argument("--output-dir", type=str, default="./results_async", help="输出目录")
    parser.add_argument("--turns", type=int, default=3, help="专家对话轮数（非 deep 模式）")
    parser.add_argument("--perspectives", type=int, default=3, help="研究视角数量")
    parser.add_argument(
        "--deep-research",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用动态递归探索树（--no-deep-research 关闭）",
    )
    parser.add_argument("--max-depth", type=int, default=2, help="深度研究最大递归层级")
    parser.add_argument("--local-docs-dir", type=str, default=None, help="挂载本地知识库目录进行混合检索 (BM25+RRF)")

    args = parser.parse_args()
    config = load_config()

    llm_cfg = config.get("llm", {})
    search_cfg = config.get("search", {}).get("params", {})

    llm = AsyncLLM(
        model=llm_cfg.get("model", "deepseek-chat"),
        api_key=llm_cfg.get("api_key", ""),
        api_base=llm_cfg.get("api_base", "https://api.deepseek.com"),
        temperature=0.7,
    )

    searx_retriever = AsyncSearXNG(
        api_url=search_cfg.get("searxng_api_url", "https://search.nunch.uk/search"),
        api_key=search_cfg.get("searxng_api_key", ""),
        engines_academic=search_cfg.get("engines_academic", "semantic_scholar,arxiv"),
        engines_chinese=search_cfg.get("engines_chinese", "baidu,zhihu"),
        engines_general=search_cfg.get("engines_general", "google,bing"),
    )

    # 若指定了本地语料库，启用多源混合检索器
    if args.local_docs_dir and Path(args.local_docs_dir).exists():
        retriever = HybridRetriever(
            web_retriever=searx_retriever,
            local_docs_dir=args.local_docs_dir,
        )
        print(f"📦 已挂载本地语料库并启用 RRF 混合检索: {args.local_docs_dir}")
    else:
        retriever = searx_retriever

    state_manager = WorkflowStateManager()
    pipeline = AsyncSTORMPipeline(
        llm=llm,
        retriever=retriever,
        output_dir=args.output_dir,
        state_manager=state_manager,
        max_conv_turns=args.turns,
        max_perspectives=args.perspectives,
        deep_research=args.deep_research,
        max_depth=args.max_depth,
    )

    def progress_callback(stage: str, data: any):
        icons = {
            "DISCOVERY_START": "🔍 [1/5] 开始发现多维度专家研究视角...",
            "DISCOVERY_COMPLETE": "✅ [1/5] 专家视角生成完成",
            "CURATION_START": "📚 [2/5] 开始知识策展与事实池构建...",
            "DEEP_RESEARCH_TREE_ACTIVE": "  🌳 启用动态递归探索树 (Tree-of-Thoughts 深度下钻)",
            "DEEP_EXPLORATION_NODE_START": "  ↳ 探索节点下钻",
            "CURATION_COMPLETE": "✅ [2/5] 事实池沉淀完毕",
            "OUTLINE_START": "📑 [3/5] 开始构建结构化学术大纲...",
            "OUTLINE_COMPLETE": "✅ [3/5] 学术大纲生成完成",
            "WRITING_START": "✍️  [4/5] 章节并行撰写与事实图谱构建中...",
            "FACT_GRAPH_EXTRACTING": "  ↳ 抽取实体关系图谱并检测跨信源分歧...",
            "SECTION_WRITTEN": "  ↳ 章节起草完成",
            "WRITING_COMPLETE": "✅ [4/5] 正文合成完毕（已注入信源分歧对照表）",
            "POLISH_START": "✨ [5/5] 开始结构审计与格式润色...",
            "COMPLETED": "🎉 [5/5] 深度研究全流程执行完毕！",
        }
        msg = icons.get(stage, f"⚙️  {stage}")
        if stage == "DISCOVERY_COMPLETE" and data:
            print(f"\n{msg}")
            for p in data.get("personas", []):
                print(f"   • {p['name']}: {p['description']}")
        elif stage == "DEEP_EXPLORATION_NODE_START" and data:
            print(f"   ↳ [深度 {data.get('depth')}] 视角: {data.get('perspective')} | 下钻: {data.get('query')[:50]}")
        elif stage == "CURATION_COMPLETE" and data:
            print(f"\n{msg} (共沉淀 {data.get('fact_count', 0)} 条原子事实)")
        elif stage == "OUTLINE_COMPLETE" and data:
            print(f"\n{msg}")
        elif stage == "SECTION_WRITTEN" and data:
            print(f"   ✓ 章节已生成: {data.get('section', '')}")
        elif stage == "WRITING_COMPLETE" and data:
            print(f"\n{msg} (正文 {data.get('article_len', 0)} 字，抽取关系边 {data.get('triples_count', 0)} 条)")
        elif stage == "COMPLETED" and data:
            print(f"\n{msg} (消耗 Token: {data.get('tokens_used', 0)})")
        elif "RESUMING" in stage:
            print(f"🔄 检测到已有断点，正在从任务状态恢复: {stage}")
        else:
            print(f"{msg}")
        sys.stdout.flush()

    print("=" * 60)
    print(f"🚀 启动 STORM 现代异步深度研究引擎 (Phase 2 Deep Research)")
    print(f"📌 主题: {args.topic}")
    print(f"🤖 模型: {llm.model} ({llm.api_base})")
    print(f"🌲 深度研究模式: {'开启 (Max Depth: ' + str(args.max_depth) + ')' if args.deep_research else '关闭'}")
    print("=" * 60)

    try:
        article = await pipeline.run(
            topic=args.topic,
            task_id=args.resume,
            progress_callback=progress_callback,
        )
    finally:
        await llm.close()
        if hasattr(retriever, "close"):
            await retriever.close()

    print("\n" + "=" * 60)
    print(f"📁 成果输出目录: {pipeline.output_dir}")
    print(f"📄 文章字数: {len(article.content)} 字")
    print(f"📚 参考文献数: {len(article.citations)} 篇")
    print("=" * 60)


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n⚠️ 收到中断信号 (Ctrl+C)。任务状态已安全保存至 SQLite Checkpoint，可随时使用 --resume 断点续跑。")


if __name__ == "__main__":
    main()
