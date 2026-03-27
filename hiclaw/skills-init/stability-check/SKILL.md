---
name: stability-check
description: 系统稳定性检查，检测 dmesg 错误和内核配置问题
type: skill
trigger:
  type: keyword
  keywords: ["stability", "稳定性", "健康检查", "系统检查"]
scripts:
  - scripts/check-dmesg.sh
  - scripts/check-config.sh
---

# Stability Check

执行稳定性检查时：

1. **检查 dmesg** — 运行 `scripts/check-dmesg.sh`
   - 扫描近期内核错误和警告
2. **检查内核配置** — 运行 `scripts/check-config.sh`
   - 验证关键配置项
3. **总结** — 向用户报告发现的问题和建议
