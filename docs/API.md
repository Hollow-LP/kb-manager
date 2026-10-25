# 接口文档

Base URL：`http://127.0.0.1:8000/api`（开发环境经前端代理为 `http://127.0.0.1:5173/api`）
在线 Swagger：`/api/docs`

## 通用约定

- 认证：`Authorization: Bearer <access_token>`（除登录外全部需要）
- 分页：`page`（默认 1）、`page_size`（默认 20，最大 100），响应 `{ items, total, page, page_size }`
- 错误体：`{ "code": "...", "message": "...", "detail": ... }`

| code | HTTP | 场景 |
|---|---|---|
| `AUTH_REQUIRED` | 401 | 未携带/无效 token |
| `TOKEN_INVALID` | 401 | token 解析失败或过期 |
| `INVALID_CREDENTIALS` | 401 | 用户名或密码错误 |
| `ACCOUNT_DISABLED` | 403 | 账号停用 |
| `PERMISSION_DENIED` | 403 | 缺少操作权限 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `VALIDATION_ERROR` | 422 | 参数校验失败 |
| `PARSE_FAILED` | 422 | 文档解析失败（M3） |
| `INTERNAL_ERROR` | 500 | 未捕获异常 |

## 系统

### GET /health
健康检查：`{ "status": "ok", "checks": { "database": "ok", "redis": "ok" } }`

## 认证（M2 ✅）

### POST /auth/login
请求：`{ "username": "admin", "password": "Admin@123" }`
响应：
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 43200,
  "user_info": {
    "id": 1, "username": "admin", "display_name": "系统管理员",
    "department_id": 2, "department": { "id": 2, "name": "技术中心", "parent_id": 1 },
    "roles": [{ "id": 1, "role_name": "系统管理员", "role_code": "sys_admin" }],
    "status": "active"
  },
  "permissions": ["ai:chat:view", "dashboard:view", "..."]
}
```

### GET /auth/me
响应：`{ "user_info": { ... }, "permissions": [...] }`

### POST /auth/logout
`{ "ok": true }`（JWT 无状态，前端清除 token）

## 组织架构（M2 ✅）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/org/departments` | 登录 | 部门树，节点含 `leader_name`、`member_count`、`children` |
| POST | `/org/departments` | `org:dept:create` | 请求 `{name, parent_id, leader_id, sort_order}` |
| PUT | `/org/departments/{id}` | `org:dept:update` | 不能设为自己的下级 |
| DELETE | `/org/departments/{id}` | `org:dept:delete` | 有子部门或成员时拒绝 |
| GET | `/org/users` | `org:user:view` | 参数 `page,page_size,keyword,department_id,status`；部门过滤含下级 |
| POST | `/org/users` | `org:user:create` | `{username,password,display_name,department_id,role_ids,status}` |
| PUT | `/org/users/{id}` | `org:user:update` | `role_ids` 存在时整体替换角色 |
| POST | `/org/users/{id}/reset-password` | `org:user:reset_pwd` | `{password}` |
| POST | `/org/users/{id}/toggle` | `org:user:toggle` | 启用/停用切换，不能停用自己 |
| DELETE | `/org/users/{id}` | `org:user:delete` | 不能删除自己 |
| GET | `/org/roles` | 登录 | 角色列表含 `permission_codes`、`user_count`、`is_builtin` |
| POST | `/org/roles` | `org:role:create` | `{role_name,role_code,description}` |
| PUT | `/org/roles/{id}` | `org:role:update` | |
| DELETE | `/org/roles/{id}` | `org:role:delete` | 内置角色/仍有用户时拒绝 |
| GET | `/org/permissions/tree` | 登录 | 权限树：`[{key:"group:org",label,type,children:[...]}]` |
| POST | `/org/roles/{id}/permissions` | `org:role:assign_permission` | `{permission_codes:[...]}` 全量替换；系统管理员不可改 |

## 知识管理（M3 ✅）

