"""模型调用与优化逻辑：通过 OpenAI 兼容接口调用小米 MiMo 模型。"""
import json
import os
import re
import time as _time
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from . import applog

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.xiaomimimo.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "mimo-v2.5")

# 智谱 GLM（超精细限定版专用，glm-4.7-flash 永久免费）
GLM_API_KEY = os.getenv("GLM_API_KEY", "")
GLM_BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
GLM_MODEL = os.getenv("GLM_MODEL", "glm-4.7-flash")

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL,
    # 小米 MiMo API 除 Bearer Token 外还需要 api-key 请求头
    default_headers={"api-key": API_KEY},
)

# 智谱 GLM：标准 OpenAI 兼容协议，仅需 Authorization Bearer，不额外加请求头
glm_client = OpenAI(
    api_key=GLM_API_KEY,
    base_url=GLM_BASE_URL,
)

# 本地 Ollama（OpenAI 兼容端点，api_key 任意非空即可）
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:1.5b")
ollama_client = OpenAI(
    api_key="ollama",
    base_url=OLLAMA_BASE_URL,
)


def clean_r1_output(text: str) -> str:
    """清洗模型输出：去除思考标签、代码块、JSON、元评论等。"""
    if not text:
        return ""

    # 1. 去除 <think>...</think> 标签
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    # 2. 去除 ``` 代码块
    if "```" in text:
        parts = text.split("```")
        # 取代码块外的文本
        text = " ".join(p for p in parts if not p.strip().lower().startswith(("response", "json")))

    # 3. 去除 JSON 块 { ... }
    text = re.sub(r"\{[^{}]*\}", "", text, flags=re.DOTALL)
    text = re.sub(r"\{.*?\}", "", text, flags=re.DOTALL)

    # 4. 去除元评论行，但保留实际内容
    #    仅匹配明确的元评论，避免误伤 "作为一名..." 等正常内容
    # 整行丢弃：AI 角色声明、STAR 标签声明等
    full_line_skip_patterns = [
        r"^作为一[位名].*?(顾问|HR|职业规划|规划师).{0,15}(我|以下|为您|您的)",
        r"^以下是.*?(改写|优化|修改|内容|版本|描述)",
        r"^我将.{0,6}(改写|优化|修改)",
        r"^我(深刻|理解|建议|认为|觉得).{0,10}(您|你|这|该|此)",
        r"^(这段|这个|该|此).{0,6}(经历|描述|内容|文字).{0,6}(改写|优化|修改|分析)",
    ]
    # 冒号前缀：提取冒号后的实际内容
    colon_extract_patterns = [
        r"^(改写后|修改后|优化后|重写后)",
        r"^(情境|任务|行动|结果)",
        r"^(原文|原描述|原内容)",
        r"^(作为一[位名].*?(顾问|HR|专家|规划师))",
    ]

    lines = text.strip().splitlines()
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 整行丢弃模式
        skip = False
        for pat in full_line_skip_patterns:
            if re.search(pat, line):
                skip = True
                break
        if skip:
            continue
        # 冒号前缀：尝试提取冒号后的内容
        extracted = False
        if "：" in line or ":" in line:
            parts = re.split(r"[：:]", line, maxsplit=1)
            if len(parts) == 2:
                before, after = parts[0].strip(), parts[1].strip()
                for pat in colon_extract_patterns:
                    if re.match(pat, before):
                        if after and len(after) >= 5:
                            clean_lines.append(after)
                        extracted = True
                        break
        if extracted:
            continue
        clean_lines.append(line)

    text = " ".join(clean_lines)

    # 5. 去除 STAR 标签前缀（内联）
    text = re.sub(r"(情境|任务|行动|结果)[：:]\s*", "", text)

    # 6. 截断行内元评论（"解释："、"说明："、"分析："等之后的内容）
    text = re.split(r"[。！？]\s*(解释|说明|分析|备注|注)[：:]", text)[0]
    text = re.split(r"\s(解释|说明|分析)[：:]", text)[0]

    # 7. 去除多余引号
    text = text.strip("\"'""''")

    # 8. 如果仍然太长（超过 200 字），只取第一句完整句子
    if len(text) > 200:
        # 找第一个句号
        for i, ch in enumerate(text):
            if ch in "。！？；":
                text = text[: i + 1]
                break
        if len(text) > 200:
            text = text[:150] + "。"

    return text.strip()


def _call_model(prompt: str, stop: Optional[List[str]] = None, json_mode: bool = False) -> str:
    kwargs = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        # MiMo 官方 API 使用 max_completion_tokens 参数
        # 关闭思考模式：MiMo 默认会先“思考”再回答，思考会消耗大量 token，
        # 长提示词下容易把输出预算耗尽导致内容为空；本任务不需要推理，直接关闭
        "max_completion_tokens": 4096,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    if stop:
        kwargs["stop"] = stop
    t0 = _time.monotonic()
    try:
        resp = client.chat.completions.create(timeout=120, **kwargs)
        content = resp.choices[0].message.content or ""
        applog.log("llm_call", model=LLM_MODEL, json_mode=json_mode,
                   duration_ms=round((_time.monotonic() - t0) * 1000),
                   chars=len(content))
    except Exception as exc:  # noqa: BLE001
        applog.log("llm_error", model=LLM_MODEL, json_mode=json_mode,
                   duration_ms=round((_time.monotonic() - t0) * 1000),
                   error=str(exc)[:200])
        raise
    if json_mode:
        # JSON 模式下不走 clean_r1_output（它会删除 { ... } 块）
        return content.strip()
    return clean_r1_output(content)


