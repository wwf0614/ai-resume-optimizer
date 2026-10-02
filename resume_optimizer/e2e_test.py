"""端到端测试：用表格型 docx（模拟 PDF 转换）测试完整优化流程。"""
import json
import urllib.request
import urllib.error
import uuid as _uuid

BASE = "http://127.0.0.1:8000"

# 构造 multipart 表单
boundary = "----test" + _uuid.uuid4().hex
body = b""
for name, path in [("resume", r"D:\DeepseekV4\resume_optimizer\test_table.docx"),
                   ("job_text", r"D:\DeepseekV4\resume_optimizer\test_job.txt")]:
    with open(path, "rb") as f:
        content = f.read()
    body += f"--{boundary}\r\n".encode()
    if name == "job_text":
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += content
    else:
        body += f'Content-Disposition: form-data; name="{name}"; filename="{path}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += content
    body += b"\r\n"
body += f"--{boundary}--\r\n".encode()

req = urllib.request.Request(f"{BASE}/optimize", data=body, method="POST")
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
sid = data["session_id"]
print(f"optimize: sid={sid}, rewritten_count={data.get('rewritten_count')}")
print(f"comparisons: {len(data.get('comparisons', []))} items")
for c in data.get("comparisons", []):
    print(f"  [{c['type']}] {c['section']}:")
    print(f"    before: {c['before'][:50]}")
    print(f"    after:  {c['after'][:50]}")

# 下载 Word
try:
    r = urllib.request.urlopen(f"{BASE}/download/{sid}?format=docx")
    docx_bytes = r.read()
    with open(r"D:\DeepseekV4\resume_optimizer\dl.docx", "wb") as f:
        f.write(docx_bytes)
    print(f"\ndownload docx: http={r.status}, size={len(docx_bytes)}")
except urllib.error.HTTPError as e:
    print(f"\ndownload docx: FAILED http={e.code}")
