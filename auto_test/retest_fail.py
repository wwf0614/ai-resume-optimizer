# -*- coding: utf-8 -*-
"""重点复测：之前失败的模板 × 两份简历。"""
import sys, io, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import requests
from docx import Document
from docx.oxml.ns import qn

BASE = "http://127.0.0.1:8000"
TIDS = [2, 4, 5, 6, 9, 11, 13]
RESUMES = [
    {"name": "赵莎", "file": os.path.join(os.environ["TEMP"], "t1_zs.pdf"),
     "jd": "招聘行政/运营类岗位，要求沟通协调、文字功底、办公软件熟练",
     "markers": ["13314477595", "亚信科技", "信息管理与信息系统"]},
    {"name": "测试用户", "file": os.path.join(os.environ["TEMP"], "src26.pdf"),
     "jd": "招聘运维工程师，要求设备部署、故障排查、数据分析",
     "markers": ["13800000000", "大华", "测试大学"]},
]

r = requests.post(BASE + "/api/login", json={"account": "13800138000", "password": "test123456"})
TOKEN = r.json()["token"]
H = {"Authorization": "Bearer " + TOKEN}

def fulltext(data_bytes):
    d = Document(io.BytesIO(data_bytes))
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

for resume in RESUMES:
    for tid in TIDS:
        t0 = time.time()
        with open(resume["file"], "rb") as f:
            files = {"resume": (os.path.basename(resume["file"]), f, "application/pdf")}
            data = {"job_text": resume["jd"], "template_id": tid, "merge_mode": "merge"}
            r2 = requests.post(BASE + "/optimize", headers=H, files=files, data=data, timeout=300)
        if r2.status_code != 200:
            print("[%s t%d] HTTP %d" % (resume["name"], tid, r2.status_code), flush=True)
            continue
        sid = r2.json()["session_id"]
        r3 = requests.get(BASE + "/download/" + sid, params={"format": "docx", "token": TOKEN}, timeout=90)
        t = fulltext(r3.content)
        missing = [m for m in resume["markers"] if m not in t]
        print("[%s t%d] missing=%s (%.0fs)" % (resume["name"], tid, missing, time.time()-t0), flush=True)
