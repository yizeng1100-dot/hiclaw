# 定时任务中心 —— 用户使用指南

> 给部门用户的快速上手文档。如果你想了解背后的架构请看 [DESIGN.md](./DESIGN.md)。

---

## 1. 这个工具是什么

HiClaw 的 **定时任务中心** 是一个"帮你每天/每周/每月自动跑脚本"的平台工具。你在网页上配好一个命令 + 触发时间，HiClaw 就会按时在后台沙箱里跑它，然后把结果和日志保存下来，方便你随时回看。

**典型用法**：
- 每天早上 9 点推送 NPS 通报
- 每周五 17:00 汇总加班数据
- 每月 1 号跑体检数据回传
- 春节前一天提前推一次催缴提醒

---

## 2. 进入页面

登录 HiClaw → 左侧栏找 🕐 定时任务中心 按钮 → 点进去。

页面布局：
- **顶部**：4 个统计卡（总数 / 执行中 / 已启用 / 已停用）
- **左侧**：任务卡片网格
- **右侧**：月历 + 最近 7 天执行计划
- **右上角**：`+新建任务` / `节假日管理` / `暂停全部`

---

## 3. 新建任务

点 `+新建任务` 打开弹窗，填 4 组字段：

### 3.1 基本信息
- **任务名称**：用你看得懂的中文。推荐加环境前缀，例 `【正式】NPS 每日通报`
- **环境标签**：`正式` 还是 `测试`。只是打标签方便筛选，不影响执行
- **命令类型**：`Linux` 还是 `Windows`

  > **Linux 命令**：由 HiClaw 后端进程直接执行（subprocess），在 HiClaw 所在的 Linux 机器上跑。
  >
  > **Windows 命令**：需要你那台 Windows 机器上装并运行 **HiClaw Windows Runner**（一个小 Python 脚本，每 10s 轮询 HiClaw）。装好后 Windows 任务就能自动执行、结果自动回传。详细部署见 `tools/windows_runner/README.md`。如果 Runner 没装、或没在运行，Windows 任务卡片会一直显示 `pending_runner` 状态。

### 3.2 调度

| 类型 | 说明 | 填什么 |
|------|------|--------|
| `一次性` | 只跑一次 | 日期 + 时间 |
| `每天` | 每天固定时间 | 时间 |
| `每周` | 每周某几天 | 星期 + 时间 |
| `每月` | 每月某一天 | 日期 (1-31) + 时间 |
| `每年` | 每年某一天 | 月份 + 日期 + 时间 |

所有时间都是 **东八区（Asia/Shanghai）**。

### 3.3 节假日策略

决定"遇到节假日怎么办"。4 个选项：

| 策略 | 说明 | 典型用法 |
|------|------|---------|
| `照常` | 节假日也跑 | 监控告警类 |
| `跳过` | 节假日当天不跑 | 正常业务通报 |
| `提前到前一工作日` | 节假日当天不跑，但前一个工作日会补一次 | 节前提醒、催缴 |
| `延后到后一工作日` | 节假日当天不跑，节后第一个工作日补一次 | 日报类不允许漏 |

节假日数据预置了国务院发布的法定节假日。如果你有部门自定义的休息日，去 `节假日管理` 页面加。

### 3.4 执行命令

这是个多行文本框，写你要跑的命令。**整段当作 shell 脚本执行**，所以可以写多行：

```bash
cd /opt/hiclaw/command_scheduler/workspace/nps
source /opt/hiclaw/command_scheduler/venv/bin/activate
python send_nps.py --env prod
```

**预装环境**：
- HiClaw 提供一个 Python 3.12 venv，路径 `/opt/hiclaw/command_scheduler/venv/`
- 预装包：`requests`, `httpx`, `python-dateutil`, `pyyaml`, `openpyxl`, `pandas`
- 工作目录：`/opt/hiclaw/command_scheduler/workspace/`（所有任务共享；建议在里面开子目录，例 `.../workspace/nps/`）
- 缺包？自己 `pip install`（会装到 venv 里，永久）

**超时**：默认 300 秒（5 分钟）。超时会被**强制终止**，fire 记录 `timeout`。如果你的脚本要更长，改 `最大执行时长` 字段。

---

## 4. 查看执行历史

任务卡片上点 `📜历史` 按钮，看到最近 N 次运行：

| 状态 | 含义 |
|------|------|
| 🟢 `success` | 退出码 0 |
| 🔴 `failed` | 退出码 ≠ 0 或异常 |
| 🟡 `timeout` | 超过 `最大执行时长` 被杀 |
| ⚫ `skipped` | 上一次还没跑完（`prev_running`）/ 节假日 |
| 🔷 `pending_runner` | Windows 任务等待 Runner 接活。Runner 在线会秒变 `running` |
| 🔵 `running` | 正在跑 |

点任意一次运行进入详情页：
- **摘要**：退出码、开始时间、结束时间、持续秒数
- **stdout 末尾 200 行**
- **stderr 末尾 200 行**
- **`下载完整日志`** 按钮 —— 下载全量日志文件

日志保留 **30 天**，过期自动清理。

---

## 5. 立即执行一次

任务卡片上点 `▶执行` 按钮，立即触发一次，不管定时。会记录一条 `trigger_source=manual` 的 fire。

用途：
- 改完脚本想立刻验证
- 节假日补跑
- 测试

---

## 6. 启停

