"""
STORM Async Core — 统一强类型配置中心与 Provider 管理矩阵 (ConfigHub)
功能：
1. 四层优先级配置继承：CLI Flags > OS Env (.env) > User TOML (~/.storm/config.toml) > Built-in Presets
2. 全生态 Provider 预置矩阵 (DeepSeek, SiliconFlow, OpenAI, Ollama, SearXNG, DuckDuckGo, Tavily)
3. 异步端点自动探测与网络 RTT 延迟测算 (Probe & Model Auto-Discovery)
4. 凭证脱敏与安全持久化
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

import httpx

logger = logging.getLogger(__name__)

USER_CONFIG_PATH = Path.home() / ".storm" / "config.toml"


class LLMProviderInfo(BaseModel):
    provider_id: str
    name: str
    base_url: str
    api_key: str = ""
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: float = 60.0
    is_custom: bool = False


class SearchProviderInfo(BaseModel):
    provider_id: str
    name: str
    api_url: str
    api_key: str = ""
    engines_academic: str = "semantic_scholar,arxiv,pubmed,google_scholar"
    engines_chinese: str = "google,bing,baidu,zhihu"
    engines_general: str = "google,bing,duckduckgo"
    max_concurrent: int = 15
    timeout: float = 8.0
    enable_cache: bool = True
    is_custom: bool = False


class StormSystemConfig(BaseModel):
    active_llm_provider: str = "deepseek"
    active_search_provider: str = "searxng"
    deep_research_default: bool = True
    max_depth: int = 2
    llm_providers: Dict[str, LLMProviderInfo] = Field(default_factory=dict)
    search_providers: Dict[str, SearchProviderInfo] = Field(default_factory=dict)


# 全生态厂商官方/推荐预置模板
DEFAULT_LLM_PRESETS: Dict[str, LLMProviderInfo] = {
    "deepseek": LLMProviderInfo(
        provider_id="deepseek",
        name="DeepSeek (官方直连)",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        temperature=0.7,
    ),
    "siliconflow": LLMProviderInfo(
        provider_id="siliconflow",
        name="SiliconFlow (硅基流动)",
        base_url="https://api.siliconflow.cn/v1",
        model="deepseek-ai/DeepSeek-V3",
        temperature=0.7,
    ),
    "openai": LLMProviderInfo(
        provider_id="openai",
        name="OpenAI (官方端点)",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        temperature=0.7,
    ),
    "ollama": LLMProviderInfo(
        provider_id="ollama",
        name="Ollama (本地私有)",
        base_url="http://localhost:11434/v1",
        model="deepseek-r1:14b",
        temperature=0.7,
    ),
    "moonshot": LLMProviderInfo(
        provider_id="moonshot",
        name="Moonshot (Kimi)",
        base_url="https://api.moonshot.cn/v1",
        model="moonshot-v1-32k",
        temperature=0.7,
    ),
}

DEFAULT_SEARCH_PRESETS: Dict[str, SearchProviderInfo] = {
    "searxng": SearchProviderInfo(
        provider_id="searxng",
        name="SearXNG (自建/私有三轨路由)",
        api_url="https://search.nunch.uk/search",
        engines_academic="semantic_scholar,arxiv,pubmed,google_scholar",
        engines_chinese="google,bing,baidu,zhihu",
        engines_general="google,bing,duckduckgo",
        max_concurrent=15,
        timeout=8.0,
    ),
    "duckduckgo": SearchProviderInfo(
        provider_id="duckduckgo",
        name="DuckDuckGo (免 Key 公网检索)",
        api_url="https://html.duckduckgo.com/html/",
        engines_general="duckduckgo",
        max_concurrent=8,
        timeout=6.0,
    ),
}


class ConfigHub:
    """现代强类型配置管理器。"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or USER_CONFIG_PATH
        self.system_config = self._load_hierarchical_config()

    def _load_hierarchical_config(self) -> StormSystemConfig:
        """分层加载配置 (Defaults -> TOML -> Environment Variables)。"""
        cfg = StormSystemConfig()

        # 1. 载入预置厂商
        cfg.llm_providers = {k: v.model_copy() for k, v in DEFAULT_LLM_PRESETS.items()}
        cfg.search_providers = {k: v.model_copy() for k, v in DEFAULT_SEARCH_PRESETS.items()}

        # 2. 读取用户 TOML 文件（若存在）
        if self.config_path.exists():
            try:
                try:
                    import tomllib
                    with open(self.config_path, "rb") as f:
                        toml_data = tomllib.load(f)
                except ImportError:
                    import tomli as tomllib
                    with open(self.config_path, "rb") as f:
                        toml_data = tomllib.load(f)

                if "llm" in toml_data and isinstance(toml_data["llm"], dict):
                    llm_sec = toml_data["llm"]
                    if "active" in llm_sec:
                        cfg.active_llm_provider = str(llm_sec["active"])

                if "search" in toml_data and isinstance(toml_data["search"], dict):
                    search_sec = toml_data["search"]
                    if "active_retriever" in search_sec:
                        cfg.active_search_provider = str(search_sec["active_retriever"])

                # 处理 Provider 属性配置（支持顶层 [deepseek] 或嵌套在 [llm] / [search] 下）
                llm_group = toml_data.get("llm", {})
                for p_id, p_obj in cfg.llm_providers.items():
                    p_dict = toml_data.get(p_id) or (llm_group.get(p_id) if isinstance(llm_group, dict) else None)
                    if p_dict and isinstance(p_dict, dict):
                        for k, v in p_dict.items():
                            if hasattr(p_obj, k):
                                setattr(p_obj, k, v)

                search_group = toml_data.get("search", {})
                for p_id, p_obj in cfg.search_providers.items():
                    p_dict = toml_data.get(p_id) or (search_group.get(p_id) if isinstance(search_group, dict) else None)
                    if p_dict and isinstance(p_dict, dict):
                        for k, v in p_dict.items():
                            if hasattr(p_obj, k):
                                setattr(p_obj, k, v)
            except Exception as e:
                logger.warning(f"Failed to parse user config file: {e}")

        # 3. 环境变量最高优先级覆盖
        env_ds_key = os.environ.get("DEEPSEEK_API_KEY")
        if env_ds_key and "deepseek" in cfg.llm_providers:
            cfg.llm_providers["deepseek"].api_key = env_ds_key

        env_ds_base = os.environ.get("DEEPSEEK_API_BASE")
        if env_ds_base and "deepseek" in cfg.llm_providers:
            cfg.llm_providers["deepseek"].base_url = env_ds_base

        env_openai_key = os.environ.get("OPENAI_API_KEY")
        if env_openai_key and "openai" in cfg.llm_providers:
            cfg.llm_providers["openai"].api_key = env_openai_key

        env_searx_url = os.environ.get("SEARXNG_API_URL")
        if env_searx_url and "searxng" in cfg.search_providers:
            cfg.search_providers["searxng"].api_url = env_searx_url

        return cfg

    def get_active_llm(self) -> LLMProviderInfo:
        p_id = self.system_config.active_llm_provider
        return self.system_config.llm_providers.get(p_id, self.system_config.llm_providers["deepseek"])

    def get_active_search(self) -> SearchProviderInfo:
        p_id = self.system_config.active_search_provider
        return self.system_config.search_providers.get(p_id, self.system_config.search_providers["searxng"])

    def get_masked_config(self) -> Dict[str, Any]:
        """返回已对敏感 Key 脱敏后的全量配置数据（供前端 Web 展示）。"""
        from .security import pop_secrets
        return pop_secrets(self.system_config.model_dump())

    def save_config(self, new_config: StormSystemConfig):
        """持久化配置到磁盘。"""
        self.system_config = new_config
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        from .security import toml_quote

        lines = [
            "# Auto-generated by STORM ConfigHub",
            "[llm]",
            f"active = {toml_quote(new_config.active_llm_provider)}",
        ]
        for p_id, p in new_config.llm_providers.items():
            lines.append(f"{p_id}.base_url = {toml_quote(p.base_url)}")
            if p.api_key:
                lines.append(f"{p_id}.api_key = {toml_quote(p.api_key)}")
            lines.append(f"{p_id}.model = {toml_quote(p.model)}")

        lines.extend(["\n[search]", f"active_retriever = {toml_quote(new_config.active_search_provider)}"])
        for p_id, p in new_config.search_providers.items():
            lines.append(f"{p_id}.api_url = {toml_quote(p.api_url)}")
            if p.api_key:
                lines.append(f"{p_id}.api_key = {toml_quote(p.api_key)}")
            lines.append(f"{p_id}.engines_academic = {toml_quote(p.engines_academic)}")
            lines.append(f"{p_id}.engines_chinese = {toml_quote(p.engines_chinese)}")
            lines.append(f"{p_id}.engines_general = {toml_quote(p.engines_general)}")

        self.config_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Config successfully saved to {self.config_path}")


