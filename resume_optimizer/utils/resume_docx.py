# -*- coding: utf-8 -*-
"""v3 结构化简历 → Word 生成器。

输入统一 JSON 数据模型（editor-v3：resume + theme），输出一份 A4 单栏
流式 .docx。主题参数只影响颜色/字体/字号/间距；导出与网页预览保持
同一信息结构与层级（标题色条、条目右对齐时间、项目符号正文），
不追求像素级一致。photo 支持 dataURL；http(s) URL 尽力抓取，失败跳过。
"""
import base64
import io
import re
from typing import List, Optional, Tuple

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

PX2PT = 0.75  # 794px ≈ 21cm @96dpi

FONT_NAMES = {
    "yahei": "微软雅黑", "pingfang": "微软雅黑", "songti": "宋体",
    "heiti": "黑体", "kai": "楷体",
}

# 模块元数据：key → (中文标题, 类型)
MODULE_META = {
    "education":  ("教育背景", "list"),
    "internship": ("实习经历", "list"),
    "work":       ("工作经历", "list"),
    "project":    ("项目经历", "list"),
    "campus":     ("校园经历", "list"),
    "skill":      ("技能特长", "skill"),
    "honor":      ("荣誉证书", "honor"),
    "self":       ("自我评价", "text"),
    "custom":     ("其他经历", "text"),
    "hobby":      ("兴趣爱好", "tags"),
}

CONTACT_ORDER = [
    ("phone", "电话"), ("email", "邮箱"), ("wechat", "微信"), ("city", "现居"),
]
EXTRA_FIELD_LABEL = {
    "gender": "性别", "birth_date": "出生年月", "age": "年龄",
    "hometown": "籍贯", "nation": "民族", "political_status": "政治面貌",
    "marriage": "婚姻状况", "education_degree": "学历",
}

DEFAULT_THEME = {
    "primary": "#34549B", "font": "yahei", "fontSize": 13,
    "lineHeight": 1.72, "gap": 20, "nameSize": 30,
}


def _hex_or(value, fallback: str) -> str:
    v = str(value or "").strip().lstrip("#")
    return v.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", v) else fallback


def _shade(hex_color: str, factor: float) -> str:
    """factor<1 变深（乘系数），factor>1 向白混合。"""
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    if factor <= 1:
        r, g, b = int(r * factor), int(g * factor), int(b * factor)
    else:
        f = min(factor - 1, 1)
        r, g, b = (int(v + (255 - v) * f) for v in (r, g, b))
    return "%02X%02X%02X" % (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def _set_run_font(run, family: str, size_pt: float, color: str,
                  bold: bool = False, italic: bool = False) -> None:
    run.font.name = family
    run.font.size = Pt(size_pt)
    run.font.color.rgb = _rgb(color)
    run.font.bold = bold
    run.font.italic = italic
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), family)


def _para_border_bottom(p, color: str, size_eighth_pt: int = 6) -> None:
    ppr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size_eighth_pt))
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    ppr.append(pbdr)


def _spacing(p, before: float = 0, after: float = 0, line: Optional[float] = None) -> None:
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    if line:
        pf.line_spacing = line


def _has(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, tuple)):
        return len(v) > 0
    return str(v).strip() != ""


def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _range_text(x: dict) -> str:
    start = _s(x.get("start")) or _s(x.get("begin")) or _s(x.get("period"))
    if x.get("current"):
        end = "至今"
    else:
        end = _s(x.get("end"))
    if start and end:
        return f"{start} ~ {end}"
    return start or end


def _photo_bytes(photo) -> Optional[bytes]:
    """dataURL 优先；http(s) 尽力抓取（3 秒超时），失败返回 None。"""
    if not photo:
        return None
    photo = str(photo).strip()
    m = re.match(r"^data:image/(?:png|jpe?g|webp);base64,(.+)$", photo, re.S)
    if m:
        try:
            return base64.b64decode(m.group(1))
        except Exception:  # noqa: BLE001
            return None
    if photo.startswith(("http://", "https://")):
        try:
            import requests
            resp = requests.get(photo, timeout=3)
            return resp.content if resp.ok else None
        except Exception:  # noqa: BLE001
            return None
    return None


def _norm_items(raw) -> List[dict]:
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _content_lines(x: dict) -> List[str]:
    c = x.get("content")
    if not c:
        return []
    return [ln.strip() for ln in str(c).split("\n") if ln.strip()]


BULLET_MARK_RE = re.compile(r"^(?:\d{1,2}\s*[.、．）)]|[①-⑳]|[●◆✦►▸•·])")


