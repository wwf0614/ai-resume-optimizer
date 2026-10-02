"""系统标准字段/板块库：简历跨模板自动迁移的唯一基准。

所有用户简历提取内容统一映射到这里的标准 key，模板板块标题通过别名
绑定到标准板块 key，实现「一套映射逻辑兼容海量差异化模板」。
"""
import re

# ── 基础信息标准字段 ──
BASIC_FIELDS = {
    "name": "姓名",
    "age": "年龄",
    "gender": "性别",
    "nation": "民族",
    "birth_date": "出生年月",
    "height": "身高",
    "hometown": "籍贯",
    "education_degree": "学历",
    "major": "专业",
    "salary": "期望薪资",
    "arrive_time": "到岗时间",
    "gpa": "绩点",
    "hobby": "兴趣爱好",
    "phone": "手机号",
    "email": "邮箱",
    "wechat": "微信",
    "address": "详细地址",
    "school": "毕业院校",
    "intention_job": "求职意向",
    "city": "现居城市",
    "political_status": "政治面貌",
}

# ── 大模块标准板块 ──
MODULES = {
    "education_info": "教育背景",
    "work_history": "工作履历",
    "skill_info": "技能合集",
    "campus_exp": "校园经历",
    "honor_cert": "证书荣誉",
    "self_evaluate": "自我评价",
}

# 板块标题别名 → 标准板块 key（同义词全局库，可后台扩展）
SECTION_ALIASES = {
    "work_history": [
        "工作经验", "工作经历", "实习经历", "实习经验", "工作履历", "职业经历",
        "工作实践", "实践经历", "工作及实践经历", "工作&实践经历", "工作与实习经历",
        "工作经历及实习经历", "工作经验及实习经历", "职业履历", "运营推广经历",
        "运营经历", "推广经历", "销售经历", "工作及实习", "实习及工作经历",
        "项目工作经历", "工作项目经历", "主要经历",
    ],
    "skill_info": [
        "职业技能", "专业技能", "技能特长", "技能证书", "专业能力", "技能",
        "证书及技能", "技能与证书", "技能证书及荣誉", "专业与技能",
    ],
    "education_info": [
        "教育背景", "教育经历", "教育情况", "教育", "学历背景", "Education",
    ],
    "campus_exp": [
        "校园经历", "校园实践", "学生工作", "社会实践", "校园活动", "校内经历",
        "在校经历", "社团经历", "校园及社团经历",
    ],
    "honor_cert": [
        "证书荣誉", "荣誉证书", "获奖经历", "奖项荣誉", "荣誉奖项", "所获荣誉",
        "证书及荣誉", "奖项与证书", "技能证书及荣誉", "获奖情况", "个人荣誉",
    ],
    "self_evaluate": [
        "自我评价", "个人评价", "个人优势", "自我简介", "自我描述", "个人简介",
        "关于我", "自我介绍", "Assessment",
    ],
}

# 基础信息行标签别名 → 标准字段 key
FIELD_ALIASES = {
    "name": ["姓名", "姓    名", "姓 名", "名字", "name", "NAME"],
    "age": ["年龄", "年    龄", "岁数"],
    "gender": ["性别", "性    别"],
    "nation": ["民族", "民    族"],
    "birth_date": ["出生年月", "出生日期", "出    生年月", "出生年月日", "生日", "生    日"],
    "height": ["身高", "身    高"],
    "hometown": ["籍贯", "籍    贯", "户籍所在地"],
    "education_degree": ["学历", "学    历", "最高学历"],
    "major": ["专业", "主修专业", "所学专业", "专    业"],
    "salary": ["期望薪资", "期望月薪", "薪资要求"],
    "arrive_time": ["到岗时间", "入职时间"],
    "gpa": ["GPA", "gpa", "绩点"],
    "hobby": ["兴趣爱好", "爱好", "特长爱好"],
    "phone": ["手机", "电话", "手机号", "联系电话", "手机号码", "联系方式",
              "手    机", "电    话"],
    "email": ["邮箱", "电子邮件", "电子邮箱", "邮件", "E-mail", "Email", "邮    箱"],
    "wechat": ["微信", "微信号", "WeChat", "个人微信", "微    信"],
    "address": ["地址", "详细地址", "住址", "家庭住址", "地    址"],
    "school": ["毕业院校", "学校", "毕业学校", "院校", "学    校"],
    "intention_job": ["求职意向", "意向岗位", "期望职位", "应聘岗位", "求职岗位"],
    "city": ["现居城市", "现居地", "现居", "现居地址", "城市", "所在地",
             "居住地", "现居住地"],
    "political_status": ["政治面貌"],
}