# ── 异步端点探测与诊断算法 ─────────────────────────────────────────────

async def probe_llm_endpoint(base_url: str, api_key: str = "", timeout: float = 6.0) -> Dict[str, Any]:
    """探测 LLM 端点健康度、测算 RTT 延迟并自动拉取可用模型列表。"""
    from .security import SecurityError, assert_probe_url_safe
    try:
        base_url = assert_probe_url_safe(base_url)
    except SecurityError as exc:
        return {"status": "BLOCKED", "rtt_ms": 0, "models": [], "msg": str(exc)}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    clean_base = base_url.rstrip("/")
    probe_url = f"{clean_base}/models" if clean_base.endswith("/v1") else f"{clean_base}/v1/models"

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(probe_url, headers=headers)
            rtt_ms = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
                return {"status": "ONLINE", "rtt_ms": rtt_ms, "models": models}
            elif resp.status_code == 401:
                return {"status": "UNAUTHORIZED", "rtt_ms": rtt_ms, "models": [], "msg": "API Key 无效或未授权"}
            else:
                return {"status": "HTTP_ERROR", "code": resp.status_code, "rtt_ms": rtt_ms, "models": [], "msg": resp.text[:100]}
    except Exception as e:
        return {"status": "OFFLINE", "rtt_ms": 0, "models": [], "msg": str(e)}


async def probe_search_endpoint(api_url: str, api_key: str = "", timeout: float = 6.0) -> Dict[str, Any]:
    """探测检索引擎连通性与 RTT 延迟。"""
    from .security import SecurityError, assert_probe_url_safe
    try:
        api_url = assert_probe_url_safe(api_url)
    except SecurityError as exc:
        return {"status": "BLOCKED", "rtt_ms": 0, "msg": str(exc)}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(api_url, headers=headers, params={"q": "probe", "format": "json"})
            rtt_ms = int((time.time() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json() if "json" in resp.headers.get("content-type", "") else {}
                count = len(data.get("results", []))
                return {"status": "ONLINE", "rtt_ms": rtt_ms, "sample_count": count}
            else:
                return {"status": "HTTP_ERROR", "code": resp.status_code, "rtt_ms": rtt_ms, "msg": resp.text[:100]}
    except Exception as e:
        return {"status": "OFFLINE", "rtt_ms": 0, "msg": str(e)}
