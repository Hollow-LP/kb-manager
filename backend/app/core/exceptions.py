"""统一业务异常与错误响应：{ code, message, detail }。

异常统一使用 AppError 实例 + 工厂函数（auth_required / permission_denied / not_found）。
不要定义 AppError 子类：本环境下框架包装后的异常按子类匹配处理器会失效。
"""

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None,
                 detail: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code or {400: "BAD_REQUEST", 401: "AUTH_REQUIRED", 403: "PERMISSION_DENIED",
                             404: "NOT_FOUND"}.get(status_code or 400, "BAD_REQUEST")
        self.status_code = status_code or 400
        self.detail = detail


def auth_required(message: str = "请先登录", *, code: str = "AUTH_REQUIRED", status_code: int = 401,
                  detail: Any = None) -> AppError:
    return AppError(message, code=code, status_code=status_code, detail=detail)


def permission_denied(message: str = "您没有访问权限", *, code: str = "PERMISSION_DENIED",
                      detail: Any = None) -> AppError:
    return AppError(message, code=code, status_code=403, detail=detail)


def not_found(message: str = "资源不存在", *, detail: Any = None) -> AppError:
    return AppError(message, code="NOT_FOUND", status_code=404, detail=detail)


def _payload(code: str, message: str, detail: Any = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(status_code=exc.status_code,
                            content=_payload(exc.code, exc.message, exc.detail), headers=headers)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, exc: HTTPException):
        code = {401: "AUTH_REQUIRED", 403: "PERMISSION_DENIED", 404: "NOT_FOUND"}.get(
            exc.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=exc.status_code, content=_payload(code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = [{"loc": [str(x) for x in e.get("loc", ())], "msg": e.get("msg"), "type": e.get("type")}
                  for e in exc.errors()]
        return JSONResponse(status_code=422, content=_payload("VALIDATION_ERROR", "请求参数校验失败", errors))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        # 兜底：保证前端总能拿到 JSON 错误体，而不是纯文本 500
        import logging

        logging.getLogger("kb").exception("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content=_payload("INTERNAL_ERROR", "服务器内部错误"))
