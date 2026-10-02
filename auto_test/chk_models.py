# -*- coding: utf-8 -*-
import json
p = r"C:\Users\测试用户\.codex\models.json"
with open(p, encoding="utf-8") as f:
    data = json.load(f)
print("模型数:", len(data["models"]))
for m in data["models"]:
    print("slug:", m.get("slug"), "| input_modalities:", m.get("input_modalities"))
    print("  supportsImages:", m.get("supportsImages"), "| supports_image_detail_original:", m.get("supports_image_detail_original"))