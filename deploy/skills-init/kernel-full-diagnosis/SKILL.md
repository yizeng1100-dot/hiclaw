---
name: kernel-full-diagnosis
description: 内核完整诊断流程，编排 crash 分析、稳定性检查和日志分析
type: workflow
trigger:
  type: keyword
  keywords: ["全面诊断", "完整检查", "full diagnosis", "全面排查"]
depends_on:
  - kernel-crash-analysis
  - stability-check
  - log-analysis
---

# Kernel Full Diagnosis

内核全面诊断流程，按顺序执行以下 skill：

## Step 1: 日志分析
触发 `log-analysis` skill
- 收集并分析系统日志
- 识别近期的错误和异常

## Step 2: 稳定性检查
触发 `stability-check` skill
- 检查 dmesg 错误
- 验证系统配置和资源状态

## Step 3: Crash 分析（如有 dump）
触发 `kernel-crash-analysis` skill
- 仅在存在 vmcore dump 时执行
- 分析 backtrace 定位根因

## Step 4: 综合报告
汇总以上所有结果，生成诊断报告：
- 发现的问题列表（按严重程度排序）
- 每个问题的可能原因
- 建议的修复方案
- 需要进一步排查的项目
