# -*- coding: utf-8 -*-
"""重新生成全部模板预览图（static/previews/t{id}.png）。

用途：当缩略图与模板实际文件不一致（用户按缩略图选模板后，编辑器
渲染出的却是另一种版式）时，运行本脚本让预览图与当前文件重新对齐。
管理端替换过模板文件后也建议重跑一次。

用法：python regen_previews.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

from utils import converter, db


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    import fitz

    base = Path(__file__).resolve().parent
    out_dir = base / "static" / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = db.list_templates()
    print(f"共 {len(rows)} 个模板，开始逐个重渲预览图（Word 转换较慢）...")
    changed, failed = [], []
    for i, t in enumerate(rows, 1):
        f = base / t["file_path"]
        if not f.exists():
            failed.append((t["id"], t["name"], "文件缺失"))
            print(f"[{i}/{len(rows)}] #{t['id']} {t['name']} — 文件缺失，跳过")
            continue
        png_path = out_dir / f"t{t['id']}.png"
        old_bytes = png_path.read_bytes() if png_path.exists() else None
        tmp = Path(tempfile.mkdtemp(prefix="regen_"))
        try:
            pdf = tmp / "p.pdf"
            converter.docx_to_pdf(str(f), str(pdf))
            doc = fitz.open(str(pdf))
            try:
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                pix.save(str(png_path))
            finally:
                doc.close()
            new_bytes = png_path.read_bytes()
            same = old_bytes == new_bytes
            if not same:
                changed.append((t["id"], t["name"]))
            print(f"[{i}/{len(rows)}] #{t['id']} {t['name']} — "
                  + ("一致" if same else "已更新（原缩略图与文件不符！）"))
        except Exception as exc:  # noqa: BLE001
            failed.append((t["id"], t["name"], str(exc)))
            print(f"[{i}/{len(rows)}] #{t['id']} {t['name']} — 失败: {exc}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    print(f"完成：{len(rows) - len(failed)} 成功，"
          f"{len(changed)} 张缩略图与文件不符已修正，{len(failed)} 失败")
    for fid, name, why in failed:
        print(f"  失败: #{fid} {name} — {why}")


if __name__ == "__main__":
    main()
