"""
desktop.py 的 WebView2 判定与浏览器兜底 —— 决策表测试。

为什么单独有这么一个文件: 这段逻辑只在 Windows 上、而且只在「缺 WebView2 运行时」
的机器上才会走到, 开发机和 CI 都复现不了真实环境, 靠手工验证必然烂掉。这里用假的
winreg 把注册表状态喂进去, 把六种判定和四种兜底路径全过一遍。

不依赖 pytest, 直接跑:
    cd backend && python test_desktop_probe.py
"""

import contextlib
import ntpath
import os
import sys
import tempfile
import time
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

# 真 winreg(Linux 上是 None)。测试会临时把它换成假的, 每次都必须还原成这个对象。
_ORIGINAL_WINREG = sys.modules.get("winreg")

RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
RUNTIME_KEY = rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"
# 32 位视图(没有 WOW6432Node 这一层)。两侧都要能认出来
RUNTIME_KEY_32 = rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"
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


@contextlib.contextmanager
def fake_registry(keys: dict):
    """
    临时把 winreg 换成假的, 退出时必须还原。

    不还原的后果(在 Windows 上才会暴露, Linux 跑不出来): platform.platform()
    内部会调真正的 winreg.OpenKeyEx 去读系统版本, 拿到我们这个假模块就
    AttributeError —— _check_report() 第一行就炸。
    """
    original = sys.modules.get("winreg")
    sys.modules["winreg"] = fake_winreg(keys)
    try:
        with mock.patch.object(os, "name", "nt"):
            yield
    finally:
        if original is None:
            sys.modules.pop("winreg", None)
        else:
            sys.modules["winreg"] = original


def probe_with(keys: dict, bundled: str = "") -> dict:
    with mock.patch.object(desktop, "BUNDLED_WEBVIEW2_DIR", bundled or "/nonexistent"), \
         fake_registry(keys):
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
        ("运行时注册在 32 位视图(无 WOW6432Node 层)",
         {**net48, RUNTIME_KEY_32: {"pv": "130.0.2849.68"}}, "system"),
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
        with fake_registry({APP_PATHS_EDGE: {None: f'"{edge}"'}}):
            got = desktop._find_chromium()
        check(got == edge, "App Paths 命中(顺带剥掉两侧引号)", got)

        # 注册表项指向不存在的文件 -> 不能采信它。注意这里不能断言返回空:
        # 本机真装了 Edge 的话, 函数会继续往标准安装路径找并找到 —— 那是正确行为
        # (CI 的 Windows runner 就装了 Edge, 这条一开始被我写成断言空值, 挂了)
        with fake_registry({APP_PATHS_EDGE: {None: r"C:\gone\msedge.exe"}}):
            got = desktop._find_chromium()
        check(got != r"C:\gone\msedge.exe",
              "注册表有值但文件不在 -> 不采信该路径(会继续往下找)", repr(got))

        # 真正的"哪儿都没有": 让所有路径判断都不存在
        with fake_registry({}), mock.patch.object(os.path, "isfile", lambda _p: False):
            got = desktop._find_chromium()
        check(got == "", "注册表空 + 磁盘上也没有 -> 返回空串", repr(got))

        # 标准安装路径这一支拼的是 Windows 路径, 在 Linux 上 os.path.join 拼不出
        # 真实文件, 所以换成 ntpath 语义, 断言它构造出的候选路径正确
        expect = ntpath.join(r"C:\Program Files (x86)", desktop._CHROMIUM_HINTS[0])
        with fake_registry({}), \
             mock.patch.dict(os.environ, {"ProgramFiles(x86)": r"C:\Program Files (x86)"}), \
             mock.patch.object(os.path, "join", ntpath.join), \
             mock.patch.object(os.path, "isfile", lambda p: p == expect):
            got = desktop._find_chromium()
        check(got == expect, "注册表全空 -> 退到标准安装路径", got)
    finally:
        os.unlink(edge)


class _FakeProc:
    """假的浏览器进程: wait() 按 delay 秒后返回"""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.waited = False

    def wait(self):
        self.waited = True
        if self.delay:
            time.sleep(self.delay)
        return 0


@contextlib.contextmanager
def _tmp_marker():
    """把"提示弹过了"的标记指到临时文件, 别动真的数据目录"""
    d = tempfile.mkdtemp()
    path = os.path.join(d, ".browser-mode-notified")
    with mock.patch.object(desktop, "_notice_marker", lambda: path):
        yield path


