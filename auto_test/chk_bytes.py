# -*- coding: utf-8 -*-
import sys, io, os, zipfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

p = os.path.join(os.environ["TEMP"], "editor_out.docx")
with zipfile.ZipFile(p) as z:
    raw = b"".join(z.read(n) for n in z.namelist() if n.endswith(".xml"))
for kw in ["测试用户", "测试大学", "大华", "运维工程师", "数据科学与大数据技术",
           "13800000000", "Linux", "CET-4", "主修课程"]:
    print("%s: %d" % (kw, raw.count(kw.encode("utf-8"))))
