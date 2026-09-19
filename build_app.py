#!/usr/bin/env python3
"""
Cluster Manager — 一键自动构建脚本(跨平台)

把「前端源码 + 后端源码」构建成一个不依赖 Python / Node 的独立 App:

    python build_app.py                  # 自动选模式: Windows→desktop, 其他→server
    python build_app.py --mode desktop   # 桌面 App(pywebview 原生窗口, 无控制台)
    python build_app.py --mode server    # 服务端(uvicorn 控制台进程, 浏览器访问)

常用开关:
    --skip-frontend      跳过 npm 构建(复用 backend/static 里已有的产物)
    --skip-deps          跳过 pip 安装(依赖已就绪时加速)
    --no-archive         只产出可运行目录, 不打压缩包
    --no-smoke           跳过产物自检(server 模式默认会拉起来打一次 API)
    --include-pxe-data   把本机真实 pxe_data/ 打进包(默认只带 pxe_data_example/)
    --output DIR         压缩包输出目录(默认仓库根目录)

产物:
    backend/dist/cluster-manager/                 可直接运行的目录
    cluster-manager-<os>-<arch>[-server].zip|.tar.gz

说明:
  - 本脚本是构建流程的唯一实现, build.bat / build.sh 只是转发到这里的薄封装。
  - PyInstaller 配置在 backend/cluster_manager.spec, 通过环境变量
    CLUSTER_MANAGER_BUILD_MODE 区分 desktop / server 两种入口。
  - --include-pxe-data 慎用: pxe_data/ 里的 pxe_host.json 含 BMC 明文口令,
    打进分发包等于把凭据发出去。默认只带 pxe_data_example/ 模板。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
BACKEND_DIR = ROOT / "backend"
STATIC_DIR = BACKEND_DIR / "static"
BUILD_DIR = BACKEND_DIR / "build"
DIST_ROOT = BACKEND_DIR / "dist"
DIST_DIR = DIST_ROOT / "cluster-manager"
TEMPLATES_DIR = ROOT / "build_templates"
# 放 WebView2 固定版运行时的地方(体积大, 不入库): 存在就自动打进包
BUILD_RESOURCES_WEBVIEW2 = ROOT / "build_resources" / "webview2"

IS_WINDOWS = os.name == "nt"
STEP_TOTAL = 6


# ── 输出 ──────────────────────────────────────────────────────────────────────

def _force_utf8_output() -> None:
    """
    Windows 上 stdout 被重定向(CI / 管道 / `> build.log`)时, Python 用的是系统
    ANSI 代码页 —— 英文 Windows 是 cp1252, 编不了中文, 第一行 print 就
    UnicodeEncodeError 崩掉。统一改成 UTF-8, 实在编不出的字符退化成转义。

    直接连控制台时 Python 走 WriteConsoleW, 本来就不受代码页影响, 这里改了也无害。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass


_force_utf8_output()


def step(n: int, msg: str) -> None:
    print(f"\n[{n}/{STEP_TOTAL}] {msg}", flush=True)


def info(msg: str) -> None:
    print(f"  -> {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"  [警告] {msg}", flush=True)


def die(msg: str) -> NoReturn:
    print(f"\n[错误] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ── 命令执行 ──────────────────────────────────────────────────────────────────

def run(cmd: list, cwd: Path, what: str, env: dict | None = None) -> None:
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable}", flush=True)
    merged = {**os.environ, **(env or {})}
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=merged)
    if result.returncode != 0:
        die(f"{what} 失败 (exit {result.returncode}): {printable}")


def which(name: str) -> str | None:
    """Windows 下 npm 实际是 npm.cmd, shutil.which 已能处理 PATHEXT"""
    return shutil.which(name)


def require(name: str, hint: str) -> str:
    found = which(name)
    if not found:
        die(f"未找到 {name}。{hint}")
    return found


def rmtree_retry(path: Path, attempts: int = 4, wait: float = 3.0) -> None:
    """
    删除目录, 失败后重试。

    Windows 上杀软扫描刚写出的 dll / jar 时会持有文件句柄, 第一次 rmtree 常报
    PermissionError; 等几秒再删通常就成功了。
    """
    for i in range(1, attempts + 1):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            if i == attempts:
                die(f"无法删除 {path}: {exc}\n       请关闭正在运行的 cluster-manager, 或暂停杀软后重试。")
            warn(f"删除 {path.name} 失败({exc.__class__.__name__}), {wait:.0f}s 后重试 ({i}/{attempts - 1})")
            time.sleep(wait)


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)


# ── 各构建步骤 ────────────────────────────────────────────────────────────────

