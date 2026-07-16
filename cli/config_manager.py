#!/usr/bin/env python3
"""
StormConfig — STORM 系统配置中心

管理 ~/.storm/config.toml 全局配置文件，提供密钥/服务的增删改查、
连接测试、secrets.toml 导出等功能。

当前系统涉及的 17 项配置分为 4 类：
  - LLM 服务: OpenAI / DeepSeek / Anthropic / Gemini / Together / Groq / Ollama
  - 搜索引擎: searXNG / DuckDuckGo / Bing / You / Serper / Brave / Tavily / Google / Azure
  - 向量库: Qdrant
  - 系统: 输出目录 / 线程数

用法:
  python3 -m cli.config_manager --list        # 列出所有配置
  python3 -m cli.config_manager --diagnose    # 全量诊断
  python3 -m cli.config_manager --export      # 导出 secrets.toml
  python3 -m cli.config_manager --set llm.openai_api_key=sk-xxx
"""

import argparse
import json
import os
import sys
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 常量 ──
CONFIG_DIR = Path.home() / ".storm"
CONFIG_PATH = CONFIG_DIR / "config.toml"
SECRETS_TEMPLATE_PATH = CONFIG_DIR / "secrets_template.toml"

# ── 配置项定义 ──
# (类别, 服务名, 配置前缀, 环境变量名, 是否需要用户填URL, extra(base_url默认/model默认), 免费可用)
SERVICE_REGISTRY = [
    # ── LLM ──
    ("LLM", "DeepSeek",       "llm.deepseek",    "DEEPSEEK_API_KEY", False, "base_url:str=https://api.deepseek.com,model:str=deepseek-chat", False),
    ("LLM", "OpenAI",         "llm.openai",      "OPENAI_API_KEY",   False, "base_url:str=https://api.openai.com/v1,model:str=gpt-4o-mini", False),
    ("LLM", "OpenAI 兼容",    "llm.custom",      "",                 True,  "base_url:str=,model:str=gpt-4o-mini", False),
    # ── 搜索 ──
    ("搜索", "searXNG",       "search.searxng",  "SEARXNG_API_KEY",  True,  "api_key:str,engines_academic:str=semantic+scholar,arxiv,pubmed,google+scholar,engines_chinese:str=baidu,zhihu,bilibili,engines_general:str=google,bing,duckduckgo", False),
    ("搜索", "DuckDuckGo",    "search.ddg",      "",                 False, "", True),
    ("搜索", "Serper",        "search.serper",   "SERPER_API_KEY",   False, "", False),
    # ── 嵌入 ──
    ("嵌入", "OpenAI",        "embed.openai",    "OPENAI_API_KEY",   False, "base_url:str=https://api.openai.com/v1,model:str=text-embedding-3-small", False),
    ("嵌入", "OpenAI 兼容",   "embed.custom",    "",                 True,  "base_url:str=,model:str=text-embedding-3-small", False),
    # ── 重排序 ──
    ("重排序", "Cohere",      "rerank.cohere",   "COHERE_API_KEY",   False, "base_url:str=https://api.cohere.com,model:str=rerank-english-v3.0", False),
    ("重排序", "Jina",        "rerank.jina",     "JINA_API_KEY",     False, "base_url:str=https://api.jina.ai,model:str=jina-reranker-v2-base-multilingual", False),
    ("重排序", "OpenAI 兼容", "rerank.custom",   "",                 True,  "base_url:str=,model:str=", False),
    ("重排序", "无",          "rerank.none",     "",                 False, "", True),
]


# ═══════════════════════════════════════════════════════════════════════════
# StormConfig 核心类
# ═══════════════════════════════════════════════════════════════════════════

