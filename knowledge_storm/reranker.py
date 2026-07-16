"""
重排序模块 — 支持 Cohere / Jina / 本地 CrossEncoder / None

从 StormConfig 自动读取活跃配置，也接受显式参数覆盖。

后端:
  - "cohere": 调用 Cohere Rerank API
  - "jina":   调用 Jina Reranker API
  - "local":  本地 CrossEncoder（需 torch）
  - "none":   无操作，直接返回原始顺序
"""

import logging
import os
import numpy as np
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class Reranker:
    """多后端重排序器。"""

    def __init__(
        self,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self._backend = "none"
        self._api_key = ""
        self._local_model = None

        # 从 StormConfig 读取默认配置
        config = {}
        try:
            from cli.config_manager import StormConfig
            config = StormConfig().get_rerank_config()
        except Exception as e:
            logger.warning(f"Cannot load StormConfig, fallback to none: {e}")
            config = {"backend": "none"}

        self._backend = backend or config.get("backend", "none")

        if self._backend == "cohere":
            self._api_key = api_key or config.get("cohere_api_key") or os.environ.get("COHERE_API_KEY", "")
            if not self._api_key:
                raise ValueError("Cohere Rerank requires an API key")
            logger.info("Reranker: Cohere backend")

        elif self._backend == "jina":
            self._api_key = api_key or config.get("jina_api_key") or os.environ.get("JINA_API_KEY", "")
            if not self._api_key:
                raise ValueError("Jina Reranker requires an API key")
            logger.info("Reranker: Jina backend")

        elif self._backend == "local":
            model = model_name or config.get("local_model", "cross-encoder/ms-marco-MiniLM-L-6-v2")
            try:
                from sentence_transformers import CrossEncoder
                self._local_model = CrossEncoder(model)
                logger.info(f"Reranker: local CrossEncoder loaded ({model})")
            except ImportError as e:
                raise ImportError(
                    f"sentence-transformers not installed for local reranker: {e}"
                )

        elif self._backend == "litellm":
            self._api_base = (api_base or config.get("litellm_base_url", "")).rstrip("/")
            self._api_key = api_key or config.get("litellm_api_key", "") or ""
            self._model = model_name or config.get("litellm_model", "") or ""
            if not self._api_base:
                raise ValueError("LiteLLM rerank requires base_url")
            logger.info(f"Reranker: LiteLLM backend ({self._api_base})")

        elif self._backend == "compat":
            self._api_base = (api_base or config.get("compat_base_url", "")).rstrip("/")
            self._api_key = api_key or config.get("compat_api_key", "") or ""
            self._model = model_name or config.get("compat_model", "") or ""
            if not self._api_base:
                raise ValueError("Compat rerank requires base_url")
            logger.info(f"Reranker: Compat backend ({self._api_base})")

        elif self._backend == "custom":
            self._api_base = (api_base or config.get("api_base", "")).rstrip("/")
            self._api_key = api_key or config.get("api_key", "") or ""
            self._model = model_name or config.get("model", "") or ""
            if not self._api_base:
                raise ValueError("Custom rerank requires base_url")
            logger.info(f"Reranker: custom backend ({self._api_base})")

        elif self._backend == "none":
            logger.info("Reranker: none (no reranking)")

        else:
            raise ValueError(f"Unsupported reranker backend: {self._backend}")

    # ── rerank ────────────────────────────────────────────────────────────

    def rerank(
        self, query: str, documents: List[str], top_k: int = 5
    ) -> List[Tuple[int, float]]:
        """
        对文档列表按与 query 的相关性重排序。

        Args:
            query: 查询字符串
            documents: 文档字符串列表
            top_k: 返回前 K 个结果

        Returns:
            [(原始索引, 相关性分数), ...] 按分数降序
        """
        if not documents:
            return []

        if self._backend == "none":
            return [(i, 1.0) for i in range(min(len(documents), top_k))]

        if self._backend == "cohere":
            return self._rerank_cohere(query, documents, top_k)
        elif self._backend == "jina":
            return self._rerank_jina(query, documents, top_k)
        elif self._backend == "local":
            return self._rerank_local(query, documents, top_k)
        elif self._backend == "litellm":
            return self._rerank_litellm(query, documents, top_k)
        elif self._backend == "compat":
            return self._rerank_compat(query, documents, top_k)
        elif self._backend == "custom":
            return self._rerank_custom(query, documents, top_k)

        return [(i, 1.0) for i in range(min(len(documents), top_k))]

    # ── 后端实现 ──────────────────────────────────────────────────────────

    def _rerank_cohere(self, query: str, docs: List[str], top_k: int) -> List[Tuple[int, float]]:
        import requests
        try:
            resp = requests.post(
                "https://api.cohere.com/v1/rerank",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"query": query, "documents": docs, "top_n": top_k, "model": "rerank-english-v3.0"},
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json()["results"]
            return [(item["index"], item["relevance_score"]) for item in results]
        except Exception as e:
            logger.error(f"Cohere rerank failed: {e}")
            return [(i, 1.0) for i in range(min(len(docs), top_k))]

    def _rerank_jina(self, query: str, docs: List[str], top_k: int) -> List[Tuple[int, float]]:
        import requests
        try:
            resp = requests.post(
                "https://api.jina.ai/v1/rerank",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "query": query, "documents": docs, "top_n": top_k,
                    "model": "jina-reranker-v2-base-multilingual",
                },
                timeout=30,
            )
            resp.raise_for_status()
            results = resp.json()["results"]
            return [(item["index"], item["relevance_score"]) for item in results]
        except Exception as e:
            logger.error(f"Jina rerank failed: {e}")
            return [(i, 1.0) for i in range(min(len(docs), top_k))]

    def _rerank_local(self, query: str, docs: List[str], top_k: int) -> List[Tuple[int, float]]:
        try:
            pairs = [(query, doc) for doc in docs]
            scores = self._local_model.predict(pairs)
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            return [(idx, float(score)) for idx, score in ranked[:top_k]]
        except Exception as e:
            logger.error(f"Local rerank failed: {e}")
            return [(i, 1.0) for i in range(min(len(docs), top_k))]

    def _rerank_litellm(self, query: str, docs: List[str], top_k: int) -> List[Tuple[int, float]]:
        """调用 LiteLLM proxy 的 /rerank 端点。
        兼容 Cohere 格式（query+documents+top_n）和 TEI 格式（query+texts+truncate）。"""
        import requests
        # 避免双 /rerank 路径
        base = self._api_base.rstrip("/")
        if base.endswith("/rerank"):
            base = base[:-7]
        url = f"{base}/rerank"
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        # 尝试 Cohere 格式
        payload_cohere = {"query": query, "documents": docs, "top_n": top_k}
        if self._model:
            payload_cohere["model"] = self._model
        try:
            resp = requests.post(url, headers=headers, json=payload_cohere, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", None)
            if results is not None:
                return [(item["index"], item["relevance_score"]) for item in results]
            # 如果返回了数据但没有 results 字段，可能是其他格式，尝试解析
            if isinstance(data, list) and len(data) > 0 and "score" in data[0]:
                return [(item["index"], item["score"]) for item in data]
        except Exception:
            pass

        # Cohere 格式失败 → 尝试 TEI 格式
        payload_tei = {"query": query, "texts": docs, "truncate": True}
        if self._model:
            payload_tei["model"] = self._model
        try:
            resp = requests.post(url, headers=headers, json=payload_tei, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return [(item["index"], item.get("score", item.get("relevance_score", 1.0))) for item in data]
            results = data.get("results", [])
            return [(item["index"], item.get("relevance_score", item.get("score", 1.0))) for item in results]
        except Exception as e:
            logger.error(f"Litellm rerank failed (tried both Cohere and TEI format): {e}")
            return [(i, 1.0) for i in range(min(len(docs), top_k))]

    def _rerank_compat(self, query: str, docs: List[str], top_k: int) -> List[Tuple[int, float]]:
        """通用 OpenAI 兼容接口 — 用户自定 endpoint + key + model，POST JSON。"""
        import requests
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {"query": query, "documents": docs, "top_n": top_k}
        if self._model:
            payload["model"] = self._model
        try:
            resp = requests.post(self._api_base, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return [(item["index"], item.get("score", item.get("relevance_score", 1.0))) for item in data]
            results = data.get("results", [])
            if results:
                return [(item["index"], item.get("relevance_score", item.get("score", 1.0))) for item in results]
        except Exception as e:
            logger.error(f"Compat rerank failed: {e}")
        return [(i, 1.0) for i in range(min(len(docs), top_k))]

    def _rerank_custom(self, query: str, docs: List[str], top_k: int) -> List[Tuple[int, float]]:
        """直连 Infinity rerank 端点。"""
        import requests
        try:
            resp = requests.post(
                f"{self._api_base}/rerank",
                headers={"Content-Type": "application/json"},
                json={"query": query, "documents": docs, "return_documents": False},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            items = [(item["index"], item["relevance_score"]) for item in results]
            return sorted(items, key=lambda x: x[1], reverse=True)[:top_k]
        except Exception as e:
            logger.error(f"Custom rerank failed: {e}")
            return [(i, 1.0) for i in range(min(len(docs), top_k))]
