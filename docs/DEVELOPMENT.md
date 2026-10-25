# 知识库管理平台（kb-manager）开发文档

> 配套需求：2.9 知识库管理平台
> 文档版本：v1.0 ｜ 编写日期：2026-10-22
> 用途：把需求拆成可逐步交付的开发步骤。每一步都有"交付物 / 验收点"，完成后打勾，再进入下一步。

---

## 0. 约定

### 0.1 需求条目编号

下文使用以下缩写引用需求原文：

| 缩写 | 对应章节 |
|---|---|
| R-scope | 2.9.1 开发范围 |
| R-role | 2.9.2 用户角色与权限 |
| R-page | 2.9.3 页面需求 |
| R-rule | 2.9.4 知识单元与权限规则 |
| R-fe | 2.9.5 前端模块要求 |
| R-be | 2.9.6 后端与服务模块要求 |
| R-db | 2.9.7 数据表要求 |
| R-api | 2.9.8 接口要求 |
| R-board | 2.9.9 看板与知识沉淀规则 |
| R-flow | 2.9.10 核心业务流程 |
| R-accept | 2.9.11 验收标准 |

### 0.2 步骤编号

`M{里程碑}.S{序号}`，例如 `M2.S3`。每一步都是可以单独交给我完成、单独验证的单元。

### 0.3 完成定义（DoD）

每一步"完成"必须满足：

- 代码可运行，无报错；
- 对应接口/页面能用真实数据演示；
- 前端与后端联调通过（接口步骤以 `curl`/Swagger 验证）；
- 更新 `docs/API.md`（如有接口变化）与 `README.md`。

---

## 1. 技术选型

沿用你已有项目（`Ai-service` / 电商智能客服）的技术栈与配置风格（`pydantic-settings` + `.env`、SQLAlchemy 2.0 + async、FastAPI 生命周期管理）。

| 层 | 选型 | 说明 |
|---|---|---|
| 后端框架 | Python 3.12 + FastAPI + Uvicorn | 与现有项目一致 |
| ORM / 迁移 | SQLAlchemy 2.0（async）+ Alembic | 迁移脚本生成 + 手写初始化 SQL |
| 数据库 | PostgreSQL 16（Docker）+ pgvector 扩展 | 向量列直接放 PG，减少组件数量 |
| 缓存 | Redis 7（Docker） | FAQ 缓存、会话上下文、导入进度 |
| 认证 | JWT（pyjwt）+ passlib[bcrypt] | R-be 认证鉴权模块 |
| 文档解析 | pypdf / python-docx / markdown（TXT 直接读） | 支持 PDF、MD、DOCX、TXT |
| 切片 | 自实现按标题层级 + 长度切分 | 一个文件 = 一个知识单元（R-rule），单元内再切片做向量 |
| 检索 | 关键词（PG `tsvector`/`pg_trgm`）+ 向量混合召回，RRF 融合 | R-be "向量检索/关键字混合召回" |
| 向量 | 可插拔 Embedding Provider：本地 `sentence-transformers`（默认，离线可用）/ 远程 OpenAI 兼容接口 | 无 API Key 也能演示 |
| LLM | OpenAI 兼容接口（DeepSeek/Qwen 等），`.env` 配置 | 流式 SSE 输出 |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Vue Router + Element Plus + ECharts | 组件齐全，适合管理端 + 对话工作台 |
| 包管理 | `uv`（后端）、`npm`（前端） | 本机已安装 uv 0.12 / Node 24 |

> **可选替换**：若希望后端更贴近 Java 技术栈（Spring Boot + MyBatis-Plus），在开工前提出，整体步骤划分不变，仅 M2–M8 的实现方式调整。

---

## 2. 总体架构

```
┌──────────────────────── 浏览器 (Vue3 SPA :5173) ────────────────────────┐
│ 登录/个人中心 │ 组织架构 │ 知识维护/导入 │ AI 对话工作台 │ 看板 │ 知识沉淀 │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ HTTP / SSE (JWT Bearer)
┌───────────────────────────────▼──────────────────────────────────────────┐
│                      FastAPI 后端 (:8000)                                 │
│  路由层    /api/auth  /api/org  /api/knowledge  /api/ai  /api/dashboard   │
│            /api/settlement                                               │
│  服务层    认证 │ 组织架构 │ 知识单元 │ 数据权限引擎 │ AI鉴权检索 │        │
│            看板统计 │ 沉淀挖掘 │ FAQ 缓存                                   │
│  数据层    SQLAlchemy async │ PostgreSQL(+pgvector) │ Redis │ 本地文件存储 │
│  后台任务  导入解析 Worker │ 沉淀定时任务（APScheduler）                    │
└──────────────────────────────────────────────────────────────────────────┘
                                │
                    LLM (OpenAI 兼容) / Embedding
```

**模块 → 需求映射**

| 后端模块（R-be） | 代码目录 | 主要接口（R-api） |
|---|---|---|
| 认证鉴权模块 | `app/core/security.py`、`app/services/auth.py`、`app/deps.py` | `/api/auth/*` |
| 组织架构服务 | `app/services/org.py` | `/api/org/*` |
| 知识单元管理服务 | `app/services/knowledge.py`、`app/services/parser/*` | `/api/knowledge/import`、`/api/knowledge/units*` |
| 数据权限引擎 | `app/services/permission.py` | `/api/knowledge/check-permissions` |
| AI 鉴权检索服务 | `app/services/chat.py`、`app/services/retrieval.py` | `/api/ai/chat/stream` |
| 数据看板统计服务 | `app/services/dashboard.py` | `/api/dashboard/*` |
| 知识沉淀挖掘服务 | `app/services/mining.py` | `/api/settlement/*` |
| FAQ 缓存服务 | `app/services/faq_cache.py` | 被 `/api/ai/chat/stream` 内部调用 |

