"""M4 接口冒烟：scope 过滤、详情鉴权、可访问单元全集、内部令牌代查、四维矩阵。

前置：后端已启动、已执行 seed.py。运行：
    uv run python scripts/smoke_m4.py
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000/api"
INTERNAL = {"X-Internal-Service-Token": "kb-internal-token"}
results: list[str] = []


def call(method: str, path: str, token: str | None = None, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    url, _, query = path.partition("?")
    url = BASE + url + (("?" + urllib.parse.urlencode(urllib.parse.parse_qsl(query))) if query else "")
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


def check(name: str, cond: bool, extra: object = "") -> None:
    results.append(("PASS" if cond else "FAIL") + f"  {name}" + ("" if cond else f"  -> {json.dumps(extra, default=str)[:300]}"))


def login(username: str) -> dict:
    status, body = call("POST", "/auth/login", body={"username": username, "password": "Admin@123"})
    assert status == 200, body
    return {"token": body["access_token"], "id": body["user_info"]["id"],
            "dept": body["user_info"]["department"], "roles": body["user_info"]["roles"]}


def main() -> int:
    admin = login("admin")
    kb = login("kbadmin")
    tech = login("user_tech")
    fin = login("user_fin")
    hr = login("user_hr")
    vp = login("user_vp")

    # ---------------------------------------------------------------- 种子数据基线
    status, all_units = call("GET", "/knowledge/units?page_size=100", admin["token"])
    units = all_units["items"]
    by_title = {u["title"]: u for u in units}
    total = all_units["total"]
    expectations = {
        "员工报销制度": {"global"},           # 全局
        "IT安全规范": {"department"},          # 技术中心
        "财务审批权限手册": {"department", "role"},  # 财务中心 + 高管
        "新员工入职指南": {"global"},
        "数据合规红线": {"role"},              # 知识管理员
        "差旅标准说明": {"user"},              # 个人 user_tech
        "无权限配置的测试文档": set(),          # 未配置
        "年假计算规则": {"department"},         # 行政中心
    }
    ok = True
    for title, kinds in expectations.items():
        unit = by_title.get(title)
        if unit is None:
            ok = False
            continue
        actual = {p["target_type"] for p in unit["permissions"]}
        if actual != kinds:
            ok = False
            results.append(f"FAIL  种子单元权限({title}) 期望 {kinds} 实际 {actual}")
    check("种子 8 个单元的数据权限符合预期", ok and len(units) == 8, [u["title"] for u in units])

    # ---------------------------------------------------------------- 鉴权矩阵
    def authorized_ids(user: dict) -> set[int]:
        _, res = call("GET", "/knowledge/accessible-units", user["token"])
        return set(res["unit_ids"])

    tech_ids = authorized_ids(tech)
    expected_tech = {by_title[t]["id"] for t in ("员工报销制度", "IT安全规范", "新员工入职指南", "差旅标准说明")}
    check("技术中心用户可访问：全局2 + 部门1 + 个人1", tech_ids == expected_tech, sorted(tech_ids))

    fin_ids = authorized_ids(fin)
    expected_fin = {by_title[t]["id"] for t in ("员工报销制度", "财务审批权限手册", "新员工入职指南")}
    check("财务用户可访问：全局2 + 部门1", fin_ids == expected_fin, sorted(fin_ids))

    vp_ids = authorized_ids(vp)
    expected_vp = {by_title[t]["id"] for t in ("员工报销制度", "财务审批权限手册", "新员工入职指南")}
    check("高管（角色）可访问：全局2 + 角色1", vp_ids == expected_vp, sorted(vp_ids))

    hr_ids = authorized_ids(hr)
    expected_hr = {by_title[t]["id"] for t in ("员工报销制度", "新员工入职指南")}
    # 人力部门是"行政中心"的下级，按设计部门权限不向子部门继承，因此不命中年假规则
    check("人力用户可访问：仅全局2（部门权限不继承子部门）", hr_ids == expected_hr
          and by_title["年假计算规则"]["id"] not in hr_ids, sorted(hr_ids))

    # 直接任职于行政中心的用户（这次验证部门权限对本人命中的场景）
    status, created = call("POST", "/org/users", admin["token"], {
        "username": "m4_admin_center", "password": "M4@12345", "display_name": "M4 行政人员",
        "department_id": 6, "role_ids": [], "status": "active",
    })
    admin_center_ok = status == 200
    if admin_center_ok:
        _, tokens = call("POST", "/auth/login", body={"username": "m4_admin_center", "password": "M4@12345"})
        _, acc = call("GET", "/knowledge/accessible-units", tokens["access_token"])
        check("行政中心用户可访问年假规则（部门命中）", by_title["年假计算规则"]["id"] in set(acc["unit_ids"]), acc)
        check("行政中心用户同时可访问全局单元", {by_title["员工报销制度"]["id"], by_title["新员工入职指南"]["id"]}
              <= set(acc["unit_ids"]), acc)
        call("DELETE", f"/org/users/{created['id'] if status == 200 else 0}", admin["token"])

    kb_ids = authorized_ids(kb)
    check("知识管理员（角色）可访问数据合规红线，但无全局单元以外的权限",
          by_title["数据合规红线"]["id"] in kb_ids and by_title["员工报销制度"]["id"] in kb_ids,
          sorted(kb_ids))
    check("无权限配置的单元对任何人都不可访问",
          by_title["无权限配置的测试文档"]["id"] not in (tech_ids | fin_ids | vp_ids | hr_ids | kb_ids))

    # ---------------------------------------------------------------- 鉴权接口（兼容旧接口）
    all_ids = [u["id"] for u in units]
    status, res = call("POST", "/knowledge/check-permissions", tech["token"],
                       {"user_id": tech["id"], "unit_ids": all_ids})
    check("check-permissions：authorized + unauthorized 覆盖全部入参",
          status == 200 and set(res["authorized_unit_ids"]) | set(res["unauthorized_unit_ids"]) == set(all_ids)
          and set(res["authorized_unit_ids"]) == expected_tech, res)
    status, res = call("POST", "/knowledge/check-permissions", tech["token"],
                       {"user_id": fin["id"], "unit_ids": all_ids})
    check("查询他人权限被拒 403", status == 403 and res.get("code") == "PERMISSION_DENIED", res)
    status, res = call("POST", "/knowledge/check-permissions", tech["token"],
                       {"user_id": fin["id"], "unit_ids": all_ids}, headers=INTERNAL)
    check("内部令牌可代查他人权限", status == 200 and set(res["authorized_unit_ids"]) == expected_fin, res)
    status, res = call("GET", f"/knowledge/accessible-units?user_id={fin['id']}", tech["token"], headers=INTERNAL)
    check("GET accessible-units 内部令牌代查", status == 200 and set(res["unit_ids"]) == expected_fin, res)
    status, res = call("GET", f"/knowledge/accessible-units?user_id={fin['id']}", tech["token"])
    check("GET accessible-units 非内部令牌代查他人 403", status == 403, res)

    # ---------------------------------------------------------------- 列表过滤 scope=mine
    status, page = call("GET", "/knowledge/units?scope=mine&page_size=100", tech["token"])
    check("scope=mine：技术中心用户只看到 4 个单元", status == 200 and page["total"] == 4
          and {u["id"] for u in page["items"]} == expected_tech, page.get("total"))
    status, page = call("GET", "/knowledge/units?scope=mine&page_size=100", hr["token"])
    check("scope=mine：人力用户只看到 2 个单元", status == 200 and page["total"] == 2, page.get("total"))
    status, page = call("GET", "/knowledge/units?page_size=100", kb["token"])
    check("scope=all：知识管理员看到全部 8 个单元", status == 200 and page["total"] == 8, page.get("total"))
    status, page = call("GET", "/knowledge/units?scope=mine&keyword=IT", tech["token"])
    check("scope=mine 与关键字组合", status == 200 and page["total"] == 1 and page["items"][0]["title"] == "IT安全规范",
          page.get("total"))
    status, page = call("GET", "/knowledge/units?scope=mine&category=" + urllib.parse.quote("人事制度"), tech["token"])
    check("scope=mine 与分类组合：技术中心只能看到人事制度中的新员工入职指南", status == 200
          and {u["title"] for u in page["items"]} == {"新员工入职指南"}, page.get("total"))
    status, page = call("GET", "/knowledge/units?scope=mine&page_size=1", tech["token"])
    check("scope=mine 分页 total 按权限过滤后的总数", status == 200 and page["total"] == 4 and len(page["items"]) == 1,
          (page.get("total"), len(page.get("items", []))))
    status, page = call("GET", "/knowledge/units?page_size=100", tech["token"])
    check("普通用户请求 scope=all 被强制降级为 mine（仍只返回 4 个）", status == 200 and page["total"] == 4, page.get("total"))
    status, res = call("GET", "/knowledge/units?scope=bad", tech["token"])
    check("非法 scope 422", status == 422, status)

    # ---------------------------------------------------------------- 详情按数据权限拦截
    finance_unit = by_title["财务审批权限手册"]["id"]
    check("技术中心用户读取无权单元详情 403", call("GET", f"/knowledge/units/{finance_unit}", tech["token"])[0] == 403)
    check("财务用户读取该单元详情 200", call("GET", f"/knowledge/units/{finance_unit}", fin["token"])[0] == 200)
    check("高管通过角色读取该单元详情 200", call("GET", f"/knowledge/units/{finance_unit}", vp["token"])[0] == 200)

    # ---------------------------------------------------------------- 权限变更即时生效
    unit_id = by_title["IT安全规范"]["id"]
    status, _ = call("POST", f"/knowledge/units/{unit_id}/permissions", kb["token"],
                     {"targets": [{"target_type": "department", "target_id": hr["dept"]["id"]}]})
    check("知识管理员改 IT 规范权限为行政中心", status == 200, status)
    check("技术中心用户立即失去访问", unit_id not in authorized_ids(tech))
    check("人力用户立即获得访问", unit_id in authorized_ids(hr))
    check("scope=mine 同步变化", unit_id not in
          {u["id"] for u in call("GET", "/knowledge/units?scope=mine&page_size=100", tech["token"])[1]["items"]})
    call("POST", f"/knowledge/units/{unit_id}/permissions", kb["token"],
         {"targets": [{"target_type": "department", "target_id": tech["dept"]["id"]}]})
    check("恢复原权限后技术中心重新可访问", unit_id in authorized_ids(tech))

    # ---------------------------------------------------------------- 边界
    status, res = call("GET", "/knowledge/accessible-units")
    check("未登录 accessible-units 401", status == 401, status)
    check("不存在的用户 → 空集合（不泄露）", call("POST", "/knowledge/check-permissions", admin["token"],
                                            {"user_id": 999999, "unit_ids": all_ids}, headers=INTERNAL)[1]
          ["authorized_unit_ids"] == [])
    status, res = call("POST", "/knowledge/check-permissions", tech["token"],
                       {"user_id": tech["id"], "unit_ids": [999999]})
    check("不存在的单元 → unauthorized", status == 200 and res["unauthorized_unit_ids"] == [999999], res)

    print("\n".join(results))
    failed = [r for r in results if r.startswith("FAIL")]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
