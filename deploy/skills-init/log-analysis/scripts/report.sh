#!/bin/bash
# 生成分析报告
REPORT="/tmp/log-analysis/report.md"
echo "# Log Analysis Report" > "$REPORT"
echo "Date: $(date)" >> "$REPORT"
echo "" >> "$REPORT"
python3 "$(dirname "$0")/analyze.py" >> "$REPORT"
echo "" >> "$REPORT"
echo "Report saved to $REPORT"
