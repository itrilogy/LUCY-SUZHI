#!/usr/bin/env python3
"""Concatenate self-owned sources for software-copyright identification pages."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "generated"
ORDER = [
    "knowledge_storm/async_core/__init__.py",
    "knowledge_storm/async_core/models.py",
    "knowledge_storm/async_core/llm.py",
    "knowledge_storm/async_core/config_hub.py",
    "knowledge_storm/async_core/retriever.py",
    "knowledge_storm/async_core/hybrid_retriever.py",
    "knowledge_storm/async_core/deep_exploration.py",
    "knowledge_storm/async_core/fact_graph.py",
    "knowledge_storm/async_core/state_manager.py",
    "knowledge_storm/async_core/pipeline.py",
    "knowledge_storm/async_core/diagram_generator.py",
    "knowledge_storm/async_core/reviewer.py",
    "knowledge_storm/async_core/exporter.py",
    "knowledge_storm/async_core/local_knowledge_hub.py",
    "knowledge_storm/async_core/typst_compiler.py",
    "knowledge_storm/async_core/encoder_reranker.py",
    "server/app.py",
    "cli/async_runner.py",
    "cli/config_manager.py",
    "cli/diagnostics.py",
    "cli/interactive_wizard.py",
    "frontend/web/index.html",
    "frontend/web/app.js",
    "frontend/web/style.css",
]
LINES_PER_PAGE = 50
PAGES = 30
CHUNK = LINES_PER_PAGE * PAGES


def collect() -> list[str]:
    lines: list[str] = []
    for rel in ORDER:
        path = ROOT / rel
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8").splitlines()
        lines.append(f"# ===== FILE: {rel} =====")
        lines.extend(body if body else [""])
        lines.append("")
    return lines


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lines = collect()
    all_text = "\n".join(lines) + "\n"
    (OUT / "source-all.txt").write_text(all_text, encoding="utf-8")
    n = len(lines)
    first = lines[:CHUNK]
    last = lines[-CHUNK:] if n > CHUNK else lines
    (OUT / "source-first-30p.txt").write_text("\n".join(first) + "\n", encoding="utf-8")
    (OUT / "source-last-30p.txt").write_text("\n".join(last) + "\n", encoding="utf-8")
    print(f"files={len(ORDER)} lines={n} wrote {OUT}")


if __name__ == "__main__":
    main()
