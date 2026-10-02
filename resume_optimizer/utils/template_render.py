# -*- coding: utf-8 -*-
"""流式模板渲染引擎：按模板配置自动生成标准流式布局 docx。

模板只需配置 4 项参数即可自动适配：
- layout_type: single_column / header_single / two_column
- primary_color: 主色（自动生成标题/高亮配色）
- avatar_position: top_right / left_side / top_center
- section_order: 模块顺序（summary/work_experience/projects/education/skills）

字体层级、间距、配色全部由引擎统一计算，内容增减自动适应一页。
"""
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor

MODULE_LABELS: Dict[str, str] = {
    "summary": "个人优势",
    "work_experience": "工作经历",
    "projects": "项目经历",
    "education": "教育背景",
    "skills": "专业技能",
}

_FONT_CN = "微软雅黑"
_FONT_EN = "Calibri"

# ── 系统级排版规范（所有流式模板强制生效）──
# 三级间距体系：模块级 > 标题级 > 内容级，自适应压缩时按“先大后小”等比缩放，
# 始终保持层级差（模块间距 > 标题间距 > 列表/段落间距）
SPACING_LEVELS = {
    "module": {"default": 18.0, "min": 10.5, "max": 28.0},   # 一级：模块之间
    "heading": {"default": 9.0, "min": 5.0, "max": 14.0},    # 二级：标题上下
    "content": {"default": 6.0, "min": 3.0, "max": 10.0},    # 三级：列表/段落
}

# 岗位类型 → 模块默认顺序（核心经历前置，保证版面重心）
ORDER_TECH = ["summary", "work_experience", "projects", "skills", "education"]
ORDER_ADMIN = ["summary", "work_experience", "skills", "education"]
_TECH_KEYWORDS = ("运维", "技术", "开发", "工程", "测试", "数据", "网络", "程序员", "工程师", "研发", "实施", "产品")
_ADMIN_KEYWORDS = ("行政", "人事", "助理", "文员", "秘书", "管理", "运营", "客服", "销售", "市场")


def resolve_section_order(config: dict, job_title: str = "") -> List[str]:
    """按岗位类型解析模块顺序；模板配置了顺序则优先使用模板顺序。"""
    cfg_order = config.get("section_order")
    if cfg_order:
        return cfg_order
    jt = (job_title or "").strip()
    if any(k in jt for k in _TECH_KEYWORDS):
        return list(ORDER_TECH)
    if any(k in jt for k in _ADMIN_KEYWORDS):
        return list(ORDER_ADMIN)
    return ["summary", "work_experience", "projects", "skills", "education"]

# 全局加粗规则：量化成果、条目头、技能分类标题自动识别
_QUANT_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|％|万|亿|倍|人|台|个|项|次|门|套|天|小时|分钟|人/次|家|份|篇))"
)
_ENTRY_RE = re.compile(r"(?:^|[^\d])((19|20)\d{2})\s*[.\-~/至到年]")
_SKILL_CAT_RE = re.compile(
    r"^(专业技术|办公软件|语言与技能证书|编程语言|数据分析|机器学习|数据库|其他能力|"
    r"证书|语言能力|计算机能力|语言水平|其他|工具|框架)[：:]"
)


def _text_width_pt(text: str, font_pt: float) -> float:
    """估算文本宽度：中文≈1em，半角≈0.62em。"""
    return sum((font_pt if ord(ch) > 0x2E80 else font_pt * 0.62) for ch in text)


def _estimate_height(data: dict, body_pt: float, usable_w_pt: float) -> float:
    """估算流式内容总高度（含标题与间距）。"""
    h1, h2, cap = body_pt * 1.8, body_pt * 1.25, body_pt * 0.9
    total = h1 * 1.45 + 10.0  # 姓名行
    total += cap * 1.6 + 8.0  # 联系方式行
    for key, label in MODULE_LABELS.items():
        content = (data.get(key) or "").strip()
        if not content:
            continue
        total += h2 * 1.5 + 14.0  # 模块标题 + 标题上下留白
        lines = 0
        for para in content.splitlines():
            para = para.strip()
            if not para:
                continue
            w = _text_width_pt(para.lstrip("-• "), body_pt)
            lines += max(1, math.ceil(w / max(usable_w_pt, 100.0)))
        total += lines * body_pt * 1.75
        total += 16.0  # 模块间距
    return total


