# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import fitz
pdf = os.path.join(os.environ["TEMP"], "editor_out.pdf")
doc = fitz.open(pdf)
t = doc[0].get_text()
doc.close()
for kw in ["测试用户", "13800000000", "测试大学", "数据科学与大数据技术", "Linux", "大华", "CET-4", "运维工程师"]:
    print("%s: %s" % (kw, "存在" if kw in t else "缺失"))
print("残留W0614:", "W0614" in t)
print("残留占位符{{:", "{{" in t)
