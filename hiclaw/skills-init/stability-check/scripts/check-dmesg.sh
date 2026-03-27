#!/bin/bash
echo "=== Recent Kernel Errors ==="
dmesg --level=err,crit,alert,emerg 2>/dev/null | tail -20
echo ""
echo "=== Recent Warnings ==="
dmesg --level=warn 2>/dev/null | tail -10
