# 定时任务中心 —— 设计文档

> **Module**: `custom/command_scheduler/`
> **Frontend route**: `/command-scheduler`
> **Owner (HiClaw)**: Platform team
> **Source user**: 某部门原有"定时任务管理系统"使用者（参见下方背景）
> **Status**: P1 设计确认中 · 2026-04-15
> **文档分区**:
> - §1 – §3：背景和结论（产品 + 用户可读）
> - §4 – §9：架构和实现（开发者必读）
> - §10 – §12：运维、故障排查、附录

---

## 1. 背景

### 1.1 为什么做

某部门为 HR 等业务线开发了一个 Windows 桌面的"定时任务管理系统"，用于跑数据通报、会议问题跟踪、体检数据回传等周期性脚本。截图里一共 5 条任务（【正式】NPS 定制通报、项目办公室会议问题跟踪、催缴收集信息、体检交付、端午剂会监督等），由 4 个启用 + 1 个停用组成。

他们希望把这套能力"搬"到 HiClaw 平台上做成**平台级功能**，未来代替他们原有的那套系统，好处：
- 不用他们再维护单独的 Windows 程序 / 数据库
- 统一平台账号、日志、监控
- 可以复用 HiClaw 的 sandbox 隔离能力，脚本不会污染主机
- 未来可以和 HiClaw 的 Chatbot / Agent 打通（比如聊天里问"今天 NPS 通报跑成功了吗"）

### 1.2 使用者

- 主要用户：**该部门的工程师和运维**
- 次要用户：HiClaw 其他部门的人，可以查看任务、查询节假日，但**不做权限隔离**（P1 全局共享）

### 1.3 范围

**在范围内 (P1)**
- 任务 CRUD（新建 / 编辑 / 删除 / 启停）
- 调度类型：一次性 / 每天 / 每周 / 每月 / 每年
- 在 HiClaw sandbox 里执行 Linux shell 命令
- 节假日（国务院数据预置 + 用户自定义）+ 节假日策略
- 月历视图 + 近期执行计划
- 单次执行日志 / 历史 / 重跑
- Windows 命令"暂存"模式（只存配置，不执行）
- `【正式】` / `【测试】` 环境标签

**不在范围内**
- Windows 命令真实执行（需要单独的 Windows Runner 组件，P2+）
- 用户 / 部门权限隔离（P2+）
- 失败自动重试（P2+）
- 跨 HiClaw sandbox 的脚本文件同步（P3+）
- 告警通知（邮件 / 企业微信 / 钉钉，P3+）

### 1.4 和现有 "scheduled tasks"（agent 触发）的区别

HiClaw 已经在 `custom/scheduled_tasks/` 里有一套"定时触发 agent"的功能（在 `task-center` 里可见）。两者的关系：

| 维度 | `custom/scheduled_tasks/` 旧 | `custom/command_scheduler/` 新 |
|------|---------------------------|----------------------------|
| 触发体 | HiClaw agent（对话） | 一段 shell 命令 |
| 存储表 | `schedules` / `fires` | `command_schedules` / `command_fires` |
| 入口 | Task Center → Scheduled Tasks tab | Sidebar → Command Scheduler |
| 节假日 | ❌ 无 | ✅ 有 |
| API 前缀 | `/api/v1/scheduled-tasks` | `/api/v1/command-schedules` |
| APScheduler | **共用同一个实例** | **共用同一个实例** |
| 目的 | 让 agent 在约定时间自动跑一个 workflow | 让 shell 脚本在约定时间执行并记录日志 |

**共用底座**：APScheduler 只有一个实例，两套逻辑各自注册自己的 job。出问题便于统一排查，不会互相污染（AP 的 job 靠 id 隔离）。

---

## 2. 决策记录（Architecture Decision Records）

按时间顺序记录所有拍板过的关键决策，方便后面有人问"当初为什么这么做"。

### ADR-01 独立模块 vs 扩展旧模块

**决策**：独立模块 `custom/command_scheduler/`，独立表，独立路由前缀，但**共用 APScheduler**。

**背景**：旧的 `scheduled_tasks` 绑定到 agent 触发；新需求是跑 shell 命令。两者数据模型差别大（命令、日志路径、节假日策略…），硬塞在同一张表会产生大量 nullable 字段。

**考虑的方案**：
- A. 独立模块，共用 APScheduler ✅（采纳）
- B. 完全独立（独立 APScheduler 实例） —— 隔离更彻底，但要管两个 scheduler 生命周期，调试成本高
- C. 扩展旧模块 —— schema 会被污染，职责混乱

**理由**：A 在"隔离"和"简单"之间平衡最好。APScheduler 本身是个异步事件循环，多挂几个 job 没有副作用。

### ADR-02 Sandbox 执行策略

**最终决策（2026-04-15 实现阶段修正）**：P1 用 **`asyncio.create_subprocess_shell` 直接 fork 子进程**（`custom/command_scheduler/runners.py::subprocess_runner`）。命令以 HiClaw 后端进程为父进程直接执行。

