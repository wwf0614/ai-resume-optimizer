# -*- coding: utf-8 -*-
"""真实模板就地编辑：解析 docx 模板的绝对定位文本框结构，
并把编辑后的文本写回对应文本框（保留原格式），支持导出。

定位信息来自 DrawingML wp:anchor（wp:extent / wp:positionH / wp:positionV），
单位 EMU → CSS px（1px = 9525 EMU）。
"""
import io
import re
import shutil
import subprocess
import sys as _sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional

from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn

WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
WPG_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
EMU_PER_PX = 9525

PLACEHOLDER_RE = re.compile(r"\{\{(.*?)\}\}")
# 表格型模板的分区标题（模块头），属于设计而非内容
SECTION_TITLE_RE = re.compile(
    r"^(个人信息|基本信息|教育(背景)?|工作(经验|经历|背景)?|实习(经验|经历)?|"
    r"项目(经验|经历)?|校园(经历|实践)?|社会实践|校内(实践)?|主修课程|"
    r"技能(证书|特长|能力)?|专业(技能|课程)?|语言(能力|水平)?|计算机(能力|技能)?|"
    r"荣誉(证书)?|获奖(情况|经历)?|证书(荣誉)?|自我(评价|介绍)?|个人(优势|简介)?|"
    r"求职(意向|目标)?|职业(目标|规划)?|兴趣(爱好|特长)?|联系方式|培训(经历)?)$")


def _emu(attr):
    try:
        return int(attr)
    except (TypeError, ValueError):
        return 0


def _find_ancestor(node, tag):
    cur = node
    while cur is not None:
        if cur.tag == tag:
            return cur
        cur = cur.getparent()
    return None


def _shape_xfrm(el):
    """取形状/分组自身属性区下的 a:xfrm（不向深层查找）。"""
    if el.tag == "{%s}wsp" % WPS_NS:
        pr = el.find("{%s}spPr" % WPS_NS)
    elif el.tag == "{%s}grpSp" % WPG_NS:
        pr = el.find("{%s}grpSpPr" % WPG_NS)
    else:
        return None
    return pr.find("{%s}xfrm" % A_NS) if pr is not None else None


def _read_xfrm(xfrm):
    off = xfrm.find("{%s}off" % A_NS)
    ext = xfrm.find("{%s}ext" % A_NS)
    choff = xfrm.find("{%s}chOff" % A_NS)
    chext = xfrm.find("{%s}chExt" % A_NS)

    def _pair(node, k1, k2):
        if node is None:
            return None
        return (_emu(node.get(k1)), _emu(node.get(k2)))

    o = _pair(off, "x", "y") or (0, 0)
    e = _pair(ext, "cx", "cy") or (0, 0)
    return {
        "off": o,
        "ext": e,
        # 缺省时子坐标系与自身坐标系一致
        "chOff": _pair(choff, "x", "y") or o,
        "chExt": _pair(chext, "cx", "cy") or e,
    }