def preflight(args) -> None:
    step(1, "环境检查")
    if not (BACKEND_DIR / "main.py").is_file():
        die(f"未找到 {BACKEND_DIR / 'main.py'}, 请在仓库根目录运行本脚本")
    if not (FRONTEND_DIR / "package.json").is_file():
        die(f"未找到 {FRONTEND_DIR / 'package.json'}")

    info(f"python   : {sys.version.split()[0]}  ({sys.executable})")
    info(f"platform : {platform.system()} {platform.machine()}")
    info(f"mode     : {args.mode}")

    if not args.skip_frontend:
        require("node", "请安装 Node.js 18+ : https://nodejs.org")
        npm = require("npm", "npm 随 Node.js 一起安装, 请检查 PATH")
        node_v = subprocess.run([which("node"), "-v"], capture_output=True, text=True)
        info(f"node     : {node_v.stdout.strip()}  (npm: {npm})")
    else:
        if not (STATIC_DIR / "index.html").is_file():
            die("--skip-frontend 需要 backend/static/index.html 已存在, "
                "请先跑一次完整构建或去掉该开关")
        info("跳过前端构建, 复用 backend/static/ 现有产物")

    if args.mode == "desktop" and not IS_WINDOWS:
        warn("desktop 模式产物依赖 pywebview 的图形后端(Linux 需 GTK/WebKit2 或 Qt), "
             "无图形环境的服务器请用 --mode server")


def build_frontend(args) -> None:
    step(2, "构建前端 (vite → backend/static/)")
    if args.skip_frontend:
        info("已跳过")
        return
    npm = which("npm")
    if not (FRONTEND_DIR / "node_modules").is_dir():
        run([npm, "install"], FRONTEND_DIR, "npm install")
    else:
        info("node_modules 已存在, 跳过 npm install(需要刷新依赖时手动删除该目录)")
    run([npm, "run", "build"], FRONTEND_DIR, "npm run build")
    if not (STATIC_DIR / "index.html").is_file():
        die("前端构建未产出 backend/static/index.html, 请检查 vite.config.js 的 build.outDir")
    info(f"前端产物: {STATIC_DIR}")


def install_deps(args) -> None:
    step(3, "安装构建依赖 (仅构建机需要)")
    if args.skip_deps:
        info("已跳过")
        return
    pip = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q"]
    run(pip + ["-r", str(BACKEND_DIR / "requirements.txt")], BACKEND_DIR, "pip install requirements.txt")
    run(pip + ["pyinstaller"], BACKEND_DIR, "pip install pyinstaller")
    info("依赖就绪")


def run_pyinstaller(args) -> None:
    step(4, "PyInstaller 打包")
    # spec 在 desktop 模式下要 collect_all('webview') 收集原生依赖, 装不上就先说清楚,
    # 否则错误会以一串 PyInstaller 回溯的形式冒出来, 看不出是缺依赖
    if args.mode == "desktop":
        probe = subprocess.run([sys.executable, "-c", "import webview"], capture_output=True)
        if probe.returncode != 0:
            die("desktop 模式需要 pywebview, 当前 Python 里没装:\n"
                f"       {sys.executable} -m pip install pywebview\n"
                "       (或去掉 --skip-deps 让脚本自动装; 无图形环境请改用 --mode server)")
    rmtree_retry(BUILD_DIR)
    rmtree_retry(DIST_DIR)
    run(
        [sys.executable, "-m", "PyInstaller", "cluster_manager.spec", "--clean", "--noconfirm"],
        BACKEND_DIR,
        "PyInstaller",
        env={"CLUSTER_MANAGER_BUILD_MODE": args.mode},
    )
    exe = DIST_DIR / ("cluster-manager.exe" if IS_WINDOWS else "cluster-manager")
    if not exe.is_file():
        die(f"PyInstaller 未产出 {exe}")
    info(f"可执行文件: {exe}")


# start.sh / install-service.sh —— Linux server 模式下发的启动脚本
_START_SH = """#!/bin/bash
# Cluster Manager 启动脚本(生产机直接运行, 无需安装 Python / Node)
cd "$(dirname "${BASH_SOURCE[0]}")"

PORT="${CLUSTER_MANAGER_PORT:-8000}"
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$LOCAL_IP" ] || LOCAL_IP=localhost

echo "================================================"
echo " Cluster Manager 启动中..."
echo " 前端界面: http://$LOCAL_IP:$PORT"
echo " API 文档: http://$LOCAL_IP:$PORT/docs"
echo " 停止服务: Ctrl+C"
echo "================================================"

exec ./cluster-manager
"""

