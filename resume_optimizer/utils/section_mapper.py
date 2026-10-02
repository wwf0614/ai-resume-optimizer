"""文本框模板板块识别与映射。

把「无规范占位符」的硬编码模板（如 余涵行政简历模板）按文档顺序扫描，
识别：板块标题框（工作经验/教育背景/职业技能/自我评价…）、内容框、
基础信息字段行（姓名/年龄/学历/手机/邮箱/微信/地址/求职意向…）、照片框，
输出映射关系供填充引擎使用。填充时必须对同一份去重后的文档实例进行映射+填充，
保证框下标一致。
"""
import re

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from . import standard_keys

# 字段行正则：捕获「标签（可含空格）＋分隔符」与值
_FIELD_LINE_RE = re.compile(r"^([^\s：:]+(?:\s+[^\s：:]+)*\s*[：:])\s*(.*)$")
_PHOTO_RE = re.compile(r"照片|头像|相片|photo|avatar", re.IGNORECASE)


def _para_lines(p_elem):
    """把段落按 w:br 拆成多行文本。"""
    lines = [""]
    for child in p_elem.iter():
        tag = child.tag.split("}")[-1]
        if tag == "t":
            lines[-1] += child.text or ""
        elif tag in ("br", "cr"):
            lines.append("")
    return lines


def _box_lines(elem, doc):
    """返回框内 (Paragraph, 全局行号, 行文本) 列表（过滤空白行）。"""
    out = []
    line_no = 0
    for p in elem.iter(qn("w:p")):
        para = Paragraph(p, doc)
        for text in _para_lines(p):
            t = text.strip()
            if t:
                out.append((para, line_no, t))
            line_no += 1
    return out


def _box_paras(elem, doc):
    """返回框内 Paragraph 列表（含空段落，供填充按索引定位）。"""
    return [Paragraph(p, doc) for p in elem.iter(qn("w:p"))]


def _box_pos(elem):
    """从 wp:anchor 读取文本框定位 (H, V)（EMU），取不到返回 (None, None)。"""
    cur = elem
    while cur is not None:
        if cur.tag.split("}")[-1] == "anchor":
            h = v = None
            for ph in cur.findall(qn("wp:positionH")):
                off = ph.find(qn("wp:posOffset"))
                if off is not None:
                    h = int(off.text)
            for pv in cur.findall(qn("wp:positionV")):
                off = pv.find(qn("wp:posOffset"))
                if off is not None:
                    v = int(off.text)
            return h, v
        cur = cur.getparent()
    return None, None


def _looks_decor(joined: str) -> bool:
    """判断是否为装饰性短文本（页眉/页脚/标题装饰等），避免误归板块被清空。"""
    t = (joined or "").strip()
    if not t or len(t) > 24:
        return False
    if "：" in t or ":" in t:
        return False
    if any(ch.isdigit() for ch in t):
        return False
    return True


def detect_mapping(doc: Document, bindings: dict = None) -> dict:
    """扫描文档文本框，返回映射：
    {
      "sections": [{"key", "title", "boxes": [box_idx...]}],   # 文档顺序
      "fields":   [{"key", "box", "line", "label", "value"}],   # 基础字段行
      "photo_box": int | None,
    }
    bindings（管理员手动绑定，优先级高于别名自动识别）：
      {"sections": {标题文本: 标准key}, "fields": {标签文本: 标准key}}
    """
    bindings = bindings or {}
    section_bindings = {str(k).strip(): v for k, v in (bindings.get("sections") or {}).items()}
    field_bindings = {str(k).strip(): v for k, v in (bindings.get("fields") or {}).items()}

    tx = doc.element.findall(".//" + qn("w:txbxContent"))
    boxes = []
    for i, elem in enumerate(tx):
        lines = _box_lines(elem, doc)
        joined = " | ".join(t for _, _, t in lines)
        h, v = _box_pos(elem)
        boxes.append({"index": i, "lines": lines, "joined": joined, "v": v})

    sections = []
    fields = []
    photo_box = None

    # 第一遍：识别板块标题框
    title_boxes = []
    for box in boxes:
        sec_key = (section_bindings.get(box["joined"])
                   or standard_keys.find_section_key(box["joined"]))
        if sec_key:
            sec = {"key": sec_key, "title": box["joined"], "boxes": [],
                   "v": box["v"], "doc_idx": box["index"]}
            sections.append(sec)
            title_boxes.append(sec)

    # 第二遍：照片框 / 字段行 / 内容框归属
    for box in boxes:
        if (section_bindings.get(box["joined"])
                or standard_keys.find_section_key(box["joined"])):
            continue
        joined = box["joined"]
        if photo_box is None and _PHOTO_RE.search(joined):
            photo_box = box["index"]
            continue
        hits = []
        for para, li, text in box["lines"]:
            m = _FIELD_LINE_RE.match(text)
            if not m:
                continue
            # group(1) 含标签与冒号（如「手机：」），匹配时去掉尾部冒号/空格
            label = re.sub(r"[\s：:]+$", "", m.group(1))
            fk = field_bindings.get(label) or standard_keys.find_field_key(label)
            if fk:
                hits.append({
                    "key": fk, "box": box["index"], "line": li,
                    "label": m.group(1), "value": m.group(2).strip(),
                })
        if hits:
            fields.extend(hits)
            continue
        # 内容框 → 归属垂直方向上最近的上方板块标题
        if box["v"] is not None:
            candidates = [s for s in title_boxes
                          if s["v"] is not None and s["v"] <= box["v"]]
            if candidates:
                nearest = max(candidates, key=lambda s: s["v"])
                nearest["boxes"].append(box["index"])
                continue
        # 无位置信息（VML/行内形状等）→ 按文档顺序归属最近的先前板块标题
        prev_titles = [s for s in title_boxes if s["doc_idx"] < box["index"]]
        if prev_titles and not _looks_decor(box["joined"]):
            prev_titles[-1]["boxes"].append(box["index"])

    # 内容框按离标题的垂直距离排序：第 1 个为板块主内容框
    for sec in sections:
        sv = sec["v"] or 0
        sec["boxes"].sort(key=lambda idx: abs(
            next((b["v"] for b in boxes if b["index"] == idx and b["v"] is not None), sv) - sv))

    return {"sections": sections, "fields": fields, "photo_box": photo_box}


def detect_mapping_from_file(docx_path) -> dict:
    """从模板文件检测映射（独立使用，供配置预览/后台）。"""
    doc = Document(str(docx_path))
    return detect_mapping(doc)