**为什么原计划行不通**：
P1 原本计划复用 HiClaw 的 `ProcessSandboxService`，作为一个常驻的 shell-exec sandbox。**实现时发现这个假设错了** —— 该 service 的 `start_sandbox` 实际上是启动一个 **agent-server HTTP 进程**（见 `openhands/app_server/sandbox/process_sandbox_service.py::_start_agent_process`），没有 `exec_command` 接口。Agent 里跑 shell 命令是通过 agent-server 的 bash tool HTTP API 走的，对定时任务 dispatch 是个过重且别扭的路径。

**替代方案评估**：
- A. 直接 `subprocess.create_subprocess_shell`（采纳）—— 简单、0 额外依赖、符合 P1 范围
- B. 借道 agent-server 的 bash tool —— 每条命令要开/复用 HiClaw conversation，延迟和复杂度都不值
- C. 自己做一个 shell-exec 专用 sandbox（systemd-nspawn / cgroup / pid namespace）—— P2+ 的事
- D. Docker 容器执行 —— 要 docker daemon，内部工具不值这个依赖

**用户明确同意这条路**（2026-04-15 对话）：
> "用 HiClaw sandbox 先试一下，不行再进程级"

现在就是"不行"的情况，进程级是明确的兜底。

**安全和边界**（见 §11）：subprocess 和 HiClaw 后端共享权限，是**部门内部工具的信任模型**。没有做 cgroup / seccomp / chroot 限制。不要把这套东西暴露到公网。

**venv 和工作目录**：`subprocess_runner` 不强制工作目录；每条任务自己在命令里 `cd` 或用绝对路径。预装 venv 的事情降级成"给用户一个推荐路径（`/opt/hiclaw/command_scheduler/venv`），让他们自己按需建/维护"。**P1 不再由 HiClaw 自动 provision venv**。

**未来升级路径**（P2+）：`custom/command_scheduler/sandbox_manager.py` 保留为 stub，`runners.py::sandbox_runner` 也保留。将来做了专用 shell-exec sandbox，只需填实 `sandbox_manager.exec_in_sandbox` 并在 `fire.py` 里把 `subprocess_runner` 换成 `sandbox_runner`，其他代码不动。

### ADR-03 venv 预装范围

**最终决策（2026-04-15 修正，随 ADR-02 一起调整）**：P1 **不自动 provision venv**。用户自己在部署 HiClaw 的机器上装任何需要的 Python 环境，命令里按需 `source xxx/bin/activate` 即可。

**为什么变了**：ADR-02 从 "HiClaw sandbox 常驻 + 预装 venv" 降级到了 "subprocess 直跑"，既然不是在隔离 sandbox 里，就没必要让 HiClaw 自己建 venv —— 部门的脚本本来就会依赖系统 Python / 已有 venv，强行预装一个新 venv 反而增加环境维护成本。

**推荐路径（文档引导）**：
- 脚本统一放 `/opt/hiclaw/command_scheduler/workspace/{subfolder}/`
- 如果要 Python venv，部署时 `python -m venv /opt/hiclaw/command_scheduler/venv` 手动建，然后 `pip install requests httpx python-dateutil pyyaml openpyxl pandas`（或任何业务需要的包）
- USER_GUIDE.md 会把这个路径作为示例，但不是强制约定

**备选（被否决）**：
- A. 空 venv 自动建 —— 用户还是要自己 pip install，不如直接让他们全部手动
- B. 基础包预装（原方案） —— P1 sandbox 已被砍，失去了"预装一次到处跑"的价值
- C. 重型预装 —— 同上

### ADR-04 节假日策略（升级原系统）

**决策**：加 `holiday_policy` 字段，枚举 `normal / skip / run_before / run_after`，默认 `normal`。

**背景**：原系统的节假日管理只有"查询工具"，没有策略（图 3）。HiClaw 趁这次做一次升级，让任务可以配置节假日行为。

**字段含义**：
- `normal` —— 照常运行（和原系统一致）
- `skip` —— 节假日当天跳过
- `run_before` —— 节假日**前一个工作日**执行一次，节假日当天和后续节假日**不再执行**
- `run_after` —— 延后到节假日**后第一个工作日**执行

**理由**：节假日表反正要做，顺手加个策略字段成本很低，但给部门提供了新能力（例如 "NPS 通报在国庆前一天就推出"）。

### ADR-05 Windows 命令 —— Pull-model Runner（P2 落地）

**P1 最终决策**：`shell_kind=windows` 任务只存配置，触发时 `command_fires` 记 `status=skipped, reason=windows_not_supported`。UI 上标记灰色 `⚠ Windows 暂存`。

**P2 升级（2026-04-16）**：Windows 任务由运行在 Windows 机器上的独立 runner 脚本负责执行。**Pull 模型** —— runner 主动出网轮询 HiClaw 获取任务，执行完回传结果。

**触发链路（P2）**：
1. 调度时刻到，executor 创建 fire 行，状态标为 `pending_runner`（P1 的 `skipped: windows_not_supported` 路径被移除）
2. Windows 上的 runner 每 10s 调 `GET /api/v1/command-scheduler/windows-runner/pending` 拿到所有 `pending_runner` 的 fire + schedule 命令
3. 逐个 `POST /windows-runner/fires/{id}/start` 抢占（冲突返回 409，换下一个），然后本地 `subprocess.run(command, shell=True)` 执行
4. 执行完 `POST /windows-runner/fires/{id}/complete` 回传 exit_code + stdout + stderr + status，服务端写全量日志 + DB tail，转成 `success/failed/timeout`
5. 每次循环 `POST /windows-runner/heartbeat`，UI 能看到 runner 是否在线