_INSTALL_SERVICE_SH = """#!/bin/bash
# 注册为 systemd 服务(开机自启)
# 用法: sudo ./install-service.sh [安装目录, 默认 /opt/cluster-manager]
set -e

INSTALL_DIR="${1:-/opt/cluster-manager}"
SERVICE_FILE="/etc/systemd/system/cluster-manager.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "安装到: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/cluster-manager" "$INSTALL_DIR/start.sh"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Cluster Manager Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/cluster-manager
Environment=CLUSTER_MANAGER_HOST=0.0.0.0
Environment=CLUSTER_MANAGER_PORT=8000
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cluster-manager

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cluster-manager
systemctl restart cluster-manager

LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$LOCAL_IP" ] || LOCAL_IP=your-server-ip
echo ""
echo "================================================"
echo " 服务已注册并启动"
echo " 前端界面: http://$LOCAL_IP:8000"
echo " 查看日志: journalctl -u cluster-manager -f"
echo " 停止服务: systemctl stop cluster-manager"
echo "================================================"
"""


# ── WebView2 运行时(离线 Win10 的关键)────────────────────────────────────────

def _find_runtime_root(path: Path) -> Path | None:
    """在 path 下找 msedgewebview2.exe 所在目录(固定版运行时解压出来会多一层版本号目录)"""
    if (path / "msedgewebview2.exe").is_file():
        return path
    for depth in ("*", "*/*"):
        for exe in path.glob(f"{depth}/msedgewebview2.exe"):
            return exe.parent
    return None


def _extract_cab(cab: Path, dest: Path) -> Path | None:
    """解 WebView2 固定版的 .cab。Windows 用系统自带 expand, Linux 用 cabextract"""
    dest.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        cmd = ["expand", str(cab), "-F:*", str(dest)]
    elif which("cabextract"):
        cmd = ["cabextract", "-q", "-d", str(dest), str(cab)]
    else:
        die(f"需要解压 {cab.name}, 但没找到 cabextract。\n"
            "       请先手动解压, 再用 --webview2 指向解压出来的目录。")
    run(cmd, ROOT, f"解压 {cab.name}")
    return _find_runtime_root(dest)


def stage_webview2(args) -> None:
    """
    把 WebView2 运行时放进包里。

    离线 Win10 上没有 WebView2 运行时, pywebview 会静默退回 IE11 内核, Vue 3
    渲染成一片空白。带上固定版运行时就彻底绕开这件事: 免安装、免管理员、免联网,
    desktop.py 启动时认 exe 同级的 webview2\\ 目录。
    """
    source = Path(args.webview2).expanduser() if args.webview2 else None
    if source is None and BUILD_RESOURCES_WEBVIEW2.exists():
        source = BUILD_RESOURCES_WEBVIEW2
        info(f"自动采用 {BUILD_RESOURCES_WEBVIEW2.relative_to(ROOT)}/ 里的 WebView2 运行时")
    if source is None:
        return
    if not source.exists():
        die(f"--webview2 指向的路径不存在: {source}")

    if args.mode != "desktop":
        warn(f"server 模式不需要 WebView2, 已忽略 {source}")
        return

    target = DIST_DIR / "webview2"

    # 1) 离线安装包(.exe): 放进包里让现场自己装, 仍然需要管理员权限
    if source.is_file() and source.suffix.lower() == ".exe":
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target / source.name)
        info(f"webview2/{source.name} (离线安装包, 现场需管理员运行一次)")
        warn("这是安装包而不是固定版运行时: 程序不会自动用它, 需要在目标机手动安装。"
             "想免安装请改用固定版运行时(解压出 msedgewebview2.exe 的那个目录)")
        return

    # 2) 固定版运行时: 目录, 或者还没解压的 .cab
    runtime_root: Path | None
    if source.is_file() and source.suffix.lower() == ".cab":
        runtime_root = _extract_cab(source, BUILD_DIR / "webview2-cab")
    else:
        runtime_root = _find_runtime_root(source)

    if runtime_root is None:
        die(f"在 {source} 里找不到 msedgewebview2.exe。\n"
            "       --webview2 需要的是 WebView2『固定版运行时』(Fixed Version) 解压后的目录,\n"
            "       或未解压的 .cab, 或离线安装包 .exe。")

    copy_tree(runtime_root, target)
    size_mb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1048576
    info(f"webview2/ 固定版运行时 ({size_mb:.0f} MB, 免安装免管理员) <- {runtime_root.name}")