---

## 3. 目录规划

```
kb-manager/
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── scripts/
│   │   ├── init_db.sql          # 数据库初始化脚本（验收交付物）
│   │   └── seed.py              # 示例数据：部门/用户/角色/知识文档导入
│   ├── seed_docs/               # 示例知识文档（PDF/MD/DOCX/TXT 各若干）
│   ├── tests/
│   └── app/
│       ├── main.py              # FastAPI 入口 + lifespan
│       ├── config.py            # Settings（pydantic-settings，读 .env）
│       ├── db.py                # async engine / session
│       ├── redis.py
│       ├── models/              # SQLAlchemy 模型（与 R-db 表一一对应）
│       ├── schemas/             # Pydantic 请求/响应模型
│       ├── deps.py              # get_db / get_current_user / require_permission
│       ├── core/
│       │   ├── security.py      # JWT 签发校验、密码哈希
│       │   └── exceptions.py    # 业务异常与统一错误响应
│       ├── routers/
│       │   ├── auth.py  org.py  knowledge.py  ai.py  dashboard.py  settlement.py
│       ├── services/
│       │   ├── auth.py  org.py  knowledge.py  permission.py  retrieval.py
│       │   ├── chat.py  dashboard.py  mining.py  faq_cache.py  stats.py
│       │   ├── llm.py           # LLM / Embedding Provider 抽象
│       │   └── parser/          # pdf.py docx.py md.py txt.py splitter.py
│       └── tasks/               # 后台任务：导入 Worker、沉淀定时任务
├── frontend/
│   ├── package.json  vite.config.ts  .env.development
│   └── src/
│       ├── api/                 # 按模块封装的请求函数
│       ├── router/              # 路由 + 动态菜单/路由守卫
│       ├── stores/              # user / permission / chat (Pinia)
│       ├── directives/          # v-permission 按钮级权限指令
│       ├── components/          # PermissionDialog、StreamMarkdown、CitationCard…
│       ├── views/
│       │   ├── login/  profile/
│       │   ├── org/{users,roles,departments}/
│       │   ├── knowledge/{import,units,unit-detail}/
│       │   ├── ai/ChatWorkbench.vue
│       │   ├── dashboard/Index.vue
│       │   └── settlement/{faqs,published,gaps}/
│       └── styles/
├── deploy/
│   ├── docker-compose.yml       # postgres+pgvector / redis
│   └── README.md                # 一键启动说明
├── docs/
│   ├── DEVELOPMENT.md           # 本文档
│   ├── API.md                   # 接口说明文档（逐步补全）
│   └── DEMO.md                  # 业务演示链路脚本
├── Makefile 或 scripts/dev.ps1  # 常用命令
└── README.md
```

---

## 4. 数据库设计

### 4.1 通用约定

- 主键：`id BIGSERIAL`（或 `BIGINT IDENTITY`）。
- 时间：`TIMESTAMPTZ`，默认 `now()`；`updated_at` 由应用层或触发器更新。
- 枚举字段：用 `VARCHAR + CHECK` 约束（比 PG 原生 enum 更易演进），并在后端用 Python `enum` 映射。
- **软删除**：`knowledge_units` 增加 `deleted_at TIMESTAMPTZ NULL`（需求未列，用于保护 `qa_access_logs`/`faqs` 的外键引用；列表默认过滤）。如不需要可在开工时说明。
- 所有表默认索引：外键列、`created_at`、高频筛选列（见 4.3）。

### 4.2 表结构（在 R-db 基础上的补充说明）

| 表 | 关键约束 / 补充 | 说明 |
|---|---|---|
| `users` | `username UNIQUE`；`status` ∈ {`active`,`disabled`}；`department_id` FK→departments | 密码 bcrypt |
| `departments` | `parent_id` 自引用可空（根节点）；`leader_id` FK→users（可空） | 树形，防环校验 |
| `roles` | `role_code UNIQUE` | 内置：`sys_admin`、`kb_admin`、`normal_user` |
| `user_roles` | `UNIQUE(user_id, role_id)` | |
| `role_permissions` | `UNIQUE(role_id, permission_code)`；`permission_code` 形如 `knowledge:unit:create`；`permission_type` ∈ {`menu`,`button`,`ai`} | 菜单权限写 `permission_type=menu`；`knowledge:ai:access` 为 AI 访问 |
| `knowledge_units` | `unit_code UNIQUE`；`status` ∈ {`parsing`,`active`,`disabled`,`parse_failed`} | 一个导入文档 = 一条单元 |
| `unit_permissions` | `CHECK(target_type IN ('global','department','role','user'))`；`target_type='global'` 时 `target_id=0`；`UNIQUE(unit_id,target_type,target_id)` | OR 逻辑 |
| `qa_access_logs` | 三个 JSON 列用 `JSONB`；`response_time_ms INTEGER`；`session_id` 索引 | 追加写，不更新 |
| `faqs` | `status` ∈ {`pending_review`,`published`,`rejected`}；`source_type` ∈ {`manual`,`auto_mined`} | |
| `knowledge_gaps` | `status` ∈ {`unresolved`,`resolved`,`ignored`}；`sample_questions_json JSONB` | |
| `chat_sessions`（**新增**） | `id`、`user_id`、`title`、`created_at`、`updated_at` | R-be"会话管理"、R-page"历史对话列表"需要持久化会话 |
| `chat_messages`（**新增**） | `id`、`session_id`、`user_id`、`role`(`user`/`assistant`)、`content`、`citations_json`、`missing_unit_ids_json`、`created_at` | 会话历史；`qa_access_logs` 专注统计 |
| `unit_chunks`（**新增**） | `id`、`unit_id`、`chunk_index`、`content`、`token_count`、`embedding vector(512)`、`tsv tsvector` | 单元内切片 + 向量 + 关键词检索 |
| `faq_vectors`（**新增，可选**） | `faq_id`、`embedding vector(512)` | FAQ 语义匹配缓存 |
| `import_jobs`（**新增**） | `id`、`batch_id`、`file_name`、`file_type`、`file_size`、`status`(`pending`/`parsing`/`success`/`failed`)、`unit_id`、`error_message`、`progress`、`creator_id`、`created_at` | 批量导入进度轮询 |

