---
name: perf-analysis-workflow
type: repo
version: 3.3.0
agent: CodeActAgent

# Dynamic input form — renders via DynamicFormPanel on agent launch.
# Same shape as render-performance-workflow, so adding a new agent is
# purely a matter of writing one of these.
input_form:
  - key: trace_path
    type: file
    label: Trace 文件
    placeholder: /workspace/trace.perfetto-trace
    accept: .perfetto-trace,.pb,.pftrace,.html,.txt,.json,.systrace,.ftrace
    required: true
  - key: direction
    type: select
    label: 分析方向
    default: full
    options:
      - label: 完整分析
        value: full
        desc: 9 阶段完整流水线
      - label: 启动性能
        value: startup
        desc: 启动耗时分析
      - label: CPU
        value: cpu
        desc: Running / 大小核 / 频率
      - label: 调度
        value: scheduling
        desc: Runnable / 优先级
      - label: IO
        value: io
        desc: IO / Non-IO 阻塞
      - label: 内存
        value: memory
        desc: OOM / GC / 分配
      - label: 渲染
        value: rendering
        desc: Jank / VSYNC
  - key: extra
    type: text
    label: 补充说明
    placeholder: 可选，关注的具体场景 / 进程 / 时间段...
    required: false

submit_message: |
  Execute skill: perf-analysis-workflow (trigger: /perf-analyze). Follow the skill instructions to complete the task.

  **Trace file path**: {{trace_path}}
  **Analysis direction**: {{direction}}
  {{extra}}

  Please execute the performance analysis workflow:
  1. Initialize trace_processor with the trace file
  2. Find foreground process
  3. Determine launch time range
  4. Analyze main thread state distribution
  5. Run branch analysis based on state results
  6. Analyze memory
  7. Analyze rendering
  8. Cleanup trace_processor
  9. Generate HTML report (full_report.html + issue_report.html)

phases:
  - key: init
    label: 初始化
    desc: 启动 Trace Processor
    output: perf_analysis_output/tp_state.json
  - key: target
    label: 查找进程
    desc: 确定分析目标
    output: perf_analysis_output/target_process.json
  - key: range
    label: 时间范围
    desc: 确定启动时间
    output: perf_analysis_output/launch_range.json
  - key: state
    label: 状态分析
    desc: 主线程状态分布
    output: perf_analysis_output/thread_state.json
  - key: branch
    label: 分支分析
    desc: 条件分析路径
    output: perf_analysis_output/big_core_ratio.json
  - key: memory
    label: 内存分析
    desc: OOM/GC/内存
    output: perf_analysis_output/memory.json
  - key: render
    label: 渲染分析
    desc: 帧率/掉帧
    output: perf_analysis_output/rendering.json
  - key: screenshot
    label: 截图（可选）
    desc: 捕获 Perfetto UI 问题片段截图
    output: perf_analysis_output/screenshots/screenshot_manifest.json
    optional: true
  - key: cleanup
    label: 清理
    desc: 停止服务
    output: null
  - key: report
    label: 生成报告
    desc: HTML 报告（含截图）
    output: perf_analysis_output/full_report.html

# Downloadable deliverables — listed separately from phases so a single
# `generate_report.py` step can publish multiple html artifacts without
# bloating the progress bar. The download component renders one button
# per entry (in order).
reports:
  - label: 完整报告
    file: perf_analysis_output/full_report.html
  - label: 问题报告
    file: perf_analysis_output/issue_report.html
---

# 性能分析工作流

按以下 10 个阶段顺序执行 Perfetto trace 性能分析。

## 🔴 命令模板（必须遵守，否则进度条无法点亮）

**每个阶段的脚本调用必须使用如下绝对路径模板。绝对不要 `cd` 到脚本目录。**

```bash
"$RUNTIME_PY" /workspace/custom/skill_examples/perf_skills/scripts/<脚本名>.py \
  <脚本参数> \
  --output-dir "$(pwd)/perf_analysis_output"
```

要点：
- **`"$RUNTIME_PY"` 是平台注入的环境变量**，指向 app-server 本身用的 Python 解释器（例如 `/home/.../.hiclaw/runtime/hiclaw-python`）。它和脚本依赖的 wheel 版本完全匹配。直接写裸 `python3` 会落到宿主机系统 Python（Ubuntu 22.04 默认 3.10）— 和 offline bundle 里的 cp312 wheel ABI 不兼容，`greenlet`、`Pillow` 等会直接 ImportError
- **`$(pwd)` 在每条命令开头被展开**，得到当前 conversation 的工作目录（由平台自动隔离到 `/workspace/project/<conv_hex>/`）
- 所有 phase 的输出统一落到 `$(pwd)/perf_analysis_output/`，前端进度条按这个路径轮询
- **绝对不要** `cd /workspace/custom/.../scripts &&` 这种写法 — 一旦 cd 出 conversation 目录，`$(pwd)` 就会改变，输出会落到错的地方
- **绝对不要** hardcode `/workspace/perf_analysis_output` 这种共享路径 — 那是老 hack，会被多个任务互相覆盖
- **绝对不要** 裸 `python3 xxx.py` — ABI 不对，ImportError；必须用 `"$RUNTIME_PY" xxx.py`

