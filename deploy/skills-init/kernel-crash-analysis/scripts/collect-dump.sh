#!/bin/bash
# 收集 crash dump 信息
VMCORE="${1:-/var/crash/vmcore}"
OUTPUT="/tmp/crash-data"
mkdir -p "$OUTPUT"

if [ ! -f "$VMCORE" ]; then
    echo "vmcore not found: $VMCORE"
    echo "Usage: $0 <vmcore_path>"
    exit 1
fi

echo "Collecting crash data from $VMCORE..."
# 如果有 crash 工具
if command -v crash &>/dev/null; then
    echo "bt -a" | crash vmlinux "$VMCORE" > "$OUTPUT/backtrace.txt" 2>/dev/null
    echo "sys" | crash vmlinux "$VMCORE" > "$OUTPUT/sysinfo.txt" 2>/dev/null
    echo "log" | crash vmlinux "$VMCORE" > "$OUTPUT/kernel-log.txt" 2>/dev/null
fi

echo "Data collected to $OUTPUT/"
ls -la "$OUTPUT/"
