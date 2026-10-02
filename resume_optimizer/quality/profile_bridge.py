"""将编辑器结构化档案（basic + modules）桥接为匹配评分可用的文本与关键词。

profile 数据结构（与 utils/llm.generate_full_resume 产出一致）：
{
  "basic": {"name","gender","age","phone","email","city","education_degree",
            "school","major","intention_job","political_status", ...},
  "modules": {"education_info":[...], "work_history":[...], "internship_info":[...],
              "projects":[...], "campus_exp":[...], "skill_info":[...],
              "honor_cert":[...], "self_evaluate":"", "hobby":[...], "custom":""}
}
"""
import re
from typing import Any, Dict, List, Set

import jieba

# 轻量停用词，过滤无信息量的高频词
_STOPWORDS = set(
    "的 了 和 与 及 或 在 对 等 我 你 他 她 它 我们 你们 他们 是 有 为 以 也 都 就 而 并 "
    "将 把 被 让 给 从 到 这 那 这个 那个 该 其 一个 一种 一名 能够 可以 进行 通过 以及 "
    "相关 以上 以下 负责 参与 协助 支持 完成 处理 使用 运用 具备 拥有 良好 一定 较强 较强".split()
)


def flatten_profile_text(profile: Dict[str, Any]) -> str:
    """把结构化档案拍平为纯文本，供 GLM 与关键词提取使用。"""
    if not isinstance(profile, dict):
        return ""
    basic = profile.get("basic") or {}
    modules = profile.get("modules") or {}
    parts: List[str] = []

    for k in ("name", "intention_job", "job_title", "city", "education_degree",
              "school", "major", "political_status"):
        v = basic.get(k)
        if v:
            parts.append(str(v))

    def _join(items: Any) -> List[str]:
        out: List[str] = []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    out.append(" ".join(str(x) for x in it.values() if x))
                elif it:
                    out.append(str(it))
        elif isinstance(items, str):
            out.append(items)
        return out

    for key in ("education_info", "work_history", "internship_info", "projects",
                "campus_exp", "skill_info", "honor_cert", "self_evaluate",
                "hobby", "custom"):
        vals = _join(modules.get(key))
        if vals:
            parts.extend(vals)
    return "\n".join(parts)


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    tokens = jieba.lcut(text)
    out: List[str] = []
    for t in tokens:
        t = t.strip()
        if len(t) < 2:
            continue
        if t in _STOPWORDS:
            continue
        if re.fullmatch(r"[\s\W\d]+", t):
            continue
        out.append(t)
    return out


def extract_jd_keywords(jd: str, target_job: str = "") -> Set[str]:
    """从 JD + 目标岗位抽取关键词集合。"""
    text = (jd or "") + "\n" + (target_job or "")
    kws = set(_tokenize(text))
    if target_job and len(target_job.strip()) >= 2:
        kws.add(target_job.strip())
    return {k for k in kws if len(k) >= 2}


def extract_profile_keywords(profile_text: str) -> Set[str]:
    return set(_tokenize(profile_text))


def keyword_overlap(jd_keywords: Set[str], profile_text: str) -> Dict[str, Any]:
    """计算 JD 关键词在档案文本中的命中情况（子串 + 分词集合双判定）。"""
    profile_tokens = set(_tokenize(profile_text))
    matched: List[str] = []
    missing: List[str] = []
    for kw in sorted(jd_keywords, key=len, reverse=True):
        if not kw:
            continue
        if kw in profile_text or kw in profile_tokens:
            matched.append(kw)
        else:
            missing.append(kw)
    total = len(jd_keywords) or 1
    ratio = len(matched) / total
    return {
        "matched": matched,
        "missing": missing,
        "coverage": round(ratio * 100),
        "jd_keyword_count": len(jd_keywords),
    }
