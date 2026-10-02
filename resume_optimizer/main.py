"""简历优化系统：FastAPI 应用入口。

角色与接口（对应设计说明第 7 节）：
- 公开：GET /health、GET /templates、POST /optimize、GET /download/{session_id}
- 管理员（需 X-Admin-Password 请求头）：
  POST /admin/templates/upload、DELETE /admin/templates/{id}、
  GET /admin/templates/{id}/config
"""
import json
import os
import re
import secrets
import threading
import time as _time
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from utils import (applog, auth as user_auth, converter, db, editor, filler, llm,
                   parser, standard_keys, template)
from utils.tmpfiles import safe_unlink

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
TEMPLATES_DIR = BASE_DIR / "utils" / "templates"
TEMP_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)


# 清理上次运行遗留的临时文件（如崩溃/重启产生的孤儿文件）
for _f in list(TEMP_DIR.iterdir()):
    if _f.is_file():
        safe_unlink(_f)

# ── 配置（.env）──
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
MAX_TEMPLATES = int(os.getenv("MAX_TEMPLATES", "100"))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024)))
BUILTIN_TEMPLATE_NAME = os.getenv("BUILTIN_TEMPLATE_NAME", "标准简洁模板")

SESSION_TTL = 1800  # 30 分钟过期
# session_id -> {"path": str, "time": float}
sessions = {}
# 实时预览缓存：{md5(template_id+content): png_b64}
_PREVIEW_CACHE = {}
_PREVIEW_CACHE_KEYS = []

USER_TOKEN_TTL = 7 * 24 * 3600  # 用户登录令牌有效期：7 天
# token -> {"user_id": int, "exp": float}
user_tokens = {}

ADMIN_TOKEN_TTL = 8 * 3600  # 管理员令牌有效期：8 小时
# token -> {"exp": float}
admin_tokens = {}

MAX_ADMINS = 3  # 管理员账号上限

# 内置模板的特殊占位符（姓名/联系方式/电话/邮箱/照片等，无需在 template_placeholders 中配置）
SPECIAL_PLACEHOLDERS = {"姓名", "联系方式", "电话", "邮箱", "求职意向", "照片", "photo"}

# 支持上传的简历格式
RESUME_EXTS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg"}


def _gc_sessions():
    """清理过期的 session 及其临时文件。"""
    now = time.time()
    expired = [sid for sid, v in sessions.items() if now - v["time"] > SESSION_TTL]
    for sid in expired:
        v = sessions.pop(sid, None)
        if v:
            safe_unlink(v.get("path"), v.get("photo"))


def _gc_user_tokens():
    """清理过期的用户登录令牌。"""
    now = time.time()
    expired = [t for t, v in user_tokens.items() if now > v["exp"]]
    for t in expired:
        user_tokens.pop(t, None)


def _gc_admin_tokens():
    """清理过期的管理员令牌。"""
    now = time.time()
    expired = [t for t, v in admin_tokens.items() if now > v["exp"]]
    for t in expired:
        admin_tokens.pop(t, None)


