# -*- coding: utf-8 -*-
"""全量批量测试：所有模板 × 指定简历（段落级文本校验）。
用法: python batch_test.py 赵莎|测试用户|all
"""
import sys, io, os, zipfile, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import requests
from docx import Document
from docx.oxml.ns import qn
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resume_optimizer"))

BASE = "http://127.0.0.1:8000"
TEMPLATES = list(range(1, 21))

ALL_RESUMES = [
    {"name": "赵莎", "file": os.path.join(os.environ["TEMP"], "t1_zs.pdf"),
     "jd": "招聘行政/运营类岗位，要求沟通协调、文字功底、办公软件熟练",
     "markers": ["13314477595", "亚信科技", "信息管理与信息系统"]},
    {"name": "测试用户", "file": os.path.join(os.environ["TEMP"], "src26.pdf"),
     "jd": "招聘运维工程师，要求设备部署、故障排查、数据分析",
     "markers": ["13800000000", "测试大学", "大华"]},
]

which = sys.argv[1] if len(sys.argv) > 1 else "all"
RESUMES = ALL_RESUMES if which == "all" else [r for r in ALL_RESUMES if r["name"] == which]
print("测试简历:", [r["name"] for r in RESUMES], flush=True)

r = requests.post(BASE + "/api/login", json={"account": "13800138000", "password": "test123456"})
if r.status_code != 200:
    print("登录失败:", r.text[:200]); sys.exit(1)
TOKEN = r.json()["token"]
H = {"Authorization": "Bearer " + TOKEN}

# 模板能力探测：占位符 + 板块 + 字段（决定哪些 marker 是必需项）
def probe_capabilities(tid):
    from utils import db, filler, section_mapper
    tpl = db.get_template(tid)
    fp = os.path.join(os.getcwd(), tpl["file_path"].replace("/", os.sep))
    doc = Document(fp)
    ph = set()
    for p in doc.element.iter(qn("w:p")):
        for m in filler.PLACEHOLDER_RE.finditer(p.text or ""):
            ph.add(m.group(1).strip())
    filler._remove_fallback_duplicates(doc)
    m = section_mapper.detect_mapping(doc)
    keys = {s["key"] for s in m["sections"]} | {
        ("work_history" if ph & {"工作经历", "工作经验", "实习经历"} else None),
        ("education_info" if ph & {"教育背景", "教育经历"} else None),
        ("skill_info" if ph & {"专业技能", "职业技能"} else None),
        ("self_evaluate" if ph & {"个人优势", "自我评价"} else None),
    } - {None}
    fkeys = {f["key"] for f in m["fields"]}
    if ph & {"电话", "手机", "手机号", "联系方式"}:
        fkeys.add("phone")
    if ph & {"邮箱", "Email", "email"}:
        fkeys.add("email")
    if ph & {"姓名", "name"}:
        fkeys.add("name")
    return keys, fkeys

CAPS = {}
for tid in TEMPLATES:
    try:
        CAPS[tid] = probe_capabilities(tid)
    except Exception as e:
        CAPS[tid] = (set(), set())
        print("探测 t%d 失败: %s" % (tid, e), flush=True)


def docx_fulltext(data_bytes):
    d = Document(io.BytesIO(data_bytes))
    out = []
    for p in d.element.iter(qn("w:p")):
        parts = []
        for child in p.iter():
            tag = child.tag.split("}")[-1]
            if tag == "t":
                parts.append(child.text or "")
            elif tag == "br":
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            out.append(line)
    return "\n".join(out)


results = []
for resume in RESUMES:
    for tid in TEMPLATES:
        t0 = time.time()
        rec = {"resume": resume["name"], "tid": tid}
        try:
            with open(resume["file"], "rb") as f:
                files = {"resume": (os.path.basename(resume["file"]), f, "application/pdf")}
                data = {"job_text": resume["jd"], "template_id": tid,
                        "strength": "均衡", "merge_mode": "merge"}
                r2 = requests.post(BASE + "/optimize", headers=H, files=files,
                                   data=data, timeout=300)
            rec["status"] = r2.status_code
            if r2.status_code != 200:
                rec["error"] = r2.text[:120]
                rec["ok"] = False
                results.append(rec)
                print("[%s t%d] HTTP %d (%.0fs)" % (resume["name"], tid, r2.status_code, time.time()-t0), flush=True)
                continue
            sid = r2.json()["session_id"]
            r3 = requests.get(BASE + "/download/" + sid,
                              params={"format": "docx", "token": TOKEN}, timeout=90)
            if r3.status_code != 200:
                rec["ok"] = False
                rec["error"] = "下载失败"
                results.append(rec)
                print("[%s t%d] 下载失败" % (resume["name"], tid), flush=True)
                continue
            data_bytes = r3.content
            with zipfile.ZipFile(io.BytesIO(data_bytes)) as z:
                xml = "".join(z.read(n).decode("utf-8", errors="ignore")
                              for n in z.namelist() if n.endswith(".xml"))
            fulltext = docx_fulltext(data_bytes)
            rec["size"] = len(data_bytes)
            rec["leftover_ph"] = "{{" in xml
            keys, fkeys = CAPS[tid]
            need = []
            if "phone" in fkeys and resume["markers"][0] not in fulltext:
                need.append(resume["markers"][0])
            if "work_history" in keys and resume["markers"][1] not in fulltext:
                need.append(resume["markers"][1])
            if "education_info" in keys and resume["markers"][2] not in fulltext:
                need.append(resume["markers"][2])
            rec["missing_markers"] = need
            rec["example_residue"] = any(k in fulltext for k in [
                "示例" if "示例" in fulltext else "___NO___"])
            r4 = requests.get(BASE + "/download/" + sid,
                              params={"format": "pdf", "token": TOKEN}, timeout=150)
            rec["pdf_ok"] = r4.status_code == 200 and len(r4.content) > 5000
            rec["ok"] = (not rec["leftover_ph"]) and (not rec["missing_markers"]) \
                        and (not rec["example_residue"]) and rec["pdf_ok"]
            results.append(rec)
            print("[%s t%d] %s (%.0fs)" % (resume["name"], tid, "OK" if rec["ok"] else "FAIL", time.time()-t0), flush=True)
        except Exception as e:
            rec["ok"] = False
            rec["error"] = str(e)[:120]
            results.append(rec)
            print("[%s t%d] EXC %s" % (resume["name"], tid, str(e)[:100]), flush=True)

print()
print("=" * 60)
fails = [r for r in results if not r.get("ok")]
print("总用例: %d, 通过: %d, 失败: %d" % (len(results), len(results)-len(fails), len(fails)))
for f in fails:
    print("  FAIL:", json.dumps(f, ensure_ascii=False))
with open(os.path.join(os.environ["TEMP"], "batch_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("结果已保存 batch_results.json")