def stage_resources(args) -> None:
    """
    把运行时资源放进 dist/。

    static/ 故意不进 PyInstaller bundle —— config.py 的 BASE_DIR 是
    dirname(sys.executable), 放在 exe 旁边现场才能直接换前端文件。
    """
    step(5, "补齐运行时资源")

    copy_tree(STATIC_DIR, DIST_DIR / "static")
    info("static/")

    bundle = BACKEND_DIR / "scripts_bundle.json"
    if bundle.is_file():
        shutil.copy2(bundle, DIST_DIR / bundle.name)
        info("scripts_bundle.json")

    example = BACKEND_DIR / "pxe_data_example"
    if example.is_dir():
        copy_tree(example, DIST_DIR / "pxe_data_example")
        info("pxe_data_example/ (含 BMC 凭据的模板, 现场复制成 pxe_data/ 再填)")

    if args.include_pxe_data:
        real = BACKEND_DIR / "pxe_data"
        if real.is_dir():
            copy_tree(real, DIST_DIR / "pxe_data")
            warn("已按 --include-pxe-data 打入真实 pxe_data/, 内含 BMC 明文口令, 注意分发范围")
        else:
            warn("--include-pxe-data 指定了, 但 backend/pxe_data/ 不存在")

    for sub in ("iso", "firmware"):
        (DIST_DIR / sub).mkdir(exist_ok=True)
    info("iso/ firmware/ (空目录占位)")

    stage_webview2(args)

    if IS_WINDOWS:
        for name in ("start.bat", "start-shared.bat", "README.txt", "check-webview2.bat"):
            src = TEMPLATES_DIR / name
            if src.is_file():
                shutil.copy2(src, DIST_DIR / name)
                info(name)
            else:
                warn(f"缺少 build_templates/{name}, 已跳过")
    else:
        for name, body in (("start.sh", _START_SH), ("install-service.sh", _INSTALL_SERVICE_SH)):
            target = DIST_DIR / name
            target.write_text(body, encoding="utf-8")
            target.chmod(0o755)
            info(name)


