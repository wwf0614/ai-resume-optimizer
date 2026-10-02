# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.oxml.ns import qn

for tid in (2, 4):
    d = Document(os.path.join(os.environ["TEMP"], "fin_t%d.docx" % tid))
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
    print("===== t%d =====" % tid)
    print("半角测试大学:", "测试大学" in full)
    print("全角贵州师范⼤学:", "贵州师范\u2f24学" in full or "贵州师范⼤学" in full)
    print("含大华:", "大华" in full)
    print("含大华股份:", "大华股份" in full)
    print("--- 教育/工作相关行 ---")
    for ln in lines:
        if any(k in ln for k in ["教育", "贵州", "大华", "德施曼", "2022", "2025", "2024"]):
            print("  ", ln[:70])
    print()