### 导入
| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/knowledge/import` | `knowledge:import:create` | multipart，字段名 `files`，可多个；PDF/DOCX/MD/TXT，单文件 ≤ `UPLOAD_MAX_SIZE_MB`。返回 `{batch_id, jobs[]}` |
| GET | `/knowledge/import/jobs?batch_id=` | `knowledge:import:view` | 轮询进度；`status`: pending/parsing/embedding/success/failed |
| POST | `/knowledge/import/jobs/{id}/retry` | `knowledge:import:create` | 仅失败任务可重试 |

### 单元
| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/knowledge/units` | `knowledge:unit:view` | `page,page_size,keyword,category,status,file_type,creator_id,include_deleted` |
| GET | `/knowledge/units/categories` | 同上 | 已有分类 |
| POST | `/knowledge/units` | `knowledge:unit:create` | 手动创建 `{title,content,summary,category,tags}`，同步切片+向量化 |
| GET | `/knowledge/units/{id}` | `knowledge:unit:view` | 详情含 `content` 与 `permissions[]` |
| PUT | `/knowledge/units/{id}` | `knowledge:unit:update` | 正文变更时重建切片与向量（期间 status=parsing） |
| DELETE | `/knowledge/units` | `knowledge:unit:delete` | body `{unit_ids}` 软删除；返回 deleted/blocked(已发布FAQ关联)/not_found |
| DELETE | `/knowledge/units/{id}` | 同上 | 单删 |
| POST | `/knowledge/units/restore` | `knowledge:unit:delete` | body `{unit_ids}` 恢复 |
| POST | `/knowledge/units/{id}/permissions` | `knowledge:permission:update` | body `{targets:[{target_type,target_id}]}` 全量替换 |

### 鉴权
`POST /knowledge/check-permissions` body `{user_id, unit_ids}` → `{authorized_unit_ids, unauthorized_unit_ids}`
普通用户只能查自己；携带 `X-Internal-Service-Token`（仍需有效 JWT）可代查。

### 权限配置选项（供权限弹窗使用）
`GET /org/options/departments | /org/options/roles | /org/options/users?keyword=`，
持有 `knowledge:permission:update` / `knowledge:import:create` / `knowledge:unit:view` 任一即可。
## 数据权限（M4 ✅）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/knowledge/units?scope=all\|mine` | `all`=全部单元（需任一维护权限，普通用户请求会被强制降级为 `mine`）；`mine`=仅当前用户有数据权限的单元 |
| GET | `/knowledge/units/{id}` | 普通用户需有该单元数据权限（403 `UNIT_FORBIDDEN`）；持维护权限者可查看任意单元 |
| GET | `/knowledge/accessible-units[?user_id=]` | 当前用户可访问单元 ID 全集；带 `X-Internal-Service-Token` 可代查他人 |
| POST | `/knowledge/check-permissions` | 兼容接口，返回 authorized / unauthorized；只能查自己，内部令牌可代查 |

规则：单元未配置权限 → 无人可访问；配置后按 全局 / 部门 / 角色 / 个人 OR 命中；部门权限**不向子部门继承**；
普通用户角色默认包含 `knowledge:unit:view`（列表按数据权限过滤）。

## AI 问答（M5 ✅）

模型：OpenAI 兼容接口（当前配置 SiliconFlow `XingChenAGI/Xing4.0-29B`），`.env` 中 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`；
`LLM_ENABLE_THINKING=false` 关闭思考过程（该模型开启思考时响应约慢 5~8 倍）。未配置时问答接口返回 503 `LLM_UNAVAILABLE`。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/ai/chat/stream` | `knowledge:ai:access` | body `{question, session_id?}`，返回 SSE |
| GET | `/ai/sessions` | 登录 | 我的会话（含消息数） |
| GET | `/ai/sessions/{id}/messages` | 会话所有者 | 历史消息（含引用、缺失单元、status） |
| DELETE | `/ai/sessions/{id}` | 会话所有者 | 软删除会话 |

### SSE 事件

```
event: meta      data: {"session_id":12,"message_id":101,"faq_hit":false}
event: citation  data: {"unit_id":7,"unit_code":"KU-0006","title":"差旅标准说明","score":0.711,"snippets":[...]}
event: missing   data: {"unit_ids":[4],"items":[{"unit_id":4,"unit_code":"KU-0003","title":"财务审批权限手册"}],
                        "message":"根据您的数据权限，以下 1 个检索召回的知识单元您无权访问…"}
event: delta     data: {"content":"根据"}
event: done      data: {"session_id":12,"message_id":103,"prompt_tokens":812,"completion_tokens":95,
                        "total_tokens":907,"response_time_ms":2300,"finish_reason":"stop"}
event: error     data: {"code":"LLM_UNAVAILABLE","message":"回答生成失败：…"}
```

处理顺序固定：`meta → citation* → missing? → delta* → done`（或 `error`）。未登录 401，无 AI 权限 403。

### 问答链路（鉴权优先）

1. 检索召回（向量 cosine + 关键词）→ **qwen3-rerank 重排**（配置 `RERANK_BASE_URL` 时）→ 单元级置信度
   - 重排文本 = `《单元标题》+ 最佳片段`；接口：`POST {RERANK_BASE_URL}/services/rerank/text-rerank/text-rerank`
     ，body `{"model","input":{"query","documents"},"parameters":{"return_documents":false}}`
   - 重排后低于 `RERANK_MIN_SCORE` 的已授权单元不进入 Prompt，也不计入权限缺失
