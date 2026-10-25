"""知识单元服务：导入任务、解析入库、CRUD、数据权限配置、鉴权计算。

导入流程（后台协程，IMPORT_WORKERS 个 worker）：
    pending → parsing（解析 + 切片 + 建单元 status=parsing）→ embedding（向量化）
            → success（单元 active）
    失败：job=failed + error_message；已建单元置 parse_failed。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AppError, not_found, permission_denied
from app.db import SessionLocal
from app.models import Department, Faq, ImportJob, KnowledgeUnit, Role, UnitChunk, UnitPermission, User
from app.schemas.knowledge import ImportJobItem, PermissionEntry, PermissionTargetIn, UnitDetail, UnitItem, UnitUpdate
from app.services import storage
from app.services.llm import embed_texts
from app.services.parser import parse as parse_document, detect_type
from app.services.parser.splitter import split_markdown, split_text

log = logging.getLogger("kb.knowledge")


# ============================================================ 导入队列

class ImportQueue:
    """进程内导入队列：N 个 worker 协程消费 job_id；重启后由 recover_pending_jobs 重新入队。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []

    async def start(self) -> None:
        if self._workers:
            return
        for i in range(get_settings().import_workers):
            self._workers.append(asyncio.create_task(self._worker(), name=f"import-worker-{i}"))

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        self._workers.clear()

    def submit(self, job_id: int) -> None:
        self._queue.put_nowait(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("import job %s crashed", job_id)
            finally:
                self._queue.task_done()


import_queue = ImportQueue()


async def recover_pending_jobs() -> int:
    """启动时把未完成的导入任务重新入队（进程崩溃后恢复）。"""
    async with SessionLocal() as session:
        ids = (
            await session.execute(
                select(ImportJob.id).where(ImportJob.status.in_(("pending", "parsing", "embedding")))
            )
        ).scalars().all()
    for job_id in ids:
        import_queue.submit(job_id)
    return len(ids)


async def create_import_jobs(session: AsyncSession, files: list[tuple[str, bytes]], creator_id: int) -> tuple[str, list[ImportJob]]:
    """校验并落盘，创建一批 pending 任务（调用方负责 commit 后再入队）。"""
    settings = get_settings()
    max_bytes = settings.upload_max_size_mb * 1024 * 1024
    if not files:
        raise AppError("请至少上传一个文件", status_code=422)
    checked: list[tuple[str, bytes, str]] = []
    for file_name, data in files:
        file_type = detect_type(file_name)
        if not data:
            raise AppError(f"文件为空: {file_name}", code="EMPTY_FILE", status_code=422)
        if len(data) > max_bytes:
            raise AppError(f"文件超过 {settings.upload_max_size_mb}MB: {file_name}",
                           code="FILE_TOO_LARGE", status_code=413)
        checked.append((file_name, data, file_type))

    batch_id = uuid.uuid4().hex[:16]
    jobs: list[ImportJob] = []
    for file_name, data, file_type in checked:
        rel = storage.save_upload(file_name, data)
        job = ImportJob(batch_id=batch_id, file_name=file_name, file_type=file_type, file_size=len(data),
                        storage_path=rel, status="pending", progress=0, creator_id=creator_id)
        session.add(job)
        jobs.append(job)
    await session.flush()
    return batch_id, jobs


def enqueue(jobs: list[ImportJob]) -> None:
    for job in jobs:
        import_queue.submit(job.id)


async def list_import_jobs(session: AsyncSession, batch_id: str | None, limit: int = 100) -> list[ImportJobItem]:
    stmt = select(ImportJob).order_by(ImportJob.id.desc()).limit(limit)
    if batch_id:
        stmt = stmt.where(ImportJob.batch_id == batch_id)
    jobs = (await session.execute(stmt)).scalars().all()
    return [ImportJobItem.model_validate(j) for j in jobs]


async def process_job(job_id: int) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        job = await session.get(ImportJob, job_id)
        if job is None or job.status == "success":
            return
        try:
            job.status, job.progress, job.error_message = "parsing", 10, None
            await session.commit()

            data = storage.read_stored(job.storage_path or "")
            doc = await asyncio.to_thread(parse_document, job.file_name, data)
            chunks = (
                split_markdown(doc.markdown) if doc.file_type == "md"
                else split_text(doc.text, max_chars=settings.chunk_max_chars)
            )
            if not chunks:
                raise AppError("文档未切分出有效内容", code="PARSE_FAILED", status_code=422)

            unit = KnowledgeUnit(
                unit_code=await _next_unit_code(session),
                title=((doc.title_hint or "").strip() or _title_from_file(job.file_name))[:255],
                content=doc.markdown or doc.text,
                summary=doc.summary or None,
                tags=[],
                source_file_name=job.file_name,
                file_type=job.file_type,
                file_size=job.file_size,
                status="parsing",
                creator_id=job.creator_id,
            )
            session.add(unit)
            await session.flush()
            job.unit_id, job.progress = unit.id, 40
            await session.commit()

            job.status, job.progress = "embedding", 50
            await session.commit()
            vectors = await embed_texts([c["content"] for c in chunks])
            session.add_all([
                UnitChunk(unit_id=unit.id, chunk_index=i, heading=c["heading"], content=c["content"],
                          token_count=c["token_count"], embedding=v)
                for i, (c, v) in enumerate(zip(chunks, vectors))
            ])
            unit.status = "active"
            job.status, job.progress = "success", 100
            await session.commit()
            log.info("import job %s -> %s (%d chunks)", job.id, unit.unit_code, len(chunks))
        except Exception as exc:
            await session.rollback()
            failed_job = await session.get(ImportJob, job_id)
            if failed_job is None:
                return
            if failed_job.unit_id:
                failed_unit = await session.get(KnowledgeUnit, failed_job.unit_id)
                if failed_unit is not None and failed_unit.status == "parsing":
                    failed_unit.status = "parse_failed"
            failed_job.status = "failed"
            failed_job.progress = 100
            failed_job.error_message = (getattr(exc, "message", None) or str(exc))[:2000]
            await session.commit()
            log.warning("import job %s failed: %s", job_id, exc)


def _title_from_file(file_name: str) -> str:
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    return stem.replace("_", " ").replace("-", " ").strip() or file_name


async def _next_unit_code(session: AsyncSession) -> str:
    """KU-0001 递增编号；advisory lock 防止并发导入重复。"""
    await session.execute(text("SELECT pg_advisory_xact_lock(9527)"))
    max_no = (
        await session.execute(
            text(
                "SELECT COALESCE(MAX(CAST(SUBSTRING(unit_code FROM 4) AS INTEGER)), 0) "
                "FROM knowledge_units WHERE unit_code LIKE 'KU-%'"
            )
        )
    ).scalar_one()
    return f"KU-{int(max_no) + 1:04d}"


# ============================================================ 查询

def _unit_item(unit: KnowledgeUnit, permissions: list[PermissionEntry], chunk_count: int,
               creator_name: str | None) -> UnitItem:
    return UnitItem(
        id=unit.id, unit_code=unit.unit_code, title=unit.title, summary=unit.summary,
        category=unit.category, tags=unit.tags or [], source_file_name=unit.source_file_name,
        file_type=unit.file_type, file_size=unit.file_size, status=unit.status,
        creator_id=unit.creator_id, creator_name=creator_name, permissions=permissions,
        chunk_count=chunk_count, created_at=unit.created_at, updated_at=unit.updated_at,
    )


async def permission_entries(session: AsyncSession, unit_ids: list[int]) -> dict[int, list[PermissionEntry]]:
    if not unit_ids:
        return {}
    rows = (
        await session.execute(select(UnitPermission).where(UnitPermission.unit_id.in_(unit_ids)))
    ).scalars().all()
    ids_by_type: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        ids_by_type[r.target_type].add(r.target_id)
    names: dict[tuple[str, int], str] = {}
    model_by_type = {"department": Department, "role": Role, "user": User}
    for ttype, model in model_by_type.items():
        ids = ids_by_type.get(ttype)
        if not ids:
            continue
        for obj in (await session.execute(select(model).where(model.id.in_(ids)))).scalars():
            names[(ttype, obj.id)] = obj.name if ttype == "department" else (
                obj.role_name if ttype == "role" else obj.display_name
            )
    order = ["global", "department", "role", "user"]
    result: dict[int, list[PermissionEntry]] = defaultdict(list)
    for r in sorted(rows, key=lambda x: order.index(x.target_type)):
        label = "全局公开" if r.target_type == "global" else names.get((r.target_type, r.target_id))
        result[r.unit_id].append(PermissionEntry(target_type=r.target_type, target_id=r.target_id, target_name=label))
    return result


async def list_units(
    session: AsyncSession, *, page: int, page_size: int, keyword: str | None, category: str | None,
    status: str | None, file_type: str | None, creator_id: int | None, only_ids: set[int] | None,
    include_deleted: bool = False, viewer: Viewer | None = None,
) -> tuple[list[UnitItem], int]:
    base_conditions = []
    if not include_deleted:
        base_conditions.append(KnowledgeUnit.deleted_at.is_(None))
    if keyword:
        kw = f"%{keyword}%"
        base_conditions.append(or_(KnowledgeUnit.title.ilike(kw), KnowledgeUnit.unit_code.ilike(kw),
                                   KnowledgeUnit.content.ilike(kw)))
    if category:
        base_conditions.append(KnowledgeUnit.category == category)
    if status:
        base_conditions.append(KnowledgeUnit.status == status)
    if file_type:
        base_conditions.append(KnowledgeUnit.file_type == file_type)
    if creator_id:
        base_conditions.append(KnowledgeUnit.creator_id == creator_id)
    if only_ids is not None:
        base_conditions.append(KnowledgeUnit.id.in_(list(only_ids) or [-1]))
    if viewer is not None:
        # 数据权限过滤：只返回该用户有权访问的单元（默认无权限的单元不出现）
        base_conditions.append(text(ACCESSIBLE_UNITS_SQL.format(alias="knowledge_units"))
                               .bindparams(**viewer_params(viewer)))

    stmt = select(KnowledgeUnit).where(*base_conditions)
    total = (await session.execute(select(func.count()).select_from(KnowledgeUnit).where(*base_conditions))).scalar_one()
    units = list((await session.execute(
        stmt.order_by(KnowledgeUnit.created_at.desc(), KnowledgeUnit.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars())
    ids = [u.id for u in units] or [-1]
    perms = await permission_entries(session, ids)
    chunk_counts = dict((await session.execute(
        select(UnitChunk.unit_id, func.count()).where(UnitChunk.unit_id.in_(ids)).group_by(UnitChunk.unit_id)
    )).all())
    creator_ids = {u.creator_id for u in units if u.creator_id} or {-1}
    creators = dict((await session.execute(select(User.id, User.display_name).where(User.id.in_(creator_ids)))).all())
    return [_unit_item(u, perms.get(u.id, []), chunk_counts.get(u.id, 0), creators.get(u.creator_id)) for u in units], total


async def get_unit(session: AsyncSession, unit_id: int, *, include_deleted: bool = False,
                   check_access_for: int | None = None, bypass_access: bool = False) -> UnitDetail:
    unit = await session.get(KnowledgeUnit, unit_id)
    is_deleted = unit is not None and unit.deleted_at is not None
    if unit is None or (is_deleted and not include_deleted):
        raise not_found("知识单元不存在")
    if check_access_for is not None and not is_deleted and not bypass_access:
        allowed = await authorized_unit_ids(session, check_access_for, [unit.id])
        if not allowed:
            raise permission_denied("您没有该知识单元的访问权限", code="UNIT_FORBIDDEN")
    perms = (await permission_entries(session, [unit.id])).get(unit.id, [])
    chunk_count = (await session.execute(select(func.count()).where(UnitChunk.unit_id == unit.id))).scalar_one()
    creator = await session.get(User, unit.creator_id) if unit.creator_id else None
    item = _unit_item(unit, perms, chunk_count, creator.display_name if creator else None)
    return UnitDetail(**item.model_dump(), content=unit.content or "")


async def list_categories(session: AsyncSession) -> list[str]:
    rows = (await session.execute(
        select(KnowledgeUnit.category).where(KnowledgeUnit.deleted_at.is_(None),
                                            KnowledgeUnit.category.is_not(None)).distinct()
    )).scalars().all()
    return sorted([c for c in rows if c])


# ============================================================ 变更

async def create_unit(session: AsyncSession, *, title: str, content: str, summary: str | None,
                      category: str | None, tags: list[str], creator_id: int) -> KnowledgeUnit:
    unit = KnowledgeUnit(
        unit_code=await _next_unit_code(session), title=title.strip()[:255], content=content,
        summary=summary or None, category=category or None, tags=tags, file_type="txt",
        status="parsing", creator_id=creator_id,
    )
    session.add(unit)
    await session.flush()
    return await _reindex(session, unit)


async def update_unit(session: AsyncSession, unit_id: int, payload: UnitUpdate) -> KnowledgeUnit:
    unit = await session.get(KnowledgeUnit, unit_id)
    if unit is None or unit.deleted_at is not None:
        raise not_found("知识单元不存在")
    if payload.title is not None:
        unit.title = payload.title.strip()
    if "category" in payload.model_fields_set:
        unit.category = payload.category or None
    if "summary" in payload.model_fields_set:
        unit.summary = payload.summary or None
    if payload.tags is not None:
        unit.tags = payload.tags
    content_changed = payload.content is not None and payload.content != unit.content
    if payload.content is not None:
        unit.content = payload.content
    if payload.status is not None:
        unit.status = payload.status
    if content_changed:
        return await _reindex(session, unit)
    await session.flush()
    return unit


async def _reindex(session: AsyncSession, unit: KnowledgeUnit) -> KnowledgeUnit:
    """重建切片与向量。向量化期间单元置 parsing，完成后恢复 active。"""
    settings = get_settings()
    chunks = split_text(unit.content or "", max_chars=settings.chunk_max_chars)
    if not chunks:
        raise AppError("内容为空，无法建立知识单元", status_code=422)
    unit.status = "parsing"
    await session.flush()
    vectors = await embed_texts([c["content"] for c in chunks])
    await session.execute(delete(UnitChunk).where(UnitChunk.unit_id == unit.id))
    session.add_all([
        UnitChunk(unit_id=unit.id, chunk_index=i, heading=c["heading"], content=c["content"],
                  token_count=c["token_count"], embedding=v)
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ])
    unit.status = "active"
    unit.updated_at = datetime.now()
    await session.flush()
    return unit


async def delete_units(session: AsyncSession, unit_ids: list[int]) -> dict:
    """软删除；被已发布 FAQ 关联的单元拒绝删除。"""
    units = list((await session.execute(
        select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids), KnowledgeUnit.deleted_at.is_(None))
    )).scalars())
    blocked: set[int] = set((await session.execute(
        select(Faq.related_unit_id).where(Faq.related_unit_id.in_(unit_ids), Faq.status == "published")
    )).scalars().all())
    deleted = []
    for u in units:
        if u.id in blocked:
            continue
        u.deleted_at = datetime.now()
        u.status = "archived"
        deleted.append(u.id)
    await session.flush()
    return {
        "deleted_unit_ids": deleted,
        "blocked_unit_ids": sorted(i for i in blocked if i is not None),
        "not_found_unit_ids": sorted(set(unit_ids) - {u.id for u in units}),
    }


async def restore_units(session: AsyncSession, unit_ids: list[int]) -> list[int]:
    units = list((await session.execute(
        select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids), KnowledgeUnit.deleted_at.is_not(None))
    )).scalars())
    for u in units:
        u.deleted_at = None
        u.status = "active"
    await session.flush()
    return [u.id for u in units]


