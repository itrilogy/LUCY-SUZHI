"""
STORM Async Core — 纯异步检索引擎 (带本地 SQLite 缓存与 Jina Reader 深度正文提纯)
支持自建 SearXNG（多轨智能路由）、DuckDuckGo 并发检索，集成三级查询缓存与二级全文深度提纯。
"""

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import List, Optional, Union, Dict, Any, Set
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

    def get(self, query: str, top_k: Optional[int] = None) -> Optional[List[SearchSnippet]]:
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
                        snippets = [SearchSnippet(**item) for item in raw_list]
                        return snippets[:top_k] if top_k else snippets
                    except Exception:
                        pass
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


# 基础权威白名单（学术、开源代码与核心维基，绝不误杀）
AUTHORITATIVE_WHITELIST = {
    "arxiv.org",
    "github.com",
    "ieee.org",
    "acm.org",
    "wikipedia.org",
    "semanticscholar.org",
    "nature.com",
    "science.org",
    "springer.com",
    "wiley.com",
    "sciencedirect.com",
    "zhihu.com",
}

# 默认内置核心内容农场、SEO 采集站与垃圾下载站（冷启动零网络依赖兜底）
BUILTIN_SPAM_DOMAINS = {
    # 软件下载站 / 捆绑安装站
    "pc.qq.com", "onlinedown.net", "soft.360.cn", "downxia.com", "jb51.net",
    "greendown.cn", "crsky.com", "zol.com.cn", "xiazai.com", "mydown.com",
    "duote.com", "cr173.com", "skycn.com", "newasp.net", "xiazaiba.com",
    "downza.cn", "pc6.com", "downcc.com", "greenxf.com", "ouyaoxiazai.com",
    "vipcn.com", "uzzf.com", "itmop.com", "52z.com", "jisuxz.com",
    # 华语知名内容农场 / 机器翻译聚合采集站
    "kknews.cc", "read01.com", "twgreatdaily.com", "cocomy.net", "gushiciku.cn",
    "itread01.com", "coderbridge.com", "programming.vip", "codenong.com",
    "shangyexinzhi.com", "360kuai.com", "kuaibao.qq.com",
    "xuebuyuan.com", "boke8.net", "hubwiz.com", "yiidian.com",
    # 英文常见 SEO 采集站与垃圾镜像
    "geek-share.com", "hotexamples.com", "programcreek.com", "codota.com",
    "copyprogramming.com",
}

BUILTIN_SPAM_URL_PATTERNS = [
    r"baike\.baidu\.com/tashuo",
    r"tutorialspoint\.com/market",
]

SPAM_PATH_PATTERN = re.compile(
    r"/(download|xiazai|soft|down|apk|exe|app_detail|softdown)/", re.IGNORECASE
)

SPAM_CONTENT_KEYWORDS = [
    "免费软件下载", "高速下载", "绿色纯净版", "破解补丁", "安装包下载",
    "立即下载", "官方正版下载", "电脑版下载", "手机版下载", "免费高速下载",
]