def _call_with_retry(prompt: str) -> str:
    return _call_model(prompt, stop=None)


# ── 简化提示词：对小模型更友好 ──
# 按身份区分：学生/应届生 vs 有经验者

# === 学生/应届生提示词 ===
_PROMPT_EXP_STUDENT = (
    "改写以下实习经历描述，使其更专业。\n"
    "要求：作为在校学生/应届生，用 参与、协助、负责、支持 等动词，"
    "突出学习能力和执行力，适当量化成果，匹配岗位关键词。\n"
    "禁止：使用 主导、带领、管理团队 等暗示资深经验的表述；"
    "禁止编造数字、输出解释、输出JSON、输出STAR标签。\n"
    "只输出一句改写后的描述（不超过80字），不要任何前缀。\n"
    "岗位：{jd}\n原文：{text}"
)

_PROMPT_PROJ_STUDENT = (
    "改写以下校园经历描述，使其更专业。\n"
    "要求：作为在校学生，用 参与、协助、组织、负责 等动词，"
    "突出团队协作和组织能力，适当量化成果，匹配岗位关键词。\n"
    "禁止：使用 主导、带领 等表述；禁止编造数字、输出解释、输出JSON。\n"
    "只输出一句改写后的描述（不超过80字），不要任何前缀。\n"
    "岗位：{jd}\n原文：{text}"
)

_PROMPT_EVAL_STUDENT = (
    "根据岗位重写以下自我评价，突出学习能力和成长潜力。\n"
    "要求：作为应届生，强调快速学习、动手能力和积极态度。\n"
    "禁止：输出解释、输出JSON、夸大经验。\n"
    "只输出改写后的自我评价（不超过120字），不要任何前缀。\n"
    "岗位：{jd}\n原文：{text}"
)

# === 有经验者提示词 ===
_PROMPT_EXPERIENCE = (
    "改写以下工作经历描述，使其更专业。\n"
    "要求：用强动词（主导、负责、构建），适当量化成果，匹配岗位关键词。\n"
    "禁止：编造数字、输出解释、输出JSON、输出STAR标签。\n"
    "只输出一句改写后的描述（不超过80字），不要任何前缀。\n"
    "岗位：{jd}\n原文：{text}"
)

_PROMPT_PROJECT = (
    "改写以下项目经历描述，使其更专业。\n"
    "要求：突出统筹协调和量化成果，匹配岗位关键词。\n"
    "禁止：编造数字、输出解释、输出JSON。\n"
    "只输出一句改写后的描述（不超过80字），不要任何前缀。\n"
    "岗位：{jd}\n原文：{text}"
)

_PROMPT_EVALUATION = (
    "根据岗位重写以下自我评价，突出核心竞争力。\n"
    "禁止：输出解释、输出JSON。\n"
    "只输出改写后的自我评价（不超过120字），不要任何前缀。\n"
    "岗位：{jd}\n原文：{text}"
)

# 技能板块两者共用
_PROMPT_SKILL = (
    "根据岗位需求优化以下技能描述，将匹配技能前置。\n"
    "禁止：编造不存在的技能、输出解释。\n"
    "只输出改写后的技能描述（不超过60字），不要任何前缀。\n"
    "岗位：{jd}\n原文：{text}"
)

# 按身份分组的提示词模板
_TEMPLATES = {
    "student": {
        "experience": _PROMPT_EXP_STUDENT,
        "project": _PROMPT_PROJ_STUDENT,
        "skill": _PROMPT_SKILL,
        "evaluation": _PROMPT_EVAL_STUDENT,
    },
    "experienced": {
        "experience": _PROMPT_EXPERIENCE,
        "project": _PROMPT_PROJECT,
        "skill": _PROMPT_SKILL,
        "evaluation": _PROMPT_EVALUATION,
    },
}


# 学生简历禁用词替换：模型可能不听指令，做后处理兜底
_STUDENT_VERB_FIXES = [
    (re.compile(r"主导(了)?"), r"负责\1"),
    (re.compile(r"带领(团队)?"), r"参与团队"),
    (re.compile(r"管理团队"), "协助团队"),
    (re.compile(r"统筹(全局|整体|全面)"), r"参与协调"),
]


def _adjust_for_student(text: str) -> str:
    """学生简历后处理：将不适合学生的资深动词替换为更合适的表述。"""
    for pattern, replacement in _STUDENT_VERB_FIXES:
        text = pattern.sub(replacement if isinstance(replacement, str) else replacement, text)
    return text


def rewrite_by_type(
    text: str,
    job_description: str,
    section_type: str,
    career_stage: str = "experienced",
) -> str:
    """按区块类型和求职者身份调用不同提示词改写。"""
    stage_templates = _TEMPLATES.get(career_stage, _TEMPLATES["experienced"])
    template = stage_templates.get(section_type, stage_templates["experience"])
    prompt = template.format(jd=job_description[:200], text=text[:300])
    result = _call_with_retry(prompt)
    # 学生简历：后处理替换不适合的资深动词
    if career_stage == "student" and result:
        result = _adjust_for_student(result)
    return result


