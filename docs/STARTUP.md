## 日常启动（3 步）

所有命令在 `D:\PythonProject1\kb-manager` 下执行。需要开 **3 个终端窗口**（或第一个用后台方式）。

### 1. VM 上的数据库与缓存（PostgreSQL + Redis）

```bash
ssh root@192.168.100.66 "cd /opt/kb-manager/deploy && docker compose up -d"
ssh root@192.168.100.66 "docker ps --filter name=kb- --format '{{.Names}} {{.Status}}'"
# 期望：kb-postgres healthy(5432)、kb-redis(6379)
```

> 如果之前用 etl-agent / milvus / ecommerce 等项目，它们可能占用了 5432/6379，需要先停掉：
> `docker stop etl-postgres etl-redis ...`（各项目自行 `docker compose -p <项目> start` 恢复）

### 2. 后端（:8000）

```bash
cd D:\PythonProject1\kb-manager\backend
uv run python run.py
```

看到 `Uvicorn running on http://0.0.0.0:8000` 即可。验证：浏览器打开 http://127.0.0.1:8000/api/health 返回 `"status":"ok"`。

> 必须用 `run.py` 启动，不要用 `uvicorn app.main:app`（Windows 上默认事件循环与 PostgreSQL 驱动不兼容）。

### 3. 前端（:5173）

```bash
cd D:\PythonProject1\kb-manager\frontend
npm run dev
```

浏览器打开 **http://localhost:5173**，用 `admin / Admin@123` 登录。

---

## 当前这台机器上：服务已经在跑

刚才检查过，后端 :8000 和前端 :5173 都返回 200，直接打开 http://localhost:5173 就能用。
若要重启，先关掉占用端口的进程：

```bash
# 找到并结束占用 8000 的进程（PowerShell 里执行则用 Stop-Process -Id <PID>）
netstat -ano | findstr :8000
```

## 演示账号（密码均为 `Admin@123`）

| 账号 | 角色 | 部门 |
|---|---|---|
| admin | 系统管理员 | 技术中心 |
| kbadmin | 知识管理员 | 行政中心 |
| user_tech | 普通用户 | 技术中心 |
| user_fin | 普通用户 | 财务中心 |
| user_hr | 普通用户 | 人力资源部 |

完整演示步骤见 `docs/DEMO.md`。

---

## 在一台全新机器上从零启动

```bash
# 0) 前提：Python 3.12 + uv、Node 20+、可 SSH 到 VM；VM 上 Docker Compose
# 1) 依赖容器
ssh root@192.168.100.66 "cd /opt/kb-manager/deploy && docker compose up -d"

# 2) 后端依赖与配置
cd backend
cp .env.example .env
#   填写 DATABASE_URL / REDIS_URL（默认指向 192.168.100.66）、LLM_*、RERANK_*
uv sync --extra dev --extra ml          # ml 额外依赖用于本地向量模型

# 3) 向量模型（约 92MB；VM 上下载不了，需在本机准备）
uv run python scripts/download_model.py
#   若 HuggingFace 直连不通，先开代理隧道再下载：
#   ssh -f -N -R 7890:127.0.0.1:7890 root@192.168.100.66
#   HTTPS_PROXY=http://127.0.0.1:7890 uv run python scripts/download_model.py
#   下载后把 .env 中 EMBEDDING_MODEL 指向 backend/models/bge-small-zh-v1.5

# 4) 建表 + 种子数据
uv run alembic upgrade head
uv run python scripts/seed.py            # 8 篇示例文档、9 个用户、部门角色
uv run python scripts/rebuild_history.py --keep   # 可选：14 天演示问答（看板有数据）

# 5) 启动
uv run python run.py

# 6) 前端
cd ../frontend && npm install --registry=https://registry.npmmirror.com && npm run dev
```

`.env` 里必须填写的外部服务：

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 形如 `postgresql+psycopg://kb:kb@192.168.100.66:5432/kb_manager` |
| `REDIS_URL` | 形如 `redis://192.168.100.66:6379/0` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 问答模型（OpenAI 兼容接口） |
| `RERANK_BASE_URL` / `RERANK_API_KEY` / `RERANK_MODEL` | 重排模型（可留空，留空则只用向量分数） |

---

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 后端启动报数据库连接失败 | VM 容器没起，或 5432 被其他项目占用，见第 1 步 |
| `/api/health` 显示 `database: error` | 同上；也可 `ssh root@192.168.100.66 "docker logs kb-postgres --tail 50"` 查看 |
| 前端打开白屏 / 接口 500 | 后端未启动，或后端起在别的端口；检查 `frontend/.env.development` 的 `VITE_API_TARGET` |
| 提问提示「服务未配置问答模型」 | `backend/.env` 中 `LLM_*` 未填写 |
| 第一次导入文档很慢 | 首次加载向量模型约 10~20 秒 |
| 看板没有数据 | 先问几次问题，或执行 `uv run python scripts/rebuild_history.py --keep` |
