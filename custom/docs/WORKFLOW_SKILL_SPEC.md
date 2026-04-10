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

## Agent 配置说明

创建 Agent 时，关联一个 workflow skill 即可。平台会自动从 workflow 的 frontmatter 中读取 `phases`，无需在 agent 的 `config_json` 中重复配置。

如果 agent 的 `config_json` 中已手动定义了 `workflow_phases`，则以 `config_json` 中的为准（向后兼容）。

优先级：`config_json.workflow_phases` > workflow skill frontmatter `phases`

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

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-03-30 | 初始版本，定义 phases frontmatter 规范 |
| 1.1.0 | 2026-04-09 | output 路径平台约定改为相对路径 + 自动 per-conversation 隔离；绝对路径作为向后兼容保留。详情见 `output 路径约定` 一节。 |
