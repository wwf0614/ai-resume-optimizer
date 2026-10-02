# -*- coding: utf-8 -*-
"""文本框模板自适应重排引擎。

pdf2docx 类模板的排版单元是「wpg 组」：组内包含标题文本框 + 内容文本框，
组整体通过 wp:anchor 锚定在页面（positionV relativeFrom=page）。
内容长短变化时组高度不变、后续组位置固定，导致间距过大或内容重叠。

本模块在内容填充完成后：
1. 按内容估算每个组需要的高度；
2. 调整组内内容文本框高度与组总高度；
3. 按“前一组底部 + 设计间距”重排后续组的页面位置；
4. 内容总高超出单页时自动缩小内容字号；
5. 替换/移除模板内置示例照片。
"""
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

EMU_PER_PT = 12700.0
# 内容文本框在组内的渲染顶部偏移（组顶 -> 实际文字起点），作为高度估算安全余量
CONTENT_TOP_OFFSET = 28.0


def _emu_to_pt(v) -> float:
    try:
        return int(v) / EMU_PER_PT
    except (TypeError, ValueError):
        return 0.0


def _pt_to_emu(v: float) -> int:
    return int(round(v * EMU_PER_PT))


def _para_font_size(para) -> float:
    for run in para.runs:
        rPr = run._r.find(qn("w:rPr"))
        if rPr is not None:
            sz = rPr.find(qn("w:sz"))
            if sz is not None and sz.get(qn("w:val")):
                return int(sz.get(qn("w:val"))) / 2.0
    return 10.5


def _estimate_height(texts: List[str], font_size: float, usable_w_pt: float) -> float:
    """估算文本框内容高度（pt）：中文≈1em，半角≈0.62em，行高≈1.3 倍字号。"""
    total = 0.0
    for t in texts:
        t = (t or "").strip()
        if not t:
            total += 6.0
            continue
        width = sum((font_size if ord(ch) > 0x2E80 else font_size * 0.62) for ch in t)
        lines = max(1, int(math.ceil(width / max(usable_w_pt, 40.0))))
        total += lines * font_size * 1.75
        total += 2.0
    return total + 6.0


