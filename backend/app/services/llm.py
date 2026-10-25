"""LLM 与 Embedding 提供方。

Embedding：
  - local：sentence-transformers 加载 BAAI/bge-small-zh-v1.5（512 维，模型懒加载并缓存到本地）
  - openai_compatible：调用 OpenAI 兼容的 /embeddings 接口，维度需与 EMBEDDING_DIM 一致

LLM：OpenAI 兼容接口，流式（SSE）输出。SiliconFlow 实测（2026-10-23，XingChenAGI/Xing4.0-29B）：
  - 思考型模型默认返回 reasoning_content，正文通常在思考后才开始；`enable_thinking=false` 可关闭思考、显著提速
  - usage 在一次性 [DONE] 之前的独立 chunk 中返回（choices 为空），openai SDK 在流式时不一定暴露，
    因此 stream_chat 直接解析 SSE，保证 token 统计准确
  - 普通 chat.completions.create(stream=True) 返回的其实是 (chunks, usage) 元组，不要按流对象遍历
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator

import httpx

from app.config import get_settings


class EmbeddingError(RuntimeError):
    pass


class LocalEmbedding:
    _model = None
    _lock = threading.Lock()

    @classmethod
    def _load(cls):
        if cls._model is None:
            with cls._lock:
                if cls._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as exc:
                        raise EmbeddingError(
                            "未安装 sentence-transformers，请执行 uv sync --extra ml，"
                            "或将 EMBEDDING_PROVIDER 改为 openai_compatible"
                        ) from exc
                    model_name = get_settings().embedding_model
                    try:
                        cls._model = SentenceTransformer(model_name)
                    except OSError as exc:
                        raise EmbeddingError(
                            f"无法加载本地 Embedding 模型 {model_name}（首次需联网下载）。"
                            f"可先执行 scripts/download_model.py，或修改 EMBEDDING_MODEL / EMBEDDING_PROVIDER"
                        ) from exc
        return cls._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
        return [v.tolist() for v in vectors]


class OpenAIEmbedding:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.llm_base_url or not settings.llm_api_key:
            raise EmbeddingError("openai_compatible Embedding 需要配置 LLM_BASE_URL 与 LLM_API_KEY")
        from openai import OpenAI

        self._client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
        self._model = settings.embedding_model

    def encode(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]


def get_embedder() -> LocalEmbedding | OpenAIEmbedding:
    provider = get_settings().embedding_provider
    if provider == "openai_compatible":
        return OpenAIEmbedding()
    return LocalEmbedding()


def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return get_embedder().encode(texts)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """异步接口：本地模型是 CPU 阻塞调用，放到线程池。"""
    if not texts:
        return []
    return await asyncio.to_thread(embed_texts_sync, texts)


async def embed_query(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]


def llm_available() -> bool:
    settings = get_settings()
    return bool(settings.llm_base_url and settings.llm_api_key and settings.llm_model)


class LLMError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMStreamResult:
    """流式调用结束后汇总的用量。"""

    def __init__(self) -> None:
        self.content = ""
        self.reasoning_chars = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.finish_reason: str | None = None
        self.error: str | None = None


def _estimate_tokens(text: str) -> int:
    """接口未返回 usage 时的兜底估算：中文约 1 字 1 token，其余约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if ord(ch) >= 0x2E80)
    return cjk + (len(text) - cjk) // 4


async def stream_chat(messages: list[dict], *, result: LLMStreamResult | None = None,
                      max_tokens: int | None = None) -> AsyncIterator[str]:
    """调用 LLM 并以增量文本流返回正文（不含思考内容）。

    失败时抛出 LLMError；已输出部分内容后中断则设置 result.error 并结束流。
    用量写入传入的 result 对象（默认自动创建，可通过 result 属性取回）。
    """
    settings = get_settings()
    if not llm_available():
        raise LLMError("未配置 LLM（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）", status=503)
    result = result or LLMStreamResult()
    body: dict = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": max_tokens or settings.llm_max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if not settings.llm_enable_thinking:
        # SiliconFlow 兼容参数；不支持该参数的供应商会忽略未知字段
        body["enable_thinking"] = False
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Accept": "text/event-stream"}
    timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                                     json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "replace")[:500]
                    raise LLMError(f"LLM 接口返回 {resp.status_code}: {detail}", status=resp.status_code)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usage")
                    if usage:
                        result.prompt_tokens = usage.get("prompt_tokens") or 0
                        result.completion_tokens = usage.get("completion_tokens") or 0
                        result.total_tokens = usage.get("total_tokens") or 0
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("reasoning_content"):
                            result.reasoning_chars += len(delta["reasoning_content"])
                        text = delta.get("content")
                        if text:
                            result.content += text
                            yield text
                        if choice.get("finish_reason"):
                            result.finish_reason = choice["finish_reason"]
    except LLMError:
        raise
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM 连接失败：{exc}") from exc
    if not result.total_tokens:
        # 供应商未返回 usage 时估算，保证看板 Token 统计不为 0
        result.prompt_tokens = _estimate_tokens(json.dumps(messages, ensure_ascii=False))
        result.completion_tokens = _estimate_tokens(result.content)
        result.total_tokens = result.prompt_tokens + result.completion_tokens
    if result.finish_reason == "length":
        result.error = "回答因长度上限被截断"