# ══════════════════════════════════════════════════════════════════
# 结构化 JSON 输出（设计说明 9.2：模型返回 JSON + word_limits 字数控制）
# ══════════════════════════════════════════════════════════════════

# 各 module_key 在简历原文中的标题关键词（用于解析失败时的降级兜底）
_FALLBACK_KW: Dict[str, List[str]] = {
    "summary": ["个人优势", "自我评价", "个人简介", "个人总结", "自我描述"],
    "work_experience": ["工作经历", "工作经验", "实习经历", "实习经验", "实习",
                        "职业经历", "工作履历", "工作实践", "实践经历", "运营推广经历"],
    "projects": ["项目经历", "项目经验", "校园经历", "校园活动", "社会实践"],
    "education": ["教育背景", "教育经历", "学历"],
    "skills": ["专业技能", "技能特长", "核心技能", "技术栈", "技能",
               "技能证书", "证书及荣誉", "技外书及荣誉"],
}


def _extract_json(text: str) -> Optional[str]:
    """提取第一个 { 到最后一个 } 之间的内容。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]


def _truncate_to_limit(text: str, max_words: int) -> str:
    """超长内容截断至最后一个完整句子（中文句号/英文句点/换行）。"""
    t = (text or "").strip()
    if not t:
        return t
    if len(t) <= max_words:
        return t
    cut = t[:max_words]
    last = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"),
               cut.rfind("；"), cut.rfind("."), cut.rfind("\n"), cut.rfind("；"))
    if last > int(len(cut) * 0.5):
        return cut[:last + 1].strip()
    return cut.strip()


def _call_json(prompt: str) -> Optional[dict]:
    """调用模型并解析 JSON，最多重试 3 次。"""
    for _attempt in range(3):
        try:
            raw = _call_model(prompt, stop=None, json_mode=True)
        except Exception:
            # 网络/API 异常时重试
            continue
        if not raw:
            continue
        body = _extract_json(raw)
        if body:
            try:
                obj = json.loads(body)
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def _fallback_section(resume_text: str, module_key: str) -> str:
    """从简历原文提取对应模块内容，作为 LLM 解析失败/缺模块时的兜底。"""
    from .template import _parse_resume_text

    keywords = _FALLBACK_KW.get(module_key, [])
    if not keywords:
        return ""
    _personal, sections = _parse_resume_text(resume_text)
    for _title, _stype, content in sections:
        if any(kw in _title for kw in keywords) and content:
            return "\n".join(content)
    return ""


_ENTITY_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}"
    r"(?:公司|集团|科技|网络|有限|股份|大学|学院|学校|研究院|中学|"
    r"银行|事务所|中心|厂|局))"
)


def _has_original_entity(orig_text: str, out_text: str) -> bool:
    """检查模型输出是否保留了原文中的关键实体名（公司/学校等）。"""
    if not orig_text or not out_text:
        return True
    names = set(_ENTITY_RE.findall(orig_text))
    if not names:
        return True
    return any(name in out_text for name in names)


_CONTACT_LABEL_RE = re.compile(
    r"^(电话|手机|手机号|移动电话|邮箱|电子邮箱|邮件|Email|E-mail|Mail|"
    r"地址|所在地|现居地|微信|WeChat|QQ|Tel|Phone|e-mail)\s*[：:]\s*",
    re.IGNORECASE,
)


def _extract_basic_from_text(resume_text: str) -> Dict[str, str]:
    """LLM 漏返回姓名/联系方式/求职意向时的兜底：直接从简历原文提取。"""
    out: Dict[str, str] = {}
    text = resume_text or ""
    # 姓名：简历开头独立一行、2-4 个汉字的行优先；其次“姓名：xxx”
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    m = re.search(r"姓\s*名\s*[:：]\s*([\u4e00-\u9fa5·]{2,4})", text)
    if m:
        out["name"] = m.group(1)
    else:
        for ln in lines[:6]:
            if re.fullmatch(r"[\u4e00-\u9fa5·]{2,4}", ln) and not any(
                k in ln for k in ("姓名", "电话", "邮箱", "求职", "性别", "生日", "现居", "地址")
            ):
                out["name"] = ln
                break
    # 电话 / 邮箱 / 所在地
    phone = re.search(r"(?<!\d)(\+?\d[\d\- ]{6,15}\d)(?!\d)", text)
    email = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    loc = re.search(r"(现居|现居地|居住地|所在地|城市)\s*[:：]?\s*([\u4e00-\u9fa5·]{2,8})", text)
    parts = []
    if phone:
        parts.append(phone.group(1).strip())
    if email:
        parts.append(email.group(0))
    if loc:
        parts.append(loc.group(2))
    if parts:
        out["contact"] = " | ".join(parts)
    # 求职意向
    m = re.search(r"(求职意向|意向岗位|应聘岗位|目标岗位)\s*[:：]\s*([^\s|｜，,。]{2,20})", text)
    if m:
        out["job_title"] = m.group(2).strip()
    return out


def _clean_contact(contact: str) -> str:
    """清理联系方式：去掉“电话：”等标签前缀、去重、去除空段与多余分隔符。"""
    parts = []
    for p in (contact or "").split("|"):
        p = _CONTACT_LABEL_RE.sub("", p.strip())
        if p:
            parts.append(p)
    seen, result = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return " | ".join(result)


STRENGTH_RULES = {
    "保守": "保守模式：仅修正语病、统一表述、优化语序，不删减内容、不大幅改写，尽量贴近原文。",
    "均衡": "均衡模式：优化表达逻辑、强化成果导向、自然融入岗位关键词、小幅精简冗余表述。",
    "大胆": "大胆模式：深度重构表述、量化成果、大幅精简非核心内容、强力匹配岗位关键词。",
}


def _build_prompt(resume_text: str, job_description: str,
                  word_limits: Dict[str, dict],
                  strength: str = "均衡",
                  target_chars: int = 0) -> str:
    """构造结构化 JSON 优化提示词。word_limits: {module_key: {label, min_words, max_words}}。"""
    lines = [
        "你是一名专业的简历优化顾问。请根据「原始简历」和「目标岗位描述」，生成优化后的简历结构化内容。",
        STRENGTH_RULES.get(strength, STRENGTH_RULES["均衡"]),
        "严格要求：",
        "1. 只输出一个 JSON 对象，不要输出任何解释、前言或 Markdown 代码块标记。",
        "2. 保留简历中的真实信息（姓名、联系方式、教育、经历、技能、证书），禁止编造任何经历、技能、数字或成果。",
        "3. 姓名、电话、邮箱、所在地、学校名称、公司名称、职位名称、起止时间等客观信息必须与简历原文完全一致，"
        "不得修改或补充；简历原文没有的信息（如所在地）输出空字符串。",
        "10. 政治面貌（中共党员/共青团员/群众等）如原文有则原样提取到 political_status，没有则输出空字符串。",
        "4. 结合岗位描述，把与岗位最匹配的经历和技能写得更突出，使用专业、简洁的书面表达，多用强动词。",
        "5. 各模块内容必须控制在给定字数范围内。",
        "6. 工作经历/项目经历若有多个条目，用换行分隔。每个条目的第一行必须逐字保留原文的"
        "公司/组织名、职位、起止时间，不得改动或换词；只能改写其后的描述行（每行以 - 开头）。",
        "7. 姓名、联系方式、求职意向必须从简历原文提取，联系方式保留电话/邮箱，用 | 分隔。",
        "8. 模块定义：work_experience 只写公司/单位的工作或实习经历；projects 只写项目经历；"
        "campus_exp 只写校园、社团、学生会等经历；honor_cert 只写证书、荣誉、奖项；各模块不要互相复制内容。",
        "9. 如果某模块在简历中确实没有对应内容，该字段输出空字符串；禁止输出\"未提供\"\"没有找到\"等解释说明。",
        "10. 禁止编造用户简历中不存在的学历、学校、公司、经历、证书、奖项、技能或任何数字；"
        "简历没有的信息一律输出空字符串。",
        "11. 必须完整覆盖用户简历中的全部内容：教育背景、全部工作/实习经历、全部校园经历、"
        "所有技能与证书、所有荣誉奖项、自我评价，缺一不可；不得遗漏任何一条经历或证书。",
        "12. 只依据【原始简历】内容生成，禁止引用、复用或摘抄任何模板、示例或岗位描述中的"
        "具体学历、公司、案例、技能与奖项；岗位描述仅用于提炼匹配方向与关键词。",
        "13. 结合岗位描述删除与目标岗位明显无关的次要描述（保留事实本身），突出匹配岗位的能力与量化成果。",
        "14. 教育背景的主修课程必须完整保留（不省略、不概括为\"等\"）；学校、专业、学制、起止时间逐字保留。",
        "15. 每段经历的第一行（时间+公司/组织+岗位）逐字保留原文，不得改写或删除；"
        "量化成果（如销售额提升20%、处理数据10万+条）必须保留，不得丢失。",
        "16. 基础信息（姓名/年龄/性别/民族/出生年月/身高/籍贯/学历/专业/毕业院校/政治面貌/GPA/"
        "驾驶证等）必须逐字提取原文，禁止改写、增删、精简、编造；简历没有的输出空字符串。",
        "17. 证书与荣誉奖项（证书名称、等级、获奖时间、奖学金、竞赛奖项）原文完整保留，"
        "不删减、不润色、不新增。",
        "18. 兴趣爱好如简历中有则原样保留到 hobby 字段，没有则输出空字符串。",
        "19. 仅允许优化两类内容：①履历（实习/工作/校园经历）每条下方的工作描述话术，"
        "结合岗位JD强化匹配关键词、量化表达；②自我评价基于用户原自评重构表达。"
        "除此之外的所有文字必须与原文一致，禁止任何改写。",
        "",
        "各模块字数要求：",
    ]
    for key, meta in word_limits.items():
        lines.append(f"- {key}（{meta['label']}）：{meta['min_words']}-{meta['max_words']} 字")
    lines.append("")
    lines.append("JSON 结构如下（字段与上述模块一一对应）：")
    if target_chars > 0:
        lines.append(f"全文正文字数目标：约 {target_chars} 字（允许 ±10%），各模块按比例分配。")
    lines.append('{"name": "姓名", "age": "年龄", "gender": "性别", "nation": "民族",'
                 ' "birth_date": "出生年月", "height": "身高", "hometown": "籍贯",'
                 ' "school": "毕业院校", "major": "专业", "salary": "期望薪资",'
                 ' "arrive_time": "到岗时间", "gpa": "绩点",'
                 ' "education_degree": "学历",'
                 ' "contact": "电话 | 邮箱 | 所在地", "job_title": "求职意向",'
                 ' "political_status": "政治面貌",'
                 ' "hobby": "兴趣爱好",'
                 ' "campus_exp": "校园经历", "honor_cert": "证书荣誉",'
                 ' "match_score": 85,'
                 ' "matched_keywords": ["简历中命中岗位的关键词", ...],'
                 ' "missing_keywords": ["岗位要求但简历未体现的关键词", ...],'
                 ' "suggestions": ["1-2 条优化建议"],')
    keys = list(word_limits.keys())
    for i, key in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        lines.append(f'"{key}": "{word_limits[key]["label"]}内容"{comma}')
    lines.append("}")
    lines.append("")
    lines.append(f"【原始简历】\n{resume_text[:6000]}")
    lines.append("")
    lines.append(f"【目标岗位描述】\n{job_description[:2000]}")
    return "\n".join(lines)


def generate_structured_content(
    resume_text: str,
    job_description: str,
    word_limits: Dict[str, dict],
    strength: str = "均衡",
    target_chars: int = 0,
) -> Dict[str, str]:
    """根据模板字数配置，生成优化后的结构化简历内容 dict。

    - 基础字段：name / contact / job_title
    - 其余字段来自 word_limits 的 module_key（summary/work_experience/...）
    - 每个模块校验字数，超限截断至最后一个完整句子
    - LLM 解析失败或模块缺失时，从简历原文对应区块兜底
    """
    prompt = _build_prompt(resume_text, job_description, word_limits,
                           strength=strength, target_chars=target_chars)
    obj = _call_json(prompt)
    if obj is None:
        # LLM 彻底失败（超时/限流/非 JSON）：不静默降级为原文，
        # 交由上层明确提示用户重试
        raise RuntimeError("AI 模型调用失败（超时或返回异常）")

    result: Dict[str, str] = {"name": "", "age": "", "gender": "", "nation": "",
                              "birth_date": "", "height": "", "hometown": "",
                              "school": "", "major": "", "salary": "",
                              "arrive_time": "", "gpa": "",
                              "education_degree": "", "contact": "", "job_title": "",
                              "political_status": "", "hobby": "", "campus_exp": "",
                              "honor_cert": ""}
    for key in ("name", "age", "gender", "nation", "birth_date", "hometown",
                "height", "school", "major", "salary", "arrive_time", "gpa",
                "education_degree", "contact", "job_title",
                "political_status", "hobby", "campus_exp", "honor_cert"):
        result[key] = str(obj.get(key, "") or "").strip()
    result["contact"] = _clean_contact(result["contact"])
    # LLM 偶尔漏返回姓名/求职意向等基础字段：任一为空时从简历原文兜底提取
    if not result["name"] or not result["job_title"]:
        fallback = _extract_basic_from_text(resume_text)
        if not result["name"] and fallback.get("name"):
            result["name"] = fallback["name"]
        if not result["job_title"] and fallback.get("job_title"):
            result["job_title"] = fallback["job_title"]
    # 匹配度与关键词（供前端展示，非排版字段）
    for key in ("match_score", "matched_keywords", "missing_keywords", "suggestions"):
        result[key] = obj.get(key, "") if key in obj else ""

    # 姓名/求职意向属于基础字段（已由 LLM + 原文兜底处理），不参与模块字数兜底
    basic_keys = {"name", "job_title"}
    for module_key, meta in word_limits.items():
        if module_key in basic_keys:
            continue
        raw = ""
        if obj:
            raw = str(obj.get(module_key, "") or "").strip()
        if len(raw) < max(20, int(meta.get("min_words", 0)) // 2):
            # 内容明显不足 → 用简历原文对应区块兜底
            raw = _fallback_section(resume_text, module_key)
        max_words = int(meta.get("max_words", 300))
        result[module_key] = _truncate_to_limit(raw, max_words)

    # 保真校验：公司名/学校名等关键实体必须保留，否则该模块回退为原文，
    # 防止模型改写或编造客观信息（姓名/公司/职位/时间不可变）
    for module_key in ("work_experience", "projects", "education"):
        orig = _fallback_section(resume_text, module_key)
        out = result.get(module_key, "")
        if orig and out and not _has_original_entity(orig, out):
            print(f"[INFO] 模块 {module_key} 未保留原文关键实体，回退为原文内容")
            result[module_key] = orig

    # 教育保真：教育背景属「固定不变类」，直接使用原文完整内容
    # （学校/专业/时间/主修课程一字不改，符合规则「教育不可修改」）
    orig_edu = _fallback_section(resume_text, "education")
    if orig_edu and ("课程" in orig_edu):
        result["education"] = orig_edu
    elif orig_edu and not result.get("education"):
        result["education"] = orig_edu

    return result


def trim_content(
    data: Dict[str, str],
    job_description: str,
    target_chars_hint: int = 0,
) -> Dict[str, str]:
    """大模型定向精简：只对次要模块做表述压缩，严格保真，不触碰核心经历。

    返回 {module_key: 精简后文本}，仅包含有实质精简的模块。
    """
    prompt = (
        "你是简历精简助手。请对下面简历中的「自我评价、校园/项目经历、教育背景、专业技能」"
        "四个模块做定向精简，目标是在不丢失任何事实的前提下减少字数。\n"
        "严格禁止：\n"
        "1. 修改或删除公司/学校名称、时间、岗位/职位、量化数据、证书名称、核心成果；\n"
        "2. 新增任何不存在的经历、技能、数字；\n"
        "3. 触碰「工作经历/实习经历」模块（完全不要输出该模块）。\n"
        "允许：合并冗余句子、删除修饰性形容词、删除非核心细节、长句拆分、压缩课程列表。\n"
        "模块精简优先级（高→低）：自我评价 → 校园/项目经历 → 教育背景(主修课程) → 专业技能。\n"
    )
    if target_chars_hint > 0:
        prompt += f"目标：整体减少约 {target_chars_hint} 字。\n"
    prompt += (
        "只输出 JSON 对象，字段为模块名，值为精简后的文本；没有精简的模块不输出。"
        "模块名与内容对应关系：summary=自我评价, projects=校园/项目经历, "
        "education=教育背景, skills=专业技能。\n"
        "输入简历内容：\n"
        + json.dumps(
            {k: data.get(k, "") for k in ("summary", "projects", "education", "skills")},
            ensure_ascii=False,
        )
        + "\n岗位描述：" + (job_description or "")[:500]
    )
    obj = _call_json(prompt)
    if not obj:
        return {}
    allowed = {"summary", "projects", "education", "skills"}
    result = {}
    for key in allowed:
        new_val = str(obj.get(key, "") or "").strip()
        old_val = (data.get(key) or "").strip()
        # 只接受确有精简且仍保留内容的结果
        if new_val and old_val and len(new_val) < len(old_val):
            result[key] = new_val
    return result


def optimize_section(kind: str, text: str, job_description: str = "") -> str:
    """AI 优化单个板块（编辑器用）。
    kind: work（工作/实习经历）| campus（校园经历）| self（自我评价）。
    - work/campus：第一行（时间+公司/组织+岗位）逐字保留，只优化描述行；
    - self：基于原文重构表达，贴合 JD，不编造。
    """
    kind = (kind or "work").strip().lower()
    text = (text or "").strip()
    if not text:
        return ""
    if kind == "self":
        prompt = (
            "你是一名专业的简历优化顾问。请基于下面的「原始自我评价」重构表达，"
            "贴合目标岗位JD，突出匹配能力与亮点。\n"
            "严格要求：\n"
            "1. 底层事实必须来自原文，禁止编造不存在的能力、经历、数字；\n"
            "2. 表达专业简洁，控制在 100-200 字；\n"
            "3. 只输出优化后的自我评价文本，不要任何解释或标记。\n"
            f"【目标岗位JD】\n{job_description[:800]}\n\n"
            f"【原始自我评价】\n{text}"
        )
    else:
        prompt = (
            "你是一名专业的简历优化顾问。请优化下面的"
            + ("校园/社团经历" if kind == "campus" else "工作/实习经历")
            + "描述，结合目标岗位JD强化匹配关键词与量化表达。\n"
            "严格要求：\n"
            "1. 第一行（时间+公司/组织+岗位/职务）必须逐字保留，不得修改；\n"
            "2. 只改写其后的描述行（每行以 - 开头），保留事实与量化数据，"
            "不得编造新的经历、数字、成果；\n"
            "3. 输出格式与输入一致：第一行原文，后续每行以 - 开头。\n"
            f"【目标岗位JD】\n{job_description[:800]}\n\n"
            f"【原始经历】\n{text}"
        )
    try:
        result = _call_model(prompt, stop=None)
    except Exception:
        return text
    result = (result or "").strip()
    return result if result else text


# ══════════════════ 简历经历 + 自我评价 优化（两版本提示词） ══════════════════

EXPERIENCE_SELF_FULL_PROMPT = """角色定位：拥有8年企业招聘HR经验+资深简历定制师，熟知国内各大公司ATS简历筛选系统关键词抓取逻辑，擅长精准贴合招聘需求打磨简历内容，只务实优化、绝不虚构编造履历。

