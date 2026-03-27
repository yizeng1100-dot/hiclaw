#!/usr/bin/env python3
"""分析 crash backtrace，识别故障模块。"""
import re, os

def analyze_backtrace(bt_file):
    if not os.path.exists(bt_file):
        print(f"File not found: {bt_file}")
        return
    
    with open(bt_file) as f:
        content = f.read()
    
    # 查找 panic/oops 调用栈
    frames = re.findall(r'\[.*?\]\s+(\S+)\+0x', content)
    if frames:
        print("=== Call Stack ===")
        for i, func in enumerate(frames[:15]):
            print(f"  #{i}: {func}")
        
        # 识别可能的故障模块
        modules = set()
        for func in frames:
            if '/' in func:
                modules.add(func.split('/')[0])
        if modules:
            print(f"\n=== Suspected Modules ===")
            for m in modules:
                print(f"  - {m}")
    else:
        print("No backtrace frames found")

if __name__ == '__main__':
    analyze_backtrace('/tmp/crash-data/backtrace.txt')
