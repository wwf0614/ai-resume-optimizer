"""MySQL 数据访问层：模板库与占位符配置的增删查。

表结构（与设计说明第 5 节一致）：
- templates: 模板主表（软删除）
- template_placeholders: 模板各模块占位符与字数限制
"""
import json
import os
from contextlib import contextmanager
from typing import Dict, List, Optional

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "resume_app")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "resume_optimizer")

# 标准模块定义：module_key -> (默认中文名, 默认最小字数, 默认最大字数)
DEFAULT_MODULES: List[Dict[str, object]] = [
    {"module_key": "summary", "label": "个人优势", "min_words": 80, "max_words": 200},
    {"module_key": "work_experience", "label": "工作经历", "min_words": 150, "max_words": 400},
    {"module_key": "projects", "label": "项目经历", "min_words": 100, "max_words": 300},
    {"module_key": "education", "label": "教育背景", "min_words": 50, "max_words": 150},
    {"module_key": "skills", "label": "专业技能", "min_words": 50, "max_words": 150},
]

_CREATE_TEMPLATES_SQL = """
CREATE TABLE IF NOT EXISTS templates (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(500),
    file_path VARCHAR(500) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active TINYINT(1) DEFAULT 1,
    is_vip TINYINT(1) DEFAULT 0,
    display_id INT DEFAULT 0,
    editable TINYINT(1) DEFAULT 1,
    INDEX idx_is_active (is_active),
    INDEX idx_display (is_vip, display_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_CREATE_PLACEHOLDERS_SQL = """
