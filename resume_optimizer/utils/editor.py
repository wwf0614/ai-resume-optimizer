"""就地编辑 docx：分类识别「优化区」与「保留区」，按区块类型调用不同改写策略。

支持普通 docx 和 PDF 转换后的 docx（内容在表格中）。
"""
import re
from pathlib import Path
from typing import Callable, List, Tuple, Union

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.table import Table
from docx.text.paragraph import Paragraph

# ── 优化区：按子类型分组 ──
EXPERIENCE_KW = [
    "工作经历", "工作经验", "工作履历", "工作历程", "职业经历", "职业履历",
    "就业经历", "实习经历", "实习经验", "实习",
]
PROJECT_KW = [
    "项目经验", "项目经历", "校园经历", "校园活动", "社会实践",
]
SKILL_KW = [
    "专业技能", "技能特长", "技能", "技术栈", "核心技能", "专业技术",
    "技外书",  # OCR 噪声变体
]
EVALUATION_KW = [
    "自我评价", "个人简介", "个人总结", "自我描述",
]

ALL_OPTIMIZE_KW = EXPERIENCE_KW + PROJECT_KW + SKILL_KW + EVALUATION_KW

# ── 保留区 ──
PRESERVE_KW = [
    "个人信息", "基本信息", "联系方式", "教育背景", "教育经历", "学历",
    "求职意向", "期望", "objective",
    "证书", "资格证书", "语言能力", "语言水平", "技外书",
    "荣誉", "获奖", "奖项", "培训经历", "书及荣誉",
    "兴趣爱好", "科研成果", "论文", "专利",
    "education", "certificate", "award", "language", "hobby",
    "publication", "research", "patent",
]

ALL_SECTION_KW = ALL_OPTIMIZE_KW + PRESERVE_KW

DATE_RE = re.compile(r"^\s*(19|20)\d{2}")
BULLET_RE = re.compile(r"^\s*[-•·*◦▪▸→►➢>©®]|^\s*[0-9０-９]+[.、）)]")
# OCR 噪声前缀：|、©、®、•、多"等
OCR_NOISE_PREFIX = re.compile(r"^[|©®•·*#@~]+\s*")
# 证书/荣誉行：在技能板块中保留不改写
CERT_HONOR_RE = re.compile(
    r"(CET|计算机[一二三四级]|驾驶证|普通话|雅思|托福|证书|等级|奖学金|优秀|荣誉|获奖|奖项)"
)


def _clean_heading_text(text: str) -> str:
    """清理 OCR 产生的标题噪声前缀。"""
    return OCR_NOISE_PREFIX.sub("", text).strip()


def _match_kw(text: str, keywords: List[str]) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(kw in text or kw in lower for kw in keywords)


def is_heading(text: str) -> bool:
    """是否为简历小节标题行。"""
    if not text or len(text) > 20:
        return False
    cleaned = _clean_heading_text(text)
    # 去除尾部冒号和空格
    cleaned = re.sub(r"[：:]\s*$", "", cleaned).strip()
    if not cleaned:
        return False
    # 含冒号且冒号后有实质内容的行是描述性内容，不是标题
    # 例如 "专业技术: 熟练掌握计算机网络" 不应被识别为标题
    m = re.match(r"^(.+?)[：:]\s*(.+)$", cleaned)
    if m and len(m.group(2)) > 3:
        return False
    return _match_kw(cleaned, ALL_SECTION_KW)


def _section_type(title: str) -> str:
    """根据标题判断区块类型。"""
    title = _clean_heading_text(title)
    if _match_kw(title, EXPERIENCE_KW):
        return "experience"
    if _match_kw(title, PROJECT_KW):
        return "project"
    if _match_kw(title, SKILL_KW):
        return "skill"
    if _match_kw(title, EVALUATION_KW):
        return "evaluation"
    return "preserve"


def _is_bullet(para) -> bool:
    text = para.text.strip()
    if not text:
        return False
    style = para.style.name if para.style else ""
    if "List Bullet" in style or "List Number" in style:
        return True
    return bool(BULLET_RE.match(text))


def _should_rewrite_line(para, sec_type: str) -> bool:
    """判断经历/项目/技能段中的某一行是否应改写。"""
    text = para.text.strip()
    if not text:
        return False
    # 清理 OCR 噪声前缀后再判断
    cleaned = _clean_heading_text(text)
    if is_heading(cleaned):
        return False
    if DATE_RE.match(text):
        return False
    if "公司" in text or "大学" in text or "学院" in text or "师范大学" in text:
        return False
    # 技能板块中的证书/荣誉行保留不改写（CET、计算机等级、驾驶证、奖学金等）
    if sec_type == "skill" and CERT_HONOR_RE.search(text):
        return False
    if sec_type in ("skill", "evaluation"):
        return len(cleaned) >= 4
    if _is_bullet(para):
        return True
    if len(cleaned) < 8:
        return False
    return True