### 4.3 索引清单

```sql
CREATE INDEX idx_users_department ON users(department_id);
CREATE INDEX idx_departments_parent ON departments(parent_id);
CREATE INDEX idx_unit_permissions_unit ON unit_permissions(unit_id);
CREATE INDEX idx_unit_permissions_target ON unit_permissions(target_type, target_id);
CREATE INDEX idx_units_status_created ON knowledge_units(status, created_at DESC);
CREATE INDEX idx_chunks_unit ON unit_chunks(unit_id);
CREATE INDEX idx_chunks_tsv ON unit_chunks USING GIN(tsv);
CREATE INDEX idx_chunks_embedding ON unit_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_logs_user_created ON qa_access_logs(user_id, created_at DESC);
CREATE INDEX idx_logs_created ON qa_access_logs(created_at DESC);
CREATE INDEX idx_faqs_status ON faqs(status);
CREATE INDEX idx_gaps_status ON knowledge_gaps(status, ask_count DESC);
```

### 4.4 初始化脚本要求

`backend/scripts/init_db.sql`：

1. `CREATE DATABASE kb_manager;`
2. `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;`
3. 全部建表 + 索引 + 约束；
4. 内置字典数据：3 个角色、`role_permissions` 全量权限码、根部门；
5. 幂等（`IF NOT EXISTS`），可重复执行。

`alembic` 首次 migration 需与 `init_db.sql` 保持一致（`alembic upgrade head` 与手工执行 SQL 结果等价）。

---

## 5. 权限模型设计

### 5.1 权限码字典

| 权限码 | 类型 | 菜单/操作 | 默认角色 |
|---|---|---|---|
| `dashboard:view` | menu | 数据看板 | sys_admin |
| `org:user:view/create/update/delete/reset_pwd/toggle` | menu/button | 用户管理 | sys_admin |
| `org:role:view/create/update/delete/assign_permission` | menu/button | 角色管理 | sys_admin |
| `org:dept:view/create/update/delete` | menu/button | 部门管理 | sys_admin |
| `knowledge:import:view/create` | menu/button | 知识导入中心 | kb_admin |
| `knowledge:unit:view` | menu | 知识单元列表/详情 | kb_admin（普通用户可选，仅看授权范围内） |
| `knowledge:unit:create/update/delete` | button | 知识单元增删改 | kb_admin |
| `knowledge:permission:update` | button | 配置数据权限 | kb_admin |
| `ai:chat:view` | menu | AI 对话工作台 | 全部角色 |
| `knowledge:ai:access` | ai | 调用 AI 问答接口（后端强制校验） | 全部角色 |
| `settlement:faq:view/review` | menu/button | FAQ 推荐与审核 | kb_admin |
| `settlement:faq:manage` | menu/button | 已发布 FAQ 库 | kb_admin |
| `settlement:gap:view/handle` | menu/button | 知识缺口 | kb_admin |

### 5.2 后端鉴权链

```
请求 → JWT 解析 (401 未登录)
     → 用户状态校验 (disabled → 403)
     → 操作权限校验 require_permission("knowledge:unit:create") (403)
     → 数据权限：
         · 普通查询：SQL 层过滤（见 5.3），无权限单元直接不出现
         · 鉴权接口 check_permissions：返回 authorized / unauthorized 两个列表
```

### 5.3 数据权限计算（`app/services/permission.py`）

输入：`user_id` + 单元 ID 集合；先取用户 `department_id`、`role_ids`。

```sql
-- 可访问单元：全局 或 部门命中 或 角色命中 或 个人命中
SELECT DISTINCT unit_id FROM unit_permissions
WHERE unit_id = ANY(:unit_ids)
  AND ( target_type = 'global'
     OR (target_type = 'department' AND target_id = :dept_id)
     OR (target_type = 'role'       AND target_id = ANY(:role_ids))
     OR (target_type = 'user'       AND target_id = :user_id) );
```

- `authorized_unit_ids` = 上述结果；`unauthorized_unit_ids` = 入参 − authorized。
- **特殊规则（需确认）**：拥有 `knowledge:permission:update` 的知识管理员，是否能查看自己创建但未配置权限的单元？建议：能在管理列表看到全部单元，但 **AI 问答仍按数据权限过滤**（保持"默认无权限"语义）。另建议：`knowledge:unit:update/delete` 的知识管理员可管理全部单元（否则新建单元后无法再配置权限）。
- 单元列表接口（`GET /api/knowledge/units`）默认返回全量（需 `knowledge:unit:view`）；若给普通用户开放该菜单，则只返回 authorized 集合（传 `scope=mine`）。

