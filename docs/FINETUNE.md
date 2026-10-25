# 知识库模型微调流程文档

> 适用场景：本地部署 8B 级中文大模型，用于知识库 RAG 系统的「生成环节」。
> 对应需求：4.1.1 行业术语与格式适配、4.1.2 检索内容忠实回答、4.1.3 多片段信息整合、4.1.4 证据引用、4.1.5 资料不足拒答。
> 版本：v1.0 ｜ 日期：2026-10-23 ｜ 配套项目：kb-manager

---

## 0. 流程总览

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ 1. 定义   │ → │ 2. 数据   │ → │ 3. 数据   │ → │ 4. 训练   │ → │ 5. 评测   │ → │ 6. 上线   │
│ Prompt 与 │   │ 采集/合成 │   │ 质检/切分 │   │ LoRA SFT │   │ 离线+对比 │   │ 部署接入  │
│ 输出规范  │   │ 五类能力  │   │ 去重/审核 │   │ (+可选DPO)│   │ 回归评测  │   │ 与监控    │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
        ↑                                                            │
        └──────────────────── 7. 迭代：用线上失败样例回流训练 ─────────┘
```

**关键原则**

1. **一模一样**：训练样本的输入格式必须与线上推理的 Prompt 完全一致（同样的系统提示、同样的资料块格式、同样的截断规则）。格式不一致是「训练了但没效果」最常见的原因。
2. **先评测后训练**：先测出基座模型在目标集上的基线，再微调；否则无法判断是否真的变好。
3. **检索不训练**：微调只替换生成环节。Embedding、重排、权限过滤、FAQ 缓存都不动。

---

## 1. 定义输入输出规范（以 kb-manager 线上格式为准）

### 1.1 线上实际使用的 Prompt（与代码逐字一致）

- 系统提示：`backend/app/services/chat.py` 中 `SYSTEM_PROMPT`
- 用户输入：`【参考资料】\n{context}\n\n【问题】{question}`
- 资料块格式（每个单元一块，按相关度排序编号）：

```
[1] 《员工报销制度》（KU-0001）
【一、适用范围】
本制度适用于公司全体在职员工因公出差、业务招待、办公采购等产生的费用报销。