**为什么 Pull 不 Push**：
- 推模型（AWS 主动 SSH/WinRM 到 Windows）需要 Windows 暴露入站端口，跨 NAT / 公司内网 / VPN 全都要配防火墙 —— 合规门槛高
- 拉模型只要 Windows 能**出站访问 HiClaw**，哪怕换 Wi-Fi / 出差 / 家用路由器都能跑（2026-04-16 实测：用户从 123.138.24.219 出网访问 AWS 可达，反向 22/3389 全部 timeout → pull 是唯一选项）
- Runner 是单文件 Python，部署简单，可 Task Scheduler / NSSM 开机自启

**认证**：可选的 `HICLAW_WINDOWS_RUNNER_KEY` 环境变量。设置则 runner 请求必须带 `X-HiClaw-Runner-Key` header，不匹配 401。未设置则关闭 auth（纯内网部署可用）。

**多 runner / 多机器**：
- 当前支持"一组 windows 任务 + 一组 runner"。Fire 抢占靠 `/start` 接口的 409 race guard，多个 runner 并行抢不会重复执行
- 未来多 Windows 机器路由：加 `windows_host_tag` 字段给 schedule，runner 带 `--tags a,b` 启动只拉匹配的 fire —— P3

**相关文件**：
- `custom/command_scheduler/router.py` — 5 个 `/windows-runner/*` 端点
- `custom/command_scheduler/executor.py` — `shell_kind == 'windows'` 分支
- `tools/windows_runner/hiclaw_windows_runner.py` — runner 脚本
- `tools/windows_runner/README.md` — 部署手册

### ADR-06 任务 ID 生成方式

**决策**：系统生成 32 位 hex（`secrets.token_hex(16)`），不沿用原系统的 `task001` 短串。

**理由**：
- 避免和旧系统任务 ID 冲突（部门不迁移数据）
- UUID/hex 无碰撞
- 用户看得到的是**任务名称**，不是 ID，所以 ID 长短不重要

### ADR-07 日志存储

**决策**：
- **数据库**：`command_fires` 表存 `exit_code`、`stdout_tail`（末尾 ~200 行，最多 32 KB）、`stderr_tail`（同）
- **文件**：全量输出写到 `~/.openhands/command_scheduler/logs/{task_id}/{fire_id}.log`
- **清理**：每天凌晨 03:00 扫一次，保留 30 天，超期删除（DB 和文件同步清理）

**理由**：DB 摘要让 UI 快速展示，文件全量用于深度排查。30 天是经验值，内部工具不需要审计合规。

### ADR-08 并发冲突

**决策**：**串行**。如果任务上一次还在跑，当前触发**跳过**（记 `status=skipped, reason=prev_running`），不排队不并行。

**理由**：
- 内部工具，大部分脚本执行时间远小于调度间隔
- 并行和排队都会带来状态一致性问题（同一脚本同时读写一个 Excel 文件就坏了）
- 用户看到 skipped 会自己去调调度间隔或优化脚本

### ADR-09 超时处理

**决策**：`max_duration_sec` 是**硬超时**。到点发 `SIGTERM`，等 2 秒后发 `SIGKILL`。`command_fires` 记 `status=timeout`。

**理由**：防止失控脚本永久占用 sandbox 资源。原系统的 300 秒是个合理默认。

### ADR-10 权限

**决策**：P1 **全局共享**，所有登录用户都能看、都能编辑。

**理由**：
- 部门内部使用，用户基数小
- 加权限会引入用户/角色模型，成本大
- P2 后期再根据反馈细化

---

## 3. 功能总览（给用户看）

### 3.1 主要页面

```
┌───────────────────────────────────────────────────────────┐
│  定时任务管理中心                              [+新建任务] │
├───────────────────────────────────────────────────────────┤
│  [总数:5]  [执行中:0]  [已启用:4]  [已停用:1]             │
├───────────────────────────────────────────────────────────┤
│  [全部] [我的] [正式] [测试]    搜索: [________]          │
│                                                            │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐                │
│  │ 任务卡片   │ │ 任务卡片   │ │ 任务卡片   │                │
│  │  ...      │ │  ...      │ │  ...      │                │
│  └───────────┘ └───────────┘ └───────────┘                │
│  ┌───────────┐ ┌───────────┐                              │
│  │ 任务卡片   │ │ 任务卡片   │                              │
│  └───────────┘ └───────────┘                              │
├─────────────────────────────┬─────────────────────────────┤
│  📅 2026-04                  │  📋 近 7 日执行计划          │
│  S M T W T F S               │  04-15 02:30 数据备份       │
│  · · · · · · ·               │  04-16 09:00 NPS 通报       │
│  (节假日红色高亮)              │  04-17 18:00 催缴提醒       │
│  点击日期查看当天任务           │  ...                        │
└─────────────────────────────┴─────────────────────────────┘
```

### 3.2 任务卡片

```
┌──────────────────────────────┐
│ 【正式】NPS 定制通报任务  🟢 │  ← 环境标签 + 启停开关
│ 每天 09:00 · 节前提前         │  ← 调度摘要 + 节假日策略
│ ✓ 09:00 成功 (0.8s)           │  ← 最后一次运行
│ 下次: 04-16 09:00             │  ← 下次触发
│ [▶执行] [📝编辑] [📜历史]      │
└──────────────────────────────┘
```

