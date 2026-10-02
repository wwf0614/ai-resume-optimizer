"""从简历文本创建格式统一的 Word 文档。

无论上传的是 PDF 还是 Word，都先提取纯文本，
再按固定模板格式重新生成 docx，确保排版一致。
"""
import re
from pathlib import Path
from typing import List, Tuple, Union

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt

from .editor import (
    OCR_NOISE_PREFIX,
    _clean_heading_text,
    _section_type,
    is_heading,
)

# 字体常量
FONT_CN = "微软雅黑"
FONT_EN = "Calibri"

# 应届生判定：当前年份 - 2 内毕业算应届
import datetime
_CURRENT_YEAR = datetime.datetime.now().year
_FRESH_GRAD_THRESHOLD = _CURRENT_YEAR - 2  # 2026 → 2024


def detect_career_stage(resume_text: str) -> str:
    """判断求职者身份：student（学生/应届生）或 experienced（有经验者）。

    判定逻辑（按优先级）：
    1. 含"实习"经历 → 学生
    2. 含"校园经历"/"校园活动" → 学生
    3. 含"应届"关键词 → 学生
    4. 教育日期中最近毕业年份在近两年内 → 学生
    5. 以上都不满足 → 有经验者
    """
    # 1. 实习经历
    if "实习" in resume_text:
        return "student"

    # 2. 校园经历
    if "校园经历" in resume_text or "校园活动" in resume_text:
        return "student"

    # 3. 应届关键词
    if "应届" in resume_text:
        return "student"

    # 4. 教育日期：匹配 2020.09-2024.07 / 2020-2024 / 2020~2024 等
    edu_dates = re.findall(r"(20\d{2})\s*[.\-~至到]\s*(20\d{2})", resume_text)
    if edu_dates:
        latest_grad = max(int(end) for _, end in edu_dates)
        if latest_grad >= _FRESH_GRAD_THRESHOLD:
            return "student"

    # 5. 默认有经验
    return "experienced"


def _set_run_font(run, size_pt: float, bold: bool = False):
    """统一设置 run 的中英文字体、字号、加粗。"""
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.font.name = FONT_EN
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.makeelement(qn("w:rFonts"), {})
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), FONT_CN)


def _add_heading_border(para):
    """为段落添加灰色下边框，作为标题分隔线。"""
    pPr = para._element.get_or_add_pPr()
    pBdr = pPr.makeelement(qn("w:pBdr"), {})
    bottom = pBdr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single",
        qn("w:sz"): "6",
        qn("w:space"): "2",
        qn("w:color"): "AAAAAA",
    })
    pBdr.append(bottom)
    pPr.append(pBdr)


