"""认证与用户身份。"""

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RoleBrief(ORMModel):
    id: int
    role_name: str
    role_code: str


class DepartmentBrief(ORMModel):
    id: int
    name: str
    parent_id: int | None = None


class UserInfo(ORMModel):
    id: int
    username: str
    display_name: str
    department_id: int | None = None
    department: DepartmentBrief | None = None
    roles: list[RoleBrief] = []
    status: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_info: UserInfo
    permissions: list[str]
