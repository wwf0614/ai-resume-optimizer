# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import fitz

pdf = os.path.join(os.environ["TEMP"], "opt_final.pdf")
doc = fitz.open(pdf)
t = doc[0].get_text()
doc.close()

checks = {
    "教育-Linux": "Linux" in t,
    "教育-ETL": "ETL" in t,
    "教育-数据库": "数据库" in t,
    "工作-大华": "大华" in t,
    "工作-德施曼": "德施曼" in t,
    "技能-CET4": "CET-4" in t,
    "残留-未婚": "未婚" not in t,
    "残留-1994": "1994" not in t,
    "残留-预结算": "预结算" not in t,
    "残留-占位符": "{{" not in t,
    "姓名-测试用户": "测试用户" in t,
    "手机-13800000000": "13800000000" in t,
}
for k, v in checks.items():
    print("[%s] %s" % ("OK" if v else "FAIL", k))
