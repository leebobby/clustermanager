# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置 - Cluster Manager
#
# 两种模式, 由环境变量 CLUSTER_MANAGER_BUILD_MODE 选择(默认 desktop):
#
#   desktop : 入口 desktop.py —— 后台起 uvicorn, 前台用 pywebview 开原生窗口。
#             双击 cluster-manager.exe 不弹浏览器, 而是一个原生应用窗口。
#             典型部署: Windows x64 管理站, 远程操作 ARM 集群节点
#             (SSH 控制面 / Redfish BMC / IPMI / PXE Host 的 DHCP-TFTP-HTTP)。
#   server  : 入口 main.py —— 纯 uvicorn 控制台进程, 浏览器访问。
#             给无图形环境的 Linux 服务器用; 不打包 pywebview。
#
# 不要直接调 pyinstaller, 用仓库根目录的构建脚本(它会设好模式并补齐
# static/ 等运行时资源):
#   python build_app.py --mode desktop
#   python build_app.py --mode server
#
# 产物: backend/dist/cluster-manager/

import os
from PyInstaller.utils.hooks import collect_all

# 注: PyInstaller 6.x 已移除字节码加密(cipher)特性, 故不再传 cipher 参数。

MODE = (os.environ.get('CLUSTER_MANAGER_BUILD_MODE') or 'desktop').strip().lower()
if MODE not in ('desktop', 'server'):
    raise SystemExit(f'CLUSTER_MANAGER_BUILD_MODE 只能是 desktop / server, 收到: {MODE!r}')
DESKTOP = MODE == 'desktop'
print(f'[spec] build mode = {MODE}')

# pywebview 在 Windows 用 Edge WebView2, 依赖 clr_loader / proxy_tools 等动态库
# 用 collect_all 收集完整, 避免漏掉 native dll。server 模式不需要窗口, 整块跳过。
if DESKTOP:
    webview_datas, webview_binaries, webview_imports = collect_all('webview')
else:
    webview_datas, webview_binaries, webview_imports = [], [], []

# pywebview 把多平台 (Android/iOS/Qt/GTK) 的资源都装进 webview/lib/
# Windows 只用 Edge WebView2 后端, 其余平台资源剔除:
#   - pywebview-android.jar  : Android 后端, 容易被杀软锁文件导致打包失败
#   - .pyc-android / qrcode  : Android 调试辅助
_WEBVIEW_PLATFORM_EXCLUDES = (
    'pywebview-android',
    'pywebview-ios',
    'qrcode.png',
)
def _keep_webview(item):
    src = item[0].lower().replace('\\', '/')
    return not any(p in src for p in _WEBVIEW_PLATFORM_EXCLUDES)
webview_datas    = [d for d in webview_datas    if _keep_webview(d)]
webview_binaries = [b for b in webview_binaries if _keep_webview(b)]

a = Analysis(
    ['desktop.py' if DESKTOP else 'main.py'],   # desktop: pywebview 壳; server: 纯 uvicorn
    pathex=['.'],
    binaries=webview_binaries,
    datas=webview_datas,
    # 注意: static/ 不放进 PyInstaller bundle, 由 build.bat 在打包后手动复制到
    # dist/cluster-manager/ 目录. 这样 config.py 的 BASE_DIR = dirname(sys.executable)
    # 可以直接找到 static/ / iso/ / pxe_data/ / scripts_bundle.json 等运行时目录.
    hiddenimports=webview_imports + [
        # uvicorn 协议/循环实现
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.off',
        'uvicorn.lifespan.on',
        # SQLAlchemy SQLite 方言
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.sqlite.pysqlite',
        'sqlalchemy.sql.default_comparator',
        # Pydantic v2
        'pydantic.deprecated.class_validators',
        'pydantic.deprecated.config',
        'pydantic.deprecated.tools',
        # aiohttp / httpx (Redfish HTTPS / 异步 HTTP)
        'aiohttp',
        'aiohttp.client',
        'httpx',
        'httpx._config',
        'httpx._transports',
        'httpx._transports.default',
        'h11',
        'httpcore',
        # paramiko (SSH 远程执行: 诊断脚本 / 自定义脚本 / 日志收集)
        'paramiko',
        'paramiko.transport',
        # FastAPI 应用模块 (确保被冻结)
        'main',
        # 标准库
        'email.mime.multipart',
        'email.mime.text',
        '_sqlite3',
    ] + ([
        # pywebview Windows 后端 (Edge WebView2) — 仅 desktop 模式
        'webview',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'clr_loader',
        'proxy_tools',
    ] if DESKTOP else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'PIL',
        'test',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cluster-manager',           # Windows 生成 cluster-manager.exe
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                        # 关 UPX, 避免 AV 误报
    # desktop: 无控制台窗口, 纯 App 体验(日志写进 cluster_manager.log)
    # server : 保留控制台, uvicorn 日志直接打在终端 / journald
    console=not DESKTOP,
    disable_windowed_traceback=False,
    target_arch=None,                 # 跟随构建主机 (Windows x64)
    codesign_identity=None,
    entitlements_file=None,
    # icon='app.ico',                 # 如需自定义图标取消注释并提供 app.ico
)

# onedir 模式: dist/cluster-manager/
#   ├── cluster-manager(.exe)
#   ├── _internal/                    Python 运行时 + 全部依赖库
#   └── (build_app.py 后续复制 static/ / pxe_data_example/ / scripts_bundle.json / iso/)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='cluster-manager',
)