### 5.4 前端权限控制（R-fe 认证与权限控制模块）

- `login` 响应中的 `permissions` 存入 Pinia；
- 路由 `meta.permissions` + 全局守卫过滤 → 动态菜单（`dynamicRoutes`）；
- `v-permission="'knowledge:unit:delete'"` 指令控制按钮显隐；
- 前端控制只做展示，**后端必须二次校验**。

---

## 6. 核心设计决策

| 决策点 | 方案 | 理由 / 影响 |
|---|---|---|
| 知识单元粒度 | R-rule 明确"一个文档 = 一个单元"。单元下再切 `unit_chunks` 做检索 | 检索命中块 → 映射回单元 → 对**单元**做权限鉴权 → 拼装该单元授权内容 |
| 权限缺失提示范围 | 只要召回的**任意**块所属单元未授权，即在前端提示缺失的单元（标题 + 单元编号）。可选配置 `MISSING_HINT_MODE=unit_title|count_only` 避免泄露敏感标题 | R-rule "明确告知缺失对应知识单元访问权限"；若担心标题泄密可切换为仅数量 |
| 导入解析 | 同步入库 + 后台任务解析（FastAPI `BackgroundTasks` 或独立 `worker` 进程）；前端轮询 `import_jobs` 状态 | 大文件不阻塞请求 |
| 导入状态 | `parsing` 时单元不可被检索；解析+向量化完成后置 `active` | |
| Embedding | 默认本地 `sentence-transformers`（`BAAI/bge-small-zh-v1.5`，512 维），可切远程接口；模型懒加载 | 离线演示；首次启动需下载模型（约 100MB），文档写明 |
| 检索策略 | 关键词（pg_trgm / 全文）+ 向量余弦距离 topK，RRF 融合 → `retrieval_score` | 未配置 LLM 时也能验证检索 |
| 知识缺口判定 | 融合分 < `GAP_SCORE_THRESHOLD`（默认 0.35）或无候选 → 写入 `knowledge_gaps`（按问题向量相似度聚类归并，`ask_count+1`） | R-board |
| FAQ 挖掘 | 定时任务（默认每日 02:00，可手动触发 `POST /api/settlement/mining/run`）扫描近 N 天 `qa_access_logs`，对提问向量聚类（相似度 ≥ 0.9 视为同类），频次 ≥ `FAQ_MINE_THRESHOLD`（默认 3）生成 `pending_review` | R-board |
| FAQ 缓存 | 发布时写入 Redis：`faq:publish:{faq_id}` → 问答对；内存/Redis 缓存 "规范化问题 → faq_id" 倒排；提问先精确匹配（规范化后），再语义匹配（相似度 ≥ 0.92），命中直接流式输出标准答案，跳过 LLM | 命中时仍然记录 `qa_access_logs`（token=0，用于统计 FAQ 命中率） |
| FAQ 缓存失效 | 发布/编辑/下架 FAQ 时刷新；缓存未命中时回源 DB | |
| 流水统计 | `qa_access_logs` 追加写；看板聚合 SQL 直接在日志表上做（按日分组），数据量小时足够；预留 `daily_metrics` 物化视图可选 | |
| UV 口径 | `COUNT(DISTINCT user_id)`；可按日期范围过滤 | |
| 响应时间 | 从收到请求到 SSE `done` 事件的总耗时 | |
| Token 统计 | LLM 返回的 usage；流式时在最后 chunk 获取；如 provider 不返回则用 tiktoken 估算 | |
| SSE 协议 | 见 `docs/API.md` 契约（M6 先定） | 前端解析依赖 |

### 6.1 SSE 事件契约（`POST /api/ai/chat/stream`）

```
event: meta        data: {"session_id":"...","message_id":123,"faq_hit":false}
event: citation    data: {"unit_id":1,"unit_code":"KU-0001","title":"员工报销制度","score":0.83}
event: missing     data: {"unit_ids":[5],"items":[{"unit_id":5,"unit_code":"KU-0005","title":"财务审批权限"}]}
event: delta       data: {"content":"根据《员工报销制度》……"}
event: done        data: {"total_tokens":1234,"prompt_tokens":900,"completion_tokens":334,"response_time_ms":2310}
event: error       data: {"code":"PERMISSION_DENIED","message":"您没有访问知识库的权限"}
```

- 未登录：HTTP 401（不建立流）；无 `knowledge:ai:access`：HTTP 403。
- 命中 FAQ 缓存：`meta.faq_hit=true` + 单个 `delta`（可再切分模拟流式）+ `done`。
- 鉴权必须在**生成回答之前**完成（R-flow 步骤 4–6）。

---

## 7. 开发步骤

> 建议节奏：每个里程碑结束做一次自测 + 演示截图/录屏；`M0` 与 `M1` 必须最先完成，后续里程碑可并行（例如 M5 看板 与 M7 沉淀 可同时推进）。

### M0 基础设施与工程骨架（P0）

| 步骤 | 内容 | 交付物 | 验收点 |
|---|---|---|---|
| M0.S1 | 创建 `deploy/docker-compose.yml`：postgres:16 + pgvector、redis:7；后端 `uv init` + FastAPI 骨架 + `.env.example`；前端 `npm create vite`（Vue3+TS）+ Element Plus + Pinia + Router | 容器可起；`GET /api/health` 返回 ok；前端空白页可访问 | `docker compose up -d`、`uv run uvicorn app.main:app`、`npm run dev` 均成功 |
| M0.S2 | 配置 `config.py`（pydantic-settings）、`db.py`（async session）、`redis.py`；统一异常与响应结构；CORS | 后端项目结构就绪 | Swagger 可打开；DB/Redis 连接 ping 成功 |
| M0.S3 | README：环境要求、启动步骤、目录说明、常见问题 | `README.md` | 新机器按 README 能跑起来 |

