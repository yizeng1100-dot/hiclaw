---
name: log-analysis-workflow
type: repo
version: 1.0.0
agent: CodeActAgent
phases:
  - key: parse
    label: 解析日志
    desc: 解析日志格式并提取结构化数据
    output: /workspace/log_output/parsed.json
  - key: statistics
    label: 统计分析
    desc: 统计错误分布和频率
    output: /workspace/log_output/statistics.json
  - key: report
    label: 生成报告
    desc: 输出分析报告
    output: /workspace/log_output/report.html
---

# 日志分析工作流

按以下 3 个阶段顺序执行日志分析。脚本位于 `/workspace/custom/skill_examples/log_analysis/scripts/`，输出保存到 `/workspace/log_output/`。

## 严格约束

1. **禁止自行编写分析代码** — 只能调用指定脚本
2. **参数必须来自用户输入或上一步输出**
3. **遇到错误立即停止并报告**

## 执行步骤

| 阶段 | 脚本 | 输入 | 输出 |
|------|------|------|------|
| 1. 解析 | `parse_log.py --file <日志路径> --format auto` | 用户提供的日志文件 | parsed.json |
| 2. 统计 | `analyze_stats.py --input /workspace/log_output/parsed.json` | 上一步输出 | statistics.json |
| 3. 报告 | `generate_report.py --output-dir /workspace/log_output` | — | report.html |

## 完成后

向用户汇总：错误数量、TOP 5 错误类型、时间分布趋势。