def _collect_all_paragraphs(doc) -> List:
    """收集文档中所有段落对象（正文 + 表格 + 文本框 + 嵌套表格），保持文档顺序。

    - pdf2docx 转换后的 docx 内容通常在表格中
    - 部分Word简历内容写在文本框（txbxContent）中
    - 使用深度遍历确保所有位置的段落都能被收集到
    - 过滤空段落，避免干扰区块识别
    """
    result = []
    for p_elem in doc.element.iter(qn("w:p")):
        para = Paragraph(p_elem, doc)
        if para.text.strip():  # 只收集有文本内容的段落
            result.append(para)
    return result


def _collect_table_paragraphs(table, result: list):
    """递归收集表格中所有段落（含嵌套表格）。"""
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                result.append(para)
            for nested in cell.tables:
                _collect_table_paragraphs(nested, result)


def _find_sections(paragraphs) -> List[Tuple[int, int, str, str]]:
    """返回所有小节：[(start_idx, end_idx, title, section_type), ...]。"""
    sections = []
    i, n = 0, len(paragraphs)
    while i < n:
        text = paragraphs[i].text.strip()
        if text and is_heading(text):
            stype = _section_type(text)
            j = i + 1
            while j < n:
                t = paragraphs[j].text.strip()
                if t and is_heading(t):
                    break
                j += 1
            sections.append((i, j, text, stype))
            i = j
        else:
            i += 1
    return sections


def _replace_paragraph_text(para, new_text: str) -> None:
    """替换段落文本，保留第一个 run 的格式。"""
    if not para.runs:
        para.add_run(new_text)
        return
    para.runs[0].text = new_text
    for run in para.runs[1:]:
        run.text = ""


def edit_resume_docx(
    docx_path: Union[str, Path],
    job_description: str,
    rewrite_fn: Callable,
    out_path: Union[str, Path],
    career_stage: str = "experienced",
) -> Tuple[Path, int, List[dict]]:
    """在原 docx 上就地改写优化区内容，保留原格式。

    自动扫描正文段落和表格内段落（兼容 PDF 转 docx）。
    career_stage: "student" 或 "experienced"，影响 LLM 提示词选择。
    返回 (out_path, rewritten_count, comparisons)。
    """
    doc = Document(str(docx_path))
    all_paras = _collect_all_paragraphs(doc)
    sections = _find_sections(all_paras)
    rewritten = 0
    comparisons: List[dict] = []

    for start, end, title, stype in sections:
        if stype == "preserve":
            continue

        if stype == "evaluation":
            content_paras = []
            full_text_parts = []
            for idx in range(start + 1, end):
                para = all_paras[idx]
                t = para.text.strip()
                if t:
                    content_paras.append(para)
                    full_text_parts.append(t)
            if not content_paras:
                continue
            full_text = "\n".join(full_text_parts)
            new_text = rewrite_fn(full_text, job_description, stype, career_stage)
            if new_text:
                _replace_paragraph_text(content_paras[0], " ".join(new_text.split()))
                for extra in content_paras[1:]:
                    _replace_paragraph_text(extra, "")
                rewritten += 1
                comparisons.append({"section": title, "type": stype,
                                    "before": full_text, "after": new_text})
            continue

        for idx in range(start + 1, end):
            para = all_paras[idx]
            if not _should_rewrite_line(para, stype):
                continue
            old_text = para.text.strip()
            new_text = rewrite_fn(old_text, job_description, stype, career_stage)
            if new_text and new_text != old_text:
                cleaned = " ".join(new_text.split())
                _replace_paragraph_text(para, cleaned)
                rewritten += 1
                comparisons.append({"section": title, "type": stype,
                                    "before": old_text, "after": cleaned})

    doc.save(str(out_path))
    return Path(out_path), rewritten, comparisons


def docx_to_text(docx_path: Union[str, Path]) -> str:
    """读取 docx 的所有段落文本（含表格、文本框），用于预览。"""
    doc = Document(str(docx_path))
    all_paras = _collect_all_paragraphs(doc)
    return "\n".join(p.text for p in all_paras if p.text.strip())


