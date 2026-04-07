# 故障局部截图指南

## 目标

在分析 trace 发现问题后，自动截取 **问题发生的那一帧或那一段** 的 Perfetto UI 局部视图，而不是整个 trace 的全局视图。

## 原理

截图脚本通过读取分析结果 JSON 中的 `issue_regions` 字段，获取每个具体问题的精确时间戳和持续时间，然后在 Perfetto UI 中导航到该时间窗口并截图。

```
分析脚本发现 Jank Frame → 输出 issue_regions（精确到纳秒）
→ 截图脚本读取 issue_regions → 导航到该帧的时间窗口 → 截图
```

## 如何输出 issue_regions

### 格式定义

在分析脚本的输出 JSON 中，添加 `issue_regions` 数组：

```json
{
    "has_issue": true,
    "severity": "high",
    "其他分析字段": "...",

    "issue_regions": [
        {
            "name": "问题名称",
            "ts": 起始时间戳（纳秒）,
            "dur": 持续时间（纳秒）,
            "desc": "问题描述",
            "severity": "严重程度"
        }
    ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 问题名称，会作为截图文件名。例如 `"Jank Frame #3"` |
| `ts` | int | 是 | 问题起始时间，单位**纳秒**，与 trace 中的时间戳一致 |
| `dur` | int | 是 | 问题持续时间，单位**纳秒** |
| `desc` | string | 否 | 问题描述，会写入报告。例如 `"帧耗时 45ms，超过 16.6ms 阈值"` |
| `severity` | string | 否 | 严重程度：`low` / `medium` / `high`。默认继承文件级别的 severity |

### 时间单位

**全部使用纳秒（nanoseconds）**，与 Perfetto trace 内部时间戳一致。

常用换算：
- 1ms = 1,000,000 ns
- 16.6ms（一帧 @60fps）= 16,600,000 ns
- 1s = 1,000,000,000 ns

## 各分析场景的 issue_regions 示例

### 渲染分析：截取掉帧的那一帧

```json
{
    "has_issue": true,
    "severity": "high",
    "jank_rate": 15.2,
    "total_frames": 150,
    "janky_frames": 23,
    "issue_regions": [
        {
            "name": "Jank Frame #3",
            "ts": 187655000000000,
            "dur": 45000000,
            "desc": "帧耗时 45ms，超过 16.6ms 阈值（预期 60fps）"
        },
        {
            "name": "Jank Frame #7",
            "ts": 187655800000000,
            "dur": 38000000,
            "desc": "帧耗时 38ms，超过 16.6ms 阈值"
        },
        {
            "name": "连续掉帧 #12-#15",
            "ts": 187656100000000,
            "dur": 120000000,
            "desc": "连续 4 帧掉帧，总耗时 120ms"
        }
    ]
}
```

### 主线程状态：截取异常状态的时间段

```json
{
    "has_issue": true,
    "severity": "high",
    "running_pct": 45.2,
    "runnable_pct": 32.1,
    "issue_regions": [
        {
            "name": "Runnable 高峰",
            "ts": 187654500000000,
            "dur": 300000000,
            "desc": "主线程 Runnable 占比达 45%，持续 300ms，疑似被抢占"
        },
        {
            "name": "长 Sleeping",
            "ts": 187655200000000,
            "dur": 150000000,
            "desc": "主线程连续 sleeping 150ms，可能是锁等待"
        }
    ]
}
```

### IO 分析：截取 IO 阻塞的那一段

```json
{
    "has_issue": true,
    "severity": "medium",
    "io_pct": 8.5,
    "issue_regions": [
        {
            "name": "IO 阻塞 - binder",
            "ts": 187654800000000,
            "dur": 80000000,
            "desc": "主线程 binder 调用阻塞 80ms"
        },
        {
            "name": "IO 阻塞 - disk read",
            "ts": 187655500000000,
            "dur": 45000000,
            "desc": "磁盘读取阻塞 45ms，发生在 SharedPreferences 加载"
        }
    ]
}
```

### 内存分析：截取 GC/OOM 事件

```json
{
    "has_issue": true,
    "severity": "high",
    "gc_count": 15,
    "issue_regions": [
        {
            "name": "频繁 GC",
            "ts": 187654600000000,
            "dur": 500000000,
            "desc": "500ms 内发生 8 次 GC，导致主线程暂停"
        },
        {
            "name": "LMK 事件",
            "ts": 187656000000000,
            "dur": 10000000,
            "desc": "Low Memory Killer 触发，进程被回收"
        }
    ]
}
```

### CPU 频率分析：截取限频时段

```json
{
    "has_issue": true,
    "severity": "medium",
    "issue_regions": [
        {
            "name": "CPU 限频",
            "ts": 187655000000000,
            "dur": 800000000,
            "desc": "大核频率被限制在 1.2GHz（最大 2.8GHz），持续 800ms"
        }
    ]
}
```

## 截图效果

### 无 issue_regions（旧行为）

截取全局时间范围，看到的是整个分析期间的概览：

```
|===========================================|  ← 整个 2.5 秒的 trace
```

### 有 issue_regions（精确截图）

截取每个问题发生的精确位置，自动放大到帧级别：

```
          |===|  ← 只看 Jank Frame #3 的 45ms
                        |==|  ← 只看 Jank Frame #7 的 38ms
