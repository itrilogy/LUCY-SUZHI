"""
STORM Async Core — 数据模型定义 (Pydantic v2)
定义全流程统一的强类型数据契约，消除隐式字典传递与序列化歧义。
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime


class Persona(BaseModel):
    """研究视角 / 专家角色"""
    name: str = Field(description="角色或视角名称")
    description: str = Field(description="视角的关注重点与专业背景")

    def to_perspective_string(self) -> str:
        return f"{self.name}: {self.description}"

    @classmethod
    def from_string(cls, text: str) -> "Persona":
        if ":" in text:
            name, desc = text.split(":", 1)
            return cls(name=name.strip(), description=desc.strip())
        return cls(name=text.strip(), description=text.strip())


class SearchSnippet(BaseModel):
    """检索返回的片段证据"""
    url: str
    title: str = ""
    content: str = ""
    engine: str = ""


class FactEntry(BaseModel):
    """原子事实记录"""
    fact_id: str
    claim: str = Field(description="陈述的事实内容")
    source_url: str = Field(description="来源 URL")
    source_title: str = ""
    confidence: float = 1.0
    perspective: str = ""
    extracted_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class FactPool(BaseModel):
    """事实池聚合"""
    facts: List[FactEntry] = Field(default_factory=list)
    url_to_index: Dict[str, int] = Field(default_factory=dict)
    url_to_title: Dict[str, str] = Field(default_factory=dict)

    def add_fact(self, claim: str, url: str, title: str = "", perspective: str = "") -> FactEntry:
        if url not in self.url_to_index:
            self.url_to_index[url] = len(self.url_to_index) + 1
            self.url_to_title[url] = title or url
        
        fact_id = f"fact_{len(self.facts) + 1}"
        entry = FactEntry(
            fact_id=fact_id,
            claim=claim,
            source_url=url,
            source_title=title or self.url_to_title.get(url, ""),
            perspective=perspective,
        )
        self.facts.append(entry)
        return entry

    def get_citations_dict(self) -> Dict[int, Dict[str, Any]]:
        """生成带引用编号的参考文献字典"""
        citations = {}
        for url, idx in self.url_to_index.items():
            snippets = [f.claim for f in self.facts if f.source_url == url]
            citations[idx] = {
                "url": url,
                "title": self.url_to_title.get(url, url),
                "snippets": snippets,
            }
        return citations


class OutlineSection(BaseModel):
    """大纲章节节点"""
    level: int = 1  # 1 为 H1, 2 为 H2, 3 为 H3
    title: str
    description: str = ""
    subsections: List["OutlineSection"] = Field(default_factory=list)


class Outline(BaseModel):
    """整篇文章大纲"""
    topic: str
    sections: List[OutlineSection] = Field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"# {self.topic}\n"]
        def _render_section(sec: OutlineSection):
            prefix = "#" * (sec.level + 1)
            lines.append(f"{prefix} {sec.title}")
            if sec.description:
                lines.append(f"<!-- {sec.description} -->")
            for sub in sec.subsections:
                _render_section(sub)
        for s in self.sections:
            _render_section(s)
        return "\n".join(lines)


class DialogueTurn(BaseModel):
    """专家问答单轮记录"""
    persona: str
    question: str
    queries_issued: List[str] = Field(default_factory=list)
    search_snippets: List[SearchSnippet] = Field(default_factory=list)
    answer: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ArticleDraft(BaseModel):
    """文章生成结果"""
    topic: str
    outline: Outline
    content: str
    citations: Dict[int, Dict[str, Any]] = Field(default_factory=dict)
    polished_content: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