### M1 数据库与种子数据（P0）

| 步骤 | 内容 | 交付物 | 验收点 |
|---|---|---|---|
| M1.S1 | 编写 `init_db.sql`（4.2/4.3 全部表与索引、扩展）；Alembic 初始迁移 | `scripts/init_db.sql`、`alembic/versions/0001_init.py` | 两种方式建库结果一致 |
| M1.S2 | SQLAlchemy 全部模型 + Pydantic schema 基础 | `app/models/*`、`app/schemas/*` | `Base.metadata` 与 SQL 对齐 |
| M1.S3 | 种子脚本 `seed.py`：部门树（3 层）、9 个用户（覆盖 3 角色/多部门）、角色权限、6–10 篇示例文档（含 PDF/DOCX/MD/TXT）并直接用解析服务入库 | 可一键初始化的演示数据 | `uv run python scripts/seed.py` 后库里有关键数据 |

### M2 认证与组织架构（P0）

| 步骤 | 内容 | 接口 | 验收点 |
|---|---|---|---|
| M2.S1 | 密码哈希、JWT 签发/校验、`get_current_user`、`require_permission` | `POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout` | 登录返回 `access_token`、`user_info`（含部门、角色）、`permissions`；401/403 行为正确 |
| M2.S2 | 部门树 CRUD | `GET/POST /api/org/departments`、`PUT/DELETE /api/org/departments/{id}` | 树形返回；防环；负责人关联 |
| M2.S3 | 用户 CRUD、重置密码、启停用、角色分配 | `GET/POST /api/org/users`、`PUT /api/org/users/{id}`、`POST .../reset-password`、`POST .../toggle` | 分页+按部门/关键字筛选 |
| M2.S4 | 角色 CRUD、权限树与分配 | `GET/POST /api/org/roles`、`GET /api/org/permissions/tree`、`POST /api/org/roles/{id}/permissions` | 全量替换式分配；登录后 `permissions` 随之变化 |
| M2.S5（前端） | 登录页、个人中心、Layout（侧边动态菜单 + 顶栏）、`v-permission` 指令、路由守卫、axios 拦截器（401 跳登录） | 页面 | 不同角色登录后菜单/按钮不同 |

### M3 知识单元与批量导入（P0）

| 步骤 | 内容 | 接口 | 验收点 |
|---|---|---|---|
| M3.S1 | 解析器抽象：PDF（pypdf）、DOCX（python-docx）、MD、TXT；按标题层级 + 最大长度切片（`splitter.py`） | `app/services/parser/*` | 单测：每种格式能解析出非空文本与 chunk |
| M3.S2 | 上传与导入任务：单文件/多文件 `multipart`；写 `import_jobs`；后台任务解析 → 建 `knowledge_units` + `unit_chunks` → Embedding → 状态变更 | `POST /api/knowledge/import`、`GET /api/knowledge/import/jobs?batch_id=` | 上传 3 个文件后轮询到全部 success，单元出现在列表 |
| M3.S3 | 知识单元查询/详情/更新/批量删除 | `GET /api/knowledge/units`、`GET/PUT /api/knowledge/units/{id}`、`DELETE /api/knowledge/units` | 搜索（标题/分类/状态）+ 分页；更新正文后重新切片与向量化 |
| M3.S4 | 数据权限配置 | `GET /api/knowledge/units/{id}` 含 `permissions[]`；`POST /api/knowledge/units/{id}/permissions` | 混合配置；保存即时生效 |
| M3.S5（前端） | 导入中心（拖拽、多选文件/目录、进度轮询表格）、单元列表（搜索/筛选/分页/批量删除）、单元编辑/详情页、`PermissionDialog`（全局开关 + 部门树多选 + 角色多选 + 人员多选） | 页面 | R-page 知识维护与导入页全部功能可用 |

### M4 数据权限引擎与鉴权接口（P0）

| 步骤 | 内容 | 接口 | 验收点 |
|---|---|---|---|
| M4.S1 | `permission.py`：批量计算 authorized/unauthorized；单元列表数据过滤 | `POST /api/knowledge/check-permissions` | 单测覆盖：仅全局 / 仅部门 / 仅角色 / 仅个人 / 混合 / 无权限 |
| M4.S2 | 权限接口需校验调用方（JWT；`user_id` 必须等于当前用户，或允许 `X-Internal-Service-Token` 内部调用） | 同上 | 越权传他人 `user_id` 被拒绝 |

### M5 检索与 AI 鉴权问答（P0）