硬性执行铁律（必须严格遵守，不可擅自改动）
1. 简历固定保留内容：个人信息、求职意向、教育背景、专业课程、资格证书、软件技能板块全部原样照搬，一字不改、不删减、不新增；
2. 本次仅负责两大模块优化：①实习/全职工作/项目经历 ②自我评价，除此以外所有内容均不调整；
3. 严禁捏造不存在的数据、项目、工作内容、业绩，只能基于我给出的原始文字深挖、提炼、重组、量化；

第一步：先输出JD深度拆解内容
1. 拆分岗位职责：梳理岗位每日、每月核心工作事项；
2. 提取任职要求：硬性门槛、必备专业能力、办公工具、软素质；
3. 标注ATS核心检索关键词（系统筛选简历的重点词汇，后续需要自然融入经历）；
4. 区分：刚需能力 / 加分能力；

第二步：工作&实习经历优化细则
1. 经历排序调整：和JD匹配度最高的经历置顶，关联性弱的往后排布；
2. 句式统一规范：统一采用「动词开头+工作内容+执行动作+落地结果」结构；
3. 全面套用STAR法则改写：场景背景→承接任务→自身具体行动→最终量化成果；
4. 量化落地：所有内容尽可能补充数字（效率提升百分比、处理文件份数、对接部门数量、耗时缩减、差错率、统筹场次、整理资料体量等），无直观数据就描述工作价值、流程优化效果；
5. 关键词植入：将JD提取的专业词汇、工具名称、业务术语自然融入段落，不生硬堆砌；
6. 剔除流水账空话：删掉"负责日常工作、协助领导做事、完成交代任务"这类无效表述；
7. 内容取舍：弱化和岗位无关的琐碎工作，重点放大适配岗位的工作细节；

