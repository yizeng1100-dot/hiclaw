---
name: kernel-crash-analysis
description: 内核 crash dump 分析，从 vmcore 收集到根因定位
type: skill
trigger:
  type: keyword
  keywords: ["crash", "panic", "vmcore", "dump", "内核崩溃", "oops"]
scripts:
  - scripts/collect-dump.sh
  - scripts/analyze-bt.py
---

# Kernel Crash Analysis

分析内核 crash 时：

1. **收集 dump** — 运行 `scripts/collect-dump.sh <vmcore_path>`
   - 提取 crash dump 关键信息
   - 输出到 /tmp/crash-data/

2. **分析 backtrace** — 运行 `python3 scripts/analyze-bt.py`
   - 解析调用栈
   - 识别故障模块和函数
   - 输出根因分析

3. **查阅参考** — 如需了解常见 panic 类型，参见 `references/common-panics.md`

4. **总结报告** — 向用户说明：
   - 崩溃发生在哪个模块
   - 可能的根因
   - 建议的修复方向
