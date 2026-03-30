---
name: git-workflow
description: Git 工作流规范，提交、分支和 PR 标准
type: skill
trigger:
  type: keyword
  keywords: ["commit", "git push", "create branch", "merge", "提交代码"]
scripts: []
---

# Git Workflow

- **提交信息**：使用 conventional commits 格式（feat:、fix:、docs: 等）
- **分支**：从 main 创建 feature 分支，不直接提交 main
- **推送前**：跑测试、检查 lint、review diff
- **PR 描述**：包含改了什么、为什么改、怎么测试
