# 定时任务中心 —— 故障排查手册

> 给平台维护者（HiClaw 开发/运维）的手册。用户端问题见 [USER_GUIDE.md](./USER_GUIDE.md) §8。

---

## 快速体检

把这几条命令一次性跑完，80% 的问题都能定位：

```bash
# 1. HiClaw 后端存活
curl -sS http://127.0.0.1:12000/api/v1/command-schedules | jq 'length'

# 2. APScheduler 调度状态（有没有挂上 job）
sqlite3 ~/.openhands/openhands.db \
  'SELECT id, name, enabled, next_fire_at FROM command_schedules;'

# 3. Sandbox 状态
curl -sS http://127.0.0.1:12000/api/v1/sandboxes | \
  jq '.[] | select(.id=="cmd-scheduler") | {id, status}'

# 4. venv 是否 provision 完成
ls /opt/hiclaw/command_scheduler/venv/.provisioned && echo OK || echo MISSING

# 5. 最近 10 条 fire
sqlite3 ~/.openhands/openhands.db \
  'SELECT id, schedule_id, status, skip_reason, started_at
   FROM command_fires ORDER BY started_at DESC LIMIT 10;'

# 6. 后端 log 里的 command_scheduler 记录
grep -i "command_scheduler\|cmd-scheduler" /tmp/openhands-12000.log | tail -40
```

---

## 按症状排查

### 症状 1：任务到点不触发

**检查清单**
1. `enabled = 1` 吗？—— `sqlite3 openhands.db 'select enabled from command_schedules where id=?'`
2. `next_fire_at` 是未来时刻吗？—— 如果是 `NULL` 说明 job 没挂上
3. APScheduler 实例是否活着？后端启动日志应有 `INFO: APScheduler started`
4. `scheduler_integration.py` 的 `sync_job` 是否在任务创建/更新时被调用？后端 log 应有 `[command_scheduler] synced job for schedule_id=...`

**根因可能**
- **cron 表达式错误**：`cron_expr` 格式非法 → APScheduler 静默丢弃。手工验证：
  ```python
  from apscheduler.triggers.cron import CronTrigger
  CronTrigger.from_crontab("0 9 * * *")
  ```
- **job_id 冲突**：如果同一个 `schedule_id` 挂了两次 → 第二次会报 `ConflictingIdError`，job 没挂上。解决：先 remove 再 add
- **scheduler 没启动**：HiClaw 启动顺序里 `command_scheduler` init 先于 `scheduler` init → job add 失败。解决：确认 `scheduler_integration.init_jobs_from_db()` 在 scheduler start 之后调用

**修复**
```bash
# 强制重建 job：把 enabled 改成 false 再改回 true
curl -X PATCH http://127.0.0.1:12000/api/v1/command-schedules/{id} \
  -d '{"enabled": false}' -H 'Content-Type: application/json'
curl -X PATCH http://127.0.0.1:12000/api/v1/command-schedules/{id} \
  -d '{"enabled": true}' -H 'Content-Type: application/json'
```

---

### 症状 2：任务触发了但命令执行失败

**先分类**
```bash
# 看 fire 状态
curl -sS http://127.0.0.1:12000/api/v1/command-schedules/{id}/fires?limit=5 | jq
```

#### 2a. `status = failed, exit_code != 0`
- **用户脚本 bug**。看 `stderr_tail` 或下载全量日志：
  ```bash
  cat ~/.openhands/command_scheduler/logs/{schedule_id}/{fire_id}.log
  ```
- 用户问题，定位后告诉用户怎么改

#### 2b. `status = failed, exit_code = null`
- 执行前就挂了（sandbox dispatch 阶段抛异常）
- 看 `stderr_tail`，一般是 Python 异常 repr
- 常见：
  - `SandboxError: sandbox not running` —— §3 解决
  - `FileNotFoundError` —— `working_dir` 不存在
  - `PermissionError` —— sandbox 用户没权限进目录

#### 2c. `status = timeout`
- 命令超过 `max_duration_sec`，被 SIGKILL
- 让用户改长超时，或者优化脚本

#### 2d. `status = skipped, skip_reason = prev_running`
- 上一次还在跑。查上一次的 fire：
  ```sql
  SELECT * FROM command_fires
   WHERE schedule_id = ? AND status = 'running'
   ORDER BY started_at DESC LIMIT 1;
  ```
- 如果上一次 running 了很久没结束，可能是 sandbox 挂了，fire 没被标记。手动 fix：
  ```sql
  UPDATE command_fires SET status = 'failed', completed_at = datetime('now')
   WHERE id = ?;
  ```

#### 2e. `status = skipped, skip_reason = windows_not_supported`
- 正常行为 —— Windows 命令暂存。不是 bug

#### 2f. `status = skipped, skip_reason = holiday_skip`
- 检查任务的 `holiday_policy` 和今天是否节假日：
  ```bash
  curl http://127.0.0.1:12000/api/v1/command-scheduler/holidays/check/2026-04-15
  ```

