---
name: render-performance-workflow
type: repo
version: 3.0.0
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
    output: /workspace/render_output/app_jank.json
  - key: screenshot
    label: Perfetto 截图
    desc: 为 Top N 问题抓取 Perfetto UI 全局图 + 局部细节图
    output: /workspace/render_output/screenshots/screenshot_manifest.json
    optional: true
  - key: report
    label: 生成报告
    desc: HTML 渲染性能报告（含嵌入截图 + Framework 根因分析）
    output: /workspace/render_output/render_report.html

reports:
  - label: 渲染性能报告
    file: /workspace/render_output/render_report.html
---

# Android 应用绘制渲染性能分析工作流

统一的 4 阶段流水线。所有脚本位于 `scripts/` 目录，输出保存到 `/workspace/render_output/`。

## 严格约束

1. **禁止自行编写 SQL 查询或分析代码** — 只能调用指定脚本
2. **禁止修改已有脚本**
3. **trace 路径来自输入表单的 {{trace_path}}**，不要猜测
4. **遇到脚本错误立即停止并报告**

## 执行步骤

| 阶段 | 脚本 | 说明 |
|------|------|------|
| 0. 环境初始化 | `setup_env.py` | 自动安装 perfetto / playwright / chromium |
| 1. Jank 分析 | `analyze_jank.py --trace <trace> --output-dir /workspace/render_output` | 一次 SQL 扫描出目标进程 + jank 帧 + 线程映射 |
| 2. 截图（可选） | `capture_screenshots.py --trace <trace> --analysis-dir /workspace/render_output --output-dir /workspace/render_output/screenshots` | Top N 问题的 Perfetto UI 截图 |
| 3. 生成报告 | `render_report_generator.py --output-dir /workspace/render_output` | 嵌入截图的 HTML 报告 |

## 阶段详情

### 阶段0: 环境初始化

```bash
python3 scripts/setup_env.py
```

自动安装所有依赖：
- **perfetto**: Python 绑定，内置 trace_processor
- **playwright + Chromium**: Perfetto UI 无头浏览器截图
- **requests**: HTTP 依赖

**验证：** 输出 JSON 中 `all_ready: true`。

### 阶段1: Jank 分析

```bash
python3 scripts/analyze_jank.py \
  --trace <trace_path> \
  --output-dir /workspace/render_output
```

一次性完成：目标进程定位（按 jank 帧数最多的 app）、全局帧统计、jank 类型分布、Top N 帧富化（region_range、keywords_hit、evidence_slices、target_ts、focus_track、problem_description、screenshot_reasoning）、线程映射（主线程 / RenderThread / hwuiTask / SF / RenderEngine / HWC）。

**产物：**
- `target_process.json` — 目标进程
- `app_jank.json` — 完整 jank 分析结果（含 top_frames 富化字段，生成报告用）
- `sf_jank.json` — SurfaceFlinger 层 jank
- `jank_types.json` — Jank 类型分布
- `thread_map.json` — 截图用的 track pin 关键字
- `tp_state.json` — trace 基础状态

**验证：** `app_jank.json` 中 `top_frames` 长度 > 0 或 `jank_rate == 0`。

### 阶段2: Perfetto 截图（可选）

```bash
python3 scripts/capture_screenshots.py \
  --trace <trace_path> \
  --analysis-dir /workspace/render_output \
  --output-dir /workspace/render_output/screenshots
```

为 `app_jank.json` 里 Top N 问题各抓 2 张图：全局图（显示 Actual Timeline + pin 的所有关键 track）+ 局部细节图（target_ts ± 窗口内的 slice）。

**重要：此步骤为可选。** 如果截图失败（chromium 无法启动、Perfetto UI 加载超时、RPC 握手失败等），记录失败原因并继续下一步 —— **不要因为截图失败而停止工作流**。

### 阶段3: 生成报告

```bash
python3 scripts/render_report_generator.py \
  --output-dir /workspace/render_output \
  --top-n 5
```

生成 HTML 渲染性能报告，包含：
- 概览统计（总帧数、Jank 率、类型分布）
- Top N 重点问题（每个问题含：Top 问题帧表、问题帧元数据、证据 slices、嵌入的 Perfetto 截图、Android Framework 根因分析）
- 调用链路、源码文件引用、根因判断、优化建议

## 完成后

向用户汇总：
1. Jank 类型分布概览
2. 最严重的 Top N 卡顿问题 + 根因
3. Android Framework 层面的优化建议
4. 报告文件位于 `/workspace/render_output/render_report.html`
