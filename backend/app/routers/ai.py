import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.exceptions import permission_denied
from app.deps import CurrentUserDep, SessionDep, require_permission
from app.schemas.chat import ChatRequest, MessageItem, SessionItem
from app.services import chat as chat_service
from app.services.llm import llm_available

router = APIRouter(prefix="/ai", tags=["AI 问答"])


@router.get("/sessions", response_model=list[SessionItem], summary="我的会话列表")
async def sessions(session: SessionDep, current: CurrentUserDep) -> list[dict]:
    return await chat_service.list_sessions(session, current.id)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageItem], summary="会话消息")
async def messages(session_id: int, session: SessionDep, current: CurrentUserDep) -> list[dict]:
    return await chat_service.list_messages(session, current.id, session_id)


@router.delete("/sessions/{session_id}", summary="删除会话")
async def delete_session(session_id: int, session: SessionDep, current: CurrentUserDep) -> dict:
    await chat_service.delete_session(session, current.id, session_id)
    await session.commit()
    return {"ok": True}


@router.post("/chat/stream", summary="鉴权问答（SSE 流式）",
             dependencies=[Depends(require_permission("knowledge:ai:access"))])
async def chat_stream(payload: ChatRequest, session: SessionDep, current: CurrentUserDep) -> StreamingResponse:
    """事件：meta / citation / missing / delta / done / error。

    - 登录态与 AI 访问权限由依赖校验（401 / 403）
    - 召回 → 数据权限引擎过滤 → 仅授权资料进入 Prompt → 未授权单元发送 missing 事件
    """
    if not llm_available():
        raise permission_denied("服务未配置问答模型，请联系管理员", code="LLM_UNAVAILABLE", status_code=503)
    prepared = await chat_service.prepare(
        session, user_id=current.id, question=payload.question, session_id=payload.session_id,
        department_id=current.department_id, role_ids=current.role_ids,
    )
    await session.commit()   # 先提交会话与用户消息，生成过程中用独立连接写日志

    async def event_stream():
        async for ev in chat_service.stream_answer(prepared, current.id):
            yield f"event: {ev.event}\ndata: {__import__('json').dumps(ev.data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
