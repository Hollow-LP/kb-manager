"""M7/M8：FAQ 规范化、LLM SSE 解析（带假服务器，不调用真实接口）、Token 兜底估算。"""

import asyncio
import json
import selectors
from pathlib import Path

import pytest

from app.services.faq_cache import normalize_question
from app.services.llm import LLMStreamResult, _estimate_tokens, stream_chat

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CRLF = b"\r\n"
NL = b"\n"


def test_normalize_question_ignores_punctuation_and_width():
    lines = [line for line in (FIXTURES / "faq_norm.txt").read_text(encoding="utf-8").splitlines() if line]
    norms = {normalize_question(line) for line in lines}
    # 同一问题的中英文标点、全/半角、空白差异归一为同一个键
    assert len(norms) == 2, norms


def test_normalize_question_keeps_digits_and_letters():
    assert normalize_question("IT 规范 v2.0?") == "it规范v20"


def test_normalize_question_empty():
    assert normalize_question("  ，。！") == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("abcd", 1), ("你好世界", 4), ("hello 世界", 3)],
)
def test_estimate_tokens(text, expected):
    assert _estimate_tokens(text) == expected


class FakeStreamServer:
    """最小 SSE 服务器：HTTP/1.1 + Connection: close，连接关闭标记响应结束。"""

    def __init__(self, frames: list[dict], status: int = 200):
        self.frames = frames
        self.status = status
        self.server = None

    async def __aenter__(self):
        frames, status = self.frames, self.status

        async def handler(reader, writer):
            try:
                while True:
                    line = await reader.readline()
                    if not line or line in (CRLF, NL):
                        break
                if status == 200:
                    head = (b"HTTP/1.1 200 OK" + CRLF + b"Content-Type: text/event-stream" + CRLF
                            + b"Connection: close" + CRLF + CRLF)
                    body = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
                    body += "data: [DONE]\n\n"
                else:
                    head = ((f"HTTP/1.1 {status} Error").encode() + CRLF
                            + b"Content-Type: application/json" + CRLF + b"Connection: close" + CRLF + CRLF)
                    body = json.dumps({"error": "boom"})
                writer.write(head + body.encode())
                await writer.drain()
            finally:
                writer.close()

        self.server = await asyncio.start_server(handler, "127.0.0.1", 0)
        return self

    @property
    def port(self) -> int:
        return self.server.sockets[0].getsockname()[1]

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()


def _chunk(content=None, reasoning=None, finish=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def _run(coro):
    return asyncio.run(coro, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))


def _use_server(monkeypatch, port: int):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_base_url", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "test-model")


def test_stream_chat_parses_delta_reasoning_and_usage(monkeypatch):
    frames = [
        _chunk(reasoning="先想一想"),
        _chunk(content="你好"),
        _chunk(content="，世界"),
        _chunk(finish="stop"),
        {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}},
    ]

    async def scenario():
        async with FakeStreamServer(frames) as server:
            _use_server(monkeypatch, server.port)
            result = LLMStreamResult()
            text = "".join([piece async for piece in stream_chat([{"role": "user", "content": "hi"}], result=result)])
            return text, result

    text, result = _run(scenario())
    assert text == "你好，世界"
    assert result.reasoning_chars == len("先想一想")
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (11, 3, 14)
    assert result.finish_reason == "stop"


def test_stream_chat_finish_length_sets_warning(monkeypatch):
    frames = [_chunk(content="截断了"), _chunk(finish="length")]

    async def scenario():
        async with FakeStreamServer(frames) as server:
            _use_server(monkeypatch, server.port)
            result = LLMStreamResult()
            async for _ in stream_chat([{"role": "user", "content": "hi"}], result=result):
                pass
            return result

    result = _run(scenario())
    assert result.finish_reason == "length"
    assert result.error and "截断" in result.error
    # 接口未返回 usage 时按文本估算，保证看板不为 0
    assert result.total_tokens > 0


def test_stream_chat_http_error_raises(monkeypatch):
    from app.services.llm import LLMError

    async def scenario():
        async with FakeStreamServer([], status=401) as server:
            _use_server(monkeypatch, server.port)
            async for _ in stream_chat([{"role": "user", "content": "hi"}]):
                pass

    with pytest.raises(LLMError) as exc_info:
        _run(scenario())
    assert exc_info.value.status == 401


def test_stream_chat_requires_configuration(monkeypatch):
    from app.config import get_settings
    from app.services.llm import LLMError

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_api_key", "")

    async def scenario():
        async for _ in stream_chat([{"role": "user", "content": "hi"}]):
            pass

    with pytest.raises(LLMError):
        _run(scenario())


def test_unknown_answer_marker_detection():
    """与挖掘一致：包含"未找到"等标记的回答不进入 FAQ 推荐。"""
    from app.services.mining import _is_unknown_answer

    samples = [s for s in (FIXTURES / "unknown_answers.txt").read_text(encoding="utf-8").splitlines() if s]
    positive = [s[2:] for s in samples if s.startswith("U|")]
    negative = [s[2:] for s in samples if s.startswith("A|")]
    assert positive and negative
    for text in positive:
        assert _is_unknown_answer(text), text
    for text in negative:
        assert not _is_unknown_answer(text), text
