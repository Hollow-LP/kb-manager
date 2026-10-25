from fastapi import APIRouter, Depends, Query

from app.deps import CurrentUserDep, SessionDep, require_permission
from app.schemas.common import Page
from app.schemas.settlement import (
    FaqCreateRequest,
    FaqItem,
    FaqReviewRequest,
    FaqUpdateRequest,
    GapItem,
    GapResolveRequest,
    MiningResult,
)
from app.services import mining
from app.services import settlement as svc
from app.tasks import scheduler

router = APIRouter(prefix="/settlement", tags=["知识沉淀"])


# --------------------------------------------------------------------------- FAQ

@router.get("/faqs", response_model=Page[FaqItem], summary="FAQ 列表（按状态 / 关键字）",
            dependencies=[Depends(require_permission("settlement:faq:view")),
                          Depends(require_permission("settlement:faq:manage"))])
async def list_faqs(session: SessionDep, status: str | None = None, keyword: str | None = None,
                    source_type: str | None = Query(None, pattern="^(manual|auto_mined)$"),
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> Page[FaqItem]:
    items, total = await svc.list_faqs(session, status=status, keyword=keyword, page=page, page_size=page_size,
                                       source_type=source_type)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/faqs/recommendations", response_model=Page[FaqItem], summary="自动推荐的待审核 FAQ",
            dependencies=[Depends(require_permission("settlement:faq:view"))])
async def recommendations(session: SessionDep, page: int = Query(1, ge=1),
                          page_size: int = Query(20, ge=1, le=100)) -> Page[FaqItem]:
    items, total = await svc.recommendations(session, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/faqs/cache-stats", summary="FAQ 缓存状态",
            dependencies=[Depends(require_permission("settlement:faq:manage"))])
async def cache_stats() -> dict:
    return await svc.faq_cache_stats()


@router.post("/faqs", response_model=FaqItem, summary="手工新建 FAQ（可直接发布）",
             dependencies=[Depends(require_permission("settlement:faq:manage"))])
async def create_faq(payload: FaqCreateRequest, session: SessionDep, current: CurrentUserDep) -> FaqItem:
    faq = await svc.create_faq(session, question=payload.question, answer=payload.answer,
                               category=payload.category, related_unit_id=payload.related_unit_id,
                               publish=payload.publish, creator_id=current.id)
    await session.commit()
    return await _faq_item_by_id(session, faq.id)


@router.put("/faqs/{faq_id}", response_model=FaqItem, summary="编辑 FAQ（已发布的会同步刷新缓存）",
            dependencies=[Depends(require_permission("settlement:faq:manage"))])
async def update_faq(faq_id: int, payload: FaqUpdateRequest, session: SessionDep) -> FaqItem:
    await svc.update_faq(session, faq_id, question=payload.question, answer=payload.answer,
                         category=payload.category)
    await session.commit()
    return await _faq_item_by_id(session, faq_id)


@router.post("/faqs/{faq_id}/review", response_model=FaqItem, summary="审核：approve（发布并写缓存）/ reject",
             dependencies=[Depends(require_permission("settlement:faq:review"))])
async def review_faq(faq_id: int, payload: FaqReviewRequest, session: SessionDep,
                     current: CurrentUserDep) -> FaqItem:
    await svc.review(session, faq_id, action=payload.action, edited_answer=payload.edited_answer,
                     note=payload.note, reviewer_id=current.id)
    await session.commit()
    return await _faq_item_by_id(session, faq_id)


@router.post("/faqs/{faq_id}/unpublish", response_model=FaqItem, summary="下架已发布 FAQ（移出缓存）",
             dependencies=[Depends(require_permission("settlement:faq:manage"))])
async def unpublish_faq(faq_id: int, session: SessionDep) -> FaqItem:
    await svc.unpublish(session, faq_id)
    await session.commit()
    return await _faq_item_by_id(session, faq_id)


async def _faq_item_by_id(session, faq_id: int) -> FaqItem:
    """按 ID 重新查询单条 FAQ。

    注意：commit 后对象属性可能已过期，直接读取会触发同步 IO（MissingGreenlet），
    因此这里先 expire 再按主键重新加载。
    """
    from app.models import Faq

    session.expire_all()
    faq = await session.get(Faq, faq_id)
    if faq is None:
        from app.core.exceptions import not_found

        raise not_found("FAQ 不存在")
    return FaqItem(**await svc.faq_dict(session, faq))


# --------------------------------------------------------------------------- 知识缺口

@router.get("/knowledge-gaps", response_model=Page[GapItem], summary="知识缺口列表（按频次）",
            dependencies=[Depends(require_permission("settlement:gap:view"))])
async def list_gaps(session: SessionDep, status: str | None = Query("unresolved"), keyword: str | None = None,
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> Page[GapItem]:
    items, total = await svc.list_gaps(session, status=status or None, keyword=keyword, page=page,
                                       page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.put("/knowledge-gaps/{gap_id}", summary="更新缺口状态（resolved / ignored / unresolved）",
            dependencies=[Depends(require_permission("settlement:gap:handle"))])
async def set_gap_status(gap_id: int, status: str, session: SessionDep) -> dict:
    gap = await svc.set_gap_status(session, gap_id, status)
    await session.commit()
    return {"id": gap.id, "status": gap.status}


@router.post("/knowledge-gaps/{gap_id}/create-unit", summary="一键建档：按缺口新建知识单元",
             dependencies=[Depends(require_permission("settlement:gap:handle"))])
async def create_unit_from_gap(gap_id: int, payload: GapResolveRequest, session: SessionDep,
                               current: CurrentUserDep) -> dict:
    result = await svc.resolve_gap_with_unit(session, gap_id, title=payload.title, content=payload.content,
                                             category=payload.category, creator_id=current.id)
    await session.commit()
    return result


# --------------------------------------------------------------------------- 挖掘任务

@router.post("/mining/run", response_model=MiningResult, summary="立即执行高频问题挖掘与缺口识别",
             dependencies=[Depends(require_permission("settlement:faq:review"))])
async def run_mining(days: int | None = Query(None, ge=1, le=365)) -> MiningResult:
    from app.schemas.settlement import MiningResult as Model

    result = await mining.run_all(days=days)
    return Model(**result)


@router.get("/mining/status", summary="挖掘定时任务状态",
            dependencies=[Depends(require_permission("settlement:faq:view"))])
async def mining_status() -> dict:
    return scheduler.status()
