#!/usr/bin/env python3
"""
STORM Paper Generator — DeepSeek API + Pre-collected web sources
Generates a research paper using the STORM methodology:
  1. Perspective-guided question asking (using real web sources)
  2. Simulated writer-expert conversations
  3. Outline generation
  4. Article generation
  5. Article polishing
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from openai import OpenAI

# ── Configuration ──
DEEPSEEK_API_KEY = "sk-c6d37a093be945c6bee7503357dd3c91"
TOPIC = "Vibe Coding as a Paradigm for AI-Assisted Software Development"
OUTPUT_DIR = Path("./results_deepseek")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


def llm_call(system: str, user: str, model: str = "deepseek-chat",
             max_tokens: int = 2048, temperature: float = 0.7) -> str:
    """Call DeepSeek API with retry logic."""
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"  [API error attempt {attempt+1}]: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# PRE-COLLECTED SOURCE MATERIAL
# ═══════════════════════════════════════════════════════════════════════════

SOURCES = {
    "wikipedia": {
        "title": "Vibe coding - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Vibe_coding",
        "content": """
Vibe coding is a software development practice assisted by artificial intelligence (AI) where the software developer describes a project or task in a prompt to a large language model (LLM) which generates source code automatically. Vibe coding may involve accepting AI-generated code without thorough review of the output, instead relying on results and follow-up prompts to guide changes.

The term was coined in February 2025 by computer scientist Andrej Karpathy, a co-founder of OpenAI and former AI leader at Tesla. Merriam-Webster listed the term in March 2025 as a "slang & trending" expression. It was named the Collins English Dictionary Word of the Year for 2025.

Advocates of vibe coding say that it allows even amateur programmers to produce software without the extensive training and skills required for software engineering. Critics say that it reduces accountability, maintainability, and increases the risk of introducing security vulnerabilities in the resulting software.

Karpathy described it as a form of coding where you "fully give in to the vibes, embrace exponentials, and forget that the code even exists". When vibe coding, the programmer guides, tests, and gives feedback about the AI-generated source code, rather than manually writing code.

In February 2025, New York Times journalist Kevin Roose, who is not a professional coder, experimented with vibe coding to create several small-scale applications. He described these as "software for one" due to the ability to personalize the software.

In March 2025, Y Combinator reported that 25% of startup companies in its Winter 2025 batch had codebases that were 95% AI-generated.

In June 2025, Andrew Ng took issue with the term, saying that it misleads people into assuming that software engineers just "go with the vibes" when using AI tools to create applications.

In July 2025, The Wall Street Journal reported that vibe coding was being adopted by professional software engineers for commercial use cases.

It was reported in January 2026 that Linus Torvalds had made use of AI to vibe code a tool component of his AudioNoise random digital audio effects generator.

In May 2026, The Wall Street Journal reported on criticism from engineers behind the Pi coding harness who warned of a looming "vibe slop" crisis. They warned that companies are trading near-term productivity for longer-term problems, including buggy software, service outages, security vulnerabilities and increased technical debt.

Key criticisms include:
- Quality of code and security issues: Some developers commit AI-generated code without comprehending its functionality, leading to undetected bugs
- Code maintainability and technical debt: GitClear analysis of 211 million lines of code found that code refactoring dropped from 25% to under 10% by 2024, code duplication increased 4x
- Task complexity: METR randomized controlled trial found experienced developers were 19% SLOWER when using AI coding tools
- Impact on open-source: A January 2026 paper "Vibe Coding Kills Open Source" argued that vibe coding reduces user engagement with maintainers
- GitHub acknowledged in Feb 2026 an increase in lower quality AI-generated contributions overwhelming open source maintainers
""",
    },
    "ibm": {
        "title": "What is Vibe Coding? - IBM",
        "url": "https://www.ibm.com/think/topics/vibe-coding",
        "content": """
"Vibe coding" is a new and loosely defined term in software development that refers to the practice of prompting AI tools to generate code rather than writing code manually.

Vibe coding represents a shift toward intent-driven software development, where AI systems assist developers by generating code from natural language instructions.

The field of vibe coding has moved from basic prompts for code to a deeper understanding of how coding works when focused around context, intention and orchestration.

