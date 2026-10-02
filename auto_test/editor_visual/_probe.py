"""跑一次编辑器验证页，打印几何与渲染结果快照。

用法：D:\\python\\python.exe _probe.py "click=fam:1,sw:5"
"""
import json
import os
import re
import subprocess
import sys

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ROOT = os.path.dirname(os.path.abspath(__file__))
URL = "http://127.0.0.1:8000/static/_verify_editor.html?geom=1"


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    url = URL + ("&" + query if query else "")
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", "--window-size=1700,1080",
           "--virtual-time-budget=20000",
           "--user-data-dir=" + os.path.join(ROOT, "_shots", "_edgeprofile3"),
           "--dump-dom", url]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240)
    dom = r.stdout or ""
    data = None
    for m in re.finditer(r"GEOMSTART(.*?)GEOMEND", dom, re.S):
        try:
            cand = json.loads(m.group(1))
        except Exception:
            continue
        if isinstance(cand, dict) and len(cand) > 3:
            data = cand
            break
    print("QUERY:", query or "(baseline)")
    if not data:
        print("  !! 未取到数据，dom 长度", len(dom))
        return 1
    for k, v in data.items():
        print(f"  {k} = {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