CREATE TABLE IF NOT EXISTS template_placeholders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    template_id INT NOT NULL,
    module_key VARCHAR(50) NOT NULL,
    label VARCHAR(50) NOT NULL,
    min_words INT NOT NULL,
    max_words INT NOT NULL,
    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE,
    UNIQUE KEY unique_module_per_template (template_id, module_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    account VARCHAR(100) NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    nickname VARCHAR(50),
    is_admin TINYINT(1) DEFAULT 0,
    is_vip TINYINT(1) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login_at DATETIME,
    UNIQUE KEY unique_account (account)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_CREATE_ALIASES_SQL = """
CREATE TABLE IF NOT EXISTS standard_aliases (
    id INT PRIMARY KEY AUTO_INCREMENT,
    kind VARCHAR(20) NOT NULL,
    std_key VARCHAR(50) NOT NULL,
    alias VARCHAR(50) NOT NULL,
    UNIQUE KEY unique_alias (kind, alias)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


_CREATE_DRAFTS_SQL = """
CREATE TABLE IF NOT EXISTS resume_drafts (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    template_id INT,
    title VARCHAR(120) DEFAULT '',
    data_json LONGTEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_drafts_user (user_id, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


@contextmanager
def get_conn():
    """获取数据库连接的上下文管理器（自动提交/回滚/关闭）。"""
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建库建表（幂等）。连接时若库不存在则先创建。"""
    # 1. 连接服务器创建数据库（若不存在）
    root = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with root.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        root.close()

    # 2. 建表
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TEMPLATES_SQL)
            cur.execute(_CREATE_PLACEHOLDERS_SQL)
            cur.execute(_CREATE_USERS_SQL)
            cur.execute(_CREATE_ALIASES_SQL)
            cur.execute(_CREATE_DRAFTS_SQL)
            # 兼容旧库：补充用户管理员标记列
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'is_admin'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE users ADD COLUMN is_admin TINYINT(1) DEFAULT 0")
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'is_vip'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE users ADD COLUMN is_vip TINYINT(1) DEFAULT 0")
            # 3. 兼容旧库：补充模板配置列（主色/布局类型等）
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'templates' AND COLUMN_NAME = 'config'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE templates ADD COLUMN config TEXT NULL")
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'templates' AND COLUMN_NAME = 'review_status'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE templates ADD COLUMN review_status VARCHAR(20) DEFAULT 'approved'")
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'templates' AND COLUMN_NAME = 'validation_report'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE templates ADD COLUMN validation_report TEXT NULL")
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'templates' AND COLUMN_NAME = 'is_vip'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE templates ADD COLUMN is_vip TINYINT(1) DEFAULT 0")
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'templates' AND COLUMN_NAME = 'display_id'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE templates ADD COLUMN display_id INT DEFAULT 0")
                cur.execute("CREATE INDEX idx_display ON templates (is_vip, display_id)")
            # 兼容旧库：编辑器模板库可用性标记
            # editable=1 表示该模板可在编辑器「更换模板」中被套用；
            # 0 表示仅在首页模板中心展示/下载，不进编辑器。
            cur.execute(
                "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'templates' AND COLUMN_NAME = 'editable'",
                (DB_NAME,),
            )
            if cur.fetchone()["c"] == 0:
                cur.execute("ALTER TABLE templates ADD COLUMN editable TINYINT(1) DEFAULT 1")


# ── 用户 CRUD ──


def create_user(account: str, password_hash: str, nickname: str = "") -> int:
    """新增用户，返回用户 id；账号已存在时返回 0。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO users (account, password_hash, nickname) VALUES (%s, %s, %s)",
                    (account, password_hash, nickname or account.split("@")[0]),
                )
                return int(cur.lastrowid)
            except pymysql.err.IntegrityError:
                return 0


def create_admin(account: str, password_hash: str, nickname: str = "") -> int:
    """新增管理员账号（is_admin=1），返回用户 id；账号已存在时返回 0。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO users (account, password_hash, nickname, is_admin) "
                    "VALUES (%s, %s, %s, 1)",
                    (account, password_hash, nickname or account.split("@")[0]),
                )
                return int(cur.lastrowid)
            except pymysql.err.IntegrityError:
                return 0


def count_admins() -> int:
    """当前管理员账号数量。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_admin = 1")
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0


def get_admin_by_account(account: str) -> Optional[dict]:
    """按账号查询管理员（含密码哈希）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, account, password_hash, nickname, created_at, last_login_at "
                "FROM users WHERE account = %s AND is_admin = 1",
                (account,),
            )
            return cur.fetchone()


def get_user_by_account(account: str) -> Optional[dict]:
    """按账号（手机号/邮箱）查询用户。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, account, password_hash, nickname, is_vip, created_at, last_login_at "
                "FROM users WHERE account = %s",
                (account,),
            )
            return cur.fetchone()


def get_user_by_id(user_id: int) -> Optional[dict]:
    """按 id 查询用户（不含密码哈希）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, account, nickname, is_vip, created_at, last_login_at "
                "FROM users WHERE id = %s",
                (user_id,),
            )
            return cur.fetchone()


def set_user_vip(user_id: int, is_vip: int) -> bool:
    """开通/取消用户 VIP（VIP 用户可使用在线编辑器与 VIP 模板中心）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_vip = %s WHERE id = %s",
                (1 if is_vip else 0, user_id),
            )
            return cur.rowcount > 0


def touch_login(user_id: int) -> None:
    """更新用户最近登录时间。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login_at = NOW() WHERE id = %s",
                (user_id,),
            )


# ── 全局同义词库 CRUD ──


def list_aliases(kind: Optional[str] = None) -> List[dict]:
    """全局板块/字段同义词列表。kind: section | field | None(全部)。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if kind:
                cur.execute(
                    "SELECT id, kind, std_key, alias FROM standard_aliases "
                    "WHERE kind = %s ORDER BY std_key, id",
                    (kind,),
                )
            else:
                cur.execute(
                    "SELECT id, kind, std_key, alias FROM standard_aliases "
                    "ORDER BY kind, std_key, id"
                )
            return cur.fetchall()


