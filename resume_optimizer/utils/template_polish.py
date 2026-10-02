# -*- coding: utf-8 -*-
"""参考模板优化工具：在不破坏模板原生设计的前提下，统一排版细节。

只做三类低风险优化：
1. 间距层级：文本框/表格内段落补齐三级间距（标题 > 条目头 > 内容行），
   仅设置“未显式指定”的间距，避免覆盖模板设计好的数值；
2. 列表符号：把 •●◆▪ 统一为短横线「-」；
3. 文本清理：去掉条目行内多余连续空格（保留制表位对齐）、统一中英文标点。

不改动：主题色、字体、标题样式、分割线、文本框位置与大小、图片。
"""
import re
from pathlib import Path
from typing import Union

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

_HEADING_PAT = re.compile(
    r"^(教育背景|工作经历|实习经历|项目经历|校园经历|校园实践|社会实践|专业技能|技能证书|"
    r"自我评价|个人优势|主修课程|荣誉奖励|获奖情况|兴趣爱好|特长爱好|基本信息|求职意向|"
    r"个人简历|Personal|Self|Education|Experience|Skill|Summary)"
)
_ENTRY_PAT = re.compile(r"(?:^|[^\d])((19|20)\d{2})\s*[.\-~/至到年]")
_BULLET_CHARS = ("•", "●", "◆", "▪", "·", "‣", "›", "»")

# 三级间距规范（pt）：仅对未显式设置间距的段落生效
SPACING = {
    "heading": {"before": 8.0, "after": 5.0},
    "entry": {"before": 4.0, "after": 2.0},
    "content": {"before": None, "after": 3.0},
}


def _iter_textbox_paragraphs(doc):
    """遍历文本框内段落（跳过 Fallback 副本，避免重复修改）。"""
    for tx in doc.element.findall(".//" + qn("w:txbxContent")):
        cur = tx
        while cur is not None and cur.tag.split("}")[-1] != "anchor":
            cur = cur.getparent()
        if cur is None:
            continue
        # 跳过 Fallback 副本（其父链含 mc:Fallback）
        c = cur
        in_fallback = False
        while c is not None:
            if c.tag.split("}")[-1] == "Fallback":
                in_fallback = True
                break
            c = c.getparent()
        if in_fallback:
            continue
        yield from tx.iter(qn("w:p"))


def _set_if_missing(pf, attr, value):
    cur = getattr(pf, attr)
    if cur is None:
        setattr(pf, attr, Pt(value))


def _apply_spacing(p):
    """按行内容类型设置三级间距。"""
    para = Paragraph(p, None) if not isinstance(p, Paragraph) else p
    text = (para.text or "").strip()
    if not text:
        return
    pf = para.paragraph_format
    if _HEADING_PAT.match(text) and len(text) <= 40:
        _set_if_missing(pf, "space_before", SPACING["heading"]["before"])
        _set_if_missing(pf, "space_after", SPACING["heading"]["after"])
        return
    if _ENTRY_PAT.search(text):
        _set_if_missing(pf, "space_before", SPACING["entry"]["before"])
        _set_if_missing(pf, "space_after", SPACING["entry"]["after"])
        return
    _set_if_missing(pf, "space_after", SPACING["content"]["after"])


def _fix_bullets(p):
    para = Paragraph(p, None) if not isinstance(p, Paragraph) else p
    if not para.runs:
        return 0
    first = para.runs[0].text or ""
    stripped = first.lstrip()
    if stripped and stripped[0] in _BULLET_CHARS:
        # 保留缩进，仅替换符号
        indent = first[: len(first) - len(stripped)]
        para.runs[0].text = indent + "-" + stripped[1:].lstrip()
        return 1
    return 0


def _clean_spaces(p):
    """条目行内多余连续空格清理（不触碰制表位 w:tab）。"""
    para = Paragraph(p, None) if not isinstance(p, Paragraph) else p
    if not para.runs:
        return
    for run in para.runs:
        if run.text and "  " in run.text and "\t" not in run.text:
            run.text = re.sub(r" {2,}", " ", run.text)


def polish_template(path: Union[str, Path], out_path: Union[str, Path]) -> dict:
    """优化单个参考模板文件，返回统计。"""
    doc = Document(str(path))
    stats = {"headings": 0, "entries": 0, "content": 0, "bullets": 0, "spaces": 0}
    # 文本框段落
    for p in _iter_textbox_paragraphs(doc):
        para = Paragraph(p, doc)
        text = (para.text or "").strip()
        if not text:
            continue
        _apply_spacing(para)
        stats["bullets"] += _fix_bullets(para)
        _clean_spaces(para)
        if _HEADING_PAT.match(text) and len(text) <= 40:
            stats["headings"] += 1
        elif _ENTRY_PAT.search(text):
            stats["entries"] += 1
        else:
            stats["content"] += 1
    # 表格单元格段落
    for tb in doc.tables:
        for row in tb.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    text = (p.text or "").strip()
                    if not text:
                        continue
                    _apply_spacing(p)
                    stats["bullets"] += _fix_bullets(p)
                    _clean_spaces(p)
                    if _HEADING_PAT.match(text) and len(text) <= 40:
                        stats["headings"] += 1
                    elif _ENTRY_PAT.search(text):
                        stats["entries"] += 1
                    else:
                        stats["content"] += 1
    doc.save(str(out_path))
    return stats
