"""模板填充模块：将优化后的结构化内容填入管理员上传的 .docx 模板。

- 遍历文档所有段落（含表格、文本框内段落），查找 {{标签}} 占位符
- 整段占位符：多行内容拆分为多段，复制原段样式依次插入
- 混合文本占位符（如 "姓名：{{姓名}}"）：原位替换，多行用段内换行
- 占位符标签含"照片"且提供了照片：在该段插入图片
- 替换保留原段落/run 的字体、大小、颜色、对齐等样式
"""
import copy
import re
from pathlib import Path
from typing import Dict, List, Union

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Mm
from docx.text.paragraph import Paragraph

from . import reflow, section_mapper

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
# 「标签：值」字段对（值不含空格），用于清空模板示例值
_PAIR_SPLIT_RE = re.compile(r"([^\s：:]{1,16})\s*[：:]\s*([^\s：:]+)")


def _clear_run_text(run) -> None:
    """只清除 run 中的文本节点，保留图片/文本框锚点（w:drawing/w:pict 等）。"""
    for child in list(run._r):
        tag = child.tag.split("}")[-1]
        if tag in ("t", "br", "cr", "tab", "instrText", "delText"):
            run._r.remove(child)


def _set_run_text(run, text: str) -> None:
    """设置 run 文本，保留其中的文本框/图片锚点（AlternateContent/drawing/pict）。"""
    t_el = None
    for child in list(run._r):
        if child.tag.split("}")[-1] == "t":
            t_el = child
            break
    if t_el is None:
        t_el = run._r.makeelement(qn("w:t"), {})
        t_el.set(qn("xml:space"), "preserve")
        rPr = run._r.find(qn("w:rPr"))
        if rPr is not None:
            rPr.addnext(t_el)
        else:
            run._r.insert(0, t_el)
    t_el.text = text
    for child in list(run._r):
        tag = child.tag.split("}")[-1]
        if tag in ("t", "br", "cr", "tab") and child is not t_el:
            run._r.remove(child)


def _set_para_text(para: Paragraph, text: str) -> None:
    """用首个 run 承载文本（保留其格式），清空其余 run。"""
    if para.runs:
        _set_run_text(para.runs[0], text)
        for run in para.runs[1:]:
            _clear_run_text(run)
    else:
        para.add_run(text)


def _set_para_text_multiline(para: Paragraph, text: str) -> None:
    """混合文本替换：多行内容用段内换行符（w:br）呈现。"""
    parts = (text or "").split("\n")
    if not parts:
        parts = [""]
    run = para.runs[0] if para.runs else para.add_run("")
    _set_run_text(run, parts[0])
    for part in parts[1:]:
        run.add_break()
        run.add_text(part)
    for r in para.runs[1:]:
        _clear_run_text(r)


def _set_para_lines(para: Paragraph, lines) -> None:
    """重建段落为多行（段内 w:br 换行），保留首个 run 的字体格式。"""
    if not lines:
        lines = [""]
    run = para.runs[0] if para.runs else para.add_run("")
    _set_run_text(run, lines[0])
    for part in lines[1:]:
        run.add_break()
        run.add_text(part)
    for r in para.runs[1:]:
        _clear_run_text(r)


def _normalize_spaces(text: str) -> str:
    """把连续多个空格压成单个空格（实习行时间/公司/岗位更易保持一行）。"""
    return re.sub(r" {2,}", " ", text or "")


def _is_in_textbox(p_elem) -> bool:
    """判断段落是否位于文本框内。"""
    cur = p_elem.getparent()
    while cur is not None:
        if cur.tag == qn("w:txbxContent"):
            return True
        cur = cur.getparent()
    return False


def _is_in_table(p_elem) -> bool:
    """判断段落是否位于表格单元格内。"""
    cur = p_elem
    while cur is not None:
        if cur.tag == qn("w:tc"):
            return True
        cur = cur.getparent()
    return False


def _copy_para_after(src_para: Paragraph) -> Paragraph:
    """深拷贝段落并插入到原段之后，返回新段落（样式与源段落完全一致）。"""
    new_p = copy.deepcopy(src_para._p)
    src_para._p.addnext(new_p)
    return Paragraph(new_p, src_para._parent)


def _containing_box_size(para: Paragraph):
    """返回照片所在文本框的尺寸 (宽pt, 高pt)；不在文本框内时返回 None。"""
    cur = para._p.getparent()
    while cur is not None:
        tag = cur.tag.split("}")[-1]
        if tag == "anchor":  # DrawingML 文本框：wp:extent
            ext = cur.find(qn("wp:extent"))
            if ext is not None and ext.get("cx") and ext.get("cy"):
                return (int(ext.get("cx")) / 12700.0, int(ext.get("cy")) / 12700.0)
        if tag == "shape":  # VML 文本框：style 中 width/height
            m = re.search(r"width:([-\d.]+)pt;height:([-\d.]+)pt", cur.get("style") or "")
            if m:
                return (float(m.group(1)), float(m.group(2)))
        cur = cur.getparent()
    return None


