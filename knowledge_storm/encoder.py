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
        self._backend = None
        self._local_model = None
        self.embedding_model_name = None
        self.kargs = {}
        self.total_token_usage = 0

        # 从 StormConfig 读取默认配置
        config = {}
        try:
            from cli.config_manager import StormConfig
            config = StormConfig().get_embed_config()
        except Exception as e:
            logger.warning(f"Cannot load StormConfig, fallback to local: {e}")
            config = {"backend": "local", "local_model": "paraphrase-MiniLM-L6-v2"}

        self._backend = backend or config.get("backend", "local")

        if self._backend == "local":
            # 懒加载 SentenceTransformer（仅此分支引入 torch）
            model_name = model_name or config.get("local_model", "paraphrase-MiniLM-L6-v2")
            try:
                from sentence_transformers import SentenceTransformer as _ST
                self._local_model = _ST(model_name)
                logger.info(f"Encoder: local backend loaded ({model_name})")
            except ImportError as e:
                raise ImportError(
                    f"SentenceTransformer not installed. Run: pip install sentence-transformers\n{e}"
                )

        elif self._backend == "openai":
            if not _LITELLM_AVAILABLE:
                raise ImportError("litellm not installed, cannot use openai backend")
            self.embedding_model_name = model_name or "text-embedding-3-small"
            self.kargs = {
                "api_key": api_key or config.get("openai_api_key") or os.getenv("OPENAI_API_KEY"),
            }

        elif self._backend == "compat":
            if not _LITELLM_AVAILABLE:
                raise ImportError("litellm not installed, cannot use compat backend")
            base = api_base or config.get("compat_base_url") or config.get("compat_base", "")
            key = api_key or config.get("compat_api_key") or ""
            model = model_name or config.get("compat_model", "text-embedding-3-small")
            self.embedding_model_name = f"openai/{model}"
            self.kargs = {"api_key": key, "api_base": base}

        elif self._backend == "litellm":
            if not _LITELLM_AVAILABLE:
                raise ImportError("litellm not installed")
            base = api_base or config.get("litellm_base_url", "")
            key = api_key or config.get("litellm_api_key", "")
            model = model_name or config.get("litellm_model", "text-embedding-3-small")
            self.embedding_model_name = model
            self.kargs = {"api_key": key, "api_base": base, "num_retries": 0}

        elif self._backend == "custom":
            self._api_base = (api_base or config.get("api_base", "")).rstrip("/")
            self._api_key = api_key or config.get("api_key", "")
            self.embedding_model_name = model_name or config.get("model", "bge-m3")
            self._direct = True

        else:
            raise ValueError(f"Unsupported encoder backend: {self._backend}")

    # ── encode ────────────────────────────────────────────────────────────

    def encode(self, texts: Union[str, List[str]], max_workers: int = 5) -> np.ndarray:
        """对外统一接口。"""
        if self._backend == "local":
            return self._encode_local(texts)
        if getattr(self, "_direct", False):
            return self._encode_direct(texts)
        return self._encode_remote(texts, max_workers=max_workers)

    def _encode_local(self, texts):
        if isinstance(texts, str):
            return self._local_model.encode([texts])[0]
        return self._local_model.encode(texts)

    def _encode_direct(self, texts):
        """直连 Infinity 嵌入端点，不走 litellm。"""
        import requests
        if isinstance(texts, str):
            texts = [texts]
        dim = 1024
        result = []
        for t in texts:
            if not t or not t.strip():
                result.append(np.zeros(dim))
                continue
            try:
                r = requests.post(
                    f"{self._api_base}/embeddings",
                    json={"input": t, "model": self.embedding_model_name},
                    timeout=30,
                )
                if r.status_code == 200:
                    data = r.json()
                    arr = data["data"][0]["embedding"]
                    result.append(np.array(arr))
                    dim = len(arr)
                else:
                    logger.error(f"Embedding HTTP {r.status_code}: {r.text[:100]}")
                    result.append(np.zeros(dim))
            except Exception as e:
                logger.error(f"Embedding error for {t[:30]}: {e}")
                result.append(np.zeros(dim))
        return np.array(result)

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
