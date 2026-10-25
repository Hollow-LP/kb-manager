"""组织架构服务：部门树、用户、角色与权限分配。"""

from collections import defaultdict

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.exceptions import AppError, not_found
from app.core.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_ROLES,
    PERMISSION_TREE,
    SYSTEM_ADMIN,
)
from app.core.security import hash_password
from app.models import Department, Role, RolePermission, User, UserRole
from app.schemas.auth import RoleBrief
from app.schemas.org import (
    DepartmentCreate,
    DepartmentNode,
    RoleItem,
    UserCreate,
    UserItem,
    UserUpdate,
)


# --------------------------------------------------------------------------- 部门

async def list_departments(session: AsyncSession) -> list[DepartmentNode]:
    depts = list((await session.execute(select(Department).order_by(Department.sort_order, Department.id))).scalars())
    leaders = {
        u.id: u.display_name
        for u in (await session.execute(select(User).where(User.id.in_([d.leader_id for d in depts if d.leader_id])))).scalars()
    } if any(d.leader_id for d in depts) else {}
    counts = dict(
        (await session.execute(select(User.department_id, func.count()).group_by(User.department_id))).all()
    )

    nodes: dict[int, DepartmentNode] = {}
    for d in depts:
        nodes[d.id] = DepartmentNode(
            id=d.id, parent_id=d.parent_id, name=d.name, leader_id=d.leader_id,
            leader_name=leaders.get(d.leader_id) if d.leader_id else None,
            sort_order=d.sort_order, member_count=counts.get(d.id, 0),
        )
    roots: list[DepartmentNode] = []
    for d in depts:
        node = nodes[d.id]
        if d.parent_id and d.parent_id in nodes:
            nodes[d.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots


async def _descendant_ids(session: AsyncSession, dept_id: int) -> set[int]:
    rows = (await session.execute(select(Department.id, Department.parent_id))).all()
    children: dict[int | None, list[int]] = defaultdict(list)
    for child_id, parent_id in rows:
        children[parent_id].append(child_id)
    result, stack = set(), [dept_id]
    while stack:
        cur = stack.pop()
        if cur in result:
            continue
        result.add(cur)
        stack.extend(children.get(cur, []))
    return result


async def create_department(session: AsyncSession, payload: DepartmentCreate) -> Department:
    if payload.parent_id is not None and await session.get(Department, payload.parent_id) is None:
        raise not_found("上级部门不存在")
    if payload.leader_id is not None and await session.get(User, payload.leader_id) is None:
        raise not_found("负责人用户不存在")
    dept = Department(name=payload.name, parent_id=payload.parent_id, leader_id=payload.leader_id,
                      sort_order=payload.sort_order)
    session.add(dept)
    await session.flush()
    return dept


async def update_department(session: AsyncSession, dept_id: int, payload: DepartmentCreate) -> Department:
    dept = await session.get(Department, dept_id)
    if dept is None:
        raise not_found("部门不存在")
    if payload.parent_id is not None:
        if payload.parent_id == dept_id:
            raise AppError("上级部门不能是自己")
        if payload.parent_id in await _descendant_ids(session, dept_id):
            raise AppError("不能把部门移动到自己的下级部门中")
    if payload.leader_id is not None and await session.get(User, payload.leader_id) is None:
        raise not_found("负责人用户不存在")
    dept.name = payload.name
    dept.parent_id = payload.parent_id
    dept.leader_id = payload.leader_id
    dept.sort_order = payload.sort_order
    return dept


async def delete_department(session: AsyncSession, dept_id: int) -> None:
    dept = await session.get(Department, dept_id)
    if dept is None:
        raise not_found("部门不存在")
    has_child = (await session.execute(select(func.count()).where(Department.parent_id == dept_id))).scalar_one()
    if has_child:
        raise AppError("请先删除或移走下级部门")
    has_user = (await session.execute(select(func.count()).where(User.department_id == dept_id))).scalar_one()
    if has_user:
        raise AppError("部门下还有用户，请先调整用户所属部门")
    await session.delete(dept)


# --------------------------------------------------------------------------- 用户

def _user_item(user: User) -> UserItem:
    return UserItem(
        id=user.id, username=user.username, display_name=user.display_name,
        department_id=user.department_id, department_name=user.dept.name if user.dept else None,
        status=user.status, roles=[RoleBrief.model_validate(r) for r in user.roles],
        created_at=user.created_at, updated_at=user.updated_at,
    )


async def list_users(session: AsyncSession, *, page: int, page_size: int, keyword: str | None,
                     department_id: int | None, status: str | None) -> tuple[list[UserItem], int]:
    stmt = select(User).options(joinedload(User.roles), joinedload(User.dept))
    count_stmt = select(func.count()).select_from(User)
    conditions = []
    # 用户名（ASCII）与显示名（中文）都做 ilike 模糊匹配
    if keyword:
        kw = f"%{keyword}%"
        conditions.append(or_(User.username.ilike(kw), User.display_name.ilike(kw)))
    if department_id is not None:
        conditions.append(User.department_id.in_(list(await _descendant_ids(session, department_id))))
    if status:
        conditions.append(User.status == status)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = (await session.execute(count_stmt)).scalar_one()
    users = (
        await session.execute(stmt.order_by(User.id).offset((page - 1) * page_size).limit(page_size))
    ).unique().scalars().all()
    return [_user_item(u) for u in users], total


async def _check_roles_exist(session: AsyncSession, role_ids: list[int]) -> None:
    if not role_ids:
        return
    found = set((await session.execute(select(Role.id).where(Role.id.in_(role_ids)))).scalars())
    missing = set(role_ids) - found
    if missing:
        raise not_found(f"角色不存在: {sorted(missing)}")


async def create_user(session: AsyncSession, payload: UserCreate) -> UserItem:
    exists = (await session.execute(select(User.id).where(User.username == payload.username))).scalar_one_or_none()
    if exists:
        raise AppError(f"用户名已存在: {payload.username}")
    if payload.department_id is not None and await session.get(Department, payload.department_id) is None:
        raise not_found("部门不存在")
    await _check_roles_exist(session, payload.role_ids)
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        department_id=payload.department_id,
        status=payload.status,
    )
    session.add(user)
    await session.flush()
    _assign_roles(session, user.id, payload.role_ids)
    await session.flush()
    return await _get_user_item(session, user.id)


