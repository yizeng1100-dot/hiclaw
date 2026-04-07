# Perfetto Trace 截图工具使用指南

## 概述

本工具使用 Playwright（headless Chromium）自动打开 Perfetto Web UI，加载 trace 文件，导航到问题时间段并截图。截图可嵌入 HTML 性能分析报告中，让报告更直观。

**核心特点：**
- 全自动：从分析结果 JSON 中提取问题时间段，自动截图
- 可选执行：环境不支持时自动跳过，不影响主流程
- 可复用：独立 skill，可集成到任何 workflow

---

## 环境准备

### 依赖项

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.10 | 运行环境 |
| playwright | 1.52.0+ | 浏览器自动化框架 |
| chromium-headless-shell | 随 playwright 自动安装 | headless 浏览器 |

### 安装方式

**方式一：在线安装（推荐）**

```bash
pip install playwright
python -m playwright install chromium
```

**方式二：离线安装（使用预打包文件）**

```bash
# 1. 安装 playwright wheel
pip install playwright-1.52.0-py3-none-win_amd64.whl   # Windows
pip install playwright-1.52.0-py3-none-manylinux1_x86_64.whl  # Linux

# 2. 安装 chromium
python -m playwright install chromium
# 或手动解压 chromium-headless-shell 到指定目录（见离线部署章节）
```

**方式三：脚本自动安装**

`capture_trace_screenshot.py` 脚本内置了自动安装逻辑，首次运行时会自动执行 `pip install playwright` 和 `playwright install chromium`。无需手动操作。

### 系统要求

- 可用内存 >= 500MB（headless Chromium 运行所需）
- 网络可访问 `https://ui.perfetto.dev`（或部署本地 Perfetto UI）
- Linux 需安装基础依赖：`libnss3`, `libatk1.0-0`, `libatk-bridge2.0-0`（大多数系统已有）

---

## 脚本说明

### 文件位置

```
custom/skill_examples/perf_skills/
├── scripts/
│   └── capture_trace_screenshot.py   # 截图脚本
└── capture-trace-screenshot.md        # Skill 描述文件
```

### 命令格式

```bash
python3 capture_trace_screenshot.py \
    --trace <trace文件路径> \
    --analysis-dir <分析结果JSON目录> \
    --output-dir <截图输出目录> \
    [--perfetto-url <Perfetto UI地址>] \
    [--min-memory-mb <最低内存要求>] \
    [--force]
```

### 参数详解

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--trace` | 是 | — | Perfetto trace 文件的绝对路径，支持 `.perfetto-trace`, `.pb`, `.pftrace` 格式 |
| `--analysis-dir` | 是 | — | 包含分析结果 JSON 文件的目录。脚本从这些文件中提取有问题的时间段 |
| `--output-dir` | 否 | `{analysis-dir}/screenshots` | 截图 PNG 和 manifest JSON 的输出目录 |
| `--perfetto-url` | 否 | `https://ui.perfetto.dev` | Perfetto UI 的访问地址。可改为本地部署的地址 |
| `--min-memory-mb` | 否 | `500` | 运行前检查的最低可用内存（MB）。低于此值则跳过截图 |
| `--force` | 否 | `false` | 跳过内存检查，强制执行 |

---

## 工作原理

### 执行流程

```
1. 读取 analysis-dir 下所有 JSON 文件
   ↓
2. 提取有问题的时间段（has_issue=true 且 severity≠normal）
   ↓
3. 检查环境（内存够不够？playwright 能装吗？）
   ├── 不满足 → 输出 manifest（skipped_reason 说明原因）→ 退出
   └── 满足 ↓
4. 启动 headless Chromium，打开 Perfetto UI
   ↓
5. 通过文件选择器加载 trace 文件，等待渲染完成（~12秒）
   ↓
6. 遍历每个问题时间段：
   ├── 通过 postMessage API 导航到对应时间范围
   ├── 等待视图更新（3秒）
   └── 截图保存为 PNG
   ↓
7. 输出 screenshot_manifest.json
```

### 时间段提取逻辑

脚本从以下 JSON 文件中提取问题时间段：

| 文件名 | 对应分析 | 截图名称 |
|--------|---------|---------|
| `thread_state.json` | 主线程状态分析 | 主线程状态 |
| `big_core_ratio.json` | 大核运行占比 | 大核占比 |
| `cpu_frequency.json` | CPU 频率分析 | CPU频率 |
| `compile_level.json` | 编译优化级别 | 编译优化 |
| `jit_thread.json` | JIT 线程分析 | JIT线程 |
| `thread_priority.json` | 线程优先级 | 线程优先级 |
| `system_load.json` | 系统负载 | 系统负载 |
| `detailed_load.json` | 详细负载 | 详细负载 |
| `io_details.json` | IO 阻塞分析 | IO分析 |
| `non_io.json` | 非IO阻塞 | 非IO阻塞 |
| `memory.json` | 内存分析 | 内存分析 |
| `rendering.json` | 渲染/帧率分析 | 渲染分析 |