def _set_textboxes_autofit(doc):
    """将所有文本框设置为自适应大小，防止内容溢出被裁剪。"""
    # DrawingML 文本框：<a:bodyPr> 下的 <a:noAutofit/> 替换为 <a:spAutoFit/>
    for no_autofit in doc.element.iter(qn("a:noAutofit")):
        parent = no_autofit.getparent()
        parent.remove(no_autofit)
        sp_autofit = parent.makeelement(qn("a:spAutoFit"), {})
        parent.append(sp_autofit)

    # VML 文本框：移除固定高度样式中的 height 属性
    # v: 命名空间不在 python-docx 默认 nsmap 中，用完整 URI
    vml_textbox = "{urn:schemas-microsoft-com:vml}textbox"
    for textbox in doc.element.iter(vml_textbox):
        style = textbox.get("style", "")
        if "height" in style:
            style = re.sub(r"height[^;]*;?", "", style)
            textbox.set("style", style.strip())


def _calc_optimal_font_size(total_chars, page_w_cm, page_h_cm, margin_lr_cm, margin_tb_cm,
                            max_size=11.0, line_spacing=1.15):
    """根据内容字数和页面尺寸，动态计算最优字号。

    逐步降低字号直到内容能放入一页。
    返回 (font_size_pt, line_spacing)。
    """
    available_w_mm = (page_w_cm - 2 * margin_lr_cm) * 10
    available_h_mm = (page_h_cm - 2 * margin_tb_cm) * 10

    # 从最大字号逐步降到 6pt，找到能容纳所有内容的最小字号
    sizes = []
    s = max_size
    while s >= 6.0:
        sizes.append(round(s, 1))
        s -= 0.5
    for size_pt in sizes:
        char_w_mm = size_pt * 0.353
        chars_per_line = max(1, int(available_w_mm / char_w_mm))
        line_h_mm = size_pt * 0.353 * line_spacing * 1.25
        lines_per_page = max(1, int(available_h_mm / line_h_mm))
        # 保守估算：实际容量打 0.7 折（标题、段间距、照片等占空间）
        max_chars = int(chars_per_line * lines_per_page * 0.7)
        if max_chars >= total_chars:
            return size_pt, line_spacing

    return 6, line_spacing


def fit_to_one_page(docx_path: Union[str, Path], max_font_pt: float = 11.0) -> None:
    """自动调整文档格式，确保内容压缩到一页内。

    1. 将文本框设为自适应大小，防止内容溢出被裁剪
    2. 根据内容字数动态计算最优字号（非固定档位）
    3. 同步调整行距、边距、段间距
    """
    doc = Document(str(docx_path))
    all_paras = _collect_all_paragraphs(doc)
    total_chars = sum(len(p.text.strip()) for p in all_paras)

    # A4 页面尺寸
    PAGE_W, PAGE_H = 21.0, 29.7

    # 根据内容量选择边距/行距/段距档位
    if total_chars <= 800:
        margin_tb, margin_lr = 1.2, 1.8
        line_spacing = 1.5
        space_before, space_after = Pt(8), Pt(4)
    elif total_chars <= 1600:
        margin_tb, margin_lr = 1.0, 1.5
        line_spacing = 1.35
        space_before, space_after = Pt(5), Pt(2)
    elif total_chars <= 2400:
        margin_tb, margin_lr = 0.6, 1.0
        line_spacing = 1.15
        space_before, space_after = Pt(3), Pt(1)
    else:
        margin_tb, margin_lr = 0.4, 0.8
        line_spacing = 1.0
        space_before, space_after = Pt(1), Pt(0)

    # 动态计算最优字号
    font_size_pt, line_spacing = _calc_optimal_font_size(
        total_chars, PAGE_W, PAGE_H, margin_lr, margin_tb,
        max_size=max_font_pt, line_spacing=line_spacing
    )
    # 不超过指定最大字号（流式渲染短内容可放大到 12pt 填满页面）
    font_size_pt = min(font_size_pt, max_font_pt)
    font_size = Pt(font_size_pt)

    print(f"[INFO] fit_to_one_page: {total_chars} chars → font={font_size_pt}pt, "
          f"spacing={line_spacing}, margin_tb={margin_tb}cm, margin_lr={margin_lr}cm")

    # 1. 文本框设为自适应
    _set_textboxes_autofit(doc)

    # 2. 调整页面边距
    for section in doc.sections:
        section.top_margin = Cm(margin_tb)
        section.bottom_margin = Cm(margin_tb)
        section.left_margin = Cm(margin_lr)
        section.right_margin = Cm(margin_lr)

    # 3. 调整所有段落的字号、行距、间距
    for para in all_paras:
        for run in para.runs:
            current_size = run.font.size
            if current_size is None or current_size > font_size:
                run.font.size = font_size

        pf = para.paragraph_format
        pf.line_spacing = line_spacing
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE

        if pf.space_before is None or pf.space_before > space_before:
            pf.space_before = space_before
        if pf.space_after is None or pf.space_after > space_after:
            pf.space_after = space_after

    doc.save(str(docx_path))
