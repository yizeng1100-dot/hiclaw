#!/bin/bash
# 收集系统日志
mkdir -p /tmp/log-analysis
dmesg > /tmp/log-analysis/dmesg.log 2>/dev/null
journalctl --since "1 hour ago" > /tmp/log-analysis/journal.log 2>/dev/null
echo "Logs collected to /tmp/log-analysis/"
