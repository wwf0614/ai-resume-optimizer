# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from docx import Document
from docx.oxml.ns import qn

d = Document(os.path.join(os.environ["TEMP"], "editor_out.docx"))
for p in d.element.iter(qn("w:p")):
    parts = []
    for child in p.iter():
        tag = child.tag.split("}")[-1]
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "br":
            parts.append("\n")
    line = "".join(parts).strip()
    if any(k in line for k in ["姓", "学", "2025", "2022", "主修", "大华"]):
        print(repr(line[:120]))
