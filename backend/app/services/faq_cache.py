"""FAQ 缓存服务（M7）。

发布 FAQ 时写入 Redis：
  - `faq:norm`             Hash：规范化问题 -> faq_id（精确命中）
  - `faq:vec`              Hash：faq_id -> 问题向量（JSON 数组），语义匹配用
  - `faq:item:{faq_id}`    String(JSON)：{question, answer, category, related_unit_id}
问答时先精确命中，未命中再做语义相似度匹配（>= FAQ_SIMILARITY_THRESHOLD）。
Redis 不可用时自动回退到数据库查询；编辑 / 下架 FAQ 时调用 invalidate 刷新缓存。
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Faq
from app.redis import get_redis
from app.services.llm import embed_query, embed_texts

log = logging.getLogger("kb.faq")

KEY_NORM = "faq:norm"
KEY_VEC = "faq:vec"
KEY_ITEM = "faq:item:{id}"


def normalize_question(text: str) -> str:
    """规范化：全角转半角、转小写、去掉空白与标点（中英文），保留文字与数字。"""
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


@dataclass
class FaqHit:
    faq_id: int
    question: str
    answer: str
    category: str | None
    related_unit_id: int | None
    score: float
    match: str  # exact | semantic


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def publish(session: AsyncSession, faq: Faq) -> None:
    """写入缓存（由审核通过 / 新建已发布 FAQ 调用）。"""
    norm = faq.question_norm or normalize_question(faq.question)
    if faq.embedding is None:
        vectors = await embed_texts([faq.question])
        faq.embedding = vectors[0]
    redis = get_redis()
    try:
        pipe = redis.pipeline()
        pipe.hset(KEY_NORM, norm, faq.id)
        pipe.hset(KEY_VEC, str(faq.id), json.dumps(faq.embedding))
        pipe.set(KEY_ITEM.format(id=faq.id), json.dumps({
            "question": faq.question, "answer": faq.answer, "category": faq.category,
            "related_unit_id": faq.related_unit_id,
        }, ensure_ascii=False))
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001 —— 缓存失败不影响发布
        log.warning("FAQ 写缓存失败：%s", exc)


async def invalidate(faq: Faq) -> None:
    redis = get_redis()
    try:
        pipe = redis.pipeline()
        pipe.hdel(KEY_NORM, faq.question_norm or normalize_question(faq.question))
        pipe.hdel(KEY_VEC, str(faq.id))
        pipe.delete(KEY_ITEM.format(id=faq.id))
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("FAQ 清缓存失败：%s", exc)


async def rebuild(session: AsyncSession) -> int:
    """全量重建缓存（发布库维护 / 服务启动可选）。"""
    faqs = list((await session.execute(select(Faq).where(Faq.status == "published"))).scalars())
    redis = get_redis()
    try:
        await redis.delete(KEY_NORM, KEY_VEC)
    except Exception as exc:  # noqa: BLE001
        log.warning("FAQ 清空缓存失败：%s", exc)
    for faq in faqs:
        await publish(session, faq)
    return len(faqs)


async def _match_from_db(session: AsyncSession, norm: str) -> Faq | None:
    return (await session.execute(
        select(Faq).where(Faq.status == "published", Faq.question_norm == norm).limit(1)
    )).scalar_one_or_none()


async def match_exact(session: AsyncSession, question: str) -> FaqHit | None:
    """只做精确匹配（规范化后完全相同）；问答主链路使用此入口，保证答案确定。"""
    norm = normalize_question(question)
    if not norm:
        return None
    try:
        faq_id = await get_redis().hget(KEY_NORM, norm)
    except Exception as exc:  # noqa: BLE001
        log.warning("FAQ 缓存读取失败，回退数据库：%s", exc)
        faq = await _match_from_db(session, norm)
        return _hit(faq, 1.0, "exact") if faq else None
    if not faq_id:
        return None
    faq = await session.get(Faq, int(faq_id))
    if faq and faq.status == "published":
        return _hit(faq, 1.0, "exact")
    if faq:
        await invalidate(faq)
    return None


async def match(session: AsyncSession, question: str) -> FaqHit | None:
    """匹配已发布 FAQ：先精确（规范化后完全相同），再语义（向量相似度 ≥ 阈值）。

    语义匹配供管理端预览 / 扩展使用；AI 问答主链路只使用 match_exact，避免近似问题命中不相关答案。
    """
    settings = get_settings()
    norm = normalize_question(question)
    if not norm:
        return None
    redis: Redis = get_redis()
    exact_id: str | None = None
    candidates: dict[str, str] = {}
    try:
        exact_id = await redis.hget(KEY_NORM, norm)
        if not exact_id:
            candidates = await redis.hgetall(KEY_VEC)
    except Exception as exc:  # noqa: BLE001 —— Redis 不可用走数据库
        log.warning("FAQ 缓存读取失败，回退数据库：%s", exc)
        faq = await _match_from_db(session, norm)
        return _hit(faq, 1.0, "exact") if faq else None

    if exact_id:
        faq = await session.get(Faq, int(exact_id))
        if faq and faq.status == "published":
            return _hit(faq, 1.0, "exact")
        if faq:
            await invalidate(faq)

    if not candidates:
        return None
    vec = await embed_query(question)
    best_id, best_score = None, 0.0
    for fid, raw in candidates.items():
        try:
            score = _cosine(vec, json.loads(raw))
        except (TypeError, ValueError):
            continue
        if score > best_score:
            best_id, best_score = fid, score
    if best_id and best_score >= settings.faq_similarity_threshold:
        faq = await session.get(Faq, int(best_id))
        if faq and faq.status == "published":
            return _hit(faq, round(best_score, 4), "semantic")
        if faq:
            await invalidate(faq)
    return None


def _hit(faq: Faq, score: float, match: str) -> FaqHit:
    return FaqHit(faq_id=faq.id, question=faq.question, answer=faq.answer, category=faq.category,
                  related_unit_id=faq.related_unit_id, score=score, match=match)


async def stats() -> dict:
    redis = get_redis()
    try:
        return {"cached": int(await redis.hlen(KEY_VEC)), "exact_keys": int(await redis.hlen(KEY_NORM)),
                "redis": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"cached": 0, "exact_keys": 0, "redis": f"error: {exc}"}
