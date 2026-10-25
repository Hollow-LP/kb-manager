"""M2 接口冒烟测试：登录、权限、部门、用户、角色。运行前需后端已启动。

uv run python scripts/smoke_m2.py
"""

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api"
results: list[str] = []


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict | list]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode("utf-8", errors="replace")[:500]}


def check(name: str, cond: bool, extra: object = "") -> None:
    results.append(("PASS" if cond else "FAIL") + f"  {name}  {extra if not cond else ''}")


admin = call("POST", "/auth/login", body={"username": "admin", "password": "Admin@123"})
check("admin 登录 200", admin[0] == 200, admin)
admin_token = admin[1]["access_token"]
check("admin 权限数量=30", len(admin[1]["permissions"]) == 30, len(admin[1]["permissions"]))
check("user_info 含部门与角色", admin[1]["user_info"]["department"] is not None and len(admin[1]["user_info"]["roles"]) == 1,
      admin[1]["user_info"])

bad = call("POST", "/auth/login", body={"username": "admin", "password": "wrong"})
check("错误密码 401 INVALID_CREDENTIALS", bad[0] == 401 and bad[1]["code"] == "INVALID_CREDENTIALS", bad)

noauth = call("GET", "/auth/me")
check("未登录 /auth/me 401", noauth[0] == 401 and noauth[1]["code"] == "AUTH_REQUIRED", noauth)

me = call("GET", "/auth/me", admin_token)
check("/auth/me 返回权限", me[0] == 200 and len(me[1]["permissions"]) == 30, me[0])

kb = call("POST", "/auth/login", body={"username": "kbadmin", "password": "Admin@123"})[1]
kb_token = kb["access_token"]
usr = call("POST", "/auth/login", body={"username": "user_tech", "password": "Admin@123"})[1]
usr_token = usr["access_token"]
check("kbadmin 14 项权限 / user_tech 3 项权限", len(kb["permissions"]) == 14 and len(usr["permissions"]) == 3,
      (len(kb["permissions"]), len(usr["permissions"])))

forbidden = call("GET", "/org/users", usr_token)
check("普通用户访问用户列表 403", forbidden[0] == 403 and forbidden[1]["code"] == "PERMISSION_DENIED", forbidden)
forbidden2 = call("GET", "/org/users", kb_token)
check("知识管理员访问用户列表 403", forbidden2[0] == 403, forbidden2[0])

tree = call("GET", "/org/departments", usr_token)
check("普通用户可读取部门树", tree[0] == 200, tree[0])
total_nodes = 0
levels: dict[int, list[str]] = {}


def walk(nodes: list[dict], depth: int = 0) -> None:
    global total_nodes
    for n in nodes:
        total_nodes += 1
        levels.setdefault(depth, []).append(n["name"])
        walk(n["children"], depth + 1)


walk(tree[1])
check("部门树至少 8 个节点且有三层", total_nodes >= 8 and len(levels) >= 3, (total_nodes, len(levels)))

created = call("POST", "/org/departments", admin_token, {"name": "测试部门", "parent_id": tree[1][0]["id"]})
check("新增部门 200", created[0] == 200, created)
dept_id = created[1]["id"]
upd = call("PUT", f"/org/departments/{dept_id}", admin_token, {"name": "测试部门-改", "parent_id": tree[1][0]["id"]})
check("编辑部门 200", upd[0] == 200 and upd[1]["name"] == "测试部门-改", upd)
cycle = call("PUT", f"/org/departments/{dept_id}", admin_token, {"name": "x", "parent_id": dept_id})
check("部门不能设为自己的上级 400", cycle[0] == 400, cycle)

users = call("GET", "/org/users?page=1&page_size=5&keyword=user", admin_token)
check("用户分页 keyword=user 命中且分页生效", users[0] == 200 and users[1]["total"] >= 7 and len(users[1]["items"]) == 5,
      users[1].get("total") if users[0] == 200 else users)
fin = call("GET", "/org/users?department_id=5&page_size=50", admin_token)
check("按部门(财务中心)过滤=1", fin[0] == 200 and fin[1]["total"] == 1, fin[1].get("total") if fin[0] == 200 else fin)