### 3.3 新建/编辑任务弹窗

```
┌───────────────────────────────────┐
│  新建任务                          │
├───────────────────────────────────┤
│  任务名称:  [________________]     │
│  环境标签:  (●) 正式  ( ) 测试     │
│  命令类型:  (●) Linux ( ) Windows  │
│                                    │
│  调度类型:  [每天 ▾]                │
│  时间:      [09:00]                │
│  (每周:选星期) (每月:选日期)        │
│                                    │
│  节假日策略:[照常 ▾]                │
│  ├─ 照常                           │
│  ├─ 跳过节假日                     │
│  ├─ 提前到前一工作日                │
│  └─ 延后到后一工作日                │
│                                    │
│  最大执行时长: [300] 秒             │
│                                    │
│  执行命令:                         │
│  ┌───────────────────────────────┐ │
│  │ cd /opt/hiclaw/scripts/nps    │ │
│  │ source venv/bin/activate      │ │
│  │ python send_nps.py --prod     │ │
│  └───────────────────────────────┘ │
│                                    │
│  [保存]  [取消]                    │
└───────────────────────────────────┘
```

### 3.4 节假日管理页面

单独一个 tab / modal：
- **预置节假日**：国务院数据（只读）
- **自定义节假日**：用户可以增删
- **调休工作日**：用户可以增删（标记某个周六为工作日）
- **日期检查工具**：输入日期 → 返回"工作日 / 节假日 / 调休工作日"

---

## 4. 数据模型

数据库：继续用 HiClaw 的 SQLite `~/.openhands/openhands.db`。新增 3 张表。

### 4.1 `command_schedules`

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | TEXT PK | ❌ | `secrets.token_hex(16)` 32 位 hex |
| `name` | TEXT | ❌ | 任务显示名称，例 `NPS 定制通报任务` |
| `env_tag` | TEXT | ❌ | `formal` / `test`，默认 `formal` |
| `shell_kind` | TEXT | ❌ | `linux` / `windows`，默认 `linux` |
| `kind` | TEXT | ❌ | `one_time` / `daily` / `weekly` / `monthly` / `yearly` |
| `cron_expr` | TEXT | ✅ | `daily/weekly/monthly/yearly` 用，存 APScheduler cron 字符串（例 `0 9 * * *`） |
| `run_at` | TEXT (ISO) | ✅ | `one_time` 用，存触发时刻 |
| `command` | TEXT | ❌ | 要执行的命令（可多行） |
| `working_dir` | TEXT | ✅ | 执行时 `cd` 到的目录，默认 `/opt/hiclaw/command_scheduler/workspace` |
| `max_duration_sec` | INTEGER | ❌ | 硬超时，默认 300 |
| `holiday_policy` | TEXT | ❌ | `normal` / `skip` / `run_before` / `run_after`，默认 `normal` |
| `log_path` | TEXT | ✅ | 用户自定义日志文件路径（可选，默认用系统路径） |
| `enabled` | BOOLEAN | ❌ | 启停，默认 true |
| `created_at` | TEXT (ISO) | ❌ | |
| `updated_at` | TEXT (ISO) | ❌ | |
| `last_fire_at` | TEXT (ISO) | ✅ | 上次执行开始时间（冗余，加速列表） |
| `next_fire_at` | TEXT (ISO) | ✅ | 下次执行时间（冗余，由 AP job 同步） |

**索引**：`idx_cs_enabled`，`idx_cs_env_tag`，`idx_cs_next_fire_at`

### 4.2 `command_fires`

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `id` | TEXT PK | ❌ | hex32 |
| `schedule_id` | TEXT FK | ❌ | → `command_schedules.id`（ON DELETE CASCADE）|
| `started_at` | TEXT (ISO) | ❌ | |
| `completed_at` | TEXT (ISO) | ✅ | |
| `status` | TEXT | ❌ | `running` / `success` / `failed` / `timeout` / `skipped` |
| `skip_reason` | TEXT | ✅ | `prev_running` / `holiday_skip` / `windows_not_supported` |
| `exit_code` | INTEGER | ✅ | 进程退出码 |
| `stdout_tail` | TEXT | ✅ | 最后 ~200 行，截断到 32KB |
| `stderr_tail` | TEXT | ✅ | 同上 |
| `log_file_path` | TEXT | ✅ | 全量日志文件路径 |
| `trigger_source` | TEXT | ❌ | `scheduled` / `manual` |

**索引**：`idx_cf_schedule_id_started_at`（用于"最近 5 次"查询）

### 4.3 `holidays`

| 字段 | 类型 | 可空 | 说明 |
|------|------|------|------|
| `date` | TEXT PK | ❌ | `YYYY-MM-DD` |
| `name` | TEXT | ❌ | 例 `春节` `劳动节` `自定义-工厂休` |
| `kind` | TEXT | ❌ | `holiday` / `makeup_workday` |
| `source` | TEXT | ❌ | `preset` / `user` |
| `created_at` | TEXT (ISO) | ❌ | |

**索引**：`idx_holidays_date`（PK 已覆盖）

