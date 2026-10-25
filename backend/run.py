"""Windows 开发入口：psycopg async 不支持 ProactorEventLoop，需显式使用 Selector 事件循环。

用法：uv run python run.py        （等价于 uvicorn app.main:app，但保证事件循环兼容）
"""

import asyncio
import selectors
import sys

import uvicorn


def _loop_factory():
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return None


if __name__ == "__main__":
    from app.config import get_settings

    settings = get_settings()
    config = uvicorn.Config("app.main:app", host=settings.api_host, port=settings.api_port, reload=False)
    server = uvicorn.Server(config)
    if _loop_factory() is not None:
        asyncio.run(server.serve(), loop_factory=_loop_factory)
    else:
        server.run()
