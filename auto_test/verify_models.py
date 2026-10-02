# -*- coding: utf-8 -*-
import json
p = r"C:\Users\测试用户\.codex\models.json"
with open(p, encoding="utf-8") as f:
    data = json.load(f)
print("JSON 有效，模型数:", len(data["models"]))
for m in data["models"]:
    print(" ", m.get("slug"), "| supportsImages:", m.get("supportsImages"), "| modalities:", m.get("input_modalities"))