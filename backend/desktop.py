"""
桌面版启动器 — 后台启动 FastAPI/uvicorn，前台用 pywebview 打开原生窗口。

打包后双击 cluster-manager.exe 不会出现浏览器，而是一个标题为
"Cluster Manager" 的原生窗口（Windows 10/11 使用 Edge WebView2 渲染）。

开发模式: python desktop.py
服务模式: python main.py   (仍可作为纯后端运行)
"""

import os
import sys
import time
import socket
import threading
import urllib.request


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


def main():
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

    print(f"[desktop] opening webview window -> http://{LOCAL_HOST}:{port}")

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
        url=f"http://{LOCAL_HOST}:{port}",
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
    webview.start(debug=devtools_enabled)


if __name__ == "__main__":
    main()