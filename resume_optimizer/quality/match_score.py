"""匹配度评分（免费引流）：确定性关键词重叠 + 智谱 GLM 四维语义打分。

综合分权重（照搬 ai-job-search 评估框架）：
  technical 30% / experience 25% / behavioral 15% / career 30%
地点为 pass/fail 闸门，不计入加权。
"""
import json
import time
from typing import Any, Dict, Optional

from utils import applog, llm

from .profile_bridge import (
    extract_jd_keywords,
    flatten_profile_text,
    keyword_overlap,
)
from .prompts import MATCH_SCORE_PROMPT

_WEIGHTS = {
    "technical": 0.30,
    "experience": 0.25,
    "behavioral": 0.15,
    "career": 0.30,
}

_THRESHOLDS = [
    (75, "strong_fit", "强匹配：建议直接投递，重点定制"),
    (60, "good_fit", "良好匹配：可以投递，在求职信中弥补缺口"),
    (45, "moderate_fit", "中等匹配：谨慎考虑，先和我对齐"),
    (30, "weak_fit", "偏弱匹配：除非有战略理由，否则建议跳过"),
]


def _parse_json(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _clamp100(x: Any) -> int:
    try:
        v = int(round(float(x)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, v))


def _recommendation(total: int):
    for thr, rec, txt in _THRESHOLDS:
        if total >= thr:
            return rec, txt
    return "poor_fit", "弱匹配：建议跳过"


def _location_gate(profile: Dict[str, Any], jd: str, target_job: str) -> str:
    """地点闸门（Phase 1 保守实现：不硬拒，仅标注）。"""
    basic = (profile or {}).get("basic") or {}
    city = basic.get("city") or ""
    text = (jd or "") + " " + (target_job or "")
    if not city or not text:
        return "unknown"
    if city in text:
        return "pass"
    return "unknown"


def _call_glm_json_retry(prompt: str, attempts: int = 3) -> Optional[str]:
    """调用智谱 GLM 并原样返回文本，遇限流（429）做指数退避重试。

    免费 glm-4.7-flash 额度紧，连发易触发 429；退避可消化瞬时限流。
    非限流异常直接放弃（交由上层走确定性回退）。
    """
    last_err = ""
    for i in range(attempts):
        try:
            return llm._call_glm_json(prompt)
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            if "rate" in last_err.lower() or "429" in last_err:
                if i < attempts - 1:
                    time.sleep(2 * (i + 1))  # 2s, 4s 退避
                    continue
            applog.log("match_score_glm_error", error=last_err[:200])
            break
    return None


def match_score(
    profile: Optional[Dict[str, Any]], target_job: str, jd: str
) -> Dict[str, Any]:
    """计算候选人与岗位的匹配度。

    返回结构见 schemas.MatchScoreResponse。模型层不可用时回退到确定性关键词覆盖估算。
    """
    profile = profile or {}
    profile_text = flatten_profile_text(profile)
    jd_keywords = extract_jd_keywords(jd, target_job)
    det = keyword_overlap(jd_keywords, profile_text)

    model_dims: Optional[Dict[str, int]] = None
    obj: Optional[dict] = None
    method = "glm"
    note = ""
    # 注意：提示词内含 JSON 示例花括号，不能用 str.format（会误解析花括号），
    # 用 replace 安全注入两个占位符。
    prompt = (
        MATCH_SCORE_PROMPT.replace("{profile}", profile_text[:4000])
        .replace("{jd}", (jd or target_job)[:2000])
    )
    raw = _call_glm_json_retry(prompt)
    if raw:
        obj = _parse_json(raw)
        if obj and all(k in obj for k in _WEIGHTS):
            model_dims = {k: _clamp100(obj.get(k)) for k in _WEIGHTS}
    if model_dims is None and raw:
        # 有返回但结构不符（缺维度），仍记一笔便于排查
        applog.log("match_score_glm_bad_structure", raw=raw[:200])

    if not model_dims:
        method = "deterministic_fallback"
        note = "模型打分暂不可用，已基于关键词覆盖给出估算"
        cov = det["coverage"]
        model_dims = {
            "technical": cov,
            "experience": cov,
            "behavioral": max(40, cov - 20),
            "career": max(40, cov - 10),
        }

    total = int(round(sum(model_dims[k] * w for k, w in _WEIGHTS.items())))
    rec, verdict = _recommendation(total)

    matched = (obj or {}).get("matched_keywords") or det["matched"][:15]
    missing = (obj or {}).get("missing_keywords") or det["missing"][:15]
    strengths = (obj or {}).get("strengths") or []
    gaps = (obj or {}).get("gaps") or []

    if isinstance(matched, str):
        matched = [matched]
    if isinstance(missing, str):
        missing = [missing]
    if isinstance(strengths, str):
        strengths = [strengths]
    if isinstance(gaps, str):
        gaps = [gaps]

    return {
        "total_score": total,
        "dimensions": model_dims,
        "matched_keywords": matched,
        "missing_keywords": missing,
        "strengths": strengths,
        "gaps": gaps,
        "recommendation": rec,
        "verdict_text": verdict,
        "location_gate": _location_gate(profile, jd, target_job),
        "method": method,
        "note": note,
        "det_keyword_coverage": det["coverage"],
    }