def _photo_cm_size(para: Paragraph):
    """计算照片尺寸（cm）：默认 2.5x3.3；若在文本框内则按 3:4 比例适配框尺寸（留 4pt 边距），
    且不超过标准尺寸。"""
    std_w, std_h = 2.5, 3.3
    box = _containing_box_size(para)
    if box is None:
        return std_w, std_h
    bw, bh = box
    # 3:4 照片适配框内
    fit_h = max(bh - 4, 20)
    fit_w = fit_h * 3 / 4
    if fit_w > bw - 4:
        fit_w = max(bw - 4, 20)
        fit_h = fit_w * 4 / 3
    # 不超过标准尺寸
    if fit_w >= std_w and fit_h >= std_h:
        return std_w, std_h
    return (fit_w / 28.3465, fit_h / 28.3465)  # pt -> cm


def _insert_photo(para: Paragraph, photo_path: Union[str, Path]) -> None:
    """在段落中插入证件照并居中，同时清掉原占位符文本。"""
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run()
    w_cm, h_cm = _photo_cm_size(para)
    run.add_picture(str(photo_path), width=Cm(w_cm), height=Cm(h_cm))
    # 清空原 {{照片}} 占位符文本（按底层 XML 元素比较，避免误删照片 run）
    photo_r = run._r
    for r in para.runs:
        if r._r is not photo_r:
            _clear_run_text(r)


# 文本框默认内边距（VML textbox 默认 inset 0.1" = 7.2pt/侧），加 0.8pt 安全余量
_TEXTBOX_INSET_PT = 8.0
# 大字号显示框（如简历姓名 28pt）：放不下"标签+值"时优先去掉标签保留大字
_LARGE_FONT_PT = 20.0
_FONT_MIN_PT = 8.0


def _para_font_size(para: Paragraph):
    """返回段落首个 run 的字号（pt），取不到时返回 None。"""
    for run in para.runs:
        rPr = run._r.find(qn("w:rPr"))
        if rPr is not None:
            sz = rPr.find(qn("w:sz"))
            if sz is not None and sz.get(qn("w:val")):
                return int(sz.get(qn("w:val"))) / 2.0
    return None


def _first_line_indent_pt(para: Paragraph) -> float:
    """返回段落首行缩进（pt），无缩进返回 0。"""
    pPr = para._p.find(qn("w:pPr"))
    if pPr is None:
        return 0.0
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        return 0.0
    fl = ind.get(qn("w:firstLine"))
    if fl:
        return int(fl) / 20.0  # twips -> pt
    flChars = ind.get(qn("w:firstLineChars"))
    if flChars:
        fs = _para_font_size(para) or 11.0
        return int(flChars) / 100.0 * fs
    return 0.0


def _text_width_pt(text: str, font_size: float) -> float:
    """估算文本宽度（pt）：中文/全角≈1em，半角（数字/字母）≈0.62em。"""
    w = 0.0
    for ch in text:
        if ord(ch) > 0x2E80:
            w += font_size
        else:
            w += font_size * 0.62
    return w


def _set_run_font_size(para: Paragraph, size_pt: float) -> None:
    """把段落所有 run 的字号设为 size_pt（半磅）。"""
    half = str(int(round(size_pt * 2)))
    for run in para.runs:
        rPr = run._r.find(qn("w:rPr"))
        if rPr is None:
            rPr = run._r.makeelement(qn("w:rPr"), {})
            run._r.insert(0, rPr)
        for tag in ("w:sz", "w:szCs"):
            el = rPr.find(qn(tag))
            if el is None:
                el = rPr.makeelement(qn(tag), {})
                rPr.append(el)
            el.set(qn("w:val"), half)


