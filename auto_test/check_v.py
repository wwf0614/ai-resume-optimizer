# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.oxml.ns import qn

for tid in (16, 2):
    d = Document(os.path.join(os.environ["TEMP"], "v_t%d.docx" % tid))
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
    for kw in ["13314477595", "亚信科技", "信息管理与信息系统", "赵莎", "某某某", "13800138000"]:
        print("  %s: %d" % (kw, full.count(kw)))
    print("  含占位符{{:", "{{" in full)
    print()