async def update_user(session: AsyncSession, user_id: int, payload: UserUpdate) -> UserItem:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("用户不存在")
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if "department_id" in payload.model_fields_set:
        if payload.department_id is not None and await session.get(Department, payload.department_id) is None:
            raise not_found("部门不存在")
        user.department_id = payload.department_id
    if payload.status is not None:
        user.status = payload.status
    if payload.role_ids is not None:
        await _check_roles_exist(session, payload.role_ids)
        await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        _assign_roles(session, user_id, payload.role_ids)
    # 批量 delete 不会刷新已加载的 roles 关系，这里强制过期后重新查询，保证响应是最新数据
    await session.flush()
    session.expire(user)
    return await _get_user_item(session, user_id)


def _assign_roles(session: AsyncSession, user_id: int, role_ids: list[int]) -> None:
    for rid in dict.fromkeys(role_ids):
        session.add(UserRole(user_id=user_id, role_id=rid))


async def reset_password(session: AsyncSession, user_id: int, password: str) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("用户不存在")
    user.password_hash = hash_password(password)


async def toggle_user(session: AsyncSession, user_id: int, actor_id: int) -> str:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("用户不存在")
    if user_id == actor_id:
        raise AppError("不能停用自己的账号")
    user.status = "disabled" if user.status == "active" else "active"
    return user.status


async def delete_user(session: AsyncSession, user_id: int, actor_id: int) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("用户不存在")
    if user_id == actor_id:
        raise AppError("不能删除自己的账号")
    await session.delete(user)


async def _get_user_item(session: AsyncSession, user_id: int) -> UserItem:
    user = (
        await session.execute(
            select(User).where(User.id == user_id).options(joinedload(User.roles), joinedload(User.dept))
        )
    ).unique().scalar_one()
    return _user_item(user)


# --------------------------------------------------------------------------- 角色