def _admin_token_ok(authorization: Optional[str]) -> bool:
    """校验 Authorization: Bearer <admin_token> 是否有效。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        return False
    token = authorization[7:].strip()
    _gc_admin_tokens()
    rec = admin_tokens.get(token)
    if rec is None or time.time() > rec["exp"]:
        return False
    return True


def _require_user(request: Request) -> dict:
    """校验用户登录令牌（Authorization: Bearer <token> 或 ?token=），
    返回用户信息字典。未登录或过期时抛 401。"""
    _gc_user_tokens()
    token = ""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = (request.query_params.get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    rec = user_tokens.get(token)
    if rec is None:
        raise HTTPException(status_code=401, detail="登录状态无效，请重新登录")
    if time.time() > rec["exp"]:
        user_tokens.pop(token, None)
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get_user_by_id(rec["user_id"])
    if user is None:
        user_tokens.pop(token, None)
        raise HTTPException(status_code=401, detail="用户不存在，请重新登录")
    return {"token": token, **user}


def _require_admin_header(x_admin_password: Optional[str] = Header(None),
                          authorization: Optional[str] = Header(None)):
    """校验管理员身份（Header X-Admin-Password 或 Bearer 管理员令牌）。"""
    if _admin_token_ok(authorization):
        return
    if not ADMIN_PASSWORD or not x_admin_password:
        raise HTTPException(status_code=401, detail="需要管理员登录")
    if not secrets.compare_digest(x_admin_password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="管理员密码错误")


def _require_admin(x_admin_password: Optional[str] = Header(None),
                   admin_password: Optional[str] = Form(None),
                   authorization: Optional[str] = Header(None)):
    """校验管理员身份（Header X-Admin-Password / Bearer 令牌 / 表单密码）。"""
    if _admin_token_ok(authorization):
        return
    pwd = x_admin_password or admin_password or ""
    if not ADMIN_PASSWORD or not pwd:
        raise HTTPException(status_code=401, detail="需要管理员登录")
    if not secrets.compare_digest(pwd, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="管理员密码错误")


def _json_safe(obj):
    """递归清洗：把 lxml 元素等不可 JSON 序列化的对象转为字符串。"""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _sync_after_renumber() -> dict:
    """重排每模块独立 display_id：免费 1,2,3…；VIP 1,2,3…（互不影响）。
    真实 id 保持不变，故外键/预览图/草稿引用均无需同步。"""
    return db.renumber_display_ids()


# 模板结构几何算法版本：v3 = 分组坐标系修复 + 表格单元格支持；
# v4 = 空盒可编辑尺寸启发式（待填内容区不再被标成装饰盒）。旧缓存自动失效。
STRUCTURE_GEO_VERSION = 4

# 新编辑模式（模板骨架+就地富文本）缓存版本
RICHTEXT_GV = 8
_RICHTEXT_BUILD_LOCK = threading.Lock()
_RICHTEXT_BUILDING = set()   # 正在构建的模板 id（防并发重复构建）


def _get_template_structure_cached(tpl: dict) -> dict:
    """返回模板结构：优先用已缓存结构（避免每次调用 Word 转换），
    没有缓存则解析一次并写回模板配置。"""
    cfg = tpl.get("config") or {}
    cache = cfg.get("structure_cache") or {}
    if cache.get("boxes") and cache.get("gv") == STRUCTURE_GEO_VERSION:
        return {
            "page_w": cache.get("page_w"),
            "page_h": cache.get("page_h"),
            "boxes": cache.get("boxes"),
        }
    from utils import template_editor
    structure = template_editor.parse_template_structure(BASE_DIR / tpl["file_path"])
    try:
        cfg["structure_cache"] = {
            "ts": int(time.time()),
            "gv": STRUCTURE_GEO_VERSION,
            "page_w": structure.get("page_w"),
            "page_h": structure.get("page_h"),
            "boxes": structure.get("boxes"),
        }
        db.update_template_config(tpl["id"], json.dumps(cfg, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] 结构缓存写入失败: {exc}")
    return structure


def _trim_secondary(data: dict) -> None:
    """单页预精简：只压缩次要模块（主修课程/技能/自我评价），
    绝不触碰工作/实习/项目经历；教育背景课程按规则保持一字不改（不再砍课程）。"""
    import re as _re
    # 技能：压缩为分类标签行
    skills = str(data.get("skills") or "").strip()
    if skills:
        kept = []
        for ln in skills.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            m = _re.match(r"^([^：:]{2,12})[：:]\s*(.+)$", ln)
            if m:
                kept.append(m.group(1) + "：" + m.group(2)[:36])
            elif len(ln) <= 40:
                kept.append(ln)
        data["skills"] = "\n".join(kept[:4])
    # 自我评价：压缩为一段
    summary = str(data.get("summary") or "").strip()
    if summary:
        data["summary"] = " ".join(p.strip() for p in summary.splitlines() if p.strip())[:140]


async def _read_limited(upload: UploadFile) -> bytes:
    """读取上传文件并限制大小。"""
    data = await upload.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="文件超过大小限制")
    return data


def _scan_placeholders(docx_path: Path) -> set:
    """扫描模板 docx 中出现的所有 {{占位符}} 标签。"""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    doc = Document(str(docx_path))
    found = set()
    for p in doc.element.iter(qn("w:p")):
        para = Paragraph(p, doc)
        for m in filler.PLACEHOLDER_RE.finditer(para.text or ""):
            found.add(m.group(1).strip())
    return found


def _generate_preview(docx_path: Path, template_id: int) -> bool:
    """用模板原始文件生成预览图（展示模板原貌，不带占位符文字）。"""
    try:
        import tempfile
        from utils import converter
        import fitz
        tmp_dir = Path(tempfile.mkdtemp(prefix="pv_"))
        pdf_path = tmp_dir / "p.pdf"
        converter.docx_to_pdf(str(docx_path), str(pdf_path))
        doc = fitz.open(str(pdf_path))
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        out = BASE_DIR / "static" / "previews" / f"t{template_id}.png"
        pix.save(str(out))
        doc.close()
        for f in list(tmp_dir.iterdir()):
            safe_unlink(f)
        try:
            tmp_dir.rmdir()
        except BaseException:  # noqa: BLE001
            pass
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] 预览图生成失败: {exc}")
        return False


def _register_builtin_template():
    """模板库为空时，自动注册内置模板，保证开箱即用。"""
    if db.count_active_templates() > 0:
        return
    fname = f"builtin_{uuid.uuid4().hex}.docx"
    tpl_path = TEMPLATES_DIR / fname
    template.create_builtin_template(tpl_path)
    tid = db.create_template(
        BUILTIN_TEMPLATE_NAME,
        "系统内置标准模板：姓名 + 联系方式 + 照片 + 五大模块，简洁统一排版",
        f"utils/templates/{fname}",
    )
    db.replace_placeholders(tid, db.DEFAULT_MODULES)
    print(f"[INFO] 已注册内置模板: id={tid}, name={BUILTIN_TEMPLATE_NAME}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
        applog.log("server_start", pid=os.getpid())
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] 数据库初始化失败（请检查 .env 数据库配置）: {exc}")
        applog.log("server_start_error", error=str(exc))
    yield


app = FastAPI(title="简历优化系统", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


@app.middleware("http")
async def no_cache_editor(request, call_next):
    """编辑器相关的静态资源禁止浏览器缓存（防止旧 JS 阻塞开发）"""
    response = await call_next(request)
    path = request.url.path
    if (path.startswith("/static/editor") or path.startswith("/static/index.html")
            or path == "/my-resumes"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/")
def index():
    """返回首页，并把模板数据直接注入 HTML，页面无需 fetch 即可展示模板。"""
    html_path = BASE_DIR / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    try:
        rows = db.list_templates()
        tpls = []
        ph_map = db.get_placeholders_map([r["id"] for r in rows])
        for r in rows:
            preview_path = BASE_DIR / "static" / "previews" / f"t{r['id']}.png"
            preview_url = f"/static/previews/t{r['id']}.png?v=5" if preview_path.exists() else None
            tpls.append({
                "id": r["id"], "name": r["name"], "description": r["description"],
                "modules": ph_map.get(r["id"], []), "config": r.get("config") or {},
                "preview_url": preview_url,
            })
        payload = json.dumps(tpls, ensure_ascii=False).replace("</", "<\\/")
        inject = f'<script>window.__TEMPLATES__ = {payload};</script>'
        # 注入脚本必须放在主脚本之前，否则 loadTemplates() 执行时数据还未定义
        html = html.replace("<script>", inject + "<script>", 1)
    except Exception as exc:  # noqa: BLE001 注入失败不影响页面
        print(f"[WARN] 模板注入失败: {exc}")
    return Response(html, media_type="text/html; charset=utf-8")


@app.get("/my-resumes")
def my_resumes():
    """「我的简历」列表页。"""
    html_path = BASE_DIR / "static" / "my-resumes.html"
    return Response(html_path.read_text(encoding="utf-8"), media_type="text/html; charset=utf-8")


@app.get("/health")
def health():
    return {"status": "ok"}


# ══════════════════ 用户登录 / 注册 ══════════════════


class _RegisterIn(BaseModel):
    account: str
    nickname: str = ""
    password: str


class _LoginIn(BaseModel):
    account: str
    password: str


_PHONE_RE = re.compile(r"^1\d{10}$")
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w.-]+\.\w+$")


def _valid_account(account: str) -> bool:
    return bool(_PHONE_RE.match(account) or _EMAIL_RE.match(account))


def _issue_token(user_id: int) -> str:
    """签发登录令牌并记录过期时间。"""
    token = user_auth.new_token()
    user_tokens[token] = {"user_id": user_id, "exp": time.time() + USER_TOKEN_TTL}
    return token


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "account": user["account"],
        "nickname": user.get("nickname") or "",
        "is_vip": 1 if user.get("is_vip") else 0,
        "created_at": str(user.get("created_at") or ""),
        "last_login_at": str(user.get("last_login_at") or ""),
    }


@app.get("/login")
def login_page():
    """用户登录/注册页。"""
    html_path = BASE_DIR / "static" / "login.html"
    return Response(html_path.read_text(encoding="utf-8"),
                    media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/register")
def register(payload: _RegisterIn):
    """用户注册（手机号/邮箱 + 昵称 + 密码），成功后直接登录。"""
    account = (payload.account or "").strip().lower()
    password = payload.password or ""
    nickname = (payload.nickname or "").strip()[:30]
    if not _valid_account(account):
        raise HTTPException(status_code=400, detail="请输入正确的手机号或邮箱")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if db.get_user_by_account(account) is not None:
        raise HTTPException(status_code=400, detail="该账号已注册，请直接登录")
    user_id = db.create_user(account, user_auth.hash_password(password), nickname)
    if not user_id:
        raise HTTPException(status_code=400, detail="该账号已注册，请直接登录")
    user = db.get_user_by_id(user_id)
    db.touch_login(user_id)
    token = _issue_token(user_id)
    applog.log("user_register", user_id=user_id, account=account)
    return {"token": token, "user": _public_user(user)}


@app.post("/api/login")
def login(payload: _LoginIn):
    """账号密码登录，返回令牌与用户信息。"""
    account = (payload.account or "").strip().lower()
    password = payload.password or ""
    user = db.get_user_by_account(account)
    if user is None or not user_auth.verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    db.touch_login(user["id"])
    token = _issue_token(user["id"])
    applog.log("user_login", user_id=user["id"], account=account)
    return {"token": token, "user": _public_user(user)}


@app.post("/api/logout")
def logout(user: dict = Depends(_require_user)):
    """退出登录：吊销当前令牌。"""
    user_tokens.pop(user["token"], None)
    applog.log("user_logout", user_id=user["id"])
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(_require_user)):
    """返回当前登录用户信息。"""
    return _public_user(user)


class _AdminLoginIn(BaseModel):
    account: str
    password: str


class _AdminRegisterIn(BaseModel):
    account: str
    nickname: str = ""
    password: str


@app.get("/admin")
def admin_console_page():
    """管理端控制台。独立入口，不再从用户页面暴露。"""
    html_path = BASE_DIR / "static" / "admin.html"
    return Response(html_path.read_text(encoding="utf-8"),
                    media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@app.get("/admin/login")
def admin_login_page():
    """管理员登录页。"""
    html_path = BASE_DIR / "static" / "admin_login.html"
    return Response(html_path.read_text(encoding="utf-8"),
                    media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/admin/login")
def admin_login(payload: _AdminLoginIn):
    """管理员账号登录，返回令牌（8 小时有效）。"""
    account = (payload.account or "").strip().lower()
    pwd = payload.password or ""
    admin = db.get_admin_by_account(account)
    if admin is None or not user_auth.verify_password(pwd, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = user_auth.new_token()
    admin_tokens[token] = {"exp": time.time() + ADMIN_TOKEN_TTL}
    db.touch_login(admin["id"])
    applog.log("admin_login", user_id=admin["id"], account=account)
    return {
        "token": token,
        "user": {
            "id": admin["id"],
            "account": admin["account"],
            "nickname": admin.get("nickname") or "",
        },
    }


@app.post("/api/admin/register")
def admin_register(payload: _AdminRegisterIn):
    """注册管理员账号（最多 MAX_ADMINS 个），成功后直接登录。"""
    account = (payload.account or "").strip().lower()
    password = payload.password or ""
    nickname = (payload.nickname or "").strip()[:30]
    if not _valid_account(account):
        raise HTTPException(status_code=400, detail="请输入正确的手机号或邮箱")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    if db.count_admins() >= MAX_ADMINS:
        raise HTTPException(status_code=400, detail=f"管理员账号已满（最多 {MAX_ADMINS} 个）")
    if db.get_user_by_account(account) is not None:
        raise HTTPException(status_code=400, detail="该账号已注册")
    admin_id = db.create_admin(account, user_auth.hash_password(password), nickname)
    if not admin_id:
        raise HTTPException(status_code=400, detail="该账号已注册")
    admin = db.get_admin_by_account(account)
    db.touch_login(admin_id)
    token = user_auth.new_token()
    admin_tokens[token] = {"exp": time.time() + ADMIN_TOKEN_TTL}
    applog.log("admin_register", user_id=admin_id, account=account,
               total=db.count_admins())
    return {
        "token": token,
        "user": {
            "id": admin["id"],
            "account": admin["account"],
            "nickname": admin.get("nickname") or "",
        },
    }


@app.get("/api/admin/status")
def admin_status():
    """管理员账号数量与剩余注册名额。"""
    count = db.count_admins()
    return {"count": count, "max": MAX_ADMINS, "remaining": max(0, MAX_ADMINS - count)}


@app.post("/api/admin/logout")
def admin_logout(authorization: Optional[str] = Header(None)):
    """管理员退出：吊销当前令牌。"""
    if not _admin_token_ok(authorization):
        raise HTTPException(status_code=401, detail="需要管理员登录")
    admin_tokens.pop(authorization[7:].strip(), None)
    applog.log("admin_logout")
    return {"ok": True}


@app.post("/api/admin/user-vip")
def admin_set_user_vip(account: str = Form(""),
                       is_vip: int = Form(...),
                       _: None = Depends(_require_admin_header)):
    """开通/取消用户 VIP：VIP 用户才能使用在线编辑器与 VIP 模板中心。"""
    if is_vip not in (0, 1):
        raise HTTPException(status_code=400, detail="is_vip 仅支持 0 / 1")
    user = db.get_user_by_account((account or "").strip().lower())
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.set_user_vip(user["id"], is_vip)
    applog.log("admin_user_vip", user_id=user["id"], account=user["account"], is_vip=is_vip)
    return {
        "message": "已为用户开通 VIP" if is_vip else "已取消用户 VIP",
        "user": {"id": user["id"], "account": user["account"], "is_vip": is_vip},
    }


# ══════════════════ 模板库（公开）══════════════════


@app.get("/templates")
def list_templates():
    """返回全部有效模板（含预览图）。公开接口，首页模板中心免费展示/下载。"""
    rows = db.list_templates()
    result = []
    ph_map = db.get_placeholders_map([r["id"] for r in rows])
    for r in rows:
        preview_path = BASE_DIR / "static" / "previews" / f"t{r['id']}.png"
        if not preview_path.exists():
            continue
        result.append({"id": r["id"], "name": r["name"],
                       "description": r["description"], "modules": ph_map.get(r["id"], []),
                       "config": r.get("config") or {},
                       "display_id": r.get("display_id") or r["id"],
                       # 编辑器模板库筛选依据；首页模板中心不据此过滤
                       "editable": 1 if r.get("editable") is None else int(r["editable"]),
                       "preview_url": f"/static/previews/t{r['id']}.png?v=5"})
    return result


@app.get("/api/vip-templates")
def list_vip_templates(_: dict = Depends(_require_user)):
    """用户端 VIP 模板中心（登录后可用），与首页免费模板中心相互独立。"""
    rows = db.list_vip_templates()
    result = []
    ph_map = db.get_placeholders_map([r["id"] for r in rows])
    for r in rows:
        preview_path = BASE_DIR / "static" / "previews" / f"t{r['id']}.png"
        if not preview_path.exists():
            continue
        result.append({
            "id": r["id"], "name": r["name"], "description": r["description"],
            "modules": ph_map.get(r["id"], []), "config": r.get("config") or {},
            "display_id": r.get("display_id") or r["id"],
            # 编辑器模板库筛选依据
            "editable": 1 if r.get("editable") is None else int(r["editable"]),
            "preview_url": f"/static/previews/t{r['id']}.png?v=5",
        })
    return result


@app.get("/api/template-structure/{template_id}")
def get_template_structure(template_id: int, _: dict = Depends(_require_user)):
    """返回真实模板的可编辑结构（文本框位置/内容/占位符），供编辑器就地编辑。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    structure = _get_template_structure_cached(tpl)
    cfg = (tpl.get("config") or {}).get("editor_boxes") or {}
    return {"id": tpl["id"], "name": tpl["name"], "config": cfg, **structure}


@app.get("/api/admin/template-config/{template_id}")
def admin_get_template_config(template_id: int,
                              refresh: int = 0,
                              _: None = Depends(_require_admin_header)):
    """管理端读取模板结构 + 当前模块配置（用于「模板训练」）。refresh=1 强制重新解析。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    structure = None
    if not refresh:
        structure = _get_template_structure_cached(tpl)
    else:
        from utils import template_editor
        structure = template_editor.parse_template_structure(BASE_DIR / tpl["file_path"])
        try:
            cfg = tpl.get("config") or {}
            cfg["structure_cache"] = {
                "ts": int(time.time()),
                "gv": STRUCTURE_GEO_VERSION,
                "page_w": structure.get("page_w"),
                "page_h": structure.get("page_h"),
                "boxes": structure.get("boxes"),
            }
            db.update_template_config(tpl["id"], json.dumps(cfg, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] 结构缓存写入失败: {exc}")
    cfg = (tpl.get("config") or {}).get("editor_boxes") or {}
    return {"id": tpl["id"], "name": tpl["name"], "config": cfg, **structure}


@app.post("/api/admin/template-config/{template_id}")
def admin_save_template_config(template_id: int,
                               config: str = Form("{}"),
                               _: None = Depends(_require_admin_header)):
    """保存模板的模块配置：{ box_id: { module: 'work' } }。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        boxes = json.loads(config or "{}")
        assert isinstance(boxes, dict)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="config 格式错误")
    cur_cfg = (tpl.get("config") or {})
    cur_cfg["editor_boxes"] = boxes
    db.update_template_config(template_id, json.dumps(cur_cfg, ensure_ascii=False))
    applog.log("template_config_save", template_id=template_id, boxes=len(boxes))
    return {"message": "模板配置已保存", "count": len(boxes)}


