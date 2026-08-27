import asyncio
import os
import sys
import tempfile
from pathlib import Path

# 添加当前工程根路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowledge_storm.async_core.models import ArticleDraft, Outline, OutlineSection
from knowledge_storm.async_core.typst_compiler import TypstCompiler
from server.app import app


def test_typst_compiler():
    print("--> Test 1: TypstCompiler Source Generation...")
    compiler = TypstCompiler()

    outline = Outline(
        topic="AI Systems in 2026",
        sections=[
            OutlineSection(level=1, title="Introduction"),
            OutlineSection(level=1, title="Core Architecture"),
        ],
    )
    draft = ArticleDraft(
        topic="AI Systems in 2026",
        outline=outline,
        content="## Introduction\nRecent advancements [1] show remarkable scaling laws [2].\n\n## Core Architecture\nTransformer architectures remain dominant.",
        citations={
            1: {"title": "Scaling Law Paper", "url": "https://arxiv.org/abs/1"},
            2: {"title": "DeepSeek Report", "url": "https://deepseek.com/r1"},
        },
    )

    typ_code = compiler.generate_typst_source(draft)
    assert "#set page" in typ_code
    assert "= Introduction" in typ_code
    assert "= Core Architecture" in typ_code
    assert "#super[1]" in typ_code
    assert "https://arxiv.org/abs/1" in typ_code
    print("  ✓ TypstCompiler generation passed.")


def test_fastapi_routes():
    print("--> Test 2: FastAPI App Routes Registration...")
    routes = [route.path for route in app.routes]
    assert "/" in routes
    assert "/api/v1/research/start" in routes
    assert "/api/v1/research/stream/{task_id}" in routes
    assert "/api/v1/research/article/{task_id}" in routes
    assert "/api/v1/export/typst/{task_id}" in routes
    print("  ✓ FastAPI routes registered correctly.")


def main():
    print("=" * 55)
    print("Running Phase 3 Streaming Web & Typst Compiler Tests")
    print("=" * 55)
    test_typst_compiler()
    test_fastapi_routes()
    print("\nALL PHASE 3 UNIT TESTS PASSED SUCCESSFULLY! 🚀")


if __name__ == "__main__":
    main()
