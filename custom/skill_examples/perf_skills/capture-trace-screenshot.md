---
name: capture-trace-screenshot
type: knowledge
version: 1.0.0
triggers:
  - screenshot
  - 截图
  - trace截图
  - perfetto截图
---

# Trace 截图工具

使用 headless Chromium 打开 Perfetto Web UI，加载 trace 文件，自动导航到问题时间段并截图。截图可嵌入 HTML 报告中。

**此工具为可选功能**：如果环境不支持（内存不足、无法安装 Playwright），会自动跳过并正常输出报告。

## 环境要求

- Python 3.10+
- 可用内存 >= 500MB（用于运行 headless Chromium）
- 网络访问 `ui.perfetto.dev`（或本地 Perfetto UI）

依赖项（脚本自动安装，无需手动处理）：
- `playwright` — 浏览器自动化框架
- `chromium-headless-shell` — 由 playwright 自动下载

## 脚本

```bash
python3 /workspace/custom/skill_examples/perf_skills/scripts/capture_trace_screenshot.py \
  --trace <trace文件路径> \
  --analysis-dir /workspace/perf_analysis_output \
  --output-dir /workspace/perf_analysis_output/screenshots
```

## 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--trace` | 是 | trace 文件路径 |
| `--analysis-dir` | 是 | 分析结果 JSON 所在目录 |
| `--output-dir` | 否 | 截图输出目录（默认 analysis-dir/screenshots） |
| `--perfetto-url` | 否 | Perfetto UI 地址（默认 https://ui.perfetto.dev） |
| `--min-memory-mb` | 否 | 最低可用内存要求（默认 500MB） |
| `--force` | 否 | 跳过内存检查 |

## 工作流程

1. 读取 `analysis-dir` 下的所有分析 JSON 文件
2. 提取有问题的时间段（`has_issue=true` 且 `severity != normal`）
3. 检查环境（内存、Playwright 可用性）
4. 打开 Perfetto UI → 加载 trace 文件
5. 逐个导航到问题时间段 → 截图保存为 PNG
6. 输出 `screenshot_manifest.json` 清单

## 输出

### 截图文件

保存在 `output-dir/` 下，命名格式 `{序号}_{问题名称}.png`：

```
screenshots/
├── 00_全局概览.png
├── 01_主线程状态.png
├── 02_大核占比.png
├── 03_内存分析.png
└── screenshot_manifest.json
```

### Manifest 文件

`screenshot_manifest.json` 包含截图结果清单：

```json
{
  "trace_file": "/workspace/test_trace.perfetto-trace",
  "total_issues": 4,
  "captured": 4,
  "skipped": 0,
  "screenshots": [
    {"name": "全局概览", "file": "00_全局概览.png", "success": true},
    {"name": "主线程状态", "file": "01_主线程状态.png", "success": true}
  ],
  "skipped_reason": null
}
```

如果环境不支持，manifest 中 `skipped_reason` 会说明原因，`captured` 为 0。

## 在其他 Workflow 中使用

在你的 workflow 中添加一个可选截图阶段：

```yaml
phases:
  # ... 你的分析阶段 ...
  - key: screenshot
    label: 截图（可选）
    desc: 捕获 Perfetto UI 问题片段截图
    output: /workspace/your_output/screenshots/screenshot_manifest.json
  - key: report
    label: 生成报告
    desc: 输出 HTML 报告（含截图）
    output: /workspace/your_output/report.html
```

在 workflow 正文中加入：

```markdown
## 截图阶段（可选）

如果环境支持，执行截图脚本捕获问题片段的 Perfetto UI 视图：

\`\`\`bash
python3 /workspace/custom/skill_examples/perf_skills/scripts/capture_trace_screenshot.py \
  --trace $TRACE_FILE \
  --analysis-dir /workspace/your_output \
  --output-dir /workspace/your_output/screenshots
\`\`\`

**重要：** 此步骤为可选。如果脚本输出 `skipped_reason`（内存不足或无法安装依赖），
直接跳过截图继续生成报告即可，不影响最终结果。
```

## 报告集成

`generate_report.py` 会自动检测 `screenshots/` 目录：
- 如果存在截图 → 在报告的对应问题段落中嵌入图片
- 如果不存在截图 → 正常输出纯文本报告

截图以 base64 内嵌到 HTML，无需额外图片文件。