# ============================================================ 数据权限

async def assign_permissions(session: AsyncSession, unit_id: int,
                             targets: list[PermissionTargetIn]) -> list[PermissionEntry]:
    unit = await session.get(KnowledgeUnit, unit_id)
    if unit is None or unit.deleted_at is not None:
        raise not_found("知识单元不存在")
    model_by_type = {"department": Department, "role": Role, "user": User}
    pairs: list[tuple[str, int]] = []
    for t in targets:
        tid = 0 if t.target_type == "global" else t.target_id
        if t.target_type != "global" and await session.get(model_by_type[t.target_type], tid) is None:
            raise AppError(f"权限目标不存在: {t.target_type}#{tid}", status_code=422)
        if (t.target_type, tid) not in pairs:
            pairs.append((t.target_type, tid))

    await session.execute(delete(UnitPermission).where(UnitPermission.unit_id == unit_id))
    session.add_all([UnitPermission(unit_id=unit_id, target_type=tt, target_id=tid) for tt, tid in pairs])
    await session.flush()
    return (await permission_entries(session, [unit_id])).get(unit_id, [])


class Viewer:
    """鉴权所用到的用户身份快照；部门、角色独立传入，便于不查库做规则单测。"""

    __slots__ = ("user_id", "department_id", "role_ids")

    def __init__(self, user_id: int, department_id: int | None, role_ids: list[int]):
        self.user_id = user_id
        self.department_id = department_id
        self.role_ids = list(role_ids)

    @property
    def is_orphan(self) -> bool:
        """无部门且无角色：任何单元都无法命中（全局权限除外）。"""
        return self.department_id is None and not self.role_ids


