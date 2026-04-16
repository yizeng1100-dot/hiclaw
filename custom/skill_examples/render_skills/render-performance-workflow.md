---
name: render-performance-workflow
type: repo
version: 4.0.0
agent: CodeActAgent

# ===== 动态输入表单 =====
input_form:
  - key: trace_path
    type: file
    label: Trace 文件
    placeholder: /workspace/trace.perfetto-trace
    accept: .perfetto-trace,.pb,.pftrace
    required: true
  - key: focus
    type: select
    label: 分析重点
    default: full
    options:
      - label: 完整分析
        value: full
        desc: 分析 + 截图 + 报告
      - label: 快速分析（不截图）
        value: fast
        desc: 分析 + 报告，跳过截图
  - key: top_n
    type: number
    label: Top N 问题数
    default: 5
    min: 1
    max: 20
    placeholder: 报告中展示的最严重问题数量
  - key: extra
    type: text
    label: 补充说明
    placeholder: 可选，如关注某个场景或进程...
    required: false

submit_message: |
  Execute skill: render-performance-workflow. Follow the skill instructions.

  **Trace file path**: {{trace_path}}
  **Analysis focus**: {{focus}}
  **Top N issues**: {{top_n}}
  {{extra}}

  Please execute the render performance analysis workflow:
  1. Setup environment (perfetto, playwright, chromium)
  2. Analyze jank frames from the trace (one SQL-driven pass)
  3. Capture Perfetto UI screenshots for the top {{top_n}} issues
  4. Generate the HTML render report

phases:
  - key: setup
    label: 环境初始化
    desc: 安装 perfetto / playwright / chromium
    output: null
  - key: analyze
    label: Jank 分析
    desc: SQL 驱动的目标进程 + jank 帧 + 线程映射分析
    output: render_analysis_output/app_jank.json
  - key: screenshot
    label: Perfetto 截图
    desc: 为 Top N 问题抓取 Perfetto UI 全局图 + 局部细节图
    output: render_analysis_output/screenshots/screenshot_manifest.json
    optional: true
  - key: report
    label: 生成报告
    desc: HTML 渲染性能报告（含嵌入截图 + Framework 根因分析）
    output: render_analysis_output/render_report.html

reports:
  - label: 渲染性能报告
    file: render_analysis_output/render_report.html
---

# Android 应用绘制渲染性能分析工作流

统一的 4 阶段流水线。所有产物写入当前 conversation 工作目录下的
`render_analysis_output/`，由平台自动隔离到
`/workspace/project/<conv_hex>/render_analysis_output/`。

## 🔴 命令模板（必须遵守，否则进度条无法点亮，下载按钮无法出现）

**每个阶段的脚本调用必须使用如下绝对路径模板。绝对不要 `cd` 到脚本目录，
绝对不要用 `scripts/xxx.py` 这类相对路径。**

```bash
python3 /workspace/custom/skill_examples/render_skills/scripts/<脚本名>.py \
  <脚本参数> \
  --output-dir "$(pwd)/render_analysis_output"
```

要点：
- **`$(pwd)` 在每条命令开头被展开**，得到当前 conversation 的工作目录（由平台
  自动隔离到 `/workspace/project/<conv_hex>/`）。后端进度条、下载按钮、产物
  列表都基于这个目录探测，**必须用 `$(pwd)/render_analysis_output`**，
  不能 hardcode `/workspace/render_output`。
- 所有 phase 的输出统一落到 `$(pwd)/render_analysis_output/`，前端进度条按
  相对路径 `render_analysis_output/...`（见 phases 字段）轮询。
- **绝对不要** `cd /workspace/custom/.../scripts && ...` — 一旦 `cd` 出
  conversation 目录，`$(pwd)` 就会改变，输出会落到错的地方，前端找不到。
- **绝对不要** `python3 scripts/...` — 依赖 LLM 恰好在 skill 目录，实际
  conversation cwd 是 `/tmp/openhands-sandboxes/...`，会直接 "No such file" 报错。

## 严格约束

1. **禁止自行编写 SQL 查询或分析代码** — 只能调用指定脚本
2. **禁止修改已有脚本**
3. **禁止 cd 到脚本目录或任何 conversation 工作目录之外的目录** — 必须用绝对脚本路径
4. **trace 路径来自输入表单的 `{{trace_path}}`**，不要猜测
5. **遇到脚本错误立即停止并报告**

## 内网部署注意

`capture_screenshots.py` 默认访问公网 `https://ui.perfetto.dev`。内网部署
无法访问公网时，通过环境变量切到内网自部署的 Perfetto UI:

```bash
export PERFETTO_UI_URL=https://perfetto.rnd.hihonor.com/
```

外网环境不用设置这个变量，脚本默认就是 `ui.perfetto.dev`。内网环境如果
没设置会导致 `page.goto` 超时，最终截到的是空白的 Perfetto UI 初始化画面
（因为 trace 根本没加载进去）。如果你所在的 OpenHands 部署把这个变量注入
到 sandbox，所有命令会自动继承，不需要每条命令手动 export。

## 执行步骤

下表只列**脚本名 + 关键参数**。每个命令都必须按上方"命令模板"展开为绝对路径，
并把输出目录统一指向 `$(pwd)/render_analysis_output`。

