"""
桌面版启动器 — 后台启动 FastAPI/uvicorn，前台用 pywebview 打开原生窗口。

打包后双击 cluster-manager.exe 不会出现浏览器，而是一个标题为
"Cluster Manager" 的原生窗口（Windows 上由 Edge WebView2 渲染）。

WebView2 运行时三种来源，按优先级：
  1. 随包携带的固定版  exe 同级 webview2\msedgewebview2.exe（离线免安装、免管理员）
  2. 系统已安装的运行时  Win11 内置；Win10 通常没有
  3. 都没有 → 不开原生窗口，改用系统默认浏览器打开

第 3 条是必须的：WebView2 缺失时 pywebview 会静默退回 MSHTML(IE11) 内核，
Vue 3 在 IE 里直接渲染成一片空白 —— 用户看到的就是"窗口打开了但全白"，
而且没有任何提示。宁可退到浏览器，也不要给一个白窗。

诊断: cluster-manager.exe --check   (打印并弹窗显示运行时探测结果)

开发模式: python desktop.py
服务模式: python main.py   (仍可作为纯后端运行)
"""

import ctypes
import os
import platform
import sys
import time
import socket
import threading
import urllib.request
import webbrowser


from console import force_utf8

# Windows 重定向 stdout 时会用 ANSI 代码页, 编不了中文 —— 任何 print 之前先修掉
force_utf8()


# ── 冻结模式下把日志重定向到文件（console=False 时仍可排查问题）─────────
def _setup_logging():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        log_path = os.path.join(base, "cluster_manager.log")
        try:
            f = open(log_path, "a", encoding="utf-8", buffering=1)
            sys.stdout = f
            sys.stderr = f
        except Exception:
            pass


_setup_logging()

import webview
import uvicorn
from main import app


# ── WebView2 运行时探测 ───────────────────────────────────────────────────────

# 打包后 exe 所在目录; 开发模式下是 backend/。
# 注意不要用 pywebview 的相对路径解析: 它按 get_app_root() 走, PyInstaller 下
# 等于 sys._MEIPASS(即 _internal/), 不是 exe 目录 —— 所以这里一律给绝对路径。
APP_DIR = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
BUNDLED_WEBVIEW2_DIR = os.path.join(APP_DIR, "webview2")

# WebView2 各发行通道在 EdgeUpdate 下的注册表 GUID(与 pywebview 的判断保持一致)
_WEBVIEW2_CLIENTS = (
    ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "Runtime"),
    ("{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}", "Beta"),
    ("{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "Dev"),
    ("{65C35B14-6C1D-4122-AC46-7148CC9D6497}", "Canary"),
)
# pywebview 认的最低版本
_WEBVIEW2_MIN = (86, 0, 622, 0)
# WebView2 控件走 WinForms, 需要 .NET Framework 4.6.2+ (Release >= 394802)
_DOTNET_MIN_RELEASE = 394802


def _bundled_runtime() -> str:
    """随包携带的固定版运行时目录, 没有则返回空串"""
    if os.path.isfile(os.path.join(BUNDLED_WEBVIEW2_DIR, "msedgewebview2.exe")):
        return BUNDLED_WEBVIEW2_DIR
    return ""


def _parse_version(text: str) -> tuple:
    parts = []
    for chunk in str(text).split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _runtime_subkeys(guid: str) -> tuple:
    """
    一个通道要查的注册表子键。

    两个视图都查, 不去判断位数: 32 位进程看到的是 WOW6432Node 下的镜像, 而运行时
    可能注册在任一侧。用 platform.machine() 来判断是错的 —— 它给的是机器架构
    (AMD64), 而注册表重定向取决于进程位数; 更要紧的是 Windows 上
    platform.machine() 内部自己要读一次注册表, 白白把这个函数绑死在
    winreg 之外的东西上(CI 上就是在这儿炸的)。两个都试, 简单且更全。
    """
    return (
        rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}",
        rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}",
    )


def _system_runtime_version() -> str:
    """读注册表看系统装没装 WebView2 运行时, 返回版本号字符串(没装返回空串)"""
    if os.name != "nt":
        return ""
    import winreg

    for guid, _channel in _WEBVIEW2_CLIENTS:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in _runtime_subkeys(guid):
                try:
                    with winreg.OpenKey(hive, sub) as key:
                        version, _ = winreg.QueryValueEx(key, "pv")
                except OSError:
                    continue
                if version and _parse_version(version) >= _WEBVIEW2_MIN:
                    return str(version)
    return ""


