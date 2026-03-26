---
name: generate-report
type: knowledge
version: 2.0.0
agent: CodeActAgent
triggers:
- /generate-report
- 生成报告
- generate report
---

# 生成性能分析 HTML 报告

## 功能
将所有分析阶段的 JSON 结果汇总，生成结构化的 HTML 报告。

## 约束
- **必须使用下方指定脚本，禁止自行编写报告生成代码。**
- **禁止自行拼接 HTML** — 报告格式由脚本统一控制。

## 执行方式

```bash
python3 /workspace/custom/skill_examples/perf_skills/scripts/generate_report.py \
  --output-dir /workspace/perf_analysis_output
```

### 参数说明
| 参数 | 必需 | 说明 |
|------|------|------|
| `--output-dir` | 否 | 分析结果目录，默认 `/workspace/perf_analysis_output` |

## 前置条件
脚本会自动读取 `--output-dir` 下所有 `*.json` 文件作为分析结果输入。确保前面的分析阶段已执行完毕且输出文件存在。

## 预期输出
- `full_report.html` — 完整报告，包含所有分析维度的详细数据
- `issue_report.html` — 问题报告，仅包含有异常的分析项

## 反思验证
执行完毕后，必须检查：
1. 两个 HTML 文件均已生成：`ls -la /workspace/perf_analysis_output/*.html`
2. 文件大小 > 0
3. 如果某个分析阶段的 JSON 缺失，报告中会跳过该项——检查是否有遗漏的分析步骤
