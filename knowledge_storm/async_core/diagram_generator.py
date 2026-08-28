"""
STORM Async Core — 多模态图表与机制流程图生成引擎 (DiagramGenerator)
轻量纯文本/SVG 方案，零重型图形库依赖：
1. 自动提取章节关键机制并生成合法 Mermaid 架构/流程图
2. 自动生成纯 SVG 数据对比图表（柱状图 / 趋势线）嵌入报告
"""

import logging
import re
from typing import Optional, List, Dict, Any
from .llm import AsyncLLM

logger = logging.getLogger(__name__)


class DiagramGenerator:
    """现代轻量图表与流程图生成器。"""

    def __init__(self, llm: AsyncLLM):
        self.llm = llm

    async def generate_mermaid_diagram(self, topic: str, section_content: str) -> Optional[str]:
        """根据章节技术机制生成合法的 Mermaid 流程图或架构图代码块。"""
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in topic)

        if is_chinese:
            prompt = f"""研究课题: {topic}
章节段落节选:
{section_content[:2000]}

请为本章节的核心运作机制、架构或业务流程绘制一个专业、清晰的 Mermaid 流程图（flowchart TD 或 sequenceDiagram）。
要求：
1. 仅输出以 ```mermaid 开头并以 ``` 结尾的代码块。
2. 节点文本必须使用中文，节点文本请用双引号包裹（例如：A["用户输入"] --> B["知识脚手架引擎"]），严禁在节点内出现裸括号或破坏 Mermaid 语法的特殊字符。
3. 节点数量保持在 4 到 7 个，逻辑结构严密。"""
        else:
            prompt = f"""Topic: {topic}
Section Excerpt:
{section_content[:2000]}

Generate a concise, professional Mermaid diagram (flowchart TD or sequenceDiagram) illustrating the core architecture, workflow, or mechanism described in the text.
Requirements:
1. Output ONLY the raw Mermaid code block starting with ```mermaid and ending with ```.
2. Quote node texts properly with brackets (e.g. A["Input"] --> B["Process"]) to avoid syntax breakage.
3. Keep the diagram between 4 to 7 nodes."""

        res = await self.llm.generate(prompt=prompt)
        match = re.search(r"```(?:mermaid)?\s*([\s\S]+?)\s*```", res)
        if match:
            clean_mermaid = match.group(1).strip()
            # 移除开头的 mermaid 标识残留
            if clean_mermaid.startswith("mermaid"):
                clean_mermaid = clean_mermaid[7:].strip()
            return f"```mermaid\n{clean_mermaid}\n```"
        elif "flowchart" in res or "graph " in res or "sequenceDiagram" in res:
            return f"```mermaid\n{res.strip()}\n```"
        return None

    def generate_svg_comparison_bar_chart(self, title: str, labels: List[str], values: List[float], unit: str = "") -> str:
        """生成原生自包含纯 SVG 对比柱状图（零外部依赖，直接内嵌 HTML/Markdown）。"""
        if not labels or not values or len(labels) != len(values):
            return ""

        max_val = max(values) if max(values) > 0 else 1.0
        chart_width = 560
        bar_height = 26
        gap = 14
        chart_height = len(labels) * (bar_height + gap) + 70

        svg_lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {chart_width} {chart_height}" width="100%" style="background:#12161f; border-radius:8px; padding:16px; font-family:sans-serif; margin:16px 0;">',
            f'  <text x="20" y="30" fill="#f1f5f9" font-size="14" font-weight="bold">{title}</text>',
        ]

        start_y = 55
        colors = ["#6366f1", "#10b981", "#38bdf8", "#f59e0b", "#a855f7", "#ec4899"]

        for i, (lbl, val) in enumerate(zip(labels, values)):
            y = start_y + i * (bar_height + gap)
            bar_w = int((val / max_val) * 320)
            color = colors[i % len(colors)]

            # 标签文本
            svg_lines.append(f'  <text x="20" y="{y + 18}" fill="#94a3b8" font-size="12">{lbl}</text>')
            # 柱条背景
            svg_lines.append(f'  <rect x="150" y="{y}" width="330" height="{bar_height}" rx="4" fill="#1a202c"/>')
            # 实际数值条
            svg_lines.append(f'  <rect x="150" y="{y}" width="{max(bar_w, 4)}" height="{bar_height}" rx="4" fill="{color}"/>')
            # 数值文本
            svg_lines.append(f'  <text x="{160 + bar_w}" y="{y + 18}" fill="#f1f5f9" font-size="11" font-weight="600">{val} {unit}</text>')

        svg_lines.append('</svg>')
        return "\n".join(svg_lines)
