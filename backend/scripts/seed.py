"""初始化演示数据：部门、用户、角色权限、示例知识单元（含切片与向量）、少量历史问答。

可重复执行（幂等）：已存在的用户名 / 单元编号会被跳过。
    uv run python scripts/seed.py            # 完整初始化
    uv run python scripts/seed.py --reset    # 清空本脚本创建的业务数据后重建（不动表结构）
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

from app.core.permissions import (  # noqa: E402
    ALL_PERMISSIONS,
    BUILTIN_ROLES,
    DEFAULT_ROLE_PERMISSIONS,
    KNOWLEDGE_ADMIN,
    NORMAL_USER,
    SYSTEM_ADMIN,
)
from app.core.security import hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ChatMessage,
    ChatSession,
    Department,
    Faq,
    ImportJob,
    KnowledgeGap,
    KnowledgeUnit,
    QaAccessLog,
    Role,
    RolePermission,
    UnitChunk,
    UnitPermission,
    User,
    UserRole,
)
from app.services.llm import embed_texts_sync  # noqa: E402
from app.services.parser import parse  # noqa: E402
from app.services.parser.splitter import split_markdown, split_text  # noqa: E402

SEED_DOCS = Path(__file__).resolve().parents[1] / "seed_docs"
DEMO_PASSWORD = "Admin@123"

# username, display, dept code, roles
USERS = [
    ("admin", "系统管理员", "tech", [SYSTEM_ADMIN]),
    ("kbadmin", "王知库", "admin_center", [KNOWLEDGE_ADMIN]),
    ("user_tech", "赵技术", "tech", [NORMAL_USER]),
    ("user_dev", "钱开发", "dev", [NORMAL_USER]),
    ("user_fin", "孙财务", "finance", [NORMAL_USER]),
    ("user_hr", "李人力", "hr", [NORMAL_USER]),
    ("user_ops", "周运维", "ops", [NORMAL_USER]),
    ("user_vp", "吴高管", "headquarters", [NORMAL_USER, "executive"]),
    ("user_sales", "郑销售", "sales", [NORMAL_USER]),
]

# (parent code, code, name, leader username)
DEPARTMENTS = [
    (None, "headquarters", "总公司", "admin"),
    ("headquarters", "tech", "技术中心", "user_tech"),
    ("tech", "dev", "研发部", "user_dev"),
    ("tech", "ops", "运维部", "user_ops"),
    ("headquarters", "finance", "财务中心", "user_fin"),
    ("headquarters", "admin_center", "行政中心", "kbadmin"),
    ("admin_center", "hr", "人力资源部", "user_hr"),
    ("headquarters", "sales", "销售中心", "user_sales"),
]

# 文件名 -> (分类, 权限实体列表)
UNITS = [
    ("员工报销制度.docx", "财务制度", [("global", 0)]),
    ("IT安全规范.pdf", "信息安全", [("department", "tech")]),
    ("财务审批权限手册.docx", "财务制度", [("department", "finance"), ("role", "executive")]),
    ("新员工入职指南.md", "人事制度", [("global", 0)]),
    ("数据合规红线.md", "合规管理", [("role", "kb_admin")]),
    ("差旅标准说明.txt", "财务制度", [("user", "user_tech")]),
    ("无权限配置的测试文档.txt", "测试数据", []),
    ("年假计算规则.docx", "人事制度", [("department", "admin_center")]),
]

# 历史提问（用于看板 / 挖掘演示）；question -> related file（用于伪造引用）
HISTORY_QUESTIONS = [
    "报销单被财务退回怎么办？",
    "报销单被财务退回怎么办？",
    "报销单被财务退回怎么办？",
    "报销单被财务退回怎么办啊",
    "跨年的发票能报销吗？",
    "跨年的发票能报销吗",
    "跨年发票可以报销吗",
    "工作电脑密码多久要换一次？",
    "工作电脑密码多久要换一次",
    "密码几天换一次",
    "出差住宿能住多少钱的酒店？",
    "出差住宿标准是多少？",
    "年假有几天？",
    "入职第一周需要做什么？",
    "公司有食堂吗？",
    "公司的股票期权怎么申请？",
    "可以用公司电脑挖矿吗？",
]


async def seed(reset: bool = False) -> None:
    async with SessionLocal() as session:
        if reset:
            await _reset(session)

        dept_ids = await _seed_departments(session)
        role_ids = await _seed_roles(session)
        user_ids = await _seed_users(session, dept_ids, role_ids)
        await _seed_units(session, dept_ids, role_ids, user_ids)
        await _seed_history(session, user_ids)
        await session.commit()

    print("完成：")
    print(f"  部门 {len(DEPARTMENTS)} 个，角色 {len(BUILTIN_ROLES) + 1} 个，用户 {len(USERS)} 个")
    print(f"  知识单元 {len(UNITS)} 个，演示密码统一为 {DEMO_PASSWORD}")


async def _reset(session) -> None:
    for model in (ChatMessage, QaAccessLog, ChatSession, KnowledgeGap, Faq, ImportJob, UnitChunk,
                  UnitPermission, KnowledgeUnit):
        await session.execute(delete(model))
    await session.execute(delete(UserRole))
    await session.execute(delete(RolePermission))
    await session.execute(delete(User))
    await session.execute(delete(Department))
    await session.execute(delete(Role))
    await session.flush()
    print("已清空业务数据")


async def _seed_departments(session) -> dict[str, int]:
    ids: dict[str, int] = {}
    for order, (parent, code, name, _leader) in enumerate(DEPARTMENTS):
        exist = (await session.execute(select(Department).where(Department.name == name))).scalar_one_or_none()
        if exist is None:
            exist = Department(name=name, parent_id=ids.get(parent) if parent else None, sort_order=order)
            session.add(exist)
            await session.flush()
        ids[code] = exist.id
    return ids


async def _seed_roles(session) -> dict[str, int]:
    ids: dict[str, int] = {}
    roles = dict(BUILTIN_ROLES)
    roles["executive"] = ("高管", "可访问高管专属知识单元")
    for code, (name, desc) in roles.items():
        role = (await session.execute(select(Role).where(Role.role_code == code))).scalar_one_or_none()
        if role is None:
            role = Role(role_code=code, role_name=name, description=desc)
            session.add(role)
            await session.flush()
        ids[code] = role.id
        wanted = set(DEFAULT_ROLE_PERMISSIONS.get(code, []))
        if code == "executive":
            wanted = {"ai:chat:view", "knowledge:ai:access", "knowledge:unit:view"}
        await _set_role_permissions(session, role.id, wanted)
    return ids


async def _set_role_permissions(session, role_id: int, codes: set[str]) -> None:
    current = set(
        (await session.execute(select(RolePermission.permission_code).where(RolePermission.role_id == role_id)))
        .scalars()
    )
    for code in codes - current:
        session.add(RolePermission(role_id=role_id, permission_code=code, permission_type=ALL_PERMISSIONS[code][1]))
    for code in current - codes:
        await session.execute(
            delete(RolePermission).where(RolePermission.role_id == role_id, RolePermission.permission_code == code)
        )


async def _seed_users(session, dept_ids: dict[str, int], role_ids: dict[str, int]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for username, display, dept, roles in USERS:
        user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if user is None:
            user = User(username=username, display_name=display, department_id=dept_ids[dept],
                        password_hash=hash_password(DEMO_PASSWORD))
            session.add(user)
            await session.flush()
        ids[username] = user.id
        for role in roles:
            exists = (await session.execute(
                select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role_ids[role])
            )).scalar_one_or_none()
            if exists is None:
                session.add(UserRole(user_id=user.id, role_id=role_ids[role]))
    # 部门负责人
    for _parent, __code, _name, leader in DEPARTMENTS:
        dept = (await session.execute(select(Department).where(Department.name == _name))).scalar_one()
        dept.leader_id = ids[leader]
    return ids


def _unit_code(index: int) -> str:
    return f"KU-{index:04d}"


async def _seed_units(session, dept_ids, role_ids, user_ids) -> None:
    embeds: list[str] = []
    plan: list[tuple[KnowledgeUnit, list[dict]]] = []
    for index, (file_name, category, targets) in enumerate(UNITS, start=1):
        code = _unit_code(index)
        exist = (await session.execute(select(KnowledgeUnit).where(KnowledgeUnit.unit_code == code))).scalar_one_or_none()
        if exist is not None:
            print(f"  跳过已存在单元 {code} {file_name}")
            continue
        path = SEED_DOCS / file_name
        data = path.read_bytes()
        doc = parse(file_name, data)
        unit = KnowledgeUnit(
            unit_code=code,
            title=path.stem,
            content=doc.markdown or doc.text,
            summary=doc.summary,
            category=category,
            tags=[category],
            source_file_name=file_name,
            file_type=doc.file_type,
            file_size=len(data),
            status="active",
            creator_id=user_ids["kbadmin"],
        )
        session.add(unit)
        await session.flush()
        for target_type, target_key in targets:
            target_id = 0
            if target_type == "department":
                target_id = dept_ids[target_key]
            elif target_type == "role":
                target_id = role_ids[target_key]
            elif target_type == "user":
                target_id = user_ids[target_key]
            session.add(UnitPermission(unit_id=unit.id, target_type=target_type, target_id=target_id))
        chunks = split_markdown(doc.markdown) if doc.file_type == "md" else split_text(doc.text)
        plan.append((unit, chunks))
        embeds.extend(c["content"] for c in chunks)

    if not plan:
        return
    print(f"  向量化 {len(embeds)} 个切片 ...")
    vectors = embed_texts_sync(embeds)
    offset = 0
    for unit, chunks in plan:
        for i, chunk in enumerate(chunks):
            session.add(UnitChunk(unit_id=unit.id, chunk_index=i, heading=chunk["heading"],
                                  content=chunk["content"], token_count=chunk["token_count"],
                                  embedding=vectors[offset]))
            offset += 1
        print(f"  {unit.unit_code} {unit.title}  {len(chunks)} 切片")


async def _seed_history(session, user_ids: dict[str, int]) -> None:
    existing = (await session.execute(select(QaAccessLog.id).limit(1))).scalar_one_or_none()
    if existing is not None:
        return
    rng = random.Random(20261022)
    units = (await session.execute(select(KnowledgeUnit.id, KnowledgeUnit.unit_code))).all()
    unit_by_title = {u[1]: u[0] for u in units}
    title_to_code = {Path(f).stem: _unit_code(i) for i, (f, _, _) in enumerate(UNITS, start=1)}
    related = {
        "报销单被财务退回怎么办？": "员工报销制度",
        "跨年的发票能报销吗？": "员工报销制度",
        "工作电脑密码多久要换一次？": "IT安全规范",
        "出差住宿能住多少钱的酒店？": "差旅标准说明",
        "年假有几天？": "年假计算规则",
        "入职第一周需要做什么？": "新员工入职指南",
    }
    askers = ["user_tech", "user_dev", "user_fin", "user_hr", "user_ops", "user_sales", "user_vp"]
    sessions: dict[str, ChatSession] = {}
    now = datetime.now()
    for n, question in enumerate(HISTORY_QUESTIONS):
        asker = askers[n % len(askers)]
        created = now - timedelta(days=rng.randint(0, 12), hours=rng.randint(0, 20))
        unit_id = unit_by_title.get(title_to_code.get(related.get(question, ""), ""))
        recalled = [unit_id] if unit_id else []
        session_key = asker + created.strftime("%m%d")
        chat = sessions.get(session_key)
        if chat is None:
            chat = ChatSession(user_id=user_ids[asker], title=question[:20], created_at=created, updated_at=created)
            session.add(chat)
            await session.flush()
            sessions[session_key] = chat
        session.add(ChatMessage(session_id=chat.id, user_id=user_ids[asker], role="user", content=question,
                                created_at=created))
        session.add(ChatMessage(session_id=chat.id, user_id=user_ids[asker], role="assistant",
                                content="（示例历史回答）", created_at=created))
        session.add(QaAccessLog(
            session_id=chat.id,
            user_id=user_ids[asker],
            question=question,
            question_norm=question,
            answer="（示例历史回答）",
            recalled_unit_ids_json=recalled,
            authorized_unit_ids_json=recalled,
            unauthorized_unit_ids_json=[],
            top_score=round(rng.uniform(0.55, 0.92) if recalled else rng.uniform(0.1, 0.33), 3),
            gap_flag=not recalled and "？" in question,
            prompt_tokens=rng.randint(600, 1200),
            completion_tokens=rng.randint(120, 400),
            total_tokens=0,
            response_time_ms=rng.randint(900, 4200),
            created_at=created,
        ))
    for log in (await session.execute(select(QaAccessLog))).scalars():
        # 注：历史演示数据里 total_tokens 可能与 prompt+completion 不一致（早期版本写死），统一按实际计算
        log.total_tokens = log.prompt_tokens + log.completion_tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="先清空业务数据")
    args = parser.parse_args()
    asyncio.run(seed(args.reset), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))


if __name__ == "__main__":
    main()