@app.post("/api/template-save/{template_id}")
def save_template_edits(template_id: int,
                        edits: str = Form("{}"),
                        format: str = Form("docx"),
                        _: dict = Depends(_require_user)):
    """把就地编辑的文本框内容写回真实模板，导出 Word / PDF。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        edits_obj = json.loads(edits or "{}")
        assert isinstance(edits_obj, dict)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="edits 格式错误")
    from utils import template_editor
    data = template_editor.apply_box_texts(BASE_DIR / tpl["file_path"], edits_obj)
    fname = f"edited_{tpl['id']}_{uuid.uuid4().hex[:8]}.docx"
    out_path = BASE_DIR / "temp" / fname
    out_path.write_bytes(data)
    if format == "pdf":
        from utils import converter
        pdf_path = BASE_DIR / "temp" / fname.replace(".docx", ".pdf")
        converter.docx_to_pdf(str(out_path), str(pdf_path))
        out_path = pdf_path
        media = "application/pdf"
    else:
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(out_path, media_type=media, filename=out_path.name)


@app.post("/api/template-preview/{template_id}")
def preview_template_edits(template_id: int, edits: str = Form("{}")):
    """真实模板模式预览：把文本框编辑写回 docx → Word 重排 → 全部页面 PNG。
    前端「热区点击+弹窗编辑」模式用它与导出结果保持像素级一致：
    预览即 Word 渲染成品，而非 HTML 近似模拟。渲染所有页面——内容较长
    溢出到第 2 页（或模板本身多页）时，编辑器同样能看到完整简历。
    带 LRU 缓存。"""
    import base64 as _b64
    import hashlib as _hashlib
    import fitz as _fitz

    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        edits_obj = json.loads(edits or "{}")
        assert isinstance(edits_obj, dict)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="edits 格式错误")

    cache_key = _hashlib.md5(
        f"tpv|{template_id}|{json.dumps(edits_obj, sort_keys=True, ensure_ascii=False)}".encode("utf-8")
    ).hexdigest()
    cached = _PREVIEW_CACHE.get(cache_key)
    if cached:
        if isinstance(cached, dict):
            return dict(cached, cached=True)
        return {"png_b64": cached, "cached": True}

    from utils import template_editor, converter
    out_path = TEMP_DIR / f"tprev_{uuid.uuid4().hex}.docx"
    pdf_path = TEMP_DIR / f"tprev_{uuid.uuid4().hex}.pdf"
    try:
        data = template_editor.apply_box_texts(BASE_DIR / tpl["file_path"], edits_obj)
        out_path.write_bytes(data)
        converter.docx_to_pdf(str(out_path), str(pdf_path))
        doc = _fitz.open(str(pdf_path))
        try:
            mat = _fitz.Matrix(150 / 72, 150 / 72)
            pages_b64 = []
            for page in doc:
                png_bytes = page.get_pixmap(matrix=mat).tobytes("png")
                pages_b64.append("data:image/png;base64," + _b64.b64encode(png_bytes).decode("ascii"))
        finally:
            doc.close()
        result = {"png_b64": pages_b64[0] if pages_b64 else "",
                  "pages": pages_b64, "page_count": len(pages_b64)}

        _PREVIEW_CACHE[cache_key] = result
        _PREVIEW_CACHE_KEYS.append(cache_key)
        if len(_PREVIEW_CACHE_KEYS) > 30:
            old_key = _PREVIEW_CACHE_KEYS.pop(0)
            _PREVIEW_CACHE.pop(old_key, None)
        return dict(result, cached=False)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"渲染失败: {e}")
    finally:
        safe_unlink(out_path, pdf_path)


@app.get("/api/richtext-structure/{template_id}")
def get_richtext_structure(template_id: int, _: dict = Depends(_require_user)):
    """新编辑模式（模板骨架+就地富文本）结构：盒子几何/格式/板块语义 +
    照片框 + 无字装饰底图 URL。结果缓存于模板配置（版本号管理失效）。
    首次构建需两次 Word 转换（10-40 秒）；构建中重复请求返回 409。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    cfg = tpl.get("config") or {}
    cache = cfg.get("richtext_cache") or {}
    if cache.get("boxes") and cache.get("gv") == RICHTEXT_GV:
        return _richtext_payload(template_id, cache)

    with _RICHTEXT_BUILD_LOCK:
        cfg = (db.get_template(template_id) or {}).get("config") or {}
        cache = cfg.get("richtext_cache") or {}
        if cache.get("boxes") and cache.get("gv") == RICHTEXT_GV:
            return _richtext_payload(template_id, cache)   # 等锁期间已构建
        if cache.get("unsupported") and cache.get("gv") == RICHTEXT_GV:
            raise HTTPException(status_code=422, detail="该模板为复杂版式（艺术字/组合图形），请使用经典版编辑")
        if template_id in _RICHTEXT_BUILDING:
            raise HTTPException(status_code=409, detail="模板正在解析中，请 30 秒后刷新重试")
        _RICHTEXT_BUILDING.add(template_id)
    try:
        from utils import template_richtext
        docx_path = BASE_DIR / tpl["file_path"]
        if not docx_path.exists():
            raise HTTPException(status_code=404, detail="模板文件缺失")
        bg_rel = f"static/previews/t{template_id}_blank.png"
        st = template_richtext.build_richtext_template(docx_path, BASE_DIR / bg_rel)
        if not st or not st.get("bg_ok") or not st.get("boxes"):
            # 负缓存：复杂模板不再反复尝试构建（30 秒×N 的等待对用户是灾难）
            cfg["richtext_cache"] = {"gv": RICHTEXT_GV, "unsupported": True,
                                     "ts": int(time.time())}
            try:
                db.update_template_config(template_id, json.dumps(cfg, ensure_ascii=False))
            except Exception:  # noqa: BLE001
                pass
            raise HTTPException(status_code=422, detail="该模板为复杂版式（艺术字/组合图形），请使用经典版编辑")
        st["gv"] = RICHTEXT_GV
        st["bg_path"] = bg_rel
        try:
            cfg["richtext_cache"] = st
            db.update_template_config(template_id, json.dumps(cfg, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] richtext 缓存写入失败: {exc}")
        return _richtext_payload(template_id, st)
    finally:
        with _RICHTEXT_BUILD_LOCK:
            _RICHTEXT_BUILDING.discard(template_id)


def _richtext_payload(template_id: int, cache: dict) -> dict:
    import os as _os
    bg_file = BASE_DIR / cache.get("bg_path", "")
    ver = int(_os.path.getmtime(bg_file)) if bg_file.exists() else 0
    bg_name = Path(cache.get("bg_path", "")).name
    return {"page_w": cache.get("page_w"), "page_h": cache.get("page_h"),
            "boxes": cache.get("boxes"),
            "photo_boxes": cache.get("photo_boxes") or [],
            "bg_url": f"/static/previews/{bg_name}?v={ver}"
            if bg_file.exists() else ""}


@app.post("/api/richtext-export/{template_id}")
def richtext_export(template_id: int,
                    edits: str = Form("{}"),
                    photo_rid: str = Form(""),
                    photo: str = Form(""),
                    format: str = Form("docx"),
                    _: dict = Depends(_require_user)):
    """新编辑模式导出：富文本编辑写回模板原 docx（保留模板设计），
    可选替换照片，导出 Word / PDF / 长图。"""
    import base64 as _b64

    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        edits_obj = json.loads(edits or "{}")
        assert isinstance(edits_obj, dict)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="edits 格式错误")

    from utils import template_richtext, converter
    docx_path = BASE_DIR / tpl["file_path"]
    try:
        data = template_richtext.apply_rich_texts(docx_path, edits_obj)
        if photo_rid and photo:
            data = template_richtext.replace_photo_bytes(
                data, photo_rid, _b64.b64decode(photo))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"写回失败: {e}")

    stamp = uuid.uuid4().hex[:8]
    out_path = TEMP_DIR / f"rt_{stamp}.docx"
    out_path.write_bytes(data)

    if format == "pdf":
        pdf_path = TEMP_DIR / f"rt_{stamp}.pdf"
        converter.docx_to_pdf(str(out_path), str(pdf_path))
        return FileResponse(str(pdf_path), media_type="application/pdf",
                            filename="简历.pdf")

    if format == "png":
        import fitz
        from PIL import Image
        pdf_path = TEMP_DIR / f"rt_{stamp}.pdf"
        converter.docx_to_pdf(str(out_path), str(pdf_path))
        doc = fitz.open(str(pdf_path))
        try:
            mat = fitz.Matrix(2.0, 2.0)
            imgs = []
            for page in doc:
                pix = page.get_pixmap(matrix=mat)
                imgs.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        finally:
            doc.close()
        if not imgs:
            raise HTTPException(status_code=500, detail="渲染失败")
        gap = int(imgs[0].width * 0.03)
        total_h = sum(i.height for i in imgs) + gap * (len(imgs) - 1)
        canvas = Image.new("RGB", (imgs[0].width, total_h), (243, 241, 255))
        y = 0
        for im in imgs:
            canvas.paste(im, (0, y))
            y += im.height + gap
        png_path = TEMP_DIR / f"rt_{stamp}.png"
        canvas.save(png_path, format="PNG")
        return FileResponse(str(png_path), media_type="image/png",
                            filename="简历.png")

    return FileResponse(str(out_path),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename="简历.docx")


@app.post("/api/richtext-warm")
def richtext_warm(_: dict = Depends(_require_user)):
    """后台预热全部模板的新编辑缓存（跳过已构建的），完成后所有模板
    在新版编辑器中秒开。耗时任务后台执行，立即返回。"""
    import threading

    def _warm():
        import time as _time
        from utils import template_richtext
        for t in db.list_templates():
            try:
                tpl = db.get_template(t["id"])
                cfg = tpl.get("config") or {}
                cache = cfg.get("richtext_cache") or {}
                if cache.get("boxes") and cache.get("gv") == RICHTEXT_GV:
                    continue
                docx_path = BASE_DIR / tpl["file_path"]
                if not docx_path.exists():
                    continue
                bg_rel = f"static/previews/t{tpl['id']}_blank.png"
                st = template_richtext.build_richtext_template(docx_path, BASE_DIR / bg_rel)
                if st and st.get("bg_ok") and st.get("boxes"):
                    st["gv"] = RICHTEXT_GV
                    st["bg_path"] = bg_rel
                    cfg["richtext_cache"] = st
                    db.update_template_config(tpl["id"], json.dumps(cfg, ensure_ascii=False))
                    print(f"[warm] 模板 {tpl['id']} {tpl['name']} 预热完成")
                else:
                    print(f"[warm] 模板 {tpl['id']} 不支持新版编辑，跳过")
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] 预热模板 {t['id']} 失败: {exc}")
            _time.sleep(0.5)

    threading.Thread(target=_warm, daemon=True).start()
    return {"message": "预热已在后台开始，全部模板将陆续支持秒开"}


