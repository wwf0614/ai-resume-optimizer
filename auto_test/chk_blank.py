# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.getcwd())
from utils import db, filler
from docx import Document
from docx.oxml.ns import qn

tpl = db.get_template(20)
fp = os.path.join(os.getcwd(), tpl["file_path"].replace("/", os.sep))
doc = Document(fp)
filler._remove_fallback_duplicates(doc)
filler._clear_template_examples(doc)
lines = []
for p in doc.element.iter(qn("w:p")):
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
print("=== 清空后模板内容 ===")
for ln in lines:
    print("  ", ln[:50])
print()
print("含测试用户:", "测试用户" in full)
print("含大华:", "大华" in full)
print("含教育背景(标题):", "教育背景" in full)
print("含姓名标签:", "姓" in full and "名" in full)
print("含实习经验(标题):", "实习经验" in full)
