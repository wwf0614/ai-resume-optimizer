"""质量引擎 Phase 1 冒烟测试：验证 match_score 返回结构正确。"""
import json
import sys
from pathlib import Path

# 让 quality 包可被导入（运行目录为 resume_optimizer）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quality.match_score import match_score  # noqa: E402

SAMPLE_PROFILE = {
    "basic": {
        "name": "张三",
        "city": "贵阳",
        "education_degree": "本科",
        "school": "贵州大学",
        "major": "计算机科学与技术",
        "intention_job": "后端开发工程师",
    },
    "modules": {
        "work_history": [
            {
                "company": "某科技公司",
                "position": "后端开发",
                "content": "<p>使用 Python 与 FastAPI 开发 RESTful API；基于 MySQL 与 Redis 做数据存储与缓存；使用 Docker 容器化部署。</p>",
            }
        ],
        "projects": [
            {
                "name": "智能简历系统",
                "role": "核心开发",
                "content": "<p>基于 GPT 的简历优化流水线，负责后端服务与数据库设计。</p>",
            }
        ],
        "skill_info": [
            {"name": "Python", "level": "熟练"},
            {"name": "FastAPI", "level": "熟练"},
            {"name": "MySQL", "level": "熟悉"},
            {"name": "Docker", "level": "熟悉"},
        ],
        "self_evaluate": "两年后端开发经验，熟悉 Python 服务端开发与云原生部署。",
    },
}

JD = (
    "岗位：高级后端开发工程师。要求：5 年以上 Python 后端经验，精通 FastAPI / Django，"
    "熟悉 MySQL、Redis、Kafka，了解 Kubernetes 与微服务架构，有高并发系统设计经验。"
)

if __name__ == "__main__":
    print(">>> 测试 1：真实档案 + JD（尝试走 GLM，失败回退确定性）")
    r1 = match_score(SAMPLE_PROFILE, "", JD)
    print(json.dumps(r1, ensure_ascii=False, indent=2))

    print("\n>>> 测试 2：空档案 + JD（应走回退/低分）")
    r2 = match_score({}, "前端工程师", "要求精通 React、TypeScript、webpack")
    print(json.dumps(r2, ensure_ascii=False, indent=2))

    # 基本结构断言
    assert isinstance(r1["total_score"], int) and 0 <= r1["total_score"] <= 100
    assert set(r1["dimensions"].keys()) == {"technical", "experience", "behavioral", "career"}
    assert r1["recommendation"] in {
        "strong_fit", "good_fit", "moderate_fit", "weak_fit", "poor_fit"
    }
    print("\n[OK] match_score 结构校验通过")