def _fit_textbox_inline(para: Paragraph, text: str) -> str:
    """文本框内"标签：值"单行适配：内容超宽时缩字号（保标签）或去掉标签（大字号框）。

    返回适配后的填充文本；可能修改段落字号。
    """
    box = _containing_box_size(para)
    if box is None:
        return text
    bw, _bh = box
    usable = bw - 2 * _TEXTBOX_INSET_PT - _first_line_indent_pt(para)
    if usable <= 10:
        return text
    fs = _para_font_size(para) or 11.0

    def fits(t, f):
        return _text_width_pt(t, f) <= usable

    if fits(text, fs):
        return text

    # 拆"标签：值"
    m = re.match(r"^([^：:]{1,8}[：:])(.*)$", text, re.S)
    label, value = (m.group(1), m.group(2)) if m else ("", text)

    if label:
        # 大字号框（姓名等）：优先去掉标签，保留大字
        if fs >= _LARGE_FONT_PT and fits(value, fs):
            return value
        # 缩小字号，尽量保留标签
        f = fs
        while f > _FONT_MIN_PT and not fits(text, f):
            f -= 0.5
        if fits(text, f):
            _set_run_font_size(para, f)
            return text
        # 仍超宽：去掉标签
        if fits(value, fs):
            return value
        f = fs
        while f > _FONT_MIN_PT and not fits(value, f):
            f -= 0.5
        _set_run_font_size(para, f)
        return value
    # 无标签：缩小字号
    f = fs
    while f > _FONT_MIN_PT and not fits(text, f):
        f -= 0.5
    if fits(text, f):
        _set_run_font_size(para, f)
    return text


def _para_font_size(para: Paragraph):
    """返回段落首个 run 的字号（pt），取不到时返回 None。"""
    for run in para.runs:
        rPr = run._r.find(qn("w:rPr"))
        if rPr is not None:
            sz = rPr.find(qn("w:sz"))
            if sz is not None and sz.get(qn("w:val")):
                return int(sz.get(qn("w:val"))) / 2.0
    return None


def _textbox_placeholder_labels(elem, doc):
    """收集元素内所有文本框占位符标签集合。"""
    labels = set()
    for p in elem.iter(qn("w:p")):
        para = Paragraph(p, doc)
        for m in PLACEHOLDER_RE.finditer(para.text or ""):
            labels.add(m.group(1).strip())
    return labels


def _textbox_texts(elem, doc):
    """收集元素内所有文本框的非空文本（用于识别静态重复副本）。"""
    texts = []
    for p in elem.iter(qn("w:p")):
        t = Paragraph(p, doc).text.strip()
        if t:
            texts.append(t)
    return texts


def _remove_fallback_duplicates(doc) -> int:
    """移除 mc:AlternateContent 中与 Choice 重复的 Fallback 文本框副本。

    pdf2docx 转换的模板会同时生成 DrawingML(Choice) 与 VML(Fallback) 两套文本框，
    某些渲染路径会同时渲染导致内容重叠/重复。保留 Choice、删除 Fallback：
    - 两者含相同占位符（常规模板）；
    - Choice 已含内容/占位符（自动补占位符后的模板，Fallback 仍是旧示例文本，必须删）。
    """
    removed = 0
    for ac in doc.element.findall(".//{%s}AlternateContent" % MC_NS):
        choice = ac.find("{%s}Choice" % MC_NS)
        fallback = ac.find("{%s}Fallback" % MC_NS)
        if choice is None or fallback is None:
            continue
        c_labels = _textbox_placeholder_labels(choice, doc)
        f_labels = _textbox_placeholder_labels(fallback, doc)
        c_texts = _textbox_texts(choice, doc)
        f_texts = _textbox_texts(fallback, doc)
        same_labels = bool(c_labels) and c_labels == f_labels
        same_text = bool(c_texts) and c_texts == f_texts
        # 删除条件：仅在「Choice 与 Fallback 内容实质重复」时删 Fallback
        # - same_labels/same_text：占位符或文字完全一致
        # - Choice 有真实内容 且 Fallback 为空：fallback 是空装饰框，删它避免重影
        # 严禁：只要 Choice 有文字就无条件删 Fallback（会误杀模块标题"教育背景"等装饰文本框）
        empty_fallback = (not f_texts) and (not f_labels)
        if same_labels or same_text or ((c_texts or c_labels) and empty_fallback):
            ac.remove(fallback)
            removed += 1
    return removed


def _force_a4(doc) -> None:
    """所有节强制 A4 画布（210x297mm），禁止 Letter 等非标准尺寸。"""
    for sec in doc.sections:
        sec.page_width = Mm(210)
        sec.page_height = Mm(297)


def _clean_trailing_labels(doc) -> int:
    """清理“主修课程：”等静态标签与内容重复的问题（尾部多余标签删除）。"""
    fixed = 0
    # 1) 同一段内出现多次“主修课程：”时删除尾部多余标签
    for p in doc.element.iter(qn("w:p")):
        para = Paragraph(p, doc)
        t = para.text or ""
        if t.count("主修课程：") <= 1:
            continue
        new = re.sub(r"(?:\s*/\s*)?主修课程：+\s*$", "", t)
        if new != t:
            _set_para_text(para, new)
            fixed += 1
    # 2) 文本框内：静态“主修课程：”标签段 与 内容段重复时，清空静态标签段
    for txbx in doc.element.findall(".//" + qn("w:txbxContent")):
        paras = []
        for p in txbx.iter(qn("w:p")):
            para = Paragraph(p, doc)
            if para.text and para.text.strip():
                paras.append(para)
        has_content = any(
            p.text.strip().startswith("主修课程：") and len(p.text.strip()) > 6
            for p in paras
        )
        if not has_content:
            continue
        for p in paras:
            if p.text.strip() == "主修课程：" or p.text.strip() == "主修课程： ":
                _set_para_text(p, "")
                fixed += 1
    return fixed