def _box_geometry(txbx) -> Dict[str, int]:
    """提取文本框的 x/y/w/h（px）与定位基准。

    支持分组（wpg:grpSp）嵌套：文本框若在组内，其坐标处于父组的子坐标系
    （由 grpSpPr/a:xfrm 的 chOff/chExt 定义），需沿层级逐级换算到锚点
    坐标系，否则组内所有文本框都会错误地继承整组的几何信息。
    """
    # 自内向外收集：wsp（含此文本框）→ 各级嵌套 grpSp → anchor
    chain = []
    anchor = None
    cur = txbx.getparent()
    while cur is not None:
        if cur.tag == "{%s}anchor" % WP_NS:
            anchor = cur
            break
        if cur.tag in ("{%s}wsp" % WPS_NS, "{%s}grpSp" % WPG_NS):
            chain.append(cur)  # 内层在前
        cur = cur.getparent()

    rel_h = rel_v = None
    ext_cx = ext_cy = 0
    pos_x = pos_y = 0
    if anchor is not None:
        extent = anchor.find("{%s}extent" % WP_NS)
        if extent is not None:
            ext_cx = _emu(extent.get("cx"))
            ext_cy = _emu(extent.get("cy"))
        pos_h = anchor.find("{%s}positionH" % WP_NS)
        pos_v = anchor.find("{%s}positionV" % WP_NS)
        if pos_h is not None:
            rel_h = pos_h.get("relativeFrom")
            off_h = pos_h.find("{%s}posOffset" % WP_NS)
            if off_h is not None:
                pos_x = _emu(off_h.text)
        if pos_v is not None:
            rel_v = pos_v.get("relativeFrom")
            off_v = pos_v.find("{%s}posOffset" % WP_NS)
            if off_v is not None:
                pos_y = _emu(off_v.text)

    x = y = w = h = 0  # EMU
    have_geo = False
    for el in chain:
        xf = _shape_xfrm(el)
        if xf is None:
            continue
        d = _read_xfrm(xf)
        if not have_geo:
            (x, y), (w, h) = d["off"], d["ext"]
            if w or h:
                have_geo = True
            continue
        # 当前坐标处于该组的子坐标系（chOff 基准）：归一到组框原点并按比例缩放。
        # 组自身的 off 不参与——顶层对象在锚点坐标系中的位置由 posOffset 给出。
        gw, gh = d["ext"]
        cox, coy = d["chOff"]
        cw, ch = d["chExt"]
        sx = (gw / cw) if cw else 1.0
        sy = (gh / ch) if ch else 1.0
        x = (x - cox) * sx
        y = (y - coy) * sy
        w, h = w * sx, h * sy

    if not have_geo or (not w and not h):
        w, h = ext_cx, ext_cy
    # 锚点 posOffset 是对象的实际落点基准
    x += pos_x
    y += pos_y

    return {"x": round(x / EMU_PER_PX), "y": round(y / EMU_PER_PX),
            "w": round(w / EMU_PER_PX), "h": round(h / EMU_PER_PX),
            "rel_h": rel_h, "rel_v": rel_v}


def _pdf_hits(page, key):
    """按递减长度的候选键在页面上搜索文本，返回命中矩形列表。"""
    for cand in (key[:32], key[:16], key[:10]):
        cand = (cand or "").strip()
        if not cand:
            continue
        try:
            return page.search_for(cand)
        except Exception:  # noqa: BLE001
            return []
    return []


def _pdf_calibrate(pdf_path, boxes):
    """用 PDF 实际渲染位置校准盒子坐标（pt → px）。

    多个盒子首行文本相同时（如多条教育经历均以「2012-2013」开头），
    按各自 XML 几何的 y 排序与 PDF 命中按页面位置一一配对——此前简单
    取首个命中，会让同类盒子全部叠到同一位置。
    返回成功校准的盒子 id 集合。"""
    from collections import defaultdict

    try:
        import fitz
    except Exception:  # noqa: BLE001
        return set()
    scale = 96.0 / 72.0
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:  # noqa: BLE001
        return set()
    try:
        page = doc[0]
        keyed = defaultdict(list)
        for b in boxes:
            lines = [ln.strip() for ln in (b.get("text") or "").splitlines()
                     if ln.strip()]
            if lines:
                b["_key"] = lines[0]
                keyed[lines[0]].append(b)
        matched = {}
        for grp in keyed.values():
            hits = _pdf_hits(page, grp[0]["_key"])
            if not hits:
                continue
            if len(grp) == 1:
                matched[grp[0]["id"]] = hits[0]
                continue
            if len(hits) < len(grp):
                continue  # 命中不足：保留 XML 几何，避免集体叠到同一处
            ordered = sorted(grp, key=lambda b: (b["y"], b["x"]))
            placed = sorted(hits, key=lambda r: (r.y0, r.x0))
            for b, r in zip(ordered, placed):
                matched[b["id"]] = r
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass
    for i, b in enumerate(boxes):
        r = matched.get(i)
        if r is None:
            continue
        b["x"] = round(r.x0 * scale - 6)
        b["y"] = round(r.y0 * scale - 6)
        if not b["w"]:
            b["w"] = round(r.width * scale)
        if not b["h"]:
            b["h"] = round(max(r.height * scale, 20))
    return {i for i in range(len(boxes)) if i in matched}