- **单任务启停**：任务卡片右上角的绿色开关。关掉后 APScheduler job 被移除，不会再按时触发
- **暂停全部**：顶部按钮 `暂停全部` 一键停所有任务。紧急情况用（比如发现脚本都在推错数据）
- **恢复全部**：`暂停全部` 后按钮变 `恢复全部`

---

## 7. 节假日管理

顶部按钮 `节假日管理` 打开管理页。三栏：

### 7.1 预置节假日（只读）
- 国务院官方发布的 2026/2027/… 节假日
- 每年 12 月平台会更新下一年的数据
- **不能删，不能改**

### 7.2 自定义节假日
- 加自己部门的休息日（例 "2026-08-15 工厂年中休假"）
- 可以删、可以改
- 所有用户共享（P1 阶段）

### 7.3 调休工作日
- 把某个周六/周日标成"上班"（例 "2026-02-03 春节调休上班"）
- 影响 `跳过` / `提前` / `延后` 策略的计算

### 7.4 日期查询工具
- 输一个日期，返回这天是"工作日 / 节假日 / 调休上班"
- 用于调试调度计划

---

## 8. 常见问题

### Q1. 我的脚本明明在本机能跑，上 HiClaw 就失败了
- 本机的绝对路径在 sandbox 里不存在。用 `/opt/hiclaw/command_scheduler/workspace/` 下的路径
- 本机的 venv 和 HiClaw 的不是一个。用 `/opt/hiclaw/command_scheduler/venv/bin/python`
- 环境变量不一样。在命令里显式 `export XXX=yyy`
- 网络权限：sandbox 和 HiClaw 主机共用网络，内网能通的主机都能通

### Q2. 我要装一个 venv 里没有的包怎么办
```bash
/opt/hiclaw/command_scheduler/venv/bin/pip install 包名
```
装一次永久生效（venv 常驻）。

### Q3. 日志太短看不到完整输出
- 卡片上点 `📜历史` → 选那次 fire → 点 `下载完整日志`
- 或者 SSH 上 HiClaw 主机，去 `~/.openhands/command_scheduler/logs/{schedule_id}/{fire_id}.log`

### Q4. 任务没触发，怎么调试
1. 看任务卡片 `下次执行时间` 是不是未来时刻
2. 看任务是不是 `enabled`
3. 看 `节假日策略` 是不是把今天跳过了
4. 看 `命令类型` 是不是 `Windows` —— 如果是，fire 会卡在 `pending_runner`，看你那台 Windows 上的 Runner 有没有在跑（`tools/windows_runner/README.md`）
5. 以上都对但还是没跑，联系平台维护者查 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)

### Q5. 我要改一个已经存在的任务
任务卡片上点 `📝编辑` → 改字段 → `保存`。改完**下次调度按新时间**，正在跑的那次不受影响。

### Q6. 同一个任务同时有两次触发会怎样
**后触发的会 skipped**（记 `skip_reason=prev_running`）。也就是说定时任务是**串行**的，不会并行。如果你的任务经常撞到自己，要么把调度间隔拉长，要么优化脚本。

### Q7. 可以多个任务同时跑吗
**不同任务**可以并行（各跑各的）。**同一任务**不能并行（见 Q6）。

### Q8. 环境标签 `正式/测试` 有什么实际效果
P1 阶段**只是筛选标签**，不影响任何执行行为。你可以用它在 UI 上快速过滤，或者脚本里通过命令行参数自己区分。

### Q9. 我手误删了任务的 fires / 日志能恢复吗
不能。删任务是级联删除，fires 和日志文件都会被清掉。删前请确认。

### Q10. 怎么启用 Windows 命令执行？
1. 在 Windows 机器上装 Python 3.9+ 和 `requests`（`pip install requests`）
2. 把 `tools/windows_runner/hiclaw_windows_runner.py` 拷过去（例如 `C:\tools\`）
3. 起脚本：`python hiclaw_windows_runner.py --hiclaw-url http://<host>:12000 --api-key <key>`
4. 开机自启：用 Windows Task Scheduler 或 NSSM，详见 [`tools/windows_runner/README.md`](../../tools/windows_runner/README.md)

Runner 装好之后，在 HiClaw UI 里新建 `命令类型=Windows` 的任务就能自动执行。

---

## 9. 最佳实践

1. **命令写 `set -e`**：bash 开头加 `set -e` 让任一步失败都立即退出，避免前面失败了后面还往错的数据上跑
2. **脚本加时间戳日志**：`echo "[$(date +%F\ %T)] starting fetch..."` 方便在 stderr_tail 里看到进度
3. **长任务提前评估超时**：默认 300 秒常常不够。改前先在本机或 sandbox 里测一次，留 50% buffer
4. **用相对路径不如绝对路径**：脚本里写死 `/opt/hiclaw/command_scheduler/workspace/nps/config.yaml`，比 `./config.yaml` 稳定
5. **测试任务先挂 `每天 23:58` 或一次性**：别急着上 `每分钟`，先观察两三次再调整频率
6. **失败要能自检**：脚本内部捕获异常 → 写到 stderr → exit 非零，这样 HiClaw 会把 fire 标 `failed`；而不是 catch 住静默返回 0
7. **命名带环境**：`【测试】` 前缀的任务可以更激进地发改动，别和 `【正式】` 混在同一个名字
8. **节假日策略慎用 `run_before`**：如果调度频率是"每天"，`run_before` 会让节前一天跑两次（一次正常一次补偿），注意幂等