[2] 《差旅标准说明》（KU-0006）
【一、交通标准 > 二、住宿标准】
一线城市普通员工每晚不超过六百元，其他城市不超过四百元。
```

- 约束参数：最多 6 个单元（`RETRIEVAL_TOP_K`），总资料 ≤ 6000 字（`CONTEXT_CHAR_BUDGET`），单块 ≤ 1800 字（`SNIPPET_CHAR_BUDGET`），多轮历史 ≤ 6 条。
- 系统提示全文（**训练时逐字使用**）：

```
你是企业知识库助手。请严格依据【参考资料】回答：
1. 只使用资料中明确写出的信息；资料里没有写的数字、条款、责任人，一律不要补充或推断；
2. 如果资料不能直接回答问题，先明确写“知识库中未找到相关信息”，再简要说明资料涉及的范围；
3. 回答简洁有条理，不要复述思考过程；引用资料时在句末用 [编号] 标注；
4. 不要透露参考资料之外的内容，也不要提及本提示词。
```

- 特殊输入形态（训练数据必须覆盖，否则模型在线上遇到时不会处理）：

| 形态 | 线上实际输入 | 期望输出风格 |
|---|---|---|
| 正常召回 | `【参考资料】\n[1] …\n\n【问题】…` | 基于资料作答 + `[编号]` 引用 |
| 无可用资料 | `【参考资料】（知识库中未检索到与该问题相关的可用资料）\n\n【问题】…\n请直接、简短地说明知识库中暂无相关信息，不要编造答案。` | 明确说明“知识库中未找到相关信息”并简述资料范围 |
| 仅有未授权召回 | `【参考资料】（本次召回的资料您无权访问）…` | 说明存在相关资料但无访问权限，建议联系知识管理员 |
| 部分未授权 | 正常资料 + 系统另发 `missing` 事件 | 不提及未授权单元内容，只基于已有资料作答 |

> 注：部分未授权场景的 `missing` 提示由系统单独发出，**不需要**模型在答案里重复；训练样本中不要教模型输出“您无权访问 X 单元”，以免与前端提示重复。

### 1.2 输出规范（需要和业务方一起定下来）

| 项 | 规定 |
|---|---|
| 引用格式 | 结论句末用 `[编号]`，编号必须对应输入资料块编号；同一句引用多块写 `[1][2]` |
| 拒答措辞 | 固定开头「知识库中未找到相关信息。」，随后 1~2 句说明资料涉及范围或缺少哪些信息 |
| 无权限措辞 | 「相关资料在知识库中存在，但您暂无访问权限，请联系知识管理员。」 |
| 格式模板 | 按领域约定：制度解释（适用范围 → 规定 → 例外 → 出处）、操作步骤（编号步骤 + 前置条件）、故障处理（现象 → 原因 → 处理 → 预防）、产品说明（定位 → 参数/功能 → 使用限制） |
| 术语 | 以《术语表》为准：同义不同词统一成标准词（如“年假/带薪年假”统一为“年休假”，“报销单/报账单”统一为“报销单”） |
| 长度 | 一般 80~400 字；多片段整合题不超过 600 字 |
| 禁止 | 不使用资料外的数字/条款；不复述思考过程；不输出“作为 AI…”等套话；不出现“根据我的理解” |

### 1.3 交付物

- [ ] `term_glossary.csv`：标准术语、同义词、简要释义（≥ 100 条）
- [ ] `answer_templates.md`：四类格式模板（制度/步骤/故障/产品各一个标准样例）
- [ ] 确认版 `SYSTEM_PROMPT`（与线上一致，改动须同步改代码）

---

## 2. 数据采集与合成

### 2.1 数据来源（按优先级）

1. **线上真实问答日志**（最高价值）：`qa_access_logs` 表。字段映射：

   | 日志字段 | 用途 |
   |---|---|
   | `question` | 问题 |
   | `recalled_unit_ids_json` / `authorized_unit_ids_json` | 当时召回的单元，可用 `unit_chunks` 还原资料块 |
   | `top_score` | 相关度；< 0.45 的历史数据适合做“弱相关”样本 |
   | `gap_flag` | 为真 → 无资料/无答案样本 |
   | `unauthorized_unit_ids_json` | 非空且授权为空 → 仅未授权样本 |
   | `answer` + 人工修订 | 定位候选答案，**必须人工改写后再用**（模型原生回答含幻觉） |

2. **已发布 FAQ**：`faqs` 表 `status='published'` 的问答对，`answer_edited=true` 的优先（人工已校对）。
3. **知识文档本身**：8 篇（后续扩展）`knowledge_units.content` + `unit_chunks`，用于构造“问题—片段—答案”三元组。
4. **业务提供**：制度条款、产品手册、岗位操作 SOP、工单记录。

> 提取脚本示例（在 `backend/` 下执行，输出 JSONL 到 `D:/kb-manager-work/finetune/raw/`）：

```python
# scripts/export_qa_for_finetune.py（示意，按需落地）
import asyncio, json
from sqlalchemy import text
from app.db import SessionLocal

