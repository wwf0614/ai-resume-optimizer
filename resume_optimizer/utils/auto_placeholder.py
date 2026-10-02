# -*- coding: utf-8 -*-
"""模板自动补占位符模块。

上传的模板可能没有任何 {{占位符}}（常见于从 PDF/Word 精美模板转换而来）。
本模块通过启发式扫描模板结构（文本框 / 表格 / 正文段落），
自动识别基本信息与简历模块（教育背景、工作经历、项目经历、专业技能等）的位置，
把对应 {{占位符}} 写入模板，使系统能够把优化后的内容填进去。

规则：
- 基本信息：把示例姓名/电话/邮箱/求职意向替换为 {{姓名}}/{{电话}}/{{邮箱}}/{{求职意向}}；
- 模块区块：找到模块标题（如“教育背景”）后的内容区，整段内容替换为 {{模块名}}；
- 内容区识别：文本框模板取标题框后的下一个非空文本框；表格模板取标题行后的内容行；
- 流式段落模板取标题后的正文段落。
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

# 模块标题别名 -> 标准占位符标签
SECTION_ALIASES: List[Tuple[str, str]] = [
    (r"教育背景|教育经历|Education", "教育背景"),
    (r"工作经历|工作经验|工作履历|实习经历|相关经历|Experience", "工作经历"),
    (r"项目经历|项目经验|项目实践", "项目经历"),
    (r"专业技能|技能证书|技能特长|专业技能证书|Skills", "专业技能"),
    (r"个人优势|自我评价|个人简介|个人总结|Summary", "个人优势"),
]

# 基本信息标签 -> 占位符
BASIC_FIELDS: List[Tuple[str, str]] = [
    (r"(?:我的)?姓\s*名|Name", "姓名"),
    (r"求职意向|意向岗位|应聘岗位|目标岗位", "求职意向"),
    (r"电话|手机号码|手机|联系电话|Tel|Phone", "电话"),
    (r"邮箱|电子邮箱|Email|Mail", "邮箱"),
    (r"现居|现居地|现居地址|居住地|所在地|城市", "所在地"),
]

# 基本信息行特征：标题与值同行（如“工作经验：4 年”“电话：138…”），不是模块区块标题
_BASIC_LINE_PAT = re.compile(r"(姓名|电话|手机|邮箱|性别|生日|现居|政治面貌|工作年限|工作经验|求职意向)\s*[:：]")


def _is_basic_info_line(text: str) -> bool:
    """判断一行是否属于基本信息（标题:值 同行），而非模块区块标题。"""
    if _BASIC_LINE_PAT.search(text):
        return True
    if re.match(r"^工作经验\s*[:：]\s*\d", text):
        return True
    return False


def _para_text(p, doc) -> str:
    return (Paragraph(p, doc).text or "")


def _set_para_text(p, doc, text: str) -> None:
    """整段替换文本，保留首个 run 的格式。"""
    para = Paragraph(p, doc)
    if para.runs:
        first = para.runs[0]
        # 清空该 run 的文本节点
        for child in list(first._r):
            tag = child.tag.split("}")[-1]
            if tag in ("t", "br", "cr", "tab", "instrText"):
                first._r.remove(child)
        t_el = first._r.makeelement(qn("w:t"), {})
        t_el.set(qn("xml:space"), "preserve")
        t_el.text = text
        rPr = first._r.find(qn("w:rPr"))
        if rPr is not None:
            rPr.addnext(t_el)
        else:
            first._r.insert(0, t_el)
        for run in para.runs[1:]:
            for child in list(run._r):
                tag = child.tag.split("}")[-1]
                if tag in ("t", "br", "cr", "tab", "instrText"):
                    run._r.remove(child)
    else:
        para.add_run(text)


def _iter_textboxes(doc):
    """遍历模板中的文本框，返回 (anchor, [段落元素])，跳过 Fallback 重复副本。"""
    seen = set()
    for tx in doc.element.findall(".//" + qn("w:txbxContent")):
        # 从文本框自身向上找：若处于 mc:Fallback 分支则跳过（部分模板 Fallback 在 anchor 之下）
        c0 = tx
        in_fallback = False
        while c0 is not None:
            if c0.tag.split("}")[-1] == "Fallback":
                in_fallback = True
                break
            c0 = c0.getparent()
        if in_fallback:
            continue
        cur = tx
        while cur is not None and cur.tag.split("}")[-1] != "anchor":
            cur = cur.getparent()
        if cur is None:
            continue
        yield cur, list(tx.iter(qn("w:p")))


def _detect_sections(doc, textbox_based: bool) -> Dict[str, List[Tuple[int, object]]]:
    """扫描模板，找出各模块标题的位置及其后内容区。

    返回 {模块标签: [(标题索引, 内容区元素), ...]}，索引为扫描序列下标。
    """
    found: Dict[str, List[Tuple[int, object]]] = {}
    # ── 文本框内容识别（含文本框的模板）──
    textbox_units = []
    for anchor, paras in _iter_textboxes(doc):
        for p in paras:
            t = _para_text(p, doc).strip()
            if t:
                textbox_units.append((t, p))
    if textbox_units:
        units = []
        units = textbox_units
        content_groups = {}
        matched_idx = set()
        for i, (text, p) in enumerate(units):
            label = None
            if re.search(r"毕业院校|毕业时间|最高学历|所学专业|大学|学院|学校", text) and re.search(r"(20\d{2}|19\d{2})\s*[.\-~/至到年]", text):
                label = "教育背景"
            elif re.search(r"公司名称|起止年月|工作描述|担任职务|网络科技|科技有限公司|岗位[:：]|负责|参与|策划", text):
                label = "工作经历"
            elif re.search(r"熟悉OFFICE|熟悉Office|Microsoft Word|OFFICE软件|AUTO CAD|PHOTOSHOP", text):
                label = "专业技能"
            if label and i not in matched_idx:
                content_groups.setdefault(label, []).append(p)
                matched_idx.add(i)
        for i, (text, p) in enumerate(units):
            if i in matched_idx:
                continue
            if len(text) > 60 and not _is_basic_info_line(text):
                content_groups.setdefault("个人优势", []).append(p)
                matched_idx.add(i)
        for label, group in content_groups.items():
            found[label] = [(i, group) for i in range(len(group))]
    # ── 表格内容识别（含表格的模板，即使也有文本框）──
    if doc.tables:
        tables = doc.tables
        for ti, tb in enumerate(tables):
            if len(tb.rows) < 2:
                continue
            first_row = " | ".join(c.text.strip() for c in tb.rows[0].cells)
            if not first_row.strip() or PLACEHOLDER_RE.search(first_row):
                continue
            for pat, label in SECTION_ALIASES:
                m = re.search(pat, first_row, re.IGNORECASE)
                if m and m.start() <= 8:
                    # 标题行之后的内容行：只要不是新的模块标题行，都算内容
                    content_rows = []
                    for row in tb.rows[1:]:
                        rt = " ".join(c.text.strip() for c in row.cells if c.text.strip())
                        # 新模块标题行特征：单行文本且匹配模块别名（如“技能证书”“自我评价”）
                        is_new_header = False
                        if len(row.cells) >= 1 and rt and len(rt) <= 12:
                            if any(re.search(p2, rt, re.IGNORECASE) for p2, _ in SECTION_ALIASES):
                                is_new_header = True
                        if rt and not is_new_header:
                            content_rows.append(row)
                    if content_rows:
                        found.setdefault(label, []).append((ti, content_rows))
                    break
    return found


def _inject_basic_info(doc, textbox_based: bool) -> Dict[str, bool]:
    """把示例姓名/电话/邮箱等替换为占位符。返回 {标签: 是否成功}。"""
    injected: Dict[str, bool] = {}
    elems: List[Tuple[str, object]] = []
    if textbox_based:
        for tx in doc.element.findall(".//" + qn("w:txbxContent")):
            # 从文本框自身向上找 Fallback（部分模板 Fallback 在 anchor 之下）
            c0 = tx
            in_fb = False
            while c0 is not None:
                if c0.tag.split("}")[-1] == "Fallback":
                    in_fb = True
                    break
                c0 = c0.getparent()
            if in_fb:
                continue
            cur = tx
            while cur is not None and cur.tag.split("}")[-1] != "anchor":
                cur = cur.getparent()
            if cur is None:
                continue
            for p in tx.iter(qn("w:p")):
                t = _para_text(p, doc).strip()
                if t:
                    elems.append((t, p))
    else:
        for p in doc.element.iter(qn("w:p")):
            t = _para_text(p, doc).strip()
            if t:
                elems.append((t, p))
    # 表格单元格段落（基本信息常在表格里）
    for tb in doc.tables:
        seen_cells = set()
        for row in tb.rows:
            for cell in row.cells:
                if id(cell._tc) in seen_cells:
                    continue
                seen_cells.add(id(cell._tc))
                for p in cell.paragraphs:
                    t = _para_text(p._p, doc).strip()
                    if t:
                        elems.append((t, p._p))
    # 姓名：优先整段示例姓名（2-4 个汉字且非标签行）
    name_pat = re.compile(r"^[\u4e00-\u9fa5·]{2,4}$")
    _HEADER_WORDS = ("基本资料", "教育背景", "工作经历", "专业技能", "自我评价", "项目经历", "校园经历", "个人简历", "技能证书", "获奖荣誉", "兴趣爱好")
    for t, p in elems:
        if name_pat.match(t) and t not in _HEADER_WORDS and not any(
            k in t for k in ("姓名", "电话", "邮箱", "求职", "性别", "生日", "现居")
        ):
            if t not in injected:
                _set_para_text(p, doc, "{{姓名}}")
                injected["姓名"] = True
                break
    # 姓名 + 求职意向同行（如“某某某    求职意向：行政主管 岗位”）：替换行首姓名
    if "姓名" not in injected:
        mixed_pat = re.compile(r"^([\u4e00-\u9fa5·]{2,4})\s{2,}(求职意向|意向岗位|应聘岗位)\s*[:：]")
        for t, p in elems:
            m = mixed_pat.match(t)
            if m and not any(k in t for k in ("姓名", "电话", "邮箱", "性别", "生日")):
                label = m.group(2)
                _set_para_text(p, doc, "{{姓名}}    " + label + "：" + t[m.end():])
                injected["姓名"] = True
                break
    # 姓名：标签形式（姓名：某某某 / 姓 名：xxx / 我的姓名：xxx）
    if "姓名" not in injected:
        name_label_pat = re.compile(r"^(?:我的)?姓\s*名\s*[:：]\s*([^\s|｜]+)")
        for t, p in elems:
            m = name_label_pat.match(t)
            if m:
                _set_para_text(p, doc, t.replace(m.group(0), "姓名：" + "{{姓名}}"))
                injected["姓名"] = True
                break
    # 混合行：姓名：示例 / 电话：示例 等
    for t, p in elems:
        for pat, label in BASIC_FIELDS:
            if label == "姓名":
                continue  # 姓名已单独处理
            if label in injected:
                continue
            cur_text = _para_text(p, doc)  # 读取当前文本（前面的替换可能已修改该段）
            m = re.search(r"(%s)\s*[:：]\s*([^\s|｜]+)" % pat, cur_text, re.IGNORECASE)
            if m:
                _set_para_text(p, doc, cur_text.replace(m.group(0), m.group(1) + "：{{" + label + "}}"))
                injected[label] = True
                continue
            # 标签单独成行且值为空（如“手机：”“邮箱：”）：直接补占位符
            lm = re.match(r"^(%s)\s*[:：]\s*$" % pat, cur_text.strip(), re.IGNORECASE)
            if lm:
                _set_para_text(p, doc, lm.group(1) + "：{{" + label + "}}")
                injected[label] = True
    return injected


def _inject_section_content(doc, sections: Dict[str, List], textbox_based: bool) -> Dict[str, bool]:
    """把各模块内容区替换为 {{标签}}。"""
    injected: Dict[str, bool] = {}
    for label, hits in sections.items():
        if label in injected:
            continue
        for _, content in hits:
            if content is None:
                continue
            try:
                group = content if isinstance(content, (list, tuple)) else [content]
                rows_to_remove = []
                for gi, item in enumerate(group):
                    if hasattr(item, "cells") and hasattr(item, "_tr"):
                        # 表格行：合并单元格会重复，按唯一 tc 去重
                        seen_cells = set()
                        unique_cells = []
                        for cell in item.cells:
                            if id(cell._tc) not in seen_cells:
                                seen_cells.add(id(cell._tc))
                                unique_cells.append(cell)
                        # 首个内容行第一格放占位符，其余清空
                        for ci, cell in enumerate(unique_cells):
                            paras = cell.paragraphs
                            for pi, p in enumerate(paras):
                                if gi == 0 and ci == 0 and pi == 0:
                                    _set_para_text(p._p, doc, "{{" + label + "}}")
                                else:
                                    _set_para_text(p._p, doc, "")
                        if gi > 0:
                            rows_to_remove.append(item._tr)
                    else:
                        # 文本框段落
                        _set_para_text(item, doc, "{{" + label + "}}" if gi == 0 else "")
                for tr in rows_to_remove:
                    parent = tr.getparent()
                    if parent is not None:
                        parent.remove(tr)
                injected[label] = True
                break
            except Exception:
                continue
    return injected


def auto_inject_placeholders(docx_path: Path, out_path: Path) -> dict:
    """对模板文件自动补占位符，返回注入结果。

    result = {
        "injected": {"姓名": True, "工作经历": True, ...},
        "labels_found": [...],           # 注入后模板中的全部占位符标签
        "missing": [...],                # 仍缺失的必选标签
    }
    """
    doc = Document(str(docx_path))
    textbox_based = (len(doc.element.findall(".//" + qn("w:txbxContent"))) > 0
                     or len(doc.tables) > 0)
    sections = _detect_sections(doc, textbox_based)
    basic = _inject_basic_info(doc, textbox_based)
    section_injected = _inject_section_content(doc, sections, textbox_based)
    injected = {**basic, **section_injected}
    doc.save(str(out_path))

    labels = set()
    doc2 = Document(str(out_path))
    for pe in doc2.element.iter(qn("w:p")):
        for m in PLACEHOLDER_RE.finditer(_para_text(pe, doc2) or ""):
            labels.add(m.group(1).strip())
    required = {"姓名", "联系方式", "个人优势", "工作经历", "教育背景"}
    missing = sorted(required - labels)
    return {
        "injected": injected,
        "labels_found": sorted(labels),
        "missing": missing,
        "textbox_based": textbox_based,
    }


def detect_metadata(docx_path: Path, fallback_name: str = "") -> dict:
    """自动识别模板元数据：名称、模块清单、场景说明。

    名称优先取文档标题属性，其次取文件名；
    模块通过扫描模板内标题/内容特征识别；
    场景说明按岗位关键词与模块组合生成。
    """
    try:
        doc = Document(str(docx_path))
        title = ""
        try:
            cp = doc.core_properties
            title = (cp.title or "").strip()
        except Exception:
            pass
        textbox_based = len(doc.element.findall(".//" + qn("w:txbxContent"))) > 0
        # 收集全部文本（文本框 + 表格 + 段落）
        texts = []
        seen = set()
        for tx in doc.element.findall(".//" + qn("w:txbxContent")):
            c0 = tx
            in_fb = False
            while c0 is not None:
                if c0.tag.split("}")[-1] == "Fallback":
                    in_fb = True
                    break
                c0 = c0.getparent()
            if in_fb:
                continue
            for p in tx.iter(qn("w:p")):
                t = _para_text(p, doc).strip()
                if t:
                    texts.append(t)
        for tb in doc.tables:
            for row in tb.rows:
                for cell in row.cells:
                    t = cell.text.strip()
                    if t:
                        texts.append(t)
        for p in doc.paragraphs:
            t = (p.text or "").strip()
            if t:
                texts.append(t)
        joined = "\n".join(texts)
        # 模块识别
        modules = []
        for pat, label in SECTION_ALIASES:
            if re.search(pat, joined, re.IGNORECASE):
                modules.append(label)
        # 基本信息字段
        for pat, label in BASIC_FIELDS:
            if re.search(pat, joined, re.IGNORECASE) and label not in modules:
                modules.append(label)
        # 去重保序
        seen_m = set()
        modules = [m for m in modules if not (m in seen_m or seen_m.add(m))]
        # 名称：文档标题（需是合法中文名称，过滤水印/网址/uuid）> 文件名
        def _is_junk_title(t):
            if not t or len(t) > 30:
                return True
            if "www" in t.lower() or ".com" in t.lower() or "http" in t.lower():
                return True
            if re.fullmatch(r"[0-9a-f]{16,}", t):
                return True
            if "简历模板资源" in t or "下载" == t or "资源网" in t:
                return True
            return False

        fname = (fallback_name or Path(docx_path).name)
        fname = fname.rsplit(".", 1)[0] if "." in fname else fname
        fname_clean = (fname.replace("简历模板", "").replace("免费", "").replace("岗位求职", "")
                       .replace("_", "").strip())
        if fname_clean.endswith("简历"):
            fname_clean = fname_clean[: -len("简历")].strip()
        name = (title if not _is_junk_title(title) else "") or fname_clean or fname or "未命名模板"
        # 场景说明
        scene_parts = []
        if re.search(r"校招|应届|毕业生", joined):
            scene_parts.append("校招应届")
        if re.search(r"社招|求职|总监|经理", joined):
            scene_parts.append("社招求职")
        if re.search(r"行政|人事|文员|秘书", joined):
            scene_parts.append("行政职能")
        if re.search(r"JAVA|开发|工程师|技术|运维", joined):
            scene_parts.append("技术岗位")
        if re.search(r"造价|工程|施工|建筑", joined):
            scene_parts.append("工程岗位")
        if re.search(r"物流|仓管|运输", joined):
            scene_parts.append("物流岗位")
        scene = "、".join(scene_parts) if scene_parts else "通用求职"
        return {
            "name": name,
            "modules": modules,
            "description": f"{scene}简历模板，包含：{'、'.join(modules) if modules else '基础信息'}等模块",
        }
    except Exception:
        return {"name": Path(docx_path).stem, "modules": [], "description": "简历模板"}