**预置数据**：`custom/command_scheduler/data/holidays_cn_2026.yaml`（以及 2027+，每年手动更新）。启动时导入，`source='preset'`。

---

## 5. 执行模型（核心）

### 5.1 Sandbox 生命周期

```
HiClaw 后端启动
   ↓
[lazy init 触发]：第一次任务开始执行时才创建 sandbox
   ↓
_get_or_start_scheduler_sandbox()
   ├─ 没有 sandbox → 调用 ProcessSandboxService.start_sandbox(sandbox_id="cmd-scheduler")
   ├─ 有且 RUNNING → 直接用
   ├─ 有但 ERROR/STOPPED → 销毁 + 重建
   └─ 启动完成后 → 执行 _provision_venv（见 §5.2）
   ↓
每次执行任务：
   sandbox.exec_command(cmd, cwd=working_dir, timeout=max_duration_sec)
   ↓
HiClaw 后端停止 / 重启：
   sandbox 进程被杀，下次启动时 lazy 重建
```

**关键点**：
- Sandbox ID 固定为 `"cmd-scheduler"`，保证只有一个
- 不随 HiClaw 启动自动创建，**第一次调度触发**时 lazy 初始化（避免空跑开销）
- 失败重建有**互斥锁**，防止并发触发时多个任务抢着起 sandbox

### 5.2 venv 预装

Sandbox 首次启动后执行一次性 provisioning：

```bash
# /opt/hiclaw/command_scheduler/venv/
python -m venv /opt/hiclaw/command_scheduler/venv
/opt/hiclaw/command_scheduler/venv/bin/pip install --no-cache-dir \
    requests httpx python-dateutil pyyaml openpyxl pandas
# 标记文件，避免重复 provision
touch /opt/hiclaw/command_scheduler/venv/.provisioned
```

用户命令里可以 `source /opt/hiclaw/command_scheduler/venv/bin/activate` 或直接 `/opt/hiclaw/command_scheduler/venv/bin/python` 调 venv Python。

### 5.3 命令 dispatch

```python
async def dispatch(schedule: CommandSchedule) -> CommandFire:
    fire = CommandFire(
        schedule_id=schedule.id,
        started_at=now(),
        status='running',
        trigger_source='scheduled',
    )
    await save(fire)

    # Pre-check: concurrent guard
    if await any_running_fire_for(schedule.id):
        fire.status = 'skipped'; fire.skip_reason = 'prev_running'
        return await save(fire)

    # Pre-check: Windows
    if schedule.shell_kind == 'windows':
        fire.status = 'skipped'; fire.skip_reason = 'windows_not_supported'
        return await save(fire)

    # Pre-check: holiday policy
    if not should_run_today(schedule, date.today()):
        fire.status = 'skipped'; fire.skip_reason = 'holiday_skip'
        return await save(fire)

    sandbox = await get_or_start_scheduler_sandbox()
    try:
        result = await sandbox.exec_command(
            schedule.command,
            cwd=schedule.working_dir,
            timeout=schedule.max_duration_sec,
        )
        fire.exit_code = result.exit_code
        fire.stdout_tail = tail(result.stdout, lines=200, max_bytes=32*1024)
        fire.stderr_tail = tail(result.stderr, lines=200, max_bytes=32*1024)
        fire.log_file_path = write_full_log(fire.id, result)
        fire.status = 'success' if result.exit_code == 0 else 'failed'
    except TimeoutError:
        fire.status = 'timeout'
    except Exception as e:
        fire.status = 'failed'
        fire.stderr_tail = repr(e)
    finally:
        fire.completed_at = now()
        await save(fire)
    return fire
```

### 5.4 节假日策略应用

```python
def should_run_today(schedule, today: date) -> bool:
    if schedule.holiday_policy == 'normal':
        return True
    is_holiday = holidays_service.is_holiday(today)
    if schedule.holiday_policy == 'skip':
        return not is_holiday
    if schedule.holiday_policy == 'run_before':
        # 今天是工作日 且 (今天是最后一个节前工作日 → 要跑; 不是 → 照常跑)
        if is_holiday:
            return False
        # 补偿：如果明天是节假日，且明天原本是 schedule 该跑的日子，就今天跑一次"提前的"
        # 实际的"提前一天"补偿由 pre-scan 机制在每天 00:00 扫一遍触发，见 §5.5
        return True
    if schedule.holiday_policy == 'run_after':
        # 今天是节假日 → 跳过; 今天是节后第一个工作日 → 正常跑 + 补跑
        if is_holiday:
            return False
        return True
```

### 5.5 节假日策略的补偿扫描

`run_before` 和 `run_after` 需要一个每日 00:01 的"扫描 job"：

- **run_before**：扫明天是否节假日 + 原本该跑的任务 → 在今天对应时刻额外触发一次
- **run_after**：扫今天是否节后第一工作日 + 昨天原本该跑的任务 → 在今天对应时刻额外触发一次

扫描 job 也挂在共用 APScheduler 上，cron `1 0 * * *`。

### 5.6 日志写入

- **DB 字段 `stdout_tail/stderr_tail`**：字节截断到 32KB，按行从末尾保留 200 行（先按 bytes 切再按 lines 切）
- **全量文件**：`~/.openhands/command_scheduler/logs/{schedule_id}/{fire_id}.log`
- **格式**：
  ```
  === STARTED 2026-04-15T09:00:00+08:00 ===
  [stdout]
  (全量 stdout)
  [stderr]
  (全量 stderr)
  === COMPLETED 2026-04-15T09:00:00.83+08:00 exit=0 ===
  ```
