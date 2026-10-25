"""组织架构：部门、用户、角色、权限树。"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.permissions import PermissionType
from app.schemas.common import ORMModel
from app.schemas.auth import RoleBrief


class DepartmentNode(ORMModel):
    id: int
    parent_id: int | None
    name: str
    leader_id: int | None
    leader_name: str | None = None
    sort_order: int
    member_count: int = 0
    children: list["DepartmentNode"] = []


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None
    leader_id: int | None = None
    sort_order: int = 0


class DepartmentUpdate(DepartmentCreate):
    pass


class UserItem(ORMModel):
    id: int
    username: str
    display_name: str
    department_id: int | None
    department_name: str | None = None
    status: str
    roles: list[RoleBrief] = []
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    department_id: int | None = None
    role_ids: list[int] = []
    status: str = Field(default="active", pattern="^(active|disabled)$")


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    department_id: int | None = None
    role_ids: list[int] | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=64)


class RoleItem(ORMModel):
    id: int
    role_name: str
    role_code: str
    description: str | None
    permission_codes: list[str] = []
    user_count: int = 0
    is_builtin: bool = False
    created_at: datetime
    updated_at: datetime


class RoleCreate(BaseModel):
    role_name: str = Field(min_length=1, max_length=64)
    role_code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    description: str | None = Field(default=None, max_length=255)


class RoleUpdate(BaseModel):
    role_name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)


class PermissionNode(BaseModel):
    key: str
    label: str
    type: PermissionType
    children: list["PermissionNode"] = []


class AssignPermissionsRequest(BaseModel):
    permission_codes: list[str]

    def model_post_init(self, __context) -> None:
        from app.core.permissions import ALL_PERMISSIONS

        unknown = set(self.permission_codes) - set(ALL_PERMISSIONS)
        if unknown:
            raise ValueError(f"未知权限码: {sorted(unknown)}")