def add_alias(kind: str, std_key: str, alias: str) -> bool:
    """新增同义词，已存在时返回 False。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO standard_aliases (kind, std_key, alias) VALUES (%s, %s, %s)",
                    (kind, std_key, alias),
                )
                return cur.rowcount > 0
            except pymysql.err.IntegrityError:
                return False


def delete_alias(alias_id: int) -> bool:
    """删除同义词。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM standard_aliases WHERE id = %s", (alias_id,))
            return cur.rowcount > 0


# ── 模板 CRUD ──


def list_templates() -> List[dict]:
    """返回所有有效的免费模板（VIP 模板独立管理，不在此列）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, file_path, config, created_at, is_vip, display_id, editable "
                "FROM templates WHERE is_active = 1 ORDER BY display_id ASC, id ASC"
            )
            rows = cur.fetchall()
            for r in rows:
                r["config"] = _parse_config(r.get("config"))
            return rows


def list_vip_templates() -> List[dict]:
    """返回所有有效的 VIP 模板（与免费模板中心独立）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, file_path, config, created_at, is_vip, display_id, editable "
                "FROM templates WHERE is_active = 1 AND is_vip = 1 ORDER BY display_id ASC, id ASC"
            )
            rows = cur.fetchall()
            for r in rows:
                r["config"] = _parse_config(r.get("config"))
            return rows


def admin_list_templates() -> List[dict]:
    """管理员视角：返回全部模板（含待审核/下架，不含已拒绝），
    附审核状态与校验报告。已拒绝的模板不显示，记录保留供后台追溯。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, file_path, config, is_active, review_status, "
                "validation_report, created_at, is_vip, display_id, editable FROM templates "
                "WHERE review_status <> 'rejected' ORDER BY id ASC"
            )
            rows = cur.fetchall()
            for r in rows:
                r["config"] = _parse_config(r.get("config"))
            return rows


def set_review(template_id: int, review_status: str, is_active: int) -> bool:
    """设置模板审核状态与是否对用户可见。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET review_status = %s, is_active = %s WHERE id = %s",
                (review_status, is_active, template_id),
            )
            return cur.rowcount > 0


def save_validation_report(template_id: int, report: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET validation_report = %s WHERE id = %s",
                (report, template_id),
            )


def _parse_config(raw):
    """解析模板配置 JSON，失败返回空字典。"""
    if not raw:
        return {}
    try:
        cfg = json.loads(raw)
        return cfg if isinstance(cfg, dict) else {}
    except (ValueError, TypeError):
        return {}


def count_active_templates() -> int:
    """当前有效免费模板数量（VIP 模板独立，不计入免费上限）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM templates WHERE is_active = 1 AND is_vip = 0")
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0


def count_pending_templates() -> int:
    """当前待审核模板数量。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM templates WHERE review_status = 'pending'")
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0


def get_max_template_id() -> int:
    """当前模板表最大 id（含免费与 VIP），用于生成不冲突的临时预览编号。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM templates")
            row = cur.fetchone()
            return int(row["m"]) if row else 0


def get_template(template_id: int) -> Optional[dict]:
    """按 id 查询有效模板。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, file_path, config, created_at, is_vip, display_id, editable "
                "FROM templates WHERE id = %s AND is_active = 1",
                (template_id,),
            )
            r = cur.fetchone()
            if r:
                r["config"] = _parse_config(r.get("config"))
            return r


def create_template(name: str, description: str, file_path: str, config: str = "",
                    is_vip: int = 0) -> int:
    """新增模板，返回新模板 id。is_vip=1 表示 VIP 模板（独立于免费模板中心）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO templates (name, description, file_path, config, is_vip) "
                "VALUES (%s, %s, %s, %s, %s)",
                (name, description, file_path, config, is_vip),
            )
            return int(cur.lastrowid)


def set_template_vip(template_id: int, is_vip: int) -> bool:
    """切换模板是否为 VIP（VIP 模板与免费模板中心相互独立）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET is_vip = %s WHERE id = %s AND is_active = 1",
                (1 if is_vip else 0, template_id),
            )
            return cur.rowcount > 0


