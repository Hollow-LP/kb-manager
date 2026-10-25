from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from app.core.exceptions import AppError, auth_required, not_found, permission_denied
from app.deps import CurrentUserDep, SessionDep, is_internal_request, require_permission
from app.models import ImportJob
from app.schemas.common import OkResponse, Page
from app.schemas.knowledge import (
    AccessibleUnitsResponse,
    AssignUnitPermissionsRequest,
    CheckPermissionsRequest,
    CheckPermissionsResponse,
    DeleteUnitsRequest,
    DeleteUnitsResponse,
    ImportBatchResponse,
    ImportJobItem,
    PermissionEntry,
    RestoreUnitsRequest,
    UnitCreate,
    UnitDetail,
    UnitItem,
    UnitUpdate,
)
from app.services import knowledge as kb

router = APIRouter(prefix="/knowledge", tags=["知识管理"])

# 具有任一维护权限即视为"知识管理视角"，可查看全部单元
MANAGE_PERMISSIONS = (
    "knowledge:unit:update", "knowledge:unit:delete", "knowledge:permission:update", "knowledge:import:view",
)


# ------------------------------------------------------------------ 导入（M3.S2）

@router.post("/import", response_model=ImportBatchResponse, summary="单文件 / 多文件批量导入",
             dependencies=[Depends(require_permission("knowledge:import:create"))])
async def import_files(
    current: CurrentUserDep,
    session: SessionDep,
    files: Annotated[list[UploadFile], File(description="支持 PDF、DOCX、Markdown、TXT，可多选")],
) -> ImportBatchResponse:
    payload = [(f.filename or "unnamed", await f.read()) for f in files]
    batch_id, jobs = await kb.create_import_jobs(session, payload, creator_id=current.id)
    await session.commit()
    kb.enqueue(jobs)
    return ImportBatchResponse(batch_id=batch_id, jobs=[ImportJobItem.model_validate(j) for j in jobs])


@router.get("/import/jobs", response_model=list[ImportJobItem], summary="导入进度（按批次轮询）",
            dependencies=[Depends(require_permission("knowledge:import:view"))])
async def import_jobs(session: SessionDep, batch_id: str | None = None,
                      limit: int = Query(100, ge=1, le=500)) -> list[ImportJobItem]:
    return await kb.list_import_jobs(session, batch_id, limit)


@router.post("/import/jobs/{job_id}/retry", response_model=ImportJobItem, summary="重试失败的导入任务",
             dependencies=[Depends(require_permission("knowledge:import:create"))])
async def retry_import(job_id: int, session: SessionDep) -> ImportJobItem:
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise not_found("导入任务不存在")
    if job.status != "failed":
        raise AppError("只能重试失败的任务", status_code=400)
    job.status, job.progress, job.error_message = "pending", 0, None
    await session.commit()
    kb.enqueue([job])
    return ImportJobItem.model_validate(job)


# ------------------------------------------------------------------ 知识单元（M3.S3）

@router.get("/units", response_model=Page[UnitItem], summary="知识单元分页查询",
            dependencies=[Depends(require_permission("knowledge:unit:view"))])
async def units(
    session: SessionDep,
    current: CurrentUserDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    category: str | None = None,
    status: str | None = Query(None, pattern="^(parsing|active|disabled|parse_failed|archived)$"),
    file_type: str | None = Query(None, pattern="^(pdf|docx|md|txt)$"),
    creator_id: int | None = None,
    include_deleted: bool = False,
    scope: str = Query("all", pattern="^(all|mine)$",
                       description="all=全部单元（知识管理视角）；mine=仅当前用户有数据权限的单元"),
) -> Page[UnitItem]:
    """列表按数据权限过滤。

    - scope=all：全部单元（知识管理视角，需维护权限；普通用户请求会被强制降级为 mine）
    - scope=mine：仅当前用户有数据权限的单元
    """
    manage = current.has_any(MANAGE_PERMISSIONS)
    if scope == "all" and not manage:
        scope = "mine"
    viewer = await kb.load_viewer(session, current.id) if not manage else None
    if viewer is None and not manage:
        raise auth_required("登录状态无效")
    items, total = await kb.list_units(
        session, page=page, page_size=page_size, keyword=keyword, category=category, status=status,
        file_type=file_type, creator_id=creator_id, only_ids=None, include_deleted=include_deleted,
        viewer=viewer,
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/units/categories", response_model=list[str], summary="已有分类",
            dependencies=[Depends(require_permission("knowledge:unit:view"))])
async def categories(session: SessionDep) -> list[str]:
    return await kb.list_categories(session)


@router.post("/units", response_model=UnitDetail, summary="手动创建知识单元",
             dependencies=[Depends(require_permission("knowledge:unit:create"))])
async def create_unit(payload: UnitCreate, session: SessionDep, current: CurrentUserDep) -> UnitDetail:
    unit = await kb.create_unit(session, title=payload.title, content=payload.content, summary=payload.summary,
                                category=payload.category, tags=payload.tags, creator_id=current.id)
    await session.commit()
    return await kb.get_unit(session, unit.id)


