# 定时任务中心 —— 文档索引

HiClaw 平台的"按时间触发 shell 命令"功能，独立于 agent 定时任务。

面向对象和入口：

- **用户** → [USER_GUIDE.md](./USER_GUIDE.md)（怎么用）
- **开发者** → [DESIGN.md](./DESIGN.md)（架构、数据模型、API、决策记录）
- **平台运维** → [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)（排查手册、SQL、迁移）

## 当前状态

- **版本**：P1 设计确认中
- **分支**：`feat/command-scheduler`
- **日期**：2026-04-15
- **代码位置**：`custom/command_scheduler/`（待实现）
- **前端位置**：`frontend/src/components/features/custom/command-scheduler/`（待实现）

## 快速链接

| 我想… | 去看 |
|------|-----|
| 知道这是什么 | [DESIGN.md §1](./DESIGN.md#1-背景) |
| 新建一个定时任务 | [USER_GUIDE.md §3](./USER_GUIDE.md#3-新建任务) |
| 理解节假日策略 | [DESIGN.md §5.4](./DESIGN.md#54-节假日策略应用) |
| 排查为什么任务没跑 | [TROUBLESHOOTING.md §症状1](./TROUBLESHOOTING.md#症状-1任务到点不触发) |
| 查 SQL / schema | [TROUBLESHOOTING.md](./TROUBLESHOOTING.md#数据库-schema-速查) |
| 看当初为什么这么设计 | [DESIGN.md §2 ADR](./DESIGN.md#2-决策记录architecture-decision-records) |
| 看路线图 | [DESIGN.md §9](./DESIGN.md#9-分期和路线图) |