**提取条件：**
- JSON 文件中 `has_issue` 字段为 `true`
- `severity` 字段不为 `"normal"`
- 时间范围来自 JSON 中的 `start_time`/`end_time` 字段，如果没有则使用 `launch_range.json` 中的全局范围

**额外截图：**
- 始终生成一张"全局概览"截图，展示完整的分析时间范围

### JSON 文件格式要求

分析结果 JSON 文件需要包含以下字段（脚本才能正确提取）：

```json
{
    "has_issue": true,          // 必须：是否存在问题
    "severity": "high",         // 必须：严重程度 (normal/low/medium/high)
    "start_time": 187654000000000,  // 可选：问题起始时间（纳秒）
    "end_time": 187656500000000,    // 可选：问题结束时间（纳秒）
    // ... 其他分析数据
}
```

时间戳格式：**纳秒（nanoseconds）**，与 Perfetto trace 中的时间戳一致。

---

## 输出说明

### 输出目录结构

```
screenshots/
├── 00_全局概览.png              # 全局时间范围截图
├── 01_主线程状态.png            # 第一个问题的截图
├── 02_内存分析.png              # 第二个问题的截图
├── ...
└── screenshot_manifest.json     # 截图清单
```

### 截图文件命名规则

`{两位序号}_{问题名称}.png`

- 序号从 00 开始，按问题在 JSON 文件中的检测顺序排列
- 00 始终是全局概览
- 截图分辨率：1920 x 1080

### Manifest 文件格式

`screenshot_manifest.json` 是截图结果的结构化描述，供报告生成器读取：

```json
{
    "trace_file": "/path/to/trace.perfetto-trace",
    "total_issues": 3,
    "captured": 3,
    "skipped": 0,
    "screenshots": [
        {
            "name": "全局概览",
            "file": "00_全局概览.png",
            "success": true,
            "error": null
        },
        {
            "name": "主线程状态",
            "file": "01_主线程状态.png",
            "success": true,
            "error": null
        },
        {
            "name": "内存分析",
            "file": "02_内存分析.png",
            "success": true,
            "error": null
        }
    ],
    "skipped_reason": null
}
```

**环境不支持时的 manifest：**

```json
{
    "trace_file": "/path/to/trace.perfetto-trace",
    "total_issues": 3,
    "captured": 0,
    "skipped": 3,
    "screenshots": [],
    "skipped_reason": "Insufficient memory (need 500MB free)"
}
```

---

## 集成到 Workflow

### 步骤一：在 workflow frontmatter 中添加截图阶段

```yaml
phases:
  # ... 你的分析阶段 ...
  - key: screenshot
    label: 截图（可选）
    desc: 捕获 Perfetto UI 问题片段截图
    output: /workspace/your_output/screenshots/screenshot_manifest.json
  # ... 报告阶段 ...
  - key: report
    label: 生成报告
    desc: 输出 HTML 报告（含截图）
    output: /workspace/your_output/report.html
```

### 步骤二：在 workflow 正文中添加执行指令

```markdown
## 截图阶段（可选）

执行截图脚本，捕获 Perfetto UI 中问题片段的视图：

\`\`\`bash
python3 /workspace/custom/skill_examples/perf_skills/scripts/capture_trace_screenshot.py \
    --trace $TRACE_FILE \
    --analysis-dir /workspace/your_output \
    --output-dir /workspace/your_output/screenshots
\`\`\`

**判断规则：**
- 如果输出的 JSON 中 `skipped_reason` 不为空 → 环境不支持，跳过截图，继续下一步
- 如果 `captured > 0` → 截图成功，后续报告中自动包含截图
- **重要：不要因为截图失败而停止整个工作流。截图是可选功能。**
```

### 步骤三：在报告生成脚本中读取截图

报告生成脚本应检查 `screenshots/` 目录和 `screenshot_manifest.json`：

```python
import json, base64
from pathlib import Path

def embed_screenshots(output_dir: Path) -> str:
    """读取截图并生成 HTML img 标签（base64 内嵌）"""
    manifest_path = output_dir / "screenshots" / "screenshot_manifest.json"
    if not manifest_path.exists():
        return ""  # 没有截图，返回空

    manifest = json.loads(manifest_path.read_text())
    if manifest.get("skipped_reason") or manifest.get("captured", 0) == 0:
        return ""  # 截图被跳过

    html_parts = ['<h2>Trace 截图</h2>']
    for shot in manifest.get("screenshots", []):
        if not shot.get("success"):
            continue
        img_path = output_dir / "screenshots" / shot["file"]
        if not img_path.exists():
            continue

        # Base64 编码内嵌到 HTML，无需额外图片文件
        img_data = base64.b64encode(img_path.read_bytes()).decode()
        html_parts.append(f'''
        <div class="screenshot-section">
            <h3>{shot["name"]}</h3>
            <img src="data:image/png;base64,{img_data}"
                 alt="{shot["name"]}"
                 style="max-width:100%; border:1px solid #333; border-radius:8px;" />
        </div>
        ''')

    return "\n".join(html_parts)
```

---

## 使用示例