def _set_font(run, size_pt: float, bold: bool = False, color: Optional[str] = None,
              cn: str = _FONT_CN):
    run.font.name = _FONT_EN
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color:
        try:
            run.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
        except ValueError:
            pass
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.makeelement(qn("w:rFonts"), {})
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:eastAsia"), cn)


def _add_heading_border(para, color_hex: str, width: float = 1.0, left_bar: bool = False):
    """模块标题装饰：底部主题色分割线 或 左侧色条。"""
    pPr = para._p.get_or_add_pPr()
    pBdr = pPr.makeelement(qn("w:pBdr"), {})
    sz = str(int(max(2, min(30, width * 8))))  # 1/8 pt
    tag = "left" if left_bar else "bottom"
    border = pBdr.makeelement(qn("w:" + tag), {
        qn("w:val"): "single", qn("w:sz"): sz, qn("w:space"): "3",
        qn("w:color"): color_hex,
    })
    pBdr.append(border)
    pPr.append(pBdr)


def _shade_paragraph(para, fill_hex: str):
    """给段落设置底色（用于头部色带）。"""
    pPr = para._p.get_or_add_pPr()
    shd = pPr.makeelement(qn("w:shd"), {
        qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): fill_hex,
    })
    pPr.append(shd)


def _add_paragraph(doc, text: str, size_pt: float, bold: bool = False,
                   color: Optional[str] = None, align=None,
                   space_after: float = 2.0, line: float = 1.4,
                   space_before: float = 0.0, font_family: str = _FONT_CN):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing = line
    run = p.add_run(text)
    _set_font(run, size_pt, bold=bold, color=color, cn=font_family)
    return p


def _add_content_paragraph(doc, line: str, body_pt: float, line_spacing: float,
                           space_after: float, primary: str, body_color: str = "#1F2937",
                           font_family: str = _FONT_CN):
    """按全局加粗规则渲染正文段落：
    - 日期开头的条目头（公司/学校/岗位）→ 600 半粗
    - 技能分类标题（如 专业技术：）→ 标签 600 半粗
    - 量化成果（数字+单位）→ 数字部分 600 半粗
    - 其余正文 → 400 常规
    """
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.line_spacing = line_spacing

    def add_run(text, bold, color=None):
        run = p.add_run(text)
        _set_font(run, body_pt, bold=bold, color=color or body_color, cn=font_family)
        return run

    if not line.startswith(("-", "•")) and _ENTRY_RE.search(line):
        add_run(line, True)
        return p
    m = _SKILL_CAT_RE.match(line)
    if m:
        label = m.group(1)
        add_run(line[:m.end()], True, color=primary)
        rest = line[m.end():]
        if rest:
            _add_quant_runs(p, rest, body_pt, add_run)
        return p
    _add_quant_runs(p, line, body_pt, add_run)
    return p


def _add_quant_runs(p, text, body_pt, add_run):
    """把正文按量化成果切分，数字+单位部分用 600 半粗。"""
    pos = 0
    for m in _QUANT_RE.finditer(text):
        if m.start() > pos:
            add_run(text[pos:m.start()], False)
        add_run(m.group(1), True)
        pos = m.end()
    if pos < len(text):
        add_run(text[pos:], False)


def _add_floating_picture(doc, paragraph, image_path, w_cm, h_cm, x_mm, y_mm):
    """添加「浮于文字上方」的浮动照片（VML 绝对定位，相对页面）。"""
    run = paragraph.add_run()
    inline = run.add_picture(str(image_path), width=Cm(w_cm), height=Cm(h_cm))
    inline_el = inline._inline
    blip = inline_el.find(".//" + qn("a:blip"))
    rid = blip.get(qn("r:embed"))
    # 移除内联 drawing，改用 VML 浮动 shape
    drawing = inline_el.getparent()
    run._r.remove(drawing)
    _VML = "urn:schemas-microsoft-com:vml"
    _OFFICE = "urn:schemas-microsoft-com:office:office"
    pict = OxmlElement("w:pict")
    shape = run._r.makeelement(f"{{{_VML}}}shape", {})
    shape.set("id", "photo1")
    shape.set("type", "#_x0000_t75")
    style = (f"position:absolute;left:{x_mm}mm;top:{y_mm}mm;"
             f"width:{w_cm}cm;height:{h_cm}cm;z-index:251658240;"
             "mso-position-horizontal-relative:page;"
             "mso-position-vertical-relative:page")
    shape.set("style", style)
    imagedata = run._r.makeelement(f"{{{_VML}}}imagedata", {})
    imagedata.set(qn("r:id"), rid)
    imagedata.set(f"{{{_OFFICE}}}title", "photo")
    shape.append(imagedata)
    pict.append(shape)
    run._r.append(pict)