# ── 产物自检 ──────────────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def smoke_test(args) -> None:
    """
    拉起打好的产物, 打一次 API 确认它真的能跑。

    只对 server 模式做: desktop 模式要开原生窗口, 构建机上未必有图形环境。
    """
    if args.no_smoke:
        info("按 --no-smoke 跳过自检")
        return
    if args.mode != "server":
        info("desktop 模式跳过自检(需要图形环境), 请在目标机双击验证")
        return

    exe = DIST_DIR / ("cluster-manager.exe" if IS_WINDOWS else "cluster-manager")
    port = _free_port()
    url = f"http://127.0.0.1:{port}/api/nodes"
    info(f"自检: 启动产物并请求 {url}")

    env = {**os.environ, "CLUSTER_MANAGER_HOST": "127.0.0.1", "CLUSTER_MANAGER_PORT": str(port)}
    # 输出重定向到临时文件而不是 PIPE: 全程不读的 PIPE 写满 64KB 后会把被测进程卡死
    log_path = DIST_DIR / "_smoke.log"
    ok = False
    with open(log_path, "w+", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen([str(exe)], cwd=str(DIST_DIR), env=env,
                                stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        try:
            while time.time() < deadline:
                if proc.poll() is not None:
                    log.flush()
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                    die(f"产物启动即退出 (exit {proc.returncode}), 输出末尾:\n{tail}")
                try:
                    with urllib.request.urlopen(url, timeout=2) as resp:
                        if resp.status == 200:
                            json.loads(resp.read().decode("utf-8"))
                            ok = True
                            break
                except (urllib.error.URLError, OSError, ValueError):
                    time.sleep(0.5)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    if not ok:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        die(f"自检失败: 60s 内没能从产物拿到 /api/nodes 的正常响应, 输出末尾:\n{tail}")
    log_path.unlink(missing_ok=True)
    info("自检通过 (/api/nodes 返回 200)")


def clean_runtime_leftovers(args) -> None:
    """自检会生成数据库 / 默认配置, 打包前清掉, 保证分发包是干净的初始状态"""
    for name in ("cluster_manager.db", "cluster_manager.db-journal",
                 "cluster_manager.log", "node_templates.json", "ssh_credentials.json",
                 "_smoke.log"):
        target = DIST_DIR / name
        if target.exists():
            target.unlink()
    generated_pxe = DIST_DIR / "pxe_data"
    # 自检生成的 pxe_data/ 只是默认模板; --include-pxe-data 打进来的要保留
    if generated_pxe.is_dir() and not args.include_pxe_data:
        shutil.rmtree(generated_pxe)


def write_build_info(args) -> dict:
    """写一份构建信息进包里 —— 现场反馈问题时能对上是哪个版本"""
    def git(*a: str) -> str:
        try:
            out = subprocess.run(["git", *a], cwd=str(ROOT), capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else ""
        except Exception:
            return ""

    meta = {
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": args.mode,
        "os": platform.system(),
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "git_commit": git("rev-parse", "--short", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
    }
    (DIST_DIR / "build-info.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def make_archive(args) -> Path | None:
    step(6, "打包发布包")
    write_build_info(args)
    if args.no_archive:
        info("按 --no-archive 跳过, 可运行目录已就绪")
        return None

    out_dir = Path(args.output).resolve() if args.output else ROOT
    out_dir.mkdir(parents=True, exist_ok=True)
    os_tag = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system(), platform.system().lower())
    suffix = "" if args.mode == "desktop" else f"-{args.mode}"
    stem = f"cluster-manager-{os_tag}-{platform.machine().lower()}{suffix}"

    if IS_WINDOWS:
        pkg = out_dir / f"{stem}.zip"
        if pkg.exists():
            pkg.unlink()
        with zipfile.ZipFile(pkg, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(DIST_DIR.rglob("*")):
                zf.write(path, Path("cluster-manager") / path.relative_to(DIST_DIR))
    else:
        pkg = out_dir / f"{stem}.tar.gz"
        if pkg.exists():
            pkg.unlink()
        with tarfile.open(pkg, "w:gz") as tf:
            tf.add(DIST_DIR, arcname="cluster-manager")

    info(f"{pkg.name}  ({pkg.stat().st_size / 1048576:.1f} MB)")
    return pkg


# ── 入口 ──────────────────────────────────────────────────────────────────────

def parse_args(argv: list) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="build_app.py",
        description="Cluster Manager 一键构建: 前端 + 后端 → 独立 App",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--mode", choices=("auto", "desktop", "server"), default="auto",
                   help="desktop=pywebview 原生窗口; server=uvicorn 控制台; auto=Windows 选 desktop, 其他选 server")
    p.add_argument("--skip-frontend", action="store_true", help="跳过 npm 构建, 复用 backend/static/")
    p.add_argument("--skip-deps", action="store_true", help="跳过 pip 安装")
    p.add_argument("--no-archive", action="store_true", help="不打压缩包")
    p.add_argument("--no-smoke", action="store_true", help="跳过产物自检")
    p.add_argument("--webview2", metavar="PATH",
                   help="把 WebView2 运行时打进包(仅 desktop 模式)。可以是固定版运行时"
                        "解压后的目录、未解压的 .cab, 或离线安装包 .exe。"
                        "放固定版运行时时目标机免安装、免管理员、免联网 —— 离线 Win10 需要这个。"
                        f"也可以直接把文件放到 {BUILD_RESOURCES_WEBVIEW2.relative_to(ROOT)}/ 由脚本自动采用")
    p.add_argument("--include-pxe-data", action="store_true",
                   help="把本机真实 pxe_data/ 打进包(含 BMC 明文口令, 默认不带)")
    p.add_argument("--output", metavar="DIR", help="压缩包输出目录, 默认仓库根目录")
    args = p.parse_args(argv)
    if args.mode == "auto":
        args.mode = "desktop" if IS_WINDOWS else "server"
    return args


def main(argv: list) -> int:
    args = parse_args(argv)
    started = time.time()

    print("=" * 60)
    print(" Cluster Manager 构建")
    print("=" * 60)

    preflight(args)
    build_frontend(args)
    install_deps(args)
    run_pyinstaller(args)
    stage_resources(args)
    smoke_test(args)
    clean_runtime_leftovers(args)
    pkg = make_archive(args)

    print("\n" + "=" * 60)
    print(f" 构建成功  ({time.time() - started:.0f}s)")
    print("=" * 60)
    print(f"\n 可运行目录: {DIST_DIR}")
    if pkg:
        print(f" 发布包    : {pkg}")
    print("\n 部署方式:")
    if args.mode == "desktop":
        print("   1. 解压到目标 Windows 机器")
        print("   2. (可选) 把 PXE Host ISO 放进 iso/")
        print("   3. 双击 cluster-manager.exe 或 start.bat, 弹出原生窗口")
        print("   注: Win10 需装 Edge WebView2 Runtime (https://aka.ms/webview2)")
    else:
        print("   1. 传到目标机并解压")
        print("   2. ./cluster-manager/start.sh            前台运行")
        print("   3. sudo ./cluster-manager/install-service.sh   注册开机自启")
        print("   4. 浏览器访问 http://<目标机IP>:8000")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
