# -*- coding: utf-8 -*-
"""v3 结构化简历 → Word 生成器。

输入统一 JSON 数据模型（editor-v3：resume + theme），输出 A4 .docx。
**导出保真目标**：跟随编辑时选择的版式族（single/headerBar/sidebar/twoCol）、
主色、标题样式（underline/leftbar/bar/plain）、字体字号行距间距与模块显隐
排序，使下载成品与编辑预览保持同一版式（结构一致；Word 流式排版与网页
存在像素级差异属正常）。
"""
import base64
import io
import re
from typing import List, Optional, Tuple

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

PX2PT = 0.75  # 794px ≈ 21cm @96dpi

FONT_NAMES = {
    "yahei": "微软雅黑", "pingfang": "微软雅黑", "songti": "宋体",
    "heiti": "黑体", "kai": "楷体",
}

# 模块元数据：key → (中文标题, 类型, 图标) —— 图标与编辑器渲染一致
MODULE_META = {
    "education":  {"label": "教育背景", "kind": "list",  "icon": "🎓"},
    "internship": {"label": "实习经历", "kind": "list",  "icon": "🏢"},
    "work":       {"label": "工作经验", "kind": "list",  "icon": "💼"},
    "project":    {"label": "项目经验", "kind": "list",  "icon": "🚀"},
    "campus":     {"label": "校园经历", "kind": "list",  "icon": "🏛️"},
    "skill":      {"label": "技能特长", "kind": "skill", "icon": "⚡"},
    "honor":      {"label": "荣誉证书", "kind": "honor", "icon": "🏆"},
    "self":       {"label": "自我评价", "kind": "text",  "icon": "✨"},
    "custom":     {"label": "自定义",   "kind": "text",  "icon": "📝"},
    "hobby":      {"label": "兴趣爱好", "kind": "tags",  "icon": "💡"},
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
    "family": "single", "sectionStyle": "underline",
}

# sidebar 版式：这些模块进左侧深色栏（与编辑器渲染一致）
SIDE_KEYS = ("skill", "hobby")


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


def _para_border_left(p, color: str) -> None:
    ppr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")
    left.set(qn("w:space"), "4")
    left.set(qn("w:color"), color)
    pbdr.append(left)
    ppr.append(pbdr)
    pf = p.paragraph_format
    pf.left_indent = Cm(0.15)


def _para_shading(p, fill: str) -> None:
    ppr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr.append(shd)


