"""M3 接口冒烟测试：导入（单/多文件）、进度轮询、单元 CRUD、数据权限配置、鉴权接口。

前置：后端已启动、已执行 seed.py。运行：
    uv run python scripts/smoke_m3.py
"""

import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000/api"
SEED = Path(__file__).resolve().parents[1] / "seed_docs"
results: list[str] = []


def call(method: str, path: str, token: str | None = None, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    url, _, query = path.partition("?")
    url = BASE + url
    if query:
        url += "?" + urllib.parse.urlencode(urllib.parse.parse_qsl(query, keep_blank_values=True))
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:300]}


def upload(token: str, files: list[Path]) -> tuple[int, object]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for f in files:
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{f.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
            + f.read_bytes() + b"\r\n"
        )
    body = b"".join(chunks) + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/knowledge/import", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def check(name: str, cond: bool, extra: object = "") -> bool:
    results.append(("PASS" if cond else "FAIL") + f"  {name}" + ("" if cond else f"  -> {extra}"))
    return cond


def login(username: str, password: str = "Admin@123") -> dict:
    status, body = call("POST", "/auth/login", body={"username": username, "password": password})
    assert status == 200, body
    return {"token": body["access_token"], "user": body["user_info"], "perms": body["permissions"]}


def wait_batch(token: str, batch_id: str, timeout: float = 180) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, jobs = call("GET", f"/knowledge/import/jobs?batch_id={batch_id}", token)
        assert status == 200, jobs
        if jobs and all(j["status"] in ("success", "failed") for j in jobs):
            return jobs
        time.sleep(1)
    raise TimeoutError("import batch timeout")


