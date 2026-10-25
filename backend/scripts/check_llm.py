"""一次性验证：用 .env 中配置的 LLM 做一次最小调用，确认 Base URL / Key / 模型名可用。

    uv run python scripts/check_llm.py
只输出结果与耗时，不打印 Key。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> int:
    s = get_settings()
    print(f"base_url={s.llm_base_url!r} model={s.llm_model!r} key_set={bool(s.llm_api_key)}")
    if not (s.llm_base_url and s.llm_api_key and s.llm_model):
        print("配置不完整")
        return 2
    client = OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=30)
    started = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=s.llm_model,
            messages=[{"role": "user", "content": "只回复两个字：可用"}],
            max_tokens=16,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"调用失败：{type(exc).__name__}: {exc}")
        return 1
    elapsed = time.perf_counter() - started
    print(f"内容={resp.choices[0].message.content!r}")
    print(f"usage={resp.usage.model_dump() if resp.usage else None}")
    print(f"耗时={elapsed:.2f}s")

    # 同时验证流式（M5 需要 SSE 增量输出）
    started = time.perf_counter()
    chunks = 0
    text = []
    stream = client.chat.completions.create(
        model=s.llm_model,
        messages=[{"role": "user", "content": "用一句话说明什么是知识库"}],
        max_tokens=64, temperature=0, stream=True, stream_options={"include_usage": True},
    )
    usage = None
    try:
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if chunk.choices and chunk.choices[0].delta.content:
                chunks += 1
                text.append(chunk.choices[0].delta.content)
    except Exception as exc:  # noqa: BLE001
        print(f"流式调用失败：{type(exc).__name__}: {exc}")
        return 1
    print(f"流式 chunks={chunks} 文本={''.join(text)[:80]!r} usage={usage.model_dump() if usage else None}")
    print(f"流式耗时={time.perf_counter() - started:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
