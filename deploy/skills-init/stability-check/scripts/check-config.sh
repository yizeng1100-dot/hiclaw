#!/bin/bash
echo "=== Kernel Version ==="
uname -r
echo ""
echo "=== Uptime ==="
uptime
echo ""
echo "=== Memory ==="
free -h
echo ""
echo "=== Disk ==="
df -h /
