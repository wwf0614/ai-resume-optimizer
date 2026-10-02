# -*- coding: utf-8 -*-
"""为所有模板（免费 + VIP）生成真实渲染预览图。

产出两类预览：
- t{id}.png     : 示例内容预览，用于模板画廊缩略图
- t{id}_bg.png  : 仅设计、无内容的空白预览，用于编辑器背景
                  （保留 Word 原型：图标/配色/版式，且避免可编辑文字与示例文字重叠成双层）
"""
import subprocess
import tempfile
import time
from pathlib import Path

import fitz
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

import utils.db as db
from utils import converter
from utils import filler
from utils.template_render import render_template

SAMPLE_RESUME = {
    "name": "张伟",
    "contact": "13800000000 | zhangwei@email.com | 上海市",
    "job_title": "数据分析师",
    "political_status": "中共党员",
    "summary": "具备数据分析与业务洞察能力，熟悉数据清洗、可视化与报告编制，拥有跨部门协作经验，"
               "擅长通过数据驱动决策，能够快速学习新技术并落地应用，结果导向，注重细节与质量。",
    "work_experience": "数据分析师 某某科技有限公司 2021.03-2024.06\n"
                       "- 搭建经营数据分析体系，输出月度经营分析报告。\n"
                       "- 主导用户留存分析专项，推动产品迭代后留存率提升 12%。\n"
                       "- 搭建自动化报表看板，将报表产出时间从 2 天缩短至 2 小时。\n"
                       "数据分析师 某网络科技公司 2018.07-2021.02\n"
                       "- 负责业务数据仓库的 ETL 开发与维护。\n"
                       "- 独立完成 A/B 实验设计与效果评估。",
    "projects": "用户购买行为预测项目 2020.09-2020.12\n"
                "- 带领 4 人团队使用 Python 构建特征工程与模型，获省级二等奖。\n"
                "- 负责数据清洗、特征筛选与模型调参，撰写项目报告并答辩展示。",
    "education": "某某大学 数据科学与大数据技术 本科 2016.09-2020.06\n"
                 "主修课程：数据结构、数据库原理、Python 程序设计、机器学习、统计学、数据可视化。",
    "skills": "编程语言：Python、SQL、Java\n"
              "数据分析：Pandas、Power BI、Tableau、Excel\n"
              "证书：大学英语六级、计算机二级（Python）",
}

LABEL_MAP = {
    "姓名": SAMPLE_RESUME["name"],
    "联系方式": SAMPLE_RESUME["contact"],
    "求职意向": SAMPLE_RESUME["job_title"],
    "个人优势": SAMPLE_RESUME["summary"],
    "工作经历": SAMPLE_RESUME["work_experience"],
    "项目经历": SAMPLE_RESUME["projects"],
    "教育背景": SAMPLE_RESUME["education"],
    "专业技能": SAMPLE_RESUME["skills"],
}


def _kill_word():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "WINWORD.EXE"],
                       capture_output=True, shell=False)
    except Exception:
        pass
    time.sleep(0.8)


def _convert_and_save(docx_path, pdf_path, png_path, name, tid, tag):
    last_err = None
    for attempt in range(3):
        try:
            converter.docx_to_pdf(str(docx_path), str(pdf_path))
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 * (attempt + 1))
    if last_err:
        raise last_err
    doc = fitz.open(str(pdf_path))
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2.2, 2.2))
    pix.save(str(png_path))
    doc.close()
    print(f"已生成: t{tid}{tag} {name} -> {png_path.name}")


def _gen_for(tpl, preview_dir, tmp):
    cfg = tpl.get("config") or {}
    tid = tpl["id"]
    tpl_file = Path(__file__).resolve().parent / tpl["file_path"]
    out_sample = preview_dir / f"t{tid}.png"
    out_blank = preview_dir / f"t{tid}_bg.png"
    try:
        if cfg.get("render_mode") == "flow":
            if not out_sample.exists():
                docx = tmp / f"t{tid}_s.docx"
                render_template(SAMPLE_RESUME, cfg, None, str(docx), quick=True)
                _convert_and_save(docx, tmp / f"t{tid}_s.pdf", out_sample, tpl["name"], tid, "")
            if not out_blank.exists():
                docx = tmp / f"t{tid}_b.docx"
                try:
                    render_template({}, cfg, None, str(docx), quick=True)
                except Exception:
                    # 空白流式渲染失败时退化为示例版作为背景底图
                    docx = tmp / f"t{tid}_s.docx"
                _convert_and_save(docx, tmp / f"t{tid}_b.pdf", out_blank, tpl["name"], tid, "_bg")
        else:
            # 文件填充模式：读取模板占位符
            labels = set()
            d = Document(str(tpl_file))
            for pe in d.element.iter(qn("w:p")):
                para = Paragraph(pe, d)
                for m in filler.PLACEHOLDER_RE.finditer(para.text or ""):
                    labels.add(m.group(1).strip())
            if not out_sample.exists():
                content_map = {label: LABEL_MAP[label] for label in labels if label in LABEL_MAP}
                docx = tmp / f"t{tid}_s.docx"
                filler.fill_template(content_map, tpl_file, docx)
                _convert_and_save(docx, tmp / f"t{tid}_s.pdf", out_sample, tpl["name"], tid, "")
            if not out_blank.exists():
                # 空白设计版：清空所有可变内容，仅保留图标/配色/版式（Word 原型）
                docx = tmp / f"t{tid}_b.docx"
                filler.fill_template({}, tpl_file, docx)
                _convert_and_save(docx, tmp / f"t{tid}_b.pdf", out_blank, tpl["name"], tid, "_bg")
    except Exception as exc:  # noqa: BLE001
        print(f"失败: t{tid} {tpl['name']}: {str(exc)[:160]}")
    finally:
        _kill_word()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tid", type=int, default=None,
                    help="仅处理指定模板 id（每进程单模板，避免 Word COM 长时间运行导致崩溃）")
    args = ap.parse_args()

    db.init_db()
    preview_dir = Path(__file__).resolve().parent / "static" / "previews"
    preview_dir.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="preview_"))
    seen = set()
    all_tpls = []
    for tpl in list(db.list_templates()) + list(db.list_vip_templates()):
        if tpl["id"] in seen:
            continue
        seen.add(tpl["id"])
        all_tpls.append(tpl)
    if args.tid is not None:
        all_tpls = [t for t in all_tpls if t["id"] == args.tid]
        print(f"单模板模式: tid={args.tid}")
    else:
        print(f"待处理模板数: {len(all_tpls)}")
    for tpl in all_tpls:
        _gen_for(tpl, preview_dir, tmp)
    for f in tmp.iterdir():
        try:
            f.unlink()
        except OSError:
            pass
    try:
        tmp.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    main()
