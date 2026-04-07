---
name: analyze-stats
type: knowledge
triggers:
  - 日志统计
  - error statistics
---

# 日志统计分析

对解析后的结构化日志进行统计分析，输出错误分布、频率和趋势。

## 脚本

```bash
python3 /workspace/custom/skill_examples/log_analysis/scripts/analyze_stats.py \
  --input /workspace/log_output/parsed.json
```

## 输出字段

- `total_entries`: 总条目数
- `error_count`: 错误数量
- `warn_count`: 警告数量
- `top_errors`: TOP N 错误类型及出现次数
- `time_distribution`: 按小时统计的错误分布
- `has_issue`: 是否存在异常
- `severity`: 严重程度 (low/medium/high)
