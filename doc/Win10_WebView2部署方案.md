# Windows 10 WebView2 部署方案

## 1. 问题说明

Cluster Manager 桌面版使用 Edge WebView2 渲染 Vue 3 前端。Windows 11 通常已经具备
WebView2 Runtime，但部分 Windows 10 机器未安装。程序检测不到可用的 WebView2 时，
会改用 Edge/Chrome 的应用窗口模式，以避免退回 IE11 内核后出现白屏。

如果希望 Windows 10 上仍使用内置桌面窗口，可以选择以下任一方案：

1. 在发布包中携带 WebView2 固定版运行时；
2. 在目标机安装 WebView2 Evergreen 离线运行时。

> 建议：批量交付到离线或环境不可控的现场机器时采用方案一；能够统一维护目标机
> 系统环境、并且希望减小发布包体积时采用方案二。

### 1.1 先看这个常见错误

如果构建输出如下：

```text
[错误] --webview2 指向的路径不存在: D:\webview2-fixed
```

说明构建命令中的 `D:\webview2-fixed` 只是示例路径，而你的电脑上不存在这个目录。
这不是 PyInstaller 构建失败，也不是 Cluster Manager 本身运行失败；从输出中的
`Build complete!` 可以看出可执行程序已经生成，错误发生在随后补齐 WebView2 资源的阶段。

- 采用**方案一**：把示例路径替换为你实际下载或解压出来的 WebView2 路径；
- 采用**方案二**：构建命令中不要添加 `--webview2`，在目标 Win10 上另行安装运行时。

---

## 2. 方案一：发布包携带 WebView2 固定版运行时

### 2.1 适用场景

- 目标 Windows 10 不能联网；
- 现场用户没有管理员权限；
- 希望所有目标机使用相同版本的 WebView2；
- 可以接受发布包体积增大。

### 2.2 准备运行时

从 Microsoft 官方渠道下载与构建架构匹配的 **WebView2 Fixed Version Runtime**，并解压。
解压后的有效运行时目录中必须直接包含：

```text
msedgewebview2.exe
```

例如：

```text
D:\build-resources\Microsoft.WebView2.FixedVersionRuntime.130.0.2849.68.x64\
├── msedgewebview2.exe
├── msedge.dll
└── ...
```

运行时架构应与生成的 Cluster Manager 可执行程序架构一致，通常使用 x64 版本。

### 2.3 构建发布包

先在 PowerShell 中确认实际目录存在，并且其中能找到 `msedgewebview2.exe`：

```powershell
$WebView2Path = "D:\实际存放位置\Microsoft.WebView2.FixedVersionRuntime.130.0.2849.68.x64"
Test-Path $WebView2Path
Get-ChildItem $WebView2Path -Filter msedgewebview2.exe -Recurse
```

第一条检查必须返回 `True`，第二条检查必须列出 `msedgewebview2.exe`。然后在仓库根目录
使用这个真实路径构建：

```powershell
python build_app.py --mode desktop --webview2 $WebView2Path
```

> `D:\实际存放位置\...` 仍是格式示例，必须换成本机真实路径。不要直接照抄
> `D:\webview2-fixed`，除非你确实创建了该目录并把固定版运行时解压到了里面。

`--webview2` 也可以直接指向下载好的固定版 `.cab` 文件：

```powershell
python build_app.py --mode desktop --webview2 "D:\Downloads\Microsoft.WebView2.FixedVersionRuntime.x64.cab"
```

也可以把解压后的运行时预先放在：

```text
build_resources/webview2/
```

然后执行：

```powershell
python build_app.py --mode desktop
```

