"""认证服务：登录、当前用户信息。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import auth_required
from app.core.security import create_access_token, verify_password
from app.deps import CurrentUser
from app.models import Department, Role, User
from app.schemas.auth import DepartmentBrief, LoginResponse, RoleBrief, UserInfo


def build_user_info(user: User, department: Department | None) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        department_id=user.department_id,
        department=DepartmentBrief.model_validate(department) if department else None,
        roles=[RoleBrief.model_validate(r) for r in user.roles],
        status=user.status,
    )


async def login(session: AsyncSession, username: str, password: str) -> LoginResponse:
    user = (
        await session.execute(
            select(User)
            .where(User.username == username)
            .options(joinedload(User.roles), joinedload(User.dept))
        )
    ).unique().scalar_one_or_none()
    # 统一提示，避免暴露用户名是否存在
    if user is None or not verify_password(password, user.password_hash):
        raise auth_required("用户名或密码错误", code="INVALID_CREDENTIALS")
    if user.status != "active":
        raise auth_required("账号已停用，请联系管理员", code="ACCOUNT_DISABLED", status_code=403)

    token, ttl = create_access_token(user.id, {"username": user.username})
    permissions = await _permissions_of(session, [r.id for r in user.roles])
    return LoginResponse(
        access_token=token,
        expires_in=ttl,
        user_info=build_user_info(user, user.dept),
        permissions=sorted(permissions),
    )


async def _permissions_of(session: AsyncSession, role_ids: list[int]) -> set[str]:
    from app.models import RolePermission

    if not role_ids:
        return set()
    rows = await session.execute(
        select(RolePermission.permission_code).where(RolePermission.role_id.in_(role_ids))
    )
    return set(rows.scalars())


def me_response(current: CurrentUser) -> dict:
    return {
        "user_info": build_user_info(current.user, current.department),
        "permissions": sorted(current.permissions),
    }


__all__ = ["login", "me_response", "build_user_info", "Role"]
