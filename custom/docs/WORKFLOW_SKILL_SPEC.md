# Workflow Skill 编写规范

本文档定义了 HiClaw 平台中 Workflow Skill 的编写标准。遵循此规范可确保你的 workflow 被平台正确���载、执行和追踪进度。

## 概念说明

HiClaw 中有三个核心概念：

| 概念 | 说明 | 举例 |
|------|------|------|
| **Skill** | 一个 `.md` 文件，描述一项具体能力（分析、操作、查询等） | `analyze-memory.md` |
| **Workflow** | 一种特殊的 Skill，定义多步骤执行流程，包含阶段和进度追踪 | `perf-analysis-workflow.md` |
| **Agent** | 一个可执行实体，关联一个 workflow + 多个 skills | `性能分析 Agent` |

关系：**Agent** 引用一个 **Workflow** 作为执行规则，引用多个 **Skill** 作为能力。

## Skill 文件结构

每个 skill 是一个 Markdown 文件，由 YAML frontmatter + 正文组成：

```markdown
---
# === 必填字段 ===
name: my-skill-name          # 唯一标识，kebab-case
type: repo | knowledge        # repo=始终加载, knowledge=按需触发

# === 可选字段 ===
version: 1.0.0               # 语义化版本号
agent: CodeActAgent           # 适用的 agent 类型
triggers:                     # knowledge 类型才需要
  - /my-command               # 以 / 开头为 TaskTrigger
  - keyword1                  # 否则为 KeywordTrigger
---

Skill 正文（Markdown 格式）...
```

### type 字段��明

| 值 | 行为 | 适用场景 |
|----|------|---------|
| `repo` | 始终注入到 agent 的 system prompt | Workflow 规则、全局约束 |
| `knowledge` | 按需加载，通过 trigger 关键字激活 | 具体分析能力、工具说明 |

## Workflow Skill 规范

Workflow 是一种特殊的 `type: repo` skill，额外定义了 `phases` 字段来描述执行阶段。

### Frontmatter 完整字段

```yaml
---
name: my-workflow             # 必填，建议以 -workflow 结尾
type: repo                    # 必须为 repo
version: 1.0.0                # 建议填写
agent: CodeActAgent           # 可选

# === Workflow 特有字段 ===
phases:                       # 定义执行阶段列表
  - key: init                 # 阶段唯一标识，snake_case 或 kebab-case
    label: 初始化              # 前端显示名称（支持中英文）
    desc: 启动服务             # 阶段简要说明
    output: my_output/state.json    # 相对会话工作目录的标志文件路径（推荐）
  - key: analyze
    label: 分析
    desc: 执行核心分析
    output: my_output/result.json
  - key: cleanup
    label: 清理
    desc: 停止服务
    output: null               # null 表示该阶段无输出文件
  - key: report
    label: 生成报告
    desc: 输出最终报告
    output: my_output/report.html
---
```

### Phase 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `key` | string | 是 | 阶段唯一标识。同一 workflow 内不可重复 |
| `label` | string | 是 | 前端展示的阶段名称 |
| `desc` | string | 是 | 阶段的简要描述 |
| `output` | string \| null | 是 | 阶段完成后生成的文件路径。平台通过检测此文件是否存在来判断阶段完成。设为 `null` 表示该阶段无输出文件（如清理阶段） |

### output 路径约定（v1.1.0 更新：推荐相对路径）

**推荐：使用相对路径，由平台自动隔离到当前 conversation 的工作目录下。**

- 路径格式：`<workflow_name>_output/<filename>`（**相对路径**）
- 平台行为：app-server 在 `read_conversation_file` endpoint 中将相对路径解析为
  `<sandbox_spec.working_dir>/<conversation_id_hex>/<相对路径>`（启用 sandbox 分组时）或
  `<sandbox_spec.working_dir>/<相对路径>`（NO_GROUPING 模式）
- 隔离效果：每次新建 conversation 都拿到独立的子目录，**不会复用上次任务的残留**，
  进度条不会"开局全亮"，多个并发任务也互不污染
- 同时，agent 在 sandbox 内的 bash CWD 默认就是这个 per-conv 工作目录，所以脚本只需写
  `--output-dir <workflow_name>_output/` 即可，文件会落到正确位置