def _cell_shading(cell, fill: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


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


class _Target:
    """统一 doc / table cell 的段落来源（cell 复用首个空段落）。"""

    def __init__(self, obj):
        self.obj = obj
        self._first_used = False

    def para(self):
        if hasattr(self.obj, "add_paragraph"):
            return self.obj.add_paragraph()
        paras = self.obj.paragraphs
        if not self._first_used and len(paras) == 1 and not paras[0].runs:
            self._first_used = True
            return paras[0]
        return self.obj.add_paragraph()


class _Ctx:
    """渲染上下文：颜色 / 字体 / 尺寸 / 数据。"""

    def __init__(self, resume: dict, theme: dict):
        theme = {**DEFAULT_THEME, **(theme or {})}
        self.primary = _hex_or(theme.get("primary"), DEFAULT_THEME["primary"])
        self.deep = _shade(self.primary, 0.72)
        self.soft = _shade(self.primary, 1.88)
        self.gray = "595959"
        self.body_color = "333333"
        self.on_dark_text = "FFFFFF"
        self.on_dark_muted = "DDE3EE"
        self.family_font = FONT_NAMES.get(theme.get("font") or "yahei", "微软雅黑")
        self.body_pt = float(theme.get("fontSize") or 13) * PX2PT
        self.name_pt = float(theme.get("nameSize") or 30) * PX2PT
        self.line_h = float(theme.get("lineHeight") or 1.72)
        self.gap_pt = float(theme.get("gap") or 20) * PX2PT
        self.family = theme.get("family") if theme.get("family") in ("single", "headerBar", "sidebar", "twoCol") else "single"
        self.section_style = theme.get("sectionStyle") if theme.get("sectionStyle") in ("underline", "leftbar", "bar", "plain") else "underline"

        basic = resume.get("basic") or {}
        self.basic = basic
        self.modules = resume.get("modules") or {}
        self.order = resume.get("order") or list(MODULE_META.keys())
        self.hidden = set(resume.get("hidden") or [])
        self.name = _s(basic.get("name")) or "姓名"
        self.intention = _s(basic.get("intention"))
        self.contacts = [(label, _s(basic.get(k))) for k, label in CONTACT_ORDER if _has(basic.get(k))]
        self.extras = [(label, _s(basic.get(k))) for k, label in EXTRA_FIELD_LABEL.items() if _has(basic.get(k))]
        self.photo_bytes = _photo_bytes(basic.get("photo"))

    def item_font(self):
        return self.family_font


def _section_title(t: _Target, ctx: _Ctx, label: str, icon: str,
                   width_cm: float, first: bool, on_dark: bool = False) -> None:
    """模块标题：跟随标题样式（underline/leftbar/bar/plain）；深色栏内固定白字。"""
    p = t.para()
    _spacing(p, before=0 if first else ctx.gap_pt, after=4, line=ctx.line_h)
    title_pt = ctx.body_pt + 2
    text = f"{icon} {label}" if icon else label
    if on_dark:
        run = p.add_run(text)
        _set_run_font(run, ctx.item_font(), title_pt, ctx.on_dark_text, bold=True)
        _para_border_bottom(p, "FFFFFF", 8)
        return
    if ctx.section_style == "bar":
        _para_shading(p, ctx.soft)
        pf = p.paragraph_format
        pf.left_indent = Cm(0.12)
        run = p.add_run(text)
        _set_run_font(run, ctx.item_font(), title_pt, ctx.deep, bold=True)
    elif ctx.section_style == "leftbar":
        _para_border_left(p, ctx.primary)
        run = p.add_run(text)
        _set_run_font(run, ctx.item_font(), title_pt, ctx.deep, bold=True)
    elif ctx.section_style == "plain":
        run = p.add_run(text)
        _set_run_font(run, ctx.item_font(), title_pt, ctx.deep, bold=True)
    else:  # underline
        run = p.add_run(text)
        _set_run_font(run, ctx.item_font(), title_pt, ctx.primary, bold=True)
        _para_border_bottom(p, ctx.primary, 12)


def _head_block(t: _Target, ctx: _Ctx, width_cm: float, with_extras: bool = True) -> None:
    """姓名 / 求职意向 / 联系方式（浅色头部，用于 single/twoCol/sidebar 主列）。"""
    p = t.para()
    _spacing(p, after=2, line=ctx.line_h)
    run = p.add_run(ctx.name)
    _set_run_font(run, ctx.item_font(), ctx.name_pt, ctx.deep, bold=True)
    if ctx.intention:
        p = t.para()
        _spacing(p, after=2)
        run = p.add_run("求职意向：" + ctx.intention)
        _set_run_font(run, ctx.item_font(), ctx.body_pt + 1.5, ctx.primary, bold=True)
    if ctx.contacts:
        p = t.para()
        _spacing(p, after=2)
        run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in ctx.contacts))
        _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.gray)
    if with_extras and ctx.extras:
        p = t.para()
        _spacing(p, after=2)
        run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in ctx.extras))
        _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.gray)
    p = t.para()
    _spacing(p, after=4)
    _para_border_bottom(p, ctx.primary, 12)


def _basic_grid(t: _Target, ctx: _Ctx) -> None:
    if not ctx.extras:
        return
    p = t.para()
    _spacing(p, after=2, line=ctx.line_h)
    run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in ctx.extras))
    _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.gray)


def _photo_paragraph(t: _Target, ctx: _Ctx, width_cm: float, center: bool = False) -> bool:
    if not ctx.photo_bytes:
        return False
    p = t.para()
    _spacing(p, after=4)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    try:
        run.add_picture(io.BytesIO(ctx.photo_bytes), width=Cm(width_cm))
        return True
    except Exception:  # noqa: BLE001
        return False


