"""探测模板可用性：逐个拉模板结构，统计可编辑盒子数。

背景：编辑器的「更换模板」弹窗原来把 /templates 与 /api/vip-templates
返回的模板全部列出来，但其中一部分模板解析不出可编辑文本框（或只有装饰盒），
点进去只会看到引导页/加载失败——老大要求这些不要在编辑器里展示。

判定「可用」= 解析成功 且 可编辑盒数量达标（阈值见 MIN_EDITABLE_BOXES）。

用法：
    python probe_template_editable.py            # 只读已有缓存 + 必要解析
    python probe_template_editable.py --json out.json
"""
import json
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:8000"
ACCOUNT = "editor_test@local.dev"
PASSWORD = "test123456"

# 与前端 boxIsEditable 保持一致：editable !== false 且 h 有值
def is_editable(box):
    return box.get("editable") is not False and bool(box.get("h"))


def _post(path, payload):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _get(path, token, timeout=180):
    req = urllib.request.Request(API + path,
                                headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def login():
    try:
        return _post("/api/login", {"account": ACCOUNT, "password": PASSWORD})["token"]
    except urllib.error.HTTPError:
        return _post("/api/register",
                     {"account": ACCOUNT, "password": PASSWORD,
                      "nickname": "编辑器测试"})["token"]


def main():
    token = login()
    out_path = None
    if "--json" in sys.argv:
        out_path = sys.argv[sys.argv.index("--json") + 1]
    do_preview = "--preview" in sys.argv

    groups = []
    groups.append(("free", _get("/templates", token)))
    groups.append(("vip", _get("/api/vip-templates", token)))

    report = {}
    for kind, rows in groups:
        print(f"\n===== {kind} 共 {len(rows)} 份 =====")
        for r in rows:
            tid = r["id"]
            entry = {"id": tid, "name": r["name"], "kind": kind,
                     "display_id": r.get("display_id"),
                     "modules_api": r.get("modules") or []}
            try:
                st = _get(f"/api/template-structure/{tid}", token, timeout=300)
                boxes = st.get("boxes") or []
                ed = [b for b in boxes if is_editable(b)]
                ph = [b for b in boxes if b.get("placeholders")]
                entry.update({
                    "ok": True, "boxes": len(boxes), "editable": len(ed),
                    "with_ph": len(ph),
                    "ph_sample": sorted({p for b in ph
                                         for p in (b.get("placeholders") or [])})[:12],
                })
            except Exception as exc:  # noqa: BLE001
                entry.update({"ok": False, "error": str(exc)[:160]})

            # 精确预览渲染：编辑器「精确预览」与导出都靠这条链路，
            # 它失败 = 这份模板在编辑器里实际不能用
            if do_preview and entry.get("ok"):
                t0 = time.time()
                try:
                    import io
                    import uuid
                    boundary = "----probe" + uuid.uuid4().hex
                    body = (
                        f"--{boundary}\r\n"
                        'Content-Disposition: form-data; name="edits"\r\n\r\n'
                        "{}\r\n"
                        f"--{boundary}--\r\n"
                    ).encode()
                    req = urllib.request.Request(
                        API + f"/api/template-preview/{tid}", data=body,
                        headers={"Authorization": "Bearer " + token,
                                 "Content-Type": "multipart/form-data; boundary=" + boundary},
                        method="POST")
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        data = json.loads(resp.read().decode())
                    pages = data.get("pages") or ([data["png_b64"]] if data.get("png_b64") else [])
                    entry["preview_ok"] = bool(pages)
                    entry["preview_pages"] = len(pages)
                    entry["preview_bytes"] = sum(len(p) for p in pages)
                except Exception as exc:  # noqa: BLE001
                    entry["preview_ok"] = False
                    entry["preview_error"] = str(exc)[:120]
                entry["preview_sec"] = round(time.time() - t0, 1)
                del io

            report[str(tid)] = entry
            flag = "OK " if entry.get("ok") else "ERR"
            pv = ("pv=" + ("OK" if entry.get("preview_ok") else "FAIL")
                  if do_preview else "pv=-")
            print(f"  [{flag}] id={tid:<3} ed={entry.get('editable', '-'):<3} "
                  f"ph={entry.get('with_ph', '-'):<3} {pv:<6} "
                  f"{entry.get('preview_sec', ''):<6} {r['name'][:24]}  "
                  f"{entry.get('error') or entry.get('preview_error') or ''}")

    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("\nwritten:", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