- JSON 输出使用 `.json` 后缀；HTML 报告使用 `.html` 后缀
- 文件名应与 phase key 或脚本名对应，便于理解

示例（推荐写法）：
```
perf_analysis_output/tp_state.json
perf_analysis_output/thread_state.json
perf_analysis_output/full_report.html
```

**向后兼容**：绝对路径（`/workspace/...`）仍受支持，endpoint 会原样透传给 agent-server。
但绝对路径**不会**被自动隔离，**不要在新 workflow 里使用**。仅当 skill 需要读取 sandbox
内固定位置（如老 agent 的硬编码工件路径）时才用绝对路径。

### 进度检测机制

平台每 **10 秒** 检查一次各阶段的 `output` 文件：
- 文件存在且非空 → 该阶��标记为 **完成**
- 文件不存在 → 该阶段标记为 **等待** 或 **执行中**
- `output: null` 的阶段 → 如果下一个阶段已完成，则自动标记为完成
- 所有阶段完成 → 任务自动标记为 **已完成**

### 阶段排列规则

1. 阶段按 frontmatter 中的**顺序**执行（从上到下）
2. 第一个阶段通常是初始化/环境准备
3. 最后一个阶段通常是报告生成或结果汇总
4. 清理阶段（`output: null`）放在报告之前

## Workflow 正文编写规范

正文是给 Agent（LLM）看的执行指令，应包含以下部分：

### 1. 标题和概述

```markdown
# 工作流名称

简要说明此工作流的目的和适用场景。
```

### 2. 严格约束（推荐）

```markdown
## 严格约束

1. **禁止自行编写分析代码** — 只能调用指定脚本
2. **参数必须来自上一步的输出** — 不要猜测
3. **遇���错误立即停止并报告** — 不要跳过失败步骤
```

### 3. 验证规则（推荐）

```markdown
## 每步反思验证

每个脚本执行后必须检查：
- 输出 JSON 是否包含预期字段
- 数值是否在合理范围内
- 如果输出异常，停止并报告
```

### 4. 执行步骤（必须）

用表格或有序列表清晰列出每个阶段的脚本、输入和输出：

```markdown
## 执行步骤

| 阶段 | 脚本 | 输入 | 输出 |
|------|------|------|------|
| 1. 初始化 | `init.py --param value` | 用户提供 | status: ready |
| 2. 分析 | `analyze.py --input $X` | 上一步输出 | result.json |
```

### 5. 条件分支（可选）

如果工作流包含条件逻辑：

```markdown
## 条件���支

根据第 N 步的输出字段 `branch_type` 选择执行路径：
- **type_a** → 执行 script_a.py
- **type_b** → 执行 script_b.py
```

### 6. 完成后（推荐）

```markdown
## 完成后

向用户汇总关键发现和建议。
```

## 完整示例

```markdown
---
name: data-quality-workflow
type: repo
version: 1.0.0
agent: CodeActAgent
phases:
  - key: connect
    label: 连接数据源
    desc: 建立数据库连接
    output: dq_output/connection.json
  - key: profile
    label: 数据概览
    desc: 统计字段分布
    output: dq_output/profile.json
  - key: validate
    label: 质量校验
    desc: 执行规则检查
    output: dq_output/validation.json
  - key: report
    label: 生成报告
    desc: 输出质量报告
    output: dq_output/report.html
---

# 数据质量检查工作流

对目标数据��执行自动化质量检查，生成质量报告。

## 严格约束

1. 只能调用 `/workspace/custom/dq_scripts/` 下的脚本
2. 参数必须来自上一步输出或用户输入

## 执行步骤

| 阶段 | 脚本 | 输入 | 输出 |
|------|------|------|------|
| 1. 连接 | `connect.py --dsn $DSN` | 用户提供的连接字符串 | connection.json |
| 2. 概览 | `profile.py --tables $TABLES` | 表名列表 | profile.json |
| 3. 校验 | `validate.py --rules rules.yaml` | 规则配置文件 | validation.json |
| 4. 报告 | `gen_report.py --output-dir dq_output` | — | report.html |

## 完成后

向用户展示质量评分、问题字段列表和修复建议。
```

## Knowledge Skill 编写规范（简要）

Knowledge skill 描述的是单个能力，比 workflow 简单：