class SpamFilterManager:
    """本地持久化与异步订阅更新的内容农场与垃圾站过滤器。"""

    def __init__(self, local_file: Optional[Path] = None):
        self.local_file = local_file or (Path.home() / ".storm" / "spam_domains.txt")
        self.local_file.parent.mkdir(parents=True, exist_ok=True)
        self.spam_domains: Set[str] = set()
        self._load_local_or_init()

    def _load_local_or_init(self):
        """从本地文件加载，若文件不存在则以内置名单初始化。"""
        if not self.local_file.exists():
            self.spam_domains = set(BUILTIN_SPAM_DOMAINS)
            self._save_to_local()
            return

        try:
            with open(self.local_file, "r", encoding="utf-8") as f:
                lines = [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]
                self.spam_domains = set(lines) | set(BUILTIN_SPAM_DOMAINS)
        except Exception as e:
            logger.warning(f"Failed to load local spam domains file, fallback to builtins: {e}")
            self.spam_domains = set(BUILTIN_SPAM_DOMAINS)

    def _save_to_local(self):
        """持久化保存至本地文本文件。"""
        try:
            with open(self.local_file, "w", encoding="utf-8") as f:
                f.write("# STORM Content Farm & Spam Domain Filter List\n")
                f.write(f"# Total Domains: {len(self.spam_domains)}\n\n")
                for domain in sorted(self.spam_domains):
                    f.write(f"{domain}\n")
        except Exception as e:
            logger.warning(f"Failed to save spam domains to {self.local_file}: {e}")

    async def sync_remote_blocklists(self) -> Dict[str, Any]:
        """异步拉取开源社区权威垃圾站与内容农场订阅源（GitHub Raw），自动去重合并。"""
        remote_sources = [
            "https://raw.githubusercontent.com/cobaltdisco/Google-Search-Blacklist/master/src/blacklist.txt",
            "https://raw.githubusercontent.com/danny0838/content-farm-terminator/master/rules/block.txt",
        ]
        headers = {"User-Agent": "STORM-SpamFilter-Sync/1.0"}
        added_count = 0
        initial_count = len(self.spam_domains)

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for url in remote_sources:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        for raw_line in resp.text.splitlines():
                            line = raw_line.strip()
                            if not line or line.startswith("#") or line.startswith("!"):
                                continue
                            # 清洗 uBlacklist 语法: *://*.example.com/* -> example.com
                            cleaned = (
                                line.replace("*://*.", "")
                                .replace("*://", "")
                                .replace("/*", "")
                                .replace("@", "")
                                .strip()
                                .lower()
                            )
                            if cleaned and "." in cleaned and "/" not in cleaned:
                                if cleaned not in self.spam_domains:
                                    self.spam_domains.add(cleaned)
                                    added_count += 1
                except Exception as e:
                    logger.debug(f"Spam list sync from {url} encountered notice: {e}")

        if added_count > 0:
            self._save_to_local()

        return {
            "initial_count": initial_count,
            "added_count": added_count,
            "total_count": len(self.spam_domains),
            "updated_at": time.time(),
        }

    def is_spam(self, url: str, title: str = "", content: str = "") -> bool:
        """多层复合判定 URL、标题或摘要是否属于垃圾内容农场或下载站。"""
        if not url:
            return True

        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            path = parsed.path.lower()
            full_url_lower = url.lower()

            # 1. 权威白名单直接放行
            if any(netloc == wl or netloc.endswith("." + wl) for wl in AUTHORITATIVE_WHITELIST):
                return False

            # 2. 域名黑名单匹配（精准匹配或子域名匹配）
            if any(netloc == sd or netloc.endswith("." + sd) for sd in self.spam_domains):
                return True

            # 3. 内置 URL 路径黑名单匹配
            if any(re.search(pat, full_url_lower) for pat in BUILTIN_SPAM_URL_PATTERNS):
                return True

            # 4. URL 路径下载特征正则拦截
            if SPAM_PATH_PATTERN.search(path):
                return True

            # 5. 标题与摘要强垃圾 SEO 特征词拦截
            text_sample = f"{title} {content}"
            if any(kw in text_sample for kw in SPAM_CONTENT_KEYWORDS):
                return True

        except Exception:
            return False

        return False


# 全局单例
_GLOBAL_SPAM_FILTER = SpamFilterManager()


