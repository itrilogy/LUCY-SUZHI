"""
STORM Async Core — 纯异步检索引擎 (带本地 SQLite 缓存与 Jina Reader 深度正文提纯)
支持自建 SearXNG（多轨智能路由）、DuckDuckGo 并发检索，集成三级查询缓存与二级全文深度提纯。
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Union, Dict, Any
import httpx

from .models import SearchSnippet

logger = logging.getLogger(__name__)

CACHE_DB_PATH = Path("./results_async/.search_cache.db")


class SearchCacheManager:
    """基于 SQLite 的检索语义缓存管理器。"""

    def __init__(self, db_path: Path = CACHE_DB_PATH, ttl_seconds: int = 43200):
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    query_text TEXT,
                    results_json TEXT,
                    created_at REAL
                );
            """)
            conn.commit()

    def get(self, query: str) -> Optional[List[SearchSnippet]]:
        q_hash = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT results_json, created_at FROM search_cache WHERE query_hash = ?", (q_hash,))
            row = cur.fetchone()
            if row:
                res_json, created_at = row
                if now - created_at < self.ttl_seconds:
                    try:
                        raw_list = json.loads(res_json)
                        return [SearchSnippet(**item) for item in raw_list]
                    except Exception:
                        return None
        return None

    def set(self, query: str, snippets: List[SearchSnippet]):
        q_hash = hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()
        raw_list = [s.model_dump() for s in snippets]
        res_json = json.dumps(raw_list, ensure_ascii=False)
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO search_cache (query_hash, query_text, results_json, created_at) VALUES (?, ?, ?, ?)",
                (q_hash, query, res_json, now),
            )
            conn.commit()


class AsyncSearXNG:
    """现代异步 SearXNG 检索引擎（带 HTTP/2 连接池复用、SQLite 缓存与 Jina Reader 深度正文抓取）。"""

    def __init__(
        self,
        api_url: str = "https://search.nunch.uk/search",
        api_key: str = "",
        engines_academic: str = "semantic_scholar,arxiv,pubmed,google_scholar",
        engines_chinese: str = "google,bing,baidu,zhihu",
        engines_general: str = "google,bing,duckduckgo",
        max_concurrent: int = 15,
        timeout: float = 8.0,
        enable_cache: bool = True,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.engines_academic = engines_academic
        self.engines_chinese = engines_chinese
        self.engines_general = engines_general
        self.timeout = timeout
        self.enable_cache = enable_cache
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.cache_mgr = SearchCacheManager() if enable_cache else None
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_keepalive_connections=30, max_connections=60),
                http2=True,
            )
        return self._client

    async def close(self):
        """关闭底层连接池。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search(self, query: str, top_k: int = 5) -> List[SearchSnippet]:
        """单条查询异步检索（优先查缓存）。"""
        if self.cache_mgr:
            cached = self.cache_mgr.get(query)
            if cached:
                logger.debug(f"Search cache HIT for query: {query[:30]}")
                return cached[:top_k]

        results = await self.search_batch([query], top_k=top_k)
        res = results[0] if results else []

        if self.cache_mgr and res:
            self.cache_mgr.set(query, res)

        return res

    async def search_batch(self, queries: List[str], top_k: int = 5) -> List[List[SearchSnippet]]:
        """批量异步并发检索（带流控与多轨路由）。"""
        tasks = [self._search_single_guarded(q, top_k) for q in queries]
        return await asyncio.gather(*tasks)

    async def _search_single_guarded(self, query: str, top_k: int) -> List[SearchSnippet]:
        async with self.semaphore:
            return await self._search_single(query, top_k)

    async def _search_single(self, query: str, top_k: int) -> List[SearchSnippet]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        params = {"q": query, "format": "json", "language": "zh-CN"}

        # 三轨智能路由选择
        chinese_chars = sum(1 for c in query if '\u4e00' <= c <= '\u9fff')
        total_chars = len(query.strip())
        is_mixed_or_academic = any(kw in query.lower() for kw in ["paper", "survey", "arxiv", "benchmark", "dataset", "framework", "algorithm"])

        if chinese_chars == 0 or is_mixed_or_academic or (chinese_chars / max(total_chars, 1) < 0.3):
            if self.engines_academic:
                params["engines"] = self.engines_academic
            elif self.engines_general:
                params["engines"] = self.engines_general
        else:
            if self.engines_chinese:
                params["engines"] = self.engines_chinese

        snippets: List[SearchSnippet] = []
        client = self._get_client()
        try:
            resp = await client.get(self.api_url, headers=headers, params=params)
            if resp.status_code == 200:
                data = resp.json()
                for r in data.get("results", [])[:top_k]:
                    url = r.get("url", "")
                    if not url:
                        continue
                    snippets.append(
                        SearchSnippet(
                            url=url,
                            title=r.get("title", ""),
                            content=r.get("content", ""),
                            engine=r.get("engine", "searxng"),
                        )
                    )

            # 若学术组结果不足，自动向通用组降级补充
            if len(snippets) < 3 and self.engines_general and params.get("engines") != self.engines_general:
                params["engines"] = self.engines_general
                fb_resp = await client.get(self.api_url, headers=headers, params=params)
                if fb_resp.status_code == 200:
                    fb_data = fb_resp.json()
                    for r in fb_data.get("results", [])[: (top_k - len(snippets))]:
                        url = r.get("url", "")
                        if url and not any(s.url == url for s in snippets):
                            snippets.append(
                                SearchSnippet(
                                    url=url,
                                    title=r.get("title", ""),
                                    content=r.get("content", ""),
                                    engine=r.get("engine", "searxng_fallback"),
                                )
                            )
        except Exception as e:
            logger.warning(f"Async SearXNG search failed for '{query[:30]}': {e}")

        return snippets

    async def fetch_deep_markdown(self, url: str, timeout: float = 6.0) -> str:
        """通过 Jina Reader 协议 (https://r.jina.ai/) 二级抓取网页提纯 Markdown 正文。"""
        if not url.startswith("http"):
            return ""
        jina_url = f"https://r.jina.ai/{url}"
        client = self._get_client()
        try:
            resp = await client.get(jina_url, headers={"Accept": "text/markdown"}, timeout=timeout)
            if resp.status_code == 200:
                return resp.text[:2500]
        except Exception as e:
            logger.debug(f"Deep markdown fetch failed for {url}: {e}")
        return ""