def _dotnet_release() -> int:
    """.NET Framework 4.x 的 Release 号, 读不到返回 0"""
    if os.name != "nt":
        return 0
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Release")
            return int(value)
    except (OSError, ValueError, TypeError):
        return 0


def probe_webview2() -> dict:
    """
    判断原生窗口能不能用。

    source: bundled(随包固定版) / system(系统已装) / none(用不了, 退浏览器)
    """
    bundled = _bundled_runtime()
    if bundled:
        return {"source": "bundled", "path": bundled, "version": "", "dotnet": _dotnet_release(),
                "reason": "使用随包携带的 WebView2 固定版运行时"}

    if os.name != "nt":
        return {"source": "system", "path": "", "version": "", "dotnet": 0,
                "reason": "非 Windows 平台, 由 pywebview 自行选择 GTK/Qt 后端"}

    dotnet = _dotnet_release()
    if dotnet and dotnet < _DOTNET_MIN_RELEASE:
        return {"source": "none", "path": "", "version": "", "dotnet": dotnet,
                "reason": f".NET Framework 版本过低 (Release={dotnet}, 需要 >= {_DOTNET_MIN_RELEASE} 即 4.6.2)"}

    version = _system_runtime_version()
    if version:
        return {"source": "system", "path": "", "version": version, "dotnet": dotnet,
                "reason": f"系统已安装 WebView2 运行时 {version}"}

    return {"source": "none", "path": "", "version": "", "dotnet": dotnet,
            "reason": "未检测到 Edge WebView2 运行时(Win11 内置, Win10 通常需要单独安装)"}


# ── 浏览器兜底 ────────────────────────────────────────────────────────────────

def _message_box(title: str, text: str) -> None:
    """
    弹一个系统模态框。

    desktop 模式是 console=False 打的包, 没有控制台可以说话; 而且这个模态框
    还兼任"进程存活锚点"—— 后端跑在守护线程里, 主线程卡在这儿, 用户点确定
    才退出。否则进程会变成一个看不见也关不掉的后台服务。
    """
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)  # MB_ICONINFORMATION
            return
        except Exception as exc:
            print(f"[desktop] MessageBoxW 失败: {exc}")
    print(f"\n=== {title} ===\n{text}\n")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


# Chromium 内核浏览器的常见位置。注意: Edge 浏览器 ≠ WebView2 运行时, 两者
# 各装各的 —— Win10 上很可能有 Edge 浏览器却没有 WebView2 运行时, 那就用浏览器。
_CHROMIUM_EXES = ("msedge.exe", "chrome.exe")
_CHROMIUM_HINTS = (
    r"Microsoft\Edge\Application\msedge.exe",
    r"Google\Chrome\Application\chrome.exe",
)