| 步骤 | 内容 | 接口 | 验收点 |
|---|---|---|---|
| M5.S1 | Embedding Provider 抽象 + 本地模型实现 + 批量向量化脚本（为种子数据生成向量） | `services/llm.py` | 向量列有值；相似度检索可用 |
| M5.S2 | 混合召回：关键词 + 向量 + RRF；返回 topK chunk 及所属单元 | `services/retrieval.py` | 输入问题返回相关单元 |
| M5.S3 | 会话管理：`chat_sessions` / `chat_messages`，历史列表与消息 | `GET /api/ai/sessions`、`GET /api/ai/sessions/{id}/messages`、`DELETE /api/ai/sessions/{id}` | 多轮上下文可用 |
| M5.S4 | 鉴权问答主链路：登录校验 → FAQ 缓存匹配（M7 完成前留空 hook）→ 召回 → 调权限引擎 → 组装 Prompt → LLM 流式 → SSE 事件 → 缺失提示 → 异步写 `qa_access_logs` | `POST /api/ai/chat/stream` | 未登录 401；无 AI 权限 403；有权用户回答正确；存在未授权召回时收到 `missing` 事件 |
| M5.S5（前端） | AI 工作台：会话列表、输入框、流式 Markdown 渲染、引用卡片、缺失提示卡片、停止生成、复制 | `views/ai/ChatWorkbench.vue` | 演示"普通用户看不到财务制度单元并收到提示" |

### M6 数据看板（P1）

| 步骤 | 内容 | 接口 | 验收点 |
|---|---|---|---|
| M6.S1 | 统计服务：指标聚合（次数、UV、单元数、Token、平均耗时） | `GET /api/dashboard/metrics` | 数字与日志一致 |
| M6.S2 | 排行榜：常见问题 TOP（提问文本规范化后分组）、最常访问单元 TOP（展开 `recalled_unit_ids_json`） | `GET /api/dashboard/rankings/questions`、`/api/dashboard/rankings/units` | 支持 `top` / 时间范围参数 |
| M6.S3 | 趋势：按日/周 Token、响应时间均值/P50/P95、访问量 | `GET /api/dashboard/stats/tokens`、`GET /api/dashboard/stats/trend`、`/api/dashboard/stats/response-time` | 返回时间序列 |
| M6.S4（前端） | 看板页：指标卡、两个排行榜、折线/柱状图（ECharts）、时间范围切换 | `views/dashboard/Index.vue` | R-page 数据看板页全部图表渲染 |

### M7 知识沉淀与 FAQ 缓存（P1）

| 步骤 | 内容 | 接口 | 验收点 |
|---|---|---|---|
| M7.S1 | 缺口识别：问答时融合分低于阈值 → 聚类归并写 `knowledge_gaps` | 内部逻辑；`GET /api/settlement/knowledge-gaps` | 提一个库外问题后缺口列表出现且频次+1 |
| M7.S2 | FAQ 挖掘：定时任务 + 手动触发，聚类聚合高频问题 → `pending_review` | `GET /api/settlement/faqs/recommendations`、`POST /api/settlement/mining/run` | 同一问题问 3 次后推荐出现 |
| M7.S3 | 审核流转：approve（可编辑答案）/ reject；approve → `published` + 写缓存 | `POST /api/settlement/faqs/{id}/review` | 状态流转正确；缓存 key 生成 |
| M7.S4 | FAQ 缓存服务：精确匹配 + 语义匹配；接入 M5 主链路，命中时绕过 LLM | 内部逻辑 | 再问同样问题 → `faq_hit=true`、耗时显著下降、`hit_count+1` |
| M7.S5 | 已发布 FAQ 库管理：列表、编辑、下架 | `GET /api/settlement/faqs?status=published`、`PUT /api/settlement/faqs/{id}` | 下架后不再命中缓存 |
| M7.S6（前端） | 沉淀页 3 个 Tab：推荐审核（编辑答案弹窗）、已发布库（缓存状态标识）、知识缺口（频次、样例问题、一键创建单元） | 页面 | "一键创建单元"跳转单元编辑页并预填问题 |

### M8 完善、测试与交付（P0，收尾）

| 步骤 | 内容 | 交付物 | 验收点 |
|---|---|---|---|
| M8.S1 | 后端接口单测/集成测试（认证、权限引擎、导入解析、检索） | `backend/tests/*` | `uv run pytest` 全绿 |
| M8.S2 | 前端构建 + 后端生产启动方式；演示账号与数据说明 | `deploy/README.md` | `npm run build` 通过 |
| M8.S3 | `docs/API.md` 完整化（字段、示例、错误码） | `docs/API.md` | 覆盖 R-api 全部接口 |
| M8.S4 | `docs/DEMO.md`：R-flow 三条核心流程的可复现演示脚本（账号 → 操作步骤 → 预期结果） | `docs/DEMO.md` | 按脚本走一遍全部成功 |
| M8.S5 | 对照 R-accept 逐条验收，形成验收记录表 | 验收记录 | 8 条全部通过 |

### 里程碑汇总

| 里程碑 | 需求覆盖 | 优先级 | 预估工作量（人日，参考） |
|---|---|---|---|
| M0 | 交付形式（可运行） | P0 | 0.5 |
| M1 | R-db、示例数据 | P0 | 0.5 |
| M2 | R-role、R-page 登录与组织架构、R-api 认证/组织 | P0 | 2 |
| M3 | R-page 知识维护、R-api 知识 CRUD/导入 | P0 | 3 |
| M4 | R-rule 数据权限、R-api check-permissions | P0 | 1 |
| M5 | R-page/flow AI 鉴权问答、R-be AI 服务 | P0 | 3 |
| M6 | R-page 看板、R-board 聚合规则 | P1 | 2 |
| M7 | R-page 沉淀、R-board 挖掘规则 | P1 | 3 |
| M8 | R-accept 全部 | P0 | 1.5 |

---

## 8. 接口清单（以 R-api 为基线 + 必要补充）