async def list_roles(session: AsyncSession) -> list[RoleItem]:
    roles = list((await session.execute(select(Role).order_by(Role.id))).scalars())
    perms: dict[int, list[str]] = defaultdict(list)
    for rid, code in (await session.execute(select(RolePermission.role_id, RolePermission.permission_code))).all():
        perms[rid].append(code)
    counts = dict((await session.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id))).all())
    return [
        RoleItem(
            id=r.id, role_name=r.role_name, role_code=r.role_code, description=r.description,
            permission_codes=sorted(perms.get(r.id, [])), user_count=counts.get(r.id, 0),
            is_builtin=r.role_code in BUILTIN_ROLES, created_at=r.created_at, updated_at=r.updated_at,
        )
        for r in roles
    ]


async def create_role(session: AsyncSession, payload) -> RoleItem:
    exists = (await session.execute(select(Role.id).where(Role.role_code == payload.role_code))).scalar_one_or_none()
    if exists:
        raise AppError(f"角色编码已存在: {payload.role_code}")
    role = Role(role_name=payload.role_name, role_code=payload.role_code, description=payload.description)
    session.add(role)
    await session.flush()
    return await _get_role_item(session, role.id)


async def update_role(session: AsyncSession, role_id: int, payload) -> RoleItem:
    role = await session.get(Role, role_id)
    if role is None:
        raise not_found("角色不存在")
    if payload.role_name is not None:
        role.role_name = payload.role_name
    if payload.description is not None:
        role.description = payload.description
    return await _get_role_item(session, role_id)


async def delete_role(session: AsyncSession, role_id: int) -> None:
    role = await session.get(Role, role_id)
    if role is None:
        raise not_found("角色不存在")
    if role.role_code in BUILTIN_ROLES:
        raise AppError("内置角色不能删除")
    in_use = (await session.execute(select(func.count()).where(UserRole.role_id == role_id))).scalar_one()
    if in_use:
        raise AppError("角色下还有用户，请先解除关联")
    await session.delete(role)


async def assign_permissions(session: AsyncSession, role_id: int, codes: list[str]) -> list[str]:
    role = await session.get(Role, role_id)
    if role is None:
        raise not_found("角色不存在")
    if role.role_code == SYSTEM_ADMIN:
        raise AppError("系统管理员权限不可修改")
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    for code in dict.fromkeys(codes):
        name, ptype, _parent = ALL_PERMISSIONS[code]
        session.add(RolePermission(role_id=role_id, permission_code=code, permission_type=ptype))
    await session.flush()
    return sorted(set(codes))


async def _get_role_item(session: AsyncSession, role_id: int) -> RoleItem:
    role = await session.get(Role, role_id)
    codes = list(
        (await session.execute(select(RolePermission.permission_code).where(RolePermission.role_id == role_id))).scalars()
    )
    count = (await session.execute(select(func.count()).where(UserRole.role_id == role_id))).scalar_one()
    return RoleItem(
        id=role.id, role_name=role.role_name, role_code=role.role_code, description=role.description,
        permission_codes=sorted(codes), user_count=count, is_builtin=role.role_code in BUILTIN_ROLES,
        created_at=role.created_at, updated_at=role.updated_at,
    )


def permission_tree() -> list[dict]:
    """生成角色权限树：一级为模块分组，二级为菜单，三级为按钮。前端 el-tree 直接渲染。

    分组优先级决定展示顺序；分组与菜单的 key 前缀（group: / menu:）与权限码（module:resource:action）区分开。
    """
    from app.schemas.org import PermissionNode

    module_order = ["dashboard", "org", "knowledge", "ai", "settlement"]
    module_labels = {
        "dashboard": "数据看板", "org": "组织架构", "knowledge": "知识管理",
        "ai": "AI 问答", "settlement": "知识沉淀",
    }
    # 先建节点，再按 parent 关系挂接
    by_code = {code: PermissionNode(key=code, label=name, type=ptype) for code, name, ptype, _ in PERMISSION_TREE}
    tops: dict[str, list[PermissionNode]] = defaultdict(list)
    for code, _name, _ptype, parent in PERMISSION_TREE:
        node = by_code[code]
        if parent:
            by_code[parent].children.append(node)
        else:
            tops[code.split(":")[0]].append(node)
    grouped: list[PermissionNode] = []
    for module in module_order:
        if tops.get(module):
            grouped.append(
                PermissionNode(key=f"group:{module}", label=module_labels[module], type="menu", children=tops[module])
            )
    return [g.model_dump() for g in grouped]


__all__ = ["permission_tree"]
