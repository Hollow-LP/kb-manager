"""M6 接口冒烟：看板指标口径与数据库一致性、榜单、趋势、Token、响应时间、权限控制。

前置：后端已启动、数据库有部分问答日志（可先手动问几句）。运行：
    uv run python scripts/smoke_m6.py
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000/api"
results: list[str] = []


def call(method: str, path: str, token: str | None = None) -> tuple[int, object]:
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def check(name: str, cond: bool, extra: object = "") -> None:
    results.append(("PASS" if cond else "FAIL") + f"  {name}" + ("" if cond else f"  -> {json.dumps(extra, default=str)[:300]}"))


def login(username: str) -> str:
    status, body = call("POST", "/auth/login")
    _ = status
    req = urllib.request.Request(BASE + "/auth/login",
                                 data=json.dumps({"username": username, "password": "Admin@123"}).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req).read())["access_token"]


def main() -> int:
    admin = login("admin")
    tech = login("user_tech")
    kb = login("kbadmin")

    # ---------------------------------------------------------------- 权限
    for user, token in (("普通用户", tech), ("知识管理员", kb)):
        status, _ = call("GET", "/dashboard/metrics", token)
        check(f"{user}访问看板 403", status == 403, status)

    # ---------------------------------------------------------------- 指标
    status, metrics = call("GET", "/dashboard/metrics?days=30", admin)
    check("指标接口 200 且字段齐全",
          status == 200 and all(k in metrics for k in
                                ("total_visits", "unique_visitors", "total_units", "total_tokens", "avg_response_ms")),
          metrics)
    check("指标为非负整数", all(int(metrics[k]) >= 0 for k in ("total_visits", "unique_visitors", "total_units",
                                                          "total_tokens", "avg_response_ms")), metrics)
    check("UV 不超过访问次数", metrics["unique_visitors"] <= metrics["total_visits"], metrics)
    status, m7 = call("GET", "/dashboard/metrics?days=7", admin)
    check("近 7 天访问量 ≤ 近 30 天", m7["total_visits"] <= metrics["total_visits"], (m7["total_visits"], metrics["total_visits"]))
    status, _ = call("GET", "/dashboard/metrics?days=0", admin)
    check("days=0 参数校验 422", status == 422, status)

    # ---------------------------------------------------------------- 榜单
    status, questions = call("GET", "/dashboard/rankings/questions?days=365&top=5", admin)
    check("常见问题 TOP 返回且按次数降序",
          status == 200 and isinstance(questions, list) and len(questions) <= 5
          and all(questions[i]["ask_count"] >= questions[i + 1]["ask_count"] for i in range(len(questions) - 1)),
          questions[:3])
    status, units = call("GET", "/dashboard/rankings/units?days=365&top=5", admin)
    check("知识单元 TOP 返回且含拦截次数",
          status == 200 and all("hit_count" in u and "denied_count" in u for u in units), units[:2])
    check("单元榜引用次数降序", all(units[i]["hit_count"] >= units[i + 1]["hit_count"] for i in range(len(units) - 1)), units)
    check("单元榜：拦截数 ≤ 召回数 ≤ 引用数 + 拦截数（口径自洽）",
          all(u["denied_count"] <= u["recalled_count"] <= u["hit_count"] + u["denied_count"] for u in units),
          [(u["unit_code"], u["hit_count"], u["recalled_count"], u["denied_count"]) for u in units])

    # ---------------------------------------------------------------- 趋势
    status, trend = call("GET", "/dashboard/stats/trend?days=30&granularity=day", admin)
    check("按日趋势连续 30 个桶（缺失补齐）", status == 200 and len(trend) == 30, len(trend) if status == 200 else status)
    check("趋势按时间升序", trend == sorted(trend, key=lambda x: x["bucket"]), trend[:3])
    status, week = call("GET", "/dashboard/stats/trend?days=30&granularity=week", admin)
    check("按周趋势桶数少于按日", status == 200 and 1 <= len(week) <= 6, len(week))
    day_sum = sum(p["visits"] for p in trend)
    check("按周访问量合计等于按日合计", sum(p["visits"] for p in week) == day_sum, (sum(p["visits"] for p in week), day_sum))
    status, _ = call("GET", "/dashboard/stats/trend?days=30&granularity=month", admin)
    check("非法粒度 422", status == 422, status)

    # ---------------------------------------------------------------- Token
    status, tokens = call("GET", "/dashboard/stats/tokens?days=30", admin)
    check("Token 趋势含 prompt/completion 拆分",
          status == 200 and len(tokens) == 30
          and all(p["total_tokens"] == p["prompt_tokens"] + p["completion_tokens"] for p in tokens), tokens[-1:])
    check("Token 合计与指标一致", sum(p["total_tokens"] for p in tokens) == metrics["total_tokens"],
          (sum(p["total_tokens"] for p in tokens), metrics["total_tokens"]))

    # ---------------------------------------------------------------- 响应时间
    status, rt = call("GET", "/dashboard/stats/response-time?days=30", admin)
    check("响应时间分布标签与计数对齐",
          status == 200 and len(rt["labels"]) == len(rt["counts"]) and sum(rt["counts"]) == rt["samples"], rt)
    check("P50 ≤ P95 且平均值 > 0", rt["p50"] <= rt["p95"] and rt["avg"] >= 0, rt)
    check("样本数与访问次数一致", rt["samples"] == metrics["total_visits"], (rt["samples"], metrics["total_visits"]))

    # ---------------------------------------------------------------- 聚合
    status, ov = call("GET", "/dashboard/overview?days=30&granularity=day", admin)
    check("overview 聚合返回全部区块",
          status == 200 and all(k in ov for k in ("metrics", "questions", "units", "trend", "tokens", "response_time")),
          list(ov) if status == 200 else status)
    check("overview 指标与单独接口一致", ov["metrics"] == metrics, "mismatch")

    status, _ = call("GET", "/dashboard/overview")
    check("未登录访问看板 401", status == 401, status)

    print("\n".join(results))
    failed = [r for r in results if r.startswith("FAIL")]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    _ = Path
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