---

### 症状 3：Sandbox 启动失败 / 反复挂

**查状态**
```bash
curl http://127.0.0.1:12000/api/v1/sandboxes | jq '.[] | select(.id=="cmd-scheduler")'
```

**根因和修复**

#### 3a. `status = error`
- 启动过程中抛错。查 `openhands-12000.log` 里 `cmd-scheduler` 的启动阶段：
  ```bash
  grep -A 5 -B 5 "cmd-scheduler" /tmp/openhands-12000.log | tail -40
  ```
- 常见原因：
  - Process sandbox 启动器 bug
  - `/opt/hiclaw/command_scheduler/` 目录没权限创建
  - venv provision 时 pip install 失败（网络问题）

#### 3b. venv provision 卡住
```bash
# 进 sandbox 手动补
/opt/hiclaw/command_scheduler/venv/bin/pip install \
    requests httpx python-dateutil pyyaml openpyxl pandas
touch /opt/hiclaw/command_scheduler/venv/.provisioned
```

#### 3c. Sandbox 跑了一段时间后挂
- 用户脚本里 `kill -9 $$` 自杀了
- 用户脚本消耗光内存
- **修复**：重启 HiClaw 或者手动销毁 sandbox，下次 lazy 重建
  ```bash
  curl -X DELETE http://127.0.0.1:12000/api/v1/sandboxes/cmd-scheduler
  ```

#### 3d. 长期未重启但突然失联
- Process sandbox 被 OOM killer 杀了？`dmesg | grep -i "killed process"`
- HiClaw 主进程和 sandbox 进程的父子关系断了？需要查 PID 关系

---

### 症状 4：节假日策略不准

**检查**
```bash
# 1. 今天是什么
curl http://127.0.0.1:12000/api/v1/command-scheduler/holidays/check/$(date +%F)

# 2. 任务的策略
sqlite3 ~/.openhands/openhands.db \
  'SELECT name, holiday_policy FROM command_schedules WHERE id=?;'

# 3. 今天是否有任务被 skip
sqlite3 ~/.openhands/openhands.db \
  "SELECT * FROM command_fires
    WHERE date(started_at) = date('now') AND skip_reason='holiday_skip';"
```

**注意 P1 阶段的限制**
- `run_before` 和 `run_after` 的**补偿扫描** P1 没实现，**P2 才会有**
- P1 只做"今天是否节假日 → 跳过"的简单判断
- 所以 P1 选 `run_before` = 效果等同 `skip`（因为没有"前一天补跑"的机制）
- **修复**：在 P1 阶段，告诉用户 `run_before` / `run_after` 暂时不可靠，等 P2

---

### 症状 5：日志清理没生效 / 磁盘占满

**检查**
```bash
# 日志目录总大小
du -sh ~/.openhands/command_scheduler/logs/

# 按 schedule 看
du -sh ~/.openhands/command_scheduler/logs/*

# 最旧的 fire
sqlite3 ~/.openhands/openhands.db \
  'SELECT min(started_at) FROM command_fires;'
```

**根因**
- 清理 job 没挂：找 `scheduler_integration.py` 里的 `register_cleanup_job`，确认在 `init_jobs_from_db` 里被调用
- 清理 job 挂了但抛异常：查后端 log `grep "cleanup" /tmp/openhands-12000.log`

**临时手动清理**
```bash
# 删 DB 里 30 天前的 fire 记录
sqlite3 ~/.openhands/openhands.db \
  "DELETE FROM command_fires WHERE started_at < datetime('now', '-30 days');"

# 删对应文件
find ~/.openhands/command_scheduler/logs/ -type f -name "*.log" \
    -mtime +30 -delete
```

---

### 症状 6：数据库 migration 冲突

**如果升级 HiClaw 后定时任务中心打不开，先看启动 log**

```bash
grep -i "migration\|command_schedules\|command_fires\|holidays" /tmp/openhands-12000.log | tail -30
```

**常见**
- 表已存在但 schema 不匹配 —— 说明你在 dev 改过表又忘了 bump migration 版本
- SQLite 不支持 `ALTER TABLE ... DROP COLUMN` → 改 schema 时要重建表

**手动 schema dump**
```bash
sqlite3 ~/.openhands/openhands.db \
  ".schema command_schedules command_fires holidays"
```

和 `custom/command_scheduler/migrations/001_initial.sql` 对照。

---

### 症状 7：前端看不到任务卡片

**分层定位**

1. **API 层**：`curl /api/v1/command-schedules` 返回有数据吗？
2. **Vite 代理层**：`curl http://127.0.0.1:12001/api/v1/command-schedules` 返回一样吗？（如果不一样，`vite.config.ts` 的 proxy 挂了）
3. **前端层**：DevTools Network tab 看 `/api/v1/command-schedules` 请求，status 和 response body
4. **React 渲染层**：DevTools Console 看有没有 JS 错误；看 `useCommandScheduler` hook 的 state