class BoxUnit:
    """一个 wpg 组：包含 anchor、组内所有形状的几何信息与内容文本。"""

    def __init__(self, anchor, doc):
        self.anchor = anchor
        self.doc = doc
        self.top = _emu_to_pt(self._pos_offset("positionV"))
        self.x = _emu_to_pt(self._pos_offset("positionH"))
        self.w = _emu_to_pt(self._extent_cx())
        self.orig_h = _emu_to_pt(self._extent_cy())
        self.content_wsp = None      # 内容文本框（含占位符/内容最长）
        self.heading_wsp = None      # 标题文本框
        self.other_bottom = 0.0      # 组内非文本框形状的最大底部
        self.new_h = self.orig_h
        self._scan()

    def _pos_offset(self, name) -> Optional[str]:
        node = self.anchor.find(qn(f"wp:{name}"))
        if node is None:
            return None
        e = node.find(qn("wp:posOffset"))
        return e.text if e is not None else None

    def _extent_cy(self) -> Optional[str]:
        ext = self.anchor.find(qn("wp:extent"))
        return ext.get("cy") if ext is not None else None

    def _extent_cx(self) -> Optional[str]:
        ext = self.anchor.find(qn("wp:extent"))
        return ext.get("cx") if ext is not None else None

    def _scan(self):
        for wsp in self.anchor.iter(f"{{{WPS_NS}}}wsp"):
            xfrm = wsp.find(f".//{{{A_NS}}}xfrm")
            if xfrm is None:
                continue
            off = xfrm.find(f"{{{A_NS}}}off")
            ext = xfrm.find(f"{{{A_NS}}}ext")
            if off is None or ext is None:
                continue
            oy = _emu_to_pt(off.get("y"))
            h = _emu_to_pt(ext.get("cy"))
            w = _emu_to_pt(ext.get("cx"))
            txbox = wsp.get(f"{{{WPS_NS}}}txBox") == "1" or wsp.find(f"{{{WPS_NS}}}txbx") is not None
            if not txbox:
                self.other_bottom = max(self.other_bottom, oy + h)
                continue
            texts = self._wsp_texts(wsp)
            has_ph = any(PLACEHOLDER_RE.search(t) for t in texts)
            score = 0
            if has_ph:
                score = 100
            score += sum(len(t) for t in texts)
            info = {
                "wsp": wsp, "oy": oy, "h": h, "w": w,
                "texts": texts, "font": self._wsp_font(wsp),
                "score": score,
            }
            if self.content_wsp is None or score > self.content_wsp["score"]:
                if self.content_wsp is not None:
                    self.heading_wsp = self.content_wsp
                self.content_wsp = info
            elif self.heading_wsp is None or score > self.heading_wsp["score"]:
                self.heading_wsp = info

    def _wsp_texts(self, wsp) -> List[str]:
        out = []
        for p in wsp.iter(qn("w:p")):
            para = Paragraph(p, self.doc)
            if para.text and para.text.strip():
                out.append(para.text.strip())
        return out

    def _wsp_font(self, wsp) -> float:
        for p in wsp.iter(qn("w:p")):
            para = Paragraph(p, self.doc)
            fs = _para_font_size(para)
            if fs:
                return fs
        return 10.5

    @property
    def content(self):
        return self.content_wsp or {"texts": [], "oy": 0.0, "h": 0.0, "w": 0.0, "font": 10.5}

    def content_height(self) -> float:
        c = self.content
        texts = [t for t in c["texts"]]
        usable_w = max(c["w"] - 22.0, 40.0)  # 左右内边距各约11pt
        return _estimate_height(texts, c["font"], usable_w)

    def set_content_height(self, h_pt: float):
        """设置内容文本框高度（保留其组内纵向位置）。"""
        if not self.content_wsp:
            return
        xfrm = self.content_wsp["wsp"].find(f".//{{{A_NS}}}xfrm")
        if xfrm is None:
            return
        # 保留内容框组内位置（移动 y 会破坏组内其他形状的几何，Word 可能拒绝打开）
        ext = xfrm.find(f"{{{A_NS}}}ext")
        if ext is not None:
            ext.set("cy", str(_pt_to_emu(h_pt)))

    def set_group_height(self, h_pt: float):
        """设置组总高度（anchor extent 与所有组级 xfrm ext）。"""
        orig_emu = int(self.orig_h * EMU_PER_PT)
        new_emu = _pt_to_emu(h_pt)
        ext = self.anchor.find(qn("wp:extent"))
        if ext is not None:
            ext.set("cy", str(new_emu))
        for xfrm in self.anchor.iter(f"{{{A_NS}}}xfrm"):
            off = xfrm.find(f"{{{A_NS}}}off")
            e2 = xfrm.find(f"{{{A_NS}}}ext")
            if e2 is None or off is None:
                continue
            if int(off.get("y", 0)) == 0 and int(e2.get("cy", 0)) == orig_emu:
                e2.set("cy", str(new_emu))
        for ch in self.anchor.iter(f"{{{A_NS}}}chExt"):
            if int(ch.get("cy", 0)) == orig_emu:
                ch.set("cy", str(new_emu))

    def move_by(self, delta_pt: float):
        node = self.anchor.find(qn("wp:positionV"))
        if node is None:
            return
        e = node.find(qn("wp:posOffset"))
        if e is None or not e.text:
            return
        new_emu = int(e.text) + _pt_to_emu(delta_pt)
        e.text = str(new_emu)
        self.top = new_emu / EMU_PER_PT


