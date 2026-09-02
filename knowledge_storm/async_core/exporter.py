"""
溯知多格式导出：Marp 幻灯片与自包含离线 HTML 研报。
离线 HTML 不加载公网 CDN；机制图以源码块保存，保证可打印、可拷走。
"""

import html
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional

from .models import ArticleDraft

logger = logging.getLogger(__name__)

_MARK_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "frontend" / "web" / "brand" / "suzhi-mark.svg",
)


def _inline_mark_svg() -> str:
    for path in _MARK_CANDIDATES:
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            raw = re.sub(r"<svg\b", '<svg class="brand-mark"', raw, count=1)
            return raw
    return (
        '<svg class="brand-mark" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" aria-hidden="true">'
        '<rect width="512" height="512" rx="112" fill="#0D5E42"/>'
        '<text x="256" y="300" text-anchor="middle" fill="#F5F7FA" font-size="180">溯</text>'
        "</svg>"
    )


class MultiFormatExporter:
    """多格式出版物导出器。"""

    def generate_marp_slides_markdown(self, draft: ArticleDraft) -> str:
        topic = draft.topic
        sections = draft.outline.sections if draft.outline else []

        slides = [
            "---",
            "marp: true",
            "theme: default",
            "_class: lead",
            "paginate: true",
            "backgroundColor: #071510",
            "color: #F5F7FA",
            "---",
            "\n# 溯知 · SuZhi\n",
            "**溯流求源，知汇成章**",
            f"\n## {topic}\n",
            "\n鹿溪联合创新实验室 · LUXI Joint Innovation Lab\n",
            "---",
            "\n## 目录\n",
        ]

        for idx, sec in enumerate(sections, start=1):
            slides.append(f"{idx}. **{sec.title}**")

        slides.append("\n---")

        body = draft.polished_content or draft.content
        for sec in sections:
            slides.append(f"\n## {sec.title}\n")
            pattern = rf"##\s+{re.escape(sec.title)}\s*\n([\s\S]+?)(?=\n##\s+|$)"
            match = re.search(pattern, body)
            if match:
                sec_text = match.group(1).strip()
                clean_text = re.sub(r"\[\d+\]", "", sec_text)
                paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
                for p in paragraphs[:3]:
                    if not p.startswith("#") and not p.startswith("|"):
                        slides.append(f"- {p[:120]}...")
            else:
                slides.append(f"- {sec.title}")
            slides.append("\n---")

        slides.append("\n## 参考文献\n")
        for idx, item in sorted(list(draft.citations.items())[:8], key=lambda x: x[0]):
            slides.append(f"- **[{idx}]** [{item['title']}]({item['url']})")

        slides.append("\n---")
        slides.append("\n# 谢谢\n\n*溯知 · SuZhi · 鹿溪联合创新实验室*")
        return "\n".join(slides)

    def generate_standalone_html_report(self, draft: ArticleDraft) -> str:
        """自包含离线研报：无 CDN，页眉为溯知字锁。"""
        topic_escaped = html.escape(draft.topic)
        content_md = draft.polished_content or draft.content
        mark_svg = _inline_mark_svg()

        mermaid_blocks = []

        def _save_mermaid(m):
            idx = len(mermaid_blocks)
            mermaid_blocks.append(m.group(1).strip())
            return f"__MERMAID_BLOCK_{idx}__"

        content_md = re.sub(r"```(?:mermaid)?\s*\n([\s\S]*?)\n```", _save_mermaid, content_md)

        def _format_inline(text: str) -> str:
            safe = html.escape(text)
            safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
            safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
            safe = re.sub(r"\[(\d+)\]", r'<sup class="citation">[\1]</sup>', safe)
            return safe

        html_body = []
        for line in content_md.split("\n"):
            line_s = line.strip()
            if not line_s:
                continue
            if line_s.startswith("__MERMAID_BLOCK_"):
                m_idx_match = re.search(r"__MERMAID_BLOCK_(\d+)__", line_s)
                if m_idx_match:
                    m_idx = int(m_idx_match.group(1))
                    if m_idx < len(mermaid_blocks):
                        raw_code = html.escape(mermaid_blocks[m_idx])
                        html_body.append(
                            '<figure class="diagram">'
                            "<figcaption>机制图（离线保存为 Mermaid 源，不依赖外网）</figcaption>"
                            f'<pre class="diagram-source">{raw_code}</pre>'
                            "</figure>"
                        )
                continue
            if line_s.startswith("# "):
                html_body.append(f"<h1>{_format_inline(line_s[2:])}</h1>")
            elif line_s.startswith("## "):
                html_body.append(f"<h2>{_format_inline(line_s[3:])}</h2>")
            elif line_s.startswith("### "):
                html_body.append(f"<h3>{_format_inline(line_s[4:])}</h3>")
            elif line_s.startswith("> "):
                html_body.append(f"<blockquote><p>{_format_inline(line_s[2:])}</p></blockquote>")
            elif line_s.startswith("- ") or line_s.startswith("• ") or line_s.startswith("* "):
                html_body.append(f"<li>{_format_inline(line_s[2:])}</li>")
            elif line_s.startswith("| ") and "|" in line_s:
                html_body.append(f"<pre class='table-line'>{html.escape(line_s)}</pre>")
            else:
                html_body.append(f"<p>{_format_inline(line_s)}</p>")

        body_html_str = "\n".join(html_body)
        citations_html = []
        for idx, item in sorted(draft.citations.items(), key=lambda x: x[0]):
            url = html.escape(item.get("url", "#"))
            title = html.escape(item.get("title", url))
            citations_html.append(
                f'    <div class="citation-item">[{idx}] '
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></div>'
            )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{topic_escaped} — 溯知 · SuZhi</title>
  <style>
    :root {{
      --luxi-green: #0D5E42;
      --origin-white: #F5F7FA;
      --evolution-cyan: #00D2FF;
      --title-gold: #F1C40F;
      --bg: #071510;
      --panel: #0C1F18;
      --text: #F5F7FA;
      --muted: #A8B8B2;
    }}
    @media print {{
      body {{ background: #fff !important; color: #1A2428 !important; }}
      .report-header, .report-footer {{ background: #fff !important; color: #0D5E42 !important; border-color: #0D5E42 !important; }}
      a {{ color: #0D5E42 !important; }}
      .no-print {{ display: none !important; }}
      @page {{ margin: 1.8cm; }}
    }}
    body {{
      font-family: "PingFang SC", "Songti SC", "Noto Serif SC", serif;
      line-height: 1.8;
      max-width: 860px;
      margin: 0 auto;
      padding: 32px 24px 64px;
      background: var(--bg);
      color: var(--text);
    }}
    .report-header {{
      display: flex;
      gap: 16px;
      align-items: center;
      border-bottom: 1px solid rgba(0, 210, 255, 0.25);
      padding-bottom: 16px;
      margin-bottom: 28px;
    }}
    .brand-mark {{ width: 56px; height: 56px; flex-shrink: 0; border-radius: 12px; }}
    .brand-name {{ font-size: 22px; font-weight: 700; letter-spacing: 0.06em; margin: 0; }}
    .brand-en {{ color: var(--evolution-cyan); font-weight: 500; font-size: 14px; margin-left: 6px; }}
    .brand-slogan {{ color: var(--title-gold); letter-spacing: 0.16em; font-size: 12px; margin: 4px 0 0; }}
    .brand-lab {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    h1 {{ font-size: 26px; border-bottom: 1px solid rgba(245,247,250,0.12); padding-bottom: 12px; }}
    h2 {{ font-size: 20px; color: var(--evolution-cyan); margin-top: 32px; }}
    h3 {{ font-size: 16px; color: #d5e4de; margin-top: 24px; }}
    p {{ margin-bottom: 16px; text-align: justify; }}
    blockquote {{
      border-left: 3px solid var(--title-gold);
      background: var(--panel);
      padding: 12px 16px;
      margin: 16px 0;
    }}
    sup.citation {{ color: var(--evolution-cyan); font-weight: 700; margin: 0 2px; }}
    .diagram {{
      background: var(--panel);
      border: 1px solid rgba(0, 210, 255, 0.25);
      border-radius: 10px;
      padding: 16px;
      margin: 24px 0;
    }}
    .diagram figcaption {{ font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
    .diagram-source {{
      font-family: ui-monospace, "SF Mono", monospace;
      font-size: 12px;
      white-space: pre-wrap;
      color: #cfe8e0;
      margin: 0;
    }}
    .citations-section {{ margin-top: 48px; border-top: 1px solid rgba(245,247,250,0.12); padding-top: 24px; }}
    .citation-item {{ font-size: 13px; color: var(--muted); margin-bottom: 8px; }}
    .citation-item a {{ color: var(--evolution-cyan); text-decoration: none; }}
    .report-footer {{
      margin-top: 48px;
      padding-top: 16px;
      border-top: 1px solid rgba(245,247,250,0.12);
      font-size: 12px;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <header class="report-header">
    {mark_svg}
    <div>
      <p class="brand-name">溯知 <span class="brand-en">SuZhi</span></p>
      <p class="brand-slogan">溯流求源，知汇成章</p>
      <p class="brand-lab">鹿溪联合创新实验室 · LUXI Joint Innovation Lab</p>
    </div>
  </header>
  <p class="topic-kicker" style="color:#A8B8B2;font-size:13px;margin-bottom:8px;">深度知识策展研报</p>
  {body_html_str}
  <div class="citations-section">
    <h2>参考文献</h2>
{chr(10).join(citations_html)}
  </div>
  <footer class="report-footer">
    出品：鹿溪联合创新实验室（LUXI Joint Innovation Lab） · 溯知 · SuZhi · 引擎代号 STORM
  </footer>
</body>
</html>"""