@app.get("/templates/{template_id}/download")
def download_template_file(template_id: int, _: dict = Depends(_require_user)):
    """用户端下载模板原始文件（仅免费模板；VIP 模板需开通会员后下载）。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    if tpl.get("is_vip"):
        raise HTTPException(status_code=403, detail="VIP 模板需开通会员后下载")
    tpl_file = BASE_DIR / tpl["file_path"]
    if not tpl_file.exists():
        raise HTTPException(status_code=404, detail="模板文件缺失")
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", tpl.get("name") or "template") + ".docx"
    return FileResponse(
        str(tpl_file),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe_name,
    )


# ════════ 用户简历草稿 CRUD（编辑器持久化） ════════
class _DraftSaveIn(BaseModel):
    draft_id: Optional[int] = None
    template_id: Optional[int] = None
    title: str = ""
    data: dict = Field(default_factory=dict)


@app.post("/api/draft/save")
def draft_save(payload: _DraftSaveIn, user: dict = Depends(_require_user)):
    """保存/更新当前用户的草稿。返回 draft_id。"""
    try:
        data_json = json.dumps(payload.data, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"data 序列化失败: {exc}")
    draft_id = db.save_draft(
        user_id=user["id"],
        template_id=payload.template_id,
        title=payload.title,
        data_json=data_json,
        draft_id=payload.draft_id)
    applog.log("draft_save", user_id=user["id"], draft_id=draft_id,
               template_id=payload.template_id, size=len(data_json))
    return {"draft_id": draft_id, "ok": True}


@app.get("/api/draft/list")
def draft_list(user: dict = Depends(_require_user)):
    """列出当前用户的所有草稿（不含 data_json 全文）。"""
    rows = db.list_drafts(user["id"])
    return [{"id": r["id"], "template_id": r["template_id"],
             "title": r["title"] or "未命名简历",
             "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
             "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
            for r in rows]


@app.get("/api/draft/{draft_id}")
def draft_get(draft_id: int, user: dict = Depends(_require_user)):
    row = db.get_draft(user["id"], draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    try:
        data = json.loads(row["data_json"]) if row.get("data_json") else {}
    except (ValueError, TypeError):
        data = {}
    return {"id": row["id"], "template_id": row["template_id"],
            "title": row["title"], "data": data,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None}


@app.delete("/api/draft/{draft_id}")
def draft_delete(draft_id: int, user: dict = Depends(_require_user)):
    ok = db.delete_draft(user["id"], draft_id)
    if not ok:
        raise HTTPException(status_code=404, detail="草稿不存在或无权删除")
    return {"ok": True}


class _DraftBatchDeleteIn(BaseModel):
    ids: List[int]


@app.post("/api/draft/batch-delete")
def draft_batch_delete(payload: _DraftBatchDeleteIn, user: dict = Depends(_require_user)):
    """批量删除当前用户的草稿。"""
    ids = [int(x) for x in payload.ids if isinstance(x, int) or (isinstance(x, str) and str(x).isdigit())]
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    deleted = db.delete_drafts_batch(user["id"], ids)
    return {"ok": True, "deleted": deleted}


@app.get("/admin/logs")
def admin_logs(
    limit: int = 200,
    _: None = Depends(_require_admin_header),
):
    """返回最近系统日志（需管理员密码）。"""
    return {"logs": applog.recent(min(max(limit, 1), 500))}


# ══════════════════ 模板库（管理员）══════════════════


_LABEL_TO_KEY = {
    "姓名": "name", "联系方式": "contact", "电话": "contact", "邮箱": "contact",
    "求职意向": "job_title", "个人优势": "summary", "工作经历": "work_experience",
    "项目经历": "projects", "教育背景": "education", "专业技能": "skills",
    "所在地": "location", "政治面貌": "political_status",
}


def _build_modules(labels) -> list:
    """根据占位符标签自动生成模块配置。"""
    mods = []
    for lab in labels:
        key = _LABEL_TO_KEY.get(lab)
        if key and key not in [m["module_key"] for m in mods]:
            mods.append({"module_key": key, "label": lab,
                         "min_words": 30, "max_words": 500})
    if not mods:
        mods = [{"module_key": "summary", "label": "个人优势",
                 "min_words": 30, "max_words": 300}]
    return mods


async def _process_upload(file: UploadFile, name: str = "", description: str = "",
                          modules: str = "", config: str = "{}",
                          is_vip: int = 0) -> dict:
    """处理单份模板上传（含自动识别名称/模块/场景说明）。"""
    suffix = (Path(file.filename or "").suffix or "").lower()
    if suffix != ".docx":
        return {"ok": False, "filename": file.filename, "error": "仅支持 .docx 格式"}
    if db.count_active_templates() >= MAX_TEMPLATES:
        return {"ok": False, "filename": file.filename,
                "error": f"模板数量已达上限（{MAX_TEMPLATES}）"}
    data = await _read_limited(file)
    fname = f"{uuid.uuid4().hex}.docx"
    tpl_path = TEMPLATES_DIR / fname
    tpl_path.write_bytes(data)
    # 校验占位符
    try:
        found = _scan_placeholders(tpl_path)
    except Exception:  # noqa: BLE001
        safe_unlink(tpl_path)
        return {"ok": False, "filename": file.filename, "error": "无法解析模板文件"}
    # 先用原始文件生成预览图（原貌），再注入占位符（占位符仅用于填充，不影响预览展示）
    tid_preview = db.get_max_template_id() + 1
    _generate_preview(tpl_path, tid_preview)
    # 自动补占位符
    auto_inject_result = None
    required_ph = {"姓名", "联系方式", "个人优势", "工作经历", "教育背景"}
    if not (required_ph & found) and ("电话" not in found or "邮箱" not in found):
        from utils.auto_placeholder import auto_inject_placeholders
        try:
            injected_path = TEMPLATES_DIR / f"auto_{fname}"
            auto_inject_result = auto_inject_placeholders(tpl_path, injected_path)
            if auto_inject_result.get("labels_found"):
                tpl_path.write_bytes(injected_path.read_bytes())
                safe_unlink(injected_path)
                found = set(auto_inject_result["labels_found"])
        except Exception as exc:  # noqa: BLE001
            auto_inject_result = {"error": str(exc)[:120]}
    # 名称/描述/模块自动识别
    if not name or not description or not modules:
        from utils.auto_placeholder import detect_metadata
        meta = detect_metadata(tpl_path, fallback_name=(file.filename or ""))
        name = name or meta["name"]
        description = description or meta["description"]
        if not modules:
            labels = sorted(set(found))
            if auto_inject_result and auto_inject_result.get("labels_found"):
                labels = sorted(set(auto_inject_result["labels_found"]))
            if meta.get("modules"):
                labels = sorted(set(labels) | set(meta["modules"]))
            mods = _build_modules(labels)
        else:
            import json as _json
            try:
                mods = _json.loads(modules)
                mods = [{"module_key": str(m["module_key"]).strip(),
                         "label": str(m["label"]).strip(),
                         "min_words": int(m.get("min_words", 30)),
                         "max_words": int(m.get("max_words", 500))} for m in mods]
            except Exception:
                mods = []
    else:
        import json as _json
        try:
            mods = _json.loads(modules)
        except Exception:
            mods = []
    if not mods:
        mods = _build_modules(sorted(set(found)))
    try:
        cfg = json.loads(config)
        assert isinstance(cfg, dict)
    except Exception:
        cfg = {}
    tid = db.create_template(name, description, f"utils/templates/{fname}",
                             config=json.dumps(cfg, ensure_ascii=False),
                             is_vip=1 if is_vip else 0)
    db.replace_placeholders(tid, mods)
    if is_vip:
        # VIP 模板由管理员直接管理，上传即上架（与免费模板的审核流程独立）
        db.set_review(tid, "approved", 1)
    else:
        db.set_review(tid, "pending", 0)
    config_labels = {m["label"] for m in mods}
    missing = config_labels - found
    unknown = (found - config_labels) - SPECIAL_PLACEHOLDERS
    report = {
        "placeholders_found": sorted(found),
        "missing_placeholders": sorted(missing),
        "unknown_placeholders": sorted(unknown),
        "auto_detected": {"name": name, "modules": [m["label"] for m in mods]},
    }
    if auto_inject_result and auto_inject_result.get("injected"):
        report["auto_inject"] = {
            "injected": auto_inject_result.get("injected"),
            "labels_found": auto_inject_result.get("labels_found"),
        }
    from utils import validator
    try:
        vresult = validator.validate_template_file(BASE_DIR / f"utils/templates/{fname}")
        report["render_checks"] = vresult["checks"]
        report["ok"] = vresult["ok"]
    except Exception as exc:  # noqa: BLE001
        report["render_checks"] = [{"name": "渲染测试", "ok": False, "detail": str(exc)[:120]}]
        report["ok"] = False
    db.save_validation_report(tid, json.dumps(_json_safe(report), ensure_ascii=False))
    applog.log("template_upload", template_id=tid, name=name,
               modules=len(mods), size_bytes=len(data), review_status="pending",
               auto_detected=bool(auto_inject_result))
    # 上传后重排：让模板 ID 始终连续（含刚上传的模板）
    _sync_after_renumber()
    return {"ok": True, "id": tid, "name": name, "is_vip": 1 if is_vip else 0,
            "review_status": "approved" if is_vip else "pending",
            "message": ("VIP 模板已上架" if is_vip else "模板已接收，等待人工审核"),
            "report": report}


@app.post("/admin/templates/upload")
async def upload_template(
    name: str = Form(""),
    description: str = Form(""),
    modules: str = Form(""),
    config: str = Form("{}"),
    is_vip: int = Form(0),
    file: UploadFile = File(...),
    _: None = Depends(_require_admin),
):
    """上传 .docx 模板；is_vip=1 时进入 VIP 模板中心（独立于免费模板，自动上架）。"""
    result = await _process_upload(file, name, description, modules, config,
                                   is_vip=is_vip)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "上传失败"))
    return result


@app.post("/admin/templates/batch_upload")
async def batch_upload_templates(
    files: List[UploadFile] = File(...),
    is_vip: int = Form(0),
    _: None = Depends(_require_admin),
):
    """批量导入模板：一次上传多个 .docx；is_vip=1 时全部进入 VIP 模板中心。"""
    results = []
    ok = 0
    for f in files:
        r = await _process_upload(f, is_vip=is_vip)
        results.append({"filename": f.filename, "ok": r.get("ok", False),
                        "id": r.get("id"), "name": r.get("name"),
                        "error": r.get("error", "")})
        if r.get("ok"):
            ok += 1
    return {"message": f"成功导入 {ok}/{len(files)} 套模板",
            "count": ok, "total": len(files), "results": results}


@app.get("/admin/templates/list")
def admin_templates(_: None = Depends(_require_admin_header)):
    """管理员视角：全部模板（含待审核/下架），附审核状态与校验报告。"""
    rows = db.admin_list_templates()
    result = []
    for r in rows:
        result.append({
            "id": r["id"], "name": r["name"], "description": r["description"],
            "is_active": r.get("is_active", 1),
            "is_vip": r.get("is_vip", 0),
            # 是否可在编辑器「更换模板」中使用（0 = 仅首页展示/下载）
            "editable": 1 if r.get("editable") is None else int(r["editable"]),
            "display_id": r.get("display_id") or r["id"],
            "review_status": r.get("review_status") or "approved",
            "validation_report": r.get("validation_report"),
            "config": r.get("config") or {},
            "created_at": str(r.get("created_at")) if r.get("created_at") else "",
        })
    return {"templates": result}


@app.post("/admin/templates/{template_id}/review")
def review_template(
    template_id: int,
    action: str = Form(...),
    _: None = Depends(_require_admin_header),
):
    """人工审核：action = approve（通过上架）| reject（拒绝）。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        # 待审核模板 is_active=0，get_template 查不到，改用 admin 列表查
        rows = db.admin_list_templates()
        tpl = next((r for r in rows if r["id"] == template_id), None)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    if action == "approve":
        # 审核通过前重新体检，确保报告反映模板当前状态（含自动补占位符结果）
        from utils import validator as _validator
        try:
            cfg = tpl.get("config") or {}
            if cfg.get("render_mode") == "flow":
                vresult = _validator.validate_flow_template(cfg)
            else:
                vresult = _validator.validate_template_file(BASE_DIR / tpl["file_path"])
            db.save_validation_report(template_id, json.dumps(_json_safe(vresult), ensure_ascii=False))
            applog.log("template_validate", template_id=template_id, ok=vresult["ok"],
                       fails=[c["name"] for c in vresult["checks"] if not c["ok"]])
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] 审核前体检失败: {exc}")
        db.set_review(template_id, "approved", 1)
        applog.log("template_review", template_id=template_id, action="approve")
        return {"message": "已通过审核，模板上架"}
    if action == "reject":
        db.set_review(template_id, "rejected", 0)
        applog.log("template_review", template_id=template_id, action="reject")
        return {"message": "已拒绝该模板"}
    raise HTTPException(status_code=400, detail="action 仅支持 approve / reject")


