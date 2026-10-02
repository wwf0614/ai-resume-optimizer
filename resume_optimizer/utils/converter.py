"""格式转换：PDF ↔ Word（尽力保留版式）、文本/图片提取。"""
import os
from pathlib import Path
from typing import Union

import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from docx2pdf import convert as docx2pdf_convert
from pdf2docx import Converter as Pdf2DocxConverter

# Tesseract OCR 路径（可通过环境变量 TESSERACT_CMD 覆盖，默认 Windows 安装路径）
pytesseract.pytesseract.tesseract_cmd = os.getenv(
    "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def image_to_text(image_path: Union[str, Path]) -> str:
    """用 Tesseract OCR 识别图片中的中英文文字。"""
    from PIL import Image

    img = Image.open(str(image_path))
    text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def pdf_to_text(pdf_path: Union[str, Path]) -> str:
    """用 pdfplumber 提取 PDF 文本内容。"""
    text_parts = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t.strip())
    return "\n".join(text_parts)


def pdf_to_text_ocr(pdf_path: Union[str, Path]) -> str:
    """用 OCR 提取图片型 PDF 的文字（中英文）。

    将每页渲染为高分辨率图片，然后用 Tesseract OCR 识别。
    """
    text_parts = []
    doc = fitz.Document(str(pdf_path))
    for page in doc:
        # 渲染为 300 DPI 的高清图片
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(img_bytes))
        # OCR 识别中英文
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        if text.strip():
            text_parts.append(text.strip())
    doc.close()
    return "\n".join(text_parts)


def pdf_to_docx(pdf_path: Union[str, Path], docx_path: Union[str, Path]) -> Path:
    """将 PDF 转为 docx，尽力保留原版式。"""
    docx_path = Path(docx_path)
    cv = Pdf2DocxConverter(str(pdf_path))
    try:
        cv.convert(str(docx_path))
    finally:
        cv.close()
    return docx_path


def docx_to_pdf(docx_path: Union[str, Path], pdf_path: Union[str, Path]) -> Path:
    """通过 Word COM 将 docx 转为 PDF。"""
    pdf_path = Path(pdf_path)
    # 先清理可能残留/损坏的 Word 进程，避免 COM 状态退化导致转换失败
    try:
        import subprocess
        subprocess.run(["taskkill", "/F", "/IM", "WINWORD.EXE"],
                       capture_output=True, shell=False)
    except Exception:  # noqa: BLE001
        pass
    import time
    time.sleep(0.6)
    # FastAPI 工作线程中必须先初始化 COM，否则 Word 自动化会报
    # "尚未调用 CoInitialize" 错误（线程池线程不自动初始化）
    import pythoncom
    pythoncom.CoInitialize()
    last_err = None
    for attempt in range(3):
        try:
            docx2pdf_convert(str(docx_path), str(pdf_path), keep_active=False)
            return pdf_path
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 * (attempt + 1))
            try:
                import subprocess
                subprocess.run(["taskkill", "/F", "/IM", "WINWORD.EXE"],
                               capture_output=True, shell=False)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)
    pythoncom.CoUninitialize()
    raise last_err


# ════════════════════════════════════════════════════════════════
# 实时预览专用：复用 Word 进程，避免每次启动 5s 开销
# ════════════════════════════════════════════════════════════════
_WORD_APP = None
_WORD_LOCK = None  # 延迟初始化（线程锁）


def _get_word_lock():
    global _WORD_LOCK
    if _WORD_LOCK is None:
        import threading
        _WORD_LOCK = threading.Lock()
    return _WORD_LOCK


def _get_word_app():
    """获取/创建全局 Word 单例。失败返回 None。"""
    global _WORD_APP
    if _WORD_APP is not None:
        try:
            # 健康检查：访问一个无害属性
            _ = _WORD_APP.Visible
            return _WORD_APP
        except Exception:
            _WORD_APP = None
    try:
        import win32com.client
        _WORD_APP = win32com.client.DispatchEx("Word.Application")
        _WORD_APP.Visible = False
        _WORD_APP.DisplayAlerts = False
        return _WORD_APP
    except Exception:
        _WORD_APP = None
        return None


