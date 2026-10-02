# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.oxml.ns import qn

d = Document(os.path.join(os.environ["TEMP"], "t8_out2.docx"))
lines = []
for p in d.element.iter(qn("w:p")):
    parts = []
    for child in p.iter():
        tag = child.tag.split("}")[-1]
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "br":
            parts.append("\n")
    line = "".join(parts).strip()
    if line:
        lines.append(line)
full = "\n".join(lines)
for kw in ["信息管理与信息系统", "测试大学", "亚信科技", "13314477595", "汉", "中共党员", "主修课程"]:
    print("%s: %d" % (kw, full.count(kw)))
print()
for ln in lines:
    if any(k in ln for k in ["教育", "贵州", "信息管理", "主修", "亚信"]):
        print("  ", ln[:75])