def _collect_units(doc) -> List[BoxUnit]:
    seen = set()
    units = []
    for txbx in doc.element.findall(".//" + qn("w:txbxContent")):
        cur = txbx
        while cur is not None and cur.tag.split("}")[-1] != "anchor":
            cur = cur.getparent()
        if cur is None or cur in seen:
            continue
        seen.add(cur)
        # 跳过 Fallback 副本
        c = cur
        in_fallback = False
        while c is not None:
            if c.tag.split("}")[-1] == "Fallback":
                in_fallback = True
                break
            c = c.getparent()
        if in_fallback:
            continue
        unit = BoxUnit(cur, doc)
        if unit.content_wsp is not None:
            units.append(unit)
    return units


def _set_content_font_size(unit: BoxUnit, size_pt: float):
    """统一设置内容文本框内所有 run 的字号。"""
    if not unit.content_wsp:
        return
    half = str(int(round(size_pt * 2)))
    for p in unit.content_wsp["wsp"].iter(qn("w:p")):
        para = Paragraph(p, unit.doc)
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
    unit.content_wsp["font"] = size_pt


def _apply_heading_style(unit: BoxUnit, primary_color: Optional[str], size_pt: float) -> None:
    """按字体层级规范美化模块标题：H2（加粗、主题色、字号联动）。"""
    heading = unit.heading_wsp
    if not heading:
        return
    color = (primary_color or "#5B5CFF").lstrip("#")
    try:
        rgb = RGBColor.from_string(color)
    except ValueError:
        rgb = None
    for p in heading["wsp"].iter(qn("w:p")):
        para = Paragraph(p, unit.doc)
        for run in para.runs:
            run.font.bold = True
            run.font.size = Pt(size_pt)
            if rgb is not None:
                run.font.color.rgb = rgb


def _total_chars(units: List[BoxUnit]) -> int:
    return sum(sum(len(t) for t in u.content["texts"]) for u in units)


def _is_decorative(unit: BoxUnit, page_w_pt: float) -> bool:
    """装饰性文本框：完全在页面外，或仅含符号无文字内容。"""
    if unit.x + unit.w < 0 or unit.x > page_w_pt:
        return True
    joined = " ".join(unit.content["texts"])
    if joined and not re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", joined):
        return True
    return False


def _reflow_group(units: List[BoxUnit], page_h_pt: float, gap_pt: float) -> None:
    """保守排版：只调整内容文本框高度适配文字，必要时缩小字号。

    不做组高/锚点范围/位置的修改——部分 pdf2docx 模板的文本框在组内有
    大偏移（oy >> 组高），改组高会让 Word 判定文档损坏。
    """
    if not units:
        return
    units.sort(key=lambda u: u.top)
    usable_h = 842.0  # 底部安全线统一为 A4 页高 842pt

    def fit():
        """按原位置估算底部位置，内容框高度贴合文字。"""
        bottom = 0.0
        for u in units:
            content_h = u.content_height()
            content_box_h = max(content_h, 12.0)
            u.set_content_height(content_box_h)
            # 底部估算：内容框位于组内（oy 偏移后的底部）
            u.new_h = max(u.content.get("oy", 0) + content_box_h, u.other_bottom, u.orig_h)
            bottom = max(bottom, u.top + u.new_h)
        return bottom

    bottom = fit()
    if bottom <= usable_h:
        return
    # 超出：统一压缩字号（保持原位置）
    for step in range(8):
        if bottom <= usable_h:
            break
        shrunk = False
        for u in units:
            fs = u.content["font"]
            if fs > 7.5:
                _set_content_font_size(u, fs - 0.5)
                shrunk = True
        if not shrunk:
            break
        bottom = fit()