Paradigm shifts from vibe coding:
1. Quick prototyping: Rapid prototyping is becoming a key enabler for teams to move ideas from early-stage concepts to functional prototype
2. Problem-first approach: Moving from rigid coding style to dynamic structure enables swift innovation
3. Reduce risk: Vibe coding enables businesses to quickly progress with MVP
4. Multimodal switch: Vibe coding is evolving into multimodal programming with voice, visual and text-based coding

To implement vibe coding:
Step 1: Selecting the AI coding platform
Step 2: Describe the intent and context
Step 3: Generate the initial application code
Step 4: Iteratively refine the generated software (Intent -> Generate -> Review -> Refine -> Generate)
Step 5: Validation, security and deployment

Context engineering is key: Business context, Architectural context, Repository context, Security context, Operational context.

Limitations include: technical complexity, code quality issues, debugging challenges, maintenance issues, security concerns.

Vibe coding caused a new type of technical debt called "security debt" - API keys and passwords hardcoded, SQL injections, unsecured APIs, etc.

The next era is "Autonomous engineering" - moving from prompt to code toward intent to AI agent to software.
""",
    },
    "github": {
        "title": "What Is Vibe Coding? - GitHub Resources",
        "url": "https://github.com/resources/articles/what-is-vibe-coding",
        "content": """
Vibe coding is a natural language-driven, AI-assisted way to build software. Instead of writing every line of code by hand, you describe what you want via natural language prompts to an agentic AI system and AI helps turn that into working code.

Vibe coding emphasizes:
- Describing ideas in plain language
- Iterating quickly without breaking your flow
- Shaping structure after the initial creative spark

Implementing vibe coding:
1. Choose a tool that fits your flow (Copilot, Cursor, Replit, etc.)
2. Describe what you want to build using plain natural language prompts
3. Shape the output - treat the response like a rough draft
4. Check before you move on - test the code

Benefits:
- Quick idea to working feature
- Fewer barriers to entry
- More focus, less repetition
- Coding as conversation

Limitations:
- Technical complexity - AI tools often miss details in advanced situations
- Quality and consistency
- Debugging and clarity
- Long-term maintenance - inconsistent naming, scattered logic
- Security risks - hardcoded credentials, insecure forms, unvalidated input

Types of tools: AI agents and orchestrators, AI code completion assistants, conversational AI coding assistants, agentic systems with prompt support.
""",
    },
    "acm": {
        "title": "AI Vibe Coding Could Reshape Software Development but Lacks Key Safeguards - ACM",
        "url": "https://www.acm.org/media-center/2026/april/techbrief-vibe-coding",
        "content": """
The Association for Computing Machinery's Technology Policy Council (TPC) released a TechBrief on "AI-Assisted Software Development, or Vibe Coding: Benefits and Risks of AI-Driven Software Development." The TechBrief examines a growing trend in software development where AI tools are used to generate code from natural language prompts.

The ACM TechBrief highlights both the transformative potential and the significant risks of vibe coding, emphasizing the need for safeguards, standards, and best practices as this approach becomes more widespread in software development.
""",
    },
    "arxiv": {
        "title": "Vibe Coding: Toward an AI-Native Paradigm for Semantic and Intent-Driven Programming - arXiv",
        "url": "https://arxiv.org/html/2510.17842v1",
        "content": """
This paper compares vibe coding with declarative, functional, and prompt-based programming and discusses its implications for software engineering, human-AI collaboration, and responsible AI practice. Vibe coding represents a shift toward semantic and intent-driven programming where the developer's role evolves from writing code to specifying intent and orchestrating AI-generated outputs.
""",
    },
    "ncsc": {
        "title": "The 'vibe coding spectrum' approach - UK NCSC",
        "url": "https://www.ncsc.gov.uk/sites/default/files/2026-06/The-vibe-coding-spectrum-approach-to-AI-assisted-software-development.pdf",
        "content": """