def set_template_editable(template_id: int, editable: int) -> bool:
    """设置模板是否可在编辑器「更换模板」中被套用。

    ``editable=1``：进编辑器模板库（免费区/VIP 区）。
    ``editable=0``：只在首页模板中心展示与下载，不进编辑器。

    返回是否命中了记录；模板不存在或已下架时为 ``False``。
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET editable = %s WHERE id = %s AND is_active = 1",
                (1 if editable else 0, template_id),
            )
            return cur.rowcount > 0


def set_templates_editable(template_ids, editable: int) -> int:
    """批量设置编辑器可用性，返回受影响的行数。

    批量场景是常态：模板可用性探测一次会判定几十个模板，
    逐个发请求既慢又容易中途失败。
    """
    ids = [int(i) for i in template_ids]
    if not ids:
        return 0
    placeholders = ", ".join(["%s"] * len(ids))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET editable = %s WHERE id IN (%s) AND is_active = 1"
                % ("%s", placeholders),
                tuple([1 if editable else 0] + ids),
            )
            return cur.rowcount


def update_template_config(template_id: int, config: str) -> bool:
    """更新模板配置 JSON（如板块绑定映射）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET config = %s WHERE id = %s",
                (config, template_id),
            )
            return cur.rowcount > 0


def soft_delete_template(template_id: int) -> bool:
    """软删除模板，返回是否删除了有效记录。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET is_active = 0 WHERE id = %s AND is_active = 1",
                (template_id,),
            )
            return cur.rowcount > 0


def renumber_templates() -> Dict[int, int]:
    """删除后自动重排：把剩余有效模板按创建时间重新编号为连续 ID（1..N），
    并同步更新 template_placeholders 的关联，返回重排映射（old -> new）。

    安全策略：把「有效 + 待审核」模板统一按创建时间重排为连续 ID，
    软删除记录保留原 ID 不清理（避免误删历史模板）；被占用的 ID 挪到高位暂存区。
    无论是否发生重排，都会修正 AUTO_INCREMENT，避免高 ID 残留污染新模板编号。
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM templates "
                "WHERE is_active = 1 OR review_status = 'pending' "
                "ORDER BY is_vip DESC, created_at ASC, id ASC"
            )
            rows = cur.fetchall()
            mapping = {}
            for idx, r in enumerate(rows, start=1):
                if r["id"] != idx:
                    mapping[r["id"]] = idx
            cur.execute("SELECT id, is_active FROM templates")
            all_rows = cur.fetchall()
            all_ids = [r["id"] for r in all_rows]
            temp_base = (max(all_ids) if all_ids else 0) + 1000
            cur.execute("SET FOREIGN_KEY_CHECKS=0")
            try:
                # 1) 全部记录挪到临时 ID 区，目标 ID 全部空出
                for rid in all_ids:
                    cur.execute(
                        "UPDATE templates SET id = %s WHERE id = %s",
                        (rid + temp_base, rid),
                    )
                # 2) 占位符同步挪到临时区
                for rid in all_ids:
                    cur.execute(
                        "UPDATE template_placeholders SET template_id = %s WHERE template_id = %s",
                        (rid + temp_base, rid),
                    )
                # 3) 有效 + 待审核模板写入最终连续 ID
                valid_new = {r["id"]: idx for idx, r in enumerate(rows, start=1)}
                # 软删除记录 = 非活动且非待审核（待审核模板已在上一步写入连续 ID）
                inactive_orig = [
                    r["id"] for r in all_rows
                    if not r["is_active"] and r["id"] not in valid_new
                ]
                for rid in all_ids:
                    if rid in valid_new:
                        new_id = valid_new[rid]
                        cur.execute(
                            "UPDATE templates SET id = %s WHERE id = %s",
                            (new_id, rid + temp_base),
                        )
                        cur.execute(
                            "UPDATE template_placeholders SET template_id = %s WHERE template_id = %s",
                            (new_id, rid + temp_base),
                        )
                # 4) 软删除记录放回原 ID；若原 ID 已被有效模板占用，挪到高位暂存
                used_ids = set(valid_new.values())
                for rid in inactive_orig:
                    if rid in used_ids:
                        cur.execute(
                            "UPDATE templates SET id = %s WHERE id = %s",
                            (rid + temp_base * 2, rid + temp_base),
                        )
                        cur.execute(
                            "UPDATE template_placeholders SET template_id = %s WHERE template_id = %s",
                            (rid + temp_base * 2, rid + temp_base),
                        )
                    else:
                        cur.execute(
                            "UPDATE templates SET id = %s WHERE id = %s",
                            (rid, rid + temp_base),
                        )
                        cur.execute(
                            "UPDATE template_placeholders SET template_id = %s WHERE template_id = %s",
                            (rid, rid + temp_base),
                        )
                # 5) 重置自增：只按有效模板的最终连续 ID 计算，
                #    避免软删除记录的高 ID（历史残留）把自增推高
                max_id = max(valid_new.values(), default=0)
                cur.execute("ALTER TABLE templates AUTO_INCREMENT = %s", (max_id + 1,))
            finally:
                cur.execute("SET FOREIGN_KEY_CHECKS=1")
            return mapping