@app.post("/admin/templates/{template_id}/vip")
def set_template_vip(template_id: int,
                     is_vip: int = Form(...),
                     _: None = Depends(_require_admin_header)):
    """切换模板是否为 VIP：is_vip=1 加入 VIP 模板中心，=0 移回免费模板。"""
    if is_vip not in (0, 1):
        raise HTTPException(status_code=400, detail="is_vip 仅支持 0 / 1")
    if not db.set_template_vip(template_id, is_vip):
        raise HTTPException(status_code=404, detail="模板不存在或已下架")
    applog.log("template_vip", template_id=template_id, is_vip=is_vip)
    _sync_after_renumber()
    return {"message": "已加入 VIP 模板中心" if is_vip else "已移出 VIP 模板中心"}


@app.post("/admin/templates/{template_id}/editable")
def set_template_editable(template_id: int,
                          editable: int = Form(...),
                          _: None = Depends(_require_admin_header)):
    """切换模板是否可在编辑器「更换模板」中被套用（不影响首页展示与下载）。

    editable=0 的模板仍然留在首页模板中心供浏览/下载，只是不再出现在
    编辑器的模板选择面板里 —— 用于把「结构与占位符不适配编辑器热区编辑」
    的模板从编辑器侧收敛掉，而不牺牲首页的模板数量。
    """
    if editable not in (0, 1):
        raise HTTPException(status_code=400, detail="editable 仅支持 0 / 1")
    if not db.set_template_editable(template_id, editable):
        raise HTTPException(status_code=404, detail="模板不存在或已下架")
    applog.log("template_editable", template_id=template_id, editable=editable)
    return {"message": "已允许在编辑器中使用" if editable else "已从编辑器模板库移除"}


@app.post("/admin/templates/editable/batch")
def batch_set_template_editable(ids: str = Form(...),
                                editable: int = Form(...),
                                _: None = Depends(_require_admin_header)):
    """批量设置编辑器可用性。``ids`` 为逗号分隔的模板 id。

    模板可用性探测一次会判定几十个模板，逐个提交太慢，故提供批量入口。
    """
    if editable not in (0, 1):
        raise HTTPException(status_code=400, detail="editable 仅支持 0 / 1")
    try:
        id_list = [int(x) for x in re.split(r"[,\s，]+", ids.strip()) if x]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids 必须是逗号分隔的整数")
    if not id_list:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    n = db.set_templates_editable(id_list, editable)
    applog.log("template_editable_batch", count=n, editable=editable)
    return {"message": "已更新 %d 个模板" % n, "affected": n}


@app.delete("/admin/templates/{template_id}")
def delete_template(template_id: int, _: None = Depends(_require_admin_header)):
    """软删除模板。"""
    if not db.soft_delete_template(template_id):
        raise HTTPException(status_code=404, detail="模板不存在或已删除")
    mapping = _sync_after_renumber()
    applog.log("template_delete", template_id=template_id)
    return {"message": "模板已删除" + ("，序号已自动重排" if mapping else "")}


