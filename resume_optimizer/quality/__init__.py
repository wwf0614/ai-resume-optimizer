"""智简历「质量引擎」模块。

从 ai-job-search 仓库提炼的四项能力，移植进智简历产品：
- 匹配度评分（免费引流）：match_score
- 事实核查审计（VIP）：grounding_audit  [Phase 3]
- 双 Agent 审查（VIP）：dual_review     [Phase 4]
- ATS 文本层校验（免费）：ats_check      [Phase 2]

引擎：保持智谱 GLM，工作流逻辑用 Python/FastAPI 复刻，零 Claude Code 依赖。
真相源：用户在编辑器填好的结构化档案（basic + modules），AI 输出不得超出。
"""