def docx_to_pdf_fast(docx_path: Union[str, Path], pdf_path: Union[str, Path]) -> Path:
    """快速版：复用全局 Word 进程，比 docx_to_pdf 快 3-5s。
    失败时自动降级到 docx_to_pdf（taskkill 重启策略）。
    线程安全：用全局锁串行化 Word 调用。"""
    import pythoncom
    import time
    pdf_path = Path(pdf_path)
    pythoncom.CoInitialize()
    lock = _get_word_lock()
    with lock:
        word = _get_word_app()
        if word is None:
            # 单例创建失败，降级
            return docx_to_pdf(docx_path, pdf_path)
        doc = None
        try:
            # wdFormatPDF = 17, wdDoNotSaveChanges = 0
            doc = word.Documents.Open(str(Path(docx_path).resolve()), ReadOnly=True)
            doc.SaveAs2(str(pdf_path.resolve()), FileFormat=17)
            return pdf_path
        except Exception:
            # Word 进程可能挂了，重置单例并降级
            global _WORD_APP
            try:
                if doc is not None:
                    doc.Close(SaveChanges=0)
            except Exception:
                pass
            try:
                _WORD_APP.Quit()
            except Exception:
                pass
            _WORD_APP = None
            return docx_to_pdf(docx_path, pdf_path)
        finally:
            try:
                if doc is not None:
                    doc.Close(SaveChanges=0)
            except Exception:
                pass
            pythoncom.CoUninitialize()


def extract_photo(file_path: Union[str, Path], out_path: Union[str, Path]):
    """从 PDF 或 Word 文件中提取证件照（AI 人脸识别优先）。

    遍历文件全部图片，用 YuNet 人脸检测评分选最佳证件照，
    统一裁剪 3:4 保存。无有效照片时返回 None。
    """
    from . import photo
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        images = photo.images_from_pdf(Path(file_path))
    elif suffix == ".docx":
        images = photo.images_from_docx(Path(file_path))
    else:
        return None
    if not images:
        return None
    info = photo.extract_best_avatar(images, Path(out_path))
    if info is None:
        return None
    return Path(out_path)


def _extract_photo_from_pdf(file_path, out_path):
    """从 PDF 提取证件照：收集所有 >50x50 的图片，选宽高比最接近 3:4 的。

    扫描件 PDF 常含大尺寸背景/装饰图，证件照宽高比约 0.7~0.85；
    若无特征明显的证件照，退回第一张合理尺寸图片。
    """
    doc = fitz.open(str(file_path))
    candidates = []
    try:
        for page in doc:
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                pix = fitz.Pixmap(doc, xref)
                if pix.width < 50 or pix.height < 50:
                    pix = None
                    continue
                candidates.append((pix, pix.width / pix.height))
        if not candidates:
            return None
        # 宽高比最接近 3:4 的图片作为证件照
        best, best_ratio = None, 1.0
        for pix, ratio in candidates:
            if abs(ratio - 0.75) < best_ratio:
                best, best_ratio = pix, abs(ratio - 0.75)
        if best is None:
            best = candidates[0][0]
        # CMYK 转 RGB
        if best.n - best.alpha > 3:
            best = fitz.Pixmap(fitz.csRGB, best)
        best.save(str(out_path))
        return Path(out_path)
    finally:
        doc.close()


def _extract_photo_from_docx(file_path, out_path):
    """从 Word 文档提取第一张图片。"""
    from docx import Document
    doc = Document(str(file_path))
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            image_part = rel.target_part
            with open(str(out_path), "wb") as f:
                f.write(image_part.blob)
            return Path(out_path)
    # 检查文本框中的图片（通过 XML 遍历）
    from docx.oxml.ns import qn
    blips = doc.element.iter(qn("a:blip"))
    for blip in blips:
        embed = blip.get(qn("r:embed"))
        if embed:
            try:
                image_part = doc.part.related_parts[embed]
                with open(str(out_path), "wb") as f:
                    f.write(image_part.blob)
                return Path(out_path)
            except (KeyError, Exception):
                continue
    return None
