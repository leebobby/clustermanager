Cluster Manager - Windows 桌面 App
============================================

[使用方式]
  1. 双击 cluster-manager.exe (或 start.bat) 启动 - 仅本机访问
  2. 自动弹出原生应用窗口, 标题 "Cluster Manager"
  3. 关闭窗口即停止服务

[局域网共享模式]
  双击 start-shared.bat 启动 (而非 start.bat)。后端绑定 0.0.0.0,
  局域网其他机器可在浏览器访问 http://<本机IP>:8000。
  窗口标题会显示可用的局域网 URL, 直接转发给同事即可。
  - 本机仍然弹出桌面窗口
  - 不分享时使用普通的 start.bat 即可
  - 也可手动设环境变量: set CLUSTER_MANAGER_BIND=0.0.0.0

[环境要求]
  - Windows 10 / 11 x64
  - Microsoft Edge WebView2 Runtime (Win11 默认已装; Win10 若缺失,
    程序首次启动会提示安装, 也可从微软官网下载:
    https://developer.microsoft.com/microsoft-edge/webview2/)

[目录结构]
  cluster-manager.exe        主程序 (FastAPI + pywebview 桌面壳)
  _internal\                 PyInstaller 运行时库 (勿删)
  static\                    前端静态资源
  iso\                       PXE Host 装机 ISO 存放目录 (BMC 通过 HTTP 拉取)
  pxe_data\                  nodes.json 等运行时数据 (首次启动自动生成)
  cluster_manager.db         SQLite 数据库 (首次启动自动生成)
  scripts_bundle.json        诊断脚本发布包 (可选, 新环境首次启动自动加载)
  ssh_credentials.json       已保存的 SSH 凭据 (首次成功执行后自动生成, 含明文密码)
  cluster_manager.log        运行日志 (无控制台窗口下排错的唯一入口)
  start.bat                  本机访问启动器 (推荐)
  start-shared.bat           局域网共享启动器 (绑定 0.0.0.0)

[网络要求]
  本 Windows 主机必须同时可达:
    - 集群节点的 BMC (管理面 GE, 通常 172.16.0.0/24)
    - 集群节点的控制面 (10GE, 通常 172.16.3.0/24)
  可在两块网卡上分别配置, 或一块网卡配置两个 IP 段。

[初次部署流程]
  1. 在 iso\ 放置 PXE Host 装机 ISO (如 openeuler-pxe-host.iso)
  2. 启动 cluster-manager, 在 "PXE 部署 - 分批部署" 页配置 PXE Host BMC
  3. 点击 "开始首次装机" (Redfish 虚拟介质)
  4. PXE Host 装机完成后, 执行第一/二/三批节点部署

[更新部署]
  保留 cluster_manager.db / pxe_data\ / iso\ / scripts_bundle.json / ssh_credentials.json
  覆盖 cluster-manager.exe / _internal\ / static\ 即可。

[端口冲突]
  默认监听 127.0.0.1:8000, 端口被占用时会自动尝试 8001..8049。
  如需手动指定: set CLUSTER_MANAGER_PORT=9000 再启动。

[排错]
  无控制台窗口模式下日志写入 cluster_manager.log,
  应用窗口里也提供 F12 (开发者工具, 需 WebView2 调试模式) 查看前端错误。
