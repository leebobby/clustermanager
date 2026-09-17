# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置 - Cluster Manager (Windows x64 桌面 App)
#
# 部署模式: cluster-manager 部署在 Windows 管理站上, 远程操作 ARM 集群节点
#   (通过 SSH 控制面 / Redfish BMC / IPMI / DHCP-TFTP-HTTP for PXE Host bootstrap)
#
# 入口: desktop.py - 后台启动 uvicorn, 前台用 pywebview 打开原生窗口
#   双击 cluster-manager.exe 不会出现浏览器, 而是一个原生应用窗口
#
# 构建命令: 在 backend/ 目录下执行
#   pyinstaller cluster_manager.spec --clean --noconfirm
# 产物: backend/dist/cluster-manager/cluster-manager.exe + _internal/

import os
from PyInstaller.utils.hooks import collect_all

# 注: PyInstaller 6.x 已移除字节码加密(cipher)特性, 故不再传 cipher 参数。

# pywebview 在 Windows 用 Edge WebView2, 依赖 clr_loader / proxy_tools 等动态库
# 用 collect_all 收集完整, 避免漏掉 native dll
webview_datas, webview_binaries, webview_imports = collect_all('webview')

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
    ['desktop.py'],                  # 入口改为桌面版启动器
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
        # pywebview Windows 后端 (Edge WebView2)
        'webview',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'clr_loader',
        'proxy_tools',
        # FastAPI 应用模块 (确保被冻结)
        'main',
        # 标准库
        'email.mime.multipart',
        'email.mime.text',
        '_sqlite3',
    ],
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
    console=False,                    # 无控制台窗口, 纯 App 体验 (日志写入 cluster_manager.log)
    disable_windowed_traceback=False,
    target_arch=None,                 # 跟随构建主机 (Windows x64)
    codesign_identity=None,
    entitlements_file=None,
    # icon='app.ico',                 # 如需自定义图标取消注释并提供 app.ico
)

# onedir 模式: dist/cluster-manager/
#   ├── cluster-manager.exe
#   ├── _internal/                    Python 运行时 + 全部依赖库
#   └── (build.bat 后续复制 static/ / pxe_data/ / scripts_bundle.json / iso/)
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