**常见**
- API 挂 HiClaw 12000，Vite 在 12001。用户打开 12000 而不是 12001 会 404
- SSE 类的 response 被 Vite 缓冲。非 SSE 应该不受影响，如果出现类似 chat-bot 那次"后端 200 前端看不到"的问题，看 chat-bot 的 CRLF 修复（`chatbot-service.api.ts` 里的 `.replace(/\r\n/g, "\n")`）

---

## 数据库 schema 速查

```sql
-- command_schedules
CREATE TABLE command_schedules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    env_tag TEXT NOT NULL DEFAULT 'formal',
    shell_kind TEXT NOT NULL DEFAULT 'linux',
    kind TEXT NOT NULL,
    cron_expr TEXT,
    run_at TEXT,
    command TEXT NOT NULL,
    working_dir TEXT,
    max_duration_sec INTEGER NOT NULL DEFAULT 300,
    holiday_policy TEXT NOT NULL DEFAULT 'normal',
    log_path TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_fire_at TEXT,
    next_fire_at TEXT
);
CREATE INDEX idx_cs_enabled ON command_schedules(enabled);
CREATE INDEX idx_cs_env_tag ON command_schedules(env_tag);
CREATE INDEX idx_cs_next_fire_at ON command_schedules(next_fire_at);

-- command_fires
CREATE TABLE command_fires (
    id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES command_schedules(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    skip_reason TEXT,
    exit_code INTEGER,
    stdout_tail TEXT,
    stderr_tail TEXT,
    log_file_path TEXT,
    trigger_source TEXT NOT NULL
);
CREATE INDEX idx_cf_schedule_id_started_at
    ON command_fires(schedule_id, started_at DESC);

-- holidays
CREATE TABLE holidays (
    date TEXT PRIMARY KEY,        -- YYYY-MM-DD
    name TEXT NOT NULL,
    kind TEXT NOT NULL,           -- holiday / makeup_workday
    source TEXT NOT NULL,         -- preset / user
    created_at TEXT NOT NULL
);
```

---

## 常用 SQL

```sql
-- 今天谁跑过 / 没跑
SELECT cs.name, cf.status, cf.started_at, cf.exit_code
  FROM command_schedules cs
  LEFT JOIN command_fires cf
    ON cf.schedule_id = cs.id
   AND date(cf.started_at) = date('now')
 WHERE cs.enabled = 1
 ORDER BY cs.name;

-- 最近 7 天失败率
SELECT cs.name,
       SUM(CASE WHEN cf.status = 'success' THEN 1 ELSE 0 END) AS ok,
       SUM(CASE WHEN cf.status = 'failed' THEN 1 ELSE 0 END) AS fail
  FROM command_schedules cs
  JOIN command_fires cf ON cf.schedule_id = cs.id
 WHERE cf.started_at > datetime('now', '-7 days')
 GROUP BY cs.id
 ORDER BY fail DESC;

-- 卡住的 fire（running > 10 分钟）
SELECT id, schedule_id, started_at
  FROM command_fires
 WHERE status = 'running'
   AND started_at < datetime('now', '-10 minutes');

-- 硬性修复卡住的 fire
UPDATE command_fires
   SET status = 'failed',
       completed_at = datetime('now'),
       stderr_tail = '[manual fix: stuck > 10 min]'
 WHERE status = 'running'
   AND started_at < datetime('now', '-10 minutes');
```

---

## 升级 / 迁移注意

### 每年 12 月：更新节假日数据

1. 把新一年的 `holidays_cn_{year}.yaml` 放进 `custom/command_scheduler/data/`
2. HiClaw 启动时会自动把 `source=preset` 的条目同步进 `holidays` 表
3. 验证：
   ```bash
   curl http://127.0.0.1:12000/api/v1/command-scheduler/holidays?year={year} | jq
   ```

### Schema 改动

1. 在 `custom/command_scheduler/migrations/` 下加 `00X_description.sql`
2. Bump migration 版本 + 在启动时按顺序执行
3. 如果要 drop/rename 字段，SQLite 需要"建新表 + copy + drop + rename"四步

### 从 `run_before`/`run_after` 补偿扫描 P1 → P2 升级

**P1**：策略字段存了但只做简单判断。用户选 `run_before` = 效果等同 `skip`。

**P2 加**：
- 每天 00:01 扫描明天的节假日
- 找出所有 `holiday_policy=run_before` 且明天该跑的任务
- 给今天的某个时刻额外注册一个 `DateTrigger` 的 one-shot job
- 类似逻辑给 `run_after`

**升级兼容性**：P1 数据可以平滑升级到 P2，不需要数据迁移，只要开 scanner job。

---

## 联系

如果排查完还搞不定，开 issue 到 hiclaw 仓库 `feat/command-scheduler` 分支，附上：
1. `快速体检` 6 条命令的输出
2. 具体的症状（哪个任务 / 什么时间 / 期望是什么 / 实际是什么）
3. 相关的 fire_id
4. `/tmp/openhands-12000.log` 的相关片段（最近 200 行）
