"""知识沉淀服务：FAQ 查询 / 审核发布 / 维护，知识缺口查询与处理。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, not_found
from app.models import Faq, KnowledgeGap, KnowledgeUnit
from app.services import faq_cache
from app.services import knowledge as kb
from app.services.faq_cache import normalize_question

FAQ_STATUSES = ("pending_review", "published", "rejected")


def _faq_item(faq: Faq, unit_title: str | None, cached: bool) -> dict:
    return {
        "id": faq.id, "question": faq.question, "answer": faq.answer, "category": faq.category,
        "related_unit_id": faq.related_unit_id, "related_unit_title": unit_title,
        "source_type": faq.source_type, "status": faq.status, "answer_edited": faq.answer_edited,
        "hit_count": faq.hit_count, "review_note": faq.review_note, "reviewer_id": faq.reviewer_id,
        "reviewed_at": faq.reviewed_at, "published_at": faq.published_at, "cached": cached,
        "created_at": faq.created_at, "updated_at": faq.updated_at,
    }


async def list_faqs(session: AsyncSession, *, status: str | None, keyword: str | None, page: int,
                    page_size: int, source_type: str | None = None) -> tuple[list[dict], int]:
    conditions = []
    if status:
        if status not in FAQ_STATUSES:
            raise AppError("status 取值不合法", status_code=422)
        conditions.append(Faq.status == status)
    if source_type:
        conditions.append(Faq.source_type == source_type)
    if keyword:
        kw = f"%{keyword}%"
        conditions.append(or_(Faq.question.ilike(kw), Faq.answer.ilike(kw)))
    total = (await session.execute(select(func.count()).select_from(Faq).where(*conditions))).scalar_one()
    faqs = list((await session.execute(
        select(Faq).where(*conditions).order_by(Faq.updated_at.desc(), Faq.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars())
    unit_ids = {f.related_unit_id for f in faqs if f.related_unit_id} or {-1}
    titles = dict((await session.execute(select(KnowledgeUnit.id, KnowledgeUnit.title).where(
        KnowledgeUnit.id.in_(unit_ids)))).all())
    cached_ids = await _cached_ids(faqs)
    return [_faq_item(f, titles.get(f.related_unit_id), f.id in cached_ids) for f in faqs], total


async def _cached_ids(faqs: list[Faq]) -> set[int]:
    """读取缓存状态：faq:item:{id} 存在即视为已缓存。"""
    from app.redis import get_redis

    ids = [f.id for f in faqs if f.status == "published"]
    if not ids:
        return set()
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        for fid in ids:
            pipe.exists(faq_cache.KEY_ITEM.format(id=fid))
        flags = await pipe.execute()
        return {fid for fid, ok in zip(ids, flags) if ok}
    except Exception:  # noqa: BLE001
        return set()


async def recommendations(session: AsyncSession, page: int, page_size: int) -> tuple[list[dict], int]:
    return await list_faqs(session, status="pending_review", keyword=None, page=page, page_size=page_size)


async def get_faq(session: AsyncSession, faq_id: int) -> Faq:
    faq = await session.get(Faq, faq_id)
    if faq is None:
        raise not_found("FAQ 不存在")
    return faq


async def faq_dict(session: AsyncSession, faq: Faq) -> dict:
    """单条 FAQ 的展示结构（含关联单元标题与缓存状态）。"""
    title = None
    if faq.related_unit_id:
        title = (await session.execute(select(KnowledgeUnit.title).where(
            KnowledgeUnit.id == faq.related_unit_id))).scalar_one_or_none()
    cached = faq.id in await _cached_ids([faq])
    return _faq_item(faq, title, cached)


async def review(session: AsyncSession, faq_id: int, *, action: str, edited_answer: str | None,
                 note: str | None, reviewer_id: int) -> Faq:
    faq = await get_faq(session, faq_id)
    if faq.status == "published" and action == "approve":
        raise AppError("该 FAQ 已发布", status_code=400)
    if action == "approve":
        if edited_answer and edited_answer.strip() and edited_answer.strip() != faq.answer:
            faq.answer = edited_answer.strip()
            faq.answer_edited = True
        faq.question_norm = normalize_question(faq.question)
        faq.status = "published"
        faq.published_by = reviewer_id
        faq.published_at = datetime.now()
        faq.reviewer_id = reviewer_id
        faq.reviewed_at = datetime.now()
        if note:
            faq.review_note = note
        await session.flush()
        await faq_cache.publish(session, faq)     # 写入缓存，后续命中直接返回
    else:
        faq.status = "rejected"
        faq.reviewer_id = reviewer_id
        faq.reviewed_at = datetime.now()
        if note:
            faq.review_note = note
        await faq_cache.invalidate(faq)
    await session.flush()
    return faq


async def create_faq(session: AsyncSession, *, question: str, answer: str, category: str | None,
                     related_unit_id: int | None, publish: bool, creator_id: int) -> Faq:
    norm = normalize_question(question)
    exists = (await session.execute(select(Faq.id).where(
        Faq.question_norm == norm, Faq.status == "published"))).scalar_one_or_none()
    if exists:
        raise AppError("已存在相同的已发布 FAQ", status_code=400)
    if related_unit_id is not None and await session.get(KnowledgeUnit, related_unit_id) is None:
        raise not_found("关联知识单元不存在")
    faq = Faq(question=question.strip(), question_norm=norm, answer=answer.strip(), category=category,
              related_unit_id=related_unit_id, source_type="manual",
              status="published" if publish else "pending_review")
    if publish:
        faq.published_by = creator_id
        faq.published_at = datetime.now()
        faq.reviewer_id = creator_id
        faq.reviewed_at = datetime.now()
    session.add(faq)
    await session.flush()
    if publish:
        await faq_cache.publish(session, faq)
    return faq


async def update_faq(session: AsyncSession, faq_id: int, *, question: str | None, answer: str | None,
                     category: str | None) -> Faq:
    faq = await get_faq(session, faq_id)
    if question is not None and question.strip() != faq.question:
        await faq_cache.invalidate(faq)
        faq.question = question.strip()
        faq.question_norm = normalize_question(faq.question)
        faq.embedding = None          # 问题变了，向量需重建
    if answer is not None:
        faq.answer = answer.strip()
    if category is not None:
        faq.category = category or None
    await session.flush()
    if faq.status == "published":
        await faq_cache.publish(session, faq)
    return faq


async def unpublish(session: AsyncSession, faq_id: int) -> Faq:
    faq = await get_faq(session, faq_id)
    faq.status = "rejected"
    faq.review_note = (faq.review_note or "") + " [已下架]"
    await faq_cache.invalidate(faq)
    await session.flush()
    return faq


async def faq_cache_stats() -> dict:
    return await faq_cache.stats()


# --------------------------------------------------------------------------- 知识缺口

async def list_gaps(session: AsyncSession, *, status: str | None, keyword: str | None, page: int,
                    page_size: int) -> tuple[list[dict], int]:
    conditions = []
    if status:
        if status not in ("unresolved", "resolved", "ignored"):
            raise AppError("status 取值不合法", status_code=422)
        conditions.append(KnowledgeGap.status == status)
    if keyword:
        conditions.append(KnowledgeGap.question_pattern.ilike(f"%{keyword}%"))
    total = (await session.execute(select(func.count()).select_from(KnowledgeGap).where(*conditions))).scalar_one()
    rows = list((await session.execute(
        select(KnowledgeGap).where(*conditions)
        .order_by(KnowledgeGap.ask_count.desc(), KnowledgeGap.last_asked_at.desc().nulls_last())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars())
    return [{
        "id": g.id, "question_pattern": g.question_pattern, "sample_questions": g.sample_questions_json or [],
        "ask_count": g.ask_count, "last_asked_at": g.last_asked_at, "status": g.status,
        "resolved_unit_id": g.resolved_unit_id, "created_at": g.created_at, "updated_at": g.updated_at,
    } for g in rows], total


async def set_gap_status(session: AsyncSession, gap_id: int, status: str) -> KnowledgeGap:
    if status not in ("unresolved", "resolved", "ignored"):
        raise AppError("status 取值不合法", status_code=422)
    gap = await session.get(KnowledgeGap, gap_id)
    if gap is None:
        raise not_found("知识缺口不存在")
    gap.status = status
    await session.flush()
    return gap


async def resolve_gap_with_unit(session: AsyncSession, gap_id: int, *, title: str, content: str,
                                category: str | None, creator_id: int) -> dict:
    """一键建档：按缺口问题新建知识单元，并把缺口标记为已解决。"""
    gap = await session.get(KnowledgeGap, gap_id)
    if gap is None:
        raise not_found("知识缺口不存在")
    unit = await kb.create_unit(session, title=title, content=content, summary=None,
                                category=category or "知识补全", tags=["知识缺口补全"], creator_id=creator_id)
    gap.status = "resolved"
    gap.resolved_unit_id = unit.id
    await session.flush()
    return {"gap_id": gap.id, "unit_id": unit.id, "unit_code": unit.unit_code, "title": unit.title}


__all__ = [
    "list_faqs", "recommendations", "get_faq", "review", "create_faq", "update_faq", "unpublish",
    "faq_cache_stats", "list_gaps", "set_gap_status", "resolve_gap_with_unit",
]
