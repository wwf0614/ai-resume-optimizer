"""Edge headless 截图 + 局部裁剪（本地视觉验证用）。

用法：
  D:\\python\\python.exe _shot.py <name> "<query>"
  query 例：fam=sidebar&theme=blue
产出：
  _shots/<name>.png          整屏
  _shots/<name>_panel.png    右侧外观面板（裁剪放大）
  _shots/<name>_paper.png    左侧简历预览
"""
import os
import subprocess
import sys

from PIL import Image

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ROOT = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(ROOT, "_shots")
BASE_URL = "http://127.0.0.1:8000/static/_verify_editor.html"

# 侧栏面板在 1700 宽窗口下的横向范围（实测：#previewWrap 宽 1366，面板自 1366 起）
PANEL_X0 = 1366
PAPER_X1 = 1366


def shoot(out, url, w=1700, h=1750, budget=11000):
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", "--hide-scrollbars",
           f"--window-size={w},{h}", f"--virtual-time-budget={budget}",
           "--user-data-dir=" + os.path.join(SHOTS, "_edgeprofile"),
           "--screenshot=" + out, url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    return r.returncode, (r.stderr or "")[-400:]


def crop(src, dst, box):
    im = Image.open(src)
    im.crop(box).save(dst)
    return im.size


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "shot"
    query = sys.argv[2] if len(sys.argv) > 2 else ""
    os.makedirs(SHOTS, exist_ok=True)
    full = os.path.join(SHOTS, name + ".png")
    url = BASE_URL + ("?" + query if query else "")
    rc, err = shoot(full, url)
    print("edge rc", rc, err.strip().splitlines()[-1] if err.strip() else "")
    if not os.path.exists(full):
        print("FAILED: no screenshot")
        return 1
    size = Image.open(full).size
    print("full", size, os.path.getsize(full))
    crop(full, os.path.join(SHOTS, name + "_panel.png"),
         (PANEL_X0, 0, size[0], size[1]))
    crop(full, os.path.join(SHOTS, name + "_paper.png"),
         (0, 0, PAPER_X1, size[1]))
    print("cropped ->", name + "_panel.png", name + "_paper.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
