"""
desktop.py 的 WebView2 判定与浏览器兜底 —— 决策表测试。

为什么单独有这么一个文件: 这段逻辑只在 Windows 上、而且只在「缺 WebView2 运行时」
的机器上才会走到, 开发机和 CI 都复现不了真实环境, 靠手工验证必然烂掉。这里用假的
winreg 把注册表状态喂进去, 把六种判定和四种兜底路径全过一遍。

不依赖 pytest, 直接跑:
    cd backend && python test_desktop_probe.py
"""

import ntpath
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from console import force_utf8  # noqa: E402

force_utf8()

# webview / uvicorn / main 导入代价大(且 Linux 上 webview 可能装不了),
# 这里只测判定逻辑, 全部打桩
_stub_webview = types.ModuleType("webview")
_stub_webview.settings = {"WEBVIEW2_RUNTIME_PATH": None}
sys.modules.setdefault("webview", _stub_webview)
sys.modules.setdefault("uvicorn", types.ModuleType("uvicorn"))
if "main" not in sys.modules:
    _stub_main = types.ModuleType("main")
    _stub_main.app = object()
    sys.modules["main"] = _stub_main

import desktop  # noqa: E402

RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
RUNTIME_KEY = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"
DOTNET_KEY = r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"
APP_PATHS_EDGE = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"

_failures = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        _failures.append(label)


def fake_winreg(keys: dict) -> types.ModuleType:
    """keys: {子键路径: {值名(None 表示默认值): 数据}}"""
    mod = types.ModuleType("winreg")
    mod.HKEY_CURRENT_USER, mod.HKEY_LOCAL_MACHINE = "HKCU", "HKLM"

    class Key:
        def __init__(self, values):
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def open_key(_hive, sub):
        if sub not in keys:
            raise OSError(2, "not found")
        return Key(keys[sub])

    def query(key, name):
        if name not in key.values:
            raise OSError(2, "no value")
        return key.values[name], 1

    mod.OpenKey, mod.QueryValueEx = open_key, query
    return mod


def probe_with(keys: dict, bundled: str = "") -> dict:
    with mock.patch.object(desktop, "BUNDLED_WEBVIEW2_DIR", bundled or "/nonexistent"), \
         mock.patch.object(os, "name", "nt"):
        sys.modules["winreg"] = fake_winreg(keys)
        return desktop.probe_webview2()


def test_registry_decisions() -> None:
    print("\n=== 系统注册表判定 ===")
    net48 = {DOTNET_KEY: {"Release": 528040}}

    cases = [
        ("Win11: 运行时 130 + .NET 4.8", {**net48, RUNTIME_KEY: {"pv": "130.0.2849.68"}}, "system"),
        ("Win10 离线: 无运行时", net48, "none"),
        ("边界: 运行时正好 86.0.622.0", {**net48, RUNTIME_KEY: {"pv": "86.0.622.0"}}, "system"),
        ("边界: 运行时 86.0.621.9 过旧", {**net48, RUNTIME_KEY: {"pv": "86.0.621.9"}}, "none"),
        (".NET 4.5 过低(有运行时也不行)",
         {DOTNET_KEY: {"Release": 378389}, RUNTIME_KEY: {"pv": "130.0.2849.68"}}, "none"),
        ("读不到 .NET 键 + 有运行时", {RUNTIME_KEY: {"pv": "130.0.2849.68"}}, "system"),
        ("pv 是空串", {**net48, RUNTIME_KEY: {"pv": ""}}, "none"),
    ]
    for label, keys, expect in cases:
        got = probe_with(keys)
        check(got["source"] == expect, label, f"{got['source']} (期望 {expect})")


def test_bundled_runtime() -> None:
    print("\n=== 随包固定版运行时 ===")
    net48 = {DOTNET_KEY: {"Release": 528040}}
    with tempfile.TemporaryDirectory() as td:
        rt = Path(td) / "webview2"
        rt.mkdir()
        exe = rt / "msedgewebview2.exe"
        exe.write_bytes(b"MZ")

        got = probe_with(net48, bundled=str(rt))
        check(got["source"] == "bundled", "系统未装但包内自带 -> bundled", got["source"])
        check(os.path.isabs(got["path"]),
              "交给 pywebview 的是绝对路径",
              "相对路径会被按 sys._MEIPASS 解析, 落到 _internal/ 而不是 exe 目录")

        # 有运行时也优先用自带的: 版本可控, 不受目标机环境影响
        got = probe_with({**net48, RUNTIME_KEY: {"pv": "130.0.2849.68"}}, bundled=str(rt))
        check(got["source"] == "bundled", "系统也装了 -> 仍优先用包内自带", got["source"])

        exe.unlink()
        got = probe_with(net48, bundled=str(rt))
        check(got["source"] == "none", "webview2/ 目录存在但没有 msedgewebview2.exe -> none",
              got["source"])


