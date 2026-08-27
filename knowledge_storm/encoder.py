"""
多后端 Encoder — 支持 OpenAI / 兼容接口 / 本地 SentenceTransformer

从 StormConfig 自动读取活跃配置，也接受显式参数覆盖。
"""

import os
import numpy as np
import logging

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union, Optional

logger = logging.getLogger(__name__)

# ── LiteLLM 初始化（可选） ──
try:
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        if "LITELLM_LOCAL_MODEL_COST_MAP" not in os.environ:
            os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        import litellm
        litellm.drop_params = True
        litellm.telemetry = False
    from litellm.caching.caching import Cache
    from pathlib import Path
    disk_cache_dir = os.path.join(Path.home(), ".storm_local_cache")
    litellm.cache = Cache(disk_cache_dir=disk_cache_dir, type="disk")
    _LITELLM_AVAILABLE = True
except ImportError:
    _LITELLM_AVAILABLE = False


class Encoder:
    """
    多后端编码器。
    后端:
      - "openai":  通过 litellm 调用 OpenAI embedding API
      - "compat":   通过 litellm 调用任何兼容 OpenAI 接口（DeepSeek/等）
      - "local":    本地 SentenceTransformer（需 torch）
    可通过 StormConfig 自动配置，也可显式传参。
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self._backend = backend or "local"
        self._local_model = None
        self.embedding_model_name = model_name or "text-embedding-3-small"
        self.kargs = {}
        self.total_token_usage = 0

        if self._backend == "local":
            model = model_name or "paraphrase-MiniLM-L6-v2"
            try:
                from sentence_transformers import SentenceTransformer as _ST
                self._local_model = _ST(model)
                logger.info(f"Encoder: local backend loaded ({model})")
            except ImportError as e:
                raise ImportError(
                    f"SentenceTransformer not installed. Run: pip install sentence-transformers\n{e}"
                )

        elif self._backend == "openai":
            if not _LITELLM_AVAILABLE:
                raise ImportError("litellm not installed, cannot use openai backend")
            self.embedding_model_name = model_name or "text-embedding-3-small"
            self.kargs = {
                "api_key": api_key or os.getenv("OPENAI_API_KEY", ""),
            }

        elif self._backend == "compat":
            if not _LITELLM_AVAILABLE:
                raise ImportError("litellm not installed, cannot use compat backend")
            base = api_base or ""
            key = api_key or ""
            model = model_name or "text-embedding-3-small"
            self.embedding_model_name = f"openai/{model}"
            self.kargs = {"api_key": key, "api_base": base}

        elif self._backend == "litellm":
            if not _LITELLM_AVAILABLE:
                raise ImportError("litellm not installed")
            base = api_base or ""
            key = api_key or ""
            model = model_name or "text-embedding-3-small"
            self.embedding_model_name = model
            self.kargs = {"api_key": key, "api_base": base, "num_retries": 0}

        elif self._backend == "custom":
            self._api_base = (api_base or "").rstrip("/")
            self._api_key = api_key or ""
            self.embedding_model_name = model_name or "bge-m3"
            self._direct = True

        else:
            raise ValueError(f"Unsupported encoder backend: {self._backend}")

    # ── encode ────────────────────────────────────────────────────────────

    def encode(self, texts: Union[str, List[str]], max_workers: int = 5) -> np.ndarray:
        """对外统一接口。"""
        if self._backend == "local":
            return self._encode_local(texts)
        if getattr(self, "_direct", False):
            return self._encode_direct_batch(texts)
        return self._encode_remote(texts, max_workers=max_workers)

    def _encode_local(self, texts):
        if isinstance(texts, str):
            return self._local_model.encode([texts])[0]
        return self._local_model.encode(texts)

    def _encode_direct_batch(self, texts: Union[str, List[str]], batch_size: int = 32) -> np.ndarray:
        """直连 Infinity/兼容嵌入端点，采用分批批处理降低网络 RTT。"""
        import requests

        is_single = isinstance(texts, str)
        text_list = [texts] if is_single else list(texts)

        if not text_list:
            return np.array([])

        dim = 1024
        all_embeddings = []
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        for i in range(0, len(text_list), batch_size):
            chunk = text_list[i : i + batch_size]
            # 保证输入非空
            clean_chunk = [t if (t and t.strip()) else " " for t in chunk]
            try:
                r = requests.post(
                    f"{self._api_base}/embeddings",
                    headers=headers,
                    json={"input": clean_chunk, "model": self.embedding_model_name},
                    timeout=30,
                )
                if r.status_code == 200:
                    data = r.json()
                    for item in data.get("data", []):
                        arr = item["embedding"]
                        all_embeddings.append(np.array(arr))
                        dim = len(arr)
                else:
                    logger.error(f"Embedding HTTP {r.status_code}: {r.text[:100]}")
                    for _ in chunk:
                        all_embeddings.append(np.zeros(dim))
            except Exception as e:
                logger.error(f"Embedding batch error: {e}")
                for _ in chunk:
                    all_embeddings.append(np.zeros(dim))

        res_array = np.array(all_embeddings)
        return res_array[0] if is_single else res_array

    def _encode_remote(self, texts, max_workers=5):
        if isinstance(texts, str):
            _, embedding, tokens = self._get_single_text_embedding(texts)
            self.total_token_usage += tokens
            return np.array(embedding)

        embeddings = []
        total_tokens = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._get_single_text_embedding, text): text
                for text in texts
            }
            for future in as_completed(futures):
                try:
                    text, embedding, tokens = future.result()
                    embeddings.append((text, embedding, tokens))
                    total_tokens += tokens
                except Exception as e:
                    logger.error(f"Embedding error for {futures[future]}: {e}")
            embeddings.sort(key=lambda x: texts.index(x[0]))
            embeddings = [r[1] for r in embeddings]
        self.total_token_usage += total_tokens
        return np.array(embeddings)

    def _get_single_text_embedding(self, text):
        response = litellm.embedding(
            model=self.embedding_model_name, input=text, caching=True, **self.kargs
        )
        embedding = response.data[0]["embedding"]
        token_usage = response.get("usage", {}).get("total_tokens", 0)
        return text, embedding, token_usage

    def get_total_token_usage(self, reset: bool = False) -> int:
        token_usage = self.total_token_usage
        if reset:
            self.total_token_usage = 0
        return token_usage
