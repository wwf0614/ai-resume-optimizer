"""质量引擎请求/响应模型。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MatchScoreRequest(BaseModel):
    """匹配度评分请求。

    profile 即编辑器的结构化档案（真相源）：{basic: {...}, modules: {...}}。
    target_job / jd 至少提供一个；两者都有时以 jd 为主、target_job 补充岗位整词。
    """

    profile: Optional[Dict[str, Any]] = Field(
        default=None, description="编辑器结构化档案 {basic, modules}"
    )
    target_job: str = Field(default="", description="目标岗位/求职意向")
    jd: str = Field(default="", description="招聘要求 JD 全文（可选）")


class MatchScoreResponse(BaseModel):
    total_score: int = Field(description="综合匹配分 0-100")
    dimensions: Dict[str, int] = Field(
        description="四维分：technical/experience/behavioral/career"
    )
    matched_keywords: List[str] = Field(default_factory=list, description="命中关键词")
    missing_keywords: List[str] = Field(default_factory=list, description="缺失关键词")
    strengths: List[str] = Field(default_factory=list, description="核心匹配优势")
    gaps: List[str] = Field(default_factory=list, description="需弥补缺口")
    recommendation: str = Field(
        description="strong_fit/good_fit/moderate_fit/weak_fit/poor_fit"
    )
    verdict_text: str = Field(description="给用户的结论文案")
    location_gate: str = Field(
        default="unknown", description="pass/fail/flag/unknown 地点闸门"
    )
    method: str = Field(
        default="glm", description="glm=模型打分 / deterministic_fallback=关键词回退"
    )
    note: str = Field(default="", description="附加说明（如回退原因）")
    det_keyword_coverage: int = Field(
        default=0, description="确定性层关键词覆盖率 0-100（仅供参考）"
    )