class StormConfig:
    """STORM 系统配置管理器。"""

    def __init__(self):
        self.config_path = CONFIG_PATH
        self._data: Dict = {}
        self._ensure_config_dir()
        self._load()

    # ── 文件操作 ──

    def _ensure_config_dir(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not CONFIG_PATH.exists():
            self._write_default()

    def _write_default(self):
        """创建默认配置文件（合法 TOML 格式）。"""
        content = """# STORM 全局配置
# 通过 cli/config_manager.py 管理
# 注意: 密钥值在文件内为明文，请确保文件权限仅本人可读

[llm]
active = "deepseek"
# deepseek.api_key = "sk-..."
# deepseek.base_url = "https://api.deepseek.com"
# deepseek.model = "deepseek-chat"
# openai.api_key = "sk-..."
# openai.base_url = "https://api.openai.com/v1"
# openai.model = "gpt-4o-mini"
# custom.api_key = ""
# custom.base_url = ""
# custom.model = "gpt-4o-mini"

[search]
active_retriever = "searxng"
# searxng.base_url = "https://search.nunch.uk/search"
# searxng.api_key = ""
# searxng.engines_academic = "semantic+scholar,arxiv,pubmed,google+scholar"
# searxng.engines_chinese = "baidu,zhihu,bilibili"
# searxng.engines_general = "google,bing,duckduckgo"
# ddg.enabled = true

[vector]
# qdrant_api_key = ""
# qdrant_url = ""

[system]
# output_dir = "./results"
# max_thread_num = 5

[embed]
active = "openai"
# openai.api_key = "sk-..."
# openai.base_url = "https://api.openai.com/v1"
# openai.model = "text-embedding-3-small"
# custom.api_key = ""
# custom.base_url = ""
# custom.model = "text-embedding-3-small"

[rerank]
active = "none"
# cohere.api_key = "..."
# cohere.base_url = "https://api.cohere.com"
# cohere.model = "rerank-english-v3.0"
# jina.api_key = "..."
# jina.base_url = "https://api.jina.ai"
# jina.model = "jina-reranker-v2-base-multilingual"
# custom.api_key = ""
# custom.base_url = ""
# custom.model = ""
"""
        self._write(content)

    def _write(self, content: str):
        CONFIG_PATH.write_text(content, encoding="utf-8")
        # 设置权限为仅用户可读（Unix）
        if sys.platform != "win32":
            CONFIG_PATH.chmod(0o600)

    def _load(self):
        """从 TOML 文件加载配置。"""
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                # 回退：使用内置的简易解析
                self._load_fallback()
                return

        try:
            with open(self.config_path, "rb") as f:
                self._data = tomllib.load(f)
        except Exception:
            self._data = {}

    def _load_fallback(self):
        """简易 TOML 解析器（无 tomllib/tomli 时的回退）。"""
        import configparser
        cp = configparser.ConfigParser()
        try:
            cp.read(self.config_path)
            for section in cp.sections():
                self._data[section] = dict(cp[section])
        except Exception:
            self._data = {}

    def save(self):
        """将 self._data 递归序列化为合法 TOML 文件。
        支持嵌套 dict（如 llm.deepseek.api_key），兼容扁平键和深层多级键。"""
        
        def _build(lines, data, parent_key=""):
            """递归构建 TOML sections。"""
            sub_tables = {}  # 嵌套 dict → 延迟到子 section
            flat = {}        # 当前层级的扁平键值对
            
            for key, value in data.items():
                if isinstance(value, dict):
                    sub_tables[key] = value
                elif value:
                    flat[key] = value
            
            # 先写当前层级的扁平键
            if flat:
                if parent_key:
                    lines.append(f"\n[{parent_key}]")
                for k, v in sorted(flat.items()):
                    if isinstance(v, str):
                        lines.append(f'{k} = "{v}"')
                    else:
                        lines.append(f"{k} = {v}")
            
            # 递归写嵌套 section
            for tbl_name, tbl_data in sub_tables.items():
                child_key = f"{parent_key}.{tbl_name}" if parent_key else tbl_name
                _build(lines, tbl_data, child_key)

        lines = [
            "# STORM 全局配置",
            "# 通过 cli/config_manager.py 管理",
            "# 注意: 密钥值在文件内为明文，请确保文件权限仅本人可读",
            "",
        ]
        _build(lines, self._data)
        self._write("\n".join(lines))

    # ── CRUD ──

    def get(self, key: str) -> str:
        """获取配置值。key 格式: 'llm.openai_api_key'"""
        parts = key.split(".")
        data = self._data
        for part in parts:
            if isinstance(data, dict):
                data = data.get(part, {})
            else:
                return ""
        return str(data) if not isinstance(data, dict) else ""

    def set(self, key: str, value: str):
        """设置配置值。"""
        parts = key.split(".")
        data = self._data
        for part in parts[:-1]:
            if part not in data:
                data[part] = {}
            data = data[part]
        data[parts[-1]] = value
        self.save()

    def delete(self, key: str):
        """删除配置值。"""
        parts = key.split(".")
        data = self._data
        for part in parts[:-1]:
            if isinstance(data, dict):
                data = data.get(part, {})
            else:
                return
        if isinstance(data, dict) and parts[-1] in data:
            del data[parts[-1]]
            self.save()

    def list_all(self) -> List[Dict]:
        """返回所有配置项的列表（适配嵌套键格式）。"""
        result = []
        for category, svc_name, prefix, env_var, needs_url, extra, free in SERVICE_REGISTRY:
            api_val = self.get(f"{prefix}.api_key")
            url_val = self.get(f"{prefix}.base_url")
            model_val = self.get(f"{prefix}.model")
            configured = bool(api_val) or (needs_url and bool(url_val))
            result.append({
                "category": category,
                "service": svc_name,
                "key": prefix,
                "value": api_val or url_val or "",
                "api_key": api_val,
                "base_url": url_val,
                "model": model_val,
                "env_var": env_var,
                "needs_url": needs_url,
                "extra": extra,
                "free": free,
                "configured": configured,
            })
        return result

    def _group_by_category(self) -> List[Tuple[str, list]]:
        """按类别分组配置项。"""
        groups = {}
        for item in self.list_all():
            cat = item["category"]
            if cat not in groups:
                groups[cat] = []
            groups[cat].append((
                item["service"], item["key"], item["value"],
                item["env_var"], item["needs_url"],
                item["extra"], item["free"],
            ))
        return list(groups.items())

    # ── 诊断 ──

    def diagnose(self) -> List[Dict]:
        """全量诊断：测试每个已配置服务的连接性。"""
        results = []
        items = self.list_all()
        for item in items:
            if item["service"] == "无":
                continue  # 跳过无选项
            status = self._test_service(item)
            results.append({**item, "status": status})
        return results

    def _test_service(self, item: Dict) -> str:
        """测试单个服务的连接性。"""
        import subprocess
        import socket

        if not item["configured"] and not item["free"]:
            return "❌ 未配置"

        # DuckDuckGo / 无 免费服务
        if item["service"] in ("DuckDuckGo", "无"):
            return "✅ 免费可用 (无需配置)" if item["service"] == "DuckDuckGo" else "✅ 已禁用"

        # 统一提取（兼容新旧格式）
        api_key = item.get("api_key") or item.get("value", "")
        base_url = item.get("base_url") or item.get("value", "")

        # URL 可达性测试
        if item["needs_url"]:
            if not base_url:
                return "❌ 未配置 URL"
            try:
                import requests
                r = requests.get(base_url, timeout=5)
                if r.status_code < 400:
                    return f"✅ 连接正常 (HTTP {r.status_code})"
                elif r.status_code < 500:
                    return f"⚠️ HTTP {r.status_code} — API 端点可能需要 POST 请求"
                else:
                    return f"⚠️ 服务错误 (HTTP {r.status_code})"
            except Exception as e:
                return f"❌ {str(e)[:60]}"

        # API Key 测试
        if item["service"] in ("DeepSeek", "OpenAI"):
            if not api_key:
                return "❌ 未配置"
            urls = {"DeepSeek": "https://api.deepseek.com/models", "OpenAI": "https://api.openai.com/v1/models"}
            try:
                import requests
                r = requests.get(urls[item["service"]], headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
                return "✅ API 连接正常" if r.status_code == 200 else f"⚠️ HTTP {r.status_code}"
            except Exception as e:
                return f"❌ {str(e)[:60]}"

        if api_key:
            return "✅ 已配置 (API Key)"
        return "❌ 未配置"

    # ── secrets.toml 导出 ──

    def export_secrets_toml(self, output_path: str = None) -> str:
        """导出为项目级 secrets.toml（供 load_api_key() 消费）。"""
        if output_path is None:
            output_path = "secrets.toml"

        env_map = {}
        for item in self.list_all():
            if item["env_var"] and item["value"] and item["configured"]:
                env_map[item["env_var"]] = item["value"]

        lines = ["# 由 StormConfig 自动生成", f"# {datetime.now().isoformat()}\n"]
        for env_key, value in env_map.items():
            lines.append(f'{env_key} = "{value}"')

        content = "\n".join(lines)
        Path(output_path).write_text(content, encoding="utf-8")
        print(f"✅ 已导出 {len(env_map)} 个配置项到 {output_path}")
        return content

    # ── 快速设置向导 ──

    def interactive_setup(self):
        """交互式配置向导。"""
        print("\n" + "=" * 50)
        print("  STORM 配置向导")
        print("=" * 50)

        # LLM 配置
        print("\n┌─ LLM 服务 ──────────────────────────┐")
        for cat, svc, key, env, url, extra, free in self._get_registry_by_cat("LLM"):
            current = self.get(key)
            if free:
                print(f"  {svc}: (免费/本地)")
                url_val = self.get(key)
                if not url_val:
                    val = input(f"    服务地址 [{key}] (默认 http://localhost:11434): ").strip()
                    self.set(key, val or "http://localhost:11434")
                    model = input(f"    模型名 (默认 llama3): ").strip()
                    if model:
                        self.set("llm.ollama_model", model)
            else:
                masked = f" (当前: {current[:8]}...)" if current else ""
                val = input(f"  {svc} API Key [{env}]{masked}: ").strip()
                if val:
                    self.set(key, val)

        # 搜索引擎配置
        print("\n┌─ 搜索引擎 ──────────────────────────┐")
        for cat, svc, key, env, url, extra, free in self._get_registry_by_cat("搜索"):
            current = self.get(key)
            if free:
                print(f"  {svc}: ✅ 免费可用 (无需配置)")
            elif "searxng" in key:
                current_url = self.get(key)
                url_hint = f" (当前: {current_url})" if current_url else ""
                val = input(f"  searXNG 服务地址{url_hint}: ").strip()
                if val:
                    self.set(key, val)
                key_val = input(f"  searXNG API Key (如无需请留空): ").strip()
                if key_val:
                    self.set("search.searxng.api_key", key_val)
            else:
                masked = f" (当前: {current[:8]}...)" if current else ""
                val = input(f"  {svc} API Key [{env}]{masked}: ").strip()
                if val:
                    self.set(key, val)

        print("\n✅ 配置完成！运行 --diagnose 测试连接。")

    def _get_registry_by_cat(self, category: str) -> list:
        return [s for s in SERVICE_REGISTRY if s[0] == category]

    def get_active_llm(self) -> str:
        """获取当前活跃的 LLM 提供商名称。"""
        return self.get("llm.active") or "deepseek"

    def get_active_retriever(self) -> str:
        """获取当前活跃的检索引擎名称。"""
        return self.get("search.active_retriever") or "searxng"

    def get_llm_config(self) -> dict:
        """获取当前活跃 LLM 的完整配置字典。"""
        provider = self.get_active_llm()  # e.g. "deepseek", "openai", "custom"
        default_url = ""
        default_model = ""
        lm_class = "LitellmModel"

        for cat, svc, prefix, env, needs_url, extra, free in SERVICE_REGISTRY:
            if cat != "LLM":
                continue
            svc_key = prefix.split(".")[-1]  # "deepseek", "openai", "custom"
            if svc_key == provider:
                for param in extra.split(","):
                    if "base_url:" in param:
                        default_url = param.split("=", 1)[1] if "=" in param else ""
                    elif "model:" in param:
                        default_model = param.split("=", 1)[1] if "=" in param else ""
                if provider == "deepseek":
                    lm_class = "DeepSeekModel"
                elif provider == "openai":
                    lm_class = "OpenAIModel"
                else:
                    lm_class = "LitellmModel"
                break

        base = f"llm.{provider}"
        api_key = self.get(f"{base}.api_key") or ""
        api_base = self.get(f"{base}.base_url") or default_url
        model = self.get(f"{base}.model") or default_model

        env_map = {"deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY"}
        if not api_key:
            api_key = os.environ.get(env_map.get(provider, ""), "")

        return {
            "provider": provider,
            "api_key": api_key,
            "api_base": api_base,
            "model": model or "gpt-4o-mini",
            "lm_class": lm_class,
            "temperature": 1.0,
            "top_p": 0.9,
        }

    def get_retriever_config(self) -> dict:
        """
        获取当前活跃检索引擎的完整配置。
        返回: {
            "name": "searxng",
            "class": "SearXNG",
            "params": { ... },
        }
        """
        retriever = self.get_active_retriever()

        registry = {
            "searxng": {
                "class": "SearXNG",
                "params": {
                    "searxng_api_url": self.get("search.searxng.base_url") or "https://search.nunch.uk/search",
                    "searxng_api_key": self.get("search.searxng.api_key") or "",
                    "engines_academic": self.get("search.searxng.engines_academic") or "semantic+scholar,arxiv,pubmed,google+scholar",
                    "engines_chinese": self.get("search.searxng.engines_chinese") or "baidu,zhihu,bilibili",
                    "engines_general": self.get("search.searxng.engines_general") or "google,bing,duckduckgo",
                },
            },
            "duckduckgo": {
                "class": "DuckDuckGoSearchRM",
                "params": {"safe_search": "On", "region": "us-en"},
            },
            "bing": {
                "class": "BingSearch",
                "params": {"bing_search_api_key": self.get("search.bing_api_key") or ""},
            },
            "serper": {
                "class": "SerperRM",
                "params": {"serper_search_api_key": self.get("search.serper_api_key") or ""},
            },
            "brave": {
                "class": "BraveRM",
                "params": {"brave_search_api_key": self.get("search.brave_api_key") or ""},
            },
        }

        config = registry.get(retriever, registry["searxng"]).copy()
        config["name"] = retriever
        return config

    def get_active_embed(self) -> str:
        """获取当前活跃的嵌入后端。"""
        return self.get("embed.active") or "openai"

    def get_active_rerank(self) -> str:
        """获取当前活跃的重排序后端。"""
        return self.get("rerank.active") or "none"

    def get_embed_config(self) -> dict:
        """获取嵌入配置。"""
        backend = self.get_active_embed()  # "openai" or "custom"
        default_url = ""
        default_model = "text-embedding-3-small"
        for cat, svc, prefix, env, needs_url, extra, free in SERVICE_REGISTRY:
            if cat != "嵌入":
                continue
            svc_key = prefix.split(".")[-1]
            if svc_key == backend:
                for param in extra.split(","):
                    if "base_url:" in param:
                        default_url = param.split("=", 1)[1] if "=" in param else ""
                    elif "model:" in param:
                        default_model = param.split("=", 1)[1] if "=" in param else ""
                break
        base = f"embed.{backend}"
        api_key = self.get(f"{base}.api_key") or os.environ.get("OPENAI_API_KEY", "")
        api_base = self.get(f"{base}.base_url") or default_url
        model = self.get(f"{base}.model") or default_model
        return {
            "backend": backend,
            "api_key": api_key,
            "api_base": api_base,
            "model": model,
        }

    def get_rerank_config(self) -> dict:
        """获取重排序配置。"""
        backend = self.get_active_rerank()  # "cohere", "jina", "custom", "none"
        default_url = ""
        default_model = ""
        for cat, svc, prefix, env, needs_url, extra, free in SERVICE_REGISTRY:
            if cat != "重排序":
                continue
            svc_key = prefix.split(".")[-1]
            if svc_key == backend:
                for param in extra.split(","):
                    if "base_url:" in param:
                        default_url = param.split("=", 1)[1] if "=" in param else ""
                    elif "model:" in param:
                        default_model = param.split("=", 1)[1] if "=" in param else ""
                break
        base = f"rerank.{backend}"
        api_key = self.get(f"{base}.api_key") or ""
        api_base = self.get(f"{base}.base_url") or default_url
        model = self.get(f"{base}.model") or default_model
        return {
            "backend": backend,
            "api_key": api_key,
            "api_base": api_base,
            "model": model,
        }

    def __repr__(self) -> str:
        items = self.list_all()
        configured = sum(1 for i in items if i["configured"])
        return f"StormConfig(path={self.config_path}, total={len(items)}, configured={configured})"


# ═══════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════════

def cmd_list(config: StormConfig):
    """列出所有配置。"""
    items = config.list_all()
    current_cat = None
    for item in items:
        if item["category"] != current_cat:
            current_cat = item["category"]
            print(f"\n┌─ {current_cat} ─────────────────────────────┐")
        value_display = item["value"]
        if item["configured"] and ("key" in item["key"] or "secret" in item["key"]):
            value_display = value_display[:8] + "..." if len(value_display) > 8 else "****"
        configured_mark = "✅" if item["configured"] else "❌"
        free_mark = " (免费)" if item["free"] else ""
        env_display = f" [{item['env_var']}]" if item["env_var"] else ""
        print(f"  {configured_mark} {item['service']}{free_mark}{env_display}")
        if value_display:
            print(f"     → {value_display}")


def cmd_diagnose(config: StormConfig):
    """全量诊断。"""
    print("\n" + "=" * 50)
    print("  STORM 系统诊断报告")
    print(f"  配置文件: {CONFIG_PATH}")
    print("=" * 50)

    results = config.diagnose()
    current_cat = None
    for r in results:
        if r["category"] != current_cat:
            current_cat = r["category"]
            print(f"\n┌─ {current_cat} ─────────────────────────────┐")
        print(f"  {r['status']} {r['service']}")

    # 统计
    total = len(results)
    ok = sum(1 for r in results if r["status"].startswith("✅"))
    warn = sum(1 for r in results if r["status"].startswith("⚠️"))
    err = sum(1 for r in results if r["status"].startswith("❌"))
    print(f"\n{'='*50}")
    print(f"  总计: {total} | ✅ {ok} | ⚠️ {warn} | ❌ {err}")
    print(f"{'='*50}")


def cmd_set(config: StormConfig, kv: str):
    """设置配置项。格式: key=value"""
    if "=" not in kv:
        print("❌ 格式错误: 请使用 key=value 格式")
        return
    key, value = kv.split("=", 1)
    config.set(key.strip(), value.strip())
    print(f"✅ 已设置 {key.strip()}")


def cmd_delete(config: StormConfig, key: str):
    """删除配置项。"""
    config.delete(key)
    print(f"✅ 已删除 {key}")


def cmd_export(config: StormConfig):
    """导出 secrets.toml。"""
    config.export_secrets_toml()


def cmd_wizard(config: StormConfig):
    """交互式配置向导。"""
    config.interactive_setup()


def main():
    parser = argparse.ArgumentParser(description="STORM 配置管理器")
    parser.add_argument("--list", action="store_true", help="列出所有配置")
    parser.add_argument("--diagnose", action="store_true", help="全量诊断")
    parser.add_argument("--set", type=str, help="设置配置 key=value")
    parser.add_argument("--delete", type=str, help="删除配置")
    parser.add_argument("--export", action="store_true", help="导出 secrets.toml")
    parser.add_argument("--wizard", action="store_true", help="交互式配置向导")

    args = parser.parse_args()
    config = StormConfig()

    if args.wizard:
        cmd_wizard(config)
    elif args.list:
        cmd_list(config)
    elif args.diagnose:
        cmd_diagnose(config)
    elif args.set:
        cmd_set(config, args.set)
    elif args.delete:
        cmd_delete(config, args.delete)
    elif args.export:
        cmd_export(config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