# 标准字段/板块 → 中文释义（供配置界面展示）
ALL_KEYS = {**BASIC_FIELDS, **MODULES}

_ALIAS_CACHE = None


def _merged_aliases():
    """内置同义词 + 数据库同义词（后台维护，全平台生效）。"""
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE
    sections = {k: list(v) for k, v in SECTION_ALIASES.items()}
    fields = {k: list(v) for k, v in FIELD_ALIASES.items()}
    try:
        from . import db
        for row in db.list_aliases():
            target = sections if row["kind"] == "section" else fields
            target.setdefault(row["std_key"], [])
            if row["alias"] not in target[row["std_key"]]:
                target[row["std_key"]].append(row["alias"])
    except Exception:
        pass
    _ALIAS_CACHE = (sections, fields)
    return _ALIAS_CACHE


def refresh_aliases() -> None:
    """后台增删同义词后调用，使新别名立即生效。"""
    global _ALIAS_CACHE
    _ALIAS_CACHE = None


def find_section_key(text: str):
    """按别名匹配板块标题文字，返回标准板块 key；无匹配返回 None。"""
    t = (text or "").strip().replace(" ", "").strip("·•。，,.:：、-—_ ").lower()
    if not t:
        return None
    for key, aliases in _merged_aliases()[0].items():
        for a in aliases:
            if t == a.replace(" ", "").lower():
                return key
    return None


def find_field_key(text: str):
    """按别名匹配基础字段行标签（label 部分），返回标准字段 key；无匹配返回 None。"""
    t = (text or "").strip().replace(" ", "").strip("·•。，,.:：、-—_ ").lower()
    if not t:
        return None
    for key, aliases in _merged_aliases()[1].items():
        for a in aliases:
            if t == a.replace(" ", "").lower():
                return key
    return None


def build_standard_content(result: dict) -> dict:
    """把 LLM 结构化结果转成系统标准字段字典（供映射填充使用）。

    result 使用现有提取键：name/age/education_degree/contact/job_title/
    political_status/campus_exp/honor_cert + 模板模块键
    （work_experience/education/skills/summary/projects）。
    """
    contact = str(result.get("contact") or "")
    parts = [p.strip() for p in re.split(r"[|｜]", contact) if p.strip()]
    phone_m = re.search(r"\+?[\d\- ]{7,16}", contact)
    email_m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", contact)
    city = ""
    if parts:
        # 联系方式里既不是电话也不是邮箱的剩余段视为所在地/城市
        for p in parts:
            if not phone_m or p != phone_m.group(0).strip():
                if not email_m or p != email_m.group(0).strip():
                    city = p
                    break

    return {
        "name": str(result.get("name") or "").strip(),
        "age": str(result.get("age") or "").strip(),
        "gender": str(result.get("gender") or "").strip(),
        "nation": str(result.get("nation") or "").strip(),
        "birth_date": str(result.get("birth_date") or "").strip(),
        "height": str(result.get("height") or "").strip(),
        "hometown": str(result.get("hometown") or "").strip(),
        "education_degree": str(result.get("education_degree") or "").strip(),
        "major": str(result.get("major") or "").strip(),
        "salary": str(result.get("salary") or "").strip(),
        "arrive_time": str(result.get("arrive_time") or "").strip(),
        "gpa": str(result.get("gpa") or "").strip(),
        "hobby": str(result.get("hobby") or "").strip(),
        "phone": phone_m.group(0).strip() if phone_m else "",
        "email": email_m.group(0).strip() if email_m else "",
        "wechat": str(result.get("wechat") or "").strip(),
        "address": str(result.get("address") or "").strip(),
        "school": str(result.get("school") or "").strip(),
        "intention_job": str(result.get("job_title") or "").strip(),
        "city": city or str(result.get("city") or "").strip(),
        "political_status": str(result.get("political_status") or "").strip(),
        "education_info": str(result.get("education") or "").strip(),
        "work_history": str(result.get("work_experience") or "").strip(),
        "skill_info": str(result.get("skills") or "").strip(),
        "campus_exp": str(result.get("campus_exp") or result.get("projects") or "").strip(),
        "honor_cert": str(result.get("honor_cert") or "").strip(),
        "self_evaluate": str(result.get("summary") or "").strip(),
    }
