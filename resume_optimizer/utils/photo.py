# -*- coding: utf-8 -*-
"""证件照智能提取模块。

从用户上传的简历（Word/PDF）中提取证件照：
1. 遍历文档内全部图片；
2. 用 OpenCV YuNet 人脸检测评分（置信度过滤）；
3. 无人脸时按尺寸/宽高比回退；
4. 统一裁剪 3:4 标准比例，生成高清导出图 + 预览缩略图。
"""
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

_MODEL_PATH = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"
_detector = None


def _get_detector():
    """懒加载 YuNet 人脸检测器；模型缺失时返回 None（回退启发式）。"""
    global _detector
    if _detector is not None:
        return _detector
    try:
        import cv2
        if not _MODEL_PATH.exists():
            return None
        _detector = cv2.FaceDetectorYN.create(
            str(_MODEL_PATH), "", (320, 320), 0.6, 0.3, 5000
        )
        return _detector
    except Exception:
        return None


def _face_score(img) -> Tuple[float, int]:
    """返回 (最高人脸置信度, 人脸数量)；检测失败返回 (0, 0)。"""
    det = _get_detector()
    if det is None:
        return 0.0, 0
    try:
        import cv2
        # YuNet 输入尺寸
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        if faces is None or len(faces) == 0:
            return 0.0, 0
        conf = float(faces[:, -1].max())
        return conf, len(faces)
    except Exception:
        return 0.0, 0


def _crop_3x4(img) -> Image.Image:
    """居中裁剪为 3:4 标准证件比例（头部略偏上）。"""
    w, h = img.size
    target = 3.0 / 4.0
    ratio = w / h
    if abs(ratio - target) < 0.03:
        return img
    if ratio > target:
        new_w = int(h * target)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    new_h = int(w / target)
    top = int((h - new_h) * 0.35)  # 略偏上保留头部
    return img.crop((0, top, w, top + new_h))


def _from_bytes(data: bytes) -> Optional[Image.Image]:
    try:
        return Image.open(__import__("io").BytesIO(data)).convert("RGB")
    except Exception:
        return None


def _score_candidate(img: Image.Image):
    """综合评分：人脸置信度优先，其次尺寸与 3:4 比例。"""
    import numpy as np
    arr = np.asarray(img.convert("RGB"))
    conf, faces = _face_score(arr[:, :, ::-1])  # RGB -> BGR
    w, h = img.size
    ratio = w / h
    ratio_score = max(0.0, 1.0 - abs(ratio - 0.75) * 2.0)
    size_score = min(1.0, (w * h) / (200 * 250))
    return conf * 3.0 + faces * 0.5 + ratio_score * 0.8 + size_score * 0.4


def extract_best_avatar(
    images: List[Tuple[bytes, str]],  # [(图片字节, 来源说明)]
    out_path: Path,
    thumb_path: Optional[Path] = None,
) -> Optional[dict]:
    """从候选图片中选最佳证件照，裁剪 3:4 保存，返回资源信息。"""
    scored = []
    for data, src in images:
        img = _from_bytes(data)
        if img is None:
            continue
        if img.width < 60 or img.height < 60:
            continue
        score = _score_candidate(img)
        scored.append((score, img, src))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best_img, src = scored[0][1], scored[0][2]
    cropped = _crop_3x4(best_img)
    # 高清导出（最长边约 900px）
    max_side = 900
    scale = min(1.0, max_side / max(cropped.size))
    if scale < 1.0:
        cropped = cropped.resize((int(cropped.width * scale), int(cropped.height * scale)),
                                 Image.LANCZOS)
    cropped.save(str(out_path), "PNG")
    info = {"path": str(out_path), "source": src, "face_conf": round(scored[0][0], 3)}
    if thumb_path is not None:
        thumb = cropped.copy()
        thumb.thumbnail((180, 240), Image.LANCZOS)
        thumb.save(str(thumb_path), "PNG")
        info["thumb"] = str(thumb_path)
    return info


def images_from_docx(docx_path: Path) -> List[Tuple[bytes, str]]:
    """收集 Word 文档内全部图片（含文本框/表格内）。"""
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(str(docx_path))
    out = []
    seen = set()
    blips = list(doc.element.iter(qn("a:blip")))
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                data = rel.target_part.blob
            except Exception:
                continue
            key = hash(data[:256])
            if key in seen:
                continue
            seen.add(key)
            out.append((data, "word"))
    for blip in blips:
        embed = blip.get(qn("r:embed"))
        if embed:
            try:
                data = doc.part.related_parts[embed].blob
            except Exception:
                continue
            key = hash(data[:256])
            if key in seen:
                continue
            seen.add(key)
            out.append((data, "word"))
    return out


def images_from_pdf(pdf_path: Path) -> List[Tuple[bytes, str]]:
    """收集 PDF 内全部图片。"""
    import fitz
    doc = fitz.open(str(pdf_path))
    out = []
    try:
        for page in doc:
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                pix = fitz.Pixmap(doc, xref)
                if pix.width < 60 or pix.height < 60:
                    continue
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                data = pix.tobytes("png")
                out.append((data, "pdf"))
    finally:
        doc.close()
    return out