def test_browser_fallback() -> None:
    print("\n=== 浏览器兜底 ===")
    with mock.patch.object(desktop, "_find_chromium", return_value="/x/msedge.exe"), \
         mock.patch.object(desktop, "_browser_profile_dir", return_value="/tmp/prof"), \
         mock.patch("subprocess.Popen") as popen:
        how, proc = desktop._open_in_browser("http://127.0.0.1:8000")
    argv = popen.call_args[0][0] if popen.call_args else []
    check(how == "app" and "--app=http://127.0.0.1:8000" in argv,
          "有 Chromium -> --app 应用窗口模式(无标签栏)", " ".join(argv[1:]))
    check(proc is popen.return_value, "app 模式要把进程句柄带回来(拿它当退出信号)")
    # 不带独立资料目录的话, 本机已经开着 Edge 时新进程会把窗口交给已有实例然后
    # 自己退出 —— 句柄立刻结束, 会被误判成"用户关了界面"而停掉后端
    check("--user-data-dir=/tmp/prof" in argv,
          "必须带独立 --user-data-dir, 否则窗口会被已有 Edge 实例接走", " ".join(argv[1:]))

    with mock.patch.object(desktop, "_find_chromium", return_value=""), \
         mock.patch("webbrowser.open", return_value=True) as wb:
        how, proc = desktop._open_in_browser("http://x")
    check(how == "default" and wb.called and proc is None,
          "没有 Chromium -> 系统默认浏览器, 没有句柄可守")

    with mock.patch.object(desktop, "_find_chromium", return_value="/x/msedge.exe"), \
         mock.patch.object(desktop, "_browser_profile_dir", return_value="/tmp/prof"), \
         mock.patch("subprocess.Popen", side_effect=OSError("boom")), \
         mock.patch("webbrowser.open", return_value=True) as wb:
        how, proc = desktop._open_in_browser("http://x")
    check(how == "default" and wb.called and proc is None, "--app 模式失败 -> 降级默认浏览器")

    with mock.patch.object(desktop, "_find_chromium", return_value=""), \
         mock.patch("webbrowser.open", side_effect=OSError("nope")):
        how, proc = desktop._open_in_browser("http://x")
    check(how == "failed" and proc is None, "全都打不开 -> failed(弹窗提示手动复制地址)")


def test_app_window_is_the_anchor() -> None:
    """
    这一组是这次改动的要害: 应用窗口模式下不能再拿模态框当进程锚点。

    老行为是弹一个框卡住主线程, 用户得一直让它开着, 点「确定」反而把后端停了,
    浏览器窗口跟着废掉。现在守的是浏览器进程本身。
    """
    print("\n=== 应用窗口当进程锚点 ===")

    # 1) 有句柄 -> 等窗口关闭, 全程不弹阻塞框。
    #    这里把"秒退保护"的门槛调成 0: 那条是另一回事, 下面第 3 点单独测
    proc = _FakeProc()
    with _tmp_marker(), \
         mock.patch.object(desktop, "_APP_WINDOW_MIN_SECONDS", 0), \
         mock.patch.object(desktop, "_open_in_browser", return_value=("app", proc)), \
         mock.patch.object(desktop, "_message_box") as box, \
         mock.patch.object(desktop, "_notify_async") as notify:
        desktop._run_in_browser("http://x", "缺 WebView2")
    check(proc.waited, "等的是浏览器进程(窗口关了才返回)")
    check(not box.called, "不再拿模态框当锚点(点确定不会再把后端停掉)")
    check(notify.called and "关掉界面窗口即退出" in notify.call_args[0][1],
          "提示要说清怎么退出", notify.call_args[0][1][:40] if notify.called else "(没弹)")

    # 2) 提示只弹第一次 —— 缺 WebView2 是长期状态, 每次启动都弹是骚扰
    with _tmp_marker():
        for i in range(2):
            with mock.patch.object(desktop, "_APP_WINDOW_MIN_SECONDS", 0), \
                 mock.patch.object(desktop, "_open_in_browser",
                                   return_value=("app", _FakeProc())), \
                 mock.patch.object(desktop, "_message_box"), \
                 mock.patch.object(desktop, "_notify_async") as notify:
                desktop._run_in_browser("http://x", "缺 WebView2")
            check(notify.called if i == 0 else not notify.called,
                  f"第 {i + 1} 次启动{'要' if i == 0 else '不再'}弹提示")

    # 3) 进程秒退 = 窗口被已有实例接走, 不能当成"用户关了界面"
    with _tmp_marker(), \
         mock.patch.object(desktop, "_open_in_browser",
                           return_value=("app", _FakeProc())), \
         mock.patch.object(desktop, "_message_box") as box, \
         mock.patch.object(desktop, "_notify_async"), \
         mock.patch.object(desktop, "_APP_WINDOW_MIN_SECONDS", 999):
        desktop._run_in_browser("http://x", "缺 WebView2")
    check(box.called, "句柄秒退 -> 退回模态框守着, 不要直接把后端停掉")

    # 4) 没有句柄(默认浏览器 / 没打开) -> 还是模态框, 文案要齐
    for how in ("default", "failed"):
        with _tmp_marker(), \
             mock.patch.object(desktop, "_open_in_browser", return_value=(how, None)), \
             mock.patch.object(desktop, "_message_box") as box:
            desktop._run_in_browser("http://x", "缺 WebView2")
        ok = box.called and "缺 WebView2" in box.call_args[0][1]
        check(ok, f"how={how}: 没句柄可守 -> 模态框当锚点, 文案带上原因")

    # 5) wait() 自己抛异常也不能把程序卡死在这里
    class _Boom(_FakeProc):
        def wait(self):
            raise RuntimeError("handle gone")

    with _tmp_marker(), \
         mock.patch.object(desktop, "_open_in_browser", return_value=("app", _Boom())), \
         mock.patch.object(desktop, "_message_box") as box, \
         mock.patch.object(desktop, "_notify_async"):
        desktop._run_in_browser("http://x", "缺 WebView2")
    check(box.called, "等待句柄抛异常 -> 退回模态框, 不让进程无声无息地跑着")


def test_check_report() -> None:
    print("\n=== --check 诊断报告 ===")
    # 这一步必须在真 winreg 下跑: 报告里有 platform.platform(), 它内部要读注册表。
    # CI 的 Windows 任务就是在这儿炸的 —— 前面的假 winreg 没被还原
    check(sys.modules.get("winreg") is _ORIGINAL_WINREG,
          "假 winreg 已还原(否则 platform.platform() 会拿到假模块而炸)")
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
    test_app_window_is_the_anchor()
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