def normalize_docx(doc, photo_path=None, primary_color=None,
                   preserve_layout=False) -> dict:
    """填充后的统一排版规范。

    preserve_layout=True（保真模式）：只做 A4 校验、去重复副本、照片替换，
    不重排文本框位置、不改间距/字号/颜色——模板原样保留。
    preserve_layout=False（旧自适应）：完整执行重排与排版归一化。
    """
    stats = {
        "removed_fallback": _remove_fallback_duplicates(doc),
        "textbox_based": len(doc.element.findall(".//" + qn("w:txbxContent"))) > 0,
    }
    _force_a4(doc)
    stats["cleaned_labels"] = _clean_trailing_labels(doc)
    if preserve_layout:
        stats["preserved"] = True
        stats["typography"] = {"headings": 0, "bullets": 0}
        if stats["textbox_based"]:
            stats["reflow"] = {"reflowed": False}
            stats["photo_replaced"] = reflow.replace_photo(doc, photo_path)
            stats["gaps_tightened"] = reflow.tighten_gaps(doc)
        else:
            stats["reflow"] = {"reflowed": False}
            stats["photo_replaced"] = False
            stats["gaps_tightened"] = 0
        return stats
    # 全局排版归一化：三级间距层级 + 列表符号统一（不改主题色/字体/布局）
    stats["typography"] = reflow.normalize_typography(doc)
    if stats["textbox_based"]:
        # 文本框模板：按内容高度重排板块，防止间距过大与内容重叠
        stats["reflow"] = reflow.reflow_textboxes(doc, primary_color=primary_color)
        # 替换模板内置示例照片（模板无 {{照片}} 占位符时）
        stats["photo_replaced"] = reflow.replace_photo(doc, photo_path)
    else:
        stats["reflow"] = {"reflowed": False}
        stats["photo_replaced"] = False
    return stats


def _apply_replacements(para: Paragraph, content_map: Dict[str, str],
                        photo_path: Union[str, Path, None]) -> None:
    """处理一个段落内的占位符替换。"""
    text = para.text or ""
    if not PLACEHOLDER_RE.search(text):
        return

    # ── 整段占位符（最常见，模板一般这样设计）──
    m = PLACEHOLDER_RE.fullmatch(text.strip())
    if m:
        label = m.group(1).strip()
        # 照片占位符（支持 {{照片}} / {{photo}} / {{avatar}}）
        if photo_path and Path(str(photo_path)).exists() and (
                "照片" in label or "photo" in label.lower() or label.lower() == "avatar"):
            _insert_photo(para, photo_path)
            return
        content = _normalize_spaces(content_map.get(label, ""))
        lines = [ln.strip() for ln in (content or "").split("\n") if ln.strip()]
        if not lines:
            _set_para_text(para, "")
            return
        _set_para_text(para, lines[0])
        prev = para
        for line in lines[1:]:
            new_para = _copy_para_after(prev)
            _set_para_text(new_para, line)
            prev = new_para
        return

    # ── 混合文本占位符 ──
    new_text = text
    for label in set(PLACEHOLDER_RE.findall(text)):
        key = label.strip()
        repl = _normalize_spaces(content_map.get(key, ""))
        # 联系方式按上下文拆分：电话：{{联系方式}} 只填电话，邮箱：{{联系方式}} 只填邮箱
        if key == "联系方式":
            if re.search(r"电话|手机|Tel|Phone", text, re.IGNORECASE) and content_map.get("电话"):
                repl = content_map["电话"]
            elif re.search(r"邮箱|Email|E-mail|Mail|邮件", text, re.IGNORECASE) and content_map.get("邮箱"):
                repl = content_map["邮箱"]
        new_text = new_text.replace("{{" + label + "}}", repl)
    # 文本框内"标签：值"单行放不下时自适应（缩字号/去标签）
    new_text = _fit_textbox_inline(para, new_text)
    _set_para_text_multiline(para, new_text)


