# -*- coding: utf-8 -*-
"""清理测试结果目录中的简历测试输出（保留 UI 设计预览）。"""
import os, glob

base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "测试结果")
patterns = ["映射填充*", "赵莎-*", "测试用户-*", "批量测试结果*"]
removed = []
for pat in patterns:
    for p in glob.glob(os.path.join(base, pat)):
        if os.path.isfile(p):
            os.remove(p)
            removed.append(os.path.basename(p))
print("已删除 %d 个文件:" % len(removed))
for r in sorted(removed):
    print("  ", r)
print("剩余文件:")
for f in sorted(os.listdir(base)):
    print("  ", f)