The UK National Cyber Security Centre (NCSC) has published guidance on the 'vibe coding spectrum' approach to AI-assisted software development. The guidance addresses the security implications of vibe coding, particularly the risks of accepting AI-generated code without thorough review. It recommends a spectrum-based approach where organizations assess the risk level of their AI-assisted development practices and implement appropriate safeguards.
""",
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# STORM PIPELINE STAGES
# ═══════════════════════════════════════════════════════════════════════════

def stage1_discover_perspectives() -> list[str]:
    """Use LLM to extract perspectives from the source material."""
    print(f"\n{'='*60}")
    print("STAGE 1: Discovering perspectives from source material")
    print(f"{'='*60}")

    sources_text = ""
    for key, src in SOURCES.items():
        sources_text += f"\n--- Source: {src['title']} ---\n"
        sources_text += src['content'][:800] + "\n"

    system = "You are a research methodologist. Extract 5 distinct perspectives or angles from which to analyze this topic."
    user = f"Topic: {TOPIC}\n\nSource material:\n{sources_text[:3000]}\n\nList 5 distinct perspectives/angles. One per line, short labels (2-5 words)."

    result = llm_call(system, user, max_tokens=300, temperature=0.8)
    perspectives = [p.strip().strip("-*").strip() for p in result.split("\n") if p.strip() and len(p.strip()) > 3]
    perspectives = perspectives[:5]

    if not perspectives:
        perspectives = ["Definition and Origins", "Technical Analysis", "Industry Impact",
                        "Risks and Criticism", "Future Directions"]

    print(f"  Discovered {len(perspectives)} perspectives:")
    for p in perspectives:
        print(f"    - {p}")
    return perspectives


def stage2_simulate_conversations(perspectives: list[str]) -> list[dict]:
    """Simulate writer-expert conversations using source material."""
    print(f"\n{'='*60}")
    print("STAGE 2: Simulating writer-expert conversations")
    print(f"{'='*60}")

    all_turns = []

    for p_idx, perspective in enumerate(perspectives[:4]):
        print(f"\n  [Perspective {p_idx+1}]: {perspective}")

        # Build perspective-specific source context
        source_context = ""
        for key, src in SOURCES.items():
            source_context += f"\n--- {src['title']} ---\n{src['content'][:1000]}\n"

        for turn_idx in range(3):
            # Writer question
            q_system = "You are a Wikipedia writer researching this topic. Ask a specific, deep question."
            q_user = f"""Topic: {TOPIC}
Your focus: {perspective}
Conversation turn: {turn_idx + 1} of 3
Previous turns: {len(all_turns)} turns completed.

Relevant source material:
{source_context[:2000]}

Ask a focused, insightful question about {perspective} that advances your understanding."""

            question = llm_call(q_system, q_user, max_tokens=200, temperature=0.7)
            print(f"    Q{turn_idx+1}: {question[:100]}...")

            # Expert answer using sources
            e_system = "You are a domain expert. Answer thoroughly based on the provided information."
            e_user = f"""Topic: {TOPIC}
Question: {question}

Source material to answer from:
{source_context[:3000]}

Provide a comprehensive, well-structured answer with specific facts and citations. Use [Source: name] format."""

            answer = llm_call(e_system, e_user, max_tokens=600, temperature=0.5)
            print(f"    A{turn_idx+1}: {answer[:100]}...")

            all_turns.append({
                "perspective": perspective,
                "turn": turn_idx + 1,
                "question": question,
                "answer": answer,
            })

    print(f"\n  Total conversation turns: {len(all_turns)}")
    return all_turns


def stage3_generate_outline(conversations: list[dict]) -> str:
    """Generate article outline."""
    print(f"\n{'='*60}")
    print("STAGE 3: Generating article outline")
    print(f"{'='*60}")

    conv_text = ""
    for i, turn in enumerate(conversations):
        conv_text += f"\n[Turn {i+1} - {turn['perspective']}]\nQ: {turn['question'][:200]}\nA: {turn['answer'][:300]}\n"

    system = "You are an experienced Wikipedia editor. Create a detailed hierarchical outline."
    user = f"Topic: {TOPIC}\n\nResearch conversations:\n{conv_text[:4000]}\n\nCreate a detailed outline with # for level 1, ## for level 2. Include: Lead/Introduction, 4-6 main sections, Conclusion."

    outline = llm_call(system, user, max_tokens=1000, temperature=0.5)
    print(f"  Outline generated ({len(outline)} chars)")
    return outline


def stage4_write_article(outline: str, conversations: list[dict]) -> str:
    """Write the full article."""
    print(f"\n{'='*60}")
    print("STAGE 4: Writing article sections")
    print(f"{'='*60}")

    # Parse outline sections
    sections = []
    for line in outline.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            sections.append(("h1", line.replace("# ", "").strip()))
        elif line.startswith("## ") and not line.startswith("### "):
            sections.append(("h2", line.replace("## ", "").strip()))

    # Filter to meaningful sections
    top_sections = [(l, n) for l, n in sections if n.lower() not in ("", "references", "see also")]
    if not top_sections:
        top_sections = [("h1", "Introduction"), ("h2", "Definition and Origins"),
                        ("h2", "Core Methodology"), ("h2", "Industry Adoption"),
                        ("h2", "Risks and Criticism"), ("h2", "Future Directions"),
                        ("h1", "Conclusion")]

    print(f"  Writing {len(top_sections)} sections")
    article_parts = []

    # Build source context for all sections
    all_sources = ""
    for key, src in SOURCES.items():
        all_sources += f"\n--- {src['title']} ---\n{src['content']}\n"

    for i, (level, name) in enumerate(top_sections):
        print(f"  [{i+1}/{len(top_sections)}] {name}")

        system = "You are an expert academic writer. Write a well-structured, detailed section."
        user = f"""Topic: {TOPIC}