def fill_template(
    content_map: Dict[str, str],
    template_path: Union[str, Path],
    out_path: Union[str, Path],
    photo_path: Union[str, Path, None] = None,
    primary_color: Union[str, None] = None,
    preserve_layout: bool = False,
) -> dict:
    """将 content_map（{占位符标签: 内容}）填入模板，保留模板排版。

    返回排版统计信息（含输出路径）。所有含 {{}} 的段落（含表格/文本框内）都会被处理。
    """
    doc = Document(str(template_path))
    # 先删除 pdf2docx 产生的重复副本（此时占位符仍在，可按标签识别）
    removed_fallback = _remove_fallback_duplicates(doc)
    # 全区域清空模板示例内容（保留标题/装饰/占位符），杜绝旧数据残留
    clear_stats = _clear_template_examples(doc)
    textbox_based = len(doc.element.findall(".//" + qn("w:txbxContent"))) > 0
    # 硬编码基本信息字段行（无占位符）用用户数据回填
    field_filled = _fill_mapped_fields_from_map(doc, content_map) if textbox_based else 0
    # 占位符框内旧示例段落清理（{{个人优势}} 同框的模板旧内容）
    mixed_cleaned = _clean_mixed_boxes(doc) if textbox_based else 0
    # 模板示例姓名（某某某等）替换为用户真实姓名
    name_replaced = _replace_example_name(doc, content_map.get("姓名") or "")
    # 标题框与内容框分离的板块：内容重定向到板块自己的空内容框
    mapping_before = section_mapper.detect_mapping(doc) if textbox_based else None
    tx_before = doc.element.findall(".//" + qn("w:txbxContent"))
    redirects = (_redirect_sections(mapping_before, content_map, tx_before)
                 if mapping_before else {})
    # 固化段落列表，避免复制插入的段落被重复遍历
    para_elems = [p for p in doc.element.iter(qn("w:p"))]
    filled_labels: set = set()
    for p_elem in para_elems:
        para = Paragraph(p_elem, doc)
        text = para.text or ""
        if not PLACEHOLDER_RE.search(text):
            continue
        # 文本框模板：正文中的占位符段落只清文字（保留锚点），避免与文本框内容重复；
        # 表格单元格内的占位符是真实内容区，必须正常填充
        if textbox_based and not _is_in_textbox(p_elem) and not _is_in_table(p_elem):
            _set_para_text(para, "")
            continue
        labels = {m.group(1).strip() for m in PLACEHOLDER_RE.finditer(text)}
        is_whole = bool(PLACEHOLDER_RE.fullmatch(text.strip()))
        # 重定向板块：内容将填入板块自己的内容框，这里清空占位符段避免重复
        if is_whole and labels and labels <= set(redirects.keys()):
            _set_para_text(para, "")
            continue
        # 同一字段只填充一次：仅对“整段占位符”的重复副本清空（防内容重复/重叠）；
        # 混合文本（如 电话：{{联系方式}}）属于不同展示位，正常填充
        if is_whole and labels and labels <= filled_labels:
            _set_para_text(para, "")
            continue
        _apply_replacements(para, content_map, photo_path)
        filled_labels |= labels

    # 重定向板块：把内容填入板块自己的空内容框（如模板1的自我评价）
    if redirects:
        tx_now = doc.element.findall(".//" + qn("w:txbxContent"))
        for label, sec in redirects.items():
            data = _normalize_spaces(content_map.get(label, "")).strip()
            if not data or not sec["boxes"]:
                continue
            # Choice/Fallback 双框同位置：全部填入，保证任意渲染器都可见
            for box_idx in sec["boxes"]:
                if 0 <= box_idx < len(tx_now) and not _box_has_text(tx_now[box_idx]):
                    _fill_section_box(doc, tx_now[box_idx], data)
    stats = normalize_docx(doc, photo_path, primary_color, preserve_layout=preserve_layout)
    stats["removed_fallback"] = removed_fallback
    stats["clear"] = clear_stats
    stats["field_filled"] = field_filled
    stats["mixed_cleaned"] = mixed_cleaned
    stats["name_replaced"] = name_replaced
    stats["collapsed_boxes"] = _collapse_empty_boxes(doc)
    doc.save(str(out_path))

    # 流式模板（无文本框）：统一压缩到单页（字号/边距按内容量自动适配）
    if not stats["textbox_based"]:
        from . import editor
        editor.fit_to_one_page(str(out_path))
    stats["path"] = str(out_path)
    return stats


def _box_paragraphs(box_elem, doc):
    """返回文本框内段落列表（含空段落，供按索引定位）。"""
    paras = []
    for p in box_elem.iter(qn("w:p")):
        paras.append(Paragraph(p, doc))
    return paras


def _fill_section_box(doc, box_elem, data: str) -> None:
    """整框替换板块内容：有数据按行填充（复制首段样式），无数据清空内容框。"""
    paras = _box_paragraphs(box_elem, doc)
    lines = [_normalize_spaces(ln).strip() for ln in (data or "").split("\n") if ln.strip()]
    if not lines:
        for para in paras:
            _set_para_text(para, "")
        return
    if not paras:
        return
    _set_para_text(paras[0], lines[0])
    prev = paras[0]
    for line in lines[1:]:
        new_para = _copy_para_after(prev)
        _set_para_text(new_para, line)
        prev = new_para
    # 清理首段之后的原多余段落（防残留模板示例文字）
    for para in paras[1:]:
        if id(para) == id(prev):
            continue
        parent = para._p.getparent()
        if parent is not None:
            parent.remove(para._p)


