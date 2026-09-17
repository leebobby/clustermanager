"""
SSH诊断服务 - 远程命令执行 & 日志采集
"""

import os
import time
from datetime import datetime
from typing import List, Dict, Callable, Optional

try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False


# 退出码语义
EXIT_TIMEOUT   = -2
EXIT_CANCELLED = -3
EXIT_ERROR     = -1


def _require_paramiko():
    if not PARAMIKO_AVAILABLE:
        raise RuntimeError("paramiko 未安装，请运行: pip install paramiko")


def _make_client(host: str, port: int, username: str, password: str) -> "paramiko.SSHClient":
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host, port=port,
        username=username, password=password,
        timeout=10, banner_timeout=30,
        allow_agent=False, look_for_keys=False
    )
    return client


def run_ssh_command(
    host: str, port: int, username: str, password: str,
    command: str, timeout: int = 30,
    is_cancelled: Optional[Callable[[], bool]] = None,
    on_client: Optional[Callable[["paramiko.SSHClient"], None]] = None,
) -> Dict:
    """
    SSH 执行命令, 返回 stdout/stderr/exit_code。

    关键改动 (相对早期实现):
      - 用 channel 轮询代替 exec_command(timeout=N) + recv_exit_status,
        前者只控制 socket I/O 间隔, 命令长时间不输出也不会超时;
        现在用本地计时器实现真·硬超时, 命中即关闭 channel 强制中断。
      - 支持 is_cancelled 回调, 用户点终止时立刻收尾。
      - on_client 回调把刚连上的 paramiko client 暴露出去, 取消端点
        可以拿到引用直接 close() 把所有阻塞 I/O 打断。
    """
    _require_paramiko()
    client = None
    out_buf = bytearray()
    err_buf = bytearray()
    try:
        client = _make_client(host, port, username, password)
        if on_client:
            try: on_client(client)
            except Exception: pass

        transport = client.get_transport()
        chan = transport.open_session()
        chan.settimeout(0.5)        # 非阻塞轮询
        chan.exec_command(command)

        deadline = time.time() + max(1, int(timeout))
        max_out = 50_000
        max_err = 5_000

        while True:
            # ── 取消 / 超时 ──
            if is_cancelled and is_cancelled():
                try: chan.close()
                except Exception: pass
                return {
                    "success": False,
                    "stdout": out_buf.decode("utf-8", errors="replace"),
                    "stderr": "[已手动终止]",
                    "exit_code": EXIT_CANCELLED,
                }
            if time.time() > deadline:
                try: chan.close()
                except Exception: pass
                return {
                    "success": False,
                    "stdout": out_buf.decode("utf-8", errors="replace"),
                    "stderr": f"[超时 {timeout}s, 已强制中断]",
                    "exit_code": EXIT_TIMEOUT,
                }

            # ── 读取已就绪数据 ──
            drained = False
            if chan.recv_ready():
                out_buf.extend(chan.recv(4096))
                drained = True
            if chan.recv_stderr_ready():
                err_buf.extend(chan.recv_stderr(4096))
                drained = True

            # ── 命令已退出: drain 剩余数据后退出循环 ──
            if chan.exit_status_ready():
                # 把通道里剩下的字节都吃干净
                while chan.recv_ready():
                    out_buf.extend(chan.recv(4096))
                while chan.recv_stderr_ready():
                    err_buf.extend(chan.recv_stderr(4096))
                exit_code = chan.recv_exit_status()
                out = out_buf.decode("utf-8", errors="replace")
                err = err_buf.decode("utf-8", errors="replace")
                if len(out) > max_out:
                    out = out[:max_out] + f"\n\n[输出已截断, 共 {len(out)} 字节]"
                if len(err) > max_err:
                    err = err[:max_err] + f"\n\n[stderr 已截断]"
                return {
                    "success": exit_code == 0,
                    "stdout": out,
                    "stderr": err,
                    "exit_code": exit_code,
                }

            if not drained:
                time.sleep(0.05)    # 避让 CPU
    except Exception as e:
        return {
            "success": False,
            "stdout": out_buf.decode("utf-8", errors="replace") if out_buf else "",
            "stderr": str(e),
            "exit_code": EXIT_ERROR,
        }
    finally:
        if client:
            try: client.close()
            except Exception: pass


