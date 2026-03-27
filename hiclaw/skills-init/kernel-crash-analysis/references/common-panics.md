# 常见 Kernel Panic 类型

| Panic | 常见原因 | 排查方向 |
|-------|---------|---------|
| NULL pointer dereference | 未初始化指针、use-after-free | 检查最近修改的驱动模块 |
| BUG: scheduling while atomic | 在原子上下文中调用了可能睡眠的函数 | 检查锁的使用 |
| Kernel stack overflow | 递归过深、栈上分配大数组 | 检查调用链深度 |
| Out of memory | 内存泄漏、OOM killer | 检查 /proc/meminfo |
| General protection fault | 对齐错误、非法内存访问 | 检查指针运算 |