def main() -> int:
    admin = login("admin")
    kb = login("kbadmin")
    normal = login("user_tech")

    # ---------------------------------------------------------------- 权限
    status, _ = upload(normal["token"], [SEED / "年假计算规则.docx"])
    check("普通用户调用导入接口 403", status == 403, status)
    status, page = call("GET", "/knowledge/units?page_size=100", normal["token"])
    check("普通用户列表被强制按数据权限过滤（看不到无权限单元）",
          status == 200 and all(u["permissions"] for u in page["items"]), (status, page.get("total")))

    # ---------------------------------------------------------------- 导入
    batch_files = [SEED / "员工报销制度.docx", SEED / "IT安全规范.pdf", SEED / "数据合规红线.md"]
    status, body = upload(kb["token"], batch_files)
    if not check("批量导入 3 个文件 200", status == 200 and len(body.get("jobs", [])) == 3, body):
        return finish()
    batch_id = body["batch_id"]
    jobs = wait_batch(kb["token"], batch_id)
    check("3 个导入任务全部 success", all(j["status"] == "success" for j in jobs),
          [(j["file_name"], j["status"], j["error_message"]) for j in jobs])
    kinds = {j["file_name"].rsplit(".", 1)[-1] for j in jobs}
    check("覆盖 docx/pdf/md 三种格式", kinds == {"docx", "pdf", "md"}, kinds)

    # 单文件导入
    status, body = upload(kb["token"], [SEED / "差旅标准说明.txt"])
    single_jobs = wait_batch(kb["token"], body["batch_id"])
    check("单文件导入 txt success", status == 200 and single_jobs[0]["status"] == "success", single_jobs)

    # 非法格式被拒
    bad = Path(str(Path(__import__("tempfile").gettempdir()) / f"demo_{uuid.uuid4().hex[:6]}.png"))
    bad.write_bytes(b"\x89PNG")
    status, body = upload(kb["token"], [bad])
    check("非法格式整批拒绝 422", status == 422 and body.get("code") == "PARSE_FAILED", body)
    bad.unlink()

    # 空文件
    empty = Path(str(Path(__import__("tempfile").gettempdir()) / f"empty_{uuid.uuid4().hex[:6]}.txt"))
    empty.write_bytes(b"")
    status, body = upload(kb["token"], [empty])
    check("空文件拒绝 422", status == 422, body)
    empty.unlink()

    # ---------------------------------------------------------------- 单元查询
    imported_ids = [j["unit_id"] for j in jobs + single_jobs]
    edited_ids = list(imported_ids)
    status, detail = call("GET", f"/knowledge/units/{imported_ids[0]}", kb["token"])
    check("导入单元详情含正文/切片/摘要", status == 200 and detail["chunk_count"] > 0 and detail["content"]
          and detail["summary"], detail if status != 200 else detail.get("chunk_count"))
    check("新导入单元默认无任何数据权限", detail["permissions"] == [], detail["permissions"])

    status, page = call("GET", "/knowledge/units?page_size=50&keyword=KU-", kb["token"])
    check("单元列表可查询", status == 200 and page["total"] >= 12, page.get("total"))

    status, kpage = call("GET", "/knowledge/units?page_size=50&keyword=%E5%91%98%E5%B7%A5%E6%8A%A5%E9%94%80", kb["token"])
    check("按标题关键字搜索命中", status == 200 and kpage["total"] >= 1, kpage.get("total"))

    status, pdf_page = call("GET", "/knowledge/units?page_size=50&file_type=pdf", kb["token"])
    check("按格式过滤 pdf", status == 200 and all(u["file_type"] == "pdf" for u in pdf_page["items"]) and pdf_page["total"] >= 2,
          pdf_page.get("total"))

    status, cats = call("GET", "/knowledge/units/categories", kb["token"])
    check("分类列表可用", status == 200 and len(cats) >= 1, cats)

    # ---------------------------------------------------------------- 编辑
    unit_id = imported_ids[0]
    new_content = (SEED / "员工报销制度.docx").read_bytes()
    status, updated = call("PUT", f"/knowledge/units/{unit_id}", kb["token"], {
        "title": "员工报销制度（修订版）", "category": "财务制度", "tags": ["报销", "修订"],
        "summary": "报销制度修订说明",
        "content": "一、修订说明\n本次修订调整了报销时限。\n二、新时限\n员工须在费用发生后十个工作日内提交报销。\n三、其他\n票据要求保持不变。",
    })
    check("编辑单元标题/分类/正文 200", status == 200 and updated["title"].endswith("（修订版）")
          and updated["chunk_count"] >= 2 and updated["status"] == "active",
          updated if status != 200 else (updated.get("chunk_count"), updated.get("status")))
    _ = new_content

    status, detail = call("GET", f"/knowledge/units/{unit_id}", kb["token"])
    check("正文变更后切片重建（标题路径保留）", "修订说明" in detail["content"] and detail["chunk_count"] >= 2,
          detail.get("chunk_count"))

    # 制造解析失败：内容只有空行
    status, body = call("PUT", f"/knowledge/units/{unit_id}", kb["token"], {"content": "   \n\n  "})
    check("空正文拒绝 422", status == 422, body)

    # ---------------------------------------------------------------- 数据权限配置
    dept_id = next(d["id"] for d in call("GET", "/org/departments", admin["token"])[1]
                   if d["name"] == "总公司")
    tech_id = next(d["id"] for d in call("GET", "/org/departments", admin["token"])[1][0]["children"]
                   if d["name"] == "技术中心")
    roles = call("GET", "/org/roles", admin["token"])[1]
    exec_role = next(r["id"] for r in roles if r["role_code"] == "executive")
    user_vp = next(u["id"] for u in call("GET", "/org/users?keyword=user_vp", admin["token"])[1]["items"])
    user_fin = next(u["id"] for u in call("GET", "/org/users?keyword=user_fin", admin["token"])[1]["items"])

    # 单元 A：全局
    unit_a = imported_ids[0]
    status, perms = call("POST", f"/knowledge/units/{unit_a}/permissions", kb["token"],
                         {"targets": [{"target_type": "global", "target_id": 0}]})
    check("配置全局权限 200", status == 200 and perms[0]["target_type"] == "global", perms)

    # 单元 B：部门=技术中心 + 角色=高管 + 个人=user_fin（混合）
    unit_b = imported_ids[1]
    status, perms = call("POST", f"/knowledge/units/{unit_b}/permissions", kb["token"], {"targets": [
        {"target_type": "department", "target_id": tech_id},
        {"target_type": "role", "target_id": exec_role},
        {"target_type": "user", "target_id": user_fin},
    ]})
    check("混合配置三类实体 200", status == 200 and len(perms) == 3
          and {p["target_type"] for p in perms} == {"department", "role", "user"}, perms)
    check("权限条目带目标名称", all(p["target_name"] for p in perms), perms)

    # 单元 C：不配置（保持无权限）
    unit_c = imported_ids[2]
    unit_d = single_jobs[0]["unit_id"]

    status, body = call("POST", f"/knowledge/units/{unit_b}/permissions", kb["token"],
                        {"targets": [{"target_type": "department", "target_id": 999999}]})
    check("不存在的权限目标 422", status == 422, body)

    # ---------------------------------------------------------------- 鉴权接口
    all_units = [unit_a, unit_b, unit_c, unit_d]
    status, auth_user_tech = call("POST", "/knowledge/check-permissions", normal["token"],
                                  {"user_id": normal["user"]["id"], "unit_ids": all_units})
    check("技术中心用户：A(全局) 授权，B(部门) 授权，C/D 未授权",
          status == 200 and set(auth_user_tech["authorized_unit_ids"]) == {unit_a, unit_b}
          and set(auth_user_tech["unauthorized_unit_ids"]) == {unit_c, unit_d}, auth_user_tech)

    fin = login("user_fin")
    status, auth_fin = call("POST", "/knowledge/check-permissions", fin["token"],
                            {"user_id": fin["user"]["id"], "unit_ids": all_units})
    check("财务用户：A 授权，B(个人) 授权", status == 200 and set(auth_fin["authorized_unit_ids"]) == {unit_a, unit_b},
          auth_fin)

    vp = login("user_vp")
    status, auth_vp = call("POST", "/knowledge/check-permissions", vp["token"],
                           {"user_id": vp["user"]["id"], "unit_ids": all_units})
    check("高管：A 授权，B(角色) 授权", status == 200 and set(auth_vp["authorized_unit_ids"]) == {unit_a, unit_b},
          auth_vp)

    hr = login("user_hr")
    status, auth_hr = call("POST", "/knowledge/check-permissions", hr["token"],
                           {"user_id": hr["user"]["id"], "unit_ids": all_units})
    check("人力用户：仅 A 授权", status == 200 and auth_hr["authorized_unit_ids"] == [unit_a], auth_hr)

    status, body = call("POST", "/knowledge/check-permissions", normal["token"],
                        {"user_id": fin["user"]["id"], "unit_ids": all_units})
    check("不能查询他人权限 403", status == 403, body)
    status, body = call("POST", "/knowledge/check-permissions", "internal", {"user_id": fin["user"]["id"], "unit_ids": all_units},
                        headers={"X-Internal-Service-Token": "kb-internal-token"})
    check("仅内部令牌、无 JWT 仍 401", status == 401, status)

    status, body = call("POST", "/knowledge/check-permissions", normal["token"],
                        {"user_id": fin["user"]["id"], "unit_ids": all_units},
                        headers={"X-Internal-Service-Token": "kb-internal-token"})
    check("内部令牌可代为查询 200", status == 200 and set(body["authorized_unit_ids"]) == {unit_a, unit_b}, body)

    status, body = call("POST", "/knowledge/check-permissions", normal["token"],
                        {"user_id": normal["user"]["id"], "unit_ids": []})
    check("空 unit_ids 422", status == 422, body)

    # 角色权限即时生效：把普通用户角色去掉 AI 之外不影响数据权限；这里验证撤销配置即时生效
    status, _ = call("POST", f"/knowledge/units/{unit_b}/permissions", kb["token"], {"targets": []})
    status, auth_after = call("POST", "/knowledge/check-permissions", normal["token"],
                              {"user_id": normal["user"]["id"], "unit_ids": [unit_b]})
    check("清空单元 B 权限后部门用户立即失去访问", auth_after["unauthorized_unit_ids"] == [unit_b], auth_after)

    # ---------------------------------------------------------------- 手动创建 / 删除
    status, created = call("POST", "/knowledge/units", kb["token"], {
        "title": f"手动单元-{uuid.uuid4().hex[:6]}", "content": "一、说明\n这是手动创建的知识单元正文。\n二、附录\n附加说明。",
        "category": "测试数据", "tags": ["手动"],
    })
    check("手动创建单元 200 且已向量化", status == 200 and created["chunk_count"] >= 2, created)

    status, body = call("DELETE", "/knowledge/units", kb["token"], {"unit_ids": [created["id"], 999999]})
    check("批量删除（含不存在 ID）", status == 200 and body["deleted_unit_ids"] == [created["id"]]
          and body["not_found_unit_ids"] == [999999], body)
    check("删除后列表不可见", call("GET", f"/knowledge/units/{created['id']}", kb["token"])[0] == 404)
    status, page = call("GET", "/knowledge/units?include_deleted=true&keyword=手动单元", kb["token"])
    check("include_deleted 可查到已删除单元", status == 200 and page["total"] >= 1 and
          any(u["status"] == "archived" for u in page["items"]), page.get("total"))
    status, restored = call("POST", "/knowledge/units/restore", kb["token"], {"unit_ids": [created["id"]]})
    check("恢复已删除单元", status == 200 and restored == [created["id"]], restored)
    call("DELETE", f"/knowledge/units/{created['id']}", kb["token"])

    check("普通用户编辑单元 403", call("PUT", f"/knowledge/units/{unit_a}", normal["token"], {"title": "x"})[0] == 403)
    check("普通用户配置权限 403",
          call("POST", f"/knowledge/units/{unit_a}/permissions", normal["token"], {"targets": []})[0] == 403)

    # 清理本次导入的单元，保持演示数据整洁（手动新建的单元已在上面删除并恢复，这里一并软删）
    cleanup_targets = sorted(set(all_units + [created["id"]] + edited_ids) - {created["id"]})
    cleanup = call("DELETE", "/knowledge/units", kb["token"], {"unit_ids": cleanup_targets})[1]
    check("清理本次测试产生的单元", set(cleanup["deleted_unit_ids"]) == set(cleanup_targets), cleanup)
    return finish()


def finish() -> int:
    print("\n".join(results))
    failed = [r for r in results if r.startswith("FAIL")]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    random.seed()
    sys.exit(main())
