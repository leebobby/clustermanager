# 集群配置、管理、诊断系统

鲲鹏 ARM64 + HNS 网卡，22 节点三平面物理隔离集群的配置、管理与诊断系统。

## 网络架构

三平面物理隔离，各平面由独立交换机承载：

| 平面 | 带宽 | 子网 | 用途 |
|------|------|------|------|
| 管理面 | GE | `172.16.0.0/24` | BMC/IPMI 带外管理 |
| 控制面 | 10GE | `172.16.3.0/24` | SSH / PXE 部署 / 心跳 |
| 数据面-DPDK1 | 100GE | `200.1.1.0/24` | Master eno2 接收 |
| 数据面-DPDK2 | 100GE | `200.1.2.0/24` | Master eno3 接收 |
| 数据面-RDMA1 | 100GE | `100.1.1.0/24` | Master/Slave/SubSwath RDMA |
| 数据面-RDMA2 | 100GE | `100.1.2.0/24` | Master/SubSwath/GStorage RDMA |

## 集群规模与角色

| 角色 | 数量 | 主机名规则 | 控制面 IP | 说明 |
|------|------|-----------|-----------|------|
| PXE Host | 1 | host-server | 172.16.3.10 | DHCP/TFTP/HTTP/API，100GE 上行至 10G 交换机 |
| Master | 6 | master-01~06 | 172.16.3.11~16 | DPDK 接收 + RDMA 计算控制，100G×4 |
| Slave | 12 | slave-01~12 | 172.16.3.51~62 | RDMA 计算 + NFS 客户端，100G×1 |
| SubSwath | 2 | subswath-01~02 | 172.16.3.170~171 | NFS Server（4×7.68T NVMe RAID10），100G×2 |
| GStorage | 1 | gstorage-01 | 172.16.3.172 | NFS Server（机械盘硬件 RAID50），100G×1 |

## 功能模块

### 1. PXE 自动化部署（v2）

- **IP 规划**：六子网固定方案，一键生成全角色 IP 表
- **nodes.json 管理**：22 节点 MAC→配置映射，支持在线编辑 MAC 地址
- **配置生成**：dhcpd.conf、grub.cfg（aarch64 UEFI）、RAID1 初始化脚本、PXE 启动脚本
- **PXE Host 首次装机引导（Bootstrap，一次性）**：Windows 管理站通过 BMC Redfish 把本地 ISO 挂为虚拟光驱，PXE Host 一次性 CD 引导完成装机；装好后稳定运行，不需要重复执行
- **分批部署**：第一批（SubSwath+GStorage）→ 第二批（Master）→ 第三批（Slave）— PXE Host 装机就绪后开始
- **node-env API**：`GET /api/pxe/node-env?mac=<MAC>` 供 firstboot detect.sh 获取差异化配置

### 2. 集群管理

- 三平面网络状态监控
- BMC/IPMI 远程管理（ipmitool / Redfish）
- 定时巡检任务
- 告警规则引擎

### 3. 故障诊断

- 三平面拓扑可视化（D3.js）
- 日志收集与分析
- 故障点定位
- 诊断脚本库（业务诊断 + 硬件诊断）

## 快速启动

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# Swagger 文档: http://localhost:8000/docs
```

启动时自动完成：数据库初始化、列迁移、种子数据写入、`pxe_data/nodes.json` 预生成。

### 前端

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

## 项目结构

```
clustermanager/
├── backend/
│   ├── api/
│   │   ├── pxe.py          # PXE 部署 API（v2）
│   │   ├── ipmi.py         # BMC/IPMI 管理
│   │   ├── nodes.py        # 节点 CRUD
│   │   ├── network.py      # 网络拓扑
│   │   ├── alerts.py       # 告警
│   │   ├── diagnose.py     # 故障诊断
│   │   └── patrol.py       # 巡检
│   ├── services/
│   │   └── pxe_service.py  # PXE 服务 v2（nodes.json / DHCP / GRUB 生成）
│   ├── models/
│   │   ├── node.py         # ORM 模型
│   │   └── seed.py         # 演示数据
│   ├── pxe_data/
│   │   └── nodes.json      # 节点配置清单（自动生成，需填入实际 MAC）
│   └── main.py             # 入口 + 迁移
└── frontend/src/
    └── views/
        └── PXEDeploy.vue   # PXE 部署页面（5 标签页）
```

## API 速查

| 接口 | 说明 |
|------|------|
| `POST /api/pxe/network-plan` | v2 六子网 IP 规划 |
| `GET  /api/pxe/nodes-json` | 获取 nodes.json |
| `POST /api/pxe/nodes-json` | 更新 nodes.json |
| `GET  /api/pxe/nodes-json/node-list` | 节点表格列表 |
| `PATCH /api/pxe/nodes-json/update-mac` | 替换节点 MAC |
| `GET  /api/pxe/node-env?mac=<MAC>` | firstboot 环境变量（纯文本） |
| `GET  /api/pxe/dhcp-config` | 生成 dhcpd.conf |
| `GET  /api/pxe/grub-config` | 生成 grub.cfg |
| `GET  /api/pxe/setup-raid1-script` | 生成 RAID1 初始化脚本 |
| `GET  /api/pxe/pxe-boot-script` | 生成 PXE 启动脚本 |
| `POST /api/pxe/wave-deploy/{1\|2\|3}` | 分批部署普通节点（前提：PXE Host 已就绪） |
| `POST /api/pxe/pxe-host/install` | PXE Host 首次装机引导（Bootstrap，Redfish 虚拟介质） |
| `GET  /api/pxe/pxe-host/status` | PXE Host 部署状态（not_configured / not_installed / installing / online / error） |
| `GET  /api/pxe/pxe-host/config` | 读取 PXE Host 装机配置 |
| `PUT  /api/pxe/pxe-host/config` | 更新 PXE Host 装机配置 |
| `GET  /api/pxe/pxe-host/iso-list` | 列出 Windows 安装目录下可用 ISO |

## 生产部署（OpenEuler ARM → Windows 浏览器访问）

> **PyInstaller 不支持跨平台编译**（无法在 Windows x86 上直接生成 Linux ARM 二进制）。  
> 提供两条路径，按场景选择：

### 方案对比

| | 部署包方案 | Docker 方案 |
|--|-----------|------------|
| 前提 | Node.js（Windows）+ Python（ARM） | Docker Desktop（Windows）+ Docker（ARM） |
| 构建位置 | 前端在 Windows，Python 在 ARM | 全部在 Windows（QEMU 模拟） |
| 产物 | ZIP 包 + Python 源码 | 容器镜像 |
| 隔离性 | venv 虚拟环境 | 容器级隔离 |
| 推荐场景 | 快速部署，无 Docker 环境 | 标准化分发，多服务器部署 |

---

### 方案一：部署包（推荐，无需 Docker）

```
Windows                              ARM 服务器
─────────────────────────────────    ──────────────────────────────────────
1. build.bat                         3. 解压 + deploy.sh
   npm run build  ──────────┐           unzip cluster-manager-deploy.zip
   打包成 ZIP     ──────────┤           ./deploy.sh
                            │           → pip install requirements.txt
                  scp ──────┘           → systemd 服务注册
2. cluster-manager-deploy.zip        4. 浏览器访问 http://<arm-ip>:8000
```

**Windows 端（构建）**：
```bat
build.bat
:: 产物: cluster-manager-deploy.zip
```

**传输到 ARM**：
```bash
scp cluster-manager-deploy.zip root@<arm-ip>:/opt/
```

**ARM 端（部署）**：
```bash
cd /opt
unzip cluster-manager-deploy.zip -d cluster-manager
cd cluster-manager
chmod +x deploy.sh
./deploy.sh
# → 自动 pip install + 注册 systemd 开机自启
```

---

### 方案二：Docker 多平台构建

**前提**：Windows 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)，并启用 QEMU 多平台支持。

**Windows 端（构建 ARM64 镜像）**：
```powershell
# 首次使用需创建 buildx builder
docker buildx create --use --name arm-builder