```markdown
---
name: analyze-memory
type: knowledge
triggers:
  - memory
  - OOM
  - GC
---

# 内存分析

分析 trace 中��内存相关指标。

## 脚本

`analyze_memory.py --start $START --end $END --port 9001`

## 输出字段

- `has_issue`: 是否存在内存问题
- `severity`: 严重程度 (low/medium/high)
- `details`: 具体指标
```

## 动态输入表单（v1.2.0+）

### 为什么要用

早期 agent 的 trace 上传面板写死在前端里（`PerfAnalysisInlinePanel.tsx`），每加一个 agent 都要改前端代码。平台现在支持"**skill frontmatter 声明表单，前端自动渲染**"——加新 agent **零前端代码改动**，只写一个 `.md` 文件即可。

具体做法：在 workflow skill 的 frontmatter 里加两个字段：

- `input_form:` 列出要渲染的表单字段
- `submit_message:` 用户提交后，模板变量替换后作为 initial message 发给 agent

前端 `DynamicFormPanel` 组件读 `input_form` 渲染 UI，提交时按 `submit_message` 模板替换用户填的值，新建 conversation 并把替换后的消息发过去。

### 完整字段

```yaml
---
name: my-workflow
type: repo

# 动态输入表单 —— 前端 DynamicFormPanel 自动渲染
input_form:
  - key: trace_path          # 必填，变量名，用于 submit_message 模板替换
    type: file               # 必填，字段类型（见下表）
    label: Trace 文件         # 必填，UI 上显示的字段名
    placeholder: /workspace/trace.perfetto-trace   # 可选
    accept: .perfetto-trace,.pb,.pftrace            # 仅 file 类型，限制扩展名
    required: true           # 可选，默认 false
  - key: focus
    type: select
    label: 分析重点
    default: full            # 可选，预选的 value
    options:                 # select 必填
      - label: 完整分析       # 下拉项显示文本
        value: full          # 提交时传的值
        desc: 全部 10 阶段    # 可选，hover 提示
      - label: 快速分析
        value: fast
  - key: top_n
    type: number
    label: Top N 问题数
    default: 5
    min: 1                   # 可选，number 类型的下限
    max: 20                  # 可选，number 类型的上限
    placeholder: 最严重问题数量
  - key: extra
    type: text               # 普通单行文本输入
    label: 补充说明
    placeholder: 可选，如关注某场景...
    required: false
  - key: notes
    type: textarea           # 多行文本
    label: 详细备注

# 提交模板 —— {{key}} 占位符会用用户填的值替换
submit_message: |
  Execute skill: my-workflow. Follow the skill instructions.

  **Trace file path**: {{trace_path}}
  **Focus**: {{focus}}
  **Top N**: {{top_n}}
  {{extra}}

  Please execute the workflow:
  1. ...
---
```

### `type` 字段说明

| 类型 | 渲染组件 | 值类型 | 说明 |
|---|---|---|---|
| `file` | 文件选择器 | string（sandbox 绝对路径）| 用户选文件后，前端通过 `POST /api/v1/uploads` 把文件上传到 `~/.openhands/sandbox-data/.uploads/<upload_id>/<filename>`，返回 sandbox 可见路径 `/workspace/conversations/.uploads/<upload_id>/<filename>` 作为 `{{key}}` 的值 |
| `select` | 下拉单选 | string | `options:` 必填；`default:` 可预选某个 value |
| `number` | 数字输入 | number | `min` / `max` / `default` 可选 |
| `text` | 单行文本 | string | |
| `textarea` | 多行文本 | string | 用于长输入（如详细备注）|

**注意**：`key` 只能用 `[a-zA-Z_][a-zA-Z0-9_]*`，避免和模板变量替换冲突。

### `submit_message` 模板替换规则

- `{{key}}` 会被替换为用户输入的对应值（所有类型统一用 `String(value)`）
- 未填写的 required=false 字段：
  - 如果没填 → `{{key}}` 保留原样进模板
  - 模板最后会清除所有未替换的 `{{...}}` 占位符（防止留一堆空标签）
- file 字段的值是 sandbox 内的绝对路径，可以直接在 bash 命令里用
- 多行模板（`|` 或 `>-`）会保留换行，适合写一段详细指令

### 提交后做了什么