def remap_draft_template_ids(mapping: Dict[int, int]) -> int:
    """模板 ID 重排后，同步更新 resume_drafts.template_id 引用，避免草稿指向错误模板。
    返回被更新的草稿行数。"""
    if not mapping:
        return 0
    affected = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for old, new in mapping.items():
                if old == new:
                    continue
                cur.execute(
                    "UPDATE resume_drafts SET template_id = %s WHERE template_id = %s",
                    (new, old),
                )
                affected += cur.rowcount
        conn.commit()
    return affected


def renumber_display_ids() -> dict:
    """统一模板池：display_id 重排为 1,2,3…（全部上架模板共用一个序列）。
    真实 id 保持不变（主键/外键/预览图/草稿引用均不动）。"""
    stats = {"free": 0, "vip": 0}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM templates "
                "WHERE is_active = 1 "
                "ORDER BY created_at ASC, id ASC",
            )
            rows = cur.fetchall()
            for idx, r in enumerate(rows, start=1):
                cur.execute(
                    "UPDATE templates SET display_id = %s WHERE id = %s",
                    (idx, r["id"]),
                )
                stats["free"] += cur.rowcount
        conn.commit()
    return stats


def update_template_file(template_id: int, file_path: str) -> bool:
    """更新模板文件路径（如模板文件被重新适配/替换后）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET file_path = %s WHERE id = %s AND is_active = 1",
                (file_path, template_id),
            )
            return cur.rowcount > 0


def rename_template(template_id: int, name: str) -> bool:
    """重命名模板。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE templates SET name = %s WHERE id = %s AND is_active = 1",
                (name, template_id),
            )
            return cur.rowcount > 0


# ── 占位符配置 CRUD ──


def get_placeholders(template_id: int) -> List[dict]:
    """返回模板的占位符配置。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, template_id, module_key, label, min_words, max_words "
                "FROM template_placeholders WHERE template_id = %s ORDER BY id ASC",
                (template_id,),
            )
            return cur.fetchall()


def get_placeholders_map(template_ids) -> Dict[int, List[dict]]:
    """批量返回多个模板的占位符配置：{template_id: [modules]}。
    一次查询代替 N 次 get_placeholders，避免 N+1 次数据库连接开销。"""
    ids = [int(i) for i in (template_ids or []) if i]
    result: Dict[int, List[dict]] = {i: [] for i in ids}
    if not ids:
        return result
    with get_conn() as conn:
        with conn.cursor() as cur:
            marks = ",".join(["%s"] * len(ids))
            cur.execute(
                "SELECT id, template_id, module_key, label, min_words, max_words "
                "FROM template_placeholders WHERE template_id IN (" + marks + ") ORDER BY id ASC",
                ids,
            )
            for r in cur.fetchall():
                result.setdefault(r["template_id"], []).append(r)
    return result


def replace_placeholders(template_id: int, modules: List[dict]) -> None:
    """整体替换模板的占位符配置（先删后插）。modules 形如
    [{"module_key": ..., "label": ..., "min_words": ..., "max_words": ...}]。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM template_placeholders WHERE template_id = %s",
                (template_id,),
            )
            for m in modules:
                cur.execute(
                    "INSERT INTO template_placeholders "
                    "(template_id, module_key, label, min_words, max_words) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (template_id, m["module_key"], m["label"],
                     int(m["min_words"]), int(m["max_words"])),
                )


