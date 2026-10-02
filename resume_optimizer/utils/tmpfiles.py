"""临时文件安全清理。

本模块只提供一个函数 :func:`safe_unlink`，它存在的唯一理由是
**让清理环节的失败永远无法影响业务逻辑**。

背景（2026-09-18 事故复盘）
---------------------------
模板可用性探测跑到第 25 个模板时，uvicorn 进程毫无征兆地整体退出，
之后所有请求 502。根因不在 Word、不在模板，而在这一行清理代码：

    finally:
        for p in (out_path, pdf_path):
            try:
                if p.exists():
                    p.unlink()          # ← 杀手
            except Exception:
                pass

`p.unlink()` 会炸两次，两种炸法 `except Exception` 都兜不住：

1. **Windows 文件锁**：Word COM 进程尚未完全释放 docx/pdf 句柄，
   `unlink` 抛 `PermissionError`。这个还好，`Exception` 能捕到。

2. **宿主沙盒的批量删除守卫**：`sitecustomize.py` 猴补了
   `os.unlink` / `Path.unlink`。当进程带有
   ``CODEBUDDY_TOOL_CALL_ID`` + ``CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR``
   环境变量（即以「工具调用」身份被拉起）时，每次删除都会去问一次
   外部守卫；守卫判定拒绝后调用 ``_exit_bulk_guard_control()``，
   该函数在写完错误信息后执行 **``raise SystemExit(1)``**。

   ``SystemExit`` 继承自 ``BaseException``，**不是** ``Exception``。
   所以 `except Exception: pass` 完全捕不到它，异常会穿透 FastAPI 的
   异常处理器，直接终结整个 uvicorn 进程 —— 这就是「服务无故猝死」
   的真相。当时每次 `/api/template-preview` 删 2 个临时文件，第 50 次
   触发上限，正好是第 25 个模板。

因此本函数必须捕 ``BaseException``。删除被拒只会留下垃圾文件，
下次启动时由 ``main.py`` 的孤儿清理逻辑回收 —— 这是可接受的降级，
远比整个服务挂掉要好。
"""
from pathlib import Path

__all__ = ["safe_unlink"]


def safe_unlink(*paths) -> int:
    """尽力删除给定路径，返回实际删除成功的个数。

    传入 ``None`` 会被跳过，因此调用方可以放心地写
    ``safe_unlink(maybe_a, maybe_b)`` 而不必先判空。

    无论底层抛什么（``PermissionError`` / ``OSError`` / ``SystemExit``），
    本函数都不会向外抛出异常。
    """
    removed = 0
    for p in paths:
        if p is None:
            continue
        try:
            pp = Path(p)
            if pp.is_symlink() or pp.exists():
                pp.unlink()
                removed += 1
        except BaseException:  # noqa: BLE001  含 SystemExit，见模块文档
            pass
    return removed