def _find_chromium() -> str:
    """找一个 Chromium 内核浏览器的可执行文件路径, 找不到返回空串"""
    if os.name != "nt":
        return ""
    import winreg

    # 1) App Paths 注册表(比硬编码路径可靠, 装在非默认盘也能找到)
    for exe in _CHROMIUM_EXES:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(
                    hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
                ) as key:
                    path, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            path = (path or "").strip('"')
            if path and os.path.isfile(path):
                return path

    # 2) 兜底: 标准安装位置
    roots = [os.environ.get(v, "") for v in
             ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for hint in _CHROMIUM_HINTS:
            candidate = os.path.join(root, hint)
            if os.path.isfile(candidate):
                return candidate
    return ""


def _open_in_browser(url: str) -> str:
    """
    打开页面, 返回用的方式: app(无标签栏的应用窗口) / default(默认浏览器) / failed。

    优先 Chromium 的 --app 模式: 出来是一个没有标签栏和地址栏的窗口, 观感和
    原生窗口基本一致, 比丢进浏览器标签页体面得多。
    """
    chromium = _find_chromium()
    if chromium:
        try:
            import subprocess

            subprocess.Popen([chromium, f"--app={url}", "--window-size=1400,900"],
                             close_fds=True)
            print(f"[desktop] 已用应用窗口模式打开: {chromium}")
            return "app"
        except Exception as exc:
            print(f"[desktop] --app 模式失败, 退回默认浏览器: {exc}")
    try:
        webbrowser.open(url)
        return "default"
    except Exception as exc:
        print(f"[desktop] 打开浏览器失败: {exc}")
        return "failed"


def _run_in_browser(url: str, reason: str) -> None:
    """用浏览器承载界面, 并用模态框把进程留住"""
    print(f"[desktop] 退回浏览器模式: {reason}")
    how = _open_in_browser(url)

    opened = {
        "app": "已用 Edge/Chrome 的应用窗口模式打开(没有标签栏和地址栏, 观感与原生窗口一致)。",
        "default": "已用系统默认浏览器打开。",
        "failed": "自动打开浏览器失败, 请手动复制下面的地址到浏览器。",
    }[how]

    _message_box(
        "Cluster Manager",
        f"本机没有可用的内置渲染内核, {opened}\n\n"
        f"原因: {reason}\n"
        f"地址: {url}\n\n"
        "功能完全一样, 只是外壳不同。\n\n"
        "想用内置窗口, 二选一(都不需要联网):\n"
        "  1. 发布包里放入 webview2\\ 固定版运行时目录 —— 免安装、免管理员\n"
        "     (打包时加 --webview2 参数);\n"
        "  2. 在本机用管理员安装 Edge WebView2 离线安装包。\n\n"
        "点「确定」将停止后台服务并退出程序 —— 浏览器窗口也就打不开了。",
    )

# 局域网共享模式 (CLUSTER_MANAGER_BIND=0.0.0.0):
#   uvicorn 绑定 0.0.0.0, 局域网其他机器可通过 IP+端口浏览器访问
#   pywebview 窗口本地仍走 127.0.0.1, 不受影响
LOCAL_HOST = "127.0.0.1"
BIND_HOST = os.environ.get("CLUSTER_MANAGER_BIND", LOCAL_HOST).strip() or LOCAL_HOST
SHARED_MODE = BIND_HOST not in ("127.0.0.1", "localhost", "::1")
DEFAULT_PORT = int(os.environ.get("CLUSTER_MANAGER_PORT", "8000"))


def _port_available(port: int) -> bool:
    """探测端口在 BIND_HOST 上是否可用"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((BIND_HOST, port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _list_lan_ips() -> list:
    """列出本机所有非环回 IPv4 地址 (供共享模式显示访问 URL)"""
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return ips


def _pick_port(start: int) -> int:
    for p in range(start, start + 50):
        if _port_available(p):
            return p
    return start


def _wait_for_server(host: str, port: int, timeout: float = 30.0) -> bool:
    """
    用 socket 检测端口是否开放（不走 HTTP，避免防火墙拦截）
    
    原因：Windows 防火墙可能会阻止 urllib.request.urlopen() 的 HTTP 请求，
    但不会阻止 socket 连接。这样更可靠。
    """
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                print(f"[desktop] port {host}:{port} is open (attempt #{attempt})")
                return True
        except Exception as e:
            elapsed = time.time() - (deadline - timeout)
            print(f"[desktop] port check at {elapsed:.1f}s: {type(e).__name__}: {e}")
        time.sleep(0.2)
    print(f"[desktop] port {host}:{port} failed to open after {timeout}s")
    return False


def _run_server(port: int):
    uvicorn.run(app, host=BIND_HOST, port=port, log_level="info")


def _sysinfo() -> tuple:
    """取操作系统/架构描述。诊断工具不该因为取不到系统信息就崩掉"""
    try:
        return platform.platform(), platform.machine()
    except Exception as exc:
        return f"(读取失败: {exc.__class__.__name__})", "(未知)"


def _check_report() -> str:
    status = probe_webview2()
    os_desc, arch = _sysinfo()
    lines = [
        "Cluster Manager — WebView2 运行时探测",
        "",
        f"操作系统    : {os_desc}",
        f"架构        : {arch}",
        f"程序目录    : {APP_DIR}",
        f"随包运行时  : {_bundled_runtime() or '(无)'}",
        f"系统运行时  : {_system_runtime_version() or '(未安装)'}",
        f".NET Release: {_dotnet_release() or '(读不到)'}",
        f"Chromium浏览器: {_find_chromium() or '(未找到)'}",
        "",
        f"判定        : {status['source']}",
        f"说明        : {status['reason']}",
        "",
    ]
    if status["source"] == "none":
        lines += [
            "结论: 本机无法使用内置原生窗口, 启动时会自动改用浏览器承载界面"
            + ("(Edge/Chrome 应用窗口模式, 无标签栏)。" if _find_chromium() else "(系统默认浏览器)。"),
            "想要原生窗口, 二选一:",
            "  1. 安装 Edge WebView2 运行时(需管理员, 有离线安装包, 无需联网);",
            "  2. 让打包方用 --webview2 把固定版运行时放进发布包 webview2\\ 目录",
            "     —— 免安装、免管理员、免联网。",
        ]
    else:
        lines.append("结论: 可以使用内置原生窗口。")
    return "\n".join(lines)


def main():
    if "--check" in sys.argv[1:]:
        report = _check_report()
        print(report)
        # 冻结后的包是 console=False, 没有控制台可以说话, 所以额外弹窗 ——
        # 现场排查全靠它。开发模式下只打印; CLUSTER_MANAGER_NO_DIALOG=1 可强制关掉
        if (os.name == "nt" and getattr(sys, "frozen", False)
                and os.environ.get("CLUSTER_MANAGER_NO_DIALOG") != "1"):
            try:
                ctypes.windll.user32.MessageBoxW(None, report, "Cluster Manager 诊断", 0x40)
            except Exception:
                pass
        return

    port = _pick_port(DEFAULT_PORT)
    print(f"[desktop] starting backend, bind={BIND_HOST}:{port} (shared={SHARED_MODE})")
    threading.Thread(target=_run_server, args=(port,), daemon=True).start()

    # 用 socket 检测端口是否开放（不走 HTTP，避免防火墙问题）
    if not _wait_for_server(LOCAL_HOST, port, timeout=30.0):
        print(f"[desktop][error] backend failed to start at {LOCAL_HOST}:{port}", file=sys.stderr)
        sys.exit(1)

    title = "Cluster Manager"
    if SHARED_MODE:
        lan_ips = _list_lan_ips()
        if lan_ips:
            urls = ", ".join(f"http://{ip}:{port}" for ip in lan_ips)
            title = f"Cluster Manager (LAN: {urls})"
            print(f"[desktop] shared mode - LAN access: {urls}")
        else:
            title = f"Cluster Manager (shared mode, port {port})"

    url = f"http://{LOCAL_HOST}:{port}"

    # 能不能开原生窗口, 在这里定。用不了就直接退浏览器 ——
    # 硬着头皮调 webview.start() 的结果是 pywebview 退回 IE11 内核渲染出一片白。
    try:
        status = probe_webview2()
    except Exception as exc:
        # 探测只是为了避免白屏, 它自己出问题不该把本来能用的机器拖下水 ——
        # 按"系统可用"处理, 行为回到改动之前
        print(f"[desktop][warn] WebView2 探测异常, 按系统可用处理: {exc!r}")
        status = {"source": "system", "path": "", "version": "", "dotnet": 0,
                  "reason": f"探测异常({exc.__class__.__name__}), 按系统可用处理"}
    print(f"[desktop] webview2: source={status['source']} — {status['reason']}")
    if status["source"] == "none":
        _run_in_browser(url, status["reason"])
        return
    if status["source"] == "bundled":
        # pywebview 会把它交给 CoreWebView2CreationProperties.BrowserExecutableFolder
        webview.settings["WEBVIEW2_RUNTIME_PATH"] = status["path"]

    print(f"[desktop] opening webview window -> {url}")

    # 暴露给前端 JS: window.pywebview.api.pick_folder() — 调系统原生目录选择
    # 用于日志导出页"输出目录"的浏览按钮; 浏览器侧 fetch 拿不到绝对路径,
    # 只有走 pywebview 的原生桥或后端 subprocess 才能取到 Windows 完整路径
    class JSAPI:
        def pick_folder(self, initial: str = ""):
            try:
                res = webview.windows[0].create_file_dialog(
                    webview.FOLDER_DIALOG,
                    directory=initial or "",
                )
            except Exception as e:
                print(f"[desktop][pick_folder] {e}")
                return ""
            return res[0] if res else ""

    webview.create_window(
        title=title,
        url=url,
        width=1400,
        height=900,
        min_size=(1024, 700),
        resizable=True,
        js_api=JSAPI(),
    )
    # 开启 DevTools: 在窗口内按 F12 / Ctrl+Shift+I 打开开发者工具,
    # 可以看到 console.log / Network 面板 (排查 API 返回值)
    # 关闭 DevTools 不影响业务, 上线后可改为 debug=False
    devtools_enabled = os.environ.get("CLUSTER_MANAGER_DEVTOOLS", "1") != "0"
    try:
        webview.start(debug=devtools_enabled)
    except Exception as exc:
        # 探测通过但窗口仍然创建失败(缺 .NET 组件、运行时被杀软拦、显卡驱动等),
        # 一样退到浏览器, 不要让用户对着一个崩掉的窗口
        print(f"[desktop][error] 原生窗口启动失败: {exc.__class__.__name__}: {exc}")
        _run_in_browser(url, f"原生窗口启动失败({exc.__class__.__name__}: {exc})")


if __name__ == "__main__":
    main()