# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.getcwd())
from utils import db, filler, section_mapper
from docx import Document
from docx.oxml.ns import qn

for tid in (2, 5, 9, 13, 14, 16):
    tpl = db.get_template(tid)
    fp = os.path.join(os.getcwd(), tpl["file_path"].replace("/", os.sep))
    doc = Document(fp)
    ph = set()
    for p in doc.element.iter(qn("w:p")):
        for m in filler.PLACEHOLDER_RE.finditer(p.text or ""):
            ph.add(m.group(1).strip())
    filler._remove_fallback_duplicates(doc)
    m = section_mapper.detect_mapping(doc)
    print("===== t%d %s =====" % (tid, tpl["name"]))
    print("占位符:", sorted(ph))
    print("板块:", [(s["key"], s["boxes"]) for s in m["sections"]])
    tx = doc.element.findall(".//" + qn("w:txbxContent"))
    for i, elem in enumerate(tx):
        texts = []
        for p in elem.iter(qn("w:p")):
            t = "".join(c.text or "" for c in p.iter() if c.tag.split("}")[-1] == "t").strip()
            if t:
                texts.append(t)
        joined = " / ".join(texts)
        if "{{" in joined or any(k in joined for k in ["教育", "工作", "经历", "某某", "示例", "13800000000"]):
            print("  [%d] %s" % (i, joined[:70]))
    print()
