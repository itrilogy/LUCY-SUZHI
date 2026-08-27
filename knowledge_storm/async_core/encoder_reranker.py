"""
STORM Async Core — 纯异步 Embedding 与 Rerank 模块
支持批处理请求 (Batch Embedding / Rerank)，直连 Infinity 或第三方 API。
零 PyTorch / Transformers 本地依赖。
"""

import asyncio
import logging
from typing import List, Tuple, Optional, Union
import httpx

logger = logging.getLogger(__name__)


class AsyncEncoder:
    """异步 RESTful Batch 编码器。"""

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        model_name: str = "bge-m3",
        batch_size: int = 32,
        timeout: float = 30.0,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.batch_size = batch_size
        self.timeout = timeout

    async def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量异步请求文本嵌入向量。"""
        if not texts or not self.api_base:
            return [[0.0] * 1024 for _ in texts]

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.api_base}/embeddings" if not self.api_base.endswith("/embeddings") else self.api_base
        all_embeddings: List[List[float]] = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(0, len(texts), self.batch_size):
                chunk = texts[i : i + self.batch_size]
                clean_chunk = [t if (t and t.strip()) else " " for t in chunk]
                try:
                    resp = await client.post(
                        url,
                        headers=headers,
                        json={"input": clean_chunk, "model": self.model_name},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data.get("data", []):
                            all_embeddings.append(item.get("embedding", []))
                    else:
                        logger.error(f"AsyncEncoder HTTP {resp.status_code}: {resp.text[:100]}")
                        all_embeddings.extend([[0.0] * 1024 for _ in chunk])
                except Exception as e:
                    logger.error(f"AsyncEncoder network error: {e}")
                    all_embeddings.extend([[0.0] * 1024 for _ in chunk])

        return all_embeddings


class AsyncReranker:
    """异步 RESTful 重排序器。"""

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        model_name: str = "bge-reranker-v2-m3",
        timeout: float = 30.0,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout

    async def rerank(
        self, query: str, documents: List[str], top_k: int = 5
    ) -> List[Tuple[int, float]]:
        """
        对文档列表按相关性重排序。
        返回: [(原始索引, 得分), ...]
        """
        if not documents:
            return []
        if not self.api_base:
            return [(i, 1.0) for i in range(min(len(documents), top_k))]

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.api_base}/rerank" if not self.api_base.endswith("/rerank") else self.api_base

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={
                        "query": query,
                        "documents": documents,
                        "top_n": top_k,
                        "model": self.model_name,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    return [(item["index"], float(item["relevance_score"])) for item in results]
                else:
                    logger.warning(f"AsyncReranker HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                logger.warning(f"AsyncReranker error: {e}")

        return [(i, 1.0) for i in range(min(len(documents), top_k))]