# 构建 ARM64 镜像并推送（替换 your-registry）
docker buildx build --platform linux/arm64 `
    -t your-registry/cluster-manager:latest `
    --push .

# 或直接保存为 tar 传输
docker buildx build --platform linux/arm64 `
    -t cluster-manager:latest `
    -o type=docker,dest=cluster-manager-arm64.tar .
```

**ARM 端（运行）**：
```bash
# 方式 A：从镜像仓库拉取
docker compose up -d

# 方式 B：从 tar 导入
docker load < cluster-manager-arm64.tar
docker compose up -d
```

**数据持久化**（docker-compose.yml 已配置 volume `cluster_data`）：
```
/var/lib/docker/volumes/cluster_data/_data/
├── cluster_manager.db   ← SQLite 数据库
├── pxe_data/            ← nodes.json 等
└── static/              ← 已内嵌镜像，无需挂载
```

---

### 方案三：全部在 ARM 构建机上构建（推荐用于生产交付）

```bash
# 构建机（有 Node.js + Python + pip）
chmod +x build.sh && ./build.sh
# 产物: cluster-manager-linux-arm64.tar.gz（自包含，生产机无需安装任何依赖）

# 生产机（干净的 OpenEuler ARM，什么都不需要装）
scp cluster-manager-linux-arm64.tar.gz root@<prod-ip>:/opt/
ssh root@<prod-ip> 'cd /opt && tar -xzf cluster-manager-linux-arm64.tar.gz'

# 直接运行
ssh root@<prod-ip> '/opt/cluster-manager/start.sh'

# 或注册为开机自启服务
ssh root@<prod-ip> 'cd /opt/cluster-manager && sudo ./install-service.sh'
```

**产物目录结构**：
```
cluster-manager-linux-arm64.tar.gz
└── cluster-manager/
    ├── cluster-manager       ← 可执行文件（含 Python 运行时 + 全部依赖）
    ├── _internal/            ← PyInstaller 依赖库（自动加载，无需关心）
    ├── static/               ← Vue 前端（FastAPI 直接提供服务）
    ├── start.sh              ← 启动脚本
    └── install-service.sh    ← systemd 自启注册脚本
```

---

### 端口与环境变量

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CLUSTER_MANAGER_HOST` | `0.0.0.0` | 监听地址 |
| `CLUSTER_MANAGER_PORT` | `8000` | 监听端口 |
| `CLUSTER_MANAGER_DATA` | 程序目录 | 数据目录（DB + pxe_data），Docker 必须设置 |

| 访问地址 | 说明 |
|----------|------|
| `http://<arm-ip>:8000` | 前端界面 |
| `http://<arm-ip>:8000/docs` | API Swagger 文档 |

---

## 变更记录

### 2026-05-15 — 故障诊断「日志导出」改造

**背景**：原 Tab3「日志采集」实际只是查询数据库里的演示日志，不是真的从远端拉日志。
用户场景是诊断一台具体的故障机器，需要把它的 journal / messages / dmesg / 网络快照
直接拉到本机文件里翻看，并按告警时间窗筛选。

| 文件 | 变更 |
|------|------|
| `backend/api/diagnose.py` | 新增 `POST /api/diagnose/log-export/run` (SSE 流式), 接收 `target_host/ssh_port/ssh_user/ssh_password/script_ids[]/output_dir/alert_time/range_before_min/range_after_min`；每个脚本顺序在目标 SSH 上跑、stdout 落盘成一个 `.log` 文件；复用 `_ACTIVE_RUNS` / `_cancel_run` 支持终止；输出路径 `{output_dir}/{时间戳}/{目标主机}/{category}-{name}.log`；`_safe_filename` 把脚本名规范化成安全文件名 |
| `backend/api/diagnose.py` | 引入 `SessionLocal` 直接构造短生命周期 session, 避开 `next(get_db())` 不会 close 的坑 |
| `backend/models/seed.py` | 加 6 条 `log_export` 默认脚本（business/system/kernel/network 四类）, 每条都根据 `$ALERT_FROM`/`$ALERT_TO` 是否存在自动切换"按时间窗筛选 vs 取最近 N 条"；新增 `_seed_log_export_if_missing()` 给旧 DB 增量补全, 不动已有 business/hardware 脚本 |
| `frontend/src/views/Diagnose.vue` | Tab 标签由「日志采集」改为「日志导出」, 名称从 `collect` 改为 `export` |
| `frontend/src/views/Diagnose.vue` | 新增 `exportForm`（目标 IP / 端口 / 用户 / 密码 / 输出目录 / 告警时间窗 / script_ids[]）、`startExport()` 消费 SSE 流并增量渲染、`terminateExport()` 调取消端点 |
| `frontend/src/views/Diagnose.vue` | 脚本面板按 category 分组, 每张卡左上 checkbox 选中、右下 编辑/删除；每个类型有"全选"复选框（含 indeterminate 状态）；可点「新建采集脚本」/「新建类型」复用 `scriptDialog` 加新条目 |
| `frontend/src/views/Diagnose.vue` | `DEFAULT_CATS`、`exportCategories`、`defaultForm`、`suggestCats`、`confirmNewType` 都补上对 `log_export` tab 的支持；默认超时 60s（高于 business/hardware 的 30s）|
| `frontend/src/views/Diagnose.vue` | 删掉旧的 `logQuery`/`queryLogs`/`logResults`/`levelColor` 死代码 |

**输出目录结构**：
```
D:\logs\export\
  20260515_103000\           ← 时间戳
    172.16.3.100\            ← 目标主机
      system-系统-journalctl.log
      system-系统-messages.log
      kernel-内核-dmesg.log
      network-网络-接口状态.log
```

**默认脚本示例**（system / journalctl）：
```bash
if [ -n "$ALERT_FROM" ]; then
  journalctl --since="$ALERT_FROM" --until="$ALERT_TO" --no-pager
else
  journalctl -n 1000 --no-pager
fi
```

**用法**：填目标 IP + SSH 密码（首次填，之后自动用持久化凭据）→ 输出目录（不存在自动创建）→ 可选告警时间，前 5 后 10 分钟 → 勾选要跑的脚本 → 开始导出。结果表实时刷新，每行显示状态、文件大小、绝对路径。中途可点终止强关 SSH。

**旧 DB 兼容**：原本只有 business/hardware 脚本的库, 启动时会被 `_seed_log_export_if_missing` 检测到 log_export 为空, 自动写入 6 条默认；已存在的脚本一条都不动。

---

### 2026-05-15 — 故障诊断脚本运行体验优化（终止 / 真超时 / 锁定窗口 / 告警时间窗）

**问题清单**：
1. 跑得卡住没法停, 只能等
2. 脚本配的超时不起作用, 长任务也不会被打断
3. 运行中误点对话框外面就关掉了, 结果丢失
4. 没办法把故障时间窗带进脚本

