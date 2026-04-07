---
name: parse-log
type: knowledge
triggers:
  - 日志解析
  - log parse
---

# 日志解析

解析常见格式的日志文件（nginx, syslog, JSON lines），提取时间戳、级别、消息等字段。

## 脚本

```bash
python3 /workspace/custom/skill_examples/log_analysis/scripts/parse_log.py \
  --file <日志文件路径> --format auto
```

## 参数

- `--file`: 日志文件路径（必填）
- `--format`: 日志格式，可选 `auto`/`nginx`/`syslog`/`jsonl`（默认 auto）

## 输出字段

- `total_lines`: 总行数
- `parsed_lines`: 成功解析行数
- `format_detected`: 检测到的格式
- `entries`: 结构化日志条目数组
