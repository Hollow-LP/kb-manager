from fastapi import APIRouter, Depends, Query

from app.core.exceptions import permission_denied
from app.deps import CurrentUser, CurrentUserDep, SessionDep, require_permission
from app.schemas.common import OkResponse, Page
from app.schemas.org import (
    AssignPermissionsRequest,
    DepartmentCreate,
    DepartmentNode,
    RoleCreate,
    RoleItem,
    RoleUpdate,
    UserCreate,
    UserItem,
    UserUpdate,
    ResetPasswordRequest,
)
from app.services import org as org_service

router = APIRouter(prefix="/org", tags=["组织架构"])


# --------------------------------------------------------------------------- 部门

@router.get("/departments", response_model=list[DepartmentNode], summary="部门树")
async def departments(session: SessionDep, _: CurrentUserDep) -> list[DepartmentNode]:
    return await org_service.list_departments(session)


@router.post("/departments", response_model=DepartmentNode, summary="新增部门",
             dependencies=[Depends(require_permission("org:dept:create"))])
async def create_department(payload: DepartmentCreate, session: SessionDep) -> DepartmentNode:
    dept = await org_service.create_department(session, payload)
    await session.commit()
    nodes = await org_service.list_departments(session)
    return _find_node(nodes, dept.id)


@router.put("/departments/{dept_id}", response_model=DepartmentNode, summary="编辑部门",
            dependencies=[Depends(require_permission("org:dept:update"))])
async def update_department(dept_id: int, payload: DepartmentCreate, session: SessionDep) -> DepartmentNode:
    await org_service.update_department(session, dept_id, payload)
    await session.commit()
    return _find_node(await org_service.list_departments(session), dept_id)


@router.delete("/departments/{dept_id}", response_model=OkResponse, summary="删除部门",
               dependencies=[Depends(require_permission("org:dept:delete"))])
async def delete_department(dept_id: int, session: SessionDep) -> OkResponse:
    await org_service.delete_department(session, dept_id)
    await session.commit()
    return OkResponse()


def _find_node(nodes: list[DepartmentNode], dept_id: int) -> DepartmentNode:
    for node in nodes:
        if node.id == dept_id:
            node.children = []
            return node
        found = _find_node(node.children, dept_id)
        if found is not None:
            return found
    return None  # type: ignore[return-value]


# --------------------------------------------------------------------------- 用户

@router.get("/users", response_model=Page[UserItem], summary="用户列表",
            dependencies=[Depends(require_permission("org:user:view"))])
async def users(
    session: SessionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    department_id: int | None = None,
    status: str | None = Query(None, pattern="^(active|disabled)$"),
) -> Page[UserItem]:
    items, total = await org_service.list_users(
        session, page=page, page_size=page_size, keyword=keyword, department_id=department_id, status=status
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/users", response_model=UserItem, summary="新增用户",
             dependencies=[Depends(require_permission("org:user:create"))])
async def create_user(payload: UserCreate, session: SessionDep) -> UserItem:
    item = await org_service.create_user(session, payload)
    await session.commit()
    return item


@router.put("/users/{user_id}", response_model=UserItem, summary="编辑用户",
            dependencies=[Depends(require_permission("org:user:update"))])
async def update_user(user_id: int, payload: UserUpdate, session: SessionDep) -> UserItem:
    item = await org_service.update_user(session, user_id, payload)
    await session.commit()
    return item


@router.post("/users/{user_id}/reset-password", response_model=OkResponse, summary="重置密码",
             dependencies=[Depends(require_permission("org:user:reset_pwd"))])
async def reset_password(user_id: int, payload: ResetPasswordRequest, session: SessionDep) -> OkResponse:
    await org_service.reset_password(session, user_id, payload.password)
    await session.commit()
    return OkResponse()


@router.post("/users/{user_id}/toggle", summary="启用/停用",
             dependencies=[Depends(require_permission("org:user:toggle"))])
async def toggle_user(user_id: int, session: SessionDep, current: CurrentUserDep) -> dict:
    status = await org_service.toggle_user(session, user_id, current.id)
    await session.commit()
    return {"ok": True, "status": status}


