"""复现/重建演示问答日志（M8 演示数据）。

用法（在 backend 目录）：
    uv run python scripts/rebuild_history.py           # 只清理测试期间产生的日志与会话，重建种子历史
    uv run python scripts/rebuild_history.py --keep    # 清空全部问答日志后重建（不影响知识单元/用户）

生成 14 天的历史问答（用于看板趋势），其中包含：
  - 高频问题（供 M7 FAQ 挖掘）
  - 权限受限问题（技术中心用户提问财务手册，产生"权限缺失"与拦截统计）
  - 库外问题（gap_flag，供知识缺口识别）
"""

from __future__ import annotations

import argparse
import asyncio
import random
import selectors
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import ChatMessage, ChatSession, QaAccessLog, User  # noqa: E402

# 用户 -> (问题, 是否检索到授权资料, 召回单元代码, 授权单元代码)
UNITS = {"报销制度": ("KU-0001", 2), "IT规范": ("KU-0002", 3), "财务手册": ("KU-0003", 4),
         "入职指南": ("KU-0004", 5), "合规红线": ("KU-0005", 6), "差旅标准": ("KU-0006", 7),
         "年假规则": ("KU-0008", 9)}

SCENARIOS: list[tuple[str, str, list[str], list[str], float]] = [
    # (提问用户, 问题, 召回单元, 授权单元, 相关度)
    ("user_tech", "出差住宿标准是多少？", ["差旅标准", "报销制度"], ["差旅标准"], 0.88),
    ("user_tech", "出差住宿标准是多少", ["差旅标准", "报销制度"], ["差旅标准"], 0.87),
    ("user_dev", "报销单被财务退回怎么办？", ["报销制度"], ["报销制度"], 0.93),
    ("user_fin", "报销单被财务退回怎么办", ["报销制度"], ["报销制度"], 0.92),
    ("user_hr", "入职第一周需要做什么？", ["入职指南"], ["入职指南"], 0.81),
    ("user_sales", "年假有几天？", ["年假规则", "差旅标准"], [], 0.62),
    ("user_tech", "工作电脑密码多久要换一次？", ["IT规范"], ["IT规范"], 0.79),
    ("user_ops", "跨年的发票能报销吗？", ["报销制度"], ["报销制度"], 0.84),
    ("user_tech", "单笔五万元以上的费用需要谁审批？", ["财务手册", "报销制度", "年假规则"], ["报销制度"], 0.77),
    ("user_dev", "单笔五万元以上的费用需要谁审批？", ["财务手册", "报销制度"], ["报销制度"], 0.78),
    ("user_sales", "财务负责人能审批多少钱以内的费用？", ["财务手册"], [], 0.72),
    # 库外问题：授权单元列留空（没有任何资料可用于回答），按口径计为知识缺口
    ("user_hr", "公司今年营业收入是多少？", ["报销制度", "差旅标准"], [], 0.36),
    ("user_sales", "公司的股票期权怎么申请？", ["财务手册", "入职指南"], [], 0.31),
    ("user_ops", "公司食堂几点开饭？", ["入职指南"], [], 0.22),
    ("user_ops", "可以用公司电脑挖矿吗？", ["IT规范"], ["IT规范"], 0.51),
    ("user_vp", "高管出差可以坐公务舱吗？", ["差旅标准"], [], 0.69),
]

ANSWERS = {
    "出差住宿": "一线城市普通员工每晚不超过六百元，其他城市不超过四百元；部门负责人一线城市不超过九百元。",
    "报销单被财务退回": "查看退回原因，补正后在原单上重新提交即可，无需重新填写。",
    "入职第一周": "报到当天领取工牌与电脑，完成 OKR 系统信息填写，参加新人培训。",
    "年假": "根据您当前的数据权限，暂时无法访问相关制度，请联系知识管理员申请。",
    "密码": "员工账号每九十天更换一次强密码，长度不少于十二位。",
    "跨年": "上一年度十二月及以后的发票最迟在次年一月十五日前提交。",
    "五万元": "知识库中未找到相关信息。",
    "财务负责人": "根据您当前的数据权限，暂时无法访问相关制度，请联系知识管理员申请。",
    "营业收入": "知识库中未找到相关信息。",
    "股票期权": "知识库中未找到相关信息。",
    "挖矿": "办公电脑须安装公司统一安全客户端，禁止安装未经审批的软件。",
    "公务舱": "根据您当前的数据权限，暂时无法访问相关制度，请联系知识管理员申请。",
}


