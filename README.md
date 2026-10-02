# 智简历 · AI 简历优化系统

基于 FastAPI + LLM 的本地部署 AI 简历优化系统：上传简历（Word / PDF / txt / 图片）与目标岗位 JD，AI 自动提取并优化简历内容，套用 Word 简历模板生成排版完好的简历，支持导出 Word / PDF。核心设计是将「简历内容」与「模板版式」解耦（标准字段库 + 板块-字段映射），并配套模板管理后台。

## 功能特性

- **简历解析**：支持 Word / PDF / txt / 图片（Tesseract OCR），自动提取教育、经历、技能等标准字段
- **AI 优化**：多模型协作 —— 小米 MiMo（内容优化主模型）、智谱 GLM（编辑器 AI 生成）、本地 Ollama deepseek-r1（经历/自我评价润色）
- **模板系统**：Word 模板上传、审核、体检、板块-字段映射配置的管理后台；18 套内置模板
- **在线编辑器**：Vue3 所见即所得编辑器，支持 AI 生成与实时预览
- **照片处理**：证件照人脸检测裁剪（OpenCV YuNet）
- **质量评估**：ATS 简历体检、岗位匹配度打分（jieba 分词）
- **导出**：Word / PDF 导出，简历内容与版式完全分离

## 技术栈

| 分类 | 技术 |
| --- | --- |
| 后端 | FastAPI + Uvicorn、Pydantic |
| 数据库 | MySQL 8（PyMySQL） |
| LLM | OpenAI 兼容 SDK（MiMo / 智谱 GLM / 本地 Ollama） |
| 文档处理 | python-docx（OOXML 级操作）、PyMuPDF、pdfplumber、pdf2docx、docx2pdf |
| 图像 | Pillow、OpenCV（YuNet 人脸检测）、Tesseract OCR |
| 前端 | 原生 HTML/CSS/JS + Vue3 编辑器 |

## 项目结构

```
├── resume_optimizer/          # 主应用
│   ├── main.py                # FastAPI 入口（全部路由与鉴权）
│   ├── requirements.txt
│   ├── .env.example           # 配置模板（复制为 .env 使用）
│   ├── 启动.bat / 停止.bat     # Windows 一键启停
│   ├── utils/                 # 核心模块：db/auth/parser/converter/llm/
│   │   │                      #   photo/filler/section_mapper/standard_keys/
│   │   │                      #   reflow/template_render/validator ...
│   │   ├── templates/         # Word 模板库
│   │   └── models/            # ONNX 模型（人脸检测）
│   ├── quality/               # ATS 检查、岗位匹配打分
│   ├── static/                # 前端页面
│   └── editor_app/            # Vue3 在线编辑器源码
├── auto_test/                 # 批量回归测试脚本
└── 项目技术说明.md            # 架构与实现说明
```

## 快速开始

### 环境要求

- Python 3.9+、MySQL 8
- （PDF 导出）本机安装 Microsoft Word —— `docx2pdf` 依赖 Word COM 组件
- （OCR）安装 [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) 并配置中文语言包
- （本地模型，可选）安装 Ollama 并拉取 `deepseek-r1:1.5b`

### 部署步骤

```bash
# 1. 安装依赖
cd resume_optimizer
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：填入 LLM API Key、数据库密码、管理员密码

# 3. 初始化数据库（在 MySQL 中创建 .env 里配置的库后）
python -c "from utils import db"   # 或按 .env 配置执行建表

# 4. 启动
python main.py                     # 或 Windows 下双击 启动.bat
```

访问 <http://localhost:8000>。

### 环境变量说明（.env）

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 内容优化主模型的 Key 与接口地址（OpenAI 兼容格式） |
| `GLM_API_KEY` | 智谱 GLM Key（编辑器 AI 生成） |
| `OLLAMA_BASE_URL` | 本地 Ollama 地址（默认 <http://localhost:11434>） |
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接配置 |
| `ADMIN_PASSWORD` | 管理后台管理员密码 |

## 说明

- `.env`、运行时预览/日志、模板素材等本地资料不入库（见 `.gitignore`）
- `editor_app/` 修改后需构建并同步到 `static/`；`static/_archive/` 保留了历史版本
- 本项目仅用于学习与个人求职辅助