```
用户点 "提交"
 → DynamicFormPanel.handleSubmit():
   1. 遍历所有 type=file 字段，调用 FileUploadService.upload(file) 拿到 sandbox 路径
   2. 把所有值塞进 values 对象
   3. 按 submit_message 模板逐个替换 {{key}} → values[key]
   4. 清除未替换的 {{...}} 占位符
   5. 调用 onSubmit(finalMessage)
 → 上游 handleFormSubmit() 做 agent 启动三件套：
   1. TaskService.createTask({agent_id})       ← 创建 agent_task 记录
   2. createConversation({query: finalMessage}) ← 创建新 conv 并把消息作为 initial message 发给 agent
   3. TaskService.startTask(task_id, conv_id)   ← 把 task 关联到 conv
   4. navigate(`/conversations/<new_conv_id>`)  ← 跳到新 conv 页面
```

**每次提交都会新建一个独立 conversation**，跟 perf/render 其它 agent 行为一致。想在已有 conv 里复用这个 agent？目前不支持，workflow 运行是"一次性"的，独立 conv 更便于任务中心追溯。

### 下载报告：`reports:` 字段

如果 workflow 的 report phase 会输出多个 `.html` 文件（比如 perf agent 一次生成 `full_report.html` + `issue_report.html`），把它们显式声明到 `reports:` 字段，前端会自动为每个条目渲染一个下载按钮：

```yaml
reports:
  - label: 完整报告                                       # 下载按钮上显示的名字
    file: perf_analysis_output/full_report.html            # 相对 conv 工作目录的路径
  - label: 问题报告
    file: perf_analysis_output/issue_report.html
```

规则：
- `file` 和 workflow phase 的 `output` 同样的路径约定（相对 = per-conv 隔离；绝对 = 原样透传）
- 条目可以和某个 phase 的 `output` 重复（如 `full_report.html` 同时是 phase output 和 report）
- **完全不声明也能 fallback**：如果 skill 没写 `reports:`，下载按钮会扫 `phases:` 里任何 `output` 以 `.html` 结尾的 phase，自动生成按钮
- 显式声明的好处：能自定义 label（"完整报告"比 `full_report.html` 好看多了）和顺序

### 前端渲染条件

Agent 的 `config_json.input_form` 字段存在 → `agent-detail-page.tsx` 展示"开始分析"按钮 + 弹 DynamicFormPanel；否则只展示"启动 Agent"按钮（直接用 system_prompt 启动 agent，无表单）。

后端 `/api/v1/agents/{id}` 的 overlay 会在**每次请求**自动从 skill frontmatter 同步 `input_form` / `workflow_phases` / `reports` 三个字段到 `config_json`（详情见 `custom/agent_mgmt/router.py:get_agent` + `custom/skill_mgmt/bridge.py`），所以改完 `.md` 不用 restart 后端 —— bridge 缓存 miss 时会重扫磁盘。

### 排错

| 现象 | 根因 |
|---|---|
| 前端启动 agent 没弹表单，直接用 system_prompt 跑 | skill frontmatter 没写 `input_form:` 字段 |
| 表单渲染但某个字段没响应 | `key` 包含了非法字符（只能用 `[a-zA-Z_][a-zA-Z0-9_]*`） |
| 提交后 message 里 `{{trace_path}}` 没被替换 | 字段 `key` 和模板 `{{key}}` 名字对不上 |
| file 字段上传后 agent 找不到文件 | 确认 sandbox `SANDBOX_VOLUMES` 有 `~/.openhands/sandbox-data:/workspace/conversations` 这条 bind-mount（见 `start_dev.sh`） |
| 下载按钮不出现 | `reports:` 里的 file 路径是相对 vs 绝对要和 phase output 一致；不声明 `reports:` 时只有 `.html` 后缀的 phase output 才会生成按钮 |

---

## Agent 配置说明

创建 Agent 时，关联一个 workflow skill 即可。平台会自动从 workflow 的 frontmatter 中读取 `phases` / `input_form` / `reports`，无需在 agent 的 `config_json` 中重复配置。

如果 agent 的 `config_json` 中已手动定义了 `workflow_phases` / `input_form` / `reports`，则以 `config_json` 中的为准（向后兼容）。

优先级：`config_json.<field>` > workflow skill frontmatter `<field>`

## 文件目录约定

