# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.oxml.ns import qn

d = Document(os.path.join(os.environ["TEMP"], "editor_out.docx"))
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
for kw in ["测试用户", "13800000000", "测试大学", "数据科学与大数据技术", "Linux", "大华", "CET-4", "运维工程师", "主修课程"]:
    print("%s: %d" % (kw, full.count(kw)))
print("总行数:", len(lines))
print("--- 前 25 行 ---")
for ln in lines[:25]:
    print("  ", ln[:70])