def _render_module(t: _Target, ctx: _Ctx, key: str, raw,
                   width_cm: float, first: bool, on_dark: bool = False) -> None:
    meta = MODULE_META[key]
    label, kind, icon = meta["label"], meta["kind"], meta["icon"]
    fam = ctx.item_font()
    body_pt = ctx.body_pt
    body_color = ctx.on_dark_text if on_dark else ctx.body_color
    muted = ctx.on_dark_muted if on_dark else ctx.gray
    accent = ctx.on_dark_text if on_dark else ctx.primary

    items = _norm_items(raw)
    tags = raw if key == "hobby" and isinstance(raw, list) else []
    text_val = _s(raw) if kind == "text" else ""
    if kind == "list" and not items:
        return
    if kind == "skill" and not items:
        return
    if kind == "honor" and not items:
        return
    if kind == "tags" and not tags:
        return
    if kind == "text" and not text_val:
        return

    _section_title(t, ctx, label, icon, width_cm, first, on_dark=on_dark)

    if kind == "tags":
        p = t.para()
        _spacing(p, after=2, line=ctx.line_h)
        run = p.add_run("、".join(_s(x) for x in tags if _s(x)))
        _set_run_font(run, fam, body_pt, body_color)
        return

    if kind == "text":
        for ln in [x for x in text_val.split("\n") if x.strip()]:
            p = t.para()
            _spacing(p, after=2, line=ctx.line_h)
            run = p.add_run(ln.strip())
            _set_run_font(run, fam, body_pt, body_color)
        return

    for x in items:
        if kind == "list":
            title = _s(x.get("school")) or _s(x.get("company")) or _s(x.get("name"))
            if key == "education":
                sub_parts: Tuple[str, ...] = tuple(v for v in (_s(x.get("degree")), _s(x.get("major"))) if v)
            else:
                role = _s(x.get("position")) or _s(x.get("role"))
                sub_parts = (role,) if role else tuple()
            meta_text = _range_text(x)
            lines = _content_lines(x)
            if not (title or meta_text or sub_parts or lines):
                continue

            p = t.para()
            _spacing(p, before=2, after=1, line=ctx.line_h)
            if sub_text := " · ".join(sub_parts):
                p.paragraph_format.tab_stops.add_tab_stop(Cm(width_cm / 2), WD_TAB_ALIGNMENT.CENTER)
            if meta_text:
                p.paragraph_format.tab_stops.add_tab_stop(Cm(width_cm), WD_TAB_ALIGNMENT.RIGHT)
            if title:
                run = p.add_run(title)
                _set_run_font(run, fam, body_pt + 1, body_color, bold=True)
            if sub_text:
                run = p.add_run("\t" + sub_text)
                _set_run_font(run, fam, body_pt, accent)
            if meta_text:
                run = p.add_run("\t" + meta_text)
                _set_run_font(run, fam, body_pt, muted)
            for ln in lines:
                p = t.para()
                _spacing(p, after=1, line=ctx.line_h)
                _bullet(p, ln, fam, body_pt, body_color)
        elif kind == "skill":
            name_v = _s(x.get("name"))
            level = _s(x.get("level"))
            lines = _content_lines(x)
            head = name_v
            if not (head or level or lines):
                continue
            if head or level:
                p = t.para()
                _spacing(p, before=2, after=1, line=ctx.line_h)
                p.paragraph_format.tab_stops.add_tab_stop(Cm(width_cm), WD_TAB_ALIGNMENT.RIGHT)
                run = p.add_run(head)
                _set_run_font(run, fam, body_pt, body_color, bold=True)
                if level:
                    run = p.add_run("\t" + level)
                    _set_run_font(run, fam, body_pt, muted)
            for ln in lines:
                p = t.para()
                _spacing(p, after=1, line=ctx.line_h)
                _bullet(p, ln, fam, body_pt, body_color)
        elif kind == "honor":
            name_v = _s(x.get("name"))
            time_v = _s(x.get("time")) or _s(x.get("date"))
            issuer = _s(x.get("issuer"))
            if not (name_v or time_v):
                continue
            p = t.para()
            _spacing(p, before=2, after=1, line=ctx.line_h)
            p.paragraph_format.tab_stops.add_tab_stop(Cm(width_cm), WD_TAB_ALIGNMENT.RIGHT)
            run = p.add_run(name_v + (f"（{issuer}）" if issuer else ""))
            _set_run_font(run, fam, body_pt, body_color)
            if time_v:
                run = p.add_run("\t" + time_v)
                _set_run_font(run, fam, body_pt, muted)


def _render_sections(t: _Target, ctx: _Ctx, width_cm: float,
                     skip_side: bool = False, on_dark: bool = False) -> None:
    first = True
    for key in ctx.order:
        if key in ctx.hidden or key not in MODULE_META:
            continue
        if skip_side and key in SIDE_KEYS:
            continue
        raw = ctx.modules.get(key)
        _render_module(t, ctx, key, raw, width_cm, first, on_dark=on_dark)
        first = False