@router.get("/units/{unit_id}", response_model=UnitDetail, summary="单元详情（含数据权限）",
            dependencies=[Depends(require_permission("knowledge:unit:view"))])
async def get_unit(unit_id: int, session: SessionDep, current: CurrentUserDep, include_deleted: bool = False) -> UnitDetail:
    # 管理后台需能打开任意单元进行维护（列表本就展示全部单元），因此持有维护权限的管理员不受数据权限拦截；
    # 普通用户只能打开自己有数据权限的单元。AI 问答的数据权限过滤在检索链路上单独执行（M5），不依赖此接口。
    return await kb.get_unit(session, unit_id, include_deleted=include_deleted, check_access_for=current.id,
                             bypass_access=current.has_any(MANAGE_PERMISSIONS))


@router.put("/units/{unit_id}", response_model=UnitDetail,
            summary="更新单元（正文变更时自动重建切片与向量）",
            dependencies=[Depends(require_permission("knowledge:unit:update"))])
async def update_unit(unit_id: int, payload: UnitUpdate, session: SessionDep) -> UnitDetail:
    await kb.update_unit(session, unit_id, payload)
    await session.commit()
    return await kb.get_unit(session, unit_id)


@router.delete("/units", response_model=DeleteUnitsResponse, summary="批量删除单元（软删除）",
               dependencies=[Depends(require_permission("knowledge:unit:delete"))])
async def delete_units(payload: DeleteUnitsRequest, session: SessionDep) -> DeleteUnitsResponse:
    result = await kb.delete_units(session, payload.unit_ids)
    await session.commit()
    return DeleteUnitsResponse(**result)


@router.delete("/units/{unit_id}", response_model=OkResponse, summary="删除单个单元",
               dependencies=[Depends(require_permission("knowledge:unit:delete"))])
async def delete_unit(unit_id: int, session: SessionDep) -> OkResponse:
    result = await kb.delete_units(session, [unit_id])
    await session.commit()
    if result["blocked_unit_ids"]:
        raise AppError("该单元已被已发布的 FAQ 关联，不能删除", status_code=400)
    return OkResponse()


@router.post("/units/restore", response_model=list[int], summary="恢复已删除单元",
             dependencies=[Depends(require_permission("knowledge:unit:delete"))])
async def restore_units(payload: RestoreUnitsRequest, session: SessionDep) -> list[int]:
    restored = await kb.restore_units(session, payload.unit_ids)
    await session.commit()
    return restored


# ------------------------------------------------------------------ 数据权限（M3.S4）

@router.post("/units/{unit_id}/permissions", response_model=list[PermissionEntry],
             summary="配置数据权限实体（全量替换：全局/部门/角色/个人混合）",
             dependencies=[Depends(require_permission("knowledge:permission:update"))])
async def assign_permissions(unit_id: int, payload: AssignUnitPermissionsRequest,
                             session: SessionDep) -> list[PermissionEntry]:
    entries = await kb.assign_permissions(session, unit_id, payload.targets)
    await session.commit()
    return entries


# ------------------------------------------------------------------ 鉴权（M4.S1）

@router.post("/check-permissions", response_model=CheckPermissionsResponse,
             summary="鉴权：返回用户对给定单元的授权 / 未授权列表")
async def check_permissions(payload: CheckPermissionsRequest, request: Request, session: SessionDep,
                            current: CurrentUserDep) -> CheckPermissionsResponse:
    """普通用户只能查自己；AI 服务内部调用携带 X-Internal-Service-Token 可代为查询。"""
    if payload.user_id != current.id and not is_internal_request(request):
        raise permission_denied("只能查询自己的数据权限")
    authorized = await kb.authorized_unit_ids(session, payload.user_id, payload.unit_ids)
    ordered = [i for i in dict.fromkeys(payload.unit_ids) if i in authorized]
    return CheckPermissionsResponse(
        authorized_unit_ids=ordered,
        unauthorized_unit_ids=sorted(set(payload.unit_ids) - authorized),
    )



@router.get("/accessible-units", response_model=AccessibleUnitsResponse,
            summary="当前用户可访问的单元 ID 全集（AI 检索召回后过滤 / 前端权限提示）")
async def accessible_units(request: Request, session: SessionDep, current: CurrentUserDep,
                           user_id: int | None = None) -> AccessibleUnitsResponse:
    """普通用户按自己计算；AI 服务内部调用可通过 user_id 代查。"""
    target = current.id
    if user_id is not None and user_id != current.id:
        if not is_internal_request(request):
            raise permission_denied("只能查询自己的数据权限")
        target = user_id
    viewer = await kb.load_viewer(session, target)
    if viewer is None:
        return AccessibleUnitsResponse(unit_ids=[], count=0)
    ids = sorted(await kb.accessible_unit_ids(session, viewer))
    return AccessibleUnitsResponse(unit_ids=ids, count=len(ids))
