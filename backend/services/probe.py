"""
真探测 —— ICMP ping 与 TCP 端口连通性。

在这之前, network_service.check_connectivity 和 api/network.check_node_network
返回的都是写死的模拟值(真 ping 那行被注释掉了)。一键诊断要是建在模拟值上,
报出来的"正常"就是假的, 所以这里做真的。

只用标准库:
  ping  调系统自带的 ping 命令 —— 不需要 root(自己发 ICMP 要原始套接字)
  tcp   socket.create_connection

Windows 上有两个坑, 都在下面处理了:
  1. ping.exe 收到"无法访问目标主机"这类 ICMP 差错回包时退出码也是 0, 光看
     退出码会把不通判成通。只有真的 echo reply 才会打印 TTL=, 所以退出码和
     TTL= 两个条件都要满足
  2. 冻结成 exe 后起子进程会闪一个黑框, 用 CREATE_NO_WINDOW 压掉
"""

import os
import re
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

IS_WINDOWS = os.name == "nt"

# 两种 locale 下 ping 输出里的往返时间: "time=0.123 ms" / "时间=1ms" / "time<1ms"
_RTT_RE = re.compile(rb"[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE)

# 并发度: 现场一套集群几十台, 再多也没必要把管理网打满
MAX_WORKERS = 16


def _no_window() -> Dict:
    """冻结后起子进程不要闪黑框"""
    if not IS_WINDOWS:
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def ping(host: str, timeout_ms: int = 1000) -> Dict:
    """
    ping 一次。返回 {ok, latency_ms, detail}。

    latency_ms 取自 ping 自己打印的往返时间, 不是我们掐的墙上时间 —— 后者包含
    起进程的开销(几十毫秒), 拿去和 2ms 的基线比毫无意义。
    """
    host = (host or "").strip()
    if not host:
        return {"ok": False, "latency_ms": None, "detail": "没有地址"}

    if IS_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_ms)), host]
    else:
        # -W 在 Linux 上是秒, 至少给 1 秒
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(round(timeout_ms / 1000.0)))), host]

    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=max(2.0, timeout_ms / 1000.0 + 2.0), **_no_window()
        )
    except FileNotFoundError:
        return {"ok": False, "latency_ms": None, "detail": "系统里没有 ping 命令"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "latency_ms": None, "detail": f"超时(>{timeout_ms}ms)"}
    except OSError as exc:
        return {"ok": False, "latency_ms": None, "detail": f"起 ping 失败: {exc}"}

    out = proc.stdout or b""
    # 退出码 0 还不够: Windows 收到"无法访问目标主机"的差错回包也是 0
    got_reply = proc.returncode == 0 and b"ttl=" in out.lower()

    latency = None
    m = _RTT_RE.search(out)
    if m:
        try:
            latency = float(m.group(1))
        except ValueError:
            latency = None

    if got_reply:
        return {"ok": True, "latency_ms": latency, "detail": ""}
    if proc.returncode == 0:
        return {"ok": False, "latency_ms": None, "detail": "收到差错回包, 目标不可达"}
    return {"ok": False, "latency_ms": None, "detail": "无响应"}


def tcp(host: str, port: int, timeout: float = 2.0) -> Dict:
    """TCP 连得上就算通。latency_ms 是建连耗时。"""
    host = (host or "").strip()
    if not host:
        return {"ok": False, "latency_ms": None, "detail": "没有地址"}

    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
    except socket.timeout:
        return {"ok": False, "latency_ms": None, "detail": f"连 {port} 端口超时"}
    except ConnectionRefusedError:
        return {"ok": False, "latency_ms": None, "detail": f"{port} 端口拒绝连接(服务没起?)"}
    except OSError as exc:
        return {"ok": False, "latency_ms": None, "detail": f"连 {port} 端口失败: {exc}"}
    return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000, 1), "detail": ""}


def tcp_any(host: str, ports: List[int], timeout: float = 2.0) -> Dict:
    """任一端口通就算通 —— BMC 有的走 443 有的走 5900/623, 挨个试"""
    last = {"ok": False, "latency_ms": None, "detail": "没有可试的端口"}
    for port in ports:
        last = tcp(host, port, timeout)
        if last["ok"]:
            last = {**last, "port": port}
            return last
    return last


def run_all(jobs: List[Tuple[str, callable]], max_workers: Optional[int] = None) -> Dict[str, Dict]:
    """
    并发跑一批探测。jobs 是 [(任务 id, 无参可调用)], 返回 {任务 id: 结果}。

    单个任务抛异常不会带垮整批 —— 诊断跑到一半炸掉比报错还难查。
    """
    if not jobs:
        return {}

    def _guard(fn):
        try:
            return fn()
        except Exception as exc:           # noqa: BLE001 —— 探测失败本身就是一种结果
            return {"ok": False, "latency_ms": None,
                    "detail": f"探测出错({exc.__class__.__name__}: {exc})"}

    workers = max_workers or min(MAX_WORKERS, len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {key: pool.submit(_guard, fn) for key, fn in jobs}
        return {key: fut.result() for key, fut in futures.items()}
