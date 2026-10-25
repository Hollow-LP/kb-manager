"""M8 验收走查：按验收标准 5~8 用真实服务 + 真实模型执行一遍，输出结果到 worklog 指定的日志目录。"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000/api"
OUT = "D:/kb-manager-work/logs/acceptance_run.txt"


def call(method, path, token=None, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def ask(token, question):
    req = urllib.request.Request(BASE + "/ai/chat/stream",
                                 data=json.dumps({"question": question}).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        resp = urllib.request.urlopen(req, timeout=180)
    except urllib.error.HTTPError as e:
        return {"status": e.code, "events": []}
    events, cur = [], None
    for line in resp:
        t = line.decode("utf-8").rstrip("\r\n")
        if t.startswith("event:"):
            cur = t[6:].strip()
        elif t.startswith("data:") and cur:
            events.append((cur, json.loads(t[5:])))
            cur = None
    return {"status": resp.status, "events": events}


def login(name):
    return call("POST", "/auth/login", None, {"username": name, "password": "Admin@123"})[1]["access_token"]


def event(result, name, default=None):
    for e, d in result["events"]:
        if e == name:
            return d
    return default


def delta(result):
    return "".join(d.get("content", "") for e, d in result["events"] if e == "delta")


def main():
    out = []
    tech, fin, admin = login("user_tech"), login("user_fin"), login("admin")

    # ⑤ AI 鉴权问答 + 缺失提示
    r = ask(tech, "单笔五万元以上的费用需要谁审批？")
    miss = event(r, "missing")
    out.append(f"[5] tech 收到缺失提示={bool(miss)} 缺失单元={[i['title'] for i in (miss or {}).get('items', [])]} "
               f"答案泄露财务手册内容={'总经理' in delta(r)}")
    r_fin = ask(fin, "单笔五万元以上的费用需要谁审批？")
    out.append(f"[5] fin 缺失提示={bool(event(r_fin, 'missing'))} 答案含审批规则={'总经理' in delta(r_fin)}")
    out.append(f"[5] 未登录调用={ask(None, 'x')['status']}")

    # ⑦ FAQ 挖掘 → 审核发布 → 缓存命中
    # 用库内可回答、且与历史日志问法一致的高频问题，确保能进入挖掘（同义合并到同一簇）
    for v in ["出差住宿标准是多少？", "出差住宿标准是多少", "出差住宿标准是多少？"]:
        r = ask(tech, v)
        out.append(f"[7] 提问 {v} -> status={r['status']} 有引用={bool(event(r, 'citation'))}")
    _, mined = call("POST", "/settlement/mining/run", admin)
    _, recs = call("GET", "/settlement/faqs?status=pending_review&page_size=100", admin)
    target = next((f for f in recs.get("items", []) if "住宿" in f["question"]), None)
    out.append(f"[7] 挖掘 returned created={mined.get('faq', {}).get('created')} 出现候选={bool(target)}")
    if target:
        _, pub = call("POST", f"/settlement/faqs/{target['id']}/review", admin,
                      {"action": "approve",
                       "edited_answer": "一线城市普通员工出差住宿每晚不超过 600 元，其他城市每晚不超过 400 元；部门负责人一线城市不超过 900 元。"})
        out.append(f"[7] 审核发布 status={pub.get('status')} cached={pub.get('cached')}")
        r_hit = ask(tech, " 出差住宿标准是多少? ")
        out.append(f"[7] 命中缓存={event(r_hit, 'meta', {}).get('faq_hit')} "
                   f"tokens={event(r_hit, 'done', {}).get('total_tokens')} 答案={delta(r_hit)[:28]}")

    # ⑧ 知识缺口识别 → 一键建档
    r_gap = ask(tech, "公司食堂几点开饭？")
    out.append(f"[8] 库外提问 status={r_gap['status']} 有缺失提示={bool(event(r_gap, 'missing'))} "
               f"回答={delta(r_gap)[:40]}")
    call("POST", "/settlement/mining/run", admin)
    _, gaps = call("GET", "/settlement/knowledge-gaps?page_size=50", admin)
    gap = next((x for x in gaps.get("items", []) if "食堂" in x["question_pattern"]), None)
    out.append(f"[8] 缺口识别={bool(gap)} 频次={gap['ask_count'] if gap else None}")
    if gap:
        s, res = call("POST", f"/settlement/knowledge-gaps/{gap['id']}/create-unit", admin,
                      {"title": "食堂就餐说明", "content": "一、开放时间\n公司食堂工作日 11:30-13:00 开放。",
                       "category": "人事制度"})
        out.append(f"[8] 一键建档 status={s} 单元={res.get('unit_code')}")
        if res.get("unit_id"):
            req = urllib.request.Request(BASE + "/knowledge/units",
                                         data=json.dumps({"unit_ids": [res["unit_id"]]}).encode(), method="DELETE")
            req.add_header("Authorization", f"Bearer {admin}")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req).read()

    # ⑥ 看板
    _, m = call("GET", "/dashboard/metrics?days=30", admin)
    _, ov = call("GET", "/dashboard/overview?days=30&granularity=day", admin)
    out.append(f"[6] 指标 visits={m['total_visits']} uv={m['unique_visitors']} units={m['total_units']} "
               f"tokens={m['total_tokens']} avg={m['avg_response_ms']}ms faq_hits={m['faq_hits']}")
    out.append(f"[6] 榜单 {len(ov['questions'])}/{len(ov['units'])} 趋势点={len(ov['trend'])} "
               f"响应样本={ov['response_time']['samples']} P95={ov['response_time']['p95']}ms")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