@app.post("/admin/templates/batch")
def batch_templates(
    action: str = Form(...),
    ids: str = Form(...),
    _: None = Depends(_require_admin_header),
):
    """批量操作：action = approve（批量通过上架）| delete（批量删除）。"""
    try:
        id_list = [int(x) for x in ids.replace("，", ",").split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids 格式错误")
    if not id_list:
        raise HTTPException(status_code=400, detail="请先选择模板")
    id_list = list(dict.fromkeys(id_list))  # 去重保序
    if action == "approve":
        ok_count = 0
        for tid in id_list:
            tpl = db.get_template(tid)
            if tpl is None:
                rows = db.admin_list_templates()
                tpl = next((r for r in rows if r["id"] == tid), None)
            if tpl is None:
                continue
            db.set_review(tid, "approved", 1)
            ok_count += 1
            applog.log("template_review", template_id=tid, action="approve(batch)")
        return {"message": f"已批量通过 {ok_count} 套模板", "count": ok_count}
    if action == "delete":
        ok_count = 0
        for tid in id_list:
            if db.soft_delete_template(tid):
                ok_count += 1
                applog.log("template_delete", template_id=tid, batch=True)
        _sync_after_renumber()
        return {"message": f"已批量删除 {ok_count} 套模板，序号已自动重排", "count": ok_count}
    raise HTTPException(status_code=400, detail="action 仅支持 approve / delete")


@app.get("/admin/templates/{template_id}/config")
def get_template_config(template_id: int, _: None = Depends(_require_admin_header)):
    """返回模板完整配置（含各模块字数限制）。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    tpl["modules"] = db.get_placeholders(template_id)
    return tpl


@app.get("/admin/templates/{template_id}/validate")
def validate_template_admin(template_id: int, _: None = Depends(_require_admin_header)):
    """重新校验模板（长内容渲染体检），返回各检查项结果。"""
    from utils import validator
    tpl = db.get_template(template_id)
    if tpl is None:
        # 待审核模板 is_active=0，get_template 查不到，改用 admin 列表查
        rows = db.admin_list_templates()
        tpl = next((r for r in rows if r["id"] == template_id), None)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    cfg = tpl.get("config") or {}
    if cfg.get("render_mode") == "flow":
        result = validator.validate_flow_template(cfg)
    else:
        result = validator.validate_template_file(BASE_DIR / tpl["file_path"])
    db.save_validation_report(template_id, json.dumps(_json_safe(result), ensure_ascii=False))
    applog.log("template_validate", template_id=template_id, ok=result["ok"],
               fails=[c["name"] for c in result["checks"] if not c["ok"]])
    return {"template_id": template_id, "ok": result["ok"], "checks": result["checks"]}


def _admin_template_row(template_id: int) -> dict:
    """查询模板（含待审核），不存在抛 404。"""
    tpl = db.get_template(template_id)
    if tpl is None:
        rows = db.admin_list_templates()
        tpl = next((r for r in rows if r["id"] == template_id), None)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    return tpl


@app.get("/admin/templates/{template_id}/mapping")
def get_template_mapping(template_id: int, _: None = Depends(_require_admin_header)):
    """返回模板板块/字段自动识别结果与已保存的手动绑定配置。"""
    from docx import Document
    from utils import filler, section_mapper
    tpl = _admin_template_row(template_id)
    tpl_file = BASE_DIR / tpl["file_path"]
    if not tpl_file.exists():
        raise HTTPException(status_code=404, detail="模板文件缺失")
    cfg = tpl.get("config") or {}
    bindings = cfg.get("bindings") or {}
    doc = Document(str(tpl_file))
    filler._remove_fallback_duplicates(doc)
    detected = section_mapper.detect_mapping(doc, bindings)
    return {"template_id": template_id, "bindings": bindings, "detected": detected}


@app.post("/admin/templates/{template_id}/mapping")
def save_template_mapping(template_id: int, bindings: str = Form("{}"),
                          _: None = Depends(_require_admin_header)):
    """保存模板板块/字段手动绑定（bindings JSON：{"sections": {...}, "fields": {...}}）。"""
    try:
        data = json.loads(bindings or "{}")
        assert isinstance(data, dict)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="bindings 格式错误")
    cleaned = {"sections": {}, "fields": {}}
    for group in ("sections", "fields"):
        for k, v in (data.get(group) or {}).items():
            if isinstance(v, str) and v.strip():
                cleaned[group][str(k).strip()] = v.strip()
    tpl = _admin_template_row(template_id)
    cfg = dict(tpl.get("config") or {})
    cfg["bindings"] = cleaned
    db.update_template_config(template_id, json.dumps(cfg, ensure_ascii=False))
    applog.log("template_mapping_save", template_id=template_id,
               sections=len(cleaned["sections"]), fields=len(cleaned["fields"]))
    return {"ok": True, "bindings": cleaned}


# ── 全局同义词库（后台维护）──


@app.get("/admin/aliases")
def list_aliases_admin(_: None = Depends(_require_admin_header)):
    """返回全部自定义同义词。"""
    return {"aliases": db.list_aliases()}


@app.post("/admin/aliases")
def add_alias_admin(kind: str = Form(...), std_key: str = Form(...),
                    alias: str = Form(...), _: None = Depends(_require_admin_header)):
    """新增同义词：kind=section（板块）| field（字段），全局模板立即生效。"""
    kind = (kind or "").strip().lower()
    if kind not in ("section", "field"):
        raise HTTPException(status_code=400, detail="kind 仅支持 section / field")
    std_key = (std_key or "").strip()
    alias = (alias or "").strip()
    if not std_key or not alias:
        raise HTTPException(status_code=400, detail="请填写标准 key 与同义词")
    if not db.add_alias(kind, std_key, alias):
        raise HTTPException(status_code=400, detail="该同义词已存在")
    from utils import standard_keys
    standard_keys.refresh_aliases()
    applog.log("alias_add", kind=kind, std_key=std_key, alias=alias)
    return {"ok": True}


@app.delete("/admin/aliases/{alias_id}")
def delete_alias_admin(alias_id: int, _: None = Depends(_require_admin_header)):
    """删除同义词。"""
    if not db.delete_alias(alias_id):
        raise HTTPException(status_code=404, detail="同义词不存在")
    from utils import standard_keys
    standard_keys.refresh_aliases()
    applog.log("alias_delete", alias_id=alias_id)
    return {"ok": True}


# ══════════════════ 简历优化 ══════════════════


def _resolve_template(template_id: Optional[int]) -> dict:
    """解析 template_id：无效时回退到第一个有效模板。"""
    if template_id is not None:
        tpl = db.get_template(template_id)
        if tpl:
            return tpl
    rows = db.list_templates()
    if not rows:
        raise HTTPException(status_code=400,
                            detail="模板库为空，请先联系管理员上传模板")
    return db.get_template(rows[0]["id"])


def _mapped_blank_fields(std_map: Optional[dict]):
    """映射填充模板中留白的标准字段（供前端「点击补充信息」）。"""
    if not std_map:
        return None
    labels = {
        "name": "姓名", "age": "年龄", "education_degree": "学历",
        "phone": "手机号", "email": "邮箱", "wechat": "微信",
        "address": "详细地址", "intention_job": "求职意向", "city": "现居城市",
        "political_status": "政治面貌", "education_info": "教育背景",
        "work_history": "工作履历", "skill_info": "技能合集",
        "campus_exp": "校园经历", "honor_cert": "证书荣誉",
        "self_evaluate": "自我评价",
    }
    return [{"key": k, "label": labels.get(k, k)}
            for k, v in std_map.items() if not str(v or "").strip()]


def _extract_resume_text(temp_path: Path) -> str:
    """按扩展名提取简历纯文本（PDF 含 OCR 兜底，图片直接 OCR）。"""
    suffix = temp_path.suffix.lower()
    if suffix == ".pdf":
        raw = converter.pdf_to_text(temp_path)
        if len(raw.strip()) < 100:
            print(f"[INFO] pdfplumber 提取不足 ({len(raw)} chars)，启用 OCR")
            raw = converter.pdf_to_text_ocr(temp_path)
        if len(raw.strip()) < 50:
            raise HTTPException(status_code=400, detail="PDF 内容提取失败，请尝试上传 Word 格式简历")
        return raw
    if suffix == ".docx":
        raw = editor.docx_to_text(temp_path)
        if len(raw.strip()) < 50:
            raise HTTPException(status_code=400, detail="Word 文档内容为空，请检查文件")
        return raw
    if suffix == ".txt":
        raw = parser.extract_text_from_txt(temp_path)
        if len(raw.strip()) < 50:
            raise HTTPException(status_code=400, detail="文本内容为空，请检查文件")
        return raw
    # 图片 → OCR
    raw = converter.image_to_text(temp_path)
    if len(raw.strip()) < 50:
        raise HTTPException(status_code=400, detail="图片 OCR 识别失败，请上传更清晰的图片")
    return raw


# 已停用（2026-08-09）：上传简历一键优化改为「选模板→编辑器→生成」流程
# @app.post("/optimize")
async def optimize(
    resume: UploadFile = File(...),
    job_description: UploadFile = File(None),
    job_text: str = Form(None),
    template_id: int = Form(None),
    strength: str = Form("均衡"),
    merge_mode: str = Form("merge"),
    _: dict = Depends(_require_user),
):
    """上传简历 + 岗位描述 + 模板ID，返回 session_id 与内容预览。"""
    t_start = _time.monotonic()
    applog.log("optimize_start",
               resume_name=(resume.filename or ""),
               template_id=template_id,
               job_mode="text" if job_text and job_text.strip() else "file")
    _gc_sessions()
    temp_path = None
    photo_path = None
    out_path = None
    try:
        suffix = (Path(resume.filename or "").suffix or "").lower()
        if suffix not in RESUME_EXTS:
            raise HTTPException(status_code=400,
                                detail="简历仅支持 PDF / Word(docx) / 文本 / 图片格式")

        # 1. 保存简历到 temp/
        temp_path = TEMP_DIR / f"{uuid.uuid4().hex}{suffix}"
        temp_path.write_bytes(await _read_limited(resume))

        # 2. 岗位描述：优先 job_text，否则从 job_description 文件解析
        if job_text and job_text.strip():
            job_desc = job_text.strip()
        elif job_description is not None:
            job_suffix = (Path(job_description.filename or "").suffix or "").lower()
            if job_suffix not in (".pdf", ".docx", ".txt"):
                raise HTTPException(status_code=400, detail="岗位描述仅支持 PDF / Word / txt")
            job_path = TEMP_DIR / f"{uuid.uuid4().hex}{job_suffix}"
            job_path.write_bytes(await _read_limited(job_description))
            try:
                job_desc = parser.parse_resume(str(job_path))
            finally:
                safe_unlink(job_path)
        else:
            raise HTTPException(status_code=400, detail="请提供岗位描述（文本或文件）")

        # 3. 提取简历纯文本
        raw_text = _extract_resume_text(temp_path)
        print(f"[INFO] 提取到 {len(raw_text)} chars 文本")

        # 4. 提取证件照（保留原简历照片，可选）
        photo_path = TEMP_DIR / f"photo_{uuid.uuid4().hex}.png"
        extracted_photo = converter.extract_photo(temp_path, photo_path)
        if extracted_photo:
            print(f"[INFO] 提取到证件照: {extracted_photo}")
        else:
            photo_path = None
            print("[INFO] 未检测到证件照")

        # 5. 选择模板并组装字数限制
        tpl = _resolve_template(template_id)
        word_limits = db.build_word_limits(tpl["id"])
        # 始终合并系统默认模块字数：即使模板没有某板块占位符，
        # LLM 也要完整提取教育/工作/技能/项目/自我评价等全部标准板块，
        # 供映射填充/板块重定向使用（模板特定配置优先）
        _default_limits = {
            m["module_key"]: {
                "label": m["label"],
                "min_words": m["min_words"],
                "max_words": m["max_words"],
            }
            for m in db.DEFAULT_MODULES
        }
        for _k, _v in _default_limits.items():
            word_limits.setdefault(_k, _v)
        print(f"[INFO] 使用模板: {tpl['name']} (id={tpl['id']}), "
              f"模块数={len(word_limits)}")
        applog.log("template_selected", template_id=tpl["id"], template_name=tpl["name"],
                   modules=len(word_limits))

        # 6. 调用 LLM 生成结构化内容
        try:
            # 前置篇幅估算：内容过长时给模型明确字数上限（生成即适配单页）
            resume_len = len(raw_text.strip())
            if resume_len > 1300:
                target_chars = 1050
            elif resume_len > 1000:
                target_chars = 1000
            else:
                target_chars = 0
            applog.log("llm_start", template_id=tpl["id"], strength=strength,
                       resume_chars=resume_len, target_chars=target_chars)
            data = llm.generate_structured_content(
                raw_text, job_desc, word_limits,
                strength=strength, target_chars=target_chars,
            )
        except RuntimeError as e:
            print(f"[ERROR] LLM 调用失败: {e}")
            raise HTTPException(status_code=502,
                                detail="AI 优化服务暂时不可用，请稍后重试")

        # 7. 组件标准化（所有模板统一生效，防止长列表挤爆单页）：
        #    - 主修课程：精简为「核心课程：xxx、xxx、xxx」单行（保留3-4门核心课程）
        #    - 专业技能：压缩为分类标签行，去掉冗余描述
        #    - 自我评价：压缩为一段
        #    只动次要模块，绝不触碰工作/实习经历内容。
        import re as _re
        for module_key in ("education", "skills", "summary"):
            raw = str(data.get(module_key) or "").strip()
            if not raw:
                continue
            if module_key == "education":
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                if lines:
                    first = lines[0]
                    course_parts = []
                    for ln in lines[1:]:
                        ln2 = _re.sub(r"^(主修课程|核心课程|课程)[：:]?\s*", "", ln)
                        course_parts.extend(x.strip() for x in ln2.replace("，", "、").replace(",", "、").split("、") if x.strip())
                    if course_parts:
                        # 完整保留主修课程（不再砍到4门，避免丢失 Linux/数据库/ETL 等）
                        data[module_key] = first + "\n主修课程：" + "、".join(course_parts[:12])
                    else:
                        data[module_key] = first
            elif module_key == "skills":
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                kept = []
                for ln in lines:
                    m = _re.match(r"^([^：:]{2,12})[：:]\s*(.+)$", ln)
                    if m:
                        kept.append(m.group(1) + "：" + m.group(2)[:40])
                    elif len(ln) <= 45:
                        kept.append(ln)
                data[module_key] = "\n".join(kept[:5])
            else:  # summary
                parts = [p.strip() for p in raw.splitlines() if p.strip()]
                data[module_key] = " ".join(parts)[:170]

        # 8. 组装占位符映射并填充模板
        content_map = {}
        for ph in db.get_placeholders(tpl["id"]):
            content_map[ph["label"]] = data.get(ph["module_key"], "")
        # 标准英文标签兼容（{{name}}/{{work_experience}}/{{education}} 等）
        _EN_LABELS = {
            "name": "姓名", "contact": "联系方式", "job_title": "求职意向",
            "summary": "个人优势", "work_experience": "工作经历", "projects": "项目经历",
            "education": "教育背景", "skills": "专业技能", "political_status": "政治面貌",
            "phone": "电话", "email": "邮箱", "location": "所在地",
        }
        for en, zh in _EN_LABELS.items():
            content_map.setdefault(en, content_map.get(zh, ""))
        # 标准基础字段补充进 content_map（供硬编码字段行回填）：
        # 模板无占位符的民族/性别/出生年月/籍贯/毕业院校/年龄/学历等
        for _std_label, _std_key in (
                ("性别", "gender"), ("民族", "nation"), ("出生年月", "birth_date"),
                ("出生日期", "birth_date"), ("籍贯", "hometown"), ("毕业院校", "school"),
                ("学校", "school"), ("年龄", "age"), ("学历", "education_degree"),
                ("微信", "wechat"), ("现居地址", "address"), ("现居", "city"),
                ("所在城市", "city"), ("身高", "height"), ("专业", "major"),
                ("期望薪资", "salary"), ("到岗时间", "arrive_time"), ("GPA", "gpa"),
                ("绩点", "gpa"), ("兴趣爱好", "hobby"), ("爱好", "hobby")):
            if not content_map.get(_std_label):
                content_map[_std_label] = str(data.get(_std_key, "") or "").strip()
        # 大模块默认标签也补进 content_map（模板无对应占位符时供板块重定向/回填使用）
        for _mod_label, _mod_key in (
                ("教育背景", "education"), ("工作经历", "work_experience"),
                ("专业技能", "skills"), ("个人优势", "summary"),
                ("校园经历", "campus_exp"), ("证书荣誉", "honor_cert"),
                ("项目经历", "projects")):
            if not content_map.get(_mod_label):
                content_map[_mod_label] = str(data.get(_mod_key, "") or "").strip()
        if data.get("name"):
            content_map.setdefault("姓名", data["name"])
            content_map.setdefault("name", data["name"])
        if data.get("contact"):
            content_map.setdefault("联系方式", data["contact"])
            content_map.setdefault("contact", data["contact"])
            # 从联系方式字符串中拆出电话/邮箱，供模板"电话：{{电话}} / 邮箱：{{邮箱}}"使用
            import re as _re
            phone_m = _re.search(r"\+?[\d\- ]{7,16}", data["contact"])
            email_m = _re.search(r"[\w.+-]+@[\w.-]+\.\w+", data["contact"])
            if phone_m:
                # 直接覆盖（占位符配置可能已把整个联系方式写入"电话"，必须拆开）
                content_map["电话"] = phone_m.group(0).strip()
                content_map["phone"] = content_map["电话"]
            if email_m:
                content_map["邮箱"] = email_m.group(0).strip()
                content_map["email"] = content_map["邮箱"]
        if data.get("job_title"):
            content_map.setdefault("求职意向", data["job_title"])
            content_map.setdefault("job_title", data["job_title"])
        if data.get("political_status"):
            content_map.setdefault("政治面貌", data["political_status"])
            content_map.setdefault("political_status", data["political_status"])

        tpl_file = BASE_DIR / tpl["file_path"]
        tpl_config = tpl.get("config") or {}
        # 9. 单页预精简（文件模板无流式压缩兜底，内容过长时先按规则精简次要模块）：
        #    仅压缩主修课程/技能/自我评价，绝不触碰工作/实习/项目经历。
        if tpl_config.get("render_mode") != "flow":
            total_chars = sum(len(str(v or "")) for v in data.values())
            if total_chars > 950:
                _trim_secondary(data)
                applog.log("content_trim", template_id=tpl["id"], before=total_chars,
                           after=sum(len(str(v or "")) for v in data.values()))

        out_path = TEMP_DIR / f"optimized_{uuid.uuid4().hex}.docx"
        if tpl_config.get("render_mode") == "flow":
            # 流式引擎渲染：按配置自动排版，无需依赖模板文件
            from utils.template_render import render_template
            render_stats = render_template(data, tpl_config, photo_path, out_path)
            fill_stats = {
                "render_mode": "flow",
                "textbox_based": False,
                "reflow": {"reflowed": False, "total_chars": sum(len(str(v or "")) for v in data.values())},
                "photo_replaced": photo_path is not None,
                **{k: v for k, v in render_stats.items() if k != "path"},
            }
        else:
            primary_color = tpl_config.get("primary_color") or "#5B5CFF"
            preserve_layout = bool(tpl_config.get("preserve_layout", True))
            # 无 {{占位符}} 的模板（硬编码文本框模板）→ 系统标准 key 映射填充：
            # 有数据填充、无数据留白、保留模板标签；校园/荣誉按 merge_mode 合并
            if not _scan_placeholders(tpl_file):
                from utils import standard_keys
                std_map = standard_keys.build_standard_content(data)
                bindings = tpl_config.get("bindings") or {}
                fill_stats = filler.fill_mapped_template(
                    std_map, tpl_file, out_path, photo_path,
                    primary_color=primary_color, merge_mode=merge_mode or "merge",
                    bindings=bindings, preserve_layout=preserve_layout)
            else:
                std_map = None
                fill_stats = filler.fill_template(content_map, tpl_file, out_path, photo_path,
                                                  primary_color=primary_color,
                                                  preserve_layout=preserve_layout)
        applog.log("fill_done", template_id=tpl["id"], **{
            k: v for k, v in fill_stats.items() if k != "path"
        })

        # 8. 生成预览文本并返回 session
        preview_text = editor.docx_to_text(out_path)
        session_id = str(uuid.uuid4())
        layout_info = None
        if tpl_config.get("render_mode") == "flow":
            layout_info = fill_stats
        sessions[session_id] = {
            "path": str(out_path),
            "time": time.time(),
            "data": data,
            "job_desc": job_desc,
            "template_config": tpl_config,
            "layout": layout_info,
            "std_map": std_map,
            "template_path": str(tpl_file),
        }
        # 保留证件照副本，供「重建」使用
        if photo_path is not None and Path(str(photo_path)).exists():
            import shutil
            session_photo = TEMP_DIR / f"session_photo_{session_id}.png"
            shutil.copyfile(str(photo_path), str(session_photo))
            sessions[session_id]["photo"] = str(session_photo)
        # 导出前体检：生成提示信息
        warnings = []
        if photo_path is None:
            warnings.append("未检测到证件照，照片位将自动隐藏")
        reflow_stats = fill_stats.get("reflow") or {}
        if fill_stats.get("textbox_based") and reflow_stats.get("total_chars", 0) > 1300:
            warnings.append("内容较多，已自动压缩字号与间距以适配一页，建议适当精简经历描述")
        elif not fill_stats.get("textbox_based") and len(preview_text) > 1200:
            warnings.append("内容较多，已压缩排版，建议适当精简")
        # 输出自检：无残留占位符 + 固定信息（姓名/电话）完整性
        try:
            from utils import filler as _filler
            _expect = {}
            if std_map:
                if std_map.get("name"):
                    _expect["姓名"] = std_map["name"]
                if std_map.get("phone"):
                    _expect["手机"] = std_map["phone"]
            else:
                if content_map.get("姓名"):
                    _expect["姓名"] = content_map["姓名"]
                if content_map.get("电话"):
                    _expect["电话"] = content_map["电话"]
            warnings.extend(_filler.verify_fill(out_path, _expect))
        except Exception:  # noqa: BLE001 自检失败不影响主流程
            pass
        applog.log("optimize_done",
                   session_id=session_id,
                   template_id=tpl["id"],
                   duration_ms=round((_time.monotonic() - t_start) * 1000),
                   text_chars=len(preview_text),
                   structured_keys=sorted(data.keys()),
                   warnings=warnings)
        return {
            "session_id": session_id,
            "template_id": tpl["id"],
            "template_name": tpl["name"],
            "preview": preview_text[:300],
            "optimized_text": preview_text,
            "structured": data,
            "warnings": warnings,
            "layout": layout_info,
            "mapped_blank_fields": _mapped_blank_fields(std_map),
        }
    finally:
        safe_unlink(temp_path, photo_path)
        # out_path 保留给下载接口使用，由 session GC 清理


@app.get("/download/{session_id}")
def download(session_id: str, format: str = "docx", _: dict = Depends(_require_user)):
    _gc_sessions()
    v = sessions.get(session_id)
    if v is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新优化")
    docx_path = Path(v["path"])
    if not docx_path.exists():
        sessions.pop(session_id, None)
        raise HTTPException(status_code=404, detail="文件已失效，请重新优化")

    fmt = (format or "docx").lower()
    if fmt == "pdf":
        pdf_path = docx_path.with_suffix(".pdf")
        converter.docx_to_pdf(docx_path, pdf_path)
        applog.log("download", session_id=session_id, format="pdf",
                   size=pdf_path.stat().st_size if pdf_path.exists() else 0)
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename="optimized_resume.pdf",
        )
    if fmt == "docx":
        applog.log("download", session_id=session_id, format="docx",
                   size=docx_path.stat().st_size if docx_path.exists() else 0)
        return FileResponse(
            str(docx_path),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="optimized_resume.docx",
        )
    raise HTTPException(status_code=400, detail="不支持的下载格式，仅支持 docx / pdf")


# 已停用：旧精简建议接口（随上传流程移除）
# @app.post("/optimize/trim-proposal")
def trim_proposal(session_id: str = Form(...), _: dict = Depends(_require_user)):
    """对已优化会话生成「原文 vs 精简版」对比建议（大模型定向精简）。"""
    _gc_sessions()
    v = sessions.get(session_id)
    if v is None or "data" not in v:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新优化")
    data = v["data"]
    job_desc = v.get("job_desc", "")
    try:
        trimmed = llm.trim_content(data, job_desc)
    except Exception as exc:  # noqa: BLE001
        applog.log("trim_error", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="精简服务暂时不可用，请稍后重试")
    proposal = []
    for key, new_text in trimmed.items():
        proposal.append({
            "module": key,
            "label": {"summary": "个人优势", "projects": "项目经历",
                      "education": "教育背景", "skills": "专业技能"}.get(key, key),
            "before": data.get(key, ""),
            "after": new_text,
        })
    applog.log("trim_proposal", session_id=session_id, modules=[p["module"] for p in proposal])
    return {"proposal": proposal}


# 已停用：旧重建接口（随上传流程移除）
# @app.post("/optimize/rebuild")
def rebuild_resume(
    session_id: str = Form(...),
    overrides: str = Form("{}"),
    shrink_font: int = Form(0),
    _: dict = Depends(_require_user),
):
    """按用户选择重建简历：应用精简模块 和/或 强制缩小字号。"""
    import json as _json
    _gc_sessions()
    v = sessions.get(session_id)
    if v is None or "data" not in v:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新优化")
    data = dict(v["data"])
    try:
        ov = _json.loads(overrides)
        assert isinstance(ov, dict)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="overrides 参数格式错误")
    for key, text in ov.items():
        if isinstance(text, str) and text.strip():
            data[key] = text.strip()
    tpl_config = v.get("template_config") or {}
    out_path = TEMP_DIR / f"optimized_{uuid.uuid4().hex}.docx"
    if tpl_config.get("render_mode") == "flow":
        from utils.template_render import render_template
        stats = render_template(data, tpl_config, v.get("photo"), out_path,
                                force_squeeze=bool(shrink_font))
    else:
        raise HTTPException(status_code=400, detail="该模板不支持重建，请重新优化")
    preview_text = editor.docx_to_text(out_path)
    new_session = str(uuid.uuid4())
    sessions[new_session] = {
        "path": str(out_path),
        "time": time.time(),
        "data": data,
        "job_desc": v.get("job_desc", ""),
        "template_config": tpl_config,
        "layout": stats,
    }
    applog.log("rebuild_done", session_id=session_id, new_session=new_session,
               overrides=sorted(ov.keys()), shrink_font=bool(shrink_font))
    return {
        "session_id": new_session,
        "preview": preview_text[:300],
        "optimized_text": preview_text,
        "structured": data,
        "layout": stats,
    }


@app.post("/optimize/mapped-fill")
def mapped_fill(
    session_id: str = Form(...),
    overrides: str = Form("{}"),
    merge_mode: str = Form("merge"),
    _: dict = Depends(_require_user),
):
    """映射模板：按用户补充的标准字段重新填充（空白字段「点击补充信息」）。"""
    import json as _json
    _gc_sessions()
    v = sessions.get(session_id)
    if v is None or not v.get("std_map"):
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新优化")
    try:
        ov = _json.loads(overrides or "{}")
        assert isinstance(ov, dict)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="overrides 格式错误")
    std = dict(v["std_map"])
    for key, text in ov.items():
        if isinstance(key, str) and isinstance(text, str):
            std[key] = text.strip()
    tpl_config = v.get("template_config") or {}
    preserve_layout = bool(tpl_config.get("preserve_layout", True))
    out_path = TEMP_DIR / f"optimized_{uuid.uuid4().hex}.docx"
    try:
        fill_stats = filler.fill_mapped_template(
            std, v["template_path"], out_path, v.get("photo"),
            primary_color=tpl_config.get("primary_color") or "#5B5CFF",
            merge_mode=merge_mode or "merge",
            bindings=tpl_config.get("bindings") or {},
            preserve_layout=preserve_layout)
    except Exception as exc:  # noqa: BLE001
        applog.log("mapped_fill_error", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="重新填充失败，请稍后重试")
    preview_text = editor.docx_to_text(out_path)
    new_session = str(uuid.uuid4())
    sessions[new_session] = {
        "path": str(out_path), "time": time.time(),
        "data": v.get("data"), "job_desc": v.get("job_desc", ""),
        "template_config": tpl_config, "layout": fill_stats,
        "std_map": std, "template_path": v.get("template_path"),
        "photo": v.get("photo"),
    }
    applog.log("mapped_fill", session_id=session_id, new_session=new_session,
               overrides=sorted(ov.keys()), merge_mode=merge_mode)
    return {
        "session_id": new_session,
        "optimized_text": preview_text,
        "mapped_blank_fields": _mapped_blank_fields(std),
        "layout": fill_stats,
    }


# ══════════════════ 模板渲染（内容字典 → 生成） ══════════════════


_PH_TO_STD = {
    "姓名": "name", "年龄": "age", "性别": "gender", "民族": "nation",
    "出生年月": "birth_date", "出生日期": "birth_date", "身高": "height",
    "籍贯": "hometown", "学历": "education_degree", "专业": "major",
    "毕业院校": "school", "政治面貌": "political_status", "电话": "phone",
    "邮箱": "email", "微信": "wechat", "现居": "city", "现居地": "city",
    "所在地": "city", "求职意向": "intention_job", "期望薪资": "salary",
    "到岗时间": "arrive_time", "GPA": "gpa", "绩点": "gpa",
    "兴趣爱好": "hobby", "爱好": "hobby", "教育背景": "education_info",
    "工作经历": "work_history", "工作经验": "work_history",
    "个人优势": "self_evaluate", "自我评价": "self_evaluate",
    "专业技能": "skill_info", "校园经历": "campus_exp",
    "证书荣誉": "honor_cert", "项目经历": "projects",
}

def _build_content_map_from_data(data: dict, tpl: dict) -> dict:
    """把标准结构 data 组装成占位符模板的 content_map（与 optimize 流程一致）。"""
    content_map = {}
    for ph in db.get_placeholders(tpl["id"]):
        content_map[ph["label"]] = data.get(ph["module_key"], "")
    en = {"name": "姓名", "contact": "联系方式", "job_title": "求职意向",
          "summary": "个人优势", "work_experience": "工作经历", "projects": "项目经历",
          "education": "教育背景", "skills": "专业技能", "political_status": "政治面貌",
          "phone": "电话", "email": "邮箱", "location": "所在地"}
    for enk, zh in en.items():
        content_map.setdefault(enk, content_map.get(zh, ""))
    std = standard_keys.build_standard_content(data)
    for label, std_key in _PH_TO_STD.items():
        if label in content_map and not content_map[label]:
            content_map[label] = std.get(std_key, "") or ""
        content_map.setdefault(label, std.get(std_key, "") or "")
    return content_map


@app.post("/api/render-preview")
def render_preview(template_id: int = Form(...), content: str = Form("{}")):
    """实时预览：把用户编辑的数据填入模板，生成第 1 页 PNG 缩略图返回 base64。
    不需要登录（编辑器是匿名态）。失败时降级返回静态预览图 URL。
    内置 LRU 缓存（最多 30 项），相同 data 不重复渲染。"""
    import base64 as _b64
    import hashlib as _hashlib
    import fitz as _fitz

    try:
        content = json.loads(content or "{}")
        assert isinstance(content, dict)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="content 格式错误")

    # LRU 缓存
    cache_key = _hashlib.md5(
        f"{template_id}|{json.dumps(content, sort_keys=True, ensure_ascii=False)}".encode("utf-8")
    ).hexdigest()
    cached = _PREVIEW_CACHE.get(cache_key)
    if cached:
        return {"png_b64": cached, "cached": True}

    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")

    # 复用 render_resume 的 data 构造
    data = {
        "name": content.get("name", ""), "age": content.get("age", ""),
        "gender": content.get("gender", ""), "nation": content.get("nation", ""),
        "birth_date": content.get("birth_date", ""), "height": content.get("height", ""),
        "hometown": content.get("hometown", ""),
        "education_degree": content.get("education_degree", ""),
        "major": content.get("major", ""), "school": content.get("school", ""),
        "political_status": content.get("political_status", ""),
        "wechat": content.get("wechat", ""),
        "salary": content.get("salary", ""), "arrive_time": content.get("arrive_time", ""),
        "gpa": content.get("gpa", ""), "hobby": content.get("hobby", ""),
        "job_title": content.get("intention_job", ""),
        "contact": " | ".join([x for x in (content.get("phone", ""), content.get("email", ""),
                                            content.get("city", "")) if x]),
        "education": content.get("education_info", ""),
        "work_experience": content.get("work_history", ""),
        "skills": content.get("skill_info", ""),
        "summary": content.get("self_evaluate", ""),
        "campus_exp": content.get("campus_exp", ""),
        "honor_cert": content.get("honor_cert", ""),
        "projects": content.get("projects", ""),
    }
    std_map = standard_keys.build_standard_content(data)
    tpl_file = BASE_DIR / tpl["file_path"]
    tpl_config = tpl.get("config") or {}
    preserve_layout = bool(tpl_config.get("preserve_layout", True))
    primary_color = tpl_config.get("primary_color") or "#5B5CFF"
    out_path = TEMP_DIR / f"preview_{uuid.uuid4().hex}.docx"
    pdf_path = TEMP_DIR / f"preview_{uuid.uuid4().hex}.pdf"

    try:
        if not _scan_placeholders(tpl_file):
            filler.fill_mapped_template(
                std_map, tpl_file, out_path, None, primary_color=primary_color,
                merge_mode="merge", bindings=tpl_config.get("bindings") or {},
                preserve_layout=preserve_layout)
        else:
            content_map = _build_content_map_from_data(data, tpl)
            filler.fill_template(
                content_map, tpl_file, out_path, None, primary_color=primary_color,
                preserve_layout=preserve_layout)

        # docx → pdf（用快速版，复用 Word 单例）
        converter.docx_to_pdf_fast(out_path, pdf_path)

        # pdf 第 1 页 → PNG（150 DPI，控制大小）
        doc = _fitz.open(str(pdf_path))
        try:
            page = doc[0]
            mat = _fitz.Matrix(150 / 72, 150 / 72)
            pix = page.get_pixmap(matrix=mat)
            png_bytes = pix.tobytes("png")
        finally:
            doc.close()

        png_b64 = "data:image/png;base64," + _b64.b64encode(png_bytes).decode("ascii")

        # LRU 缓存
        _PREVIEW_CACHE[cache_key] = png_b64
        _PREVIEW_CACHE_KEYS.append(cache_key)
        if len(_PREVIEW_CACHE_KEYS) > 30:
            old_key = _PREVIEW_CACHE_KEYS.pop(0)
            _PREVIEW_CACHE.pop(old_key, None)

        return {"png_b64": png_b64, "cached": False}

    except Exception as e:
        # 降级：返回静态预览图 URL
        preview_path = BASE_DIR / "static" / "previews" / f"t{template_id}.png"
        if preview_path.exists():
            return {"preview_url": f"/static/previews/t{template_id}.png?v=5",
                    "error": str(e), "fallback": True}
        raise HTTPException(status_code=500, detail=f"渲染失败: {e}")
    finally:
        # 清理临时文件（沙盒/Word 句柄都可能拒绝删除，safe_unlink 兜底）
        safe_unlink(out_path, pdf_path)


@app.post("/api/render-resume")
def render_resume(template_id: int = Form(...), content: str = Form("{}"),
                  merge_mode: str = Form("merge"),
                  _: dict = Depends(_require_user)):
    """按用户编辑内容渲染模板。content = {标准key: 文本}。"""
    try:
        content = json.loads(content or "{}")
        assert isinstance(content, dict)
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="content 格式错误")
    tpl = db.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    data = {
        "name": content.get("name", ""), "age": content.get("age", ""),
        "gender": content.get("gender", ""), "nation": content.get("nation", ""),
        "birth_date": content.get("birth_date", ""), "height": content.get("height", ""),
        "hometown": content.get("hometown", ""), "education_degree": content.get("education_degree", ""),
        "major": content.get("major", ""), "school": content.get("school", ""),
        "political_status": content.get("political_status", ""), "wechat": content.get("wechat", ""),
        "salary": content.get("salary", ""), "arrive_time": content.get("arrive_time", ""),
        "gpa": content.get("gpa", ""), "hobby": content.get("hobby", ""),
        "job_title": content.get("intention_job", ""),
        "contact": " | ".join([x for x in (content.get("phone", ""), content.get("email", ""),
                                           content.get("city", "")) if x]),
        "education": content.get("education_info", ""),
        "work_experience": content.get("work_history", ""),
        "skills": content.get("skill_info", ""),
        "summary": content.get("self_evaluate", ""),
        "campus_exp": content.get("campus_exp", ""),
        "honor_cert": content.get("honor_cert", ""),
        "projects": "",
    }
    std_map = standard_keys.build_standard_content(data)
    tpl_file = BASE_DIR / tpl["file_path"]
    tpl_config = tpl.get("config") or {}
    preserve_layout = bool(tpl_config.get("preserve_layout", True))
    primary_color = tpl_config.get("primary_color") or "#5B5CFF"
    out_path = TEMP_DIR / f"optimized_{uuid.uuid4().hex}.docx"
    if not _scan_placeholders(tpl_file):
        fill_stats = filler.fill_mapped_template(
            std_map, tpl_file, out_path, None, primary_color=primary_color,
            merge_mode=merge_mode or "merge",
            bindings=tpl_config.get("bindings") or {},
            preserve_layout=preserve_layout)
    else:
        content_map = _build_content_map_from_data(data, tpl)
        fill_stats = filler.fill_template(
            content_map, tpl_file, out_path, None, primary_color=primary_color,
            preserve_layout=preserve_layout)
    preview_text = editor.docx_to_text(out_path)
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        "path": str(out_path), "time": time.time(), "data": data,
        "template_config": tpl_config, "layout": fill_stats,
        "std_map": std_map, "template_path": str(tpl_file),
    }
    warnings = []
    try:
        warnings.extend(filler.verify_fill(out_path, {"姓名": data["name"]}))
    except Exception:
        pass
    applog.log("render_resume", template_id=template_id,
               session_id=session_id, fields=len(std_map))
    return {
        "session_id": session_id,
        "template_id": template_id,
        "template_name": tpl["name"],
        "optimized_text": preview_text,
        "warnings": warnings,
        "mapped_blank_fields": _mapped_blank_fields(std_map),
    }


@app.post("/api/optimize-experience-self")
def optimize_experience_self_api(jd: str = Form(""),
                                 experience: str = Form(""),
                                 self_evaluate: str = Form(""),
                                 extra: str = Form(""),
                                 mode: str = Form("full"),
                                 _: dict = Depends(_require_user)):
    """「简历经历 + 自我评价」优化（本地 Ollama 单版本，mode 仅兼容旧前端、忽略）。
    仅优化经历与自我评价，其余内容分毫不动。"""
    if not (jd or "").strip():
        raise HTTPException(status_code=400, detail="请粘贴完整招聘 JD（岗位职责 + 任职要求）")
    if not (experience or "").strip():
        raise HTTPException(status_code=400, detail="请填写原始工作/实习/项目经历")
    try:
        result = llm.optimize_experience_self(
            jd, experience, self_evaluate, extra=extra)
    except Exception as exc:  # noqa: BLE001
        applog.log("optimize_experience_self_error", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="AI 优化服务暂时不可用，请稍后重试")
    applog.log("optimize_experience_self", chars=len(result))
    return {"text": result}


@app.post("/api/ai-generate-resume")
def ai_generate_resume(data: dict = None, _: dict = Depends(_require_user)):
    """AI 从零生成整份简历：输入一句话描述 / JD / 目标岗位，返回 basic + modules 结构化内容。"""
    data = data or {}
    description = (data.get("description") or "") if isinstance(data, dict) else ""
    jd = (data.get("jd") or "") if isinstance(data, dict) else ""
    target_job = (data.get("target_job") or "") if isinstance(data, dict) else ""
    try:
        result = llm.generate_full_resume(description, jd, target_job)
    except Exception as exc:  # noqa: BLE001
        applog.log("ai_generate_resume_error", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="AI 生成服务暂时不可用，请稍后重试")
    if not result:
        raise HTTPException(status_code=502, detail="AI 生成失败，请补充更多个人信息或稍后重试")
    applog.log("ai_generate_resume", basic_keys=list((result.get("basic") or {}).keys()))
    return result


# ── 质量引擎：匹配度评分 / 事实核查审计 / 双Agent审查 / ATS文本层校验 ──
# quality 包不反向 import main，挂载于此处（app 已创建、全量路由已注册）无循环依赖。
from quality.router import router as quality_router
app.include_router(quality_router)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    applog.log("request_error", url=str(request.url), error=str(exc),
               error_type=type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": str(exc)})
