"""质量引擎 FastAPI 路由。

Phase 1：匹配度评分（免费引流）。
Phase 2：ATS 文本层校验（免费）：PDF/Word 导出文件字节流上传，统一报告。
后续 Phase 在下方追加 grounding-audit / dual_review 路由。
"""
import json

from fastapi import APIRouter, File, Form, UploadFile

from .ats_check import ats_check
from .match_score import match_score
from .schemas import MatchScoreRequest

router = APIRouter()


@router.post("/api/quality/match-score")
def api_match_score(req: MatchScoreRequest):
    """匹配度评分：输入结构化档案 + 目标岗位/JD，返回综合分与四维分。

    免费功能，无需登录（档案由前端编辑器自己传入）。
    """
    return match_score(req.profile, req.target_job, req.jd)


@router.post("/api/quality/ats-check")
async def api_ats_check(
    file: UploadFile = File(...),
    jd: str = Form(""),
    target_job: str = Form(""),
    profile: str = Form(""),
):
    """ATS 文本层校验：上传导出的 PDF/Word 字节流，返回统一 ATS 报告。

    免费功能，无需登录。文件由前端导出后直接上传，与后端 sessions 解耦。
    - file: 导出的 .pdf 或 .docx
    - jd / target_job: 可选，用于关键词覆盖率
    - profile: 可选 JSON 字符串，用于强校验联系方式是否以字面文本出现
    """
    data = await file.read()
    filename = (file.filename or "").lower()
    fmt = "pdf" if filename.endswith(".pdf") else ("docx" if filename.endswith((".docx", ".doc")) else "")
    if not fmt:
        # 退而求其次：按 magic 判断
        fmt = "pdf" if data[:4] == b"%PDF" else "docx"

    parsed_profile = None
    if profile:
        try:
            parsed_profile = json.loads(profile)
        except Exception:
            parsed_profile = None

    return ats_check(
        file_bytes=data,
        fmt=fmt,
        jd=jd or "",
        target_job=target_job or "",
        profile=parsed_profile,
    )