| 方法 | 路径 | 权限 | 所属步骤 |
|---|---|---|---|
| POST | `/api/auth/login` | 公开 | M2.S1 |
| GET | `/api/auth/me` | 登录 | M2.S1 |
| POST | `/api/auth/logout` | 登录 | M2.S1 |
| GET | `/api/org/departments` | `org:dept:view` | M2.S2 |
| POST | `/api/org/departments` | `org:dept:create` | M2.S2 |
| PUT | `/api/org/departments/{id}` | `org:dept:update` | M2.S2 |
| DELETE | `/api/org/departments/{id}` | `org:dept:delete` | M2.S2 |
| GET | `/api/org/users` | `org:user:view` | M2.S3 |
| POST | `/api/org/users` | `org:user:create` | M2.S3 |
| PUT | `/api/org/users/{id}` | `org:user:update` | M2.S3 |
| POST | `/api/org/users/{id}/reset-password` | `org:user:reset_pwd` | M2.S3 |
| POST | `/api/org/users/{id}/toggle` | `org:user:toggle` | M2.S3 |
| GET | `/api/org/roles` | `org:role:view` | M2.S4 |
| POST | `/api/org/roles` / PUT / DELETE `/api/org/roles/{id}` | `org:role:create/update/delete` | M2.S4 |
| GET | `/api/org/permissions/tree` | `org:role:view` | M2.S4 |
| POST | `/api/org/roles/{id}/permissions` | `org:role:assign_permission` | M2.S4 |
| POST | `/api/knowledge/import` | `knowledge:import:create` | M3.S2 |
| GET | `/api/knowledge/import/jobs` | `knowledge:import:view` | M3.S2 |
| GET | `/api/knowledge/units` | `knowledge:unit:view` | M3.S3 |
| GET | `/api/knowledge/units/{id}` | `knowledge:unit:view` | M3.S3 |
| PUT | `/api/knowledge/units/{id}` | `knowledge:unit:update` | M3.S3 |
| DELETE | `/api/knowledge/units` | `knowledge:unit:delete` | M3.S3 |
| POST | `/api/knowledge/units/{id}/permissions` | `knowledge:permission:update` | M3.S4 |
| POST | `/api/knowledge/check-permissions` | 登录 | M4.S1 |
| GET | `/api/ai/sessions` / GET `/api/ai/sessions/{id}/messages` / DELETE `/api/ai/sessions/{id}` | `ai:chat:view` | M5.S3 |
| POST | `/api/ai/chat/stream` | `knowledge:ai:access` | M5.S4 |
| GET | `/api/dashboard/metrics` | `dashboard:view` | M6.S1 |
| GET | `/api/dashboard/rankings/questions` | `dashboard:view` | M6.S2 |
| GET | `/api/dashboard/rankings/units` | `dashboard:view` | M6.S2 |
| GET | `/api/dashboard/stats/tokens` | `dashboard:view` | M6.S3 |
| GET | `/api/dashboard/stats/trend` / `/api/dashboard/stats/response-time` | `dashboard:view` | M6.S3 |
| GET | `/api/settlement/faqs/recommendations` | `settlement:faq:view` | M7.S2 |
| POST | `/api/settlement/faqs/{id}/review` | `settlement:faq:review` | M7.S3 |
| GET | `/api/settlement/faqs` / PUT `/api/settlement/faqs/{id}` | `settlement:faq:manage` | M7.S5 |
| GET | `/api/settlement/knowledge-gaps` / PUT `/api/settlement/knowledge-gaps/{id}` | `settlement:gap:view/handle` | M7.S1 |
| POST | `/api/settlement/mining/run` | `settlement:faq:review` | M7.S2 |

**统一约定**

- 认证：`Authorization: Bearer <token>`。
- 分页：`page`（默认 1）、`page_size`（默认 20，最大 100）；响应 `{ items, total, page, page_size }`。
- 错误：`{ code, message, detail? }`；业务错误码如 `AUTH_REQUIRED`、`PERMISSION_DENIED`、`VALIDATION_ERROR`、`NOT_FOUND`、`LLM_UNAVAILABLE`。
- 时间：ISO 8601（含时区）。

---

## 9. 前端路由与页面

| 路由 | 页面 | 权限 |
|---|---|---|
| `/login` | 登录 | 公开 |
| `/profile` | 个人中心 | 登录 |
| `/dashboard` | 数据看板 | `dashboard:view` |
| `/org/users`、`/org/roles`、`/org/departments` | 组织架构管理 | `org:user:view` 等 |
| `/knowledge/import` | 知识导入中心 | `knowledge:import:view` |
| `/knowledge/units`、`/knowledge/units/:id` | 单元列表 / 编辑详情 | `knowledge:unit:view` |
| `/ai/chat` | AI 对话鉴权工作台 | `ai:chat:view` |
| `/settlement/faqs`、`/settlement/published`、`/settlement/gaps` | 知识沉淀 | `settlement:*:view` |

**关键组件**

- `PermissionDialog.vue`：全局开关、部门树（`el-tree` check）、角色多选、人员多选（远程搜索）；显示当前已配置摘要。
- `StreamMarkdown.vue`：增量 Markdown 渲染（marked / markdown-it）+ 代码高亮。
- `CitationCard.vue`：引用来源卡片（单元编号、标题、相似度）。
- `MissingPermissionCard.vue`：权限缺失提示卡片。
- `ImportProgressTable.vue`：按 `batch_id` 轮询（2s）。

---

## 10. 环境变量（`.env.example`）

