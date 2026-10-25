from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.deps import CurrentUserDep, SessionDep, require_permission
from app.services import dashboard as dash

router = APIRouter(prefix="/dashboard", tags=["数据看板"])

_days = Query(30, ge=1, le=365, description="统计最近 N 天（含今天）")
_gran = Query("day", pattern="^(day|week)$", description="趋势粒度")


@router.get("/metrics", summary="核心指标：访问次数、UV、单元数、Token、平均耗时",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def metrics(session: SessionDep, days: int = _days) -> dict:
    return await dash.metrics(session, days)


@router.get("/rankings/questions", summary="常见问题 TOP",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def question_ranking(session: SessionDep, days: int = _days,
                           top: int = Query(10, ge=1, le=50)) -> list[dict]:
    return await dash.question_ranking(session, days, top)


@router.get("/rankings/units", summary="最常访问知识单元 TOP",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def unit_ranking(session: SessionDep, days: int = _days,
                       top: int = Query(10, ge=1, le=50)) -> list[dict]:
    return await dash.unit_ranking(session, days, top)


@router.get("/stats/trend", summary="访问趋势（按日/周）",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def trend(session: SessionDep, days: int = _days,
                granularity: Literal["day", "week"] = _gran) -> list[dict]:
    return await dash.trend(session, days, granularity)


@router.get("/stats/tokens", summary="Token 消耗趋势",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def tokens(session: SessionDep, days: int = _days,
                 granularity: Literal["day", "week"] = _gran) -> list[dict]:
    return await dash.token_stats(session, days, granularity)


@router.get("/stats/response-time", summary="响应时间分布与分位数",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def response_time(session: SessionDep, days: int = _days) -> dict:
    return await dash.response_time_stats(session, days)


@router.get("/stats/heatmap", summary="访问时段热力（星期×小时）",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def heatmap(session: SessionDep, days: int = _days) -> list[dict]:
    return await dash.token_heatmap(session, days)


@router.get("/overview", summary="看板一次性聚合（指标 + 榜单 + 趋势 + Token + 响应时间）",
            dependencies=[Depends(require_permission("dashboard:view"))])
async def overview(session: SessionDep, current: CurrentUserDep, days: int = _days,
                   granularity: Literal["day", "week"] = _gran) -> dict:
    data = await dash.overview(session, days, granularity)
    data["scope_days"] = days
    return data
