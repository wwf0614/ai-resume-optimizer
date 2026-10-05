# -*- coding: utf-8 -*-
"""WPS 富文本直接编辑模式 - 一键自检脚本
用法: D:\\python\\python.exe tools\\smoke_richtext.py
只输出 ASCII，便于在任何终端阅读。覆盖：
  1. 前端集成点（editor.js / editor.html / editor.css / editor-richtext.js）
  2. JS 语法（node --check）
  3. 后端契约（用编辑器同款 edits 结构真实调用 /api/richtext-export）
"""
import io, json, os, subprocess, sys, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE, "static")
OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append("%s %s %s" % ("PASS" if cond else "FAIL", name, detail))


def read(p):
    return io.open(os.path.join(STATIC, p), encoding="utf-8").read()


# ── 1. 前端集成点 ──
try:
    ed = read("editor.js")
    rt = read("editor-richtext.js")
    html = read("editor.html")
    css = read("editor.css")

    for anchor in ["window.__edBridge", "RichtextMode.isActive", "RichtextMode.render",
                   "RichtextMode.exportAs", "RichtextMode.switched", "RichtextMode.load",
                   "RichtextMode.reset", "RichtextMode.snapshot", "RichtextMode.restoreSnap",
                   "RichtextMode.restoreLocal", "RichtextMode.restoreCloud",
                   "richtext_mode:", "richtext_edits:", "rtMode:", "rtEdits:",
                   "rtTemplateId:"]:
        check("editor.js: " + anchor, anchor in ed)

    # 旧草稿小 id 防护（404 根因修复）
    check("editor.js: stale-template guard", "已失效" in ed and "resume_planet_templates" in ed)

    # editor.html：richtext 模块必须在 editor.js 之后加载
    i_ed = html.find("editor.js?v=")
    i_rt = html.find("editor-richtext.js")
    check("editor.html: richtext script after editor.js", i_ed > -1 and i_rt > i_ed)
    check("editor.html: version bumped", "20261005a" in html)

    for cls in [".rt-box", ".rt-toolbar", ".rtp-page", ".ed-nav-card", ".rt-loading-wrap"]:
        check("editor.css: " + cls, cls in css)

    for anchor in ["window.RichtextMode", "__edBridge", "richtext-structure",
                   "richtext-export", "plaintext-only", "collectEdits"]:
        check("editor-richtext.js: " + anchor, anchor in rt)
except Exception as e:
    check("frontend files readable", False, str(e))

# ── 2. JS 语法 ──
node = None
for cand in ["node", r"D:\Program Files\nodejs\node.exe", "node.exe"]:
    try:
        subprocess.run([cand, "--version"], capture_output=True, check=True)
        node = cand
        break
    except Exception:
        continue
if node:
    for f in ["editor.js", "editor-richtext.js"]:
        r = subprocess.run([node, "--check", os.path.join(STATIC, f)], capture_output=True)
        check("node --check " + f, r.returncode == 0,
              "" if r.returncode == 0 else r.stderr.decode("utf-8", "ignore")[:160])
else:
    check("node available", False, "skip syntax check")

# ── 3. 后端契约：编辑器同款 edits 结构真实导出一次 ──
TOK_FILE = os.path.join(BASE, "logs", ".smoke_token")
token = io.open(TOK_FILE, encoding="utf-8").read().strip() if os.path.exists(TOK_FILE) else ""
tid = "30840"
if token:
    # 与 editor-richtext.js collectEdits() 完全同构的载荷（FormData，与前端一致）
    edits = {"0": {"paragraphs": [
        {"align": "center", "line": 1.15,
         "runs": [{"text": "张三", "bold": True, "italic": None, "underline": None,
                    "size": 22, "color": "#29545A", "font": "微软雅黑"}]}]}}
    boundary = "----smoke1234567890"
    parts = []
    for k, v in [("edits", json.dumps(edits, ensure_ascii=False)),
                 ("format", "docx")]:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, k, v)).encode("utf-8"))
    body = b"".join(parts) + ("--%s--\r\n" % boundary).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:8000/api/richtext-export/" + tid, data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            blob = resp.read()
            disp = resp.headers.get("Content-Disposition", "")
            check("export API accepted edits-shape", len(blob) > 1000,
                  "%dB %s" % (len(blob), disp[:60]))
            out = os.path.join(BASE, "temp", "smoke_export.docx")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            io.open(out, "wb").write(blob)
            check("export docx saved", os.path.getsize(out) > 1000, out)
    except Exception as e:
        check("export API", False, str(e)[:160])
else:
    print("NOTE: no token at logs/.smoke_token - export API test skipped")
    print("      (browser 内操作一次后自动写入，或手动 echo token > logs/.smoke_token)")

# ── 汇总 ──
print("=" * 62)
for line in OK:
    print(line)
if FAIL:
    print("-" * 62)
    for line in FAIL:
        print(line)
print("=" * 62)
print("TOTAL: %d passed, %d failed" % (len(OK), len(FAIL)))
sys.exit(1 if FAIL else 0)