| 文件 | 变更 |
|------|------|
| `backend/services/diag_service.py` | `run_ssh_command` 整个重写：用 `channel.settimeout(0.5)` 非阻塞轮询代替阻塞 `recv_exit_status()`；本地维护 `deadline = time.time() + timeout` 的硬超时，命中即 `chan.close()` 强行中断（之前 paramiko 的 `exec_command(timeout=N)` 只控制 socket I/O 间隔，命令长时间不输出也不会超时——这就是「超时设置没生效」的根因）；新增 `is_cancelled` 回调和 `on_client` 回调，分别用于检查取消信号、把刚建立的 paramiko client 暴露出去给外部 cancel 关闭；定义清晰的退出码 `EXIT_TIMEOUT=-2 / EXIT_CANCELLED=-3 / EXIT_ERROR=-1` |
| `backend/api/diagnose.py` | 引入 `_ACTIVE_RUNS: Dict[run_id, {cancel: Event, clients: [], lock: Lock}]` + `_RUNS_LOCK` 跟踪每次运行；`_cancel_run(run_id)` 设置 Event 并 `close()` 所有已注册 client，把阻塞的 `chan.recv` 立刻打断 |
| `backend/api/diagnose.py` | `ScriptRunRequest` 加 `alert_time: Optional[datetime]` + `range_before_min: int` + `range_after_min: int`；新增 `_build_env_prefix()` 把告警时间窗生成 shell `export ALERT_TIME=... ALERT_FROM=... ALERT_TO=... ALERT_BEFORE_MIN=... ALERT_AFTER_MIN=...` 前缀，拼接到 script_content 头部 |
| `backend/api/diagnose.py` `/scripts/{id}/run` | 生成 `run_id = uuid4().hex[:12]` 注册到 `_ACTIVE_RUNS`，在 SSE `start` 事件中下发；`_run_one` 起跑前先检查 `_is_cancelled`（已取消的节点 short-circuit 不再连接，返回 exit_code=-3）；`end` 事件附带 `cancelled` 标志；`try/finally` 保证从 `_ACTIVE_RUNS` 摘除避免内存泄漏 |
| `backend/api/diagnose.py` | 新增 `POST /api/diagnose/scripts/runs/{run_id}/cancel` 端点（找不到 run_id 返回 404）和 `GET /api/diagnose/scripts/runs/active`（调试用） |
| `frontend/src/views/Diagnose.vue` 运行对话框 | `:close-on-click-modal="!running"` + `:close-on-press-escape="!running"` + `:show-close="!running"`，运行中点击遮罩 / ESC / X 都关不掉；表单 `:disabled="running"` 冻结所有输入；顶部一条 warning alert 告知"对话框已锁定" |
| `frontend/src/views/Diagnose.vue` 运行对话框 | 「执行」按钮 `v-if="!running"`、运行中切换为红色「终止」`v-else type="danger"`，点击弹二次确认（用语：会立刻关闭进行中的 SSH，已完成的结果保留）；POST `/scripts/runs/{run_id}/cancel`；展示当前 `run_id` 标签 |
| `frontend/src/views/Diagnose.vue` 运行对话框 | 新增「告警时间」`el-date-picker` + 「前 N 分 · 后 N 分」`el-input-number`（仅在 `alert_time` 非空时显示）；hint 提示脚本里可用 `$ALERT_TIME` / `$ALERT_FROM` / `$ALERT_TO`（格式 `YYYY-MM-DD HH:MM:SS`，适配 `journalctl --since/--until`、`dmesg --since`） |
| `frontend/src/views/Diagnose.vue` | `executeScript` 把 `alert_time/range_before_min/range_after_min` 放进 payload；start 事件里取 `run_id` 存到 `currentRunId`；end 事件的 `cancelled` 标志决定 toast 是「已终止」还是「执行完成」 |

**取消机制原理**：取消端点同时做两件事 — set `cancel` event + 对每个已注册的 paramiko client 调 `client.close()`。后者会让 SSH 线程里阻塞的 `chan.recv*` 抛异常或 `exit_status_ready()` 立刻变 True；轮询循环每 50ms 也会主动检查 cancel event。两条路保证 100ms 内能收尾。已经在执行的脚本拿到的是部分输出 + `EXIT_CANCELLED=-3`；还没排到 SSH 的节点 short-circuit 直接返回。

**用户感受变化**：

| 场景 | 之前 | 现在 |
|---|---|---|
| 脚本卡在 sleep 600 | 只能等满 600s | 点终止 < 100ms 退出 |
| 脚本超时 30s, 一直 echo 心跳 | 永不超时（socket 一直在动） | 严格 30s 后 chan.close 强中断, exit_code=-2 |
| 运行中不小心点了对话框外面 | 对话框关掉, 结果丢失 | 关不掉, 必须等结束或点终止 |
| 想看故障发生时窗的 journal | 改脚本硬编码时间, 跑完改回去 | 表单填告警时间, 脚本里直接 `journalctl --since="$ALERT_FROM" --until="$ALERT_TO"` |

---

### 2026-05-15 — 节点管理空表修复 + dev.bat 一键启动 + 应用规划清理残留

**问题**：用户做完 IP 规划点应用，节点管理还是空的；改完前后端文件没法快速重启验证。

| 文件 | 变更 |
|------|------|
| `backend/main.py` | SPA 兜底路由 `/{full_path:path}` 显式排除 `api/` 和 `iso/` 前缀，否则贪婪 path 路由会优先于 FastAPI 的 `redirect_slashes`，把 `GET /api/nodes`（无尾斜杠）兜底成 `index.html`，前端 axios 拿到 HTML 解析失败 → 节点表永远是空 |
| `backend/api/nodes.py` | `@router.get("/")` 改成 `@router.get("")`，POST 同改，让 `/api/nodes`（无尾斜杠）精确匹配；`/masters` `/slaves` `/topology` 三个静态路径上移到 `/{node_id}` 之前，否则 `topology` 会被当作 node_id 校验失败 |
| `backend/api/pxe.py` | 新增 `_PLAN_HOSTNAME_RE = ^(master\|slave\|subswath\|gstorage\|acquisition)-\d{2,}$`，`_sync_nodes_json_to_db_impl` 同步前先按这个正则识别"规划生成的主机名"，凡是不在本次 nodes.json 里的全部 delete；demo seed 的 `master-1`（单位数字）和用户自定义主机名都不动 |
| `backend/api/pxe.py` | 同步返回 `deleted_hostnames` 字段，regenerate 响应 message 显式说明「清理规划残留 N 个」 |
| `frontend/src/views/Nodes.vue` | 同步按钮 toast 增加「清理残留 N」；deleted_hostnames 列表打到 console 便于核对 |
| `frontend/src/views/PXEDeploy.vue` | 应用规划确认弹窗补一条说明"名称符合规划模板但不在本次规划 → 一并删除；单数字 demo 和自定义主机名 → 不受影响"；toast 加 `清理残留 N` 字段 |
| `frontend/src/App.vue` `frontend/src/router/index.js` | 注释掉巡检页菜单和路由（页面留着不删，后续重新设计），左侧导航少一个入口 |
| `clustermanager/dev.bat` | **新文件** — conda `myenv` + Node.js 一键拉起前后端：后端在新 CMD 跑 `python main.py:8000`，前端在新 CMD 跑 `npm run dev:3000`，5 秒后自动打开浏览器；全 ASCII 文本避免 GBK 代码页问题；含 conda/node/main.py/package.json 前置检查 |

**SPA 兜底踩坑过程**：用户反馈"节点管理还是空"，最开始以为是 DB 没数据；让用户开 F12 看 Network 面板 → `/api/nodes` 返回 HTML 不是 JSON → 锁定路由问题。根因：之前跑过一次 `build.bat`，[backend/static/](clustermanager/backend/static/) 目录存在 → `main.py` 注册了 SPA 兜底 → `/{full_path:path}` 完整匹配 `/api/nodes`（FULL match）优先级高于 FastAPI 的 redirect_slashes（PARTIAL match）→ 请求直接吃 index.html。修复后 axios 能正常拿 JSON，节点表立即恢复。

