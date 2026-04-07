# 渲染专项性能分析工作流规则

## 概述

本规则严格对应渲染专项分析文档（android-render-performance-analysis.md），只包含文档中定义的流程与分支。

## 分析流程

### 阶段1: Trace 采集与初始化
1. **调用 skill**: `trace-processor-init`
2. **说明**: 加载 trace 文件并启动查询服务
3. **初始化指标**: 运行 jank 指标初始化
4. **调用 skill**: `init-render-jank-metric`

### 阶段2: Jank 类型识别
1. **调用 skill**: `analyze-jank-types`
2. **说明**: 统计 jank_type / jank_tag / jank_severity_type（如存在）

### 阶段3: 应用层 Jank 分析
1. **分支 3.1 JANK_APP_DEADLINE_MISSED**
   - **调用 skill**: `analyze-app-jank`
   - **包含**: doFrame 超时、DrawFrames 时长、GPU wait
2. **分支 3.2 JANK_BUFFER_STUFFING**
   - **调用 skill**: `analyze-app-jank`
   - **包含**: dequeueBuffer 阻塞、buffer queue 相关分析

### 阶段4: SurfaceFlinger Jank 分析
1. **分支 4.1 JANK_SF_CPU_DEADLINE_MISSED**
   - **调用 skill**: `analyze-sf-cpu-jank`
   - **包含**: SF 主线程耗时、锁竞争、Layer 更新量
2. **分支 4.2 JANK_SF_GPU_DEADLINE_MISSED**
   - **调用 skill**: `analyze-sf-gpu-jank`
   - **包含**: RenderEngine/GLES/Skia 耗时、Layer 统计
3. **分支 4.3 JANK_DISPLAY_HAL**
   - **调用 skill**: `analyze-display-hal-jank`
   - **包含**: HWC/present 事件
4. **分支 4.4 JANK_PREDICTION_ERROR**
   - **调用 skill**: `analyze-jank-dropped`
5. **分支 4.5 JANK_SF_SCHEDULING**
   - **调用 skill**: `analyze-jank-dropped`
6. **分支 4.6 JANK_SF_STUFFING**
   - **调用 skill**: `analyze-jank-dropped`
   - **包含**: 前一帧耗时关联
7. **分支 4.7 JANK_DROPPED**
   - **调用 skill**: `analyze-jank-dropped`

### 阶段5: 报告生成
1. **调用 skill**: `render-report-generator`
2. **说明**: 汇总渲染分析 JSON 结果生成 HTML 报告

## 注意事项
1. 分支由 Jank 类型识别结果触发
2. 本规则不包含额外的通用分析步骤

---

# Android应用绘制渲染性能分析工作流

## 概述

本工作流提供基于Perfetto trace的Android应用绘制渲染性能分析能力，帮助开发者快速定位卡顿根因。涵盖从应用层到SurfaceFlinger、Display HAL的完整渲染链路分析。

## 使用场景

应用卡顿、掉帧、滚动不流畅、动画延迟、界面响应慢

## 分析流程

### 阶段1: Trace采集

1. **配置Perfetto采集**
```bash
perfetto -o trace.perfetto-trace -c android_categories.cfg
```

2. **初始化分析表**
```sql
SELECT RUN_METRIC('android/jank/android_jank_cuj_init.sql');
```

### 阶段2: Jank类型识别

**SQL查询**:
```sql
SELECT
    jank_type,
    jank_tag,
    jank_severity_type,
    COUNT(*) AS frame_count,
    AVG(dur) / 1000000.0 AS avg_dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type IS NOT NULL
    AND jank_type NOT IN ('None', 'Unspecified')
GROUP BY jank_type, jank_tag, jank_severity_type
ORDER BY frame_count DESC;
```

**Jank类型说明**:

| Jank类型 | 说明 | 严重程度 |
|----------|------|----------|
| JANK_NONE | 无Jank | 🟢 正常 |
| JANK_UNSPECIFIED | 信息不足 | 🟢 正常 |
| JANK_APP_DEADLINE_MISSED | 应用侧超时 | 🔴 严重 |
| JANK_BUFFER_STUFFING | Buffer塞满 | 🟠 中等 |
| JANK_SF_CPU_DEADLINE_MISSED | SF主线程CPU超时 | 🔴 严重 |
| JANK_SF_GPU_DEADLINE_MISSED | SF GPU合成超时 | 🔴 严重 |
| JANK_DISPLAY_HAL | 显示HAL延迟 | 🔴 严重 |
| JANK_PREDICTION_ERROR | VSync预测错误 | 🟠 中等 |
| JANK_SF_SCHEDULING | SF调度异常 | 🟠 中等 |
| JANK_SF_STUFFING | SF侧stuffing | 🟠 中等 |
| JANK_DROPPED | 帧被丢弃 | 🔴 严重 |
| JANK_UNKNOWN | 未知原因 | 🔴 严重 |