```

## 自动 Padding 策略

截图脚本会根据问题持续时间自动添加上下文 padding：

| 问题持续时间 | Padding 比例 | 效果 |
|-------------|-------------|------|
| < 50ms（单帧级别） | 200% | 大幅放大，能看清帧内的函数调用 |
| 50ms - 500ms | 50% | 适中缩放，能看到前后帧的上下文 |
| > 500ms | 10% | 轻微扩展，保持宏观视图 |

示例：一个 45ms 的 Jank Frame，padding 200%：
- 实际截图范围 = 45ms + 90ms(前) + 90ms(后) = 225ms 窗口
- 在 Perfetto UI 中约占半屏宽度，能清楚看到这一帧的细节

## 在分析脚本中如何获取精确时间戳

### 从 trace_processor 查询

```python
# 查询掉帧的精确时间
query = """
SELECT ts, dur, name
FROM slice
WHERE track_id IN (
    SELECT id FROM track WHERE name = 'Choreographer#doFrame'
)
AND dur > 16600000
ORDER BY dur DESC
LIMIT 10
"""
```

### 从已有分析结果推导

如果分析脚本已经计算了某个指标的时间分布，可以找到异常点：

```python
# 伪代码：找到 Running 占比异常的时间窗口
for window in sliding_windows(thread_states, window_size=100_000_000):  # 100ms 窗口
    running_pct = calc_running_pct(window)
    if running_pct < 40:  # 异常低
        issue_regions.append({
            "name": f"Running 偏低 ({running_pct:.0f}%)",
            "ts": window.start,
            "dur": window.end - window.start,
            "desc": f"Running 占比仅 {running_pct:.1f}%，正常应 > 60%",
        })
```

## 完整流程

```
1. 分析脚本执行
   → 发现问题
   → 记录精确时间戳
   → 输出 JSON（含 issue_regions）

2. 截图脚本读取所有分析 JSON
   → 优先使用 issue_regions（精确截图）
   → 没有 issue_regions 则使用全局时间范围（兜底）
   → 全局概览截图始终生成

3. 报告生成
   → 读取 screenshot_manifest.json
   → 在对应问题段落插入截图
   → 截图以 base64 内嵌到 HTML
```

## 注意事项

1. **issue_regions 是可选的**。没有它，截图脚本会回退到全局时间范围，不会报错
2. **不要输出太多 regions**。建议每个分析文件最多 5 个最严重的问题，否则截图太多影响性能
3. **时间戳必须在 trace 范围内**。超出 trace 时间范围的 ts 会导致 Perfetto UI 导航到空白区域
4. **dur 不要太小**。小于 1ms (1,000,000 ns) 的问题在 Perfetto UI 中可能看不清，建议合并相邻的小问题
5. **name 会作为文件名**。避免使用特殊字符（`/\:*?"<>|`），中英文都可以