async def load_viewer(session: AsyncSession, user_id: int) -> Viewer | None:
    user = await session.get(User, user_id)
    if user is None or user.status != "active":
        return None
    role_ids = (await session.execute(
        text("SELECT role_id FROM user_roles WHERE user_id = :uid ORDER BY role_id"), {"uid": user_id}
    )).scalars().all()
    return Viewer(user_id, user.department_id, role_ids)


# 可访问单元的 SQL 条件（作用于外层查询的 knowledge_units 别名，列名 id）
ACCESSIBLE_UNITS_SQL = """
    EXISTS (
        SELECT 1 FROM unit_permissions up
        WHERE up.unit_id = {alias}.id
          AND (
            up.target_type = 'global'
            OR (up.target_type = 'department' AND up.target_id = :dept_id)
            OR (up.target_type = 'role' AND up.target_id IN (SELECT unnest(CAST(:role_ids AS BIGINT[]))))
            OR (up.target_type = 'user' AND up.target_id = :user_id)
          )
    )
"""


def viewer_params(viewer: Viewer) -> dict:
    return {"dept_id": viewer.department_id or 0, "role_ids": list(viewer.role_ids) or [0],
            "user_id": viewer.user_id}


async def authorized_unit_ids(session: AsyncSession, user_id: int, unit_ids: list[int]) -> set[int]:
    """数据权限引擎：全局 / 部门 / 角色 / 个人 任一命中即可（OR 逻辑）。

    用户不存在或已停用时一律拒绝；单元未配置任何权限时默认不可访问。
    """
    if not unit_ids:
        return set()
    viewer = await load_viewer(session, user_id)
    if viewer is None:
        return set()
    rows = await session.execute(
        text(
            f"""
            SELECT ku.id FROM knowledge_units ku
            WHERE ku.id IN (SELECT unnest(CAST(:unit_ids AS BIGINT[])))
              AND {ACCESSIBLE_UNITS_SQL.format(alias="ku")}
            """
        ),
        {"unit_ids": list(unit_ids), **viewer_params(viewer)},
    )
    return set(rows.scalars().all())


async def accessible_unit_ids(session: AsyncSession, viewer: Viewer, *, include_disabled: bool = False,
                              require_active: bool = True) -> set[int]:
    """当前用户可访问的全部未删除单元 ID。

    require_active=True 只返回 status=active（供 AI 检索召回后过滤）；
    知识管理列表传 False，保留解析失败/停用等状态的可见性。
    """
    status_filter = "AND ku.status = 'active'" if (require_active and not include_disabled) else ""
    rows = await session.execute(
        text(
            f"""
            SELECT ku.id FROM knowledge_units ku
            WHERE ku.deleted_at IS NULL {status_filter}
              AND {ACCESSIBLE_UNITS_SQL.format(alias="ku")}
            """
        ),
        viewer_params(viewer),
    )
    return set(rows.scalars().all())
