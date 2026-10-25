"""知识沉淀挖掘服务（M7）。

- 高频问题挖掘：扫描近 N 天访问日志（已授权且有资料的问答），按问题向量聚类（相似度 ≥ FAQ_MINE_SIMILARITY），
  频次 ≥ FAQ_MINE_THRESHOLD 时生成/更新 `pending_review` 候选 FAQ，建议答案取该问题最近一次回答。
- 知识缺口识别：`gap_flag=true` 的提问按向量聚类归并到 `knowledge_gaps`，累加频次与样例问题。
两类任务都可用定时器触发（MINING_CRON，默认每日 02:00），也可通过接口手动触发。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import Faq, KnowledgeGap, QaAccessLog
from app.services.faq_cache import normalize_question
from app.services.llm import embed_texts
from sqlalchemy import text

log = logging.getLogger("kb.mining")

MAX_ANSWER_CHARS = 1500


UNKNOWN_MARKERS = ("未找到", "暂无", "没有", "未检索", "无法得知", "无法回答", "不含", "未提及", "未涉及", "无法依据",
                   "无权访问", "暂无访问权限", "没有访问权限")


def _is_unknown_answer(answer: str) -> bool:
    """识别"知识库中未找到相关信息 / 暂无访问权限"这一类回答；这类问题应作为知识缺口而不是 FAQ。"""
    head = answer[:200]
    return any(marker in head for marker in UNKNOWN_MARKERS)


def _cosine(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _cluster(items: list[dict], vectors: list[list[float]], threshold: float) -> list[list[int]]:
    """贪心聚类：按频次从高到低，归入第一个代表问题相似度达标的簇。"""
    order = sorted(range(len(items)), key=lambda i: -items[i]["count"])
    clusters: list[list[int]] = []
    reps: list[list[float]] = []
    for idx in order:
        vec = vectors[idx]
        placed = False
        for ci, rep in enumerate(reps):
            if _cosine(vec, rep) >= threshold:
                clusters[ci].append(idx)
                placed = True
                break
        if not placed:
            clusters.append([idx])
            reps.append(vec)
    return clusters


def _representative(items: list[dict], group: list[int], vectors: list[list[float]]) -> int:
    """簇代表：频次最高且离簇质心最近的一条（用简单平均近似）。"""
    if len(group) == 1:
        return group[0]
    dim = len(vectors[group[0]])
    centroid = [sum(vectors[i][d] for i in group) / len(group) for d in range(dim)]
    return max(group, key=lambda i: (items[i]["count"], _cosine(vectors[i], centroid)))


async def mine_faqs(session: AsyncSession, *, days: int | None = None,
                    threshold: int | None = None) -> dict:
    settings = get_settings()
    days = days or settings.faq_mine_lookback_days
    threshold = threshold or settings.faq_mine_threshold
    since = datetime.now() - timedelta(days=days)

    rows = (await session.execute(
        select(QaAccessLog.question, QaAccessLog.question_norm, QaAccessLog.answer, QaAccessLog.created_at,
               QaAccessLog.authorized_unit_ids_json, QaAccessLog.faq_hit)
        .where(QaAccessLog.created_at >= since, QaAccessLog.gap_flag.is_(False))
        .order_by(QaAccessLog.created_at)
    )).all()

    # 按规范化问题聚合（同义变体靠向量聚类并入）
    groups: dict[str, dict] = {}
    for question, norm, answer, created_at, authorized, faq_hit in rows:
        if not question or faq_hit:
            continue  # 已由 FAQ 缓存回答的不再推荐
        # 库外问题（回答仅为"未找到"）归知识缺口，不进入 FAQ 推荐——模型并没有可沉淀的标准答案；
        # 无授权资料的提问同样不推荐（回答只是"无权限"提示，不是知识内容）
        if _is_unknown_answer(answer or "") or not (authorized or []):
            continue
        key = norm or normalize_question(question)
        if not key:
            continue
        g = groups.setdefault(key, {"question": question, "count": 0, "variants": set(), "answer": "",
                                    "last": created_at, "units": [], "samples": []})
        g["count"] += 1
        g["variants"].add(question)
        if created_at and (g["last"] is None or created_at > g["last"]):
            g["last"] = created_at
            if answer:
                g["answer"] = answer
        g["units"] = list(set(g["units"]) | set(authorized or []))
        if len(g["samples"]) < 5 and question not in g["samples"]:
            g["samples"].append(question)

    items = [g for g in groups.values() if g["count"] >= threshold]
    if not items:
        return {"clusters": 0, "created": 0, "updated": 0, "considered": len(groups)}

    vectors = await embed_texts([g["question"] for g in items])
    clusters = _cluster(items, vectors, settings.faq_mine_similarity)

    published_norms = set((await session.execute(
        select(Faq.question_norm).where(Faq.status.in_(("published", "pending_review")))
    )).scalars())
    published = list((await session.execute(select(Faq).where(Faq.status == "published"))).scalars())

    created = updated = 0
    for group in clusters:
        # 簇内的所有变体合并频次
        total = sum(items[i]["count"] for i in group)
        if total < threshold:
            continue
        rep = _representative(items, group, vectors)
        question = items[rep]["question"]
        # 与已发布/待审 FAQ 语义重复则跳过
        dup = False
        for f in published:
            if f.embedding and _cosine(vectors[rep], f.embedding) >= settings.faq_mine_similarity:
                dup = True
                break
        if dup:
            continue
        norm = normalize_question(question)
        if norm in published_norms:
            continue
        answer = max((items[i]["answer"] for i in group if items[i]["answer"]), key=len, default="")
        if not answer:
            continue
        units = [u for i in group for u in items[i]["units"]]
        related_unit = max(set(units), key=units.count) if units else None
        existing = (await session.execute(
            select(Faq).where(Faq.question_norm == norm, Faq.status == "pending_review")
        )).scalar_one_or_none()
        samples = [s for i in group for s in items[i]["samples"]][:8]
        if existing:
            existing.answer = answer[:MAX_ANSWER_CHARS]
            existing.embedding = vectors[rep]
            existing.hit_count = total
            existing.mine_group_key = f"mine:{norm[:60]}"
            existing.related_unit_id = related_unit
            existing.review_note = f"变体示例：{' / '.join(samples[:4])}"
            updated += 1
        else:
            session.add(Faq(
                question=question[:500], question_norm=norm, answer=answer[:MAX_ANSWER_CHARS],
                related_unit_id=related_unit, source_type="auto_mined", status="pending_review",
                hit_count=total, embedding=vectors[rep], mine_group_key=f"mine:{norm[:60]}",
                review_note=f"最近提问 {items[rep]['last']:%Y-%m-%d %H:%M}；变体示例：{' / '.join(samples[:4])}"
                if items[rep]["last"] else f"变体示例：{' / '.join(samples[:4])}",
            ))
            created += 1
    await session.flush()
    return {"clusters": len(clusters), "created": created, "updated": updated, "considered": len(groups)}


async def mine_gaps(session: AsyncSession, *, days: int | None = None) -> dict:
    """把 gap_flag 的提问按向量聚类归并为知识缺口（ask_count 累加）。"""
    settings = get_settings()
    days = days or settings.faq_mine_lookback_days
    since = datetime.now() - timedelta(days=days)
    logs = (await session.execute(
        select(QaAccessLog.question, QaAccessLog.created_at, QaAccessLog.top_score)
        .where(QaAccessLog.gap_flag.is_(True), QaAccessLog.created_at >= since)
        .order_by(QaAccessLog.created_at)
    )).all()
    if not logs:
        return {"considered": 0, "created": 0, "updated": 0}

    groups: dict[str, dict] = {}
    for question, created_at, score in logs:
        key = normalize_question(question)
        if not key:
            continue
        g = groups.setdefault(key, {"question": question, "count": 0, "last": created_at, "samples": [],
                                    "scores": []})
        g["count"] += 1
        g["last"] = max(g["last"] or created_at, created_at)
        g["scores"].append(score or 0)
        if len(g["samples"]) < 5 and question not in g["samples"]:
            g["samples"].append(question)
    items = list(groups.values())
    vectors = await embed_texts([g["question"] for g in items])
    clusters = _cluster(items, vectors, settings.faq_mine_similarity)

    open_gaps = list((await session.execute(
        select(KnowledgeGap).where(KnowledgeGap.status == "unresolved")
    )).scalars())
    existing_vectors = [g.embedding for g in open_gaps]
    for i, gap in enumerate(open_gaps):
        if gap.embedding is None:
            # 早期缺口没有向量：此处仅保留在列表中，不做语义合并（按问题文本兜底）
            existing_vectors[i] = None
    new_logs = sum(g["count"] for g in items)
    created = updated = 0
    for group in clusters:
        total = sum(items[i]["count"] for i in group)
        rep = _representative(items, group, vectors)
        pattern = items[rep]["question"]
        last = max(items[i]["last"] for i in group)
        samples = [s for i in group for s in items[i]["samples"]][:8]
        matched = None
        for gi, gap in enumerate(open_gaps):
            emb = existing_vectors[gi]
            if emb and _cosine(emb, vectors[rep]) >= settings.faq_mine_similarity:
                matched = gap
                break
            if emb is None and normalize_question(gap.question_pattern) == normalize_question(pattern):
                matched = gap
                break
        if matched:
            matched.ask_count += total
            matched.last_asked_at = last
            merged = list(dict.fromkeys((matched.sample_questions_json or []) + samples))[:10]
            matched.sample_questions_json = merged
            matched.embedding = vectors[rep]
            updated += 1
        else:
            gap = KnowledgeGap(question_pattern=pattern, sample_questions_json=samples, ask_count=total,
                               last_asked_at=last, status="unresolved", embedding=vectors[rep])
            session.add(gap)
            open_gaps.append(gap)
            existing_vectors.append(vectors[rep])   # 与本轮后续簇去重时参与相似度比较
            created += 1
    await session.flush()
    # 已把目前为止的缺口都归并，清零 gap_flag，避免下次重复累加
    await session.execute(
        text("UPDATE qa_access_logs SET gap_flag = false WHERE gap_flag AND created_at >= :since"),
        {"since": since},
    )
    return {"considered": new_logs, "created": created, "updated": updated}


async def run_all(*, days: int | None = None) -> dict:
    async with SessionLocal() as session:
        faq_result = await mine_faqs(session, days=days)
        gap_result = await mine_gaps(session, days=days)
        await session.commit()
    result = {"faq": faq_result, "gap": gap_result, "ran_at": datetime.now().isoformat(timespec="seconds")}
    log.info("沉淀挖掘完成：%s", result)
    return result


__all__ = ["mine_faqs", "mine_gaps", "run_all"]