## 严格约束

1. **禁止自行编写 SQL 查询、Python 脚本或任何分析代码** — 只能调用指定脚本
2. **禁止修改已有脚本** — 脚本内容不可更改
3. **禁止 cd 到脚本目录或任何 conversation 工作目录之外的目录** — 必须用绝对脚本路径
4. **参数必须来自上一步的输出** — 不要猜测进程名、时间范围等值
5. **遇到脚本错误立即停止并报告** — 不要跳过失败步骤，不要自行编写替代方案

## 每步反思验证

每个脚本执行后必须检查：
- 输出 JSON 是否包含预期字段（`has_issue`, `severity` 等）
- 数值是否在合理范围内
- 如果输出异常，停止并报告，不要继续

## 执行步骤

下表只列**脚本名 + 关键参数**。每个命令都必须按上方"命令模板"展开为绝对路径形式，并附加 `--output-dir "$(pwd)/perf_analysis_output"`。

| 阶段 | 脚本 | 输入 | 关键输出 |
|------|------|------|----------|
| 1. 初始化 | `trace_processor_init.py --trace <路径> --port 9001` | 用户提供的 trace 文件 | `status: ready` |
| 2. 查找进程 | `find_foreground_process.py --port 9001` | — | `PROCESS_NAME` |
| 3. 时间范围 | `find_launch_range.py --process $PROCESS_NAME --port 9001` | PROCESS_NAME | `START_TIME`, `END_TIME` |
| 4. 状态分析 | `analyze_main_thread_state.py --process $P --start $S --end $E --port 9001` | 上述参数 | `branches_to_analyze` |
| 5. 分支分析 | 根据第4步 branches 动态选择，见下方 | 上述参数 | 各分支结果 |
| 6. 内存分析 | `analyze_memory.py --start $S --end $E --port 9001` | 时间范围 | 内存问题 |
| 7. 渲染分析 | `analyze_rendering.py --process $P --start $S --end $E --target-fps 60 --port 9001` | 上述参数 | 帧率/掉帧 |
| 8. 截图（可选） | `capture_trace_screenshot.py --trace $TRACE --process-name $PROCESS_NAME` | trace + 分析结果 | 截图 PNG |
| 9. 清理 | `trace_processor_cleanup.py` | — | 服务停止 |
| 10. 报告 | `generate_report.py` | — | `full_report.html` + `issue_report.html` |

**示例**（阶段 1 的完整命令)：

```bash
"$RUNTIME_PY" /workspace/custom/skill_examples/perf_skills/scripts/trace_processor_init.py \
  --trace /workspace/test_trace.perfetto-trace \
  --port 9001 \
  --output-dir "$(pwd)/perf_analysis_output"
```

**反例**（绝对不要这样）：

```bash
# ❌ 错：cd 改变了 $(pwd)，输出会落到 /workspace/custom/.../scripts/perf_analysis_output/
cd /workspace/custom/skill_examples/perf_skills/scripts && "$RUNTIME_PY" trace_processor_init.py --trace ... --output-dir perf_analysis_output

# ❌ 错：hardcode 共享路径，会被多个任务互相覆盖
"$RUNTIME_PY" /workspace/.../trace_processor_init.py --trace ... --output-dir /workspace/perf_analysis_output

# ❌ 错：裸 python3 会落到宿主机 /usr/bin/python3（Ubuntu 22.04 是 3.10），
#    和 offline bundle 里的 cp312 wheel ABI 不兼容，ImportError
python3 /workspace/custom/skill_examples/perf_skills/scripts/trace_processor_init.py ...
```

## 第5阶段分支选择

只执行 `branches_to_analyze` 中包含的分支：

- **running** → 依次执行: `analyze_big_core_ratio.py`, `analyze_cpu_frequency.py`, `analyze_compile_level.py`, `analyze_jit_thread.py`
- **runnable** → `analyze_thread_priority.py`, `analyze_system_load.py`（负载>80%时追加 `analyze_detailed_load.py`）
- **sleeping** → `analyze_system_load.py`（负载>80%时追加 `analyze_detailed_load.py`）
- **io** → `analyze_io_details.py`
- **non_io** → `analyze_non_io.py`

所有分支脚本参数格式统一：`--process $P --start $S --end $E --port 9001`

## 第8阶段：截图（可选）

**此步骤为可选。** 在清理 trace_processor 之前，尝试对 Perfetto UI 中的问题片段截图：

```bash
"$RUNTIME_PY" /workspace/custom/skill_examples/perf_skills/scripts/capture_trace_screenshot.py \
  --trace $TRACE_FILE \
  --analysis-dir "$(pwd)/perf_analysis_output" \
  --output-dir "$(pwd)/perf_analysis_output/screenshots" \
  --process-name "$PROCESS_NAME"
```

**判断规则：**
- 如果输出包含 `"skipped_reason"` 非空 → 环境不支持，跳过截图，继续下一步
- 如果输出 `"captured" > 0` → 截图成功，报告中会自动包含图片
- **不要因为截图失败而停止整个工作流**

## 完成后

生成报告后向用户汇总：最严重的问题 + 建议的优化方向。报告文件位于 `$(pwd)/perf_analysis_output/full_report.html` 和 `issue_report.html`。