第三步：自我评价撰写规则
1. 篇幅控制：3-4句话，简洁凝练，杜绝长篇大论；
2. 紧扣JD创作：依次概括：适配岗位的专业能力+过往相关工作经验+沟通/细心/抗压等适配软实力+工作处事风格；
3. 摒弃万能套话：不写性格乐观、吃苦耐劳、学习能力强这类空洞语句，全部结合岗位需求具象化；
4. 精准体现匹配度，让HR一眼看出适配该岗位；

整体文风要求
私企/互联网：简洁干练、偏结果导向；国企/事业单位：措辞严谨稳重、规整正式；文职/职能岗：细致柔和；技术支撑岗：务实严谨。

输出格式：
一、JD全方位拆解分析
二、优化后的实习/工作经历
三、全新定制自我评价

本次输入已直接给出，请按上述格式直接输出结果，不要提问、不要要求补充材料、不要输出任何开场白或结束语。"""


def _call_ollama_long_text(prompt: str) -> str:
    """调用本地 Ollama 模型并返回完整长文本。

    - Ollama 走标准 OpenAI 兼容协议，输出长度参数为 max_tokens；
    - deepseek-r1 系列会把思考过程以 <think>...</think> 混在正文里，需剥离；
    - 只去除思考标签与代码块围栏，不截断内容。
    """
    kwargs = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    t0 = _time.monotonic()
    try:
        resp = ollama_client.chat.completions.create(timeout=300, **kwargs)
        content = resp.choices[0].message.content or ""
        applog.log("llm_call", model=OLLAMA_MODEL, json_mode=False,
                   duration_ms=round((_time.monotonic() - t0) * 1000),
                   chars=len(content))
    except Exception as exc:  # noqa: BLE001
        applog.log("llm_error", model=OLLAMA_MODEL, json_mode=False,
                   duration_ms=round((_time.monotonic() - t0) * 1000),
                   error=str(exc)[:200])
        raise
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    if "```" in content:
        parts = content.split("```")
        content = " ".join(p for p in parts if not p.strip().lower().startswith(("response", "json")))
    return content.strip()


def optimize_experience_self(jd: str, experience: str, self_evaluate: str = "",
                             mode: str = "full", extra: str = "") -> str:
    """「简历经历 + 自我评价」优化：仅优化经历与自我评价，其余内容分毫不动。
    统一由本地 Ollama 模型驱动；mode 参数仅为兼容旧调用保留、不再区分版本。
    返回：JD拆解 + 优化后经历 + 定制自我评价 三部分文本。"""
    jd = (jd or "").strip()
    experience = (experience or "").strip()
    self_evaluate = (self_evaluate or "").strip()
    extra = (extra or "").strip()
    if not jd or not experience:
        return ""
    if not self_evaluate:
        self_evaluate = "（暂无，可跳过自我评价部分）"
    prompt = EXPERIENCE_SELF_FULL_PROMPT + "\n\n【本次输入】\n" \
        "1. 完整招聘JD全文（岗位职责+任职要求）：\n" + jd + "\n\n" \
        "2. 简历原始工作/实习经历原文：\n" + experience + "\n\n" \
        "3. 原本的自我评价内容：\n" + self_evaluate
    if extra:
        prompt += "\n\n4. 补充信息（求职行业/应届或社招/是否转行等）：\n" + extra
    return _call_ollama_long_text(prompt)


# ── 整份简历 AI 生成（用户原始目标：一句话 / JD → 完整简历） ──
FULL_RESUME_PROMPT = """你是一位资深简历顾问与 HR。根据用户提供的少量信息，生成一份完整、专业、可直接用于求职的中文简历内容。
严格要求：
1. 只输出一个 JSON 对象，不要任何解释、前言、Markdown 代码块标记。
2. JSON 结构（字段缺失时基于求职意向合理推断填充；但用户明确给出的姓名/电话/邮箱/学校/公司/岗位等实体必须严格保留原样，禁止编造或更改）：
{
  "basic": {
    "name":"姓名","gender":"男/女","age":"年龄(纯数字,如 26)","phone":"手机","email":"邮箱",
    "city":"现居城市","education_degree":"学历(如 本科/硕士)","school":"毕业院校","major":"专业",
    "intention_job":"求职意向","salary":"期望薪资(可空)","political_status":"政治面貌(可空)",
    "nation":"民族(可空)","hometown":"籍贯(可空)","wechat":"微信(可空)"
  },
  "modules": {
    "education_info": [ {"school":"院校","major":"专业","degree":"学历层次","start":"2018.09","end":"2022.06","current":false,"content":"<ul><li>主修课程/成绩/校园亮点</li></ul>"} ],
    "work_history": [ {"company":"公司","position":"职位","start":"2022.07","end":"2024.06","current":false,"content":"<p>用 2-4 条 <li> 量化描述工作内容与成果（含数据）</p>"} ],
    "internship_info": [ {"company":"","position":"","start":"","end":"","current":false,"content":"<p>实习内容与收获</p>"} ],
    "projects": [ {"name":"项目名称","role":"担任角色","period":"2023.01-2023.06","content":"<p>项目描述与你的贡献</p>"} ],
    "campus_exp": [ {"name":"经历名称","role":"角色","period":"","content":"<p>校园/社团经历</p>"} ],
    "skill_info": [ {"name":"技能名","level":"熟练/精通(可空)","content":"补充(可空)"} ],
    "honor_cert": [ {"name":"证书/荣誉名","time":"2023(可空)","issuer":"颁发机构(可空)"} ],
    "self_evaluate": "2-4 句专业自我评价，突出核心优势与目标岗位匹配度",
    "hobby": ["兴趣1","兴趣2"],
    "custom": ""
  }
}
3. content 字段使用 <p> / <li> 等简单 HTML 标签，便于富文本展示；描述用动词开头、量化成果。
4. 若用户信息不足，基于求职意向合理虚构一份完整、连贯、无空板块的样例简历（hobby 给 2-3 个即可）。
5. 语言：简体中文，专业、简洁、不夸大、不编造用户未提供的客观事实。
"""


def _call_glm_json(prompt: str) -> str:
    """调用智谱 GLM 并原样返回文本（用于 JSON 生成）。"""
    kwargs = {
        "model": GLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 5000,
    }
    t0 = _time.monotonic()
    try:
        resp = glm_client.chat.completions.create(timeout=180, **kwargs)
        content = resp.choices[0].message.content or ""
        applog.log("llm_call", model=GLM_MODEL, json_mode=True,
                   duration_ms=round((_time.monotonic() - t0) * 1000), chars=len(content))
        return content.strip()
    except Exception as exc:  # noqa: BLE001
        applog.log("llm_error", model=GLM_MODEL, json_mode=True,
                   duration_ms=round((_time.monotonic() - t0) * 1000), error=str(exc)[:200])
        raise


def generate_full_resume(description: str, jd: str = "", target_job: str = "") -> Optional[dict]:
    """根据一句话描述 / JD / 目标岗位，生成整份简历结构化内容（basic + modules）。失败返回 None。"""
    desc = (description or "").strip()
    jd = (jd or "").strip()
    target_job = (target_job or "").strip()
    if not (desc or jd or target_job):
        return None
    user_parts = []
    if target_job:
        user_parts.append("求职意向 / 目标岗位：" + target_job)
    if desc:
        user_parts.append("个人情况描述：\n" + desc)
    if jd:
        user_parts.append("招聘要求（JD）：\n" + jd)
    user_parts.append("\n请基于以上信息生成完整简历 JSON。")
    prompt = FULL_RESUME_PROMPT + "\n\n" + "\n".join(user_parts)
    last_err = ""
    for _ in range(3):
        try:
            raw = _call_glm_json(prompt)
        except Exception as exc:
            last_err = str(exc)
            continue
        if not raw:
            continue
        body = _extract_json(raw)
        if not body:
            last_err = "模型未返回 JSON"
            continue
        try:
            obj = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            last_err = "JSON 解析失败"
            continue
        if isinstance(obj, dict) and (obj.get("basic") or obj.get("modules")):
            return _normalize_generated_resume(obj)
        last_err = "返回结构不完整"
    if last_err:
        applog.log("ai_generate_fail", error=last_err[:200])
    return None


def _normalize_generated_resume(obj: dict) -> dict:
    """把模型输出规范化为编辑器可用的结构，补缺字段、修正类型。"""
    basic = obj.get("basic") or {}
    if not isinstance(basic, dict):
        basic = {}
    modules = obj.get("modules") or {}
    if not isinstance(modules, dict):
        modules = {}
    arr_keys = ["education_info", "work_history", "internship_info", "projects",
                "campus_exp", "skill_info", "honor_cert", "hobby"]
    for k in arr_keys:
        v = modules.get(k)
        modules[k] = v if isinstance(v, list) else []
    for rec in modules.get("work_history", []) + modules.get("internship_info", []):
        if isinstance(rec, dict) and not isinstance(rec.get("current"), bool):
            rec["current"] = bool(rec.get("current"))
    if not isinstance(modules.get("self_evaluate"), str):
        modules["self_evaluate"] = "" if modules.get("self_evaluate") is None else str(modules.get("self_evaluate"))
    if not isinstance(modules.get("custom"), str):
        modules["custom"] = ""
    return {"basic": basic, "modules": modules}
