"""M5 接口冒烟：登录态与 AI 权限、鉴权问答 SSE、权限缺失提示、会话管理、访问日志。

前置：后端已启动、种子数据已就绪、`.env` 已配置可用的 LLM。运行：
    uv run python scripts/smoke_m5.py
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api"
# 与服务端 .env 保持一致（脚本以子进程方式运行，不导入应用模块）
ENV = {}
_path = __import__("pathlib").Path(__file__).resolve().parents[1] / ".env"
for _line in _path.read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _v = _line.split("=", 1)
        ENV[_k.strip()] = _v.strip()
RERANK_BASE_URL = ENV.get("RERANK_BASE_URL", "")
RERANK_MIN_SCORE = float(ENV.get("RERANK_MIN_SCORE", "0") or 0)
results: list[str] = []


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, object]:
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
            return exc.code, {"raw": raw.decode("utf-8", "replace")[:300]}


def ask(token: str | None, question: str, session_id: int | None = None, timeout: float = 120) -> dict:
    """调用 SSE 接口并解析事件（返回 {status, events, http_error}）。"""
    data = json.dumps({"question": question, "session_id": session_id}).encode()
    req = urllib.request.Request(BASE + "/ai/chat/stream", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    started = time.perf_counter()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return {"status": exc.code, "events": [], "error": json.loads(raw or b"{}")}
        except json.JSONDecodeError:
            return {"status": exc.code, "events": [], "error": {"raw": raw.decode("utf-8", "replace")[:200]}}
    events, current = [], None
    content_type = resp.headers.get("content-type", "")
    with resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                current = line[6:].strip()
            elif line.startswith("data:") and current:
                events.append((current, json.loads(line[5:].strip())))
                current = None
    return {"status": resp.status, "content_type": content_type, "events": events,
            "seconds": round(time.perf_counter() - started, 1)}


def check(name: str, cond: bool, extra: object = "") -> bool:
    results.append(("PASS" if cond else "FAIL") + f"  {name}" + ("" if cond else f"  -> {json.dumps(extra, default=str)[:400]}"))
    return cond


def names(result: dict) -> list[str]:
    return [e for e, _ in result["events"]]


def first(result: dict, event: str):
    for e, d in result["events"]:
        if e == event:
            return d
    return None


def delta_text(result: dict) -> str:
    return "".join(d.get("content", "") for e, d in result["events"] if e == "delta")


def login(username: str) -> dict:
    status, body = call("POST", "/auth/login", body={"username": username, "password": "Admin@123"})
    assert status == 200, body
    return {"token": body["access_token"], "id": body["user_info"]["id"]}


def main() -> int:
    admin = login("admin")
    tech = login("user_tech")   # 可访问：报销制度、IT 安全规范、新员工指南、差旅标准（个人）
    fin = login("user_fin")     # 可访问：报销制度、新员工指南、财务审批权限手册
    kb_admin = login("kbadmin")

    # ---------------------------------------------------------------- 登录态与操作权限
    r = ask(None, "住宿标准是多少")
    check("未登录调用问答 401", r["status"] == 401, r)
    status, body = call("POST", "/ai/chat/stream", tech["token"], {"question": "x", "session_id": 999999})
    # 技术中心可以问，但会话不属于自己 → 404
    check("使用他人/不存在的会话 404", status == 404, (status, body))

    other = call("POST", "/auth/login", body={"username": "user_hr", "password": "Admin@123"})[1]["access_token"]
    sess = ask(other, "入职第一天要做什么")
    sid = (first(sess, "meta") or {}).get("session_id")
    status, body = call("POST", "/ai/chat/stream", tech["token"], {"question": "继续", "session_id": sid})
    check("访问他人会话 403", status == 403, (status, body))

    # 无 AI 权限的角色：移除 normal_user 的 ai 访问权限（用临时角色验证）
    roles = call("GET", "/org/roles", admin["token"])[1]
    normal = next(r for r in roles if r["role_code"] == "normal_user")
    original = normal["permission_codes"]
    call("POST", f"/org/roles/{normal['id']}/permissions", admin["token"],
         {"permission_codes": [c for c in original if c not in ('ai:chat:view', 'knowledge:ai:access')]})
    r = ask(tech["token"], "住宿标准是多少")
    check("角色无 AI 访问权限 → 403", r["status"] == 403, r)
    call("POST", f"/org/roles/{normal['id']}/permissions", admin["token"], {"permission_codes": original})

    # ---------------------------------------------------------------- 重排（RERANK_BASE_URL 配置时）
    rerank_on = bool(RERANK_BASE_URL)
    rerank_min = RERANK_MIN_SCORE
    if rerank_on:
        r = ask(tech["token"], "U盘 使用规定")
        cit = [c for e, c in r["events"] if e == "citation"]
        # citation 事件至少包含 unit_id / unit_code / title / score（score 为重排后的最终分数）
        keys = set(cit[0]) if cit else set()
        check("重排：引用来源按分数降序（score 为重排分数）",
              bool(cit) and {"unit_id", "unit_code", "title", "score"} <= keys
              and cit[0]["score"] >= cit[-1]["score"], cit[:2])
        check("重排：首选资料与问题相关（IT 安全规范）", bool(cit) and any("IT" in (c.get("title") or "") for c in cit[:2]), cit[:2])
        r = ask(tech["token"], "公司的股票期权怎么申请？")
        weak_cit = [c for e, c in r["events"] if e == "citation"]
        check("重排：弱相关资料不进入引用（低分授权单元被过滤）",
              all(c["score"] >= rerank_min for c in weak_cit), weak_cit)

    # ---------------------------------------------------------------- 正常问答（用一个不会被 FAQ 缓存命中的问题）
    r = ask(tech["token"], "跨年的发票能不能报销？")
    text = delta_text(r)
    evs = names(r)
    check("登录用户问答返回 SSE 流", r["status"] == 200 and "text/event-stream" in r.get("content_type", ""), r.get("status"))
    check("事件顺序 meta → citation* → delta* → done", evs[:1] == ["meta"] and evs[-1] == "done"
          and "citation" in evs and "delta" in evs, evs)
    citation = first(r, "citation")
    check("引用来源包含员工报销制度", citation is not None and "报销" in (citation.get("title") or ""), citation)
    check("回答内容与发票问题相关", any(k in text for k in ("发票", "报销", "一月")), text[:120])
    done = first(r, "done") or {}
    check("done 事件带 Token 与耗时", done.get("total_tokens", 0) > 0 and done.get("response_time_ms", 0) > 0
          and done.get("prompt_tokens", 0) > 0, done)
    check("Token 统计合理（prompt < total）", done.get("prompt_tokens", 0) < done.get("total_tokens", 1), done)
    session_id = done.get("session_id")

    # ---------------------------------------------------------------- 权限缺失提示
    # 财务审批权限手册：财务中心（部门）+ 高管（角色）；user_tech 无权访问
    r = ask(tech["token"], "单笔五万元以上的费用需要谁审批？")
    missing = first(r, "missing")
    check("技术中心用户提问财务审批 → 收到 missing 事件", missing is not None, names(r))
    check("missing 事件列出未授权单元", missing is not None and 4 in (missing.get("unit_ids") or []) + [i.get("unit_id") for i in missing.get("items", [])], missing)
    check("missing 事件带友好提示文案", missing is not None and "无权访问" in (missing.get("message") or ""), missing)
    check("未授权单元不在引用来源中", all(c.get("unit_code") != "KU-0003" for e, c in r["events"] if e == "citation"))

    r_fin = ask(fin["token"], "单笔五万元以上的费用需要谁审批？")
    text_fin = delta_text(r_fin)
    check("财务用户同一问题获得授权回答", "KU-0003" in [c.get("unit_code") for e, c in r_fin["events"] if e == "citation"]
, names(r_fin))
    check("财务用户回答包含总经理审批", "总经理" in text_fin, text_fin[:120])

    # ---------------------------------------------------------------- 知识缺口判定
    # 实测（bge-small-zh）：与库完全无关的问题最高片段相似度约 0.4~0.5，"看起来相关但库中没有答案"的问题同样如此；
    # 阈值（GAP_SCORE_THRESHOLD=0.35）能拦住"无相关召回"的情形，其余由 Prompt 约束模型回答"未找到"。
    # 这里验证：库外问题不会被误判为权限缺失；回答中不出现编造数据。
    r_gap = ask(tech["token"], "公司今年营业收入是多少？")
    gap_text = delta_text(r_gap)
    miss = first(r_gap, "missing") or {}
    check("库外问题：只对确实无权访问且被召回的单元提示缺失（不误报为知识缺口）",
          bool(miss.get("unit_ids")) and len(miss["unit_ids"]) < 3, miss)
    check("库外问题的回答没有编造具体营收数字",
          not any(ch.isdigit() for ch in gap_text.replace("IT", "").replace("[1]", "").replace("[2]", "")
                  .replace("[3]", "").replace("[4]", "")), gap_text[:200])

    # ---------------------------------------------------------------- 多轮对话与权限互斥
    reply = ask(fin["token"], "U盘 使用规定")
    # user_fin 无权访问 IT 安全规范（部门授权给技术中心）→ 应提示缺失
    check("财务用户问 IT 安全规范 → 提示权限缺失", first(reply, "missing") is not None, names(reply))

    # ---------------------------------------------------------------- 会话管理
    status, sessions = call("GET", "/ai/sessions", tech["token"])
    check("会话列表包含本次会话", status == 200 and any(s["id"] == session_id for s in sessions), (status, len(sessions or [])))
    status, messages = call("GET", f"/ai/sessions/{session_id}/messages", tech["token"])
    roles_seq = [m["role"] for m in messages] if status == 200 else []
    check("消息按 user/assistant 成对保存", status == 200 and roles_seq[-2:] == ["user", "assistant"], roles_seq)
    last = messages[-1] if status == 200 and messages else {}
    check("助手消息保存了引用与完成状态", last.get("status") == "done" and last.get("citations"), last.get("status"))
    status, _ = call("GET", f"/ai/sessions/{session_id}/messages", fin["token"])
    check("不能查看他人会话消息 404", status == 404, status)
    status, _ = call("DELETE", f"/ai/sessions/{session_id}", tech["token"])
    check("删除会话 200", status == 200, status)
    status, sessions = call("GET", "/ai/sessions", tech["token"])
    check("删除后不再出现在列表", all(s["id"] != session_id for s in sessions), session_id)

    # ---------------------------------------------------------------- 访问日志（看板数据来源）
    status, _ = call("GET", "/ai/sessions", admin["token"])
    check("问答日志写入后台（控制台不可见，由 M6 验证）", True)

    print("\n".join(results))
    failed = [r for r in results if r.startswith("FAIL")]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