- **清理 job**：每天 03:00 扫一次，删除 `started_at < now - 30d` 的 fires（DB + 文件）

---

## 6. API 设计

所有路由挂 `/api/v1/command-schedules`（除节假日 API 挂 `/api/v1/command-scheduler/holidays`）。

### 6.1 Schedules CRUD

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/command-schedules` | 列出所有任务，支持 `?env_tag=formal&enabled=true&q=搜索词` |
| GET | `/api/v1/command-schedules/{id}` | 任务详情（带最近 5 次 fires） |
| POST | `/api/v1/command-schedules` | 新建任务 |
| PUT | `/api/v1/command-schedules/{id}` | 编辑任务（全量字段） |
| PATCH | `/api/v1/command-schedules/{id}` | 局部更新（例 `{"enabled": false}`） |
| DELETE | `/api/v1/command-schedules/{id}` | 删除任务（级联删 fires + 日志文件） |
| POST | `/api/v1/command-schedules/{id}/run` | 立即执行一次（`trigger_source=manual`） |
| POST | `/api/v1/command-schedules/pause-all` | 暂停全部（所有任务 `enabled=false`） |
| POST | `/api/v1/command-schedules/resume-all` | 恢复全部 |
| GET | `/api/v1/command-schedules/{id}/fires` | 分页执行历史，`?limit=20&offset=0` |
| GET | `/api/v1/command-schedules/fires/{fire_id}` | 单次 fire 详情（摘要） |
| GET | `/api/v1/command-schedules/fires/{fire_id}/log` | 下载全量日志文件 |

### 6.2 Holidays

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/command-scheduler/holidays?year=2026` | 列出整年的节假日 + 调休工作日 |
| POST | `/api/v1/command-scheduler/holidays` | 新增自定义节假日 `{date, name, kind}` |
| DELETE | `/api/v1/command-scheduler/holidays/{date}` | 删除（只能删 `source=user` 的） |
| GET | `/api/v1/command-scheduler/holidays/check/{date}` | 查询日期 → `{is_holiday, is_makeup_workday, is_workday, name}` |

### 6.3 请求/响应示例

**POST /api/v1/command-schedules**
```json
{
  "name": "【正式】NPS 定制通报任务",
  "env_tag": "formal",
  "shell_kind": "linux",
  "kind": "daily",
  "cron_expr": "0 9 * * *",
  "command": "cd /opt/hiclaw/command_scheduler/workspace/nps\nsource /opt/hiclaw/command_scheduler/venv/bin/activate\npython send_nps.py --prod",
  "max_duration_sec": 300,
  "holiday_policy": "run_before"
}
```

**响应**
```json
{
  "id": "a3f8c1e2...",
  "name": "【正式】NPS 定制通报任务",
  "next_fire_at": "2026-04-16T09:00:00+08:00",
  ...
}
```

---

## 7. 前端设计

### 7.1 路由

| 路径 | 文件 | 说明 |
|------|------|------|
| `/command-scheduler` | `frontend/src/routes/command-scheduler.tsx` | 主页 |
| `/command-scheduler/holidays` | 同上，内嵌 tab / modal | 节假日管理 |

### 7.2 Sidebar 入口

在 `frontend/src/components/shared/buttons/` 下新建 `command-scheduler-button.tsx`，加到 `sidebar.tsx` 里，放在 `TaskCenterButton` 和 `ChatButton` 之间。图标用日历/闹钟 SVG。

### 7.3 组件树

```
CommandSchedulerPage
├── Header (title + [+新建任务] + [节假日管理] + [暂停全部])
├── StatsBar (4 个统计卡片)
├── FilterBar (tab + 搜索)
├── SplitLayout
│   ├── TaskGrid (左)
│   │   └── TaskCard × N
│   └── SidePanel (右)
│       ├── MonthCalendar
│       └── UpcomingRuns
└── Modals
    ├── EditTaskModal
    ├── TaskHistoryModal
    └── HolidayManagerModal
```

### 7.4 复用现有组件

- `MarkdownRenderer` —— 任务详情里展示命令
- 暗色主题样式 —— 和 task-center / chat 保持一致
- `custom-scrollbar` 类
- 确认 dialog 组件

### 7.5 API client

`frontend/src/api/custom-skill-service/command-scheduler.api.ts`

```ts
export class CommandSchedulerService {
  static async list(filter?: {env_tag?: string; enabled?: boolean; q?: string}): Promise<CommandSchedule[]>
  static async get(id: string): Promise<CommandScheduleDetail>
  static async create(payload: CommandScheduleInput): Promise<CommandSchedule>
  static async update(id: string, payload: CommandScheduleInput): Promise<CommandSchedule>
  static async delete(id: string): Promise<void>
  static async run(id: string): Promise<CommandFire>
  static async pauseAll(): Promise<void>
  static async resumeAll(): Promise<void>
  static async listFires(id: string, opts?: {limit?: number; offset?: number}): Promise<CommandFire[]>
  // holidays
  static async listHolidays(year: number): Promise<Holiday[]>
  static async addHoliday(h: {date: string; name: string; kind: string}): Promise<Holiday>
  static async deleteHoliday(date: string): Promise<void>
  static async checkDate(date: string): Promise<HolidayCheck>
}
```