def export_files_via_sftp(
    host: str, port: int, username: str, password: str,
    discover_script: str, output_dir: str, timeout: int = 60,
    is_cancelled: Optional[Callable[[], bool]] = None,
    on_client: Optional[Callable[["paramiko.SSHClient"], None]] = None,
) -> Dict:
    """
    日志导出 files 模式实现:
      Phase 1: SSH 执行 discover_script, stdout 行 = 待下载文件的绝对路径
               (空行 / # 注释行忽略)
      Phase 2: 对每条路径 SFTP 拉完整文件到 output_dir; 权限不足兜底 sudo cat
      Phase 3: 同名文件自动追加 -2/-3 后缀避免覆盖

    返回:
      {
        "discover_error": Optional[str],     # None 表示发现阶段成功
        "discover_stderr": str,              # 发现脚本的 stderr (即便成功也可能有)
        "files": [
          {"remote": str, "local": Optional[str], "size": int,
           "success": bool, "error": Optional[str], "note": Optional[str]}
        ],
      }
    """
    _require_paramiko()
    import shlex

    result: Dict = {"discover_error": None, "discover_stderr": "", "files": []}
    client = None
    try:
        client = _make_client(host, port, username, password)
        if on_client:
            try: on_client(client)
            except Exception: pass

        # ── Phase 1: discover ───────────────────────────────────────
        transport = client.get_transport()
        chan = transport.open_session()
        chan.settimeout(0.5)
        chan.exec_command(discover_script)

        deadline = time.time() + max(1, int(timeout))
        out_buf = bytearray()
        err_buf = bytearray()
        while True:
            if is_cancelled and is_cancelled():
                try: chan.close()
                except Exception: pass
                result["discover_error"] = "[已手动终止]"
                return result
            if time.time() > deadline:
                try: chan.close()
                except Exception: pass
                result["discover_error"] = f"[发现脚本超时 {timeout}s]"
                return result
            drained = False
            if chan.recv_ready():
                out_buf.extend(chan.recv(8192))
                drained = True
            if chan.recv_stderr_ready():
                err_buf.extend(chan.recv_stderr(4096))
                drained = True
            if chan.exit_status_ready():
                while chan.recv_ready():
                    out_buf.extend(chan.recv(8192))
                while chan.recv_stderr_ready():
                    err_buf.extend(chan.recv_stderr(4096))
                exit_code = chan.recv_exit_status()
                break
            if not drained:
                time.sleep(0.05)

        result["discover_stderr"] = err_buf.decode("utf-8", errors="replace")[:2000]
        if exit_code != 0:
            result["discover_error"] = f"发现脚本退出码 {exit_code}"
            return result

        # 解析路径列表
        raw_lines = out_buf.decode("utf-8", errors="replace").splitlines()
        paths = []
        for line in raw_lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            paths.append(line)

        if not paths:
            return result  # 没匹配到任何文件, files = []

        # ── Phase 2: SFTP 每个文件 ──────────────────────────────────
        os.makedirs(output_dir, exist_ok=True)
        sftp = client.open_sftp()
        try:
            for remote in paths:
                if is_cancelled and is_cancelled():
                    result["files"].append({
                        "remote": remote, "local": None, "size": 0,
                        "success": False, "error": "[已取消]", "note": None,
                    })
                    continue

                # 本地文件名 = basename, 同名自动 -2/-3 后缀
                base = os.path.basename(remote.rstrip("/")) or remote.replace("/", "_").strip("_")
                local = os.path.join(output_dir, base)
                if os.path.exists(local):
                    root, ext = os.path.splitext(base)
                    n = 2
                    while os.path.exists(os.path.join(output_dir, f"{root}-{n}{ext}")):
                        n += 1
                    local = os.path.join(output_dir, f"{root}-{n}{ext}")

                try:
                    sftp.get(remote, local)
                    size = os.path.getsize(local)
                    result["files"].append({
                        "remote": remote, "local": local, "size": size,
                        "success": True, "error": None, "note": None,
                    })
                except FileNotFoundError:
                    result["files"].append({
                        "remote": remote, "local": None, "size": 0,
                        "success": False, "error": "文件不存在", "note": None,
                    })
                except PermissionError:
                    # 权限不足时尝试 sudo cat (会丢失二进制属性但能拿到文本)
                    try:
                        _, stdout, stderr = client.exec_command(
                            f"sudo -n cat {shlex.quote(remote)}", timeout=60
                        )
                        content = stdout.read()
                        err_text = stderr.read().decode("utf-8", errors="replace")
                        if content:
                            with open(local, "wb") as f:
                                f.write(content)
                            result["files"].append({
                                "remote": remote, "local": local, "size": len(content),
                                "success": True, "error": None, "note": "sudo cat 兜底",
                            })
                        else:
                            result["files"].append({
                                "remote": remote, "local": None, "size": 0,
                                "success": False,
                                "error": f"权限不足且 sudo 不可用: {err_text.strip()[:200]}",
                                "note": None,
                            })
                    except Exception as e:
                        result["files"].append({
                            "remote": remote, "local": None, "size": 0,
                            "success": False, "error": f"权限不足: {e}", "note": None,
                        })
                except Exception as e:
                    result["files"].append({
                        "remote": remote, "local": None, "size": 0,
                        "success": False, "error": str(e), "note": None,
                    })
        finally:
            try: sftp.close()
            except Exception: pass

        return result

    except Exception as e:
        result["discover_error"] = f"SSH 连接失败: {e}"
        return result
    finally:
        if client:
            try: client.close()
            except Exception: pass