def _new_doc(ctx: _Ctx) -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(1.4), Cm(1.4)
    normal = doc.styles["Normal"]
    normal.font.name = ctx.item_font()
    normal.font.size = Pt(ctx.body_pt)
    normal.font.color.rgb = _rgb(ctx.body_color)
    nrpr = normal.element.get_or_add_rPr()
    nrpr.get_or_add_rFonts().set(qn("w:eastAsia"), ctx.item_font())
    return doc


def _build_single_headerBar(doc: Document, ctx: _Ctx, banner: bool) -> None:
    """single / headerBar：headerBar 先画主色横幅（姓名/意向/联系方式 + 照片）。"""
    if banner:
        tbl = doc.add_table(rows=1, cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        left, right = tbl.rows[0].cells
        left.width, right.width = Cm(15.0), Cm(3.0)
        for c in (left, right):
            _cell_shading(c, ctx.primary)
        lt = _Target(left)
        p = lt.para()
        _spacing(p, after=2)
        run = p.add_run(ctx.name)
        _set_run_font(run, ctx.item_font(), ctx.name_pt, ctx.on_dark_text, bold=True)
        if ctx.intention:
            p = lt.para()
            _spacing(p, after=2)
            run = p.add_run(ctx.intention)
            _set_run_font(run, ctx.item_font(), ctx.body_pt + 1.5, ctx.on_dark_text, bold=True)
        if ctx.contacts:
            p = lt.para()
            _spacing(p, after=0)
            run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in ctx.contacts))
            _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.on_dark_muted)
        if ctx.photo_bytes:
            rt = _Target(right)
            p = rt.para()
            _spacing(p, after=0)
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = p.add_run()
            try:
                run.add_picture(io.BytesIO(ctx.photo_bytes), width=Cm(2.4))
            except Exception:  # noqa: BLE001
                pass
        doc.add_paragraph()  # 横幅与正文的间隔

    t = _Target(doc)
    _basic_grid(t, ctx)
    _render_sections(t, ctx, 18.0)


def _build_sidebar(doc: Document, ctx: _Ctx) -> None:
    """sidebar：左侧深色栏（照片/联系方式/基本信息/技能/爱好）+ 右侧主列。"""
    tbl = doc.add_table(rows=1, cols=2)
    tbl.autofit = False
    left, right = tbl.rows[0].cells
    left.width, right.width = Cm(5.8), Cm(12.2)
    _cell_shading(left, ctx.deep)
    side_w, main_w = 5.0, 11.6

    side = _Target(left)
    _photo_paragraph(side, ctx, 3.2, center=True)
    first_side = True
    if ctx.contacts:
        _section_title(side, ctx, "联系方式", "", side_w, first_side, on_dark=True)
        for label, v in ctx.contacts:
            p = side.para()
            _spacing(p, after=2, line=ctx.line_h)
            run = p.add_run(f"{label}：{v}")
            _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.on_dark_text)
        first_side = False
    if ctx.extras:
        _section_title(side, ctx, "基本信息", "", side_w, first_side, on_dark=True)
        for label, v in ctx.extras:
            p = side.para()
            _spacing(p, after=2, line=ctx.line_h)
            run = p.add_run(f"{label}：{v}")
            _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.on_dark_text)
        first_side = False

    main = _Target(right)
    p = main.para()
    _spacing(p, after=2, line=ctx.line_h)
    run = p.add_run(ctx.name)
    _set_run_font(run, ctx.item_font(), ctx.name_pt, ctx.deep, bold=True)
    if ctx.intention:
        p = main.para()
        _spacing(p, after=4)
        run = p.add_run("求职意向：" + ctx.intention)
        _set_run_font(run, ctx.item_font(), ctx.body_pt + 1.5, ctx.primary, bold=True)
    p = main.para()
    _spacing(p, after=4)
    _para_border_bottom(p, ctx.primary, 12)

    first_main = True
    for key in ctx.order:
        if key in ctx.hidden or key not in MODULE_META:
            continue
        raw = ctx.modules.get(key)
        if key in SIDE_KEYS:
            _render_module(side, ctx, key, raw, side_w, first_side, on_dark=True)
            if _module_has_content(ctx, key, raw):
                first_side = False
        else:
            _render_module(main, ctx, key, raw, main_w, first_main)
            if _module_has_content(ctx, key, raw):
                first_main = False