def answer_for(question: str) -> str:
    for key, value in ANSWERS.items():
        if key in question:
            return value
    return "知识库中未找到相关信息。"


async def main(reset_all: bool) -> None:
    rng = random.Random(20261023)
    now = datetime.now()
    async with SessionLocal() as s:
        users = {u.username: u for u in (await s.execute(select(User))).scalars()}
        b = {name: unit_id for name, (_code, unit_id) in UNITS.items()}

        if reset_all:
            await s.execute(delete(ChatMessage))
            await s.execute(delete(QaAccessLog))
            await s.execute(delete(ChatSession))
            print("已清空全部会话与问答日志")
        else:
            # 只清理“最近这些天的测试数据”，保留此前种子历史
            cutoff = now - timedelta(days=2)
            await s.execute(delete(QaAccessLog).where(QaAccessLog.created_at >= cutoff))
            ids = (await s.execute(select(ChatSession.id).where(ChatSession.created_at >= cutoff))).scalars().all()
            if ids:
                await s.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(ids)))
                await s.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
            print(f"已清理近 2 天的测试会话与日志（{len(ids)} 个会话）")

        created = 0
        sessions: dict[str, ChatSession] = {}
        for day_offset in range(13, -1, -1):
            day = now - timedelta(days=day_offset)
            count = rng.randint(3, 8) if day_offset else 14
            for _ in range(count):
                who, question, recalled, authorized, score = rng.choice(SCENARIOS)
                if who not in users:
                    continue
                user = users[who]
                created_at = day.replace(hour=rng.randint(9, 19), minute=rng.randint(0, 59),
                                         second=rng.randint(0, 59), microsecond=0)
                if created_at > now:
                    created_at = now
                key = f"{who}-{created_at.strftime('%m%d')}-{rng.randint(0, 3)}"
                chat = sessions.get(key)
                if chat is None:
                    chat = ChatSession(user_id=user.id, title=question[:20], created_at=created_at,
                                       updated_at=created_at)
                    s.add(chat)
                    await s.flush()
                    sessions[key] = chat
                answer = answer_for(question)
                # 知识缺口 = 没有任何授权资料且回答为"未找到"（与 AI 链路口径一致）；
                # 回答为"无权限"的属于权限原因，不计入缺口
                no_info = any(m in answer for m in ("未找到",))
                gap = no_info and not authorized
                prompt_tokens = rng.randint(700, 1200)
                completion_tokens = rng.randint(80, 260)
                s.add(QaAccessLog(
                    session_id=chat.id, user_id=user.id, question=question, question_norm=question,
                    answer=answer,
                    recalled_unit_ids_json=[b[k] for k in recalled],
                    authorized_unit_ids_json=[b[k] for k in authorized],
                    unauthorized_unit_ids_json=[b[k] for k in recalled if k not in authorized],
                    top_score=score, faq_hit=False, gap_flag=gap,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    response_time_ms=rng.randint(1500, 9000), created_at=created_at,
                ))
                s.add(ChatMessage(session_id=chat.id, user_id=user.id, role="user", content=question,
                                  created_at=created_at))
                s.add(ChatMessage(session_id=chat.id, user_id=user.id, role="assistant", content=answer,
                                  status="done", created_at=created_at))
                created += 1
        await s.commit()
    print(f"已生成 {created} 条问答日志（14 天）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="清空全部日志后重建（默认只清理近 2 天）")
    args = parser.parse_args()
    asyncio.run(main(args.keep), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