2. 数据权限引擎过滤：**只有授权单元的片段进入 Prompt**；未授权单元通过 `missing` 事件提示（`MISSING_HINT_MODE=unit_title|count_only`）
3. 流式生成 → 保存助手消息（`status=done/failed`）→ 写 `qa_access_logs`（Token、耗时、命中/未授权单元、`gap_flag`）

## 数据看板（M6 ✅）

权限：`dashboard:view`。公共参数 `days`（默认 30，1~365，按北京时间自然日）；趋势类另有 `granularity=day|week`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/dashboard/metrics` | 访问次数、UV、生效单元数、Token 总量、平均耗时、FAQ 命中、缺口数 |
| GET | `/dashboard/rankings/questions?top=10` | 常见问题 TOP（问句规范化后聚合，附变体数与平均 Token） |
| GET | `/dashboard/rankings/units?top=10` | 知识单元热度 TOP：`hit_count` 用于回答次数、`recalled_count` 召回次数、`denied_count` 因权限被拦截次数 |
| GET | `/dashboard/stats/trend` | 访问趋势：次数 / UV / Token / 平均耗时 / FAQ 命中（缺失日期补 0） |
| GET | `/dashboard/stats/tokens` | Token 趋势：prompt / completion / total 拆分 |
| GET | `/dashboard/stats/response-time` | 响应时间直方图（8 个区间）+ P50 / P95 / 平均值 / 样本数 |
| GET | `/dashboard/stats/heatmap` | 访问热力（星期 × 小时） |
| GET | `/dashboard/overview` | 一次性聚合上面的指标、榜单、趋势、Token、响应时间（前端看板使用） |

数据来源 `qa_access_logs`；Token 口径受数据库约束 `total_tokens = prompt_tokens + completion_tokens` 保护。
## 知识沉淀（M7 ✅）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/settlement/faqs/recommendations` | `settlement:faq:view` | 待审核推荐（自动挖掘生成），含频次、关联单元、建议答案 |
| GET | `/settlement/faqs?status=&keyword=` | `settlement:faq:view` + `settlement:faq:manage` | FAQ 列表（按状态 / 关键字 / 来源） |
| POST | `/settlement/faqs` | `settlement:faq:manage` | 手工新建（`publish=true` 直接发布） |
| PUT | `/settlement/faqs/{id}` | `settlement:faq:manage` | 编辑（已发布时同步刷新缓存；改问题会重建向量） |
| POST | `/settlement/faqs/{id}/review` | `settlement:faq:review` | `{action: approve\|reject, edited_answer?, note?}`；通过即发布并写缓存 |
| POST | `/settlement/faqs/{id}/unpublish` | `settlement:faq:manage` | 下架并移出缓存 |
| GET | `/settlement/faqs/cache-stats` | `settlement:faq:manage` | 缓存条数与 Redis 状态 |
| GET | `/settlement/knowledge-gaps?status=unresolved` | `settlement:gap:view` | 知识缺口（按频次），含样例问题、最近提问时间 |
| PUT | `/settlement/knowledge-gaps/{id}?status=` | `settlement:gap:handle` | 标记 resolved / ignored / unresolved |
| POST | `/settlement/knowledge-gaps/{id}/create-unit` | `settlement:gap:handle` | 一键建档：`{title, content, category?}`，创建单元并把缺口置为已解决 |
| POST | `/settlement/mining/run?days=` | `settlement:faq:review` | 立即执行挖掘；返回 faq / gap 统计 |
| GET | `/settlement/mining/status` | `settlement:faq:view` | 定时任务状态与下次运行时间 |

### 规则

- **FAQ 挖掘**：扫描近 `FAQ_MINE_LOOKBACK_DAYS` 天问答日志（排除 FAQ 缓存命中、权限拦截、以及回答为"知识库中未找到"的库外问题），
  按问题向量聚类（`FAQ_MINE_SIMILARITY`），频次 ≥ `FAQ_MINE_THRESHOLD` 生成候选；与已发布/待审 FAQ 语义重复的跳过。
- **缓存加速**：发布时写 Redis（规范化问题 → FAQ）及问题向量；用户提问经规范化后**完全一致**时直接返回标准答案，
  `meta.faq_hit=true`、`done.total_tokens=0`；不命中则走正常检索链路（不因未命中而跳过知识库查询）。
- **知识缺口**：`gap_flag` 的提问按向量聚类归并，累加 `ask_count`、合并样例问题；挖掘后清零 `gap_flag` 避免重复累加。
- **定时**：`MINING_CRON`（默认每日 02:00，服务本地时区），`MINING_ENABLED=true` 开关。