### 阶段3: 应用层Jank分析

#### 3.1 JANK_APP_DEADLINE_MISSED

**特征**: 应用侧实际完成时间超出期望窗口

**SQL查询**:
```sql
SELECT
    frame_id,
    dur / 1000000.0 AS actual_dur_ms,
    jank_type
FROM actual_frame_timeline_slice
WHERE jank_type = 'AppDeadlineMissed'
ORDER BY dur DESC
LIMIT 50;
```

**排查重点**:
- ✅ Choreographer#doFrame是否超时
- ✅ RenderThread DrawFrames时长
- ✅ waiting for GPU completion时长

**详细分析SQL**:
```sql
-- 1. Choreographer#doFrame超时
SELECT
    frame_id,
    dur / 1000000.0 AS do_frame_ms
FROM android_frames_choreographer_do_frame
JOIN slice USING (id)
WHERE dur > 16000000
ORDER BY dur DESC;

-- 2. DrawFrames时长
SELECT
    frame_id,
    SUM(CASE WHEN name GLOB '*DrawFrame*' THEN dur ELSE 0 END) / 1000000.0 AS draw_frames_ms
FROM slice
WHERE name GLOB 'DrawFrame*'
GROUP BY frame_id
ORDER BY draw_frames_ms DESC;

-- 3. GPU等待时长
SELECT
    name,
    dur / 1000000.0 AS gpu_wait_ms
FROM slice
WHERE name GLOB '*GPU*wait*'
ORDER BY dur DESC;
```

#### 3.2 JANK_BUFFER_STUFFING

**特征**: BufferQueue被塞满，呈现延迟升高

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'BufferStuffing'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ 是否render-ahead太多
- ✅ 是否出现dequeueBuffer阻塞
- ✅ 是否"帧率平滑但延迟很大"

**详细分析SQL**:
```sql
-- 检查dequeueBuffer阻塞
SELECT
    name,
    dur / 1000000.0 AS dur_ms
FROM slice
WHERE name GLOB '*dequeueBuffer*'
    AND dur > 5000000
ORDER BY dur DESC;

-- 检查buffer queue状态
SELECT
    frame_id,
    COUNT(*) AS buffer_count
FROM slice
WHERE name GLOB '*queueBuffer*'
GROUP BY frame_id
HAVING buffer_count > 3;
```

### 阶段4: SurfaceFlinger Jank分析

#### 4.1 JANK_SF_CPU_DEADLINE_MISSED

**特征**: SF主线程CPU合成/调度超时

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'SurfaceFlingerCpuDeadlineMissed'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ surfaceflinger进程主线程忙
- ✅ 锁竞争
- ✅ HWC device composition阻塞时间
- ✅ 事务/Layer更新量过大

**详细分析SQL**:
```sql
-- 1. SF主线程耗时
SELECT
    name,
    dur / 1000000.0 AS dur_ms
FROM slice
WHERE name GLOB '*SurfaceFlinger*'
    OR name GLOB '*onMessageReceived*'
    AND dur > 5000000
ORDER BY dur DESC;

-- 2. 锁竞争分析
SELECT
    name,
    dur / 1000000.0 AS dur_ms
FROM slice
WHERE name GLOB '*lock*'
    OR name GLOB '*mutex*'
ORDER BY dur DESC;

-- 3. Layer更新量
SELECT
    frame_id,
    COUNT(*) AS layer_count
FROM slice
WHERE name GLOB '*Layer*'
GROUP BY frame_id
ORDER BY layer_count DESC;
```

#### 4.2 JANK_SF_GPU_DEADLINE_MISSED

**特征**: SF GPU合成fence太晚

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'SurfaceFlingerGpuDeadlineMissed'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ RenderEngine/GPU负载
- ✅ 过多layer/overdraw
- ✅ 分辨率过高
- ✅ shader复杂

