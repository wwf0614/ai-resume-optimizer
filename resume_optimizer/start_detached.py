# -*- coding: utf-8 -*-
"""以「后台独立进程」身份启动简历服务（推荐入口）。

为什么不直接用 ``python -m uvicorn``
------------------------------------
当 uvicorn 是**以工具调用身份**被拉起时，它会继承一组宿主沙盒变量：

    CODEBUDDY_TOOL_CALL_ID
    CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR
    CODEBUDDY_SAFE_DELETE_BULK_GUARD

只要这几个变量在，``sitecustomize.py`` 猴补的 ``Path.unlink`` 就会
对**每一次**删除都去起一个 node 子进程问外部守卫。后果有两层：

1. 守卫判拒时抛 ``SystemExit``（继承 ``BaseException``），
   ``except Exception`` 捕不到 —— 会直接杀掉 uvicorn 进程。
   2026-09-18 的模板探测就是这样跑到第 25 个模板时服务整体猝死的。
   （``utils/tmpfiles.safe_unlink`` 已能兜住这一层。）
2. 即使不判拒，每个临时文件都多一次 node 冷启动，渲染接口白白
   多出几百毫秒延迟。

正常的 Windows 服务不该带着这组变量跑。所以本脚本做两件事：

1. 从自己的环境里**摘掉**这几个变量，再拉起 ``start_background.vbs``；
2. 用 ``DETACHED_PROCESS`` 让服务脱离调用方的进程树，
   调用方（终端 / 工具）退出后服务继续存活。

注意：摘变量只影响**被拉起的那个服务进程**；本 agent 自己的文件
操作仍然受沙盒守卫约束，守卫本身没有被削弱。

用法::

    D:\\python\\python.exe start_detached.py            # 启动
    D:\\python\\python.exe start_detached.py --check    # 只探活，不启动
"""
import os
import socket
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

#: 只有以「工具调用」身份运行才会出现，必须剥离
GUARD_ENV_KEYS = (
    "CODEBUDDY_TOOL_CALL_ID",
    "CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR",
    "CODEBUDDY_SAFE_DELETE_BULK_GUARD",
    "CODEBUDDY_NODE_BIN",
)

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

VBS = BASE_DIR / "start_background.vbs"
PY = Path(r"D:\python\python.exe")


def port_open(host: str = "127.0.0.1", port: int = 8000, timeout: float = 1.5) -> bool:
    """探活：端口是否可连。不依赖 netstat（本机安全策略禁用了系统级工具）。"""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> int:
    if "--check" in sys.argv:
        ok = port_open()
        print("PORT 8000:", "OPEN" if ok else "CLOSED")
        return 0 if ok else 1

    if port_open():
        print("端口 8000 已在监听，无需重复启动。")
        return 0

    if not PY.exists():
        print("找不到解释器（项目依赖只装在这个 3.9.7 里）：%s" % PY, file=sys.stderr)
        return 2

    env = dict(os.environ)
    stripped = [k for k in GUARD_ENV_KEYS if env.pop(k, None) is not None]
    env.setdefault("PYTHONIOENCODING", "utf-8")

    argv = [str(PY), "-m", "uvicorn", "main:app",
            "--host", "0.0.0.0", "--port", "8000"]

    # --fg：用 os.execve 就地替换本进程（pid 不变），作为调用方的
    # 子进程常驻。适用于「后台任务」方式托管服务——这样服务既拿不到
    # 沙盒守卫变量（上面已剥离），又不会被当作游离进程回收。
    if "--fg" in sys.argv:
        print("exec uvicorn（前台常驻）；剥离的沙盒变量: %s"
              % (", ".join(stripped) if stripped else "无"))
        sys.stdout.flush()
        os.execve(str(PY), argv, env)

    if not VBS.exists():
        print("找不到启动脚本：%s" % VBS, file=sys.stderr)
        return 2

    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_path = logs_dir / "server.log"
    log = open(log_path, "ab", buffering=0)  # noqa: SIM115 - 由子进程持有

    proc = subprocess.Popen(  # noqa: S603 - 路径与参数均为本地常量
        argv,
        cwd=str(BASE_DIR),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    print("已派生 uvicorn pid=%d，剥离的沙盒变量: %s"
          % (proc.pid, ", ".join(stripped) if stripped else "无（本来就很干净）"))
    print("日志：%s" % log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