def test_version_parse() -> None:
    print("\n=== 版本号比较 ===")
    for a, b, expect in (
        ("130.0.2849.68", "86.0.622.0", True),
        ("86.0.622.0", "86.0.622.0", True),
        ("86.0.621.9", "86.0.622.0", False),
        ("1.2.x.4", "86.0.622.0", False),
        ("87", "86.0.622.0", True),
    ):
        got = desktop._parse_version(a) >= desktop._parse_version(b)
        check(got == expect, f"{a} >= {b} -> {got}")


def test_find_chromium() -> None:
    print("\n=== Chromium 浏览器查找(兜底用) ===")
    with tempfile.NamedTemporaryFile(suffix="-msedge.exe", delete=False) as f:
        edge = f.name

    try:
        with mock.patch.object(os, "name", "nt"):
            sys.modules["winreg"] = fake_winreg({APP_PATHS_EDGE: {None: f'"{edge}"'}})
            got = desktop._find_chromium()
        check(got == edge, "App Paths 命中(顺带剥掉两侧引号)", got)

        with mock.patch.object(os, "name", "nt"):
            sys.modules["winreg"] = fake_winreg({APP_PATHS_EDGE: {None: r"C:\gone\msedge.exe"}})
            got = desktop._find_chromium()
        check(got == "", "注册表有值但文件不在 -> 视为未找到", repr(got))

        # 标准安装路径这一支拼的是 Windows 路径, 在 Linux 上 os.path.join 拼不出
        # 真实文件, 所以换成 ntpath 语义, 断言它构造出的候选路径正确
        expect = ntpath.join(r"C:\Program Files (x86)", desktop._CHROMIUM_HINTS[0])
        with mock.patch.object(os, "name", "nt"), \
             mock.patch.dict(os.environ, {"ProgramFiles(x86)": r"C:\Program Files (x86)"}), \
             mock.patch.object(os.path, "join", ntpath.join), \
             mock.patch.object(os.path, "isfile", lambda p: p == expect):
            sys.modules["winreg"] = fake_winreg({})
            got = desktop._find_chromium()
        check(got == expect, "注册表全空 -> 退到标准安装路径", got)
    finally:
        os.unlink(edge)


def test_browser_fallback() -> None:
    print("\n=== 浏览器兜底 ===")
    with mock.patch.object(desktop, "_find_chromium", return_value="/x/msedge.exe"), \
         mock.patch("subprocess.Popen") as popen:
        how = desktop._open_in_browser("http://127.0.0.1:8000")
    argv = popen.call_args[0][0] if popen.call_args else []
    check(how == "app" and "--app=http://127.0.0.1:8000" in argv,
          "有 Chromium -> --app 应用窗口模式(无标签栏)", " ".join(argv[1:]))

    with mock.patch.object(desktop, "_find_chromium", return_value=""), \
         mock.patch("webbrowser.open", return_value=True) as wb:
        how = desktop._open_in_browser("http://x")
    check(how == "default" and wb.called, "没有 Chromium -> 系统默认浏览器")

    with mock.patch.object(desktop, "_find_chromium", return_value="/x/msedge.exe"), \
         mock.patch("subprocess.Popen", side_effect=OSError("boom")), \
         mock.patch("webbrowser.open", return_value=True) as wb:
        how = desktop._open_in_browser("http://x")
    check(how == "default" and wb.called, "--app 模式失败 -> 降级默认浏览器")

    with mock.patch.object(desktop, "_find_chromium", return_value=""), \
         mock.patch("webbrowser.open", side_effect=OSError("nope")):
        how = desktop._open_in_browser("http://x")
    check(how == "failed", "全都打不开 -> failed(弹窗提示手动复制地址)")

    for how in ("app", "default", "failed"):
        with mock.patch.object(desktop, "_open_in_browser", return_value=how), \
             mock.patch.object(desktop, "_message_box") as box:
            desktop._run_in_browser("http://x", "缺 WebView2")
        ok = box.called and "缺 WebView2" in box.call_args[0][1]
        check(ok, f"how={how}: 文案齐全且带上原因(不会 KeyError)")


def test_check_report() -> None:
    print("\n=== --check 诊断报告 ===")
    try:
        report = desktop._check_report()
        check("判定" in report and "WebView2" in report,
              "报告可渲染", f"{len(report.splitlines())} 行")
    except Exception as exc:
        check(False, "报告渲染抛异常", repr(exc))


def main() -> int:
    print("desktop.py WebView2 判定 / 兜底 决策表测试")
    test_registry_decisions()
    test_bundled_runtime()
    test_version_parse()
    test_find_chromium()
    test_browser_fallback()
    test_check_report()

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
