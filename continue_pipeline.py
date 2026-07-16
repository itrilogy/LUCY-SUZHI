#!/usr/bin/env python3
"""
STORM Pipeline — Continuation (Stages 4 & 5)
Reads existing outline + conversations, writes article sections and polishes.
"""

import json, os, sys, time
from datetime import datetime
from pathlib import Path
from openai import OpenAI

DEEPSEEK_API_KEY = "sk-c6d37a093be945c6bee7503357dd3c91"
TOPIC = "Vibe Coding as a Paradigm for AI-Assisted Software Development"
OUTPUT_DIR = Path("./results_deepseek")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


def llm_call(system, user, model="deepseek-chat", max_tokens=2048, temperature=0.7):
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}])
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [API error attempt {attempt+1}]: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return ""


# ── Load existing data ──
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

outline = OUTPUT_DIR.joinpath("outline.txt").read_text("utf-8")
perspectives = json.loads(OUTPUT_DIR.joinpath("perspectives.json").read_text("utf-8"))
conversations = json.loads(OUTPUT_DIR.joinpath("conversations.json").read_text("utf-8"))

print(f"Loaded: outline ({len(outline)} chars), {len(perspectives)} perspectives, {len(conversations)} conversations")

# ── Source material embedded ──
SOURCES = {
    "wikipedia": {"title": "Wikipedia - Vibe coding", "url": "https://en.wikipedia.org/wiki/Vibe_coding"},
    "ibm": {"title": "IBM - What is Vibe Coding?", "url": "https://www.ibm.com/think/topics/vibe-coding"},
    "github": {"title": "GitHub - What Is Vibe Coding?", "url": "https://github.com/resources/articles/what-is-vibe-coding"},
    "acm": {"title": "ACM TechBrief - Vibe Coding", "url": "https://www.acm.org/media-center/2026/april/techbrief-vibe-coding"},
    "arxiv": {"title": "arXiv - Vibe Coding: Toward an AI-Native Paradigm", "url": "https://arxiv.org/html/2510.17842v1"},
    "ncsc": {"title": "UK NCSC - The vibe coding spectrum", "url": "https://www.ncsc.gov.uk/sites/default/files/2026-06/The-vibe-coding-spectrum-approach-to-AI-assisted-software-development.pdf"},
}

# ── Stage 4: Write article sections ──
print("\n" + "="*60)
print("STAGE 4: Writing article sections")
print("="*60)

sections = []
for line in outline.split("\n"):
    line = line.strip()
    if not line:
        continue
    # Match # Title (h1) and ## Title (h2)
    if line.startswith("## ") and not line.startswith("###"):
        name = line.replace("## ", "").strip()
        # Remove numbered prefix like "1. " or "1.1 "
        import re
        name = re.sub(r'^\d+(\.\d+)*\s*[\.\s]*', '', name).strip()
        if name and name.lower() not in ("", "references", "see also", "lead/introduction"):
            sections.append(("h2", name))
    elif line.startswith("# ") and not line.startswith("##"):
        name = line.replace("# ", "").strip()
        if name.lower() != TOPIC.lower() and "vibe coding" not in name.lower():
            sections.append(("h1", name))

# Filter out metadata lines
sections = [(l, n) for l, n in sections if n.lower() not in ("", "references", "see also")]
print(f"Found {len(sections)} sections to write:")
for l, n in sections:
    print(f"  [{l}] {n}")

# Build sources text once
all_sources = ""
for key, src in SOURCES.items():
    fpath = OUTPUT_DIR.parent / "raw_sources" / f"{key}.txt"
    # We'll just use the search results inline
    all_sources += f"\nSource: {src['title']} ({src['url']})\n"

# Conversation context
conv_text = ""
for i, turn in enumerate(conversations):
    conv_text += f"\n[{turn.get('perspective','general')}] Q: {turn.get('question','')[:200]}\nA: {turn.get('answer','')[:300]}\n"

article_parts = []
for i, (level, name) in enumerate(sections):
    print(f"  [{i+1}/{len(sections)}] Writing: {name}")
    sys.stdout.flush()

    system = "You are an expert academic writer and researcher. Write a well-structured, detailed, and insightful section."
    user = f"""Topic: {TOPIC}

Section to write: {name}

Overall article outline:
{outline[:2000]}

Research conversations:
{conv_text[:3000]}

Available sources:
{all_sources}

Write this section in a formal academic style. Include:
- Specific facts, data points, and examples from the research
- Analysis and critical discussion
- Citations in [1], [2] format referencing sources
- 500-900 words per section
- Clear subsections if needed

Make it substantive and well-researched, not superficial."""

    content = llm_call(system, user, max_tokens=2500, temperature=0.5)
    prefix = "# " if level == "h1" else "## "
    article_parts.append(f"\n\n{prefix}{name}\n\n{content}")

draft = "\n".join(article_parts)
OUTPUT_DIR.joinpath("draft_article.txt").write_text(draft, "utf-8")
print(f"\n✅ Draft written ({len(draft)} chars)")

# ── Stage 5: Polish ──
print("\n" + "="*60)
print("STAGE 5: Polishing article")
print("="*60)

system = "You are a senior academic editor. Polish this article: 1) Add a compelling abstract/executive summary at the top, 2) Ensure smooth transitions, 3) Fix repetition, 4) Check logical flow, 5) Add a proper references section. Return the COMPLETE improved article."
user = f"Article:\n\n{draft[:7000]}\n\nPolish it and return the full improved version with abstract, all sections, and references."

polished = llm_call(system, user, max_tokens=4000, temperature=0.4)
OUTPUT_DIR.joinpath("final_article.txt").write_text(polished, "utf-8")

# ── Summary stats ──
print(f"\n{'='*60}")
print(f"✅ COMPLETE!")
print(f"Draft: {len(draft)} chars")
print(f"Final: {len(polished)} chars")
print(f"Output: {OUTPUT_DIR.resolve()}")
print(f"{'='*60}")
print(f"\nPreview (first 1000 chars):\n")
print(polished[:1000])