构建脚本会把运行时复制到发布目录的 `webview2\` 中。最终应确认目录结构类似：

```text
ClusterManager/
├── cluster-manager.exe
├── webview2/
│   ├── msedgewebview2.exe
│   └── ...
└── ...
```

不要只把 WebView2 安装程序放进 `webview2\`；程序需要的是**已经解压的固定版运行时**。

### 2.4 目标机验证

将完整发布目录复制到 Windows 10 目标机，先运行诊断：

```powershell
.\cluster-manager.exe --check
```

预期报告包含：

```text
判定        : bundled
结论: 可以使用内置原生窗口。
```

然后正常双击 `cluster-manager.exe`，确认：

- 打开的是 Cluster Manager 内置窗口；
- 不再出现“未检测到 Edge WebView2 运行时”的提示；
- 页面可以正常加载和操作；
- 关闭窗口后进程正常退出。

### 2.5 优缺点

**优点**

- 完全离线；
- 不需要管理员权限；
- 不需要修改目标机；
- 运行时版本固定，便于复现和统一验证。

**缺点**

- 发布包体积明显增大；
- WebView2 安全更新需要重新替换固定版运行时并重新发布。

---

## 3. 方案二：目标机安装 WebView2 Evergreen 离线运行时

### 3.1 适用场景

- 可以统一维护 Windows 10 系统环境；
- 现场具备管理员权限；
- 希望减小 Cluster Manager 发布包体积；
- 可以通过离线介质分发 WebView2 安装包。

### 3.2 准备安装包

从 Microsoft 官方渠道下载 **Microsoft Edge WebView2 Evergreen Standalone Installer**。
必须选择与目标系统匹配的架构，常见的 64 位 Windows 10 使用 x64 安装包。

将安装包通过 U 盘、内网共享或其他离线介质复制到目标机；安装过程本身不要求目标机联网。

### 3.3 安装

方案二构建 Cluster Manager 时**不使用** `--webview2`：

```powershell
python build_app.py --mode desktop
```

构建完成后，将 Cluster Manager 发布包和 WebView2 Evergreen 离线安装包一起复制到
目标 Windows 10，但二者不需要放在同一个目录中。

使用管理员账户运行安装程序。也可以在管理员 PowerShell 或命令提示符中执行静默安装：

```powershell
.\MicrosoftEdgeWebView2RuntimeInstallerX64.exe /silent /install
```

安装完成后，关闭旧的 Cluster Manager 进程，再重新启动程序。通常不需要重启 Windows；
如果程序仍检测不到运行时，可先重启系统再验证。

### 3.4 目标机验证

在 Cluster Manager 发布目录执行：

```powershell
.\cluster-manager.exe --check
```

预期报告包含已安装的系统运行时版本，并显示：

```text
判定        : system
结论: 可以使用内置原生窗口。
```

如果报告提示 `.NET Framework` 版本过低，还需要把目标机升级到至少
**.NET Framework 4.6.2**，然后重新运行诊断。

最后正常启动 `cluster-manager.exe`，确认不再进入浏览器应用窗口模式。

### 3.5 优缺点

**优点**

- Cluster Manager 发布包较小；
- 系统中其他使用 WebView2 的应用可以共用运行时；
- Evergreen Runtime 可以通过系统维护机制升级。

**缺点**

- 安装需要管理员权限；
- 每台目标机都需要单独安装或通过运维工具统一下发；
- 不同机器上的运行时版本可能不一致。

---

## 4. 两种方案对比

| 对比项 | 方案一：随包固定版 | 方案二：目标机安装 Evergreen |
|---|---|---|
| 目标机联网 | 不需要 | 不需要，可使用离线安装包 |
| 管理员权限 | 不需要 | 需要 |
| 发布包体积 | 较大 | 较小 |
| 目标机改动 | 无 | 安装系统运行时 |
| 版本一致性 | 高，由发布包锁定 | 可能因机器而异 |
| 后续安全更新 | 重新打包发布 | 更新系统运行时 |
| 推荐场景 | 离线交付、批量现场部署 | 统一运维、可管理系统环境 |

## 5. 故障排查

### 5.1 诊断命令

无论采用哪种方案，首先运行：

```powershell
.\cluster-manager.exe --check
```

重点查看以下字段：

- `随包运行时`：是否识别到发布目录中的固定版运行时；
- `系统运行时`：是否识别到系统安装的 Evergreen Runtime；
- `.NET Release`：是否满足原生窗口要求；
- `Chromium浏览器`：WebView2 不可用时是否可以进入浏览器应用窗口模式；
- `判定`：`bundled`、`system` 或 `none`；
- `说明`：最终判定原因。

### 5.2 仍显示 `none`

依次检查：

1. 固定版目录中是否直接存在 `webview2\msedgewebview2.exe`；
2. 是否复制了完整发布目录，而不是只复制 `cluster-manager.exe`；
3. WebView2 和程序架构是否匹配；
4. Evergreen 安装是否成功，安装后是否重新启动了 Cluster Manager；
5. `.NET Framework` 是否至少为 4.6.2；
6. 杀毒软件或终端安全软件是否隔离了 WebView2 文件；
7. 查看发布目录中的 `cluster_manager.log` 获取详细启动日志。

### 5.3 构建在 `[5/6] 补齐运行时资源` 阶段报路径不存在

这表示前面的 PyInstaller 步骤可能已经生成了 EXE，但完整发布流程尚未成功结束。不要把
这个不完整的 `backend\dist\cluster-manager\` 目录直接用于正式发布。

按选择的方案处理后重新执行完整构建：

```powershell
# 方案一：换成真实存在的固定版运行时目录或 .cab 文件
python build_app.py --mode desktop --webview2 "D:\真实路径\WebView2固定版目录"

# 方案二：不向发布包放运行时，删除 --webview2 参数
python build_app.py --mode desktop
```

如果之前把不存在的路径写进了批处理文件，也需要从 `.bat` 中修改或删除对应参数。

### 5.4 临时继续使用

在问题排除前，程序会尝试用 Edge/Chrome 的应用窗口模式打开
`http://127.0.0.1:8000`。该模式与内置窗口使用相同的后端和前端功能，只是窗口外壳不同。
当前版本中，关闭该应用窗口后 Cluster Manager 后台服务会随之退出。