def _fill_field_line(doc, box_elem, para_idx: int, label: str, value: str) -> None:
    """按行号填充基础字段行：保留原标签，值留空时仅保留标签。"""
    target_para = None
    local_idx = None
    line_no = 0
    for p in box_elem.iter(qn("w:p")):
        lines = section_mapper._para_lines(p)
        for li, _t in enumerate(lines):
            if line_no == para_idx:
                target_para = Paragraph(p, doc)
                local_idx = li
                break
            line_no += 1
        if target_para is not None:
            break
    if target_para is None:
        return
    lines = section_mapper._para_lines(target_para._p)
    lines[local_idx] = label + value
    _set_para_lines(target_para, lines)


def _clear_template_examples(doc) -> dict:
    """填充前置：全区域清空模板自带示例内容（保留板块标题/装饰/占位符）。

    1. 无占位符的板块内容框 → 整框清空（模板示例教育/工作/技能/自评等）；
    2. 无占位符的「标签：值」行（民族：汉族、出生日期：1994 等）→ 保留标签、清空值。
    占位符行（含 {{}}）跳过，交由占位符替换逻辑填充。
    """
    from . import section_mapper
    stats = {"cleared_boxes": 0, "blanked_lines": 0}
    mapping = section_mapper.detect_mapping(doc)
    tx = doc.element.findall(".//" + qn("w:txbxContent"))

    # 1) 无占位符的板块内容框 → 整框清空
    for sec in mapping["sections"]:
        for box_idx in sec["boxes"]:
            if box_idx >= len(tx):
                continue
            elem = tx[box_idx]
            has_ph = any("{{" in (c.text or "") for c in elem.iter(qn("w:t")))
            if has_ph:
                continue
            for p in elem.iter(qn("w:p")):
                para = Paragraph(p, doc)
                if (para.text or "").strip():
                    _set_para_text(para, "")
                    stats["cleared_boxes"] += 1

    # 2) 「标签：值」示例对 → 保留标签、清空值（含占位符的对不受影响）
    for elem in tx:
        by_para = {}
        for p in elem.iter(qn("w:p")):
            lines = section_mapper._para_lines(p)
            for li, t in enumerate(lines):
                if not t.strip():
                    continue
                new_text = _blank_example_pairs(t)
                if new_text != t:
                    by_para.setdefault(p, {})[li] = new_text
        for p, repl in by_para.items():
            lines = section_mapper._para_lines(p)
            for li, new_text in repl.items():
                lines[li] = new_text
                stats["blanked_lines"] += 1
            _set_para_lines(Paragraph(p, doc), lines)
    return stats


def _blank_example_pairs(text: str) -> str:
    """把文本中不含 {{}} 的「标签：值」对的值清空（保留标签与占位符对）。"""
    if "：" not in text and ":" not in text:
        return text
    out = []
    last = 0
    for m in _PAIR_SPLIT_RE.finditer(text):
        value = m.group(2)
        if "{{" in value:
            continue
        out.append(text[last:m.start(2)])
        last = m.end(2)
    out.append(text[last:])
    return "".join(out)


def _clean_mixed_boxes(doc) -> int:
    """占位符框内清理：清掉与占位符同框的旧示例段落（非占位符、非字段行、
    非板块标题、非短装饰），避免「{{个人优势}} + 模板示例经历」混排残留。"""
    from . import standard_keys
    tx = doc.element.findall(".//" + qn("w:txbxContent"))
    removed = 0
    for elem in tx:
        has_ph = any("{{" in (c.text or "") for c in elem.iter(qn("w:t")))
        if not has_ph:
            continue
        for p in elem.iter(qn("w:p")):
            para = Paragraph(p, doc)
            t = (para.text or "").strip()
            if not t or "{{" in t:
                continue
            if section_mapper._FIELD_LINE_RE.match(t):
                continue
            if standard_keys.find_section_key(t):
                continue
            if len(t) <= 12 and "：" not in t and not any(ch.isdigit() for ch in t):
                continue
            _set_para_text(para, "")
            removed += 1
    return removed


def _box_has_text(elem) -> bool:
    """文本框是否含任何文字（含占位符）。"""
    return any((c.text or "").strip() for c in elem.iter(qn("w:t")))


