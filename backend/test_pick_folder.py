"""
/api/diagnose/pick-folder 的分支测试。

为什么单独有这么一个文件: 冻结包里这条路走的是 PowerShell(打包排除了 tkinter,
而 sys.executable 是 exe 不是解释器), 而模态对话框没法在 CI 里点。所以:
  - 在真 Windows 上用 CLUSTER_MANAGER_PICKER_SELFTEST=1 跑通除"弹框"以外的整条链路
    (Add-Type / -STA / ExecutionPolicy / 临时文件 / 中文路径编码)
  - 其余分支(远程来源拒绝、非 Windows 冻结、脚本转义)在任何平台都能测

不依赖 pytest, 直接跑:
    cd backend && python test_pick_folder.py
"""

import os
import re
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from console import force_utf8  # noqa: E402

force_utf8()

from fastapi.testclient import TestClient  # noqa: E402

import api.diagnose as dg  # noqa: E402
from main import app  # noqa: E402

_failures = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        _failures.append(label)


def test_remote_client_refused() -> None:
    print("\n=== 远程来源: 不能弹框 ===")
    # TestClient 默认 client host 是 testclient, 不在本机白名单里
    with TestClient(app) as client:
        r = client.post("/api/diagnose/pick-folder", json={"initial": ""})
    ok = r.status_code == 400 and "远程" in r.json().get("detail", "")
    check(ok, "非本机来源 -> 400 且提示手填", f"{r.status_code} {r.json().get('detail', '')[:40]}")

    ok = all(h in dg._LOCAL_HOSTS for h in ("127.0.0.1", "::1", "localhost"))
    check(ok, "本机白名单覆盖 v4 / v6 / localhost")


def test_frozen_non_windows() -> None:
    print("\n=== 冻结 + 非 Windows: 明确告知手填, 不去乱起子进程 ===")
    with TestClient(app, client=("127.0.0.1", 12345)) as client, \
         mock.patch.object(sys, "frozen", True, create=True), \
         mock.patch.object(os, "name", "posix"), \
         mock.patch.object(dg, "_pick_folder_powershell",
                           side_effect=AssertionError("不该调 PowerShell")), \
         mock.patch.object(dg, "_pick_folder_tkinter",
                           side_effect=AssertionError("不该调 tkinter")):
        r = client.post("/api/diagnose/pick-folder", json={"initial": ""})
    ok = r.status_code == 400 and dg.HINT_TYPE_PATH in r.json().get("detail", "")
    check(ok, "冻结 + 非 Windows -> 400 且不启动任何子进程", str(r.status_code))


def test_script_generation() -> None:
    print("\n=== PowerShell 脚本生成(中文 + 单引号 + 空格) ===")
    tricky = r"D:\日志 导出\O'Brien"
    captured = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **_kw):
        captured["cmd"] = list(cmd)
        captured["script"] = Path(cmd[-1]).read_text(encoding="utf-8-sig")
        m = re.search(r"WriteAllText\('([^']+)'", captured["script"])
        Path(m.group(1)).write_text(tricky, encoding="utf-8")
        return Result()

    with mock.patch("subprocess.run", fake_run), \
         mock.patch.dict(os.environ, {"CLUSTER_MANAGER_PICKER_SELFTEST": "1"}):
        got = dg._pick_folder_powershell(tricky)

    check(got == tricky, "中文路径原样回来", repr(got))
    check("''Brien" in captured["script"], "单引号按 PowerShell 规则转义成两个")
    check(tricky not in " ".join(captured["cmd"][:-1]),
          "初始路径没拼进命令行(走脚本文件, 规避引号/空格陷阱)")
    for flag in ("-STA", "-NoProfile"):
        check(flag in captured["cmd"], f"命令行带 {flag}")
    check("Bypass" in captured["cmd"], "命令行带 ExecutionPolicy Bypass")


def test_powershell_real() -> None:
    """真 Windows 上非交互跑通整条链路(不弹框)"""
    print("\n=== 真实 PowerShell 链路 ===")
    if os.name != "nt":
        print("SKIP  非 Windows, 跳过(CI 的 windows 任务会跑到)")
        return
    tricky = r"D:\日志 导出\test"
    with mock.patch.dict(os.environ, {"CLUSTER_MANAGER_PICKER_SELFTEST": "1"}):
        got = dg._pick_folder_powershell(tricky)
    check(got == tricky,
          "PowerShell 起得来, 临时文件 + 中文 UTF-8 往返正确", repr(got))


def test_failure_is_actionable() -> None:
    print("\n=== 失败时给的是能照做的提示, 不是内部错误 ===")
    with TestClient(app, client=("127.0.0.1", 12345)) as client, \
         mock.patch.object(sys, "frozen", True, create=True), \
         mock.patch.object(os, "name", "nt"), \
         mock.patch.object(dg, "_pick_folder_powershell",
                           side_effect=FileNotFoundError("powershell 不见了")):
        r = client.post("/api/diagnose/pick-folder", json={"initial": ""})
    detail = r.json().get("detail", "")
    check(r.status_code == 500 and dg.HINT_TYPE_PATH in detail,
          "找不到 powershell -> 提示手填", detail[:50])


def main() -> int:
    print("/api/diagnose/pick-folder 分支测试")
    test_remote_client_refused()
    test_frozen_non_windows()
    test_script_generation()
    test_powershell_real()
    test_failure_is_actionable()

    print()
    if _failures:
        print(f"{len(_failures)} 项失败:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