def _bullet(p_line, text: str, family: str, size_pt: float, color: str) -> None:
    p_line.text = ""
    # 内容已自带序号/符号标记（1. 1） ① ● ◆ ✦ ► 等）时不再叠加圆点
    prefix = "" if BULLET_MARK_RE.match(text) else "• "
    run = p_line.add_run(prefix + text)
    _set_run_font(run, family, size_pt, color)
    pf = p_line.paragraph_format
    pf.left_indent = Cm(0.35)
    pf.first_line_indent = Cm(-0.35)


def generate_docx(resume: dict, theme: dict) -> bytes:
    """统一 JSON 模型 → docx 字节。"""
    resume = resume or {}
    theme = {**DEFAULT_THEME, **(theme or {})}
    primary = _hex_or(theme.get("primary"), DEFAULT_THEME["primary"])
    deep = _shade(primary, 0.72)
    soft = _shade(primary, 1.88)
    gray = "595959"
    body_color = "333333"
    family = FONT_NAMES.get(theme.get("font") or "yahei", "微软雅黑")
    body_pt = float(theme.get("fontSize") or 13) * PX2PT
    name_pt = float(theme.get("nameSize") or 30) * PX2PT
    line_h = float(theme.get("lineHeight") or 1.72)
    gap_pt = float(theme.get("gap") or 20) * PX2PT

    basic = resume.get("basic") or {}
    modules = resume.get("modules") or {}
    order = resume.get("order") or list(MODULE_META.keys())
    hidden = set(resume.get("hidden") or [])

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(1.4), Cm(1.4)
    content_width_cm = 18.0

    normal = doc.styles["Normal"]
    normal.font.name = family
    normal.font.size = Pt(body_pt)
    normal.font.color.rgb = _rgb(body_color)
    nrpr = normal.element.get_or_add_rPr()
    nrpr.get_or_add_rFonts().set(qn("w:eastAsia"), family)

    # ── 头部：姓名 / 求职意向 / 联系方式（+可选照片，右侧 2.4cm）──
    name = _s(basic.get("name")) or "姓名"
    intention = _s(basic.get("intention"))
    contacts = [(label, _s(basic.get(k))) for k, label in CONTACT_ORDER if _has(basic.get(k))]
    extras = [(label, _s(basic.get(k))) for k, label in EXTRA_FIELD_LABEL.items() if _has(basic.get(k))]

    photo_bytes = _photo_bytes(basic.get("photo"))
    head_cells = None
    if photo_bytes:
        tbl = doc.add_table(rows=1, cols=2)
        tbl.autofit = False
        left, right = tbl.rows[0].cells
        left.width, right.width = Cm(15.4), Cm(2.6)
        head_cells = (left.paragraphs[0], right.paragraphs[0])

    def head_para():
        return head_cells[0] if head_cells else doc.add_paragraph()

    p = head_para()
    _spacing(p, after=2)
    if intention:
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = p.add_run(name)
    _set_run_font(run, family, name_pt, deep, bold=True)

    if intention:
        p = head_para()
        _spacing(p, after=2)
        run = p.add_run("求职意向：" + intention)
        _set_run_font(run, family, body_pt + 1.5, primary, bold=True)

    if contacts:
        p = head_para()
        _spacing(p, after=2)
        run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in contacts))
        _set_run_font(run, family, body_pt, gray)

    if extras:
        p = head_para()
        _spacing(p, after=2)
        run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in extras))
        _set_run_font(run, family, body_pt, gray)

    if head_cells:
        run = head_cells[1].add_run()
        try:
            run.add_picture(io.BytesIO(photo_bytes), width=Cm(2.4))
        except Exception:  # noqa: BLE001
            pass
    elif photo_bytes:
        pass  # 已在表格分支处理；理论不可达

    # 头部下分隔线
    p = doc.add_paragraph()
    _spacing(p, after=4)
    _para_border_bottom(p, primary, 12)

    # ── 各模块 ──
    first_section = True
    for key in order:
        if key in hidden or key not in MODULE_META:
            continue
        label, kind = MODULE_META[key]
        raw = modules.get(key)
        title_pt = body_pt + 2

        items = _norm_items(raw)
        tags = raw if key == "hobby" and isinstance(raw, list) else []
        text_val = _s(raw) if kind == "text" else ""
        if kind == "list" and not items:
            continue
        if kind == "skill" and not items:
            continue
        if kind == "honor" and not items:
            continue
        if kind == "tags" and not tags:
            continue
        if kind == "text" and not text_val:
            continue

        p = doc.add_paragraph()
        _spacing(p, before=0 if first_section else gap_pt, after=4, line=line_h)
        _para_border_bottom(p, soft, 8)
        run = p.add_run(label)
        _set_run_font(run, family, title_pt, primary, bold=True)
        first_section = False

        if kind == "tags":
            p = doc.add_paragraph()
            _spacing(p, after=2, line=line_h)
            run = p.add_run("、".join(_s(t) for t in tags if _s(t)))
            _set_run_font(run, family, body_pt, body_color)
            continue

        if kind == "text":
            for ln in [x for x in text_val.split("\n") if x.strip()]:
                p = doc.add_paragraph()
                _spacing(p, after=2, line=line_h)
                run = p.add_run(ln.strip())
                _set_run_font(run, family, body_pt, body_color)
            continue

        for x in items:
            if kind == "list":
                title = _s(x.get("school")) or _s(x.get("company")) or _s(x.get("name"))
                sub_parts: Tuple[str, ...] = tuple()
                if key == "education":
                    sub_parts = tuple(v for v in (_s(x.get("degree")), _s(x.get("major"))) if v)
                else:
                    role = _s(x.get("position")) or _s(x.get("role"))
                    sub_parts = (role,) if role else tuple()
                meta = _range_text(x)
                lines = _content_lines(x)
                if not (title or meta or sub_parts or lines):
                    continue

                p = doc.add_paragraph()
                _spacing(p, before=2, after=1, line=line_h)
                sub_text = " · ".join(sub_parts)
                if sub_text:
                    p.paragraph_format.tab_stops.add_tab_stop(
                        Cm(content_width_cm / 2), WD_TAB_ALIGNMENT.CENTER)
                if meta:
                    p.paragraph_format.tab_stops.add_tab_stop(
                        Cm(content_width_cm), WD_TAB_ALIGNMENT.RIGHT)
                if title:
                    run = p.add_run(title)
                    _set_run_font(run, family, body_pt + 1, body_color, bold=True)
                if sub_text:
                    run = p.add_run("\t" + sub_text)
                    _set_run_font(run, family, body_pt, primary)
                if meta:
                    run = p.add_run("\t" + meta)
                    _set_run_font(run, family, body_pt, gray)
                for ln in lines:
                    p = doc.add_paragraph()
                    _spacing(p, after=1, line=line_h)
                    _bullet(p, ln, family, body_pt, body_color)
            elif kind == "skill":
                name_v = _s(x.get("name"))
                level = _s(x.get("level"))
                lines = _content_lines(x)
                head = name_v + (f"（{level}）" if level else "")
                if not (head or lines):
                    continue
                p = doc.add_paragraph()
                _spacing(p, before=2, after=1, line=line_h)
                run = p.add_run(head)
                _set_run_font(run, family, body_pt, body_color, bold=True)
                for ln in lines:
                    p = doc.add_paragraph()
                    _spacing(p, after=1, line=line_h)
                    _bullet(p, ln, family, body_pt, body_color)
            elif kind == "honor":
                name_v = _s(x.get("name"))
                time_v = _s(x.get("time")) or _s(x.get("date"))
                issuer = _s(x.get("issuer"))
                if not (name_v or time_v):
                    continue
                p = doc.add_paragraph()
                _spacing(p, before=2, after=1, line=line_h)
                p.paragraph_format.tab_stops.add_tab_stop(
                    Cm(content_width_cm), WD_TAB_ALIGNMENT.RIGHT)
                run = p.add_run(name_v + (f"（{issuer}）" if issuer else ""))
                _set_run_font(run, family, body_pt, body_color)
                if time_v:
                    run = p.add_run("\t" + time_v)
                    _set_run_font(run, family, body_pt, gray)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pdf_to_long_png(pdf_path: str, dpi: int = 150) -> bytes:
    """PDF 各页渲染后纵向拼接为一张 PNG 长图。"""
    import fitz
    from PIL import Image

    doc = fitz.open(pdf_path)
    try:
        images = []
        for page in doc:
            pm = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0))
            images.append(Image.frombytes("RGB", (pm.width, pm.height), pm.samples))
    finally:
        doc.close()
    if not images:
        raise RuntimeError("PDF 无页面")
    if len(images) == 1:
        out = images[0]
    else:
        width = max(im.width for im in images)
        height = sum(im.height for im in images)
        out = Image.new("RGB", (width, height), "white")
        y = 0
        for im in images:
            out.paste(im, (0, y))
            y += im.height
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()