def _collapse_empty_boxes(doc, min_h_emu: int = 120000) -> int:
    """把无文字文本框高度塌缩到最小（消模板示例清空后的大块空白），不改位置。"""
    collapsed = 0
    for elem in doc.element.findall(".//" + qn("w:txbxContent")):
        if _box_has_text(elem):
            continue
        cur = elem
        while cur is not None:
            if cur.tag.split("}")[-1] == "anchor":
                ext = cur.find(qn("wp:extent"))
                if ext is not None and ext.get("cy"):
                    ext.set("cy", str(min_h_emu))
                for aext in cur.findall(".//" + qn("a:ext")):
                    if aext.get("cy"):
                        aext.set("cy", str(min_h_emu))
                collapsed += 1
                break
            cur = cur.getparent()
        # VML 文本框（无 wp:anchor 定位）：仅压扁「当前 w:txbxContent 所在」v:shape 高度，
        # 严禁改同 pict 容器内其他 v:shape（避免误杀装饰元素，如模块标题旁的双竖条）。
        if not _box_has_text(elem):
            # 1) 沿 elem 向上找到包含它的最近 v:shape
            target_shape = None
            ancestor = elem.getparent()
            while ancestor is not None:
                if ancestor.tag.split("}")[-1] == "shape":
                    target_shape = ancestor
                    break
                ancestor = ancestor.getparent()
            # 2) 找到 pict 容器，只压扁 target_shape 这一个
            cur = elem
            while cur is not None:
                if cur.tag.split("}")[-1] == "pict":
                    if target_shape is not None:
                        style = target_shape.get("style") or ""
                        new_style = re.sub(r"height:\s*[\d.]+(pt|px)", "height:1pt", style)
                        if new_style != style:
                            target_shape.set("style", new_style)
                            collapsed += 1
                    break
                cur = cur.getparent()
    return collapsed


def _redirect_sections(mapping: dict, content_map: Dict[str, str], tx) -> dict:
    """找出「标题框与内容框分离」的板块：板块自己的内容框为空（无占位符），
    而该板块的占位符内容被放在了其他框里 → 需要重定向到板块自己的框。
    返回 {占位符标签: section}。"""
    from . import standard_keys
    reverse = {}
    for key, aliases in standard_keys.SECTION_ALIASES.items():
        for a in aliases:
            if a in content_map:
                reverse.setdefault(key, a)
    result = {}
    for sec in mapping["sections"]:
        if sec["key"] not in reverse:
            continue
        boxes_ok = [bi for bi in sec["boxes"] if 0 <= bi < len(tx)]
        if not boxes_ok:
            continue
        # 板块自己的框里若已有该板块占位符承载内容 → 不重定向
        own_aliases = standard_keys.SECTION_ALIASES.get(sec["key"], [])
        has_own_ph = False
        for bi in boxes_ok:
            for c in tx[bi].iter(qn("w:t")):
                for m in PLACEHOLDER_RE.finditer(c.text or ""):
                    if m.group(1).strip() in own_aliases:
                        has_own_ph = True
        if has_own_ph:
            continue
        # 至少一个空内容框可承载
        if any(not _box_has_text(tx[bi]) for bi in boxes_ok):
            result[reverse[sec["key"]]] = sec
    return result


# 标准字段 key → content_map 候选标签（取第一个非空）
FIELD_KEY_LABELS = {
    "name": ["姓名"], "age": ["年龄"], "education_degree": ["学历"],
    "phone": ["电话", "手机号", "手机"], "email": ["邮箱"],
    "wechat": ["微信"], "address": ["地址", "现居地址", "详细地址"],
    "intention_job": ["求职意向"], "city": ["所在地", "城市", "现居"],
    "political_status": ["政治面貌"], "gender": ["性别"], "nation": ["民族"],
    "birth_date": ["出生年月", "出生日期"], "hometown": ["籍贯"],
    "height": ["身高"], "major": ["专业"], "salary": ["期望薪资"],
    "arrive_time": ["到岗时间"], "gpa": ["GPA", "绩点"],
    "hobby": ["兴趣爱好", "爱好"],
    "school": ["学校", "毕业院校"],
}


def _fill_mapped_fields_from_map(doc, content_map: Dict[str, str]) -> int:
    """占位符路径补充：把硬编码基本信息字段行（标签：值，无占位符）用用户数据回填。
    与映射路径共用字段识别逻辑，保证任意模板的基本信息都能填入用户数据。"""
    mapping = section_mapper.detect_mapping(doc)
    tx = doc.element.findall(".//" + qn("w:txbxContent"))
    filled = 0
    for f in mapping["fields"]:
        value = ""
        for label in FIELD_KEY_LABELS.get(f["key"], []):
            v = content_map.get(label)
            if v:
                value = v
                break
        if not value:
            continue
        if 0 <= f["box"] < len(tx):
            _fill_field_line(doc, tx[f["box"]], f["line"], f["label"],
                             _normalize_spaces(value))
            filled += 1
    return filled