| 阶段 | 脚本 | 关键参数 |
|------|------|----------|
| 0. 环境初始化 | `setup_env.py` | 无(自动安装依赖) |
| 1. Jank 分析 | `analyze_jank.py` | `--trace {{trace_path}}` |
| 2. 截图（可选） | `capture_screenshots.py` | `--trace {{trace_path}} --analysis-dir "$(pwd)/render_analysis_output"` |
| 3. 生成报告 | `render_report_generator.py` | `--top-n {{top_n}}` |

## 阶段详情

### 阶段 0: 环境初始化

```bash
python3 /workspace/custom/skill_examples/render_skills/scripts/setup_env.py
```

自动安装所有依赖：
- **perfetto**: Python 绑定，内置 trace_processor
- **playwright + Chromium**: Perfetto UI 无头浏览器截图
- **requests**: HTTP 依赖

**验证：** 输出 JSON 中 `all_ready: true`。

### 阶段 1: Jank 分析

```bash
python3 /workspace/custom/skill_examples/render_skills/scripts/analyze_jank.py \
  --trace {{trace_path}} \
  --output-dir "$(pwd)/render_analysis_output"
```

一次性完成：目标进程定位（按 jank 帧数最多的 app）、全局帧统计、jank 类型分布、
Top N 帧富化（region_range、keywords_hit、evidence_slices、target_ts、
focus_track、problem_description、screenshot_reasoning）、线程映射（主线程 /
RenderThread / hwuiTask / SF / RenderEngine / HWC）。

**产物（都在 `$(pwd)/render_analysis_output/` 下）：**
- `target_process.json` — 目标进程
- `app_jank.json` — 完整 jank 分析结果（含 top_frames 富化字段，生成报告用）
- `sf_jank.json` — SurfaceFlinger 层 jank
- `jank_types.json` — Jank 类型分布
- `thread_map.json` — 截图用的 track pin 关键字
- `tp_state.json` — trace 基础状态

**验证：** `app_jank.json` 中 `top_frames` 长度 > 0 或 `jank_rate == 0`。

### 阶段 2: Perfetto 截图（可选）

```bash
python3 /workspace/custom/skill_examples/render_skills/scripts/capture_screenshots.py \
  --trace {{trace_path}} \
  --analysis-dir "$(pwd)/render_analysis_output" \
  --output-dir "$(pwd)/render_analysis_output/screenshots"
```

为 `app_jank.json` 里 Top N 问题各抓 2 张图：全局图（显示 Actual Timeline +
pin 的所有关键 track）+ 局部细节图（target_ts ± 窗口内的 slice）。

**重要：此步骤为可选。** 如果截图失败（chromium 无法启动、Perfetto UI 加载
超时、RPC 握手失败等），记录失败原因并继续下一步 —— **不要因为截图失败而
停止工作流**。

### 阶段 3: 生成报告

```bash
python3 /workspace/custom/skill_examples/render_skills/scripts/render_report_generator.py \
  --output-dir "$(pwd)/render_analysis_output" \
  --top-n {{top_n}}
```

生成 HTML 渲染性能报告，包含：
- 概览统计（总帧数、Jank 率、类型分布）
- Top N 重点问题（每个问题含：Top 问题帧表、问题帧元数据、证据 slices、嵌入的
  Perfetto 截图、Android Framework 根因分析）
- 调用链路、源码文件引用、根因判断、优化建议

## 完成后

向用户汇总：
1. Jank 类型分布概览
2. 最严重的 Top N 卡顿问题 + 根因
3. Android Framework 层面的优化建议
4. 报告文件位于 `$(pwd)/render_analysis_output/render_report.html`
   （前端会在下载按钮自动探测该路径）

## 完整示例（完整分析模式）

```bash
# 阶段 0
python3 /workspace/custom/skill_examples/render_skills/scripts/setup_env.py

# 阶段 1
python3 /workspace/custom/skill_examples/render_skills/scripts/analyze_jank.py \
  --trace /workspace/project/abc123def456/trace.perfetto-trace \
  --output-dir "$(pwd)/render_analysis_output"

# 阶段 2
python3 /workspace/custom/skill_examples/render_skills/scripts/capture_screenshots.py \
  --trace /workspace/project/abc123def456/trace.perfetto-trace \
  --analysis-dir "$(pwd)/render_analysis_output" \
  --output-dir "$(pwd)/render_analysis_output/screenshots"

# 阶段 3
python3 /workspace/custom/skill_examples/render_skills/scripts/render_report_generator.py \
  --output-dir "$(pwd)/render_analysis_output" \
  --top-n 5
```

## 反例（绝对不要这样）

```bash
# ❌ 错：相对脚本路径，LLM 实际 cwd 是 /tmp/openhands-sandboxes，会直接报错
#    "No such file or directory"
python3 scripts/setup_env.py

# ❌ 错：cd 改变了 $(pwd)，输出会落到 /workspace/custom/.../scripts/render_analysis_output/
cd /workspace/custom/skill_examples/render_skills/scripts && python3 analyze_jank.py ...

# ❌ 错：hardcode 共享路径，会被多个任务互相覆盖，前端进度条/下载按钮都探测不到
python3 /workspace/.../analyze_jank.py ... --output-dir /workspace/render_output
```
