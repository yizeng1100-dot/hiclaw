---
name: debug-helper
description: 系统化调试方法，从复现到修复的完整流程
type: skill
trigger:
  type: keyword
  keywords: ["debug", "调试", "排查", "troubleshoot", "not working", "为什么不行"]
scripts: []
---

# Debug Helper

调试问题时遵循以下流程：

1. **复现** — 确定触发 bug 的精确步骤
2. **隔离** — 找到最小的失败代码路径
3. **看日志** — 检查所有相关日志，不要猜
4. **查最近改动** — `git log --oneline -10` 和 `git diff`
5. **形成假设** — 明确说出你认为哪里出了问题，为什么
6. **验证假设** — 每次只改一个地方，确认效果
7. **修复并验证** — 确保修复不破坏其他功能
