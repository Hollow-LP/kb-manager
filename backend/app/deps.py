"""FastAPI 依赖：数据库会话、当前用户、操作权限。"""

from typing import Annotated

from fastapi import Depends, Request
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.core.exceptions import AppError, auth_required, permission_denied
from app.core.security import decode_access_token
from app.db import get_session
from app.models import Department, Role, RolePermission, User, UserRole

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class CurrentUser:
    """登录用户及其角色/权限集合。

    每次请求实时从数据库计算，管理员调整角色权限后立即生效。
    `user.roles` / `user.dept` 由查询时 joinedload 预加载，可直接用于响应序列化。
    """

    def __init__(self, user: User, department: Department | None, roles: list[Role], permissions: set[str]):
        self.user = user
        self.id = user.id
        self.department = department
        self.roles = roles
        self.permissions = permissions

    @property
    def role_ids(self) -> list[int]:
        return [r.id for r in self.roles]

    @property
    def department_id(self) -> int | None:
        return self.user.department_id

    def has(self, code: str) -> bool:
        return code in self.permissions

    def has_any(self, codes: tuple[str, ...]) -> bool:
        return any(c in self.permissions for c in codes)

    def is_system_admin(self) -> bool:
        from app.core.permissions import SYSTEM_ADMIN

        return any(r.role_code == SYSTEM_ADMIN for r in self.roles)


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


async def get_current_user(request: Request, session: SessionDep) -> CurrentUser:
    token = _bearer_token(request)
    if not token:
        raise auth_required()
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise auth_required("登录已过期，请重新登录", code="TOKEN_INVALID") from exc

    user = (
        await session.execute(
            select(User).where(User.id == user_id).options(joinedload(User.roles), joinedload(User.dept))
        )
    ).unique().scalar_one_or_none()
    if user is None:
        raise auth_required("用户不存在")
    if user.status != "active":
        raise permission_denied("账号已停用", code="ACCOUNT_DISABLED")

    role_ids = [r.id for r in user.roles]
    perms: set[str] = set()
    if role_ids:
        perms = set(
            (
                await session.execute(
                    select(RolePermission.permission_code).where(RolePermission.role_id.in_(role_ids))
                )
            ).scalars()
        )
    return CurrentUser(user, user.dept, list(user.roles), perms)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_permission(code: str):
    async def _checker(user: CurrentUserDep) -> CurrentUser:
        if not user.has(code):
            raise permission_denied(f"缺少操作权限: {code}")
        return user

    return _checker


def is_internal_request(request: Request) -> bool:
    token = request.headers.get("X-Internal-Service-Token")
    return bool(token) and token == get_settings().internal_service_token