def _module_has_content(ctx: _Ctx, key: str, raw) -> bool:
    meta = MODULE_META[key]
    kind = meta["kind"]
    if kind == "tags":
        return isinstance(raw, list) and any(_s(x) for x in raw)
    if kind == "text":
        return bool(_s(raw))
    items = _norm_items(raw)
    if not items:
        return False
    if kind == "skill":
        return any(_s(x.get("name")) or _s(x.get("level")) or _content_lines(x) for x in items)
    if kind == "honor":
        return any(_s(x.get("name")) or _s(x.get("time")) or _s(x.get("date")) for x in items)
    return True


def _build_two_col(doc: Document, ctx: _Ctx) -> None:
    """twoCol：头部 + 基本信息 + 双栏流式模块。"""
    t = _Target(doc)
    p = t.para()
    _spacing(p, after=2, line=ctx.line_h)
    run = p.add_run(ctx.name)
    _set_run_font(run, ctx.item_font(), ctx.name_pt, ctx.deep, bold=True)
    if ctx.intention:
        p = t.para()
        _spacing(p, after=2)
        run = p.add_run("求职意向：" + ctx.intention)
        _set_run_font(run, ctx.item_font(), ctx.body_pt + 1.5, ctx.primary, bold=True)
    if ctx.contacts:
        p = t.para()
        _spacing(p, after=2)
        run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in ctx.contacts))
        _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.gray)
    if ctx.photo_bytes:
        _photo_paragraph(t, ctx, 2.4)
    p = t.para()
    _spacing(p, after=4)
    _para_border_bottom(p, ctx.primary, 12)
    _basic_grid(t, ctx)

    # 双栏分节（后续模块内容在两栏间流式排布）
    cols = doc.sections[0]._sectPr.xpath("./w:cols")
    if cols:
        cols[0].set(qn("w:num"), "2")
        cols[0].set(qn("w:space"), "425")
    else:
        c = OxmlElement("w:cols")
        c.set(qn("w:num"), "2")
        c.set(qn("w:space"), "425")
        doc.sections[0]._sectPr.append(c)
    _render_sections(t, ctx, 8.6)


def generate_docx(resume: dict, theme: dict) -> bytes:
    """统一 JSON 模型 → docx 字节（跟随版式族与标题样式）。"""
    ctx = _Ctx(resume or {}, theme or {})
    doc = _new_doc(ctx)
    if ctx.family == "headerBar":
        _build_single_headerBar(doc, ctx, banner=True)
    elif ctx.family == "sidebar":
        _build_sidebar(doc, ctx)
    elif ctx.family == "twoCol":
        _build_two_col(doc, ctx)
    else:
        t = _Target(doc)
        if ctx.photo_bytes:
            tbl = doc.add_table(rows=1, cols=2)
            tbl.autofit = False
            left, right = tbl.rows[0].cells
            left.width, right.width = Cm(15.4), Cm(2.6)
            ht = _Target(left)
            p = ht.para()
            _spacing(p, after=2, line=ctx.line_h)
            run = p.add_run(ctx.name)
            _set_run_font(run, ctx.item_font(), ctx.name_pt, ctx.deep, bold=True)
            if ctx.intention:
                p = ht.para()
                _spacing(p, after=2)
                run = p.add_run("求职意向：" + ctx.intention)
                _set_run_font(run, ctx.item_font(), ctx.body_pt + 1.5, ctx.primary, bold=True)
            if ctx.contacts:
                p = ht.para()
                _spacing(p, after=2)
                run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in ctx.contacts))
                _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.gray)
            if ctx.extras:
                p = ht.para()
                _spacing(p, after=2)
                run = p.add_run("  |  ".join(f"{label}：{v}" for label, v in ctx.extras))
                _set_run_font(run, ctx.item_font(), ctx.body_pt, ctx.gray)
            rt = _Target(right)
            p = rt.para()
            _spacing(p, after=0)
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = p.add_run()
            try:
                run.add_picture(io.BytesIO(ctx.photo_bytes), width=Cm(2.4))
            except Exception:  # noqa: BLE001
                pass
            p = t.para()
            _spacing(p, after=4)
            _para_border_bottom(p, ctx.primary, 12)
            _basic_grid(t, ctx)
            _render_sections(t, ctx, 18.0)
        else:
            _head_block(t, ctx, 18.0)
            _basic_grid(t, ctx)
            _render_sections(t, ctx, 18.0)
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
