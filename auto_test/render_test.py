# -*- coding: utf-8 -*-
"""编辑器渲染接口测试（文件方式保证中文内容正确）。"""
import sys, io, os, json, zipfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import requests

BASE = "http://127.0.0.1:8000"
r = requests.post(BASE + "/api/login", json={"account": "13800138000", "password": "test123456"})
H = {"Authorization": "Bearer " + r.json()["token"]}
TOKEN = H["Authorization"].split()[-1]

content = {
    "name": "测试用户", "age": "24", "phone": "13800000000", "email": "test@example.com",
    "city": "贵州贵阳", "school": "测试大学", "education_degree": "本科",
    "major": "数据科学与大数据技术", "intention_job": "运维工程师",
    "education_info": "2022.09-2026.07 测试大学 数据科学与大数据技术（本科）\n主修课程：计算机网络基础、数据库、Linux、ETL技术",
    "work_history": "2025.10-2026.01 大华股份 产品与解决方案实习生\n- 参与安防产品信息化市场调研\n- 协助方案演示与交付跟进",
    "skill_info": "专业技术：计算机网络、数据分析\n证书：CET-4、计算机二级、C1驾驶证",
    "self_evaluate": "具备数据科学专业背景，擅长用数据发现问题、优化流程，责任心强，愿意长期深耕运维方向。",
}
r2 = requests.post(BASE + "/api/render-resume", headers=H,
                   data={"template_id": 20, "content": json.dumps(content, ensure_ascii=False),
                         "merge_mode": "merge"})
print("render:", r2.status_code)
if r2.status_code != 200:
    print(r2.text[:400]); sys.exit(1)
j = r2.json()
sid = j["session_id"]
r3 = requests.get(BASE + "/download/" + sid, params={"format": "docx", "token": TOKEN}, timeout=60)
open(os.path.join(os.environ["TEMP"], "editor_out2.docx"), "wb").write(r3.content)
with zipfile.ZipFile(os.path.join(os.environ["TEMP"], "editor_out2.docx")) as z:
    raw = b"".join(z.read(n) for n in z.namelist() if n.endswith(".xml"))
for kw in ["测试用户", "测试大学", "大华", "运维工程师", "数据科学与大数据技术",
           "主修课程", "Linux", "CET-4", "13800000000", "数据库"]:
    print("%s: %d" % (kw, raw.count(kw.encode("utf-8"))))
print("残留W0614:", raw.count("W0614".encode()))
print("残留占位符{{:", raw.count("{{".encode()))