**规划残留清理**：实际场景是用户先规划了 master×6+slave×12+subswath×2+gstorage×1（22 节点），后改成 master×1+slave×3+subswath×1+gstorage×1（7 节点）。旧的 sync 只 upsert 不删除，DB 里堆着原来的 19 个旧节点 + 7 个新节点 = 26 个不符合预期。新版以「主机名模板」为判据精准清理：

| 主机名 | 模板匹配 | 在新规划中 | 处理 |
|---|---|---|---|
| `master-01` (旧) | ✓ | ✗ | 删除 |
| `master-01` (新) | ✓ | ✓ | upsert |
| `master-1` (demo) | ✗（单位数字） | n/a | 保留 |
| `sensor-array-1` (demo) | ✗ | n/a | 保留 |
| `my-custom-rack-a` (手动添加) | ✗ | n/a | 保留 |

---

### 2026-05-13 — IP 规划：新规划为准 + 单按钮 UX 修复

**问题**：用户做了新规划（5 节点）后，节点配置仍显示旧的 23 节点、节点管理为空。原因有二：
1. 之前的合并语义是「保留旧的多余节点不删」，缩容后看不出变化
2. 「生成规划」（仅预览）和「应用到 nodes.json」（真正保存）两个按钮容易让用户以为预览即保存

| 文件 | 变更 |
|------|------|
| `backend/api/pxe.py` `_merge_nodes_json` | 改语义为「**新规划为 source of truth**」：同 hostname 用旧 MAC（若真实）+ 新 IP 字段；新 hostname 追加；**旧规划里有但本次不在的 → 删除**（不再保留），符合用户的"相同覆盖 / 新增即可"语义 |
| `backend/api/pxe.py` `_sync_nodes_json_to_db_impl` | 新增 `prune_missing` 参数（默认 True）；同步时按 `master-*/slave-*/subswath-*/gstorage-*/acquisition-*` 前缀匹配规划生成的节点，**hostname 不在本次规划中 → 从 DB 删除**；手动添加的节点（不匹配上述前缀）不动 |
| `backend/api/pxe.py` `/nodes-json/regenerate` 响应 | 返回 `added/updated/removed` 列表（之前是 `added/updated/kept`），并附 `db: {created, updated, deleted}` 完整统计 |
| `frontend/src/views/PXEDeploy.vue` | 「生成规划」和「应用到 nodes.json」两按钮合并简化：主按钮「**应用规划 (保存到 nodes.json + 节点管理)**」success 色一键完成；次按钮「**仅预览**」plain 色仅查看不保存 |
| `frontend/src/views/PXEDeploy.vue` | 新增 `planSaved` 响应式状态：仅预览时 `planSaved=false` 显示**橙色 warning 条**"当前未保存,点击应用规划保存"；应用成功后 `planSaved=true` 显示**绿色 success 条**"已保存到 nodes.json,节点管理已同步"；`watch(planForm, deep)` 在用户改任意 count 时把 `planSaved` 重置为 false |
| `frontend/src/views/PXEDeploy.vue` 确认弹窗 | 列出明确规则：同名保 MAC + 新增追加 + **旧规划被删除**（之前文案说"保留不删"，与新行为不一致） |
| `frontend/src/views/PXEDeploy.vue` 成功 toast | `已保存到 nodes.json: 新增 X / 更新 Y / 删除 Z; 节点管理: 新建 N 离线 / 删除 M` 直接对账 |

**新合并示例**：

```
旧 nodes.json (23):              新规划 (5):           合并后 (5):
  00:11:.. master-01            aa:bb:.. master-01    00:11:.. master-01  ← 真 MAC 保留, IP 新算
  aa:bb:.. master-02..07                              ← 删除 (不在新规划)
  aa:bb:.. slave-01..02         aa:bb:.. slave-01..02 aa:bb:.. slave-01..02
  aa:bb:.. slave-03..13                               ← 删除
  aa:bb:.. subswath-01..02      aa:bb:.. subswath-01  aa:bb:.. subswath-01
  aa:bb:.. gstorage-01          aa:bb:.. gstorage-01  aa:bb:.. gstorage-01
```

**DB 清理边界**：只删除符合规划前缀（master-/slave-/subswath-/gstorage-/acquisition-）且不再在本次规划的节点；用户在「节点管理」手动新建的节点（不匹配前缀）一律不动。

**用户感受变化**：

| 操作 | 之前 | 现在 |
|---|---|---|
| 改 Master 从 7 缩到 1, 应用 | nodes.json 仍 23 个 (旧的 6 个一直堆着) | nodes.json 严格为 5 个, 节点管理同步删除 6 个 |
| 改完 count 没点应用就跳到节点配置 | 没人提醒, 用户以为已保存 | 主按钮变 success 大字; 预览框上方橙色未保存警告 |
| 应用后查看 | 上方绿色提示, 但和预览一样的措辞 | 上方绿色 ✓ "已保存"; toast 详细列出 added/updated/removed/db_deleted |
| 改了 count 但没重新应用 | 状态保持"已保存" (假象) | watch 立即把状态切回"未保存", 提示重新应用 |

---

### 2026-05-13 — IP 规划合并落库 + 节点状态贯通诊断目标过滤

**用户场景**：
- 想看到 IP 规划保存到 nodes.json 后的节点 → 直接出现在「节点管理」页，且未部署的显示为离线
- 诊断脚本的目标节点下拉只列出**真正在线**的节点（offline 节点 SSH 拨不通，不应出现）
- 多次执行 IP 规划时，已经填了真实 MAC / 已部署的节点不能被覆盖丢失

| 文件 | 变更 |
|------|------|
| `backend/api/pxe.py` | 新增 `_is_placeholder_mac`、`_index_by_hostname`、`_merge_nodes_json` 三个辅助函数；`/nodes-json/regenerate` 改为**合并语义**：同 hostname 保留旧 MAC（若为真实 MAC `非 aa:bb:cc:* 前缀`）+ IP 字段用新规划；新 hostname 追加；旧 hostname 不在新规划中 → 保留不删。regenerate 内部自动调用 `_sync_nodes_json_to_db_impl()` 落库，返回 `{added, updated, kept, db: {created, updated}}` 详细计数 |
| `backend/api/pxe.py` | `/nodes-json/sync-to-db` 抽出 `_sync_nodes_json_to_db_impl()` 内部函数；新节点创建时显式设 `status=ctrl_status=data_status='offline'`；**更新已存在节点时只覆盖规划字段（IP/MAC/role），不动状态字段** —— 避免在线节点被规划重置成离线 |
| `frontend/src/views/Diagnose.vue` | 新增 `onlineNodes` 计算属性 `nodes.filter(n => n.status === 'online')`；运行对话框的「目标节点」下拉只渲染 onlineNodes，无在线节点时下拉禁用并显示橙色提示；`openRunDialog()` 时调 `loadNodes()` 拉一次最新状态 |
| `frontend/src/views/PXEDeploy.vue` | `applyPlanToNodesJson()` 改为单次 POST（regenerate 内部已落库，无需再 POST sync-to-db）；确认弹窗文案说明合并语义；成功 toast 显示 `新增 X / 更新 Y / 保留 Z；节点管理新建 N 个离线节点`，让用户能直接对账 |

**合并算法（regenerate）**：

```
old nodes.json:           new defaults:            merged:
  00:11:.. master-01        aa:bb:.. master-01  →  00:11:.. master-01   (旧 MAC 真实, 保留; IP 用新)
  aa:bb:.. master-02        aa:bb:.. master-02  →  aa:bb:.. master-02   (旧 MAC 占位, 用新)
                            aa:bb:.. master-03  →  aa:bb:.. master-03   (新增)
  00:22:.. legacy-host                          →  00:22:.. legacy-host (旧的不在新规划中, 保留)
```

