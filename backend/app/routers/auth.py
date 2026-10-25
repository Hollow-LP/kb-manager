from fastapi import APIRouter

from app.deps import CurrentUserDep, SessionDep
from app.schemas.auth import LoginRequest, LoginResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse, summary="用户名密码登录")
async def login(payload: LoginRequest, session: SessionDep) -> LoginResponse:
    return await auth_service.login(session, payload.username, payload.password)


@router.get("/me", summary="当前用户信息与权限")
async def me(current: CurrentUserDep) -> dict:
    return auth_service.me_response(current)


@router.post("/logout", summary="退出登录")
async def logout() -> dict:
    # JWT 无状态：前端清除 token 即可；此处保留接口用于日后黑名单/审计
    return {"ok": True}
