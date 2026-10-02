"""文件解析模块：从 pdf / docx / txt 中提取纯文本。"""
from pathlib import Path
from typing import Union

import pdfplumber
from docx import Document


def extract_text_from_pdf(file_path: Union[str, Path]) -> str:
    """用 pdfplumber 提取所有页面文本，去掉多余空行。"""
    lines = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = raw.strip()
                if line:
                    lines.append(line)
    return "\n".join(lines)


def extract_text_from_docx(file_path: Union[str, Path]) -> str:
    """用 python-docx 提取段落文本，保留换行。"""
    doc = Document(str(file_path))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text_from_txt(file_path: Union[str, Path]) -> str:
    """读取纯文本文件，尝试常见编码。"""
    path = str(file_path)
    for encoding in ("utf-8", "gbk", "gb18030"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def parse_resume(file_path: Union[str, Path]) -> str:
    """根据文件扩展名提取文本，支持 .pdf / .docx / .txt，其他格式抛出 ValueError。"""
    lower = str(file_path).lower()
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(file_path)
    if lower.endswith(".docx"):
        return extract_text_from_docx(file_path)
    if lower.endswith(".txt"):
        return extract_text_from_txt(file_path)
    raise ValueError("不支持的文件格式，仅支持 .pdf / .docx / .txt")