**用户感受变化**：

| 操作 | 之前 | 现在 |
|---|---|---|
| 第二次跑 IP 规划应用 | 已填的 MAC 被冲掉，状态被重置为 offline | MAC 保留；状态保留；按 hostname 合并 |
| IP 规划 → 节点管理 | 需要手动二次同步才能看到 | regenerate 内部已落库，一次按钮全部到位 |
| 选择诊断目标节点 | 列出所有节点 (offline 也在列, 选了必然 SSH 失败) | 只列 online 节点，无 online 时下拉禁用并提示 |

---

### 2026-05-13 — SSH 凭据持久化 + 流式诊断 + 局域网共享模式

**背景**：每次执行诊断脚本都要输密码、串行执行慢、Windows 上有时需要让别的机器也能浏览器
访问。三处一起改：

| 改进 | 实现 |
|------|------|
| ① **SSH 凭据持久化** | `backend/services/cred_service.py` 把 user/password/port 写到 `BASE_DIR/ssh_credentials.json`；后端 `POST /api/diagnose/scripts/{id}/run` 接受 `********` 占位密码自动回退到已保存的；首次成功执行后自动保存 |
| ② **诊断脚本流式执行** | 把 run 接口改为 `StreamingResponse` (SSE `text/event-stream`)；多节点用 `asyncio.create_task` + `ThreadPoolExecutor(16)` 并行 SSH；每节点完成立即 emit `data: {...}` 一条事件，前端 `fetch` + `ReadableStream` 解析后追加到结果列表 |
| ③ **局域网共享模式** | `backend/desktop.py` 读 `CLUSTER_MANAGER_BIND` 环境变量，默认 `127.0.0.1`，设为 `0.0.0.0` 时绑定所有网卡；窗口标题显示局域网可访问 URL；`build_templates/start-shared.bat` 一键开启 |

**新增 / 修改文件**：

| 文件 | 变更 |
|------|------|
| `backend/services/cred_service.py` | **新文件** — `load_creds / save_creds / clear_creds / get_public_info / resolve_password`；密码占位符 `********` 由 `resolve_password()` 回退到磁盘已保存的密码 |
| `backend/api/diagnose.py` | run 接口改异步 + SSE 流式 + 并行；新增 `GET/POST/DELETE /api/diagnose/ssh-creds`；运行时若收到非占位符密码会自动调用 `cred_service.save_creds()`；事件结构 `start`/`result`/`end` |
| `backend/desktop.py` | `BIND_HOST` 从 `CLUSTER_MANAGER_BIND` 环境变量取；`_list_lan_ips()` 列出非环回 IPv4；共享模式窗口标题展示 `LAN: http://<ip>:<port>, ...`；pywebview 始终走 `127.0.0.1` 不受 BIND 影响 |
| `frontend/src/views/Diagnose.vue` | `openRunDialog()` 自动调 `GET /ssh-creds` 预填用户名/端口、密码字段填 `********` 占位；`executeScript()` 改为 `fetch` 消费 SSE 流，每收到一条 `result` 事件就 `runResults.push(evt)` 增量渲染；新增「已完成 N / 总数」进度文本和「已保存凭据」标签 |
| `build_templates/start-shared.bat` | **新文件** — `set CLUSTER_MANAGER_BIND=0.0.0.0` 后再启 EXE |
| `build_templates/README.txt` | 加局域网共享模式说明、`ssh_credentials.json` 文件说明、更新部署时保留 `ssh_credentials.json` |
| `build.bat` | 同时拷贝 `start.bat` 和 `start-shared.bat` |
| `.gitignore` | 加 `backend/ssh_credentials.json` |

**用户体感变化**：

| 项 | 之前 | 现在 |
|---|---|---|
| 第二次起跑脚本 | 重新输密码 | 自动用上次的（密码栏显示 `********`，改了就更新保存） |
| 5 节点 30s 脚本 | 串行 150s 全黑屏 | 并行 ~30s，每节点完成立刻显示 |
| 同事临时看一眼 | 必须远程到 Windows | 双击 `start-shared.bat`，把窗口标题里的 LAN URL 发给他即可 |

**关于 Q4 (手动纳管未部署机器)**：节点页 `frontend/src/views/Nodes.vue` 在 2026-05-05 已支持
新增/编辑/删除节点，并已包含 hostname / node_type / mgmt_ip / bmc_ip / ctrl_ip / data_ip /
五类硬件字段共五个区块。手动添加的节点和 PXE 部署的节点在数据库里同等对待，可以直接进入
故障诊断 → 选中节点 → 跑脚本。本次未做额外改动。

**安全提示**：`ssh_credentials.json` 含明文密码，文件加进了 `.gitignore`；启用共享模式时
（`0.0.0.0`），同网段任何能访问到端口的机器都能调 API 跑脚本，**生产环境请配合防火墙限制
源 IP**，或仅在临时演示时启用。

---

### 2026-05-13 — Windows 桌面 App 模式 + 编码问题修复

**背景**：cluster-manager 由「部署到 ARM 服务器 + 浏览器访问」改为「直接部署在 Windows 管理站
作为桌面应用」。启动后不再打开浏览器，而是弹出原生应用窗口；后端在内部启动 uvicorn，对外远程
操作 ARM 集群（SSH 控制面 / Redfish BMC / IPMI / DHCP-TFTP-HTTP）。

同时修复 `build.bat` 在中文 Windows 上 UTF-8 / GBK 代码页冲突导致的乱码与命令解析失败。

| 文件 | 变更 |
|------|------|
| `backend/desktop.py` | **新文件** — 桌面版启动器：后台线程跑 uvicorn，主线程 pywebview 打开 1400×900 原生窗口；端口被占用时自动顺延 8001..8049；冻结模式下日志重定向到 `cluster_manager.log` |
| `backend/requirements.txt` | 新增 `pywebview>=5.0`（Windows 用 Edge WebView2 后端） |
| `backend/cluster_manager.spec` | 入口由 `main.py` 改为 `desktop.py`；`console=False` 纯 App 体验；`collect_all('webview')` 收集 pywebview 全部资源；hiddenimports 加 `webview.platforms.edgechromium` / `clr_loader` / `proxy_tools` 等 |
| `backend/main.py` | 保留 `__main__` 入口作为纯后端开发模式（`python main.py`） |
| `build.bat` | **完全重写**，全 ASCII 英文文本（中文 Windows 上代码页不再出错）；用 `>>` 追加和 `copy` 替代 `( echo ... )` 多行重定向块；不再在 .bat 里嵌入要生成的 start.bat / README.txt，改为从 `build_templates/` 复制 |
| `build_templates/start.bat` | **新文件** — 用户启动器模板，ASCII，`start "" cluster-manager.exe` 后立即返回 |
| `build_templates/README.txt` | **新文件** — 中文部署说明，含 WebView2 Runtime 要求、目录结构、网络要求、初次部署/更新部署流程、端口冲突处理、排错指引 |

**目标机部署步骤**：

```
1. 解压 cluster-manager-windows.zip
2. (可选) 在 iso\ 目录放置 PXE Host 装机 ISO
3. 双击 cluster-manager.exe (或 start.bat)
4. 自动弹出 "Cluster Manager" 原生窗口 (无浏览器)
```

**运行时要求**：
- Windows 10 / 11 x64
- Microsoft Edge WebView2 Runtime（Win11 内置；Win10 缺失时程序首次启动会引导安装，
  或从 https://aka.ms/webview2 手动下载）