---

## 8. 模块文件布局

```
custom/command_scheduler/
├── __init__.py
├── README.md                 ← 链接到本文档
├── db.py                     ← SQLAlchemy models
├── schemas.py                ← Pydantic DTOs
├── router.py                 ← FastAPI router (挂 /api/v1/command-schedules)
├── service.py                ← CRUD 服务层
├── executor.py               ← 命令执行逻辑（§5.3）
├── sandbox_manager.py        ← Process sandbox 生命周期管理
├── scheduler_integration.py  ← APScheduler 挂载 / 卸载 job
├── holidays.py               ← 节假日查询 + 策略
├── log_io.py                 ← 日志文件读写 + 清理
├── migrations/
│   └── 001_initial.sql       ← 建 3 张表
└── data/
    ├── holidays_cn_2026.yaml ← 预置节假日
    └── holidays_cn_2027.yaml

custom/docs/command_scheduler/
├── DESIGN.md                 ← 本文档
├── USER_GUIDE.md             ← 面向用户的快速上手
└── TROUBLESHOOTING.md        ← 运维故障排查手册

frontend/src/
├── routes/command-scheduler.tsx
├── components/features/custom/command-scheduler/
│   ├── command-scheduler-page.tsx
│   ├── stats-bar.tsx
│   ├── filter-bar.tsx
│   ├── task-grid.tsx
│   ├── task-card.tsx
│   ├── edit-task-modal.tsx
│   ├── task-history-modal.tsx
│   ├── month-calendar.tsx
│   ├── upcoming-runs.tsx
│   ├── holiday-manager-modal.tsx
│   └── use-command-scheduler.ts
├── components/shared/buttons/command-scheduler-button.tsx
└── api/custom-skill-service/command-scheduler.api.ts
```

---

## 9. 分期和路线图

### P1 —— 本次交付（计划 3-5 天）

核心落地：
- 后端 3 张表 + CRUD API + 节假日 API
- APScheduler 挂载（daily / weekly / monthly / yearly / one_time）
- Sandbox lazy init + venv provision + 命令 dispatch
- `holiday_policy = normal | skip` 可用；`run_before/run_after` 可配置但策略逻辑先用简单版（仅当天判断），补偿扫描 job 放 P2
- Windows 命令存而不跑（skipped）
- 日志 DB 摘要 + 文件全量 + 30 天清理
- 前端：sidebar 入口、主页、任务 CRUD 弹窗、节假日管理页、月历静态视图、执行历史弹窗
- 3 条 E2E 验收：创建 daily linux → 触发 → 看到 fire；创建 daily windows → 触发 → skipped；创建节假日 → check API 返回正确

### P2 —— 补强（1-2 天）

- `run_before / run_after` 的补偿扫描 job（§5.5）
- 失败重试策略（每条任务配 `retry_times`, `retry_interval_sec`）
- 月历"有任务的日期打点"+ 点击日期看当天任务
- 告警：失败时推送到企业微信/钉钉 webhook（可选配置）
- 任务复制 / 批量启停

### P3 —— 延伸（不定期）

- Windows Runner 接入：开独立 Go/Python 进程挂在 Windows 机器上，通过 HTTP 拉 pending 任务 + 回推结果
- 用户/部门权限隔离（基于 HiClaw 现有 user 模型）
- 脚本文件同步（UI 上传 .py 文件到 sandbox workspace，自动版本化）
- 任务依赖 DAG（task A 成功后触发 task B）
- 和 Chatbot 打通（"查询 NPS 今天跑得怎么样"）

---

## 10. 运维和故障排查

### 10.1 数据位置

| 什么 | 在哪 |
|------|------|
| 任务/fires/节假日 DB | `~/.openhands/openhands.db`（HiClaw 主库） |
| Sandbox workspace | `/opt/hiclaw/command_scheduler/workspace/`（HiClaw 主机） |
| venv | `/opt/hiclaw/command_scheduler/venv/` |
| 全量日志 | `~/.openhands/command_scheduler/logs/{schedule_id}/{fire_id}.log` |
| 节假日 yaml | `custom/command_scheduler/data/holidays_cn_YYYY.yaml` |

### 10.2 常见故障排查

#### 问题：任务没按时触发
```bash
# 1. 确认 APScheduler 是否活着
curl http://127.0.0.1:12000/api/v1/command-schedules/{id} | jq .next_fire_at
# next_fire_at 应在未来；如果是 null 或过去，说明 job 没挂上

# 2. 查后端 log
grep "command_scheduler" /tmp/openhands-12000.log | tail -30

# 3. 查 schedule 是否 enabled
sqlite3 ~/.openhands/openhands.db 'SELECT id,name,enabled,next_fire_at FROM command_schedules;'
```

#### 问题：任务触发但命令执行失败
```bash
# 1. 看 fire 摘要
curl http://127.0.0.1:12000/api/v1/command-schedules/{id}/fires?limit=5

# 2. 看全量日志
cat ~/.openhands/command_scheduler/logs/{id}/{fire_id}.log

# 3. 手工在 sandbox 里重现
# (TODO: 写一个 hiclaw-exec-in-sandbox CLI 工具)
```

