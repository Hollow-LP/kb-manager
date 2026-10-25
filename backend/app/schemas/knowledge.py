"""知识单元、数据权限、导入任务。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel

TargetType = Literal["global", "department", "role", "user"]
UnitStatus = Literal["parsing", "active", "disabled", "parse_failed", "archived"]


class PermissionTargetIn(BaseModel):
    target_type: TargetType
    target_id: int = 0

    @model_validator(mode="after")
    def _global_id(self) -> "PermissionTargetIn":
        if self.target_type == "global":
            self.target_id = 0
        elif self.target_id <= 0:
            raise ValueError("target_id 必须大于 0")
        return self


class PermissionEntry(ORMModel):
    target_type: TargetType
    target_id: int
    target_name: str | None = None


class Citation(ORMModel):
    unit_id: int
    unit_code: str
    title: str
    score: float = 0.0


class UnitItem(ORMModel):
    id: int
    unit_code: str
    title: str
    summary: str | None
    category: str | None
    tags: list[str] = []
    source_file_name: str | None
    file_type: str | None
    file_size: int | None
    status: UnitStatus
    creator_id: int | None
    creator_name: str | None = None
    permissions: list[PermissionEntry] = []
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class UnitDetail(UnitItem):
    content: str


class UnitUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    summary: str | None = None
    category: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = None
    status: Literal["active", "disabled"] | None = None


class UnitCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    summary: str | None = None
    category: str | None = Field(default=None, max_length=64)
    tags: list[str] = []


class AssignUnitPermissionsRequest(BaseModel):
    """全量替换某个知识单元的数据权限实体列表。"""

    targets: list[PermissionTargetIn]


class DeleteUnitsRequest(BaseModel):
    unit_ids: list[int] = Field(min_length=1)


class DeleteUnitsResponse(BaseModel):
    deleted_unit_ids: list[int]
    blocked_unit_ids: list[int]
    not_found_unit_ids: list[int]


class RestoreUnitsRequest(BaseModel):
    unit_ids: list[int] = Field(min_length=1)


class CheckPermissionsRequest(BaseModel):
    user_id: int
    unit_ids: list[int] = Field(min_length=1)


class AccessibleUnitsResponse(BaseModel):
    unit_ids: list[int]
    count: int


class CheckPermissionsResponse(BaseModel):
    authorized_unit_ids: list[int]
    unauthorized_unit_ids: list[int]


class ImportJobItem(ORMModel):
    id: int
    batch_id: str
    file_name: str
    file_type: str
    file_size: int
    status: str
    progress: int
    unit_id: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ImportBatchResponse(BaseModel):
    batch_id: str
    jobs: list[ImportJobItem]