def _add_header(doc, data: dict, body_pt: float, primary: str,
                avatar_position: str, photo_path: Optional[Path],
                font_family: str = _FONT_CN,
                header_style: str = "centered",
                header_color: Optional[str] = None):
    h1 = body_pt * 1.8
    cap = body_pt * 0.9
    name = (data.get("name") or "").strip()
    contact = (data.get("contact") or "").strip()
    job = (data.get("job_title") or "").strip()
    politics = (data.get("political_status") or "").strip()
    has_photo = photo_path is not None and Path(photo_path).exists()
    band = header_style == "band" and header_color
    name_color = "#FFFFFF" if band else None
    contact_color = "#F3F4F6" if band else "#6B7280"
    contact_line = contact
    if politics:
        contact_line = (contact_line + " | " if contact_line else "") + politics
    if job:
        contact_line = (contact_line + " | " if contact_line else "") + job

    # 文字头部（照片改为浮动，不占用文档流）
    last_p = None
    if avatar_position == "left_side":
        last_p = _add_paragraph(doc, name, h1, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT,
                                space_after=2, line=1.3, font_family=font_family,
                                color=name_color)
        last_p = _add_paragraph(doc, contact_line, cap,
                                color=contact_color, align=WD_ALIGN_PARAGRAPH.LEFT, space_after=8,
                                font_family=font_family)
    else:
        last_p = _add_paragraph(doc, name, h1, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
                                space_after=2, line=1.3, font_family=font_family,
                                color=name_color)
        last_p = _add_paragraph(doc, contact_line, cap,
                                color=contact_color, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8,
                                font_family=font_family)

    if band:
        # 头部色带：姓名与联系方式段落加底色
        for para in doc.paragraphs[-2:]:
            _shade_paragraph(para, header_color)

    # 浮动照片：浮于文字上方，相对页面定位
    if has_photo:
        if avatar_position == "left_side":
            x_mm, y_mm = 18.0, 12.0
        elif avatar_position == "top_center":
            x_mm, y_mm = (210.0 - 25.0) / 2.0, 12.0
        else:
            x_mm, y_mm = 210.0 - 18.0 - 25.0, 12.0
        # 锚点挂在最后一段（联系方式），避免额外空段落占用空间
        _add_floating_picture(doc, last_p, photo_path, 2.5, 3.3, x_mm, y_mm)


def _rule_trim(data: dict) -> dict:
    """第三级规则化精简：只动次要模块，绝不触碰工作/实习经历。"""
    out = dict(data)
    # 自我评价：压缩为 1 段
    summary = (out.get("summary") or "").strip()
    if summary:
        parts = [p.strip() for p in summary.splitlines() if p.strip()]
        out["summary"] = " ".join(parts[:2])[:160]
    # 主修课程/教育背景：保留首行（学校/专业/时间），压缩课程列表
    edu_lines = [p.strip() for p in (out.get("education") or "").splitlines() if p.strip()]
    if edu_lines:
        first = edu_lines[0]
        rest = [p for p in edu_lines[1:] if "主修课程" in p or "课程" in p]
        if rest:
            joined = "、".join(rest)[:80]
            out["education"] = first + "\n核心课程：" + joined.rstrip("、")[:60] + "等"
        else:
            out["education"] = first
    # 校园经历/项目：保留前 2 个条目
    proj_lines = [p.strip() for p in (out.get("projects") or "").splitlines() if p.strip()]
    if proj_lines:
        kept = []
        count = 0
        for ln in proj_lines:
            if ln.startswith(("-", "•")):
                if count < 6:
                    kept.append(ln)
                    count += 1
            else:
                if count < 2:
                    kept.append(ln)
        out["projects"] = "\n".join(kept)
    # 技能证书：合并为横向标签
    skills = (out.get("skills") or "").strip()
    if skills:
        parts = [x.strip() for x in skills.replace("\n", "、").split("、") if x.strip()]
        out["skills"] = "、".join(parts[:8])
    return out