# 模板常见示例姓名（整段为纯姓名时替换为用户真实姓名）
_EXAMPLE_NAME_PAT = re.compile(r"^(某某{1,6}|张三|李四|王五|赵宇明|林晓恩|刘璇凯|关月兰|余涵)$")


def _replace_example_name(doc, name: str) -> int:
    """把模板示例姓名（某某某/张三/赵宇明等纯姓名段）替换为用户真实姓名。"""
    if not name:
        return 0
    replaced = 0
    for p in doc.element.iter(qn("w:p")):
        para = Paragraph(p, doc)
        t = (para.text or "").strip()
        if t and _EXAMPLE_NAME_PAT.match(t):
            _set_para_text(para, name)
            replaced += 1
    return replaced


def fill_mapped_template(
    content_map: Dict[str, str],
    template_path: Union[str, Path],
    out_path: Union[str, Path],
    photo_path: Union[str, Path, None] = None,
    primary_color: Union[str, None] = None,
    merge_mode: str = "merge",
    bindings: dict = None,
    preserve_layout: bool = False,
) -> dict:
    """标准 key 映射填充：适用于无 {{占位符}} 的文本框模板。

    - 板块：按映射填充内容，无数据则内容框留白、标题框保留；
    - 基础字段行：有数据填值，无数据仅保留标签；
    - 合并策略（merge）：模板无校园/荣誉独立板块时，校园经历追加到工作履历末尾、
      证书荣誉追加到技能末尾；pure 模式不追加。
    """
    doc = Document(str(template_path))
    removed_fallback = _remove_fallback_duplicates(doc)
    # 全区域清空模板示例内容（保留标题/装饰），再按映射写入用户数据
    clear_stats = _clear_template_examples(doc)
    mapping = section_mapper.detect_mapping(doc, bindings)
    tx = doc.element.findall(".//" + qn("w:txbxContent"))

    section_keys = {s["key"] for s in mapping["sections"]}
    # 1) 大板块内容填充（含合并策略）
    for sec in mapping["sections"]:
        data = str(content_map.get(sec["key"], "") or "").strip()
        if sec["key"] == "work_history" and "campus_exp" not in section_keys:
            campus = str(content_map.get("campus_exp", "") or "").strip()
            if merge_mode == "merge" and campus:
                data = (data + "\n\n" + campus).strip()
        elif sec["key"] == "skill_info" and "honor_cert" not in section_keys:
            honor = str(content_map.get("honor_cert", "") or "").strip()
            if merge_mode == "merge" and honor:
                data = (data + "\n\n" + honor).strip()
        # 主内容框（离标题最近）填内容，其余内容框清空，避免重复
        for pos, box_idx in enumerate(sec["boxes"]):
            if 0 <= box_idx < len(tx):
                _fill_section_box(doc, tx[box_idx], data if pos == 0 else "")

    # 2) 基础字段行填充
    for f in mapping["fields"]:
        if 0 <= f["box"] < len(tx):
            _fill_field_line(doc, tx[f["box"]], f["line"], f["label"],
                             str(content_map.get(f["key"], "") or "").strip())

    stats = normalize_docx(doc, photo_path, primary_color, preserve_layout=preserve_layout)
    stats["removed_fallback"] = removed_fallback
    stats["clear"] = clear_stats
    stats["mapped"] = True
    stats["mapped_sections"] = [s["key"] for s in mapping["sections"]]
    stats["mapped_fields"] = [f["key"] for f in mapping["fields"]]
    stats["collapsed_boxes"] = _collapse_empty_boxes(doc)
    stats["path"] = str(out_path)
    doc.save(str(out_path))
    return stats


def verify_fill(docx_path: Union[str, Path], expect: Dict[str, str] = None) -> List[str]:
    """输出自检（方案第六节4条校验的自动版）：
    - 无残留 {{占位符}}；
    - 模板具备且用户提供的固定信息（姓名/电话等）应出现在输出中；
    返回警告列表，供前端提示。"""
    warnings = []
    doc = Document(str(docx_path))
    alltext = []
    for p in doc.element.iter(qn("w:p")):
        parts = []
        for child in p.iter():
            tag = child.tag.split("}")[-1]
            if tag == "t":
                parts.append(child.text or "")
            elif tag == "br":
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            alltext.append(line)
    full = "\n".join(alltext)
    if "{{" in full:
        warnings.append("检测到未替换的占位符，模板可能未被完全填充")
    if expect:
        for label, value in expect.items():
            if value and value not in full:
                warnings.append(f"{label}（{value[:20]}）未出现在结果中，请检查模板是否有对应字段")
    return warnings
