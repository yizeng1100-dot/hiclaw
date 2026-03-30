---
name: code-review
description: 执行深度代码审查，检查 bug、安全、性能和可读性
type: skill
trigger:
  type: keyword
  keywords: ["code review", "review code", "审查代码", "代码审查"]
scripts: []
---

# Code Review

执行代码审查时，按以下顺序检查：

1. **读完整 diff** — 先通览全貌，再逐个评审
2. **检查 bug** — 逻辑错误、边界条件、空指针
3. **检查安全** — 注入、越权、数据泄露
4. **检查性能** — N+1 查询、不必要的分配、缺失缓存
5. **检查可读性** — 命名、结构、必要的注释
6. **给出可操作建议** — 具体修复方案，不只是"这不对"

格式：使用 `file:line` 内联注释引用每个问题。