```ini
# --- 基础 ---
APP_ENV=dev
API_HOST=0.0.0.0
API_PORT=8000
FRONTEND_ORIGINS=http://localhost:5173

# --- 数据库 / 缓存 ---
DATABASE_URL=postgresql+psycopg://kb:kb@127.0.0.1:5432/kb_manager
REDIS_URL=redis://127.0.0.1:6379/0

# --- 认证 ---
JWT_SECRET=change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=720
INTERNAL_SERVICE_TOKEN=kb-internal-token

# --- LLM / Embedding ---
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=60
EMBEDDING_PROVIDER=local          # local | openai_compatible
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIM=512

# --- 检索 / 沉淀规则 ---
RETRIEVAL_TOP_K=6
RRF_K=60
GAP_SCORE_THRESHOLD=0.35
FAQ_SIMILARITY_THRESHOLD=0.92
FAQ_MINE_THRESHOLD=3
FAQ_MINE_LOOKBACK_DAYS=30
MINING_CRON=0 2 * * *
MISSING_HINT_MODE=unit_title      # unit_title | count_only
```

---

## 11. 演示账号与数据（建议）

| 账号 | 密码 | 部门 | 角色 | 用途 |
|---|---|---|---|---|
| admin | Admin@123 | 总公司 / 技术中心 | 系统管理员 | 组织与权限管理 |
| kbadmin | Admin@123 | 总公司 / 行政中心 | 知识管理员 | 导入、权限配置、FAQ 审核 |
| user_tech | Admin@123 | 总公司 / 技术中心 | 普通用户 | 能看到技术类单元 |
| user_fin | Admin@123 | 总公司 / 财务中心 | 普通用户 | 演示看不到技术类单元并出现缺失提示 |
| user_vp | Admin@123 | 总公司 | 高管角色 | 演示角色维度权限 |

**示例知识文档（`seed_docs/`）**

1. `员工报销制度.docx` → 权限：全局
2. `IT 安全规范.pdf` → 权限：部门=技术中心
3. `财务审批权限手册.pdf` → 权限：部门=财务中心、角色=高管
4. `新员工入职指南.md` → 权限：全局
5. `数据合规红线.md` → 权限：角色=知识管理员
6. `差旅标准说明.txt` → 权限：个人=user_tech
7. `无权限配置的测试文档.txt` → 权限：无（验证默认无权限 + 缺失提示）
8. `年假计算规则.docx` → 权限：部门=行政中心

---

## 12. 测试与验收

### 12.1 自动化测试清单

| 类型 | 用例 | 对应步骤 |
|---|---|---|
| 单测 | 权限引擎 6 种组合矩阵 | M4 |
| 单测 | 文档解析（4 种格式）+ 切片边界 | M3.S1 |
| 单测 | FAQ 匹配（精确/语义/未命中） | M7.S4 |
| 集成 | 登录→导入→配权→问答→日志写入 | M3–M5 |
| 集成 | 无权限用户问答返回 `missing` 且 Prompt 不含未授权正文 | M5 |
| 集成 | 看板数字与日志一致 | M6 |

### 12.2 验收对照（R-accept）

| # | 验收标准 | 验证方式 | 覆盖步骤 |
|---|---|---|---|
| 1 | 用户登录、角色管理、部门管理、菜单/按钮权限分配 | 不同账号登录对比菜单/按钮 | M2 |
| 2 | 单篇与批量导入，拆分为单元并完成检索入库 | 导入中心上传，解析完成后提问命中 | M3 |
| 3 | 单元增删改查 + 四类权限混合配置 | 单元详情页配置并保存 | M3/M4 |
| 4 | 满足任一权限实体即可访问 | 5 个账号分别访问 8 篇文档矩阵 | M4 |
| 5 | AI 强制登录 + 鉴权过滤 + 缺失提示 | user_fin 提问技术问题 | M5 |
| 6 | 看板指标与排行、趋势正确 | 对照 DB 日志核对 | M6 |
| 7 | 高频问题自动推荐 + 审核发布 + 缓存加速 | 同一问题问 3 次 → 挖掘 → 发布 → 再问 | M7 |
| 8 | 知识缺口识别与频次统计 | 问库外问题 → 缺口列表 | M7 |

---

## 13. 风险与待确认事项

| # | 事项 | 默认方案 | 需你确认 |
|---|---|---|---|
| 1 | 后端技术栈 | Python FastAPI（与你现有项目一致） | 是否改用 Java/Spring Boot |
| 2 | LLM 与 Embedding 来源 | OpenAI 兼容接口 + 本地 bge-small-zh | 是否有可用 Key / 指定模型 |
| 3 | 权限缺失提示是否暴露单元标题 | 暴露标题（`unit_title`），可配置 | 是否需要隐藏标题 |
| 4 | 知识管理员是否可管理全部单元 | 可管理全部（AI 问答仍按数据权限） | — |
| 5 | 新增 4 张辅助表（会话、消息、切片、导入任务） | 需求表之外的合理补充 | 是否允许扩充 |
| 6 | 导入解析方式 | 后台任务 + 轮询 | 是否要求独立 Celery Worker |
| 7 | 示例文档是否真实业务数据 | 自行编写的脱敏假数据 | 你提供真实文档 |

---

## 附：建议执行顺序（给"分步骤让我完成"用）

```
M0 → M1 → M2 → M3 → M4 → M5 →（M6 与 M7 可并行）→ M8
```

每一步开始时，你只需说：**"开始 M{n}.S{m}"**。
我会：① 阅读本文档的对应步骤与验收点；② 实现代码；③ 自测并汇报结果；④ 在 `docs/PROGRESS.md` 中勾选完成项。
