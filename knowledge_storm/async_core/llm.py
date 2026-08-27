"""
STORM Async Core — 纯异步 LLM 客户端
基于 httpx.AsyncClient 实现，支持 OpenAI 标准 API、DeepSeek、Ollama 及兼容端点。
完全消除重型 DSPy 与 LiteLLM 代谢。
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
import httpx

logger = logging.getLogger(__name__)


class AsyncLLM:
    """现代纯异步 LLM 调用引擎。"""

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str = "",
        api_base: str = "https://api.deepseek.com",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 0.9,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.timeout = timeout
        self.max_retries = max_retries
        self.total_tokens_used = 0

        # 标准化 endpoint
        if not self.api_base.endswith("/v1") and "deepseek.com" not in self.api_base:
            self.endpoint = f"{self.api_base}/v1/chat/completions"
        else:
            self.endpoint = f"{self.api_base}/chat/completions"

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "You are a helpful and precise academic research assistant.",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> str:
        """异步生成文本（单次响应）。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        return await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
    ) -> str:
        """异步多轮对话。"""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "top_p": self.top_p,
        }
        if response_format:
            payload["response_format"] = response_format

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(1, self.max_retries + 1):
                try:
                    resp = await client.post(self.endpoint, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        usage = data.get("usage", {})
                        self.total_tokens_used += usage.get("total_tokens", 0)
                        content = data["choices"][0]["message"]["content"]
                        return content.strip()
                    elif resp.status_code in (429, 500, 502, 503, 504):
                        # 可重试错误
                        logger.warning(
                            f"LLM API temporary error (status {resp.status_code}) attempt {attempt}/{self.max_retries}: {resp.text[:100]}"
                        )
                    else:
                        logger.error(f"LLM API client error (status {resp.status_code}): {resp.text[:200]}")
                        return ""
                except Exception as e:
                    logger.warning(f"LLM API network error attempt {attempt}/{self.max_retries}: {e}")

                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        logger.error(f"LLM API failed after {self.max_retries} attempts.")
        return ""

    async def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """异步流式输出 Token。"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", self.endpoint, headers=headers, json=payload) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            continue
