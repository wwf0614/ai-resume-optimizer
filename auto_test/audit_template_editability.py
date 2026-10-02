# -*- coding: utf-8 -*-
"""模板「编辑器可用性」审计 —— 判定哪些模板可以在编辑器中使用，并把结果写回。

解决的问题
----------
编辑器「更换模板」面板以前会把模板全部平铺出来。老大要求：**不能用的不要展示**。
但「能不能用」不该靠肉眼判断，也不该写死在代码里 —— 模板是管理员随时上传的，
今天能解析不代表明天上传的也能。所以判定必须是一条**可复跑的检测链**，
结果落到 ``templates.editable``，编辑器只认这个标记。

判定口径（全部通过才算可用）
----------------------------
1. ``/api/template-structure/{id}`` 能解析出文本框结构（Word 文件本身可读）
2. 至少 ``--min-editable``（默认 1）个可编辑文本框（否则用户点哪儿都改不了）
3. 至少 ``--min-ph``（默认 1）个带 ``{{占位符}}`` 的文本框
   （占位符是 AI/结构化内容回填的落点；一个都没有的话，
    ``/api/render-resume`` 无法把简历内容灌进去）
4. ``/api/template-preview/{id}`` 能用 Word 真实渲染出图
   （这条同时验证了 Word COM 链路与模板本身没有损坏）

任一条不过 → ``editable = 0``：模板仍在首页模板中心展示与下载，只是不进编辑器。

用法::

    # 只审计，打印表格，不改数据库（默认）
    D:\\python\\python.exe auto_test/audit_template_editability.py

    # 审计并把结论写回 editable（可用=1，不可用=0）
    D:\\python\\python.exe auto_test/audit_template_editability.py --apply

    # 顺带收敛：占位符少于 4 个的模板也从编辑器移除（配合 Phase-1 的精选决策）
    D:\\python\\python.exe auto_test/audit_template_editability.py --apply --min-ph 4

    # 导出报告
    D:\\python\\python.exe auto_test/audit_template_editability.py --json auto_test/_tpl_audit.json
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("RESUME_API", "http://127.0.0.1:8000")
TEST_ACCOUNT = "editor_test@local.dev"
TEST_PASSWORD = "test123456"
ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / "resume_optimizer" / ".env"


# ── HTTP 基础 ──

def _request(method, path, token=None, admin=None, body=None, ctype=None, timeout=300):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if admin:
        headers["X-Admin-Password"] = admin
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(API + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw else {}


def _post_json(path, payload, timeout=30):
    return _request("POST", path, body=json.dumps(payload).encode(),
                    ctype="application/json", timeout=timeout)


def get_token():
    """自备测试账号：优先登录，没注册过就注册。"""
    try:
        return _post_json("/api/login",
                          {"account": TEST_ACCOUNT, "password": TEST_PASSWORD})["token"]
    except urllib.error.HTTPError:
        return _post_json("/api/register",
                          {"account": TEST_ACCOUNT, "password": TEST_PASSWORD,
                           "nickname": "模板审计"})["token"]


def get_admin_password():
    """从 .env 读管理员口令（审计脚本要调管理端写接口）。"""
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("ADMIN_PASSWORD="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ── 单项检测 ──

def check_structure(tid, token):
    st = _request("GET", "/api/template-structure/%d" % tid, token=token)
    boxes = st.get("boxes") or []
    editable = [b for b in boxes if b.get("editable") is not False and b.get("h")]
    with_ph = [b for b in boxes if b.get("placeholders")]
    return {"boxes": len(boxes), "editable": len(editable), "with_ph": len(with_ph)}


def check_preview(tid, token):
    """空 edits 走一次真实渲染：能出图说明 Word 转换链路与模板都正常。"""
    boundary = "----audit" + uuid.uuid4().hex
    body = ("--%s\r\nContent-Disposition: form-data; name=\"edits\"\r\n\r\n{}\r\n--%s--\r\n"
            % (boundary, boundary)).encode()
    data = _request("POST", "/api/template-preview/%d" % tid, token=token, body=body,
                    ctype="multipart/form-data; boundary=" + boundary)
    pages = data.get("pages") or ([data["png_b64"]] if data.get("png_b64") else [])
    return len(pages)


def audit_one(tid, kind, name, token, min_editable, min_ph):
    t0 = time.time()
    entry = {"id": tid, "kind": kind, "name": name, "ok": False, "reasons": []}
    try:
        st = check_structure(tid, token)
        entry.update(st)
    except Exception as exc:  # noqa: BLE001
        entry["reasons"].append("结构解析失败: %s" % str(exc)[:100])
        entry["sec"] = round(time.time() - t0, 1)
        return entry

    if entry["editable"] < min_editable:
        entry["reasons"].append("可编辑文本框仅 %d 个（要求 ≥%d）"
                                % (entry["editable"], min_editable))
    if entry["with_ph"] < min_ph:
        entry["reasons"].append("带占位符文本框仅 %d 个（要求 ≥%d）"
                                % (entry["with_ph"], min_ph))

    try:
        entry["preview_pages"] = check_preview(tid, token)
        if entry["preview_pages"] < 1:
            entry["reasons"].append("精确预览未产出页面")
    except Exception as exc:  # noqa: BLE001
        entry["reasons"].append("精确预览渲染失败: %s" % str(exc)[:100])

    entry["ok"] = not entry["reasons"]
    entry["sec"] = round(time.time() - t0, 1)
    return entry


# ── 主流程 ──

def main(argv=None):
    ap = argparse.ArgumentParser(description="模板编辑器可用性审计")
    ap.add_argument("--apply", action="store_true",
                    help="把结论写回 templates.editable（默认只审计不改库）")
    ap.add_argument("--min-editable", type=int, default=1,
                    help="通过所需的最少可编辑文本框数（默认 1）")
    ap.add_argument("--min-ph", type=int, default=1,
                    help="通过所需的最少占位符文本框数（默认 1；调大可做精选收敛）")
    ap.add_argument("--json", dest="json_path", help="把完整报告写到该路径")
    args = ap.parse_args(argv)

    token = get_token()
    groups = [("free", _request("GET", "/templates")),
              ("vip", _request("GET", "/api/vip-templates", token=token))]

    rows = []
    for kind, items in groups:
        print("\n===== %s 共 %d 份（可编辑≥%d / 占位符≥%d）====="
              % (kind, len(items), args.min_editable, args.min_ph))
        for t in items:
            r = audit_one(t["id"], kind, t.get("name") or "", token,
                          args.min_editable, args.min_ph)
            rows.append(r)
            flag = "[可用]" if r["ok"] else "[不可用]"
            detail = ("ed=%-3s ph=%-3s pv=%-2s" % (r.get("editable", "-"),
                                                  r.get("with_ph", "-"),
                                                  r.get("preview_pages", "-")))
            print("  %s id=%-3s %s %5.1fs  %s"
                  % (flag, r["id"], detail, r["sec"], r["name"][:22]))

    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    print("\n合计 %d 份 → 可用 %d / 不可用 %d" % (len(rows), len(good), len(bad)))
    for r in bad:
        print("  ✗ id=%-3s %s ← %s" % (r["id"], r["name"][:20], "; ".join(r["reasons"])))

    if args.json_path:
        out = pathlib.Path(args.json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"rows": rows, "min_editable": args.min_editable,
                                   "min_ph": args.min_ph},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print("报告已写入:", out)

    if not args.apply:
        print("\n（未改动数据库。加 --apply 把结论写回 editable）")
        return 0

    admin = get_admin_password()
    if not admin:
        print("找不到 ADMIN_PASSWORD，无法写回。请检查 %s" % ENV_PATH, file=sys.stderr)
        return 2

    changed = 0
    for flag, batch in ((1, good), (0, bad)):
        if not batch:
            continue
        ids = ",".join(str(r["id"]) for r in batch)
        boundary = "----audit" + uuid.uuid4().hex
        parts = []
        for k, v in (("ids", ids), ("editable", str(flag))):
            parts.append("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                         % (boundary, k, v))
        body = ("".join(parts) + "--%s--\r\n" % boundary).encode()
        res = _request("POST", "/admin/templates/editable/batch", admin=admin, body=body,
                       ctype="multipart/form-data; boundary=" + boundary, timeout=60)
        changed += res.get("affected", 0)
        print("editable=%d ← %d 套：%s" % (flag, len(batch), res.get("message")))
    print("写回完成，共影响 %d 套模板。" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
