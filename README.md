# 知识库管理平台（kb-manager）

集知识维护、四维数据权限、AI 鉴权问答、数据看板与知识沉淀于一体的知识库管理平台。

> **只想启动项目？** 看 [docs/STARTUP.md](docs/STARTUP.md)（日常 3 步启动 / 全新机器从零启动 / 常见问题）。

开发计划见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)，进度见 [docs/PROGRESS.md](docs/PROGRESS.md)，
接口说明见 [docs/API.md](docs/API.md)，业务演示见 [docs/DEMO.md](docs/DEMO.md)，验收记录见 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)，
模型微调流程见 [docs/FINETUNE.md](docs/FINETUNE.md)，项目总结（面试准备版）见 [docs/INTERVIEW.md](docs/INTERVIEW.md)。

## 架构

| 部分 | 技术栈 | 本机端口 |
|---|---|---|
| 前端 `frontend/` | Vue 3 + TS + Vite + Element Plus + Pinia + ECharts | 5173 |
| 后端 `backend/` | Python 3.12 + FastAPI + SQLAlchemy 2（async） | 8000 |
| PostgreSQL（pgvector） | 容器 `kb-postgres` | 5432 |
| Redis | 容器 `kb-redis` | 6379 |

数据库与缓存运行在 CentOS 虚拟机 **192.168.100.66**（`/opt/kb-manager`），本机只运行前后端代码。

## 环境要求

- Windows 10/11（开发机）：Python 3.12 + [uv](https://docs.astral.sh/uv/)、Node.js ≥ 20 + npm、OpenSSH 客户端
- 虚拟机 CentOS 7.9：Docker 26 + Docker Compose v2，已配置镜像加速
- 开发机可免密 SSH 登录 `root@192.168.100.66`

## 启动步骤

### 1. 启动数据库与缓存（VM）

```bash
ssh root@192.168.100.66 "cd /opt/kb-manager/deploy && docker compose up -d"
# 或
bash scripts/dev.sh vm-up
```

首次启动时 `backend/scripts/init_db.sql` 会自动执行，安装 `vector`、`pg_trgm` 扩展。
可访问 `192.168.100.66:5432`（kb / kb / kb_manager）与 `192.168.100.66:6379`。

> 注意：VM 上其他项目（etl-agent、milvus、ecommerce）会抢占 5432/6379，启动前需先停掉它们。
> 容器名、网络 `kb-net`、数据卷 `kb-manager_kb-pgdata` 均带 kb 前缀，不会影响其他项目的数据。

### 2. 后端

```bash
cd backend
cp .env.example .env          # 首次；按需修改 DATABASE_URL 的 host
uv sync --extra dev
uv run python run.py          # http://127.0.0.1:8000  API 文档 http://127.0.0.1:8000/api/docs
```

> Windows 上请用 `uv run python run.py` 启动，不要直接用 `uvicorn app.main:app`：
> psycopg 异步驱动不支持 Windows 默认的 ProactorEventLoop，`run.py` 会切换为 SelectorEventLoop。

### 3. 前端

```bash
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev                   # http://localhost:5173 ，/api 代理到 127.0.0.1:8000
npm run build                 # 生产构建，输出 dist/
```

开发机走 `.env.development` 中的 `VITE_API_TARGET` 指定后端地址。

## 部署方式：代码本机运行，VM 只承载依赖

本项目按约定**不在 VM 上部署代码**。VM（192.168.100.66）只通过 Docker 提供 PostgreSQL + pgvector、Redis：
容器编排文件 `/opt/kb-manager/deploy/docker-compose.yml`，容器 `kb-postgres`（5432）、`kb-redis`（6379），
`init_db.sql` 以只读方式挂载到容器的 `/docker-entrypoint-initdb.d/`，首次初始化时创建 `vector`、`pg_trgm` 扩展。

后端、前端在开发机运行，通过 `backend/.env` 中的 `DATABASE_URL` / `REDIS_URL` 连接 VM。
需要把依赖部署复制到新虚拟机时：

```bash
scp deploy/docker-compose.yml root@<vm>:/opt/kb-manager/deploy/
scp backend/scripts/init_db.sql root@<vm>:/opt/kb-manager/backend/scripts/
ssh root@<vm> "cd /opt/kb-manager/deploy && docker compose up -d"
```

VM 默认只能直连少数站点（npmmirror、阿里云镜像、Docker Hub 经 daocloud 加速）。需要 VM 访问 GitHub / HuggingFace / PyPI 时，在开发机执行：

```bash
ssh -f -N -o ExitOnForwardFailure=yes -R 7890:127.0.0.1:7890 root@192.168.100.66
```

之后在 VM 上把 `http://127.0.0.1:7890` 当作 HTTP 代理即可（`HTTPS_PROXY=http://127.0.0.1:7890 pip ...` / `git -c http.proxy=...`）。

## 目录

```
backend/     FastAPI 服务（app/、alembic/、scripts/、seed_docs/、tests/）
frontend/    Vue3 单页应用（src/api、router、stores、views、components）
deploy/      docker-compose.yml（kb-postgres、kb-redis）
scripts/     dev.sh 常用命令
docs/        DEVELOPMENT.md 开发文档、PROGRESS.md 进度、WORKLOG.md 工作记录、API.md 接口、DEMO.md 演示、ACCEPTANCE.md 验收、STARTUP.md 启动、FINETUNE.md 微调、INTERVIEW.md 项目总结
tools/       ssh_bootstrap.py（向 VM 安装 SSH 公钥的一次性脚本）
```

## 已知环境问题

开发机（Windows）上的 Python 3.12.8 运行时存在以下异常行为，已在代码中规避：

- 部分含中文的字符串 `==`、`str.startswith`、含中文的 `re` 匹配会给出错误结果（同一表达式换成其他来源的字符串结果又正常，原因未定位）。
- 规避方式：
  - 文档解析/切分的标题识别改为「按码位数值（`ord`）判断」，见 `app/services/parser/splitter.py`；
  - 代码层的中文判断（角色编码等）改用 ASCII 标识（如 `sys_admin`），数据中的中文保持原样；
  - 自动化测试中需要中文断言的用例，从 UTF-8 夹具文件（`backend/tests/fixtures/`）读取而不是写中文字面量。
- 另行注意：在 Git Bash 中用 `python -c "...中文..."` 传参会因 GBK 转码失真，验证中文逻辑请写成 `.py` 文件执行。

## 开发工作目录

测试脚本、截图、服务日志、下载的模型等非源码文件统一放在 `D:\kb-manager-work\`：

```
D:\kb-manager-work\
├── e2e\       浏览器端到端脚本（m2.js、m3.js）与截图 shots\
└── logs\      后端 / 前端服务日志、冒烟测试输出
```


启动服务时把日志重定向到这里，例如：

```bash
cd backend && uv run python run.py > D:/kb-manager-work/logs/backend.log 2>&1 &
cd frontend && npm run dev > D:/kb-manager-work/logs/frontend.log 2>&1 &
```

## 常见问题

| 现象 | 处理 |
|---|---|
| `/api/health` 显示 database error | VM 上 `docker ps` 确认 `kb-postgres` 为 healthy；检查 5432 是否被其他项目占用 |
| 后端报 `ProactorEventLoop` | 用 `uv run python run.py` 启动 |
| Ubuntu/CentOS 拉镜像慢 | 依赖 VM 上 `/etc/docker/daemon.json` 的 registry-mirrors |
| 前端 401 自动跳登录 | 预期行为（M2 登录功能完成后生效） |