**详细分析SQL**:
```sql
-- 1. GPU合成耗时
SELECT
    name,
    dur / 1000000.0 AS dur_ms
FROM slice
WHERE name GLOB '*RenderEngine*'
    OR name GLOB '*GLES*'
    OR name GLOB '*Skia*'
ORDER BY dur DESC;

-- 2. Layer数量
SELECT
    frame_id,
    COUNT(DISTINCT name) as unique_layers
FROM slice
WHERE name GLOB '*Layer*'
GROUP BY frame_id
ORDER BY unique_layers DESC;
```

#### 4.3 JANK_DISPLAY_HAL

**特征**: SF已按时提交，但最终未在目标上屏

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'DisplayHal'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ HWC present fence晚
- ✅ display pipeline
- ✅ 驱动/硬件瓶颈

**详细分析SQL**:
```sql
-- 检查HWC相关事件
SELECT
    name,
    dur / 1000000.0 AS dur_ms
FROM slice
WHERE name GLOB '*HWC*'
    OR name GLOB '*present*'
ORDER BY dur DESC;
```

#### 4.4 JANK_PREDICTION_ERROR

**特征**: SF调度器对硬件vsync预测发生漂移

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'PredictionError'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ 是否频繁发生
- ✅ 是否伴随refresh rate/模式切换

#### 4.5 JANK_SF_SCHEDULING

**特征**: SF调度运行时机异常

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'SurfaceFlingerScheduling'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ SF线程调度
- ✅ CPU抢占
- ✅ 同核高优任务
- ✅ rt/uclamp配置

#### 4.6 JANK_SF_STUFFING

**特征**: 前一帧跑太久，占用当前帧的预期vsync

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'SurfaceFlingerStuffing'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ 前一帧的SF CPU/GPU/DisplayHAL是否已超

**详细分析SQL**:
```sql
-- 查找前一帧的耗时
SELECT
    frame_id,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE frame_id IN(
    SELECT frame_id - 1
    FROM actual_frame_timeline_slice
    WHERE jank_type = 'SurfaceFlingerStuffing'
)
ORDER BY dur DESC;
```

#### 4.7 JANK_DROPPED

**特征**: 帧被丢弃/被更新的帧替换

**SQL查询**:
```sql
SELECT
    frame_id,
    jank_type,
    dur / 1000000.0 AS dur_ms
FROM actual_frame_timeline_slice
WHERE jank_type = 'DroppedFrame'
ORDER BY dur DESC;
```

**排查重点**:
- ✅ SF侧present_type
- ✅ 是否发生"追延迟"策略
- ✅ 应用是否提交不稳定

---

## 卡顿根因分类与优化建议

### 1. 应用层卡顿 (JANK_APP_DEADLINE_MISSED)

**特征**:
- Choreographer#doFrame > 16ms
- RenderThread DrawFrames长
- GPU等待时间长

**优化建议**:
- 将耗时操作移到子线程
- 减少布局层级
- 避免频繁重绘
- 优化onDraw实现

### 2. Buffer卡顿 (JANK_BUFFER_STUFFING)

**特征**:
- dequeueBuffer阻塞
- Buffer queue满
- 帧率平滑但延迟大

**优化建议**:
- 减少render-ahead
- 优化buffer消费速度
- 调整buffer队列大小

### 3. SF CPU卡顿 (JANK_SF_CPU_DEADLINE_MISSED)

**特征**:
- SF主线程忙
- 锁竞争
- Layer更新量大

**优化建议**:
- 减少Layer数量
- 优化锁的使用
- 减少事务更新频率

### 4. SF GPU卡顿 (JANK_SF_GPU_DEADLINE_MISSED)

**特征**:
- GPU合成耗时长
- Layer过多/overdraw
- Shader复杂

**优化建议**:
- 使用硬件合成
- 减少overdraw
- 优化shader
- 降低分辨率

### 5. Display HAL卡顿 (JANK_DISPLAY_HAL)

**特征**:
- HWC present fence晚
- 显示pipeline延迟

**优化建议**:
- 检查HWC驱动
- 优化显示配置
- 联系硬件厂商

### 6. 调度卡顿 (JANK_SF_SCHEDULING)

**特征**:
- SF线程调度异常
- CPU抢占

**优化建议**:
- 调整SF线程优先级
- 优化CPU调度策略
- 检查rt/uclamp配置

---

## 相关文件

- Perfetto源码
- Android Framework源码