def reflow_textboxes(doc, page_h_pt: float = 793.0,
                     primary_color: Optional[str] = None) -> Dict[str, object]:
    """对文本框模板做纵向重排（支持单列/双栏/多页），返回统计信息。"""
    page_w = doc.sections[0].page_width / EMU_PER_PT if doc.sections else 595.0
    all_units = _collect_units(doc)
    units = [u for u in all_units if not _is_decorative(u, page_w)]
    if not units:
        return {"units": len(all_units), "reflowed": False, "decorative_skipped": len(all_units) - len(units)}

    # 内容量 -> 间距/标题字号档位（内容越少间距越大，版面饱满）
    total = _total_chars(units)
    if total <= 800:
        gap_pt, h2_size = 18.0, 13.5
    elif total <= 1200:
        gap_pt, h2_size = 14.0, 13.0
    else:
        gap_pt, h2_size = 11.0, 12.5

    # 按 x 区间重叠分列（左右分栏模板）
    units_sorted = sorted(units, key=lambda u: (u.x, u.top))
    columns = []
    cur_col = [units_sorted[0]]
    col_x1 = units_sorted[0].x + units_sorted[0].w
    for u in units_sorted[1:]:
        if u.x > col_x1 + 5.0:
            columns.append(cur_col)
            cur_col = [u]
            col_x1 = u.x + u.w
        else:
            cur_col.append(u)
            col_x1 = max(col_x1, u.x + u.w)
    columns.append(cur_col)

    # 一页优先：每列整体重排并压缩到单页
    count = 0
    for col in columns:
        _reflow_group(col, page_h_pt, gap_pt)
        for u in col:
            _apply_heading_style(u, primary_color, h2_size)
        count += len(col)

    return {"units": count, "reflowed": True, "columns": len(columns),
            "total_chars": total, "gap_pt": gap_pt,
            "decorative_skipped": len(all_units) - len(units)}


def tighten_gaps(doc, max_gap_pt: float = 100.0, keep_gap_pt: float = 45.0) -> int:
    """保真模式辅助：只消除「异常大空白」（> max_gap_pt），把大空白下方的
    全部文本框垂直上移，保持原有相对顺序与间距；不改宽度/字号/分栏。
    仅处理有 wp:anchor 定位且含文字的框。"""
    units = []
    for anchor in doc.element.findall(".//" + qn("wp:anchor")):
        posv = anchor.find(qn("wp:positionV"))
        if posv is None:
            continue
        off = posv.find(qn("wp:posOffset"))
        ext = anchor.find(qn("wp:extent"))
        if off is None or ext is None:
            continue
        try:
            v = int(off.text)
            h = int(ext.get("cy"))
        except (TypeError, ValueError):
            continue
        has_text = any((c.text or "").strip() for c in anchor.iter(qn("w:t")))
        units.append({"anchor": anchor, "off": off, "v": v, "h": h,
                      "top": _emu_to_pt(v), "has_text": has_text})
    active = [u for u in units if u["has_text"]]
    active.sort(key=lambda u: u["v"])
    if not active:
        return 0
    shift = 0.0
    prev_bottom = None
    moved = 0
    for u in active:
        top = u["top"] - shift
        if prev_bottom is not None:
            gap = top - prev_bottom
            if gap > max_gap_pt:
                shift += gap - keep_gap_pt
                top -= gap - keep_gap_pt
                moved += 1
        new_v = int(u["v"] - shift * EMU_PER_PT)
        if new_v != u["v"]:
            u["off"].text = str(new_v)
            _sync_vml_fallback(u["anchor"], _emu_to_pt(new_v))
            moved += 1
        prev_bottom = top + _emu_to_pt(u["h"])
    return moved


def _sync_vml_fallback(anchor, top_pt: float) -> None:
    """同步 AlternateContent 内 Fallback VML 文本框的 margin-top（与 Choice 锚点一致）。"""
    mc_ns = "http://schemas.openxmlformats.org/markup-compatibility/2006"
    vml_ns = "urn:schemas-microsoft-com:vml"
    cur = anchor
    while cur is not None:
        if cur.tag.split("}")[-1] == "AlternateContent":
            fallback = cur.find(f"{{{mc_ns}}}Fallback")
            if fallback is not None:
                for shp in fallback.findall(f".//{{{vml_ns}}}shape"):
                    style = shp.get("style") or ""
                    if "margin-top:" in style:
                        new_style = re.sub(
                            r"margin-top:\s*[\d.]+(pt|px)",
                            f"margin-top:{top_pt:.2f}pt", style)
                        shp.set("style", new_style)
            return
        cur = cur.getparent()


