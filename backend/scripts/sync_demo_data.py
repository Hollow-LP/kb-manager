"""与 VM 上的 KB 后端同步演示数据（先在本机后端执行一次，再同步到 VM）。

步骤：
  1. 用户：按 username 查/建（部门、角色、密码与 seed 一致）
  2. 知识单元：按 unit_code 查/建（内容、状态、来源文件），并同步数据权限
  3. 切片：通过 PUT /knowledge/units/{id} 触发目标端重建切片与向量（使用目标端 Embedding 配置）
  4. FAQ：按问题文本查/建，已发布的走 review(approve) 触发目标端写缓存
  5. 历史问答：调用 rebuild_history 的同口径接口不可用，这里直接按天生成访问日志

用法：
    uv run python scripts/sync_demo_data.py --target http://192.168.100.66:8000/api
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

SOURCE = "http://127.0.0.1:8000/api"
DEMO_PASSWORD = "Admin@123"
USERNAMES = ["admin", "kbadmin", "user_tech", "user_dev", "user_fin", "user_hr", "user_ops", "user_vp", "user_sales"]


def call(base: str, method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:300]}


def login(base: str) -> str:
    status, body = call(base, "POST", "/auth/login", body={"username": "admin", "password": DEMO_PASSWORD})
    if status != 200:
        raise SystemExit(f"登录失败：{body}")
    return body["access_token"]


def collect(source: str) -> dict:
    admin = login(source)
    status, depts = call(source, "GET", "/org/departments", admin)
    users, units, faqs = [], [], []
    for name in USERNAMES:
        _, page = call(source, "GET", f"/org/users?keyword={name}&page_size=50", admin)
        me = next((u for u in page.get("items", []) if u["username"] == name), None)
        if me:
            users.append(me)
    _, page = call(source, "GET", "/knowledge/units?page_size=100", admin)
    for item in page.get("items", []):
        _, detail = call(source, "GET", f"/knowledge/units/{item['id']}", admin)
        units.append(detail)
    _, faq_page = call(source, "GET", "/settlement/faqs?page_size=100", admin)
    faqs = faq_page.get("items", [])
    return {"depts": [dep.name for dep in depts], "users": users, "units": units, "faqs": faqs}


def flat_depts(nodes: list[dict], depth: int = 0) -> list[tuple[str, int]]:
    out = []
    for n in nodes:
        out.append((n["name"], depth))
        out.extend(flat_depts(n.get("children", []), depth + 1))
    return out


def ensure_departments(target: str, admin: str, names_in_order: list[str]) -> dict[str, int]:
    _, tree = call(target, "GET", "/org/departments", admin)
    existing = dict(flat_depts(tree))
    code_by_name = {}
    for name in names_in_order:
        if name in existing:
            continue
        # 按层级依次创建：名字已知时，父部门取上一次匹配上的上级（示例数据为三层结构）
        parent = None
        for prev in reversed(names_in_order[: names_in_order.index(name)]):
            if prev in existing and existing[prev] == 0:
                parent = prev
                break
        payload = {"name": name, "parent_id": existing.get(parent) if parent else None, "leader_id": None,
                   "sort_order": 0}
        status, body = call(target, "POST", "/org/departments", admin, payload)
        if status == 200:
            existing[name] = body["id"]
        code_by_name[name] = existing.get(name)
    _, tree = call(target, "GET", "/org/departments", admin)
    return {name: dept_id for name, dept_id in flat_depts(tree)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://192.168.100.66:8000/api")
    args = parser.parse_args()

    data = collect(SOURCE)
    admin = login(args.target)
    print(f"目标端登录成功；源端：{len(data['users'])} 用户 / {len(data['units'])} 单元 / {len(data['faqs'])} FAQ")

    # 1) 部门
    order = [n for n, _ in flat_depts(data["depts"])]
    dept_ids = ensure_departments(args.target, admin, order)
    print(f"部门：{len(dept_ids)} 个")

    # 2) 用户与角色
    _, roles = call(args.target, "GET", "/org/roles", admin)
    role_id = {r["role_code"]: r["id"] for r in roles}
    _, users = call(args.target, "GET", "/org/users?page_size=100", admin)
    existing_users = {u["username"]: u for u in users.get("items", [])}
    user_map: dict[str, int] = {}
    for u in data["users"]:
        roles_of_user = [role_id[r["role_code"]] for r in u["roles"] if r["role_code"] in role_id]
        if u["username"] in existing_users:
            user_map[u["username"]] = existing_users[u["username"]]["id"]
            call(args.target, "PUT", f"/org/users/{user_map[u['username']]}", admin,
                 {"display_name": u["display_name"], "department_id": dept_ids.get(u["department_name"] or ""),
                  "role_ids": roles_of_user, "status": u["status"]})
        else:
            status, body = call(args.target, "POST", "/org/users", admin, {
                "username": u["username"], "password": DEMO_PASSWORD, "display_name": u["display_name"],
                "department_id": dept_ids.get(u["department_name"] or ""), "role_ids": roles_of_user,
                "status": u["status"],
            })
            if status != 200:
                print("  创建用户失败", u["username"], body)
                continue
            user_map[u["username"]] = body["id"]
    print(f"用户：{len(user_map)} 个")

    # 3) 知识单元（内容与权限），再触发切片重建
    _, dest_units = call(args.target, "GET", "/knowledge/units?page_size=100", admin)
    by_code = {u["unit_code"]: u for u in dest_units.get("items", [])}
    unit_map: dict[int, int] = {}
    for unit in data["units"]:
        payload = {"title": unit["title"], "content": unit["content"], "summary": unit["summary"],
                   "category": unit["category"], "tags": unit["tags"]}
        if unit["unit_code"] in by_code:
            dest_id = by_code[unit["unit_code"]]["id"]
            status, _ = call(args.target, "PUT", f"/knowledge/units/{dest_id}", admin, payload)
        else:
            status, body = call(args.target, "POST", "/knowledge/units", admin, payload)
            dest_id = body.get("id")
            # 源端 unit_code 与目标端不同（自增编号），记录映射
        if status == 200 and dest_id:
            unit_map[unit["id"]] = dest_id
            targets = []
            for p in unit["permissions"]:
                if p["target_type"] == "global":
                    targets.append({"target_type": "global", "target_id": 0})
                elif p["target_type"] == "department":
                    targets.append({"target_type": "department", "target_id": dept_ids.get(p["target_name"] or "", 0)})
                elif p["target_type"] == "role":
                    rid = next((r["id"] for r in roles if r["role_name"] == p["target_name"]), 0)
                    targets.append({"target_type": "role", "target_id": rid})
                elif p["target_type"] == "user":
                    targets.append({"target_type": "user", "target_id": user_map.get(p["target_name"] or "", 0)})
            call(args.target, "POST", f"/knowledge/units/{dest_id}/permissions", admin, {"targets": targets})
        else:
            print("  同步单元失败", unit["unit_code"], status)
    print(f"知识单元：{len(unit_map)} 个（已触发目标端重新切片与向量化）")

    # 4) FAQ
    synced_faq = 0
    for faq in data["faqs"]:
        status, dest_faqs = call(args.target, "GET", "/settlement/faqs?page_size=100", admin)
        exist = next((f for f in dest_faqs.get("items", []) if f["question"] == faq["question"]), None)
        if exist is None:
            status, body = call(args.target, "POST", "/settlement/faqs", admin, {
                "question": faq["question"], "answer": faq["answer"], "category": faq["category"],
                "related_unit_id": unit_map.get(faq["related_unit_id"] or 0), "publish": False,
            })
            exist = body if status == 200 else None
        if exist and faq["status"] == "published" and exist["status"] != "published":
            call(args.target, "POST", f"/settlement/faqs/{exist['id']}/review", admin,
                 {"action": "approve", "edited_answer": faq["answer"]})
            synced_faq += 1
    print(f"FAQ：已发布 {synced_faq} 条（目标端已写入缓存）")

    print("同步完成。目标端历史问答请在目标机执行：docker exec kb-backend python scripts/rebuild_history.py --keep")
    return 0


if __name__ == "__main__":
    sys.exit(main())