def _parse_resume_text(text: str) -> Tuple[List[str], List[Tuple[str, str, List[str]]]]:
    """将简历纯文本解析为 (个人信息行列表, [(标题, 类型, [内容行])])。

    - 第一个可识别标题之前的行视为个人信息
    - 之后按标题分组内容
    - 经历类区块合并多条描述为1条，减少内容量确保一页
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    personal_lines: List[str] = []
    sections: List[Tuple[str, str, List[str]]] = []
    i = 0

    # 收集个人信息（第一个标题行之前的内容）
    while i < len(lines):
        cleaned = _clean_heading_text(lines[i])
        if is_heading(cleaned):
            break
        personal_lines.append(lines[i])
        i += 1

    # 解析各区块
    while i < len(lines):
        cleaned = _clean_heading_text(lines[i])
        if is_heading(cleaned):
            title = cleaned
            stype = _section_type(title)
            content: List[str] = []
            i += 1
            while i < len(lines):
                c = _clean_heading_text(lines[i])
                if is_heading(c):
                    break
                if c:
                    content.append(c)
                i += 1
            # 经历类区块：合并多条描述为1条/每个条目
            if stype in ("experience", "project"):
                content = _merge_entry_descriptions(content)
            sections.append((title, stype, content))
        else:
            i += 1

    return personal_lines, sections


# 匹配日期开头的行（如 2025.10-2026.01 或 2024.07~2024.09）
_DATE_LINE_RE = re.compile(r"^\s*(19|20)\d{2}")


def _merge_entry_descriptions(content_lines: List[str]) -> List[str]:
    """将经历区块中每个条目的多条描述合并为1条。

    日期开头的行作为条目头部保留，其后的描述行合并为1段。
    这样减少段落数，确保内容能压缩到一页。
    """
    merged: List[str] = []
    desc_buffer: List[str] = []

    for line in content_lines:
        if _DATE_LINE_RE.match(line):
            # 新条目：先刷新缓冲区
            if desc_buffer:
                merged.append(" ".join(desc_buffer))
                desc_buffer = []
            merged.append(line)  # 日期/公司行保留
        else:
            desc_buffer.append(line)

    if desc_buffer:
        merged.append(" ".join(desc_buffer))

    return merged


def _remove_table_borders(table):
    """移除表格所有边框。"""
    tbl = table._element
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = tbl.makeelement(qn("w:tblPr"), {})
        tbl.insert(0, tblPr)
    borders = tblPr.makeelement(qn("w:tblBorders"), {})
    for name in ["top", "left", "bottom", "right", "insideH", "insideV"]:
        b = borders.makeelement(qn(f"w:{name}"), {
            qn("w:val"): "none", qn("w:sz"): "0", qn("w:space"): "0",
        })
        borders.append(b)
    tblPr.append(borders)


def create_from_template(
    resume_text: str,
    out_path: Union[str, Path],
    photo_path: Union[str, Path, None] = None,
) -> Path:
    """从简历文本创建格式统一的 Word 文档。

    布局规范：
    - 顶部：姓名+联系方式（左）+ 证件照（右，如有）
    - 区块标题：12pt加粗 + 灰色下边框
    - 内容正文：10.5pt，1.15倍行距
    - 经历类区块：每个条目的多条描述已合并为1条
    - 页面边距：上下1.5cm，左右2cm
    """
    out_path = Path(out_path)
    personal_lines, sections = _parse_resume_text(resume_text)

    doc = Document()

    # 页面设置
    for s in doc.sections:
        s.top_margin = Cm(1.5)
        s.bottom_margin = Cm(1.5)
        s.left_margin = Cm(2.0)
        s.right_margin = Cm(2.0)

    # 默认样式
    style = doc.styles["Normal"]
    style.font.name = FONT_EN
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)

    # ── 顶部：个人信息 + 照片 ──
    has_photo = photo_path and Path(str(photo_path)).exists()
    if personal_lines:
        if has_photo:
            # 用无边框表格实现左文右图布局
            table = doc.add_table(rows=1, cols=2)
            _remove_table_borders(table)
            # 左单元格：姓名 + 联系方式
            left = table.cell(0, 0)
            left.width = Cm(14)
            p = left.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(personal_lines[0])
            _set_run_font(run, 16, bold=True)
            if len(personal_lines) > 1:
                p2 = left.add_paragraph(" | ".join(personal_lines[1:]))
                p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for r in p2.runs:
                    _set_run_font(r, 10)
            # 右单元格：照片
            right = table.cell(0, 1)
            right.width = Cm(3)
            p = right.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = p.add_run()
            run.add_picture(str(photo_path), width=Cm(2.5), height=Cm(3.3))
        else:
            # 无照片：纯文本居中
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(personal_lines[0])
            _set_run_font(run, 16, bold=True)
            p.paragraph_format.space_after = Pt(4)
            if len(personal_lines) > 1:
                contact = " | ".join(personal_lines[1:])
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(contact)
                _set_run_font(run, 10)
                p.paragraph_format.space_after = Pt(8)

    # ── 各区块 ──
    for title, stype, content_lines in sections:
        # 标题
        p = doc.add_paragraph()
        run = p.add_run(title)
        _set_run_font(run, 12, bold=True)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)
        _add_heading_border(p)

        # 内容
        for line in content_lines:
            p = doc.add_paragraph(line)
            p.paragraph_format.line_spacing = 1.1
            p.paragraph_format.space_after = Pt(1)
            for run in p.runs:
                _set_run_font(run, 10.5)

    doc.save(str(out_path))
    return out_path


def create_builtin_template(out_path: Union[str, Path]) -> Path:
    """生成内置模板 docx：含 {{占位符}} 的统一排版模板。

    顶部：姓名 + 联系方式（左）+ 照片（右，可选）
    区块：个人优势 / 工作经历 / 项目经历 / 教育背景 / 专业技能
    占位符标签与 db.DEFAULT_MODULES 的 label 一一对应。
    """
    out_path = Path(out_path)
    doc = Document()

    # 页面设置：强制 A4 标准画布 + 统一安全边距（上下20mm 左右18mm）
    for s in doc.sections:
        s.page_width = Mm(210)
        s.page_height = Mm(297)
        s.top_margin = Cm(2.0)
        s.bottom_margin = Cm(2.0)
        s.left_margin = Cm(1.8)
        s.right_margin = Cm(1.8)

    # 默认样式
    style = doc.styles["Normal"]
    style.font.name = FONT_EN
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CN)

    # ── 顶部：姓名/联系方式（左）+ 照片（右）──
    table = doc.add_table(rows=1, cols=2)
    _remove_table_borders(table)
    left = table.cell(0, 0)
    left.width = Cm(14)
    p = left.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("{{姓名}}")
    _set_run_font(run, 16, bold=True)
    p2 = left.add_paragraph("{{联系方式}}")
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in p2.runs:
        _set_run_font(r, 10)
    right = table.cell(0, 1)
    right.width = Cm(3)
    p = right.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("{{照片}}")
    _set_run_font(run, 9)

    # ── 各模块区块：标题（加粗+下边框）+ 占位符内容段 ──
    for title, placeholder in [
        ("个人优势", "{{个人优势}}"),
        ("工作经历", "{{工作经历}}"),
        ("项目经历", "{{项目经历}}"),
        ("教育背景", "{{教育背景}}"),
        ("专业技能", "{{专业技能}}"),
    ]:
        p = doc.add_paragraph()
        run = p.add_run(title)
        _set_run_font(run, 12, bold=True)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)
        _add_heading_border(p)

        p = doc.add_paragraph(placeholder)
        p.paragraph_format.line_spacing = 1.1
        p.paragraph_format.space_after = Pt(1)
        for run in p.runs:
            _set_run_font(run, 10.5)

    doc.save(str(out_path))
    return out_path
