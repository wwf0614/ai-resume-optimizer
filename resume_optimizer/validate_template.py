# -*- coding: utf-8 -*-
"""模板入库校验 CLI：python validate_template.py <template_id 或 docx 路径>

校验内容：A4/占位符/图片内嵌/长内容单页/溢出/模块完整/照片适配。
"""
import json
import sys
from pathlib import Path

from utils import db, validator


def print_report(title, result):
    print(f"\n===== {title} =====")
    for c in result["checks"]:
        flag = "通过" if c["ok"] else "失败"
        print(f"  [{flag}] {c['name']}: {c.get('detail', '')}")
    print(f"结论: {'✓ 校验通过，可入库' if result['ok'] else '✗ 校验未通过，禁止入库'}")


def main():
    arg = sys.argv[1]
    if arg.lower().endswith(".docx"):
        result = validator.validate_template_file(arg)
        print_report(f"模板文件：{Path(arg).name}", result)
        return
    db.init_db()
    tpl = db.get_template(int(arg))
    if not tpl:
        print(f"模板 {arg} 不存在")
        return
    cfg = tpl.get("config") or {}
    if cfg.get("render_mode") == "flow":
        result = validator.validate_flow_template(cfg)
        print_report(f"模板 {tpl['name']}（流式配置）", result)
    else:
        fpath = Path(__file__).resolve().parent / tpl["file_path"]
        result = validator.validate_template_file(fpath)
        print_report(f"模板 {tpl['name']}（文件模板）", result)


if __name__ == "__main__":
    main()
