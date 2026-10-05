# 智简历 · 简历优化系统

基于 FastAPI + LLM 的本地部署 AI 简历生成与优化平台。核心设计是**「简历内容」与「版式模板」彻底分离**：求职者专注填写真实经历，AI 负责打磨表达，系统负责排版与导出；换模板不丢内容，一键导出 Word / PDF / 长图。全部服务可运行在一台普通 Windows 电脑上，AI 能力由本地大模型驱动，**简历数据不出本机**。

## 功能特性

### 可视化编辑器（三栏所见即所得）

- **统一 JSON 数据模型**：简历 = 内容（basic/modules/order/hidden）+ 主题（theme）；版式与配色只是渲染层皮肤，**更换模板内容零丢失**
- **左栏内容表单**：教育/实习/工作/项目/校园/技能/荣誉/自我评价/兴趣爱好等模块，条目增删、上下移动、拖拽排序、模块显隐
- **中间 A4 实时预览**（794×1123，与打印同尺度）：支持**点击直改**，页面上直接编辑文字，与表单双向同步
- **右栏设计面板**：4 种版式族（单栏经典/左侧栏/顶部横幅/双栏紧凑）、7 种配色 + 自定义主色、5 种字体、字号/行距/姓名字号/模块间距/版心留白滑杆、标题样式、头像（方框/圆框/大小）
- **年月选择面板**：所有时间段字段点选 `« 年份 »` + 十二宫格，起止双框、单选一侧即单值，兼容旧文本
- **双通道自动保存**：浏览器本地兜底 + 云端草稿 3 秒同步，旧格式草稿自动迁移；登录即可用，无 VIP 门禁

### 导出体系

- **结构化导出**：统一 JSON → 生成排版干净的 Word（主题色/字体/字号/间距全映射）→ PDF → 纵向拼接 PNG 长图
- **模板保真链路**：Word 模板解析为带坐标的编辑盒子（PDF 渲染校准定位），就地替换文字完整保留原格式，内容变长自动启用「缩小字体填充」防溢出，导出与预览像素级一致

### AI 能力

- **JD 拆解 + 经历 STAR 量化改写 + 自我评价定制**（本地 Ollama，数据不出本机）
- **ATS 简历体检**、**岗位匹配度打分**（免费功能）

### 管理后台

- 模板上传 / 批量导入 / 审核上架 / 编辑器可用性开关 / 批量管理，操作留痕
- **可视化模板编辑器**：整页底图 + 盒子图层，拖拽移动、八向缩放、增删文本框、调字体颜色对齐、开关可编辑；保存后布局覆盖**即时生效**于用户编辑器，新增盒子在导出时以真实 wps 文本框注入 Word
- 重置覆盖一键回滚模板布局

## 技术栈

| 分类 | 技术 |
| --- | --- |
| 后端 | FastAPI + Uvicorn、Pydantic |
| 数据库 | MySQL 8（PyMySQL） |
| LLM | OpenAI 兼容 SDK（MiMo / 智谱 GLM / 本地 Ollama） |
| 文档处理 | python-docx（OOXML 级操作）、PyMuPDF、pdfplumber、pdf2docx、docx2pdf |
| 图像 | Pillow、OpenCV（YuNet 人脸检测）、Tesseract OCR |
| 前端 | 原生 HTML/CSS/JS（参数化渲染引擎 + 自研交互组件，无重型框架） |

## 项目结构

```
├── resume_optimizer/            # 主应用
│   ├── main.py                  # FastAPI 入口（路由/鉴权/导出/结构合并）
│   ├── requirements.txt
│   ├── .env.example             # 配置模板（复制为 .env 使用）
│   ├── 启动.bat / 停止.bat       # Windows 一键启停
│   ├── utils/
│   │   ├── template_editor.py   # 模板盒子解析 / 文本写回 / 新增盒子注入
│   │   ├── resume_docx.py       # 结构化简历 → Word 生成器 + PDF→PNG 长图
│   │   ├── db.py / auth.py / parser.py / converter.py / llm.py / ...
│   │   └── templates/           # Word 模板库
│   ├── static/
│   │   ├── editor.html + editor-v3.js/.css   # 三栏编辑器
│   │   ├── resume-render.js/.css             # 参数化 A4 渲染引擎
│   │   ├── template-editor.html              # 管理端可视化模板编辑器
│   │   └── admin.html                        # 管理后台
│   ├── quality/                 # ATS 检查、岗位匹配打分
│   └── tools/smoke_v3.py        # 自检脚本（端点/合并/语法/导出往返）
├── auto_test/                   # 批量回归测试脚本
└── 项目技术说明.md              # 架构与实现说明
```

## 快速开始

### 环境要求

- Python 3.9+、MySQL 8
- （PDF 导出）本机安装 Microsoft Word —— 依赖 Word COM 组件
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
python -m uvicorn main:app --host 0.0.0.0 --port 8000   # 或 Windows 下双击 启动.bat
```

访问 <http://localhost:8000>，编辑器入口：`/static/editor.html`（需注册/登录）。

### 环境变量说明（.env）

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 内容优化主模型的 Key 与接口地址（OpenAI 兼容格式） |
| `GLM_API_KEY` | 智谱 GLM Key（编辑器 AI 生成） |
| `OLLAMA_BASE_URL` | 本地 Ollama 地址（默认 <http://localhost:11434>） |
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接配置 |
| `ADMIN_PASSWORD` | 管理后台管理员密码 |

## 自检

```bash
cd resume_optimizer
python tools/smoke_v3.py
# 覆盖：端点增删、editor_boxes 结构合并、JS 语法、docx→pdf→长图真实往返、盒子注入
```

## 更新日志

### 编辑器重构（当前）

- 编辑器整体推翻重建：统一 JSON 数据模型 + 三栏布局 + 点击直改，换模板零丢失
- 新增管理端可视化模板编辑器，布局覆盖（overrides）+ 新增盒子（added）即时下发
- 新增结构化导出链路 `/api/export/{docx,pdf,png}`
- 移除 VIP 门禁（登录即可用），下线用户 VIP 管理 / 板块绑定 / 同义词库等旧模块
- 时间字段全面升级为年月点选面板；照片、云草稿、旧数据迁移等一系列修复

## 说明

- `.env`、运行时预览/日志、模板素材等本地资料不入库（见 `.gitignore`）
- 本项目仅用于学习与个人求职辅助