def render_template(
    data: dict,
    config: dict,
    photo_path: Union[str, Path, None],
    out_path: Union[str, Path],
    force_squeeze: bool = False,
    quick: bool = False,
) -> dict:
    """按配置渲染标准流式模板，并用真实渲染校验强制单页 A4。

    压缩阶梯：间距 → 字号/行高 → 规则精简（不触碰核心经历）。
    内容过少时反向放大字号/间距填满页面。
    """
    primary = (config.get("primary_color") or "#5B5CFF").lstrip("#")
    theme = config.get("theme") or {}
    font_family = theme.get("font_family") or _FONT_CN
    title_style = theme.get("title_style") or "bottom_line"
    divider_color = (theme.get("divider_color") or primary).lstrip("#")
    divider_width = float(theme.get("divider_width") or 1.2)
    spacing_base = float(theme.get("spacing_base") or 1.0)
    body_color = theme.get("body_color") or "#1F2937"
    header_style = theme.get("header_style") or "centered"
    header_color = (theme.get("header_color") or "").lstrip("#") or None
    avatar_position = config.get("avatar_position") or "top_right"
    section_order = resolve_section_order(config, data.get("job_title") or "")
    total_chars = sum(len(str(v or "")) for v in data.values())
    # 单页安全区：A4 297mm - 上下边距 20mm*2 → 内容底部 ≤ 257mm ≈ 728pt（含页眉留白给 780pt）
    SAFE_BOTTOM = 842.0

    def build(body_pt, line, module_gap, para_gap, heading_space, payload,
              margin_tb=2.0, margin_lr=1.8, photo_clear=0.0):
        doc = Document()
        sec = doc.sections[0]
        sec.page_width = Mm(210)
        sec.page_height = Mm(297)
        sec.top_margin = Cm(margin_tb)
        sec.bottom_margin = Cm(margin_tb)
        sec.left_margin = Cm(margin_lr)
        sec.right_margin = Cm(margin_lr)
        style = doc.styles["Normal"]
        style.font.name = _FONT_EN
        style.font.size = Pt(body_pt)
        style.element.rPr.rFonts.set(qn("w:eastAsia"), font_family)
        _add_header(doc, payload, body_pt, primary, avatar_position,
                    Path(photo_path) if photo_path else None, font_family,
                    header_style, header_color)
        first = True
        for key in section_order:
            label = MODULE_LABELS.get(key)
            content = (payload.get(key) or "").strip()
            if not label or not content:
                continue
            p = doc.add_paragraph()
            pf = p.paragraph_format
            # 右上角浮动照片时，第一个板块下移避开照片区域
            pf.space_before = Pt(heading_space + (photo_clear if first else 0.0))
            pf.space_after = Pt(3)
            run = p.add_run(label)
            _set_font(run, body_pt * 1.25, bold=True, color=primary, cn=font_family)
            if title_style == "left_bar":
                _add_heading_border(p, divider_color, divider_width, left_bar=True)
            elif title_style == "bottom_line":
                _add_heading_border(p, divider_color, divider_width, left_bar=False)
            # plain：无装饰，仅主题色加粗标题
            for line_text in content.splitlines():
                line_text = line_text.strip()
                if not line_text:
                    continue
                _add_content_paragraph(doc, line_text, body_pt, line, para_gap, primary,
                                       body_color, font_family)
            doc.paragraphs[-1].paragraph_format.space_after = Pt(module_gap)
            first = False
        doc.save(str(out_path))

    def measure():
        """用 Word 真实渲染，返回内容底部位置（pt）。"""
        import os
        import time
        import tempfile
        import uuid
        from . import converter
        from .tmpfiles import safe_unlink
        import fitz

        # 每次调用用唯一文件名：固定名在多请求并发时会互相覆盖，
        # 且 Word COM 句柄未释放时删除会失败（safe_unlink 兜底）。
        tmp = os.path.join(tempfile.gettempdir(), "page_check_%s.pdf" % uuid.uuid4().hex)
        pdf = None
        try:
            converter.docx_to_pdf(str(out_path), tmp)
            pdf = fitz.open(tmp)
            page = pdf[0]
            if pdf.page_count > 1:
                # 多页即视为超出单页
                bottom = SAFE_BOTTOM + 200.0
            else:
                bottom = 0.0
                for b in page.get_text("blocks"):
                    bottom = max(bottom, b[3])
                for info in page.get_image_info():
                    bottom = max(bottom, info["bbox"][3])
        finally:
            if pdf is not None:
                try:
                    pdf.close()
                except BaseException:  # noqa: BLE001
                    pass
            safe_unlink(tmp)
        time.sleep(0.3)  # 避免连续启动 Word 过快
        return bottom

    # 默认参数（三级间距体系：模块级/标题级/内容级，按模板间距基数缩放）
    if force_squeeze:
        # 用户选择“缩小字号至9.5pt”的降级路径
        body_pt, line = 9.5, 1.3
        module_gap, para_gap, heading_space = 10.5, 3.0, 6.0
        margin_tb, margin_lr = 1.2, 1.4
    else:
        body_pt, line = 11.0, 1.6
        module_gap = SPACING_LEVELS["module"]["default"] * spacing_base
        heading_space = SPACING_LEVELS["heading"]["default"] * spacing_base
        para_gap = SPACING_LEVELS["content"]["default"] * spacing_base
        margin_tb, margin_lr = 2.0, 1.8
    has_photo = photo_path is not None and Path(str(photo_path)).exists()
    photo_clear = 0.0
    trimmed = False
    payload = dict(data)

    if quick:
        # 快速模式：仅按默认参数渲染一次，不做单页测量校验（用于预览图/主题验证）
        build(body_pt, line, module_gap, para_gap, heading_space, payload,
              margin_tb, margin_lr, photo_clear)
        return {"path": str(out_path), "fitted": True, "body_pt": body_pt,
                "margin_tb": margin_tb, "squeezed": False, "quick": True}

    for _ in range(10):
        build(body_pt, line, module_gap, para_gap, heading_space, payload,
              margin_tb, margin_lr, photo_clear)
        bottom = measure()
        if bottom <= SAFE_BOTTOM:
            # 内容过少：反向放大填满页面
            if bottom < 690.0 and (body_pt < 12.0 or line < 1.7 or module_gap < 21.0):
                if body_pt < 12.0:
                    body_pt = min(12.0, body_pt + 0.5)
                if line < 1.7:
                    line = min(1.7, line + 0.1)
                if module_gap < 21.0:
                    module_gap = min(21.0, module_gap + 1.5)
                continue
            break
        # 超出：先按“先大后小”压缩三级间距（模块级降幅最大，保持层级差）
        if module_gap > SPACING_LEVELS["module"]["min"]:
            module_gap = max(SPACING_LEVELS["module"]["min"], module_gap - 2.0)
            heading_space = max(SPACING_LEVELS["heading"]["min"],
                                heading_space - 1.0 * spacing_base)
            para_gap = max(SPACING_LEVELS["content"]["min"],
                           para_gap - 0.8 * spacing_base)
            continue
        if body_pt > 9.5 or line > 1.3:
            body_pt = max(9.5, body_pt - 0.5)
            line = max(1.3, line - 0.1)
            continue
        if not trimmed:
            payload = _rule_trim(payload)
            trimmed = True
            continue
        # 最后兜底：收紧页边距换取空间（保证强制单页）
        if margin_tb > 1.2 or margin_lr > 1.4:
            margin_tb = max(1.2, margin_tb - 0.4)
            margin_lr = max(1.4, margin_lr - 0.2)
            continue
        break

    # 最终校验（确保本次渲染结果已保存到 out_path）
    build(body_pt, line, module_gap, para_gap, heading_space, payload,
          margin_tb, margin_lr, photo_clear)
    bottom = measure()
    return {
        "path": str(out_path),
        "bottom": round(bottom, 1),
        "fitted": bottom <= SAFE_BOTTOM,
        "body_pt": body_pt,
        "margin_tb": margin_tb,
        "squeezed": body_pt <= 10.0 or margin_tb < 2.0 or trimmed,
    }