def collect_node_logs(
    host: str, port: int, username: str, password: str,
    log_paths: List[str], target_dir: str, node_name: str
) -> Dict:
    """
    从OpenEuler节点采集日志文件到Windows目录。

    log_paths 规则:
      - 以 "/" 开头 → SFTP 直接下载文件
      - 其他 → 作为 shell 命令执行，输出保存为 .log 文件
        (例: "dmesg", "journalctl --no-pager -n 2000")
    """
    _require_paramiko()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    node_dir = os.path.join(target_dir, node_name, timestamp)

    client = None
    file_results = []

    try:
        os.makedirs(node_dir, exist_ok=True)
        client = _make_client(host, port, username, password)
        sftp = client.open_sftp()

        for log_path in log_paths:
            if log_path.startswith('/'):
                # SFTP 文件下载
                filename = os.path.basename(log_path) or log_path.replace('/', '_').strip('_')
                local_path = os.path.join(node_dir, filename)
                try:
                    sftp.get(log_path, local_path)
                    size = os.path.getsize(local_path)
                    file_results.append({
                        "path": log_path,
                        "status": "success",
                        "local": local_path,
                        "size_kb": round(size / 1024, 1)
                    })
                except FileNotFoundError:
                    file_results.append({"path": log_path, "status": "not_found"})
                except PermissionError:
                    # 权限不足时尝试 sudo cat 读取
                    try:
                        _, stdout, stderr = client.exec_command(
                            f"sudo cat {log_path} 2>/dev/null", timeout=30
                        )
                        content = stdout.read().decode('utf-8', errors='replace')
                        with open(local_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        file_results.append({
                            "path": log_path,
                            "status": "success_sudo",
                            "local": local_path
                        })
                    except Exception as e2:
                        file_results.append({
                            "path": log_path, "status": "permission_denied",
                            "error": str(e2)
                        })
                except Exception as e:
                    file_results.append({"path": log_path, "status": "error", "error": str(e)})
            else:
                # 命令执行，保存输出
                safe_name = log_path.split()[0].replace('/', '_').strip('_') + '.log'
                local_path = os.path.join(node_dir, safe_name)
                try:
                    _, stdout, stderr = client.exec_command(log_path, timeout=60)
                    content = stdout.read().decode('utf-8', errors='replace')
                    err_content = stderr.read().decode('utf-8', errors='replace')
                    with open(local_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                        if err_content:
                            f.write(f"\n--- stderr ---\n{err_content}")
                    file_results.append({
                        "path": log_path,
                        "status": "success",
                        "local": local_path,
                        "size_kb": round(os.path.getsize(local_path) / 1024, 1)
                    })
                except Exception as e:
                    file_results.append({"path": log_path, "status": "error", "error": str(e)})

        sftp.close()
        return {
            "success": True,
            "node": node_name,
            "host": host,
            "target_dir": node_dir,
            "files": file_results
        }

    except Exception as e:
        return {
            "success": False,
            "node": node_name,
            "host": host,
            "error": str(e),
            "files": file_results
        }
    finally:
        if client:
            client.close()