@router.delete("/users/{user_id}", response_model=OkResponse, summary="删除用户",
               dependencies=[Depends(require_permission("org:user:delete"))])
async def delete_user(user_id: int, session: SessionDep, current: CurrentUserDep) -> OkResponse:
    await org_service.delete_user(session, user_id, current.id)
    await session.commit()
    return OkResponse()


# --------------------------------------------------------------------------- 角色

@router.get("/roles", response_model=list[RoleItem], summary="角色列表",
            dependencies=[Depends(require_permission("org:role:view"))])
async def roles(session: SessionDep) -> list[RoleItem]:
    return await org_service.list_roles(session)


@router.post("/roles", response_model=RoleItem, summary="新增角色",
             dependencies=[Depends(require_permission("org:role:create"))])
async def create_role(payload: RoleCreate, session: SessionDep) -> RoleItem:
    item = await org_service.create_role(session, payload)
    await session.commit()
    return item


@router.put("/roles/{role_id}", response_model=RoleItem, summary="编辑角色",
            dependencies=[Depends(require_permission("org:role:update"))])
async def update_role(role_id: int, payload: RoleUpdate, session: SessionDep) -> RoleItem:
    item = await org_service.update_role(session, role_id, payload)
    await session.commit()
    return item


@router.delete("/roles/{role_id}", response_model=OkResponse, summary="删除角色",
               dependencies=[Depends(require_permission("org:role:delete"))])
async def delete_role(role_id: int, session: SessionDep) -> OkResponse:
    await org_service.delete_role(session, role_id)
    await session.commit()
    return OkResponse()


@router.get("/permissions/tree", summary="权限树")
async def permissions_tree(_: CurrentUserDep) -> list[dict]:
    # 登录即可查看：角色管理页需要它渲染权限树
    return org_service.permission_tree()


# ------------------------------------------------------------------ 权限配置选项
# 知识管理员没有组织管理权限，但配置数据权限（/ 导入后查看）需要部门/角色/人员选项，
# 因此提供只读、字段精简的选项接口。

_OPTION_PERMISSIONS = ("knowledge:permission:update", "knowledge:import:create", "knowledge:unit:view")


def _require_option_access(user: CurrentUserDep) -> CurrentUser:
    if not user.has_any(_OPTION_PERMISSIONS):
        raise permission_denied("缺少查看权限选项的权限")
    return user


@router.get("/options/departments", summary="部门选项（权限配置用）")
async def option_departments(session: SessionDep, current: CurrentUserDep) -> list[dict]:
    _require_option_access(current)
    nodes = await org_service.list_departments(session)

    def flat(items: list[DepartmentNode], depth: int = 0) -> list[dict]:
        out: list[dict] = []
        for n in sorted(items, key=lambda x: (x.sort_order, x.id)):
            out.append({"id": n.id, "name": n.name, "parent_id": n.parent_id, "depth": depth})
            out.extend(flat(n.children, depth + 1))
        return out

    return flat(nodes)


@router.get("/options/roles", summary="角色选项（权限配置用）")
async def option_roles(session: SessionDep, current: CurrentUserDep) -> list[dict]:
    _require_option_access(current)
    roles = await org_service.list_roles(session)
    return [{"id": r.id, "role_name": r.role_name, "role_code": r.role_code} for r in roles]


@router.get("/options/users", summary="人员选项（权限配置用）")
async def option_users(session: SessionDep, current: CurrentUserDep, keyword: str | None = None) -> list[dict]:
    _require_option_access(current)
    users, _ = await org_service.list_users(session, page=1, page_size=100, keyword=keyword,
                                            department_id=None, status="active")
    return [{"id": u.id, "username": u.username, "display_name": u.display_name,
             "department_id": u.department_id, "department_name": u.department_name} for u in users]


@router.post("/roles/{role_id}/permissions", response_model=list[str], summary="分配角色权限（全量替换）",
             dependencies=[Depends(require_permission("org:role:assign_permission"))])
async def assign_permissions(role_id: int, payload: AssignPermissionsRequest, session: SessionDep) -> list[str]:
    codes = await org_service.assign_permissions(session, role_id, payload.permission_codes)
    await session.commit()
    return codes
