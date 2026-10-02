"""质量引擎 GLM 提示词模板（均走智谱 GLM-4.7-Flash）。"""

# 匹配度评分：四维语义打分 + 关键词提取
MATCH_SCORE_PROMPT = """你是一名资深招聘顾问。请根据【候选人档案】与【目标岗位JD】，评估该候选人与岗位的匹配度。

严格要求：
1. 只输出一个 JSON 对象，不要任何解释、前言或 Markdown 代码块标记。
2. 从以下四个维度打分（0-100，整数）：
   - technical：技术/技能匹配度（岗位硬性技能要求与候选人技能、经历的重合）
   - experience：经验匹配度（过往工作/项目经历与岗位职能的相关程度，看职能本质而非字面职位名）
   - behavioral：行为/文化契合度（岗位文化、协作方式、软素质要求与候选人展现特质的契合）
   - career：职业契合度（该岗位是否契合候选人职业方向与成长）
3. 提取 matched_keywords（岗位要求中候选人确实具备的关键词，最多 10 个）与
   missing_keywords（岗位要求但候选人档案未体现的，最多 10 个）。
4. strengths：2-3 条该岗位下的核心匹配优势（简述）。gaps：1-3 条需弥补的缺口。
5. 必须严格依据【候选人档案】内容判断，禁止臆测档案中没有的能力；档案未体现即视为 missing。

JSON 结构：
{
  "technical": 0, "experience": 0, "behavioral": 0, "career": 0,
  "matched_keywords": ["关键词"],
  "missing_keywords": ["关键词"],
  "strengths": ["..."],
  "gaps": ["..."]
}

【候选人档案】
{profile}

【目标岗位JD】
{jd}
"""