class AsyncSearXNG:
    """现代纯异步 SearXNG 客户端（集成三级缓存、动态订阅垃圾过滤与二级全文提纯）。"""

    def __init__(
        self,
        api_url: str = "http://localhost:8080/search",
        api_key: str = "",
        engines_academic: str = "semantic_scholar,arxiv,pubmed,google_scholar",
        engines_chinese: str = "google,bing,baidu,zhihu",
        engines_general: str = "google,bing,duckduckgo",
        max_concurrent: int = 15,
        timeout: float = 8.0,
        enable_cache: bool = True,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.engines_academic = engines_academic
        self.engines_chinese = engines_chinese
        self.engines_general = engines_general
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.enable_cache = enable_cache
        self.cache_manager = SearchCacheManager() if enable_cache else None
        self.spam_filter = _GLOBAL_SPAM_FILTER
        self._client: Optional[httpx.AsyncClient] = None

    def _is_spam_url(self, url: str, title: str = "", content: str = "") -> bool:
        """委托给动态 SpamFilterManager 执行多层判定。"""
        return self.spam_filter.is_spam(url, title=title, content=content)

    def _get_client(self) -> httpx.AsyncClient:
        """获取或复用实例级长连接池。"""
        if self._client is None or self._client.is_closed:
            try:
                self._client = httpx.AsyncClient(
                    timeout=self.timeout,
                    limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
                    http2=True,
                )
            except Exception as e:
                logger.debug(f"HTTP/2 init failed for SearXNG client ({e}), fallback to HTTP/1.1")
                self._client = httpx.AsyncClient(
                    timeout=self.timeout,
                    limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
                    http2=False,
                )
        return self._client

    async def close(self):
        """显式关闭连接池。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def search(self, query: str, top_k: int = 5) -> List[SearchSnippet]:
        """异步执行网页与文献检索（含缓存命中、三轨路由与垃圾域名过滤）。"""
        clean_query = query.strip()
        if not clean_query:
            return []

        if self.enable_cache and self.cache_manager:
            cached_snippets = self.cache_manager.get(clean_query, top_k)
            if cached_snippets:
                return cached_snippets

        async with self.semaphore:
            snippets = await self._execute_search_with_routing(clean_query, top_k)

        if self.enable_cache and self.cache_manager and snippets:
            self.cache_manager.set(clean_query, snippets)

        return snippets

    def _is_relevant_snippet(self, query: str, snippet: SearchSnippet) -> bool:
        """判定检索片段是否与查询词具备基本语义相关度（过滤蜜罐实例与假数据）。"""
        chinese_chars = [c for c in query if '\u4e00' <= c <= '\u9fff']
        text = (snippet.title + " " + snippet.content).lower()
        if chinese_chars:
            # 中文查询：至少命中查询词中 25% 以上的汉字或 2 个关键汉字
            matched = sum(1 for c in set(chinese_chars) if c in text)
            if matched < min(2, len(set(chinese_chars))):
                return False
        else:
            # 英文查询：至少命中 1 个有效单词 (len >= 4)
            words = [w.lower() for w in re.findall(r'[a-zA-Z]{4,}', query)]
            if words and not any(w in text for w in words):
                return False
        return True

    async def _execute_search_with_routing(self, query: str, top_k: int = 5) -> List[SearchSnippet]:
        """内部执行带路由策略的网络请求、垃圾过滤与真实性核验。"""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        params: Dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": "zh-CN",
        }

        # 三轨智能路由选择
        chinese_chars = sum(1 for c in query if '\u4e00' <= c <= '\u9fff')
        total_chars = len(query.strip())
        is_mixed_or_academic = any(kw in query.lower() for kw in ["paper", "survey", "arxiv", "benchmark", "dataset", "framework", "algorithm"])

        if chinese_chars == 0 or is_mixed_or_academic or (chinese_chars / max(total_chars, 1) < 0.3):
            params["engines"] = self.engines_academic if self.engines_academic else self.engines_general
        else:
            params["engines"] = self.engines_chinese

        snippets: List[SearchSnippet] = []
        client = self._get_client()
        for attempt in range(2):
            try:
                req_timeout = 3.5 if params.get("engines") == self.engines_academic else self.timeout
                resp = await client.get(self.api_url, headers=headers, params=params, timeout=req_timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    for r in data.get("results", []):
                        url = r.get("url", "")
                        title_text = r.get("title", "").strip()
                        content_text = r.get("content", "").strip()
                        if not url or self._is_spam_url(url, title=title_text, content=content_text):
                            continue
                        engine_name = str(r.get("engine", "searxng")).lower()
                        # 学术引擎赋予 1.2 高权威度
                        if any(sch in engine_name for sch in ["scholar", "arxiv", "pubmed", "semanticscholar"]):
                            quality = 1.2
                        elif any(ugc in engine_name for ugc in ["zhihu", "reddit", "weibo", "forum"]):
                            quality = 0.8
                        else:
                            quality = 1.0

                        snip = SearchSnippet(
                            url=url,
                            title=title_text,
                            content=content_text,
                            engine=engine_name,
                            source_quality=quality,
                        )
                        if self._is_relevant_snippet(query, snip):
                            snippets.append(snip)
                            if len(snippets) >= top_k:
                                break
                    break
                elif resp.status_code in (429, 502, 503, 504):
                    await asyncio.sleep(0.3 * (attempt + 1))
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(0.2)
                else:
                    logger.debug(f"Async SearXNG search error: {e}")

        # Fallback 1: SearXNG 通用引擎组
        if len(snippets) < 2 and self.engines_general and params.get("engines") != self.engines_general:
            params["engines"] = self.engines_general
            try:
                fb_resp = await client.get(self.api_url, headers=headers, params=params, timeout=self.timeout)
                if fb_resp.status_code == 200:
                    fb_data = fb_resp.json()
                    for r in fb_data.get("results", []):
                        url = r.get("url", "")
                        fb_title = r.get("title", "").strip()
                        fb_content = r.get("content", "").strip()
                        if not url or self._is_spam_url(url, title=fb_title, content=fb_content) or any(s.url == url for s in snippets):
                            continue
                        fb_snip = SearchSnippet(
                            url=url,
                            title=fb_title,
                            content=fb_content,
                            engine=r.get("engine", "searxng_fallback"),
                            source_quality=1.0,
                        )
                        if self._is_relevant_snippet(query, fb_snip):
                            snippets.append(fb_snip)
                            if len(snippets) >= top_k:
                                break
            except Exception as e:
                logger.debug(f"SearXNG fallback search error: {e}")

        # Fallback 2: 若 SearXNG 实例受限或返回伪数据，无缝启动内置 DuckDuckGo 直连保底
        if len(snippets) < 2:
            ddg_snippets = await self._search_direct_ddg(query, top_k=(top_k - len(snippets)))
            for s in ddg_snippets:
                if self._is_relevant_snippet(query, s) and not any(exist.url == s.url for exist in snippets):
                    snippets.append(s)

        return snippets

    async def _search_direct_ddg(self, query: str, top_k: int = 5) -> List[SearchSnippet]:
        """内置高可用轻量 DuckDuckGo 直连检索通道（零外部依赖、双层容灾兜底）。"""
        client = self._get_client()
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        res: List[SearchSnippet] = []
        try:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers=headers,
                timeout=6.0,
            )
            if resp.status_code == 200:
                html = resp.text
                blocks = re.findall(r'<div class="result results_links results_links_deep[\s\S]*?</div>\s*</div>\s*</div>', html)
                import urllib.parse
                for b in blocks:
                    url_m = re.search(r'<a class="result__url" href="(.*?)"', b)
                    snip_m = re.search(r'<a class="result__snippet"[^>]*>([\s\S]*?)</a>', b)
                    title_m = re.search(r'<a class="result__a"[^>]*>([\s\S]*?)</a>', b)

                    raw_url = url_m.group(1).strip() if url_m else ""
                    if "uddg=" in raw_url:
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                        raw_url = parsed["uddg"][0] if "uddg" in parsed else raw_url

                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else "Web Search Result"
                    content = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip() if snip_m else ""

                    if not raw_url or self._is_spam_url(raw_url, title=title, content=content):
                        continue

                    res.append(
                        SearchSnippet(
                            url=raw_url,
                            title=title,
                            content=content,
                            engine="duckduckgo_direct",
                            source_quality=1.0,
                        )
                    )
                    if len(res) >= top_k:
                        break
        except Exception as e:
            logger.debug(f"Direct DDG fallback error: {e}")
        return res

    async def fetch_deep_markdown(self, url: str, timeout: float = 6.0) -> str:
        """多策略网页正文提纯 (Jina Reader 优先 + 直连 HTML 轻量提取回退)。"""
        if not url.startswith("http"):
            return ""
        
        client = self._get_client()
        # 1. 优先尝试 Jina Reader
        jina_url = f"https://r.jina.ai/{url}"
        try:
            resp = await client.get(
                jina_url,
                headers={"Accept": "text/markdown", "User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            )
            if resp.status_code == 200 and len(resp.text.strip()) > 80:
                return resp.text.strip()[:3500]
        except Exception:
            pass

        # 2. 直连 HTTP 回退与轻量 HTML 清洗
        try:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                timeout=timeout,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                html = resp.text
                # 剔除 script, style, nav 等标签
                cleaned = re.sub(r'<(script|style|nav|header|footer)[\s\S]*?<\/\1>', '', html, flags=re.IGNORECASE)
                cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                if len(cleaned) > 50:
                    return cleaned[:3000]
        except Exception as e:
            logger.debug(f"Deep markdown fetch failed for {url}: {e}")
        return ""