**网络要求**：目标 Windows 主机需同时可达集群节点的 BMC（管理面 GE，通常 `172.16.0.0/24`）
和 控制面（10GE，通常 `172.16.3.0/24`）。

**为什么用 pywebview 而不是 Electron**：体积小（无需打包 Chromium，复用系统 WebView2，
通常 < 100MB onedir）；Python + FastAPI 现有后端无需改动；窗口生命周期管理直接绑定到
进程退出。

**调试入口**：`console=False` 模式下日志写入 EXE 同目录的 `cluster_manager.log`；
开发阶段可以 `python desktop.py` 跑桌面版、`python main.py` 跑纯服务器版。

**编码问题修复说明**：原 `build.bat` 含中文 echo 与 `( echo ... echo ... )` 多行重定向块，
在中文 Windows（默认 GBK 代码页）下读取 UTF-8 字节会乱码，且 `(...)` 块内的 `cluster-manager.exe`
等行被 cmd 解析器误拆为外层命令。新版本所有 echo 全英文、所有生成文件改为「模板 + copy」
模式，彻底回避代码页问题。

---

### 2026-05-08 — 故障诊断脚本配置持久化与发布包支持

**背景**：脚本库配置完成后需打入发布包，新环境首次启动可直接复用，无需手动重建。

| 文件 | 变更 |
|------|------|
| `backend/config.py` | 新增 `SCRIPTS_BUNDLE_PATH`（指向 `<安装目录>/scripts_bundle.json`） |
| `backend/models/seed.py` | `_seed_diag_scripts()` 启动时优先读取 `scripts_bundle.json`；文件存在则从中加载，否则回退到内置默认脚本 |
| `backend/api/diagnose.py` | 新增 4 个脚本管理接口（见下表） |
| `frontend/src/views/Diagnose.vue` | 诊断页顶部新增「脚本配置」全局操作栏，含导出 / 导入 / 保存为发布配置三个按钮及发布包状态标签 |

**新增后端接口**：

| 接口 | 说明 |
|------|------|
| `GET  /api/diagnose/scripts/export` | 导出全部脚本为 `scripts_bundle.json`（浏览器触发下载） |
| `POST /api/diagnose/scripts/import` | 批量导入脚本 JSON；`mode=merge`（默认）按 `tab+category+name` upsert，`mode=replace` 先清空再导入 |
| `POST /api/diagnose/scripts/save-bundle` | 将当前数据库脚本快照写入服务端 `scripts_bundle.json` |
| `GET  /api/diagnose/scripts/bundle-info` | 返回发布包是否存在、脚本数量、最后修改时间 |

**使用流程**：
```
1. 在诊断页配置好全部脚本（增删改）
2. 点击「保存为发布配置」→ 生成 backend/scripts_bundle.json
3. 打包 release 时将 scripts_bundle.json 随安装包一同发布
4. 新环境首次启动 → 自动从 scripts_bundle.json 加载脚本，无需手动重建
```

也可通过「导出配置」将 JSON 下载后离线传递，目标环境通过「导入配置」合并（不清空已有脚本）。

---

### 2026-05-08 — 新增 Acquisition 角色 + 角色数量允许为 0 + Bootstrap 卡片底色修复

| 文件 | 变更 |
|------|------|
| `backend/services/pxe_service.py` | `_default_nodes_json` / `generate_ip_plan` 新增 `acquisition_count` 参数（默认 0）；Acquisition 节点：BMC 172.16.0.100+，ctrl 172.16.3.100+，DPDK-1 200.1.1.100+，RDMA-1 100.1.1.100+，网卡 eno2(dpdk)/eno3(rdma) |
| `backend/api/pxe.py` | `NetworkPlanRequest` / `RegenerateRequest` 加 `acquisition_count`；`_WAVE_ROLES[3]` 加入 `acquisition` |
| `backend/api/network.py` | Acquisition 节点同时加入 DPDK（data_front）和 RDMA（data_back）链路组 |
| `frontend/src/views/PXEDeploy.vue` | 数量输入框全部改为 `:min="0"`；加 Acquisition 数量输入和规划结果表；规划结果各角色表按 count > 0 条件显示；编辑对话框顶部加角色 NIC 规划提示；DPDK 段条件改为 `['master', 'acquisition'].includes(role)`；分批部署卡片加 `v-if="waveNodes(n).length > 0"` 条件渲染，全空时显示空提示；wave3 卡片标题改为"Slave / Acquisition" |
| `frontend/src/views/NetworkMap.vue` | `NODE_TYPE_LABEL` / `NODE_R` / `NODE_ICON` / `nodeFills` 加 `acquisition`（图标 A，青黑色）；底层节点加入 acquisitions |
| `frontend/src/views/PXEDeploy.vue` (CSS) | `el-descriptions` `content` 改为 `#0a1628`；Bootstrap 卡片内 `.bootstrap-body` 的 el-descriptions 使用更深底色 `#060e1c`；加 `.role-acquisition` 青色 |

### 2026-05-08 — Windows 管理站 + PXE Host 首次装机引导（Bootstrap，一次性）

将 cluster-manager 由"运行在 PXE Host 上"改为"运行在独立 Windows 管理站上"。
PXE Host 装好后稳定运行（持续给其他节点提供 DHCP/TFTP/HTTP），不需要每次都重装；管理站只在
**首次部署**时通过 BMC Redfish 把本地 ISO 挂为 PXE Host 的虚拟光驱，触发其一次性 CD 引导完成自动装机。

| 文件 | 变更 |
|------|------|
| `backend/config.py` | 新增 `ISO_DIR`（环境变量 `CLUSTER_MANAGER_ISO_DIR`，默认 `<安装目录>/iso/`） |
| `backend/services/redfish_service.py` | **新文件** — `RedfishClient.deploy_iso()` 三步法：InsertMedia → Boot=Cd/Once → ComputerSystem.Reset；支持华为 iBMC / Dell iDRAC / 标准 DMTF |
| `backend/services/pxe_service.py` | 新增 `pxe_host.json` 独立配置文件（BMC IP/凭据 + Redfish ID + ISO HTTP 主机端口）；`read/write_pxe_host_config()`、`list_iso_files()` |
| `backend/api/pxe.py` | 新增 `POST /pxe-host/install`（语义清晰的 Bootstrap 端点）、`GET /pxe-host/status`（5 态：not_configured / not_installed / installing / online / error）、`GET/PUT /pxe-host/config`、`GET /pxe-host/iso-list`；`wave-deploy/{wave}` 仅允许 1/2/3 — PXE Host 装机不再混在分批序列里 |
| `backend/main.py` | 挂载 `/iso/` 静态目录给 BMC 拉 ISO（必须早于 SPA catch-all） |
| `backend/api/network.py` | `mgmt-station` 节点改名为「管理站 (Windows)」并连入控制面；新增 `pxe-host` 节点（Redfish 链路 + DHCP/TFTP/HTTP 上行至控制交换机） |
| `backend/requirements.txt` | 新增 `httpx>=0.25.0`（Redfish HTTPS 调用） |
| `frontend/src/views/PXEDeploy.vue` | 分批部署 Tab 顶部独立的「PXE Host 首次装机引导」**默认折叠**卡片，明确标注 `Bootstrap · 一次性`；状态指示器（5 态彩色）；按钮根据状态显示「开始首次装机 / 装机进行中… / PXE Host 已就绪」；线上态额外提供「⚠ 强制重新装机」二次确认按钮防误触；分批部署 alert 文案不再提"第零批" |
| `frontend/src/views/NetworkMap.vue` | `NODE_TYPE_LABEL` / `NODE_R` / `NODE_ICON` / `nodeFills` 加 `pxe_host`（图标 P，红棕色填充）；`computePositions()` 把 PXE Host 放在管理层右侧 |

