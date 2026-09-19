"""
控制台输出编码 —— Windows 代码页兜底。

Windows 上 stdout 一旦被重定向(管道、`> log.txt`、CI、被别的进程拉起),
Python 用的就是系统 ANSI 代码页: 英文 Windows 是 cp1252, 编不了中文, 第一句
带中文的 print 直接 UnicodeEncodeError 崩掉。直连控制台时 Python 走
WriteConsoleW 不受影响, 所以这个问题只在重定向时出现 —— 特别隐蔽。

凡是会打中文的入口(main.py / desktop.py / 测试脚本)都在最开始调一次
force_utf8()。仓库根目录的 build_app.py 是独立的构建工具, 自带一份同样的实现。
"""

import sys


def force_utf8() -> None:
    """把 stdout / stderr 强制成 UTF-8, 编不出的字符退化成转义而不是抛异常"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            # 流被替换成了不支持 reconfigure 的对象(如已重定向到文件对象), 忽略
            pass