roles = call("GET", "/org/roles", admin_token)
role_by_code = {r["role_code"]: r for r in roles[1]}
check("角色 4 个", roles[0] == 200 and len(roles[1]) == 4, len(roles[1]))
new_user = call("POST", "/org/users", admin_token, {
    "username": "tester_m2", "password": "Test@123", "display_name": "审批产物", "department_id": dept_id,
    "role_ids": [role_by_code["normal_user"]["id"]],
})
session_uid = None
if new_user[0] == 400:
    # 上轮残留：先查到再编辑
    found = call("GET", "/org/users?keyword=tester_m2", admin_token)[1]["items"][0]
    session_uid = found["id"]
else:
    check("新增用户 200", new_user[0] == 200, new_user)
    session_uid = new_user[1].get("id") if isinstance(new_user[1], dict) else None
    if session_uid is None:
        results.append(f"DEBUG new_user={new_user!r}")

dup = call("POST", "/org/users", admin_token, {"username": "tester_m2", "password": "Test@123", "display_name": "dup"})
check("重复用户名 400", dup[0] == 400, dup)
upd_user = call("PUT", f"/org/users/{session_uid}", admin_token,
                {"display_name": "审批产物2", "role_ids": [role_by_code["kb_admin"]["id"]]})
check("编辑用户+改角色 200", upd_user[0] == 200 and upd_user[1]["display_name"] == "审批产物2"
      and upd_user[1]["roles"][0]["role_code"] == "kb_admin", upd_user)
new_login = call("POST", "/auth/login", body={"username": "tester_m2", "password": "Test@123"})
check("新用户登录且权限随角色变化(14)", new_login[0] == 200 and len(new_login[1]["permissions"]) == 14,
      new_login[0] if new_login[0] != 200 else len(new_login[1]["permissions"]))
rp = call("POST", f"/org/users/{session_uid}/reset-password", admin_token, {"password": "Reset@123"})
check("重置密码 200", rp[0] == 200, rp)
check("重置后旧密码失效", call("POST", "/auth/login", body={"username": "tester_m2", "password": "Test@123"})[0] == 401)
check("重置后新密码可登录", call("POST", "/auth/login", body={"username": "tester_m2", "password": "Reset@123"})[0] == 200)
tg = call("POST", f"/org/users/{session_uid}/toggle", admin_token)
check("停用后登录被拒 403", tg[1].get("status") == "disabled"
      and call("POST", "/auth/login", body={"username": "tester_m2", "password": "Reset@123"})[0] == 403, tg)
call("POST", f"/org/users/{session_uid}/toggle", admin_token)
check("删除用户 200", call("DELETE", f"/org/users/{session_uid}", admin_token)[0] == 200)

own_toggle = call("POST", "/org/users/1/toggle", admin_token)
check("不能停用自己 400", own_toggle[0] == 400, own_toggle)
check("删除部门 200", call("DELETE", f"/org/departments/{dept_id}", admin_token)[0] == 200)

ptree = call("GET", "/org/permissions/tree", usr_token)
check("权限树 5 个模块分组", ptree[0] == 200 and len(ptree[1]) == 5, ptree[0])
check("权限树含按钮子节点", any(g["key"] == "group:org" and g["children"][0]["children"] for g in ptree[1]) if ptree[0] == 200 else False)

new_role = call("POST", "/org/roles", admin_token, {"role_name": "审计员", "role_code": "auditor", "description": "只读"})
if new_role[0] == 200:
    rid = new_role[1]["id"]
    assigned = call("POST", f"/org/roles/{rid}/permissions", admin_token,
                    {"permission_codes": ["dashboard:view", "ai:chat:view", "knowledge:ai:access"]})
    check("分配权限 3 项", assigned[0] == 200 and len(assigned[1]) == 3, assigned)
    bad_code = call("POST", f"/org/roles/{rid}/permissions", admin_token, {"permission_codes": ["nope:x"]})
    check("未知权限码 422", bad_code[0] == 422, bad_code)
    check("删除角色 200", call("DELETE", f"/org/roles/{rid}", admin_token)[0] == 200)
else:
    check("新增角色 200", False, new_role)

sys_role = role_by_code["sys_admin"]["id"]
check("系统管理员权限不可改 400", call("POST", f"/org/roles/{sys_role}/permissions", admin_token,
                                    {"permission_codes": []})[0] == 400)
check("内置角色不可删 400", call("DELETE", f"/org/roles/{sys_role}", admin_token)[0] == 400)

print("\n".join(results))
failed = [r for r in results if r.startswith("FAIL")]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