async def main():
    async with SessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT l.id, l.question, l.answer, l.top_score, l.gap_flag,
                   l.authorized_unit_ids_json AS auth, l.unauthorized_unit_ids_json AS unauth
            FROM qa_access_logs l
            WHERE l.faq_hit = false
            ORDER BY l.id DESC LIMIT 5000
        """))).mappings().all()
        with open("D:/kb-manager-work/finetune/raw/logs.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")

asyncio.run(main())
```

> 资料块还原：按 `authorized_unit_ids_json` 查 `unit_chunks` 中该单元相似度最高的 1~2 个 chunk，按线上 `[序号] 《标题》（编号）\n内容` 格式拼接。

### 2.2 五类样本的定义与构造方法

每条样本统一存为 ChatML/SFT 格式：

```json
{
  "id": "faith-0001",
  "capability": "faithfulness",
  "messages": [
    {"role": "system", "content": "<SYSTEM_PROMPT 全文>"},
    {"role": "user", "content": "【参考资料】\n[1] 《员工报销制度》（KU-0001）\n【二、报销流程】\n1. 员工应在费用发生后十五个工作日内提交报销申请……\n2. 单笔金额超过五千元需部门负责人与财务负责人双签。\n\n【问题】报销单需要在多久内提交？"},
    {"role": "assistant", "content": "报销单应在费用发生后十五个工作日内提交 [1]。"}
  ],
  "source": {"units": ["KU-0001"], "chunks": [12], "origin": "doc/faq/log", "reviewer": "张三", "reviewed_at": "2026-10-23"}
}
```

#### 4.1.1 行业术语与格式适配（`capability: terminology`）

- 构造：同一问题配不同模板答案（制度解释/操作步骤/故障处理），术语按 `term_glossary.csv` 统一。
- 样本量：600~1000 条；四类模板各 ≥ 150。
- 要点：答案里必须**出现标准术语**，不出现同义口语词。
- 示例（操作步骤）：
  - 输入：问题“怎么提交报销”
  - 输出：“提交报销的步骤如下：\n1. 在报销系统中新建报销单，填写费用明细；\n2. 上传合规发票（抬头为公司全称）；\n3. 提交直属上级审批，超过五千元需财务负责人双签；\n4. 财务复核后，款项目每个工作日打款至工资卡 [1][2]。”

#### 4.1.2 检索内容忠实回答（`capability: faithfulness`）

- 正样本：答案每个事实点都能在资料中逐字找到依据；数字、金额、期限、责任人必须与资料一致。
- **不可回答样本（重点）**：资料与问题相关但缺少关键信息，标准答案为拒答。例如资料只写“超过五千元需双签”，问题问“十万元以上谁审批” → 输出「知识库中未找到相关信息。现有资料仅规定了超过五千元的双签要求，未涉及十万元以上的审批层级。」
- 数字替换负样本：把资料里的“十五个工作日”与问题中的“一个月”混用，标准答案必须用资料数字。
- 样本量：1200~2000 条，其中不可回答 ≥ 40%。
- 标注要求：每条正样本标出“依据句”在哪个 chunk（人工核对）。

#### 4.1.3 多片段信息整合（`capability: multi_hop`）

- 构造：同一主题拆到 2~4 个文档/章节，问题需要跨片段合并；片段间故意放轻微表述差异（如“十五个工作日” vs “三周内”）。
- 标准答案要求：分主次、写清适用条件、冲突时说明以哪份为准（例如“以最新发布的制度版本为准 [2]”）。
- 样本量：500~800 条，其中含冲突样本 ≥ 15%。
- 示例：资料 [1] 住宿标准、[2] 交通标准 → 问题“出差去上海三天，住宿和交通有什么规定？” → 答案分两块列出并分别引用。

#### 4.1.4 证据引用与出处标注（`capability: citation`）

- 构造：答案每条结论句末带 `[n]`，`n` 必须与输入块编号一致；另造“引用错误”对照（答案内容正确但编号错），训练时**只给正确版本**，错误版本用于评测。
- 数值题、条款题、条件题是引用准确率的关键，应占 60% 以上。
- 样本量：600~1000 条。
- 自动化校验：写脚本比对答案中的 `[n]` 对应资料块是否包含答案关键词（见第 5 章评测脚本）。

#### 4.1.5 资料不足拒答（`capability: refusal`）

四类各 ≥ 200 条：

| 类型 | 输入特征 | 期望输出 |
|---|---|---|
| 无召回 | `【参考资料】` 段为空，或“知识库中未检索到与该问题相关的可用资料” | 「知识库中未找到相关信息。目前知识库未收录该主题的内容，建议联系知识管理员补充。」 |
| 弱相关 | 有资料但主题不符 | 「知识库中未找到相关信息。检索到的资料涉及 X，未涉及 Y。」 |
| 冲突 | 两份资料相互矛盾 | 「资料之间存在不一致：A 规定… [1]，B 规定… [2]。建议与知识管理员确认后补充统一口径。」 |
| 仅无权限 | 未授权召回形态的输入 | 「相关资料在知识库中存在，但您暂无访问权限，请联系知识管理员。」 |

- 额外构造“**有资料但资料里写的是不相关内容**”的样本，避免模型把“有资料”误判成“必须回答”。

### 2.3 样本配比（总计约 4000~5500 条）

| 能力 | 占比 | 条数 |
|---|---|---|
| 忠实回答（含不可回答） | 30% | ~1500 |
| 术语与格式 | 18% | ~900 |
| 证据引用 | 18% | ~900 |
| 拒答（四类） | 20% | ~1000 |
| 多片段整合 | 14% | ~700 |

另需：通用指令保持样本 300~500 条（防止灾难性遗忘），可用公开中文指令集抽样混入。

### 2.4 可用合成工具（OpenAI 兼容）

用当前线上模型（SiliconFlow `XingChenAGI/Xing4.0-29B` 或更强的 GPT 类模型）批量生成草稿，Prompt 要点：

1. 给模型一段资料 chunk + 要求生成 3 个「可回答」问题和 2 个「不可回答」问题；
2. 再让模型**只依据资料**生成答案，并输出依据句编号；
3. 生成后用脚本校验：答案中的数字/金额/期限是否都能在资料中找到；未通过的人工修；
4. 所有样本必须经人工抽检（≥ 20%）后才进入训练集。

> 严禁直接把模型自由发挥的答案放进去，否则等于把幻觉教给模型。

---

## 3. 数据质检与切分

### 3.1 质检清单

- [ ] 格式：每条都是 system/user/assistant 三段；user 段以 `【参考资料】` 开头、以 `【问题】` 引出问题。
- [ ] 一致性：system 段与线上 `SYSTEM_PROMPT` 逐字一致。
- [ ] 引用：assistant 中的 `[n]` 都 ≤ 资料块数量，且对应块包含答案依据。
- [ ] 事实：答案中每个数字/额度/期限/责任人都能在资料中找到原文。
- [ ] 去重：问题语义去重（可用本项目的 Embedding + 聚类，相似度 ≥ 0.95 视为重复，保留质量高的一条）。
- [ ] 脱敏：真实姓名、手机号、身份证、内网地址替换为占位符。
- [ ] 长度：单条样本（含资料）≤ 6000 字，超出按线上截断规则裁剪。
- [ ] 拒答样本：答案第一句必须是固定开头，且不包含任何资料外的推断。

### 3.2 切分

| 集合 | 比例 | 要求 |
|---|---|---|
| 训练集 | 85% | 分层抽样：五类能力比例保持 |
| 验证集 | 5% | 用于训练中监控 loss，防止过拟合 |
| 测试集 | 10% | 只用于最终对比，训练过程不可见 |

切分按**问题来源**分组，避免同一问题的变体同时出现在训练集和测试集。

### 3.3 目录结构

```
D:\kb-manager-work\finetune\
├── raw\                 # 原始导出（日志、FAQ、文档）
├── datasets\
│   ├── sft_train.jsonl
│   ├── sft_dev.jsonl
│   ├── sft_test.jsonl
│   ├── dpo_train.jsonl  # 可选
│   └── style_samples.md
├── scripts\             # 导出、清洗、校验、评测脚本
├── configs\             # LLaMA-Factory / Axolotl 训练配置
├── outputs\             # checkpoint、合并后的模型
├── reports\             # 基线/微调后评测报告
└── deploy\              # vLLM 启动脚本
```

---

## 4. 训练

### 4.1 环境

| 项 | 建议 |
|---|---|
| GPU | 单卡 24GB 可做 QLoRA（4-bit）；2×24GB 或 1×48GB 更舒适 |
| 框架 | LLaMA-Factory（推荐，配置简单）或 Axolotl |
| Python | 3.10/3.11 + CUDA 12.x |
| 依赖 | `torch`、`transformers`、`peft`、`bitsandbytes`、`trl`、`accelerate`、`flash-attn`（可选） |
| 基座 | 中文能力强的 8B 指令模型（如 Qwen2.5-7B-Instruct、Llama-3.1-8B-Instruct 中文版、Yi-1.5-9B-Chat），**用 Instruct 版而不是 Base 版** |

### 4.2 LoRA 超参（起点配置）

| 参数 | 值 | 说明 |
|---|---|---|
| 方法 | LoRA（QLoRA） | 8B 全参微调需多卡，不推荐 |
| lora_rank (r) | 16 | 数据多可 32 |
| lora_alpha | 32 | 通常 2×r |
| lora_dropout | 0.05 | |
| target_modules | q,k,v,o_proj,gate,up,down_proj | 覆盖全部线性层效果更好 |
| learning_rate | 1e-4（QLoRA）/ 5e-5~1e-4（LoRA） | |
| lr_scheduler | cosine | warmup 3%~5% |
| epochs | 2~3 | 超过 3 容易遗忘拒答能力 |
| batch_size | 每卡 1~2，梯度累积 8~16 | 有效 batch 16~32 |
| max_seq_len | 6144 | 覆盖 6000 字资料 + 问题 |
| cutoff_len | 6144 | 超出截断，**截断策略保持资料在前** |
| loss 计算 | 只对 assistant 段计算 | LLaMA-Factory 中设置 `mask_history` / 对应模板的 `train_on_prompt: false` |
| bf16 | 开启 | |
| gradient_checkpointing | 开启 | 降显存 |

### 4.3 LLaMA-Factory 配置示例（`configs/lora_sft.yaml`）

```yaml
### model
model_name_or_path: /data/models/Qwen2.5-7B-Instruct
trust_remote_code: true
quantization_bit: 4                 # QLoRA；显存足够可去掉

### method
stage: sft
do_train: true
finetuning_type: lora
lora_rank: 16
lora_alpha: 32
lora_dropout: 0.05
lora_target: all

### dataset
dataset_dir: D:/kb-manager-work/finetune/datasets
dataset: kb_manager_sft            # 需在 dataset_info.json 中登记 sft_train.jsonl
template: qwen                     # 与基座模型匹配
cutoff_len: 6144
max_samples: 100000
preprocessing_num_workers: 8

### output
output_dir: D:/kb-manager-work/finetune/outputs/lora-v1
logging_steps: 10
save_steps: 200
plot_loss: true
overwrite_output_dir: true

### train
per_device_train_batch_size: 1
gradient_accumulation_steps: 16
learning_rate: 1.0e-4
num_train_epochs: 2.5
lr_scheduler_type: cosine
warmup_ratio: 0.04
bf16: true
gradient_checkpointing: true

### eval
val_size: 0
per_device_eval_batch_size: 1
eval_strategy: steps
eval_steps: 200
```

`dataset_info.json` 登记：

```json
{
  "kb_manager_sft": {
    "file_name": "sft_train.jsonl",
    "formatting": "sharegpt",
    "columns": {"messages": "messages"},
    "tags": {"role_tag": "role", "content_tag": "content", "user_tag": "user", "assistant_tag": "assistant", "system_tag": "system"}
  }
}
```

启动：

```bash
llamafactory-cli train configs/lora_sft.yaml
```

### 4.4 训练中要看的指标

- `loss`：应稳步下降后趋平；若 200 步内不降，检查数据格式/template/学习率。
- 验证集 loss：与训练 loss 差距持续扩大 → 过拟合，减少 epoch 或加 dropout。
- 观察点：每 200 步存一次 checkpoint，最终在验证集上选**引用准确率 + 拒答正确率**最好的那个，而不是只看 loss 最低。

### 4.5 可选第二轮：DPO（提升拒答与忠实度）

- 构造偏好对：同一问题，`chosen` = 正确答案（有依据、带引用 / 正确拒答），`rejected` = 幻觉答案、无引用答案、该拒答却强答、引用编号错误。
- 每条 SFT 样本可配 1~2 对偏好，约 1500~2500 对。
- 超参起点：`beta=0.1`、`learning_rate=5e-6`、1 epoch、LoRA 接在 SFT 之后继续训练。
- LLaMA-Factory：`stage: dpo`，数据格式 `{messages, chosen, rejected}`。

### 4.6 合并与导出

```bash
# 合并 LoRA 到基座
llamafactory-cli export configs/merge_lora.yaml
# 关键字段：model_name_or_path=基座路径, adapter_name_or_path=LoRA 输出目录, export_dir=输出目录
```

输出目录即最终模型（Safetensors），用于 vLLM 加载。

---

## 5. 评测

### 5.1 评测集

- 测试集 `sft_test.jsonl`（10%）；
- 另建 **100 道核心业务题**（人工金标），覆盖五类能力，每类 20 题；
- 另建 **30 道上线风险题**：资料与问题“看似相关但无答案”（考察拒答）、资料冲突题、数字陷阱题、引用编号陷阱题。

### 5.2 指标定义

| 能力 | 指标 | 计算方式 |
|---|---|---|
| 忠实性 | 幻觉率 | 答案中出现资料中不存在的数字/条款/责任人的比例（脚本抽数字比对 + 人工复核） |
| 忠实性 | 依据覆盖率 | 答案要点中能在资料里找到依据的比例 |
| 完整性 | 要点召回率 | 标准答案要素清单被覆盖的比例 |
| 整合 | 跨片段覆盖 | 涉及的所有资料块至少被引用一次的比例 |
| 引用 | 引用准确率 | 答案中 `[n]` 所指块确实包含该结论依据的比例 |
| 拒答 | 拒答正确率 | 应拒答题中正确拒答的比例 |
| 拒答 | 误拒率 | 可回答题却被拒答的比例 |
| 格式 | 模板符合率 | 制度/步骤/故障类问题按对应模板输出的比例 |
| 术语 | 术语一致率 | 答案中标准术语占比（对照 `term_glossary.csv`） |

### 5.3 评测流程

1. **基线**：用基座模型（未微调）在测试集上跑一遍，记录全部指标。
2. **微调后**：同一套 Prompt、同一温度（0 或 0.1）、同一测试集跑一遍。
3. **对比报告**：每项指标列出「基线 / 微调后 / 变化」，并抽 20 条错误样例做人工分析。
4. **门槛**（建议）：引用准确率 ≥ 90%，拒答正确率 ≥ 90%，幻觉率下降 ≥ 50%，可回答题准确率不下降超过 3 个百分点；任一不达标不进入下一轮。
5. **LLM-as-Judge 辅助**：用更强模型（如 GPT 类）按「是否有依据 / 是否完整 / 引用是否正确」打分，只做趋势参考，最终以人工抽检为准。

### 5.4 评测脚本骨架（`scripts/eval_model.py`）

```python
# 要点：复刻线上的 Prompt 组装，逐题调用模型（OpenAI 兼容），保存 jsonl
import json, re, urllib.request

def build_messages(sample):
    return sample["messages"][:2]          # system + user，与线上一致

def call(base_url, api_key, model, messages):
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 800,
            "stream": False, "enable_thinking": False}
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + api_key)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def citations_ok(answer, n_blocks):
    ids = [int(x) for x in re.findall(r"\[(\d+)\]", answer)]
    return bool(ids) or n_blocks == 0, ids
```

> 评测时检索结果要**冻结**（直接用测试集里预置的资料块），不要现场检索，否则指标会被检索波动污染。

---

## 6. 部署与接入 kb-manager

### 6.1 vLLM 启动（OpenAI 兼容 + 流式）

```bash
python -m vllm.entrypoints.openai.api_server \
  --model /data/models/kb-manager-8b-lora-merged \
  --served-model-name kb-manager-8b \
  --host 0.0.0.0 --port 8001 \
  --max-model-len 8192 \
  --tensor-parallel-size 1 \
  --enable-prefix-caching
```

- 与线上接口的差异：SiliconFlow 的 `enable_thinking` 参数是厂商扩展，vLLM 原生不识别（会忽略）。若基座是 Qwen 系列思考模型，用 `--chat-template` 或 `--default-chat-template-kwargs '{"enable_thinking": false}'`（按 vLLM 版本）控制。
- 流式 SSE 与 `usage` chunk：vLLM 默认在流结束时返回 usage（`stream_options.include_usage`），与 `backend/app/services/llm.py` 的解析逻辑兼容；接入后用 `scripts/check_llm.py` 验证。

### 6.2 kb-manager 侧改动（只改配置）

| 位置 | 修改 |
|---|---|
| `backend/.env` | `LLM_BASE_URL=http://127.0.0.1:8001/v1`、`LLM_API_KEY=any`、`LLM_MODEL=kb-manager-8b`、`LLM_ENABLE_THINKING=false` |
| `scripts/check_llm.py` | 跑一次确认普通调用与流式都正常 |
| `app/services/chat.py` | **不改代码**；但必须确认 `SYSTEM_PROMPT` 与训练时逐字一致 |
| `app/services/llm.py` | 若新模型不支持 `enable_thinking` 字段，vLLM 会忽略，无需改 |

### 6.3 切换与灰度

1. 保留原模型配置（备份 `.env`）；
2. 新模型起在 8001 端口，先用一个普通用户账号在 AI 工作台抽 20 题对比；
3. 无问题后把 `LLM_BASE_URL` 切到 8001，重启后端；
4. 观察 1~3 天：`qa_access_logs` 中 `gap_flag` 比例、FAQ 命中率、用户反馈；
5. 出问题就改回原配置并重启，回滚成本为一次配置修改。

### 6.4 上线后监控指标（来自看板）

- 幻觉类投诉/人工标记数；
- 拒答率与误拒率（人工抽检 50 条/周）；
- 引用准确率（抽检）；
- 平均响应时间与 Token 消耗（微调后一般略降，因为答案更短）。

---

## 7. 迭代与数据回流

1. 每周从 `qa_access_logs` 导出：`gap_flag=true` 的提问（补资料/补拒答样本）、人工认为错误但未标记的答案（加入评测集）。
2. 新知识单元导入后，补充对应的可回答问题与“不可回答对照题”。
3. 每 1~2 个月做一次增量 LoRA（在上一版 adapter 上继续训练），或重新从基座训练。
4. 每次迭代都必须重跑测试集，更新 `reports/` 下的对比报告。

---

## 8. 常见问题排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 微调后不引用编号 | 训练样本中引用比例低 / 只对 answer 计算 loss 时模板未正确设置 | 提高引用样本占比，检查 template 与 `train_on_prompt=false` |
| 微调后什么都拒答 | 拒答样本占比过高 / epoch 过多 | 调整配比，降 epoch，补正样本 |
| 微调后仍编造数字 | 训练集里存在资料外数字（合成数据未校验） | 用脚本全量扫描答案中的数字是否在资料出现，剔除 |
| 太啰嗦、复述“根据资料” | 参考答案风格问题 | 人工统一答案风格，删除套话样本后重训 |
| 回答格式不稳定 | 模板样本太少或混入多种风格 | 每类模板 ≥ 150 条，统一标点与列表格式 |
| 输出混入思考过程 | 基座是思考模型且未关闭 | 关闭 thinking；训练数据中剔除 reasoning 内容 |
| 线上效果不如评测 | Prompt 与训练时不一致（少了 `[序号]` 或换了标题格式） | 用线上代码导出真实 Prompt 作为样本 |
| 训练 loss 不下降 | 数据格式/template 错、学习率过低 | 用小样本 50 条先跑通，确认 loss 能降 |

---

## 9. 交付物清单

- [ ] 术语表 `term_glossary.csv`
- [ ] 格式模板 `answer_templates.md`
- [ ] 五类样本 JSONL（`sft_train/dev/test.jsonl`，含质检报告）
- [ ] 训练配置 `configs/lora_sft.yaml`（及可选 `dpo.yaml`、`merge_lora.yaml`）
- [ ] LoRA 权重与合并后模型
- [ ] 评测报告 `reports/eval_baseline_vs_ft.md`
- [ ] 部署脚本 `deploy/vllm_start.sh` 与接入说明（更新 `backend/.env` 即可）
- [ ] 回滚方案与监控指标说明