# ── 用户简历草稿（编辑器持久化） ──
def _extract_template_id_from_data(data_json: str, template_id: Optional[int]) -> Optional[int]:
    """若外部没传 template_id，尝试从 data_json 里扒 real_template_id/template_id。"""
    if template_id:
        return template_id
    try:
        data = json.loads(data_json) if data_json else {}
        tid = data.get('real_template_id') or data.get('template_id')
        return int(tid) if tid else None
    except (ValueError, TypeError):
        return None


def save_draft(user_id: int, template_id: Optional[int], title: str, data_json: str,
               draft_id: Optional[int] = None) -> int:
    """保存/更新草稿，返回 draft_id。draft_id 为空则新增，否则更新。"""
    template_id = _extract_template_id_from_data(data_json, template_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            if draft_id:
                cur.execute(
                    "UPDATE resume_drafts SET template_id=%s, title=%s, data_json=%s "
                    "WHERE id=%s AND user_id=%s",
                    (template_id, title, data_json, draft_id, user_id))
                if cur.rowcount == 0:
                    # 该用户无此 id → 新建一条
                    cur.execute(
                        "INSERT INTO resume_drafts (user_id, template_id, title, data_json) "
                        "VALUES (%s,%s,%s,%s)",
                        (user_id, template_id, title, data_json))
                    return cur.lastrowid
                return draft_id
            cur.execute(
                "INSERT INTO resume_drafts (user_id, template_id, title, data_json) "
                "VALUES (%s,%s,%s,%s)",
                (user_id, template_id, title, data_json))
            return cur.lastrowid


def list_drafts(user_id: int) -> List[dict]:
    """列出当前用户的草稿（最新在前）。模板 id 为空时尝试从 data_json 补齐。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, template_id, title, data_json, updated_at, created_at "
                "FROM resume_drafts WHERE user_id=%s ORDER BY updated_at DESC",
                (user_id,))
            rows = cur.fetchall()
            for r in rows:
                if not r.get('template_id') and r.get('data_json'):
                    r['template_id'] = _extract_template_id_from_data(r['data_json'], None)
            return rows


def get_draft(user_id: int, draft_id: int) -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, template_id, title, data_json, updated_at, created_at "
                "FROM resume_drafts WHERE id=%s AND user_id=%s",
                (draft_id, user_id))
            return cur.fetchone()


def delete_draft(user_id: int, draft_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM resume_drafts WHERE id=%s AND user_id=%s",
                        (draft_id, user_id))
            return cur.rowcount > 0


def delete_drafts_batch(user_id: int, draft_ids: List[int]) -> int:
    """批量删除草稿，返回实际删除条数（只删属于该用户的）。"""
    if not draft_ids:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            placeholders = ','.join(['%s'] * len(draft_ids))
            cur.execute(
                f"DELETE FROM resume_drafts WHERE user_id=%s AND id IN ({placeholders})",
                (user_id, *draft_ids))
            return cur.rowcount


def build_word_limits(template_id: int) -> Dict[str, dict]:
    """组装 LLM 所需的 word_limits：{module_key: {"label", "min_words", "max_words"}}。"""
    limits = {}
    for p in get_placeholders(template_id):
        limits[p["module_key"]] = {
            "label": p["label"],
            "min_words": p["min_words"],
            "max_words": p["max_words"],
        }
    return limits