```
custom/
├── skill_examples/
│   └── perf_skills/              # 按领域分目录
│       ├── perf-analysis-workflow.md   # Workflow skill
│       ├── analyze-memory.md           # Knowledge skill
│       ├── analyze-cpu-frequency.md    # Knowledge skill
│       └── scripts/                    # 脚本目录
│           ├── analyze_memory.py
│           └── analyze_cpu_frequency.py
├── skill_mgmt/                   # Skill 管理模块
│   └── bridge.py                 # Skill 加载桥接
├── agent_mgmt/                   # Agent 管理模块
└── docs/
    └── WORKFLOW_SKILL_SPEC.md    # 本文档
```

## 系统已有 Agent 实例参考

截至 2026-04-17，平台上已注册 5 个 Agent。下面列出各 agent 的 workflow skill 配置
作为真实参考，新 agent 可直接照抄改。

### 1. 性能分析 Agent（标杆，最完整）

| 项 | 值 |
|---|---|
| Workflow | `custom/skill_examples/perf_skills/perf-analysis-workflow.md` |
| Category | performance |
| Phases | 10 个（init → target → range → state → branch → memory → render → screenshot → cleanup → report） |
| input_form | 3 字段：`trace_path`(file) + `direction`(select, 7 个选项) + `extra`(text) |
| reports | 2 个：完整报告 `full_report.html` + 问题报告 `issue_report.html` |
| 输出目录 | `perf_analysis_output/`（相对路径，per-conv 隔离）✅ |
| 脚本调用 | `"$RUNTIME_PY" /workspace/custom/skill_examples/perf_skills/scripts/xxx.py`（绝对路径 + RUNTIME_PY）✅ |

**input_form 配置：**

```yaml
input_form:
  - key: trace_path
    type: file
    label: Trace 文件
    accept: .perfetto-trace,.pb,.pftrace,.html,.txt,.json,.systrace,.ftrace
    required: true
  - key: direction
    type: select
    label: 分析方向
    default: full
    options:
      - { label: 完整分析, value: full, desc: 9 阶段完整流水线 }
      - { label: 启动性能, value: startup, desc: 启动耗时分析 }
      - { label: CPU, value: cpu, desc: Running / 大小核 / 频率 }
      - { label: 调度, value: scheduling, desc: Runnable / 优先级 }
      - { label: IO, value: io, desc: IO / Non-IO 阻塞 }
      - { label: 内存, value: memory, desc: OOM / GC / 分配 }
      - { label: 渲染, value: rendering, desc: Jank / VSYNC }
  - key: extra
    type: text
    label: 补充说明
    placeholder: 可选，关注的具体场景 / 进程 / 时间段...
    required: false
```

### 2. 渲染性能分析 Agent

| 项 | 值 |
|---|---|
| Workflow | `custom/skill_examples/render_skills/render-performance-workflow.md` |
| Category | performance |
| Phases | 4 个（setup → analyze → screenshot → report） |
| input_form | 4 字段：`trace_path`(file) + `focus`(select) + `top_n`(number) + `extra`(text) |
| reports | 1 个：渲染性能报告 `render_report.html` |
| 输出目录 | `render_analysis_output/`（相对路径）✅ |
| 脚本调用 | `"$RUNTIME_PY" /workspace/custom/skill_examples/render_skills/scripts/xxx.py` ✅ |
| 特殊依赖 | Playwright + Chromium（截图用），需内网设 `PERFETTO_UI_URL` 环境变量 |

**input_form 配置：**

```yaml
input_form:
  - key: trace_path
    type: file
    label: Trace 文件
    accept: .perfetto-trace,.pb,.pftrace
    required: true
  - key: focus
    type: select
    label: 分析重点
    default: full
    options:
      - { label: 完整分析, value: full, desc: 分析 + 截图 + 报告 }
      - { label: 快速分析（不截图）, value: fast, desc: 分析 + 报告，跳过截图 }
  - key: top_n
    type: number
    label: Top N 问题数
    default: 5
    min: 1
    max: 20
  - key: extra
    type: text
    label: 补充说明
    required: false
```

### 3. 内核对比分析 Agent