Section to write: {name}
Overall outline:
{outline}

Research material:
{all_sources[:4000]}

Write this section in an academic style. Use [1], [2] etc. for citations to sources.
Make it 400-800 words with specific facts, examples, and analysis."""

        content = llm_call(system, user, max_tokens=2000, temperature=0.5)
        prefix = "# " if level == "h1" else "## "
        article_parts.append(f"\n\n{prefix}{name}\n\n{content}")

    return "\n".join(article_parts)


def stage5_polish_article(draft: str) -> str:
    """Polish and add lead section."""
    print(f"\n{'='*60}")
    print("STAGE 5: Polishing article")
    print(f"{'='*60}")

    system = "You are an expert editor. Polish this article: 1) Write a brief executive summary/abstract at the top, 2) Improve transitions, 3) Fix any repetition. Return the FULL article."
    user = f"Article:\n\n{draft[:6000]}\n\nPolish it and return the complete improved version."

    polished = llm_call(system, user, max_tokens=4000, temperature=0.4)
    print(f"  Polished ({len(polished)} chars)")
    return polished


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print(f"{'='*60}")
    print(f"STORM Paper Generator — DeepSeek API + Web Sources")
    print(f"Topic: {TOPIC}")
    print(f"{'='*60}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    start_time = time.time()

    # Stage 1
    perspectives = stage1_discover_perspectives()
    OUTPUT_DIR.joinpath("perspectives.json").write_text(
        json.dumps(perspectives, indent=2), "utf-8")
    print(f"[Saved] perspectives.json")

    # Stage 2
    conversations = stage2_simulate_conversations(perspectives)
    OUTPUT_DIR.joinpath("conversations.json").write_text(
        json.dumps(conversations, indent=2, ensure_ascii=False), "utf-8")
    print(f"[Saved] conversations.json")

    # Stage 3
    outline = stage3_generate_outline(conversations)
    OUTPUT_DIR.joinpath("outline.txt").write_text(outline, "utf-8")
    print(f"[Saved] outline.txt")

    # Stage 4
    draft = stage4_write_article(outline, conversations)
    OUTPUT_DIR.joinpath("draft_article.txt").write_text(draft, "utf-8")
    print(f"[Saved] draft_article.txt")

    # Stage 5
    polished = stage5_polish_article(draft)
    OUTPUT_DIR.joinpath("final_article.txt").write_text(polished, "utf-8")
    print(f"[Saved] final_article.txt")

    # Write metadata
    elapsed = time.time() - start_time
    meta = {
        "topic": TOPIC,
        "generated_at": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed),
        "pipeline": "STORM-inspired (perspectives -> conversations -> outline -> article -> polish)",
        "llm_backend": "deepseek-chat via OpenAI-compatible API",
        "sources": list(SOURCES.keys()),
        "num_conversation_turns": len(conversations),
        "num_perspectives": len(perspectives),
        "outline_length": len(outline),
        "draft_length": len(draft),
        "polished_length": len(polished),
    }
    OUTPUT_DIR.joinpath("metadata.json").write_text(
        json.dumps(meta, indent=2), "utf-8")

    print(f"\n{'='*60}")
    print(f"✅ COMPLETE! Elapsed: {elapsed:.0f}s")
    print(f"📁 Output: {OUTPUT_DIR.resolve()}")
    print(f"{'='*60}")
    print(f"\nFinal article preview:\n")
    print(polished[:1500])
    print(f"\n... ({len(polished)} chars total)")


if __name__ == "__main__":
    main()