def _convert_to_pdf_safe(docx_path, pdf_path, timeout=25):
    """独立子进程 + 超时转换（Word COM），避免卡死接口。
    在临时目录复制一份再转换，绕开原文件可能的占用/锁。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="rt_conv_"))
    work = tmp_dir / "tpl.docx"
    try:
        shutil.copyfile(docx_path, work)
        script = (
            "import sys, os, pythoncom, win32com.client\n"
            "pythoncom.CoInitialize()\n"
            "app = win32com.client.DispatchEx('Word.Application')\n"
            "app.Visible = False\n"
            "app.DisplayAlerts = False\n"
            "doc = app.Documents.Open(os.path.abspath(sys.argv[1]), ReadOnly=True)\n"
            "doc.SaveAs2(os.path.abspath(sys.argv[2]), FileFormat=17)\n"
            "doc.Close(False)\n"
            "app.Quit()\n"
        )
        subprocess.run([_sys.executable, "-c", script, str(work), str(pdf_path)],
                       capture_output=True, timeout=timeout)
        return Path(pdf_path).exists()
    except Exception:  # noqa: BLE001 超时/失败
        try:
            subprocess.run(["taskkill", "/F", "/IM", "WINWORD.EXE"],
                           capture_output=True, shell=False, timeout=8)
        except Exception:  # noqa: BLE001
            pass
        return False
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


def _run_props(run) -> Dict:
    """提取 run 的显示属性（粗体/斜体/字号/颜色/字体）。"""
    rpr = run.find(qn("w:rPr")) if run is not None else None
    props = {"bold": False, "italic": False, "size": None, "color": None, "font": None}
    if rpr is None:
        return props
    if rpr.find(qn("w:b")) is not None:
        props["bold"] = True
    if rpr.find(qn("w:i")) is not None:
        props["italic"] = True
    sz = rpr.find(qn("w:sz"))
    if sz is not None and sz.get(qn("w:val")):
        props["size"] = round(int(sz.get(qn("w:val"))) / 2, 1)
    color = rpr.find(qn("w:color"))
    if color is not None and color.get(qn("w:val")):
        props["color"] = "#" + color.get(qn("w:val"))
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is not None:
        props["font"] = fonts.get(qn("w:eastAsia")) or fonts.get(qn("w:ascii"))
    return props


def _paragraph_info(p) -> Dict:
    runs = []
    text = ""
    for r in p.iter(qn("w:r")):
        t = "".join(x.text or "" for x in r.iter(qn("w:t")))
        if not t:
            continue
        runs.append({"text": t, **(_run_props(r))})
        text += t
    return {"text": text, "runs": runs}


def _fix_degenerate_boxes(boxes, page_w, page_h):
    """兜底修正：有文字但宽/高为 0 的盒子会竖排堆字，按字号估算最小尺寸；
    坐标越出页面的钳回页面内（posOffset 异常或无锚点的模板）。"""
    for b in boxes:
        if b.get("editable") is False:
            continue
        txt = b.get("text") or ""
        first = next((ln.strip() for ln in txt.splitlines() if ln.strip()), "")
        paras = b.get("paragraphs") or []
        r0 = (paras[0]["runs"][0] if paras and paras[0].get("runs") else None) or {}
        size = max(float(r0.get("size") or 12), 9)
        if txt.strip() and not b["w"]:
            est = int(len(first) * size * 1.1) + 20
            b["w"] = max(80, min(int(page_w * 0.7), est))
        if txt.strip() and not b["h"]:
            n_lines = max(1, sum(1 for ln in txt.splitlines() if ln.strip()))
            b["h"] = max(22, min(int(page_h * 0.5), int(n_lines * size * 1.6)))
        if b["w"] > page_w:
            b["w"] = page_w
        if b["h"] > page_h:
            b["h"] = page_h
        if b["x"] < 0:
            b["x"] = 0
        if b["y"] < 0:
            b["y"] = 0
        if b["x"] + b["w"] > page_w + 8:
            b["x"] = max(0, page_w - min(b["w"], 160))
        if b["y"] + b["h"] > page_h + 8:
            b["y"] = max(0, page_h - min(b["h"], 60))


def parse_template_structure(docx_path) -> Dict:
    """解析模板为可编辑盒子列表。"""
    doc = Document(str(docx_path))
    sec = doc.sections[0]
    page_w = round(sec.page_width / EMU_PER_PX)
    page_h = round(sec.page_height / EMU_PER_PX)
    body = doc.element.body

    boxes = []
    for kind, node, cell_geo in _collect_edit_targets(body):
        paras = []
        full_text = ""
        for p in node.findall(qn("w:p")):
            info = _paragraph_info(p)
            if info["text"] or info["runs"]:
                paras.append(info)
            full_text += info["text"] + "\n"
        placeholders = PLACEHOLDER_RE.findall(full_text)
        if kind == "textbox":
            geo = _box_geometry(node)
            boxes.append({
                "id": len(boxes), "kind": "textbox",
                "x": geo["x"], "y": geo["y"], "w": geo["w"], "h": geo["h"],
                "text": full_text.rstrip("\n"),
                "paragraphs": paras,
                "placeholders": placeholders,
            })
        else:
            # 表格单元格：XML 网格坐标近似定位（vMerge 续格不在此列），
            # 行高缺失导致纵向漂移由 PDF 校准兜底
            boxes.append({
                "id": len(boxes), "kind": "table",
                "x": cell_geo["x"], "y": cell_geo["y"],
                "w": cell_geo["w"], "h": cell_geo["h"],
                "text": full_text.rstrip("\n"),
                "paragraphs": paras,
                "placeholders": placeholders,
            })

    # 用 PDF 实际渲染校准位置（x/y 以 PDF 为准；宽高仅在退化时补齐）
    pdf_ok = False
    hit_ids = set()
    tmp_dir = Path(tempfile.mkdtemp(prefix="rt_"))
    try:
        pdf_path = tmp_dir / "tpl.pdf"
        if _convert_to_pdf_safe(docx_path, pdf_path):
            pdf_ok = True
            hit_ids = _pdf_calibrate(pdf_path, boxes)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] PDF 定位失败，回退 XML 坐标: {exc}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    ml = round(sec.left_margin / EMU_PER_PX)
    mt = round(sec.top_margin / EMU_PER_PX)
    for b in boxes:
        if b["id"] in hit_ids:
            continue  # 已按 PDF 实际渲染位置校准
        if pdf_ok and not b["text"].strip():
            # 空盒子：够大的是待填内容区（保持可编辑），小的当装饰盒剔除，
            # 避免「清空后再也点不回来」或满屏装饰热区两种极端
            b["editable"] = b["w"] >= 40 and b["h"] >= 14
            continue
        # 未校准：用带边距的 XML 坐标兜底
        b["x"] += ml
        b["y"] += mt

    for b in boxes:
        b.setdefault("editable", True)
    _fix_degenerate_boxes(boxes, page_w, page_h)

    # 模块标题格（表格型模板的分区头）不可编辑：属于设计的一部分
    for b in boxes:
        if b.get("kind") != "table" or b.get("editable") is False:
            continue
        t = (b.get("text") or "").strip()
        if t and not PLACEHOLDER_RE.search(t) and len(t) <= 6 \
                and SECTION_TITLE_RE.match(t):
            b["editable"] = False

    # 正文段落（无文本框时兜底）：逐段作为流式盒子
    if not boxes:
        for p in body.findall(qn("w:p")):
            info = _paragraph_info(p)
            if not info["text"]:
                continue
            boxes.append({
                "id": len(boxes), "kind": "paragraph",
                "x": 0, "y": 0, "w": page_w, "h": 0,
                "text": info["text"], "paragraphs": [info],
                "placeholders": PLACEHOLDER_RE.findall(info["text"]),
            })

    return {"page_w": page_w, "page_h": page_h, "boxes": boxes}


def _iter_editable_txbxs(body):
    """文本框序列（跳过 mc:Fallback 副本）。"""
    for txbx in body.iter(qn("w:txbxContent")):
        if _find_ancestor(txbx, "{%s}Fallback" % MC_NS) is not None:
            continue
        yield txbx


def _collect_edit_targets(body) -> list:
    """收集可编辑目标，parse 与 apply 共用，保证盒子编号严格一致。

    目标两类：
    1. 文本框 w:txbxContent（跳过 mc:Fallback 副本），文档顺序；
    2. 顶层表格单元格 w:tc——大量中文简历模板用表格排版。含文本框的
       格子跳过（内容由内部文本框表达）；空格子也产出以维持编号连续。

    每项为 (kind, node, geo)；geo 仅对 cell 有意义（px，相对页面内容区）。"""
    targets = []
    for txbx in _iter_editable_txbxs(body):
        targets.append(("textbox", txbx, None))

    for tbl in body.findall(qn("w:tbl")):
        grid = []
        grid_el = tbl.find(qn("w:tblGrid"))
        if grid_el is not None:
            for gc in grid_el.findall(qn("w:gridCol")):
                try:
                    grid.append(int(gc.get(qn("w:w"))) / 15.0)  # dxa→px
                except (TypeError, ValueError):
                    grid.append(0.0)

        ind_px = 0.0
        tblpr = tbl.find(qn("w:tblPr"))
        if tblpr is not None:
            ind = tblpr.find(qn("w:tblInd"))
            if ind is not None and ind.get(qn("w:w")) \
                    and (ind.get(qn("w:type")) or "dxa") == "dxa":
                try:
                    ind_px = int(ind.get(qn("w:w"))) / 15.0
                except ValueError:
                    ind_px = 0.0

        y = 0.0
        for tr in tbl.findall(qn("w:tr")):
            h = 0.0
            trpr = tr.find(qn("w:trPr"))
            if trpr is not None:
                th = trpr.find(qn("w:trHeight"))
                if th is not None and th.get(qn("w:val")):
                    try:
                        h = int(th.get(qn("w:val"))) / 15.0
                    except ValueError:
                        h = 0.0

            x = ind_px
            col = 0
            for tc in tr.findall(qn("w:tc")):
                span = 1
                tcw_px = 0.0
                has_vmerge = False
                tcpr = tc.find(qn("w:tcPr"))
                if tcpr is not None:
                    gs = tcpr.find(qn("w:gridSpan"))
                    if gs is not None and gs.get(qn("w:val")):
                        try:
                            span = max(1, int(gs.get(qn("w:val"))))
                        except ValueError:
                            span = 1
                    if tcpr.find(qn("w:vMerge")) is not None:
                        has_vmerge = True
                    tcw = tcpr.find(qn("w:tcW"))
                    if tcw is not None and (tcw.get(qn("w:type")) or "") == "dxa":
                        try:
                            tcw_px = int(tcw.get(qn("w:w"))) / 15.0
                        except ValueError:
                            tcw_px = 0.0

                advance = sum(grid[col:col + span]) if grid else 0.0
                width = tcw_px or advance
                col += span
                x += advance

                if tc.find(".//" + qn("w:txbxContent")) is not None:
                    continue  # 内容由内部文本框表达
                targets.append(("cell", tc,
                                {"x": round(x - advance), "y": round(y),
                                 "w": round(width), "h": round(h),
                                 "vmerge": has_vmerge}))
            y += h
        # 表后累加行高缺失时整体坐标可能不准，交由 PDF 校准兜底
    return targets


def _write_plain_text(container, text):
    """把纯文字写入容器（文本框或单元格）：保留首段 pPr/首 run rPr 格式，
    按换行拆段落重建，其余原段落删除。"""
    paras = [p for p in container.findall(qn("w:p"))]
    p_pr = None
    r_pr = None
    if paras:
        first = paras[0]
        p_pr = first.find(qn("w:pPr"))
        first_run = first.find(qn("w:r"))
        if first_run is not None:
            r_pr = first_run.find(qn("w:rPr"))
    for p in paras:
        container.remove(p)
    for line in (text or "").split("\n"):
        p = OxmlElement("w:p")
        if p_pr is not None:
            p.append(deepcopy(p_pr))
        r = OxmlElement("w:r")
        if r_pr is not None:
            r.append(deepcopy(r_pr))
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = line
        r.append(t)
        p.append(r)
        container.append(p)


def _node_text(node) -> str:
    """容器当前全文（用于对比编辑前后长度）。"""
    parts = []
    for t in node.iter(qn("w:t")):
        parts.append(t.text or "")
    return "".join(parts)


def _ensure_shrink_on_overflow(txbx) -> None:
    """文本内容变长时，把文本框的自动调整改为 Word 的「缩小字体填充」
    (normAutofit)。

    简历模板的文本框都是绝对定位：spAutoFit（框随文字长高）会把下方
    板块压叠，noAutofit 则直接溢出叠字——两者在用户写长内容后都会把
    版面搅乱。统一切换为 normAutofit 后，Word 渲染/导出时自动压缩字号
    装进原框，版面不再互相覆盖。VML 老式文本框（w:pict）不支持该属性，
    自动跳过。仅在该框内容比原文长时调用。"""
    cur = txbx.getparent()
    while cur is not None:
        if cur.tag == "{%s}wsp" % WPS_NS:
            body_pr = cur.find("{%s}bodyPr" % WPS_NS)
            if body_pr is None:
                return
            for child in list(body_pr):
                if child.tag in ("{%s}normAutofit" % A_NS,
                                 "{%s}spAutoFit" % A_NS,
                                 "{%s}noAutofit" % A_NS):
                    body_pr.remove(child)
            fit = OxmlElement("a:normAutofit")
            warp = body_pr.find("{%s}prstTxWarp" % A_NS)
            if warp is not None:
                warp.addnext(fit)
            else:
                body_pr.insert(0, fit)
            return
        cur = cur.getparent()


_WNS_DECL = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
)


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
        .replace(">", "&gt;").replace('"', "&quot;")


def _box_run_properties(font: dict) -> str:
    """added 盒子文字的 rPr 片段：字体/字号(px→pt×0.75)/颜色/加粗/斜体。"""
    font = font if isinstance(font, dict) else {}
    parts = []
    family = str(font.get("family") or "").strip()
    if family:
        fam = _xml_escape(family)
        parts.append(f'<w:rFonts w:ascii="{fam}" w:eastAsia="{fam}" w:hAnsi="{fam}"/>')
    try:
        half = int(round(float(font.get("size")) * 0.75 * 2))
    except (TypeError, ValueError):
        half = 0
    if half > 0:
        parts.append(f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>')
    color = str(font.get("color") or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", color):
        parts.append(f'<w:color w:val="{color.upper()}"/>')
    if font.get("bold"):
        parts.append("<w:b/>")
    if font.get("italic"):
        parts.append("<w:i/>")
    return "".join(parts)


def _add_textbox_paragraph(body, box) -> None:
    """把 added 盒子注入为页面级绝对定位的 wps 文本框（EMU = px × 9525）。

    锚点段落插在 body 首个元素之前，行高压到 1pt 级别避免版面位移；
    页面级定位使文本框出现在 (x, y)。几何非法时抛异常，由调用方跳过。"""
    x = int(round(float(box.get("x") or 0) * EMU_PER_PX))
    y = int(round(float(box.get("y") or 0) * EMU_PER_PX))
    w = max(1, int(round(float(box.get("w") or 200) * EMU_PER_PX)))
    h = max(1, int(round(float(box.get("h") or 40) * EMU_PER_PX)))
    try:
        shape_id = int(box.get("id"))
    except (TypeError, ValueError):
        shape_id = 0
    doc_pr_id = 9001 + (abs(shape_id) % 9000)
    jc = {"center": "center", "right": "right"}.get(str(box.get("align") or "").lower(), "left")
    rpr = _box_run_properties(box.get("font"))
    text = str(box.get("text") or "")
    paras_xml = "".join(
        f'<w:p><w:pPr><w:spacing w:before="0" w:after="0"/><w:jc w:val="{jc}"/></w:pPr>'
        f'<w:r><w:rPr>{rpr}</w:rPr>'
        f'<w:t xml:space="preserve">{_xml_escape(ln)}</w:t></w:r></w:p>'
        for ln in text.split("\n"))
    xml = (
        f'<w:p {_WNS_DECL}>'
        '<w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/>'
        '<w:rPr><w:sz w:val="2"/></w:rPr></w:pPr>'
        '<w:r><w:rPr><w:sz w:val="2"/></w:rPr><w:drawing>'
        '<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
        f'relativeHeight="{251650000 + abs(shape_id)}" behindDoc="0" locked="0" '
        'layoutInCell="1" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{x}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{y}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{w}" cy="{h}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{doc_pr_id}" name="AddedBox{shape_id}"/>'
        '<wp:cNvGraphicFramePr/>'
        '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:cNvSpPr txBox="1"/>'
        f'<wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/>'
        '<a:ln><a:noFill/></a:ln></wps:spPr>'
        f'<wps:txbx><w:txbxContent>{paras_xml}</w:txbxContent></wps:txbx>'
        '<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="9144" tIns="0" '
        'rIns="9144" bIns="0" anchor="t"><a:noAutofit/></wps:bodyPr>'
        '</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p>'
    )
    body.insert(0, parse_xml(xml))


def apply_box_texts(docx_path, edits: Dict[str, str], added: Optional[List[dict]] = None):
    """把编辑后的文本写回对应文本框/单元格（保留原格式），返回 docx 字节。

    added：管理端「自由编辑」新增盒子的定义列表 [{id(负数), x,y,w,h, text, font, align}]，
    逐个注入为绝对定位文本框；edits 里若带同 id 的负数键，其文本优先。
    单个盒子注入失败仅打印告警并跳过，不炸导出主链路。"""
    doc = Document(str(docx_path))
    body = doc.element.body
    targets = _collect_edit_targets(body)
    for box_id, text in edits.items():
        try:
            idx = int(box_id)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(targets):
            continue
        kind, node, _geo = targets[idx]
        if kind == "textbox" and len(text or "") > len(_node_text(node)):
            # 内容变长才需要防溢出；变短/清空不动模板原有排版
            _ensure_shrink_on_overflow(node)
        # 文本框与单元格统一：保留首段格式，按换行重建段落
        _write_plain_text(node, text)
    for spec in (added or []):
        if not isinstance(spec, dict):
            continue
        try:
            spec = dict(spec)
            bid = spec.get("id")
            if bid is not None and str(bid) in edits:
                spec["text"] = edits[str(bid)]
            _add_textbox_paragraph(body, spec)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] 追加文本框 #{spec.get('id')} 注入失败，已跳过: {exc}")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
