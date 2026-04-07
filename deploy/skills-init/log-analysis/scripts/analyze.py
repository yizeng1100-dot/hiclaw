#!/usr/bin/env python3
"""分析日志文件，识别错误和警告。"""
import re, sys, os

def analyze(log_file):
    if not os.path.exists(log_file):
        return []
    errors = []
    with open(log_file) as f:
        for i, line in enumerate(f, 1):
            if re.search(r'error|fail|panic|oops|warning', line, re.I):
                errors.append((i, line.strip()))
    return errors

if __name__ == '__main__':
    log_dir = '/tmp/log-analysis'
    for f in ['dmesg.log', 'journal.log']:
        path = os.path.join(log_dir, f)
        errors = analyze(path)
        print(f"\n=== {f} ({len(errors)} issues) ===")
        for lineno, line in errors[:20]:
            print(f"  L{lineno}: {line[:120]}")