| 项 | 值 |
|---|---|
| Workflow | `custom/skill_examples/android-kernel-diff-analysis.md` |
| Category | kernel-analysis |
| Phases | 无（seed 时只设了 system_prompt，没有 phases frontmatter） |
| input_form | 无（前端用默认"启动 Agent"按钮，无动态表单）|
| 状态 | 老式 agent，未迁移到 workflow + input_form 规范 |

> **待改进**：建议补 `input_form`（old_tag / new_tag 两个 text 字段）+ `phases`（clone → diff → analyze → report）+ `reports`（`kernel_analysis_report.md`），让它和性能/渲染 agent 体验一致。

### 4. 日志分析 Agent

| 项 | 值 |
|---|---|
| Workflow | `custom/skill_examples/log_analysis/log-analysis-workflow.md` |
| Category | 运维 |
| Phases | 3 个（parse → statistics → report）|
| input_form | 无 |
| 输出目录 | `/workspace/log_output/`（**⚠️ 绝对路径，老式写法**）|
| 脚本调用 | `python3 scripts/xxx.py`（**⚠️ 相对路径，依赖 cwd**）|

> **待改进**：
> 1. 输出路径从 `/workspace/log_output/` 改成 `log_analysis_output/`（相对路径，per-conv 隔离）
> 2. 脚本调用从 `python3 scripts/xxx.py` 改成 `"$RUNTIME_PY" /workspace/custom/skill_examples/log_analysis/scripts/xxx.py`（绝对路径 + RUNTIME_PY）
> 3. 补 `input_form`（`log_file` file 字段 + `format` select 字段）

### 5. 回声测试 Agent

| 项 | 值 |
|---|---|
| Category | 测试 |
| 用途 | 简单的 echo 回显，用于验证 agent 链路是否通 |
| input_form | 无 |
| Phases | 无 |

---

## 环境变量参考

以下环境变量影响 workflow 脚本在 sandbox 内的行为。由 `deploy/start.sh` 在启动时
export，通过 `process_sandbox_service.py` 的 `os.environ.copy()` 自动传给 sandbox
bash 子进程。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `RUNTIME_PY` | `$RUNTIME_DIR/hiclaw-python`(pro) 或 Poetry venv python(dev) | sandbox 内脚本调用应使用 `"$RUNTIME_PY" /workspace/.../xxx.py` 而非裸 `python3`，避免落到宿主机系统 Python（Ubuntu 22.04 = 3.10）导致 ABI 不兼容 |
| `PERFETTO_UI_URL` | `https://ui.perfetto.dev` | 渲染 agent 截图脚本 `capture_screenshots.py` / `capture_trace_screenshot.py` 的 Perfetto UI 地址。内网部署设为 `https://perfetto.rnd.hihonor.com/`（或其他自部署实例） |
| `OH_SECRET_KEY` | 由 `start_dev.sh` 设置 | OpenHands 认证密钥 |
| `SANDBOX_VOLUMES` | 见 `start_dev.sh` | sandbox bind-mount 挂载点（`sandbox-data:/workspace/conversations:rw,custom:/workspace/custom:ro`） |

### 内网部署启动示例

```bash
PERFETTO_UI_URL=https://perfetto.rnd.hihonor.com/ bash deploy/start.sh pro
```

`RUNTIME_PY` 和 `PERFETTO_UI_URL` 都会自动传进 sandbox 子进程，所有 workflow 脚本
直接读环境变量即可，不需要每次手动 export。

---

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-03-30 | 初始版本，定义 phases frontmatter 规范 |
| 1.1.0 | 2026-04-09 | output 路径平台约定改为相对路径 + 自动 per-conversation 隔离；绝对路径作为向后兼容保留。详情见 `output 路径约定` 一节。 |
| 1.2.0 | 2026-04-13 | 新增 `input_form` / `submit_message` / `reports` 三个 frontmatter 字段，让 agent 的输入表单 + 下载按钮完全由 skill 驱动，前端零代码改动即可加新 agent。`PerfAnalysisInlinePanel` 硬编码面板已退役。详情见「动态输入表单」一节。 |
| 1.3.0 | 2026-04-17 | 新增「系统已有 Agent 实例参考」——列出 5 个在线 agent 的 workflow 配置作为真实案例；新增「环境变量参考」——`RUNTIME_PY` / `PERFETTO_UI_URL` 的说明和内网部署启动示例；标注日志分析 / 内核对比 agent 的待改进项。 |