#### 问题：Sandbox 挂了 / 启动失败
```bash
# 查 sandbox 状态
curl http://127.0.0.1:12000/api/v1/sandboxes | jq '.[] | select(.id=="cmd-scheduler")'

# 手动重启（删除后 lazy 重建）
curl -X DELETE http://127.0.0.1:12000/api/v1/sandboxes/cmd-scheduler

# 查 provision 是否完成
ls /opt/hiclaw/command_scheduler/venv/.provisioned
```

#### 问题：所有任务显示"已跳过 windows_not_supported"
- 检查 `shell_kind` 字段，应该是 `linux` 不是 `windows`
- UI 编辑时的单选按钮可能选错

#### 问题：节假日策略没生效
- 先用 `GET /api/v1/command-scheduler/holidays/check/{date}` 确认该日期是节假日
- 再看任务的 `holiday_policy` 字段
- P1 的 `run_before/run_after` 只在**当天**判断，**补偿扫描 job 在 P2 才完整**，P1 可能有漏触发

### 10.3 日常维护任务

- **每年 12 月**：更新 `custom/command_scheduler/data/holidays_cn_{nextyear}.yaml`
- **查 30 天外的历史**：日志已清理，只能看 DB 里的 fires 摘要
- **磁盘占用**：日志目录每月最大估算 ~几百 MB（假设每任务每天一次，每次 10 KB 日志）

---

## 11. 安全和边界

**信任模型**：`command_scheduler` 假设所有用户和命令**是可信的**。

**原因**：
- 部门内部工具，用户都是工程师
- Sandbox 是 Process 模式，和 HiClaw 主进程共享用户权限 —— 理论上 `rm -rf /` 能破坏 HiClaw 所在机器

**缓解措施（P1 放 TODO）**：
- Process sandbox 用单独 Linux 用户启动，限制权限
- 命令黑名单（`rm -rf`, `dd if=` 之类）
- Cgroup 限制 CPU/内存

**绝对不要做的**：
- 把 `/api/v1/command-schedules/*` 的 POST/DELETE 暴露到公网，未加认证
- 让 `command` 字段接受模板变量（容易 SQL/shell 注入）

---

## 12. 附录

### 12.1 国务院节假日 YAML 示例

```yaml
# custom/command_scheduler/data/holidays_cn_2026.yaml
year: 2026
holidays:
  - {date: "2026-01-01", name: "元旦"}
  - {date: "2026-02-01", name: "春节"}
  - {date: "2026-02-02", name: "春节"}
  - {date: "2026-02-03", name: "春节"}
  # ...
makeup_workdays:
  - {date: "2026-02-03", name: "春节调休上班"}
  # ...
```

### 12.2 典型用户命令示例

**HTTP API 调用类**：
```bash
cd /opt/hiclaw/command_scheduler/workspace/nps
/opt/hiclaw/command_scheduler/venv/bin/python send_nps.py --env prod
```

**Excel 处理类**：
```bash
cd /opt/hiclaw/command_scheduler/workspace/health
/opt/hiclaw/command_scheduler/venv/bin/python generate_health_report.py \
    --input /data/health.xlsx --output /tmp/health_report.pdf
```

**多步骤 pipeline**：
```bash
set -e
cd /opt/hiclaw/command_scheduler/workspace/collect
/opt/hiclaw/command_scheduler/venv/bin/python fetch_data.py
/opt/hiclaw/command_scheduler/venv/bin/python process_data.py
/opt/hiclaw/command_scheduler/venv/bin/python push_to_wecom.py
```

### 12.3 APScheduler 触发器对照

| `kind` | APScheduler Trigger | 说明 |
|--------|---------------------|------|
| `one_time` | `DateTrigger(run_date=run_at)` | 一次性，跑完自动移除 |
| `daily` | `CronTrigger.from_crontab("M H * * *")` | 每天 HH:MM |
| `weekly` | `CronTrigger.from_crontab("M H * * D")` | 每周某几天 |
| `monthly` | `CronTrigger.from_crontab("M H D * *")` | 每月某天 |
| `yearly` | `CronTrigger(year='*', month=M, day=D, hour=H, minute=M)` | 每年某日 |

### 12.4 术语对照

| HiClaw 术语 | 原系统术语 | 说明 |
|-------------|-----------|------|
| Schedule | 定时任务 | 任务定义 |
| Fire | 执行记录 | 单次运行 |
| env_tag | 【正式】/【测试】 | 环境标签 |
| shell_kind | (无) | Linux / Windows 区分 |
| holiday_policy | (无) | 节假日行为 |

### 12.5 和上游 OpenHands 的兼容性

本模块全部在 `custom/` 和 `frontend/src/{routes,components,api}/` 下，不修改 `openhands/` 目录。上游 rebase 时只需合并以下文件：
- `frontend/src/routes.ts`（加一行 route）
- `frontend/src/components/features/sidebar/sidebar.tsx`（加一个 button）
- `openhands/server/app.py`（`include_router(command_scheduler_router)`）

其他全部是新文件，无冲突。

---

**文档修订历史**

| 版本 | 日期 | 作者 | 变更 |
|------|------|------|------|
| 0.1 | 2026-04-15 | Claude + wq | 初稿，P1 范围敲定 |