def _find_photo_anchor(doc):
    """查找模板中的示例照片锚点（竖版、尺寸接近证件照、含图片）。"""
    best = None
    best_ratio = 1.0
    for anchor in doc.element.findall(".//" + qn("wp:anchor")):
        ext = anchor.find(qn("wp:extent"))
        if ext is None:
            continue
        w = _emu_to_pt(ext.get("cx"))
        h = _emu_to_pt(ext.get("cy"))
        if w < 40 or h < 60 or w > 180 or h > 220:
            continue
        if not anchor.findall(".//" + qn("a:blip")):
            continue
        ratio = abs((h / max(w, 1.0)) - 1.33)
        if ratio < best_ratio:
            best_ratio = ratio
            best = anchor
    return best


def _crop_photo_to_3x4(data: bytes) -> bytes:
    """将证件照裁剪为 3:4 标准比例（略偏上保留头部），不变形。"""
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(data))
    w, h = img.size
    target = 3.0 / 4.0
    ratio = w / h
    if abs(ratio - target) < 0.02:
        return data
    if ratio > target:
        new_w = int(h * target)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target)
        top = int((h - new_h) * 0.35)
        img = img.crop((0, top, w, top + new_h))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _remove_photo_frame(anchor) -> int:
    """移除照片锚点内的衬底/边框矩形（保留照片本体与说明文本框）。"""
    removed = 0
    for wsp in list(anchor.iter(f"{{{WPS_NS}}}wsp")):
        if wsp.find(f"{{{WPS_NS}}}txbx") is not None:
            continue  # 文本框（说明文字）保留
        # 保留承载照片本体的 shape（含 a:blip 元素），只删除纯装饰性衬底/边框；
        # 否则某些模板（如人事经理模板）唯一照片 shape 会被整体删除，导致文档损坏
        if wsp.find(".//" + qn("a:blip")) is not None:
            continue
        parent = wsp.getparent()
        if parent is not None:
            parent.remove(wsp)
            removed += 1
    return removed


def replace_photo(doc, photo_path: Union[str, Path, None]) -> bool:
    """替换模板内置示例照片为真实证件照；无照片时用透明占位图。

    同一照片锚点内可能包含多张图（主照片 + 椭圆装饰/相框填充），
    全部替换为用户照片，保证视觉统一。
    """
    anchor = _find_photo_anchor(doc)
    if anchor is None:
        return False
    blips = anchor.findall(".//" + qn("a:blip"))
    if not blips:
        return False
    # 同一锚点内多个 blip：第一个常为形状背景/装饰填充，后续为照片本体。
    # 仅替换照片本体（最后一个 blip 通常承载真实照片），保留装饰层。
    if len(blips) > 1:
        blips = blips[-1:]

    if photo_path and Path(str(photo_path)).exists():
        try:
            data = Path(photo_path).read_bytes()
            data = _crop_photo_to_3x4(data)
            # 每个 blip 的 rId 可能相同（同一张图多次引用），去重后统一替换
            done = set()
            for blip in blips:
                rid = blip.get(qn("r:embed"))
                if not rid or rid in done:
                    continue
                done.add(rid)
                part = doc.part.related_parts[rid]
                content_type = getattr(part, "content_type", "") or ""
                blob = data
                if "jpeg" in content_type or "jpg" in content_type:
                    # 目标位 JPEG：把 PNG 转成 JPEG 再写入
                    from io import BytesIO
                    from PIL import Image
                    img = Image.open(BytesIO(blob)).convert("RGB")
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=92)
                    blob = buf.getvalue()
                part._blob = blob
            _remove_photo_frame(anchor)
            return True
        except Exception:
            return False
    else:
        # 无证件照：用空白/透明占位图替换（保持文档结构完整，避免 Word 判定文件损坏）
        try:
            from io import BytesIO
            from PIL import Image
            done = set()
            for blip in blips:
                rid = blip.get(qn("r:embed"))
                if not rid or rid in done:
                    continue
                done.add(rid)
                part = doc.part.related_parts[rid]
                content_type = getattr(part, "content_type", "") or ""
                buf = BytesIO()
                if "jpeg" in content_type or "jpg" in content_type:
                    Image.new("RGB", (10, 10), (255, 255, 255)).save(buf, format="JPEG", quality=90)
                else:
                    # 无照片：用白色占位图（透明 PNG 在 Word 转 PDF 时会渲染成深色块）
                    Image.new("RGB", (10, 10), (255, 255, 255)).save(buf, format="PNG")
                part._blob = buf.getvalue()
            _remove_photo_frame(anchor)
            return True
        except Exception:
            return False
    return False


