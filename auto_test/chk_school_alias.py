# -*- coding: utf-8 -*-
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.getcwd())
from utils import db, standard_keys

standard_keys.refresh_aliases()
sections, fields = standard_keys._merged_aliases()
print("school 字段别名:", fields.get("school"))
print()
print("数据库自定义同义词:")
for row in db.list_aliases():
    print("  kind=%s std_key=%s alias=%s" % (row["kind"], row["std_key"], row["alias"]))

# 验证 find_field_key 对 毕业院校/学校/毕业学校/院校 的识别
for label in ["毕业院校", "毕业学校", "院校", "学校", "学    校"]:
    print("find_field_key(%s) = %s" % (label, standard_keys.find_field_key(label)))
