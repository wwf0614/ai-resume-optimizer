# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.oxml.ns import qn

def fulltext(path):
    d = Document(path)
    out = []
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
            out.append(line)
    return "\n".join(out)

for tid, markers in ((4, ["13800000000", "大华", "测试大学"]),
                     (13, ["13314477595", "亚信科技", "信息管理与信息系统"])):
    t = fulltext(os.path.join(os.environ["TEMP"], "chk_t%d.docx" % tid))
    missing = [m for m in markers if m not in t]
    print("t%d missing: %s" % (tid, missing))