### 示例一：命令行直接使用

```bash
# 前提：已有分析结果 JSON 在 /workspace/perf_analysis_output/ 中

python3 capture_trace_screenshot.py \
    --trace /workspace/test_trace.perfetto-trace \
    --analysis-dir /workspace/perf_analysis_output \
    --output-dir /workspace/perf_analysis_output/screenshots
```

输出：
```
[screenshot] Found 3 regions to capture
[screenshot] Opening https://ui.perfetto.dev...
[screenshot] Loading trace: /workspace/test_trace.perfetto-trace
[screenshot] Waiting for trace to render...
[screenshot] [1/3] 全局概览 (info) ts=187654000000000-187656500000000
[screenshot]   -> saved 00_全局概览.png
[screenshot] [2/3] 主线程状态 (high) ts=187654000000000-187656500000000
[screenshot]   -> saved 01_主线程状态.png
[screenshot] [3/3] 内存分析 (medium) ts=187654000000000-187656500000000
[screenshot]   -> saved 02_内存分析.png
[screenshot] Done: 3 captured, 0 skipped
```

### 示例二：在 AI Agent 对话中使用

对 Agent 说：
```
请对 /workspace/test_trace.perfetto-trace 执行性能分析，并截取问题片段的 Perfetto UI 截图。
```

Agent 会按照 workflow 执行分析，在截图阶段自动调用脚本。

### 示例三：环境不支持时的降级

```bash
# 在内存不足的机器上运行
python3 capture_trace_screenshot.py \
    --trace /workspace/test_trace.perfetto-trace \
    --analysis-dir /workspace/perf_analysis_output
```

输出：
```
[screenshot] Found 3 regions to capture
[screenshot] SKIP: Insufficient memory (need 500MB free)
```

Manifest 中 `skipped_reason` 会说明原因，`captured` 为 0。主流程不受影响。

---

## 离线部署

在无法访问外网的环境中部署：

### 1. 准备离线包

在有网络的机器上：
```bash
# 下载 playwright wheel
pip download playwright==1.52.0 --no-deps -d ./offline_pkg/

# 下载 chromium
python -m playwright install chromium
# 浏览器下载到: ~/.cache/ms-playwright/chromium_headless_shell-1169/
# 打包这个目录
tar czf chromium-headless-shell-1169.tar.gz -C ~/.cache/ms-playwright chromium_headless_shell-1169/
mv chromium-headless-shell-1169.tar.gz ./offline_pkg/
```

### 2. 在目标机器安装

```bash
# 安装 playwright
pip install ./offline_pkg/playwright-1.52.0-py3-none-*.whl

# 解压 chromium 到 playwright 的浏览器目录
mkdir -p ~/.cache/ms-playwright
tar xzf ./offline_pkg/chromium-headless-shell-1169.tar.gz -C ~/.cache/ms-playwright/

# 验证
python -c "from playwright.sync_api import sync_playwright; print('OK')"
```

### 3. 使用本地 Perfetto UI（可选）

如果无法访问 `ui.perfetto.dev`，可以本地部署：

```bash
# 方式一：使用 npm
npx @nicolo-ribaudo/perfetto-ui

# 方式二：下载 release
# https://github.com/nicolo-ribaudo/nicolo-ribaudo.github.io/releases
# 解压后用任意 HTTP server 提供服务

# 使用本地 UI
python3 capture_trace_screenshot.py \
    --trace xxx.perfetto-trace \
    --analysis-dir ./output \
    --perfetto-url http://localhost:10000
```

---

## 常见问题

### Q: 截图全是一样的内容？

**原因：** 不同分析项使用了相同的全局时间范围（从 `launch_range.json`），导致导航到同一位置。

**解决：** 在分析脚本的输出 JSON 中加入该分析项特定的 `start_time` 和 `end_time`，精确到问题发生的时间段。

### Q: 截图中 Perfetto UI 有 cookie 弹窗？

脚本会尝试自动关闭弹窗（点击 OK 按钮）。如果仍然出现，可以：
- 使用本地部署的 Perfetto UI（无 cookie 弹窗）
- 或忽略，弹窗不影响 trace 内容的展示

### Q: 内存不足怎么办？

- 降低 `--min-memory-mb` 阈值（有风险）：`--min-memory-mb 300`
- 或使用 `--force` 跳过检查
- 或在截图前关闭不需要的服务释放内存

### Q: 如何支持新的分析类型？

在 `capture_trace_screenshot.py` 的 `file_mappings` 字典中添加新的映射：

```python
file_mappings = {
    "your_analysis.json": ("你的分析名称", "English description"),
    # ...
}
```

只要 JSON 文件包含 `has_issue`, `severity` 字段，脚本就能自动提取。

### Q: Windows 上运行？

```powershell
pip install playwright==1.52.0
python -m playwright install chromium
python capture_trace_screenshot.py --trace xxx.perfetto-trace --analysis-dir .\output
```

Windows 和 Linux 使用方式完全一致，脚本跨平台。

---

## 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-03-31 | 初始版本：自动截图、可选执行、manifest 输出 |