_HEADING_PAT = re.compile(
    r"^(教育背景|工作经历|实习经历|项目经历|校园经历|专业技能|技能证书|自我评价|"
    r"个人优势|主修课程|荣誉奖励|社会经历|获奖情况|证书|语言能力|特长爱好)"
)
_ENTRY_PAT = re.compile(r"(?:^|[^\d])((19|20)\d{2})\s*[.\-~/至到年]")
_BULLET_RE = re.compile(r"^[•●◆▪·‣›»]\s*")


def normalize_typography(doc) -> Dict[str, int]:
    """文件模板填充后的全局排版归一化：
    1. 三级间距层级：标题行加大上下间距、条目头(时间+公司+岗位)保持二级间距、内容行收紧；
    2. 列表符号统一为短横线「-」；
    3. 保持模板原生布局结构（不移动文本框、不改变颜色字体）。
    仅调整间距数值与符号，不改主题。
    """
    stats = {"headings": 0, "bullets": 0}
    for tx in doc.element.findall(".//" + qn("w:txbxContent")):
        paras = list(tx.iter(qn("w:p")))
        for i, p in enumerate(paras):
            para = Paragraph(p, doc)
            text = (para.text or "").strip()
            if not text:
                continue
            pf = para.paragraph_format
            # 标题行：加大上方间距，形成模块边界
            if _HEADING_PAT.match(text):
                if pf.space_before is None or pf.space_before.pt < 6.0:
                    pf.space_before = Pt(8.0)
                if pf.space_after is None or pf.space_after.pt < 4.0:
                    pf.space_after = Pt(4.0)
                stats["headings"] += 1
                continue
            # 条目头（时间+公司+岗位）：二级间距
            if _ENTRY_PAT.search(text):
                if pf.space_before is None or pf.space_before.pt < 3.0:
                    pf.space_before = Pt(4.0)
                if pf.space_after is None or pf.space_after.pt < 2.0:
                    pf.space_after = Pt(2.0)
                continue
            # 列表项：统一符号，行距收紧（三级间距）
            m = _BULLET_RE.match(text)
            if m:
                stats["bullets"] += 1
                # 统一为短横线（保留缩进与原始 run 格式）
                first_run = para.runs[0] if para.runs else None
                if first_run is not None and first_run.text and first_run.text.startswith(("•", "●", "◆")):
                    first_run.text = "-" + first_run.text[len(m.group(0)):]
                if pf.space_after is None or pf.space_after.pt > 5.0:
                    pf.space_after = Pt(3.0)
    # 表格内单元格段落同样处理（部分模板内容在表格中）
    for tb in doc.tables:
        for row in tb.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    text = (p.text or "").strip()
                    if not text:
                        continue
                    m = _BULLET_RE.match(text)
                    if m and p.runs and p.runs[0].text.startswith(("•", "●", "◆")):
                        p.runs[0].text = "-" + p.runs[0].text[len(m.group(0)):]
                        stats["bullets"] += 1
    return stats
