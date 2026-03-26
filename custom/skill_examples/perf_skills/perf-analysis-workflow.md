---
name: perf-analysis-workflow
type: repo
version: 3.1.0
agent: CodeActAgent
---

# 性能分析工作流

按以下 9 个阶段顺序执行 Perfetto trace 性能分析。每阶段执行对应脚本，脚本位于 `/workspace/custom/skill_examples/perf_skills/scripts/`，输出保存到 `/workspace/perf_analysis_output/`。

## 严格约束

1. **禁止自行编写 SQL 查询、Python 脚本或任何分析代码** — 只能调用指定脚本
2. **禁止修改已有脚本** — 脚本内容不可更改
3. **参数必须来自上一步的输出** — 不要猜测进程名、时间范围等值
4. **遇到脚本错误立即停止并报告** — 不要跳过失败步骤，不要自行编写替代方案

## 每步反思验证

每个脚本执行后必须检查：
- 输出 JSON 是否包含预期字段（`has_issue`, `severity` 等）
- 数值是否在合理范围内
- 如果输出异常，停止并报告，不要继续

## 执行步骤

| 阶段 | 脚本 | 输入 | 关键输出 |
|------|------|------|----------|
| 1. 初始化 | `trace_processor_init.py --trace <路径> --port 9001` | 用户提供的 trace 文件 | `status: ready` |
| 2. 查找进程 | `find_foreground_process.py --port 9001` | — | `PROCESS_NAME` |
| 3. 时间范围 | `find_launch_range.py --process $PROCESS_NAME --port 9001` | PROCESS_NAME | `START_TIME`, `END_TIME` |
| 4. 状态分析 | `analyze_main_thread_state.py --process $P --start $S --end $E --port 9001` | 上述参数 | `branches_to_analyze` |
| 5. 分支分析 | 根据第4步 branches 动态选择，见下方 | 上述参数 | 各分支结果 |
| 6. 内存分析 | `analyze_memory.py --start $S --end $E --port 9001` | 时间范围 | 内存问题 |
| 7. 渲染分析 | `analyze_rendering.py --process $P --start $S --end $E --target-fps 60 --port 9001` | 上述参数 | 帧率/掉帧 |
| 8. 清理 | `trace_processor_cleanup.py --output-dir /workspace/perf_analysis_output` | — | 服务停止 |
| 9. 报告 | `generate_report.py --output-dir /workspace/perf_analysis_output` | — | `full_report.html` + `issue_report.html` |

## 第5阶段分支选择

只执行 `branches_to_analyze` 中包含的分支：

- **running** → 依次执行: `analyze_big_core_ratio.py`, `analyze_cpu_frequency.py`, `analyze_compile_level.py`, `analyze_jit_thread.py`
- **runnable** → `analyze_thread_priority.py`, `analyze_system_load.py`（负载>80%时追加 `analyze_detailed_load.py`）
- **sleeping** → `analyze_system_load.py`（负载>80%时追加 `analyze_detailed_load.py`）
- **io** → `analyze_io_details.py`
- **non_io** → `analyze_non_io.py`

所有分支脚本参数格式统一：`--process $P --start $S --end $E --port 9001`

## 完成后

生成报告后向用户汇总：最严重的问题 + 建议的优化方向。报告文件位于 `/workspace/perf_analysis_output/full_report.html` 和 `issue_report.html`。
