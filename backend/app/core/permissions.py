"""权限码字典与内置角色。前后端共享的权限清单以此为准（org/permissions/tree 接口也由此生成）。

权限码格式：<模块>:<资源>:<动作>；菜单权限与按钮权限分离；AI 访问单独标记为 ai 类型。
"""

from typing import Literal

PermissionType = Literal["menu", "button", "ai"]

SYSTEM_ADMIN = "sys_admin"
KNOWLEDGE_ADMIN = "kb_admin"
NORMAL_USER = "normal_user"

BUILTIN_ROLES: dict[str, tuple[str, str]] = {
    SYSTEM_ADMIN: ("系统管理员", "创建维护用户/角色/部门，分配权限，查看看板"),
    KNOWLEDGE_ADMIN: ("知识管理员", "导入维护知识单元，配置数据权限，审核 FAQ 与知识缺口"),
    NORMAL_USER: ("普通用户", "登录并进行 AI 智能问答"),
}

# (code, name, type, parent)
PERMISSION_TREE: list[tuple[str, str, PermissionType, str | None]] = [
    ("dashboard:view", "数据看板", "menu", None),

    ("org:user:view", "用户管理", "menu", None),
    ("org:user:create", "新增用户", "button", "org:user:view"),
    ("org:user:update", "编辑用户", "button", "org:user:view"),
    ("org:user:delete", "删除用户", "button", "org:user:view"),
    ("org:user:reset_pwd", "重置密码", "button", "org:user:view"),
    ("org:user:toggle", "启用/停用", "button", "org:user:view"),

    ("org:role:view", "角色管理", "menu", None),
    ("org:role:create", "新增角色", "button", "org:role:view"),
    ("org:role:update", "编辑角色", "button", "org:role:view"),
    ("org:role:delete", "删除角色", "button", "org:role:view"),
    ("org:role:assign_permission", "分配权限", "button", "org:role:view"),

    ("org:dept:view", "部门管理", "menu", None),
    ("org:dept:create", "新增部门", "button", "org:dept:view"),
    ("org:dept:update", "编辑部门", "button", "org:dept:view"),
    ("org:dept:delete", "删除部门", "button", "org:dept:view"),

    ("knowledge:import:view", "知识导入中心", "menu", None),
    ("knowledge:import:create", "上传导入", "button", "knowledge:import:view"),

    ("knowledge:unit:view", "知识单元", "menu", None),
    ("knowledge:unit:create", "新增知识单元", "button", "knowledge:unit:view"),
    ("knowledge:unit:update", "编辑知识单元", "button", "knowledge:unit:view"),
    ("knowledge:unit:delete", "删除知识单元", "button", "knowledge:unit:view"),
    ("knowledge:permission:update", "配置数据权限", "button", "knowledge:unit:view"),

    ("ai:chat:view", "AI 对话工作台", "menu", None),
    ("knowledge:ai:access", "AI 问答访问", "ai", "ai:chat:view"),

    ("settlement:faq:view", "FAQ 推荐与审核", "menu", None),
    ("settlement:faq:review", "审核 FAQ", "button", "settlement:faq:view"),
    ("settlement:faq:manage", "已发布 FAQ 库", "menu", None),
    ("settlement:gap:view", "知识缺口", "menu", None),
    ("settlement:gap:handle", "处理知识缺口", "button", "settlement:gap:view"),
]

ALL_PERMISSIONS: dict[str, tuple[str, PermissionType, str | None]] = {
    code: (name, ptype, parent) for code, name, ptype, parent in PERMISSION_TREE
}

# 知识管理员的默认权限：知识维护 + 沉淀管理 + AI（后端仍按数据权限过滤）
_KB_ADMIN_CODES = [
    code for code, _, ptype, _ in PERMISSION_TREE
    if code.startswith(("knowledge:", "settlement:")) or ptype == "ai" or code == "knowledge:unit:view"
]
_KB_ADMIN_CODES.append("ai:chat:view")

DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    SYSTEM_ADMIN: list(ALL_PERMISSIONS.keys()),
    KNOWLEDGE_ADMIN: sorted(set(_KB_ADMIN_CODES)),
    # 普通用户可见 AI 工作台，以及自己有权访问的知识单元（列表按数据权限过滤）
    NORMAL_USER: ["ai:chat:view", "knowledge:ai:access", "knowledge:unit:view"],
}