**关键定位**：PXE Host 装机是一次性 Bootstrap 操作，不属于"每次都要做的分批部署"。UI 上独立折叠、按钮在
`online` 状态时禁用并显示"已就绪"，强制重装走单独的红色二次确认通道；API 上拆出 `/pxe-host/install`
和 `/wave-deploy/{1|2|3}`，避免语义混淆。

**ISO 准备**：把 PXE Host 部署 ISO（如 `openeuler-pxe-host.iso`）放到 Windows 管理站安装目录下的 `iso/` 子目录。
ISO 内的 kickstart/firstboot 应包含 dhcpd / tftp-server / nginx 等服务的安装与启动，使 PXE Host 装完即可对外服务。
该 ISO 可被复用为其他角色的基础镜像（用 firstboot 差异化注入决定 master/slave/...）。

**Windows 管理站网卡**：同时接入管理面（GE，与所有 BMC 互通）和控制面（10GE，与所有节点互通）。
配置中 `iso_http_host` 字段需填写 BMC 可达的管理面 IP（GE 网卡地址）。

**安全提示**：BMC 密码以明文存于 `pxe_data/pxe_host.json`。建议在生产环境给该文件加 ACL 限制读权限，
或后续改为操作系统密钥库存储。前端读取时密码字段会以 `********` 占位，保存时留空表示不修改。

### 2026-05-08 — 分批部署状态监控修复（IP 地址 + 进展显示）

| 文件 | 变更 |
|------|------|
| `backend/api/pxe.py` | 新增 `POST /wave-deploy/{wave}` 端点：从 nodes.json 读取对应角色节点，同步到 DB 并置 `status=deploying`，使状态监控立即可见 |
| `backend/api/pxe.py` | `DeployStatus` 模型增加 `bmc_ip`、`ctrl_ip`、`data_ip` 字段；`GET /status` 返回 IP 信息及有意义的阶段文本（等待 PXE 引导/安装/配置）和对应进度百分比 |
| `frontend/src/views/PXEDeploy.vue` | `triggerWaveDeploy()` 改为调用 `/api/pxe/wave-deploy/{wave}`，不再依赖静默失败的 IPMI 接口 |
| `frontend/src/views/PXEDeploy.vue` | 状态监控表格新增 BMC IP / 控制面 IP / 数据面 IP 三列，蓝色等宽字体显示 |

### 2026-05-08 — 配色修复 + 组网图 100G 交换机拓扑 + 多接口并行链路

**涉及文件**：
- `frontend/src/views/Nodes.vue`
- `frontend/src/views/PXEDeploy.vue`
- `frontend/src/views/NetworkMap.vue`
- `backend/api/network.py`

**变更详情**：

| # | 变更点 | 说明 |
|---|--------|------|
| 1 | **Nodes.vue 暗色表格** | 新增 `.nodes-view :deep(.el-table)` 覆盖，表头 `#0d1b2e`、hover `#1e3a5f`，与 PXE 页面配色统一 |
| 2 | **对话框 divider 修复** | Nodes.vue + PXEDeploy.vue 编辑对话框中 `el-divider` 标签背景改为 `#1a2744`，消除白色背景块 |
| 3 | **组网图 100G 数据交换机** | 新增 `sw-data-100g` 虚拟节点；DPDK（传感器/Master）和 RDMA（Master/Slave/SubSwath/GStorage）均通过交换机中转，不再直连 |
| 4 | **多接口并行链路** | 读取 nodes.json NIC 清单，每个物理接口生成独立链路（携带 `port_index`/`port_count`/`nic` 字段）；前端按垂直偏移（11px 间距）渲染平行曲线，标注显示网卡名（如 `enp129s0f0`） |
| 5 | **5 层拓扑布局** | 新增"数据交换层"（100GE 交换机），布局调整为：管理层 → 控制层 → 主控层 → 数据交换层 → 数据处理层 |
| 6 | **SubSwath / GStorage 节点** | 加入数据处理层，图标 N/G，颜色绿/橙褐，`NODE_TYPE_LABEL` / `NODE_R` / `nodeFills` 同步补全 |

---

### 2026-05-08 — PXE 表格暗色主题修复 + IP规划同步节点配置/组网图

**涉及文件**：
- `frontend/src/views/PXEDeploy.vue`
- `backend/api/pxe.py`
- `backend/services/pxe_service.py`

**变更详情**：

| # | 变更点 | 说明 |
|---|--------|------|
| 1 | **表格暗色主题** | 用 `.pxe-deploy :deep(.el-table)` 覆盖 Element Plus 所有白色默认值：表头 `#0d1b2e`，行透明，hover `#1e3a5f`，斑马纹 `rgba(255,255,255,0.025)`，使用 CSS 变量 + `!important` 双保险 |
| 2 | **IP规划同步** | 修复 `applyPlanToNodesJson()` —— 原实现只是将 nodes.json 读出再写回（无变化）；现改为调用 `regenerate`（按规划数量重新生成）+ `sync-to-db`（同步到 DB），节点配置和组网图同步更新 |
| 3 | **`_default_nodes_json()` 参数化** | 新增 `master_count / slave_count / subswath_count / gstorage_count` 参数，支持任意数量节点的模板生成 |

**新增后端接口**：

| 接口 | 说明 |
|------|------|
| `POST /api/pxe/nodes-json/regenerate` | 按指定节点数量重新生成 nodes.json 模板 |
| `POST /api/pxe/nodes-json/sync-to-db` | 将 nodes.json 同步到 DB 节点表，使组网图同步更新 |

---

### 2026-05-08 — PXE 页面优化：暗色 Tab / NIC 编辑 / 自定义脚本 / 组网图 BMC 跳转

**涉及文件**：
- `frontend/src/views/PXEDeploy.vue`
- `frontend/src/views/NetworkMap.vue`
- `backend/api/pxe.py`
- `backend/services/pxe_service.py`

**变更详情**：

| # | 变更点 | 说明 |
|---|--------|------|
| 1 | **Tab 暗色主题** | 用 `.dark-tabs` 覆盖 `el-tabs--border-card` 默认白色背景；未激活 `#64748b`，激活 `#3b82f6`（蓝色），与整体深蓝主题协调 |
| 2 | **节点 NIC/IP 编辑** | 节点配置编辑对话框扩展为 MAC → 控制面 NIC → DPDK 网卡（仅 master）→ RDMA 网卡四个区块；每行含网卡名（如 `enp129s0f0`）和 IP/掩码（如 `200.1.1.11/24`）输入，支持动态增删行；新增后端 `PATCH /api/pxe/nodes-json/update-node` |
| 3 | **自定义脚本** | 分批部署页新增"自定义脚本"卡片：节点多选 + SSH 用户/密码 + 脚本编辑器 + 结果表格；新增后端 `POST /api/pxe/run-script`，通过 paramiko 并发 SSH 到各节点控制面 IP 执行脚本 |
| 4 | **组网图 BMC 跳转** | 点击拓扑图节点，右侧详情面板底部显示"打开 BMC 管理界面"按钮，提取 `planes.management.bmc_ip` 在新标签页打开 `https://<bmc_ip>` |

**新增后端接口**：

| 接口 | 说明 |
|------|------|
| `PATCH /api/pxe/nodes-json/update-node` | 更新节点 ctrl_nic / dpdk_nics / dpdk_ips / rdma_nics / rdma_ips |
| `POST  /api/pxe/run-script` | SSH 并发执行自定义脚本，返回每节点状态和输出 |

---

### 2026-05-05 — 节点管理页支持手动新增/编辑/删除节点

