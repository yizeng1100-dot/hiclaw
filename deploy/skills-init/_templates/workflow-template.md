---
name: your-workflow-name
description: 一句话描述这个 workflow 的完整流程
type: workflow
trigger:
  type: keyword
  keywords: ["关键词1", "关键词2"]
depends_on:
  - skill-a
  - skill-b
---

# Workflow 名称

## 流程概览
Step 1 → Step 2 → Step 3 → 输出报告

## 详细步骤

### Step 1: 描述
触发 `skill-a`
- 输入：xxx
- 输出：xxx

### Step 2: 描述
触发 `skill-b`
- 输入：上一步的输出
- 输出：xxx

### Step 3: 综合报告
汇总以上结果。
