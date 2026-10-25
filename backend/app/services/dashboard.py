"""M6：数据看板统计服务。

数据来源：`qa_access_logs`（每次问答追加一条）。
所有接口支持 `days`（默认 30，1~365）与 `granularity=day|week`（趋势类）。
时间统一按 Asia/Shanghai 自然日切分。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


TZ = ZoneInfo("Asia/Shanghai")


def _window(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(TZ)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _params(days: int) -> dict:
    start, end = _window(days)
    return {"start": start, "end": end, "tz": str(TZ)}


async def metrics(session: AsyncSession, days: int) -> dict:
    p = _params(days)
    row = (await session.execute(text("""
        SELECT count(*)                                    AS total_visits,
               count(DISTINCT user_id)                     AS unique_visitors,
               COALESCE(sum(total_tokens), 0)              AS total_tokens,
               COALESCE(round(avg(response_time_ms)), 0)   AS avg_response_ms,
               COALESCE(sum(CASE WHEN faq_hit THEN 1 ELSE 0 END), 0) AS faq_hits,
               COALESCE(sum(CASE WHEN gap_flag THEN 1 ELSE 0 END), 0) AS gaps
        FROM qa_access_logs
        WHERE created_at >= :start AND created_at < :end
    """), p)).mappings().one()
    units = (await session.execute(text(
        "SELECT count(*) FROM knowledge_units WHERE deleted_at IS NULL AND status = 'active'"
    ))).scalar_one()
    total_visits = int(row["total_visits"])
    return {
        "days": days,
        "total_visits": total_visits,
        "unique_visitors": int(row["unique_visitors"]),
        "total_units": int(units),
        "total_tokens": int(row["total_tokens"]),
        "avg_response_ms": int(row["avg_response_ms"]),
        "faq_hits": int(row["faq_hits"]),
        "gap_questions": int(row["gaps"]),
        "faq_hit_rate": round(row["faq_hits"] / total_visits, 4) if total_visits else 0.0,
    }


async def question_ranking(session: AsyncSession, days: int, top: int) -> list[dict]:
    """常见问题 TOP：先按规范化文本（去空白、去标点）聚合，再取每组代表问题。"""
    p = {**_params(days), "top": top}
    rows = (await session.execute(text("""
        WITH normed AS (
            SELECT regexp_replace(question, '[\\s，。！？、；：,.!?;:]+', '', 'g') AS q,
                   question, total_tokens, response_time_ms, created_at
            FROM qa_access_logs
            WHERE created_at >= :start AND created_at < :end
        )
        SELECT q, count(*) AS ask_count, count(DISTINCT question) AS variant_count,
               (array_agg(question ORDER BY created_at DESC))[1] AS sample_question,
               round(avg(total_tokens)) AS avg_tokens
        FROM normed GROUP BY q ORDER BY ask_count DESC, avg_tokens DESC
        LIMIT :top
    """), p)).mappings().all()
    return [{"question": r["sample_question"], "ask_count": int(r["ask_count"]),
             "variant_count": int(r["variant_count"]), "avg_tokens": int(r["avg_tokens"] or 0)} for r in rows]


async def unit_ranking(session: AsyncSession, days: int, top: int) -> list[dict]:
    """最常访问知识单元 TOP：统计每次问答"实际用于回答"的授权单元（authorized_unit_ids_json），
    同时给出召回次数（recalled）与因权限被拦截的次数（recalled 但未授权），供管理员判断哪些单元需要开放权限。"""
    p = {**_params(days), "top": top}
    recalled = {r["unit_id"]: dict(r) for r in (await session.execute(text("""
        SELECT rid.unit_id::bigint AS unit_id, count(*) AS recalled
        FROM qa_access_logs l
        CROSS JOIN LATERAL (SELECT jsonb_array_elements_text(l.recalled_unit_ids_json) AS unit_id) rid
        WHERE l.created_at >= :start AND l.created_at < :end
        GROUP BY 1
    """), p)).mappings().all()}
    authorized = {r["unit_id"]: int(r["hits"]) for r in (await session.execute(text("""
        SELECT aid.unit_id::bigint AS unit_id, count(*) AS hits
        FROM qa_access_logs l
        CROSS JOIN LATERAL (SELECT jsonb_array_elements_text(l.authorized_unit_ids_json) AS unit_id) aid
        WHERE l.created_at >= :start AND l.created_at < :end
        GROUP BY 1
    """), p)).mappings().all()}
    unit_ids = list(authorized)
    if not unit_ids:
        unit_ids = list(recalled)
    meta_rows = (await session.execute(text(
        "SELECT id, unit_code, title, category FROM knowledge_units "
        "WHERE id IN (SELECT unnest(CAST(:ids AS BIGINT[])))"
    ), {"ids": unit_ids or [0]})).all()
    meta = {r[0]: {"unit_code": r[1], "title": r[2], "category": r[3]} for r in meta_rows}
    rows = []
    for uid in unit_ids:
        m = meta.get(uid)
        if not m:
            continue
        hits = authorized.get(uid, 0)
        rows.append({"unit_id": uid, **m, "hit_count": hits, "recalled_count": int(recalled.get(uid, {}).get("recalled", hits)),
                     "denied_count": max(int(recalled.get(uid, {}).get("recalled", hits)) - hits, 0)})
    rows.sort(key=lambda r: (-r["hit_count"], -r["recalled_count"]))
    return rows[:top]


def _bucket(granularity: str) -> str:
    return "week" if granularity == "week" else "day"


async def trend(session: AsyncSession, days: int, granularity: str) -> list[dict]:
    """按日/周的访问趋势：次数、独立人数、Token、平均耗时、FAQ 命中。"""
    bucket = _bucket(granularity)
    rows = (await session.execute(text(f"""
        SELECT to_char(date_trunc('{bucket}', created_at AT TIME ZONE :tz), 'YYYY-MM-DD') AS bucket,
               count(*) AS visits, count(DISTINCT user_id) AS uv,
               COALESCE(sum(total_tokens), 0) AS tokens,
               COALESCE(round(avg(response_time_ms)), 0) AS avg_ms,
               COALESCE(sum(CASE WHEN faq_hit THEN 1 ELSE 0 END), 0) AS faq_hits
        FROM qa_access_logs
        WHERE created_at >= :start AND created_at < :end
        GROUP BY 1 ORDER BY 1
    """), _params(days))).mappings().all()
    series = [
        {"bucket": r["bucket"], "visits": int(r["visits"]), "uv": int(r["uv"]), "tokens": int(r["tokens"]),
         "avg_response_ms": int(r["avg_ms"]), "faq_hits": int(r["faq_hits"])}
        for r in rows
    ]
    return _fill_gaps(series, days, bucket)


def _fill_buckets(by_key: dict, days: int, bucket: str, empty: dict) -> list[dict]:
    """按时间顺序补齐缺失的桶（只补 bucket + empty 字段）。

    注意：空值必须按"本次请求需要"当场复制，不能在函数定义/default 参数里复用可变对象，
    否则不同请求（或 trend/token 两个接口）之间会互相污染。
    """
    out = []
    start, end = _window(days)
    cursor = start.date()
    seen: set[str] = set()
    while cursor <= end.date():
        if bucket == "week":
            cursor = cursor - timedelta(days=cursor.weekday())
        key = cursor.isoformat()
        if key not in seen:
            seen.add(key)
            out.append(by_key.get(key) or {"bucket": key, **empty})
        cursor += timedelta(days=7 if bucket == "week" else 1)
    return out


def _fill_gaps(series: list[dict], days: int, bucket: str) -> list[dict]:
    """补齐没有数据的时间桶，方便前端画连续折线。"""
    if not series:
        return []
    by_key = {s["bucket"]: s for s in series}
    out = []
    start, end = _window(days)
    cursor = start.date()
    seen = set()
    while cursor <= end.date():
        if bucket == "week":
            cursor = cursor - timedelta(days=cursor.weekday())
        key = cursor.isoformat()
        if key in seen:
            cursor += timedelta(days=7 if bucket == "week" else 1)
            continue
        seen.add(key)
        out.append(by_key.get(key, {"bucket": key, "visits": 0, "uv": 0, "tokens": 0, "avg_response_ms": 0, "faq_hits": 0}))
        cursor += timedelta(days=7 if bucket == "week" else 1)
    return out


async def token_stats(session: AsyncSession, days: int, granularity: str) -> list[dict]:
    """Token 消耗趋势：按日/周拆分 prompt / completion。

    注意：不能复用 trend() 的补洞结果（其字段是 tokens，直接合并会覆盖本接口的 total_tokens）。
    """
    bucket = _bucket(granularity)
    rows = (await session.execute(text(f"""
        SELECT to_char(date_trunc('{bucket}', created_at AT TIME ZONE :tz), 'YYYY-MM-DD') AS bucket,
               COALESCE(sum(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(sum(completion_tokens), 0) AS completion_tokens,
               COALESCE(sum(total_tokens), 0) AS total_tokens,
               count(*) AS visits
        FROM qa_access_logs WHERE created_at >= :start AND created_at < :end
        GROUP BY 1 ORDER BY 1
    """), _params(days))).mappings().all()
    by_key = {r["bucket"]: {"bucket": r["bucket"], "prompt_tokens": int(r["prompt_tokens"]),
                            "completion_tokens": int(r["completion_tokens"]),
                            "total_tokens": int(r["total_tokens"]), "visits": int(r["visits"])} for r in rows}
    empty = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "visits": 0}
    return _fill_buckets(by_key, days, bucket, dict(empty))


async def response_time_stats(session: AsyncSession, days: int) -> dict:
    """响应时间分布（直方图）+ 分位数。buckets 为 [下界, 上界)。"""
    edges = [0, 500, 1000, 2000, 3000, 5000, 8000, 15000, 10**9]
    labels = ["<0.5s", "0.5-1s", "1-2s", "2-3s", "3-5s", "5-8s", "8-15s", "≥15s"]
    p = _params(days)
    buckets = [0] * len(labels)
    rows = (await session.execute(text("""
        SELECT response_time_ms FROM qa_access_logs
        WHERE created_at >= :start AND created_at < :end
    """), p)).scalars().all()
    for ms in rows:
        for i in range(len(edges) - 1):
            if edges[i] <= ms < edges[i + 1]:
                buckets[i] += 1
                break
    pct = (await session.execute(text("""
        SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY response_time_ms), 0) AS p50,
               COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY response_time_ms), 0) AS p95,
               COALESCE(round(avg(response_time_ms)), 0) AS avg
        FROM qa_access_logs WHERE created_at >= :start AND created_at < :end
    """), p)).mappings().one()
    return {
        "labels": labels,
        "counts": buckets,
        "p50": int(pct["p50"]),
        "p95": int(pct["p95"]),
        "avg": int(pct["avg"]),
        "samples": len(rows),
    }


async def token_heatmap(session: AsyncSession, days: int) -> list[dict]:
    """按 星期×小时 的访问热力（额外辅助图表）。"""
    rows = (await session.execute(text("""
        SELECT extract(dow FROM created_at AT TIME ZONE :tz)::int AS dow,
               extract(hour FROM created_at AT TIME ZONE :tz)::int AS hour,
               count(*) AS visits
        FROM qa_access_logs WHERE created_at >= :start AND created_at < :end
        GROUP BY 1, 2
    """), _params(days))).mappings().all()
    return [dict(r) for r in rows]


async def overview(session: AsyncSession, days: int, granularity: str) -> dict:
    """看板一次性加载：指标 + 两个榜单 + 趋势 + Token + 响应时间。"""
    return {
        "metrics": await metrics(session, days),
        "questions": await question_ranking(session, days, 10),
        "units": await unit_ranking(session, days, 10),
        "trend": await trend(session, days, granularity),
        "tokens": await token_stats(session, days, granularity),
        "response_time": await response_time_stats(session, days),
    }


__all__ = ["metrics", "question_ranking", "unit_ranking", "trend", "token_stats", "response_time_stats",
           "token_heatmap", "overview"]