**背景**：已完成 PXE 部署的集群可直接通过 UI 手动录入节点信息，无需再走 PXE 流程，实现组网图和后续监控功能。

**涉及文件**：
- `backend/api/nodes.py` — `NodeCreate` 补充 `os_version / cpu_cores / memory_gb / disk_gb`；`NodeUpdate` 补全所有 MAC 字段和 `data_protocol`（原缺失）
- `frontend/src/views/Nodes.vue` — 重写，新增以下能力：

**前端变更详情**：

| 变更点 | 说明 |
|--------|------|
| 新增节点按钮 | 表头右侧新增"新增节点"按钮，打开空白表单 |
| 编辑/删除按钮 | 操作列新增"编辑"（主色）和"删除"（红色）按钮，删除带二次确认弹窗 |
| 新增/编辑对话框 | 700px 宽，按五个区块组织：基本信息 / 管理面 / 控制面 / 数据面 / 硬件信息 |
| 节点类型扩展 | 筛选下拉和表单选项新增 SubSwath、GStorage、Sensor |
| 角色副标题 | 类型列在 Tag 下方显示 `role` 字段内容 |
| 类型色彩区分 | Master=红、Slave=蓝、SubSwath=橙、GStorage=绿 |
| 空值处理 | 保存时空字符串自动转 `null`，避免覆盖已有数据 |

---

### 2026-05-05 — build.sh 改为生产自包含包（无需在生产机安装依赖）

**背景**：生产机应该零依赖，直接解压运行，不允许执行 pip install。

**涉及文件**：
- `build.sh` — 重写：PyInstaller 打包 + 手动复制 `static/` + 输出 `tar.gz`
- `backend/cluster_manager.spec` — 移除 `datas` 中的 `static/`（改为 build.sh 手动复制，避免 `sys._MEIPASS` 路径混淆）

**生产机部署步骤**（三行命令）：
```bash
tar -xzf cluster-manager-linux-arm64.tar.gz
./cluster-manager/start.sh          # 直接运行
# 或
./cluster-manager/install-service.sh # 注册开机自启
```

---

### 2026-05-05 — 跨平台部署支持（Windows 构建 → Linux ARM 部署）

**背景**：PyInstaller 不支持交叉编译，需提供可在 Windows 上构建、Linux ARM 上部署的方案。

**涉及文件**：
- `backend/config.py` — 新增 `CLUSTER_MANAGER_DATA` 环境变量支持（Docker 数据目录）
- `build.bat` — **新建**：Windows 一键构建脚本（前端 build + 打包 ZIP）
- `deploy.sh` — **新建**：Linux ARM 部署脚本（pip install + systemd 注册）
- `Dockerfile` — **新建**：多阶段构建，支持 `linux/arm64` 和 `linux/amd64`
- `docker-compose.yml` — **新建**：Docker 部署配置，volume 持久化数据
- `.dockerignore` — **新建**：排除 node_modules 等大文件

**三种部署路径**：
1. **Windows build.bat → ZIP → ARM deploy.sh**（推荐，无需 Docker）
2. **Windows docker buildx → ARM docker compose**（标准化，需 Docker）
3. **ARM 本地 build.sh**（最简单，全部在 ARM 上完成）

---

### 2026-05-05 — 生产部署打包支持（PyInstaller + 前端内嵌）

**背景**：将系统部署到 OpenEuler ARM 服务器，Windows 桌面通过浏览器访问。

**涉及文件**：
- `backend/config.py` — **新建**：统一路径解析，兼容开发模式和 PyInstaller 打包运行
- `backend/models/node.py` — DATABASE_URL 改用 `config.DATABASE_PATH`，路径跟随可执行文件
- `backend/services/pxe_service.py` — nodes.json 路径改用 `config.PXE_DATA_DIR`
- `backend/main.py` — 新增 Vue 静态文件挂载（SPA 路由 catch-all）+ `__main__` 入口
- `frontend/vite.config.js` — `build.outDir` 设为 `../backend/static`
- `backend/cluster_manager.spec` — **新建**：PyInstaller onedir 打包配置
- `build.sh` — **新建**：一键构建脚本（前端 build + PyInstaller）
- `cluster-manager.service` — **新建**：systemd 自启服务模板

**部署流程**：
1. `./build.sh` → 输出 `backend/dist/cluster-manager/`
2. 复制到 ARM 服务器 `/opt/cluster-manager/`
3. `./start.sh` 或 `systemctl enable --now cluster-manager`
4. Windows 浏览器访问 `http://<arm-ip>:8000`

---

### 2026-05-05 — PXE 模块 v2（对应部署方案 v2）

**背景**：依据新 SVG 组网图重新设计，从旧方案（23 节点、192.168.x.x）迁移到新方案（22 节点、172.16.x.x 三平面物理隔离）。

**涉及文件**：
- `backend/services/pxe_service.py` — 完整重写
- `backend/api/pxe.py` — 新增 v2 端点
- `backend/main.py` — 补充迁移列
- `backend/models/seed.py` — 更新默认 PXE 配置子网
- `frontend/src/views/PXEDeploy.vue` — 重构为 5 标签页

**主要变更**：

| 维度 | 旧值（v1） | 新值（v2） |
|------|-----------|-----------|
| 集群规模 | Master×7 等 | Master×6 + Slave×12 + SubSwath×2 + GStorage×1 |
| 管理面子网 | `192.168.x.x` | `172.16.0.0/24` |
| 控制面子网 | `10.0.0.x` | `172.16.3.0/24` |
| 数据面 | 单子网 | DPDK-1/2 + RDMA-1/2 四个 100GE 子网 |
| 系统盘 | 各角色不同 | 全角色统一 2×960G 硬件 RAID1 → `/dev/sda` |
| SubSwath 数据盘 | 无 | 4×7.68T NVMe 软件 RAID10（mdadm） |
| GStorage 数据盘 | 无 | 机械盘硬件 RAID50（BMC 预配置） |
| 部署方式 | Kickstart | base.tar.zst + firstboot 差异化注入 |
| 引导配置 | pxelinux | grubaa64.efi（aarch64 UEFI） |
| 节点配置载体 | 数据库字段 | `pxe_data/nodes.json`（MAC→配置映射） |

**新增后端端点**（均挂载在 `/api/pxe/`）：

- `POST /network-plan` — 六子网 IP 规划（支持四角色数量参数）
- `GET/POST /nodes-json` — nodes.json 读写
- `GET /nodes-json/node-list` — 前端表格展示用节点列表
- `PATCH /nodes-json/update-mac` — 在线替换节点 MAC 地址
- `GET /node-env?mac=` — 返回 shell 变量文本，firstboot detect.sh 调用
- `GET /dhcp-config` — 生成 dhcpd.conf（含 ARM64 UEFI class 规则）
- `GET /grub-config` — 生成 grub.cfg（`pxe_server=172.16.3.10`）
- `GET /setup-raid1-script` — 批量 Redfish 建 RAID1 脚本
- `GET /pxe-boot-script` — 批量 ipmitool PXE 启动脚本

**前端重构**（`PXEDeploy.vue`）：

| 标签页 | 内容 |
|--------|------|
| IP 规划 | v2 六子网规划，四角色分表，一键应用到 nodes.json |
| 节点配置 | 22 节点表格，MAC 在线编辑（替换占位符） |
| 配置生成 | dhcpd.conf / grub.cfg / RAID1 脚本 / PXE 脚本，一键生成 + 复制 |
| 分批部署 | 三批卡片（存储→Master→Slave），含耗时估计和就绪验证命令 |
| 状态监控 | BMC 扫描、单节点部署、部署任务进度 |
