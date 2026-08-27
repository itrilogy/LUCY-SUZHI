"""
STORM Async Core — 多源混合检索与 RRF 融合引擎 (HybridRetriever)
融合两路独立召回通道：
1. 外部 Web 实时检索 (AsyncSearXNG)
2. 本地知识库/语料库轻量检索 (Local Docs BM25 / Exact Term Index)
使用 Reciprocal Rank Fusion (RRF) 算法进行多路召回重排，提供全局证据聚合。
"""

import asyncio
import math
import logging
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from collections import defaultdict

from .models import SearchSnippet
from .retriever import AsyncSearXNG

logger = logging.getLogger(__name__)


class LocalBM25Index:
    """轻量纯 Python 内存 BM25 索引器（支持本地 Markdown/TXT/PDF 导出的文本）。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: List[SearchSnippet] = []
        self.doc_lengths: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_freqs: Dict[str, int] = defaultdict(int)
        self.term_freqs: List[Dict[str, int]] = []

    def add_directory(self, dir_path: str):
        """扫描并加载本地文本文件入库。"""
        p = Path(dir_path)
        if not p.exists() or not p.is_dir():
            return

        for fpath in p.rglob("*"):
            if fpath.is_file() and fpath.suffix.lower() in (".txt", ".md", ".json", ".log"):
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    if len(content.strip()) > 20:
                        # 划分段落
                        paragraphs = [para.strip() for para in content.split("\n\n") if len(para.strip()) > 30]
                        for idx, para in enumerate(paragraphs):
                            self.add_document(
                                content=para,
                                title=f"{fpath.name} (Part {idx+1})",
                                url=f"file://{fpath.absolute()}#part{idx+1}",
                            )
                except Exception as e:
                    logger.debug(f"Failed to index {fpath}: {e}")

        self._finalize_index()

    def add_document(self, content: str, title: str, url: str):
        snippet = SearchSnippet(url=url, title=title, content=content, engine="local_bm25")
        tokens = self._tokenize(content)
        t_freq = defaultdict(int)
        for t in tokens:
            t_freq[t] += 1

        self.docs.append(snippet)
        self.doc_lengths.append(len(tokens))
        self.term_freqs.append(t_freq)
        for t in t_freq:
            self.doc_freqs[t] += 1

    def _finalize_index(self):
        if self.doc_lengths:
            self.avg_doc_len = sum(self.doc_lengths) / len(self.doc_lengths)

    def search(self, query: str, top_k: int = 5) -> List[SearchSnippet]:
        """BM25 打分检索。"""
        if not self.docs or not self.doc_lengths:
            return []

        q_tokens = self._tokenize(query)
        scores = []
        n_docs = len(self.docs)

        for i, doc_tf in enumerate(self.term_freqs):
            doc_len = self.doc_lengths[i]
            score = 0.0
            for t in q_tokens:
                if t in doc_tf:
                    tf = doc_tf[t]
                    df = self.doc_freqs.get(t, 0)
                    idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / max(self.avg_doc_len, 1.0)))
                    score += idf * (numerator / max(denominator, 1e-5))
            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [self.docs[i] for i, _ in scores[:top_k]]

    def _tokenize(self, text: str) -> List[str]:
        # 兼容中英文分词
        clean_text = text.lower()
        # 提取英文单词与中文字符
        tokens = re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]', clean_text)
        return tokens


class HybridRetriever:
    """多源混合检索引擎（Web + 本地 BM25 + RRF 融合）。"""

    def __init__(
        self,
        web_retriever: AsyncSearXNG,
        local_docs_dir: Optional[str] = None,
        rrf_k: int = 60,
    ):
        self.web_retriever = web_retriever
        self.rrf_k = rrf_k
        self.local_index = LocalBM25Index()
        if local_docs_dir:
            self.local_index.add_directory(local_docs_dir)

    async def search(self, query: str, top_k: int = 5) -> List[SearchSnippet]:
        """执行混合检索并通过 RRF 算法合并重排。"""
        # 1. 并发获取 Web 检索结果与本地检索结果
        web_task = self.web_retriever.search(query, top_k=top_k * 2)
        local_results = self.local_index.search(query, top_k=top_k * 2)
        web_results = await web_task

        # 2. RRF (Reciprocal Rank Fusion) 倒数排名融合打分
        rrf_scores: Dict[str, float] = defaultdict(float)
        snippet_map: Dict[str, SearchSnippet] = {}

        # 累计 Web 结果分数 (rank 从 1 开始)
        for rank, snip in enumerate(web_results, start=1):
            rrf_scores[snip.url] += 1.0 / (self.rrf_k + rank)
            snippet_map[snip.url] = snip

        # 累计 Local 结果分数 (权重适当偏向本地高权威文档: 1.2x)
        for rank, snip in enumerate(local_results, start=1):
            rrf_scores[snip.url] += 1.2 / (self.rrf_k + rank)
            snippet_map[snip.url] = snip

        # 3. 按 RRF 综合得分降序排列
        sorted_urls = sorted(rrf_scores.keys(), key=lambda u: rrf_scores[u], reverse=True)
        final_results = [snippet_map[u] for u in sorted_urls[:top_k]]
        return final_results
