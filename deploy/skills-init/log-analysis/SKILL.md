---
name: log-analysis
description: 系统日志收集与分析，识别错误、警告和异常
type: skill
trigger:
  type: keyword
  keywords: ["analyze logs", "check logs", "日志分析", "dmesg", "查日志"]
scripts:
  - scripts/collect-logs.sh
  - scripts/analyze.py
  - scripts/report.sh
---

# Log Analysis

分析系统日志时：

1. **收集日志** — 运行 `scripts/collect-logs.sh`
   - 采集 dmesg 和 journalctl 输出到 /tmp/
2. **分析错误** — 运行 `python3 scripts/analyze.py`
   - 扫描 error/fail/panic 模式
3. **生成报告** — 运行 `scripts/report.sh`
   - 输出汇总到 /tmp/report.md
4. **展示结果** — 读取报告，向用户说明发现
5. **建议修复** — 对关键问题给出修复建议
