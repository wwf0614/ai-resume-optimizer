# -*- coding: utf-8 -*-
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.getcwd())
from utils import llm, converter

text = converter.pdf_to_text_ocr(os.path.join(os.environ["TEMP"], "src26.pdf"))
orig = llm._fallback_section(text, "education")
print("orig len:", len(orig))
lines = [ln.strip() for ln in orig.splitlines() if ln.strip()]
first = lines[0]
course_parts = []
for ln in lines[1:]:
    ln2 = re.sub(r"^(主修课程|核心课程|课程)[：:]?\s*", "", ln)
    course_parts.extend(x.strip() for x in ln2.replace("，", "、").replace(",", "、").split("、") if x.strip())
print("lines:", len(lines))
print("course_parts:", course_parts)
out = first + "\n主修课程：" + "、".join(course_parts[:12])
print("标准化后 len:", len(out))
print("含Linux:", "Linux" in out, "含ETL:", "ETL" in out)
