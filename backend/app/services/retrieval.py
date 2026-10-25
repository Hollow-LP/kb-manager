"""检索：向量（pgvector 余弦）召回 → （可选）qwen3-rerank 重排 → 单元级聚合。

规则：
  - 向量召回：按 chunk 的 cosine 相似度取 topN，得到每块的相似度（作为置信度分数）
  - 关键词召回：中文无空格分词，建议文档与问题都以"一、""第X章"等编号或自然词语书写；
    plainto_tsquery 对整句命中有限，主要弥补包含专有词的短查询
  - 融合：RRF（k=60）排序，输出统一到单元粒度：同单元多块合并，取最高相似度作为单元分数。
    实测（bge-small-zh，2026-10-23）：同一文档会产生大量语义相近的块，RRF 的排名加成会把"命中块多"的
    无关文档顶到前面；因此**最终排序按单元最高相似度**，RRF 分只作为并列时的次序。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.services.llm import embed_query

log = logging.getLogger("kb.retrieval")


@dataclass
class UnitHit:
    unit_id: int
    unit_code: str
    title: str
    score: float                        # 最高 chunk 相似度（0~1），用于置信度与缺口判定
    best_chunk_ids: list[int] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)
    rrf: float = 0.0                    # 融合排序分（仅用于排序）
    reranked: bool = False
    vector_score: float | None = None   # 重排前的向量相似度（诊断用）

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id, "unit_code": self.unit_code, "title": self.title,
            "score": round(self.score, 4), "vector_score": round(self.vector_score, 4) if self.vector_score else None,
            "reranked": self.reranked, "snippets": self.snippets,
        }


@dataclass
class RetrievalResult:
    query: str
    hits: list[UnitHit]

    @property
    def top_score(self) -> float:
        return self.hits[0].score if self.hits else 0.0

    def unit_ids(self) -> list[int]:
        return [h.unit_id for h in self.hits]


_VECTOR_SQL = text(
    """
    SELECT uc.id AS chunk_id, uc.unit_id, uc.heading, uc.content,
           (1 - (uc.embedding <=> CAST(:qvec AS vector))) AS sim
    FROM unit_chunks uc
    JOIN knowledge_units ku ON ku.id = uc.unit_id
    WHERE uc.embedding IS NOT NULL
      AND ku.deleted_at IS NULL AND ku.status = 'active'
    ORDER BY uc.embedding <=> CAST(:qvec AS vector)
    LIMIT :limit
    """
)

_KEYWORD_SQL = text(
    """
    SELECT uc.id AS chunk_id, uc.unit_id, uc.heading, uc.content,
           ts_rank(uc.tsv, plainto_tsquery('pg_catalog.simple', :q)) AS rank
    FROM unit_chunks uc
    JOIN knowledge_units ku ON ku.id = uc.unit_id
    WHERE uc.tsv @@ plainto_tsquery('pg_catalog.simple', :q)
      AND ku.deleted_at IS NULL AND ku.status = 'active'
    ORDER BY rank DESC
    LIMIT :limit
    """
)


async def search(session: AsyncSession, query: str, *, top_k: int | None = None) -> RetrievalResult:
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    query = (query or "").strip()
    if not query:
        return RetrievalResult(query, [])

    qvec = await embed_query(query)
    vector_rows = (await session.execute(_VECTOR_SQL, {"qvec": str(qvec), "limit": top_k * 4})).mappings().all()
    keyword_rows = []
    try:
        keyword_rows = (await session.execute(_KEYWORD_SQL, {"q": query, "limit": top_k * 4})).mappings().all()
    except Exception:  # 关键词检索失败不影响向量召回
        keyword_rows = []

    fused: dict[int, float] = defaultdict(float)   # unit_id -> rrf 分
    best_sim: dict[int, float] = defaultdict(float)
    best_chunks: dict[int, list[int]] = defaultdict(list)
    snippets: dict[int, list[str]] = defaultdict(list)
    meta: dict[int, tuple[str, str]] = {}

    def add(rows, k: int, vector: bool) -> None:
        for rank, row in enumerate(rows, start=1):
            uid = int(row["unit_id"])
            fused[uid] += 1.0 / (k + rank)
            if vector:
                sim = float(row["sim"])
                if sim > best_sim[uid]:
                    best_sim[uid] = sim
                if len(best_chunks[uid]) < 2:
                    best_chunks[uid].append(int(row["chunk_id"]))
            if len(snippets[uid]) < 2:
                snippets[uid].append((row["content"] or "")[:200])

    add(vector_rows, settings.rrf_k, vector=True)
    add(keyword_rows, settings.rrf_k, vector=False)

    # 单元元信息
    if fused:
        meta_rows = (
            await session.execute(
                text("SELECT id, unit_code, title FROM knowledge_units WHERE id IN (SELECT unnest(CAST(:ids AS BIGINT[])))"),
                {"ids": list(fused)},
            )
        ).all()
        meta = {int(r[0]): (r[1], r[2]) for r in meta_rows}

    hits = [
        UnitHit(unit_id=uid, unit_code=meta.get(uid, ("", ""))[0], title=meta.get(uid, ("", ""))[1],
                score=best_sim.get(uid, 0.0), best_chunk_ids=best_chunks.get(uid, []),
                snippets=snippets.get(uid, []), rrf=rrf)
        for uid, rrf in fused.items()
    ]
    hits.sort(key=lambda h: (-round(h.score, 4), -h.rrf))
    hits = hits[:top_k]
    if hits and settings.rerank_base_url and settings.rerank_api_key:
        await rerank(query, hits)
        hits.sort(key=lambda h: -h.score)
    return RetrievalResult(query, hits)


async def rerank(query: str, hits: list[UnitHit]) -> None:
    """用 qwen3-rerank 对候选单元重新打分，就地更新 hit.score（0~1）。

    接口为 DashScope 原生格式：POST {base}/services/rerank/text-rerank/text-rerank
      body {"model", "input": {"query", "documents"}, "parameters": {"return_documents": false}}
      resp {"output": {"results": [{"index", "relevance_score"}]}}
    失败时保持向量分数不变（不阻断问答），并记录日志。
    """
    settings = get_settings()
    documents, owners = [], []
    for hit in hits:
        # 用单元标题 + 最佳片段作为重排文本，保留文档语义同时控制长度
        body = (hit.snippets[0] if hit.snippets else "")[:1200]
        documents.append(f"《{hit.title}》\n{body}")
        owners.append(hit)
    url = f"{settings.rerank_base_url.rstrip('/')}/services/rerank/text-rerank/text-rerank"
    payload = {
        "model": settings.rerank_model,
        "input": {"query": query, "documents": documents},
        "parameters": {"return_documents": False, "top_n": len(documents)},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.rerank_timeout_seconds) as client:
            resp = await client.post(url, json=payload,
                                     headers={"Authorization": f"Bearer {settings.rerank_api_key}"})
            resp.raise_for_status()
            results = resp.json().get("output", {}).get("results", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("rerank 失败，沿用向量分数：%s", exc)
        return
    for item in results:
        idx = item.get("index")
        if idx is None or not (0 <= idx < len(owners)):
            continue
        score = float(item.get("relevance_score") or 0.0)
        owners[idx].vector_score = owners[idx].score
        owners[idx].score = max(0.0, min(1.0, score))
    for hit in hits:
        hit.reranked = True
