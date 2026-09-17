# PXE 模块简化方案

> 状态：草案（待评审）
> 目标痛点：**调试困难** + **概念难理解**
> 不做大重构，仅做四次外科手术式精简，每步独立可回滚

---

## 目录

1. [现状诊断：为什么难理解？](#一现状诊断为什么难理解)
2. [现状诊断：为什么难调试？](#二现状诊断为什么难调试)
3. [目标架构（精简后）](#三目标架构精简后)
4. [简化路线图（四刀）](#四简化路线图四刀)
5. [调试中心方案（独立改进）](#五调试中心方案独立改进)
6. [执行顺序与检查点](#六执行顺序与检查点)
7. [风险与回滚策略](#七风险与回滚策略)

---

## 一、现状诊断：为什么难理解？

### 1.1 数据存了 4 个地方，职责重叠

```
┌────────────────────────────────────────────────────────┐
│ 当前数据存储分布                                            │
├────────────────────────────────────────────────────────┤
│                                                            │
│   ┌─ nodes.json ─────────────┐    ◄ 真源（节点规划）        │
│   │  hostname / role / IP    │                            │
│   │  ctrl_nic / dpdk_nics    │                            │
│   │  rdma_ips / hugepages    │                            │
│   └──────────────┬───────────┘                            │
│                  │ _sync_nodes_json_to_db_impl (100+ 行)   │
│                  ▼                                         │
│   ┌─ DB.nodes ───────────────┐    ◄ 派生（同时也是真源？）   │
│   │  hostname / status       │                            │
│   │  rdma_ips / dpdk_ips     │  ← 同步过来的镜像             │
│   │  last_seen / online      │  ← 这才是 DB 应该独占的       │
│   └──────────────────────────┘                            │
│                                                            │
│   ┌─ pxe_host.json ──────────┐    ◄ PXE 服务器自身配置       │
│   │  bmc_ip / iso_filename   │     为什么和 nodes.json 分开？│
│   └──────────────────────────┘                            │
│                                                            │
│   ┌─ DB.pxe_config ──────────┐    ◄ 死表（无人读取）        │
│   │  mgmt_subnet / dns       │     被 nodes.json 替代了    │
│   └──────────────────────────┘                            │
└────────────────────────────────────────────────────────┘
```

**根因**：项目演进中"加表"比"删表"容易，新方案上线但旧方案没退场。

### 1.2 两套部署实现并存

| 实现 | 文件 | 行数 | 状态 |
|------|------|------|------|
| **方案 A：firstboot（v2 主推）** | `pxe_service.py` | 459 | 前端在用 |
| **方案 B：Kickstart（v1 遗留）** | `pxe_service_enhanced.py` | 554 | 没人调用 |

新人来一看，`pxe_service` 和 `pxe_service_enhanced` 名字相似度 90%，第一反应是 "enhanced 是改进版应该用这个"，结果点了半天发现前端根本没接，浪费一上午。

### 1.3 MAC 占位符流程反直觉

当前流程：

```
用户输入"6 个 master"
    ↓
后端生成 6 条占位记录: aa:bb:cc:11:00:01, aa:bb:cc:11:00:02 ...
    ↓
用户去机房抄真 MAC: 用 dmidecode / 看标签
    ↓
回到 UI 一条条点"替换 MAC"
    ↓
PATCH /nodes-json/update-mac × 6 次
```

中间夹了一层"假 MAC"的概念，纯粹是为了让 nodes.json 的 key 能先占住位置。新人不理解为什么要有占位符。

---

## 二、现状诊断：为什么难调试？

PXE 装机失败时，问题可能出在 5 个不同位置，但日志散落在 5 个地方：

| 阶段 | 失败现象 | 日志位置 | 你现在怎么查？ |
|---|---|---|---|
| 1. DHCP DISCOVER | 节点起不来，黑屏 | PXE Host `/var/log/messages` | SSH 进 PXE Host `tail -f` |
| 2. TFTP 传 grub.efi | 节点显示 "TFTP timeout" | PXE Host xinetd 日志 | SSH 进去 grep tftp |
| 3. GRUB 加载 kernel | 节点显示 "file not found" | 节点屏幕（无远程日志） | 看 BMC 远程控制台 |
| 4. firstboot 执行 | 节点装完没注册回来 | 节点 `/var/log/cluster-firstboot.log` | SSH 进节点查（前提是网络通） |
| 5. Redfish 挂载 ISO | "Insert media failed" | backend uvicorn 日志 | 看 backend 控制台 |

**这正是用户反馈"调试困难"的根源** — 不是工具不够，而是**没有聚合视图**。

---

## 三、目标架构（精简后）

### 3.1 数据职责重新划分

```
┌────────────────────────────────────────────────────────┐
│ 目标数据存储                                                │
├────────────────────────────────────────────────────────┤
│                                                            │
│   ┌─ nodes.json ─────────────┐    ◄ 唯一规划真源            │
│   │  _pxe_host: {...}        │      含 PXE Host 配置        │
│   │  _subnets: {...}         │      含子网配置（替代 PXEConfig）│
│   │  nodes: {                │                            │
│   │    "<mac>": {            │                            │
│   │       hostname / role    │                            │
│   │       ips / nics / disks │                            │
│   │    }                     │                            │
│   │  }                       │                            │
│   └──────────────────────────┘                            │
│                                                            │
│   ┌─ DB.nodes ───────────────┐    ◄ 仅运行时状态            │
│   │  hostname (PK)           │                            │
│   │  status / last_seen      │      心跳/在线监控用          │
│   │  ctrl_status / data_status│                           │
│   └──────────────────────────┘                            │
│                                                            │
│   删除：pxe_host.json (并入 nodes.json._pxe_host)           │
│   删除：DB.pxe_config 表 (并入 nodes.json._subnets)         │
│                                                            │
└────────────────────────────────────────────────────────┘
```

### 3.2 心智模型一句话总结

> **nodes.json = "应该是什么样" · DB = "现在是什么样"**

只要记住这一句，所有数据存哪里就不再纠结。

### 3.3 部署链路收敛为单一方案

删除 Kickstart 方案，只保留 firstboot：

```
PXE Host 启动 → DHCP → TFTP → GRUB → 拉 base.tar.zst →
firstboot 读 nodes.json → 按 MAC 匹配 → 应用差异化配置 → 注册回 backend
```

---

## 四、简化路线图（四刀）

### 🥇 第一刀：删除 Kickstart 方案

**改动范围**

| 文件 | 操作 | 影响 |
|---|---|---|
| `backend/services/pxe_service_enhanced.py` | 整文件删除 | -554 行 |
| `backend/api/pxe.py` | 搜索引用确认无人 import | 预期 0 处 |
| `backend/services/__init__.py` | 移除 export（如有） | 1 行 |
| 前端 | 无影响 | 0 |

**风险**：极低。该文件不在 import 链上。

**回滚**：`git revert` 一次即可。

**预期收益**：减 554 行；新人不再混淆"用哪个"。

---

### 🥈 第二刀：删除 PXEConfig 表与 v2 派生字段

**当前问题**：

```python
# models/node.py 中 Node 表里这些字段
rdma_nics      # 派生自 nodes.json
rdma_ips       # 派生自 nodes.json
dpdk_nics      # 派生自 nodes.json
dpdk_ips       # 派生自 nodes.json
hugepages_1g   # 派生自 nodes.json
system_disk    # 派生自 nodes.json
data_disks     # 派生自 nodes.json
data_raid_level # 派生自 nodes.json
nfs_mounts     # 派生自 nodes.json
nfs_export_ip  # 派生自 nodes.json
nfs_exports    # 派生自 nodes.json
extra_pkgs     # 派生自 nodes.json
```

这 12 个字段都是 nodes.json 的镜像，存 DB 没意义 —— 要看就直接读 nodes.json，要修改也只能改 nodes.json。

**改动范围**

| 文件 | 操作 | 影响 |
|---|---|---|
| `models/node.py` | 删除 Node 表中 12 个 v2 字段；删除 PXEConfig 类 | -30 行 |
| `models/seed.py` | 删除 PXEConfig 种子数据 | -15 行 |
| `api/pxe.py` | 删除 `/configs`、`/config` 两个端点；简化 `_sync_nodes_json_to_db_impl` | -100 行 |
| `api/nodes.py` | 检查是否暴露这些字段，删掉对应字段 | 可能 -10 行 |
| `main.py` | 加 SQLite 迁移：DROP TABLE pxe_config + ALTER TABLE 删列 | +10 行 |
| `frontend/PXEDeploy.vue` | 节点表如果展示这些字段，改为从 nodes.json 读 | 视情况 |

**风险**：中。涉及表结构变更。

**回滚**：保留旧库备份；改回 model 重启即可。

**预期收益**：减 100+ 行同步代码；数据流图从 4 个箭头降到 1 个。

---

### 🥉 第三刀：合并 pxe_host.json 进 nodes.json

**改造前**：

```
backend/data/
├── nodes.json        ← 节点规划
└── pxe_host.json     ← PXE Host BMC/ISO 配置
```

**改造后**：

```
backend/data/
└── nodes.json        ← 统一存储
    ├── _meta: { version: 2, updated_at: ... }
    ├── _pxe_host: { bmc_ip, iso_filename, ... }  ← 内嵌
    ├── _subnets: { mgmt: ..., ctrl: ..., ... }   ← 内嵌
    └── nodes: { "<mac>": {...} }
```

**改动范围**

| 文件 | 操作 | 影响 |
|---|---|---|
| `services/pxe_service.py` | `read_pxe_host_config` / `write_pxe_host_config` 改读 nodes.json 的 `_pxe_host` 节 | -20 行 |
| 启动迁移脚本 | 自动把现有 pxe_host.json 内容合并进 nodes.json | +30 行 |
| 文档 | 更新 nodes.json 数据结构示例 | 文档变更 |

**风险**：低。逻辑上更清晰。

**回滚**：迁移脚本写成幂等，反向迁移也可还原。

**预期收益**：少一个配置文件；理解成本下降。

---

### 🏅 第四刀：拆分 PXEDeploy.vue

**当前**：一个 1500 行的 Vue 文件，6 个 Tab。

**目标**：

```
frontend/src/views/pxe/
├── PXEDeploy.vue           ← 主容器，仅放 el-tabs + 路由
├── tabs/
│   ├── PlanningTab.vue     ← "IP规划" + "节点配置" 合并
│   ├── PxeHostTab.vue      ← "部署配置"
│   ├── ConfigGenTab.vue    ← "配置生成"
│   ├── DeploymentTab.vue   ← "部署执行" + 新增"调试中心"
│   └── ToolsTab.vue        ← "工具"
└── composables/
    ├── useNodes.js         ← nodes.json CRUD 逻辑
    └── useDeploy.js        ← 部署状态轮询
```

**改动范围**：纯前端，后端零改动。

**风险**：低（结构调整，行为不变）。

**预期收益**：每个文件 < 400 行；多人协作时不抢同一文件。

---

## 五、调试中心方案（独立改进）

> 这是针对"调试困难"的核心改进，**优先级建议在第二刀之后立即做**

### 5.1 新增页面：PXE 部署调试中心

在"部署执行" Tab 下增加子页签 **「调试时间线」**。

### 5.2 调试时间线视图

按节点维度，展示部署各阶段的时间轴：

```
节点：master-01 (172.16.3.11, MAC: 6c:92:bf:11:00:01)

🕐 14:23:01  DHCP DISCOVER          ✓  lease 172.16.3.11
🕐 14:23:03  TFTP REQUEST grub.efi  ✓  2.3 MB
🕐 14:23:04  TFTP REQUEST grub.cfg  ✓  1.2 KB
🕐 14:23:08  HTTP GET base.tar.zst  ✓  450 MB / 4.2s
🕐 14:23:15  firstboot heartbeat #1 ✓  stage=detect
🕐 14:23:42  firstboot heartbeat #2 ✓  stage=network
🕐 14:24:08  firstboot heartbeat #3 ✓  stage=disk_init
🕐 14:24:35  firstboot heartbeat #4 ✓  stage=finalize
🕐 14:24:40  REGISTER from node     ✓  status=online
✅ 部署完成 (用时 1m39s)
```

或失败示例：

```
节点：slave-07 (...)

🕐 14:23:01  DHCP DISCOVER          ✓
🕐 14:23:03  TFTP REQUEST grub.efi  ✓
🕐 14:23:04  TFTP REQUEST grub.cfg  ❌ file not found
   └─ 建议：检查 /tftpboot/grub.cfg 是否存在
            或运行"重新生成 grub.cfg"

⛔ 部署中断
```

### 5.3 实现方案

| 数据源 | 采集方式 | 后端实现 |
|---|---|---|
| DHCP leases | 解析 `/var/lib/dhcpd/dhcpd.leases` | 定时扫描，写入新表 `pxe_deploy_events` |
| TFTP requests | 解析 `/var/log/messages` 中 tftp 相关行 | tail + 正则提取 |
| HTTP base.tar.zst | nginx access.log（按节点 IP 过滤） | tail + 正则提取 |
| firstboot 心跳 | 节点上 firstboot 脚本主动 POST 到 backend | 新增 `POST /api/pxe/heartbeat` 端点 |
| 节点注册 | 现有 `POST /api/nodes` 注册端点 | 已存在 |

**新增数据表**：

```sql
CREATE TABLE pxe_deploy_events (
  id INTEGER PRIMARY KEY,
  node_mac VARCHAR(20),
  node_hostname VARCHAR(50),
  stage VARCHAR(30),    -- dhcp / tftp / http / firstboot / register
  detail TEXT,
  success BOOLEAN,
  occurred_at DATETIME
);
```

**新增端点**：

```
GET  /api/pxe/deploy-events?hostname=master-01  → 时间线数据
POST /api/pxe/heartbeat                          → 节点主动上报
GET  /api/pxe/deploy-events/summary              → 全节点状态聚合
```

### 5.4 预期效果

排查失败用例的耗时变化：

| 操作 | 改造前 | 改造后 |
|---|---|---|
| 定位失败阶段 | 5~15 分钟 | < 10 秒 |
| 查看节点对应日志 | 需要 SSH 3~5 台机器 | 一个页面 |
| 重试单个节点 | 命令行手动操作 | 按钮一键 |

---

## 六、执行顺序与检查点

### 6.1 推荐顺序（按风险递增）

```
Day 1  ─┐
Day 2  ─┤  第一刀（删 enhanced）→ 提交 → 测试无回归  ✓ 检查点1
Day 3  ─┘
        │
Day 4  ─┐
Day 5  ─┤  第三刀（合并 pxe_host.json）→ 提交 → 验证读写  ✓ 检查点2
Day 6  ─┘
        │
Day 7  ─┐
Day 8  ─┤  调试中心后端（数据采集 + 端点）→ 提交  ✓ 检查点3
Day 9  ─┘
        │
Day 10 ─┐
Day 11 ─┤  调试中心前端时间线 → 提交  ✓ 检查点4
Day 12 ─┘
        │
Day 13 ─┐
Day 14 ─┤  第四刀（拆 Vue 文件）→ 提交  ✓ 检查点5
Day 15 ─┘
        │
Day 16 ─┐
Day 17 ─┤  第二刀（删 PXEConfig + v2 字段）→ 数据库迁移 → 全量测试  ✓ 检查点6
Day 18 ─┘
```

**第二刀放最后**：因为涉及 DB schema 变更，风险最高，放在所有上游改动稳定后再做。

### 6.2 每个检查点的验收标准

| 检查点 | 验收项 |
|---|---|
| ✓1 | `grep enhanced backend/` 无结果；前端所有 PXE 功能正常 |
| ✓2 | 现有 pxe_host.json 字段在 nodes.json._pxe_host 下可读可写 |
| ✓3 | `POST /api/pxe/heartbeat` 可接收；`pxe_deploy_events` 有新增数据 |
| ✓4 | 调试中心页面能看到至少一个节点的完整时间线 |
| ✓5 | 拆分后所有 Tab 行为与原版一致；每个文件 < 500 行 |
| ✓6 | 全量部署一遍 6+12+2+1 节点，DB 中无 v2 字段；功能正常 |

---

## 七、风险与回滚策略

### 7.1 风险矩阵

| 改动 | 风险等级 | 主要风险 | 缓解措施 |
|---|---|---|---|
| 第一刀（删 enhanced） | 🟢 极低 | 误删被引用代码 | 提交前全工程 grep `enhanced` |
| 第二刀（删表+字段） | 🔴 高 | DB 迁移失败、字段被遗漏使用 | 备份数据库；编写迁移测试 |
| 第三刀（合并 json） | 🟡 中 | 迁移期间数据丢失 | 迁移脚本幂等；保留旧 pxe_host.json 7 天 |
| 第四刀（拆 Vue） | 🟢 低 | Tab 切换状态丢失 | 用 composable 集中状态 |
| 调试中心 | 🟡 中 | 日志解析正则错误 | 增加单元测试覆盖正则 |

### 7.2 通用回滚原则

1. **每刀单独提交**，确保 `git revert` 粒度可控
2. **数据库改动前必备份**：`cp cluster_manager.db cluster_manager.db.before-cutN`
3. **迁移脚本必幂等**：可重复执行不出错
4. **生产环境部署窗口**：第二刀和第三刀只在维护窗口执行
5. **保留旧实现 1 个版本**：先标 deprecated，下个版本再彻底删

---

## 八、不在本次范围

明确不做的事，避免范围蔓延：

- ❌ 不替换 ORM / 不引入新框架
- ❌ 不重写 firstboot 脚本逻辑
- ❌ 不改六子网 IP 规划方案
- ❌ 不引入 K8s/Terraform 等新工具
- ❌ 不重做 UI 设计风格

---

## 九、总成果预估

| 指标 | 当前 | 简化后 | 变化 |
|---|---|---|---|
| 后端代码行数 | ~1800 | ~1100 | **-700 行** |
| 数据存储位置数 | 4 个 | 2 个 | **-50%** |
| 前端单文件最大行数 | 1500 | 400 | **-73%** |
| 部署失败定位耗时 | 5~15 分钟 | < 1 分钟 | **-90%** |
| 新人上手时间（估） | 2 天 | 0.5 天 | **-75%** |

---

## 十、等你拍板

请回复：

- **OK，按这个文档执行**：我先做第一刀
- **方案再调整**：哪一刀需要改？例如"第二刀风险太高先不做"
- **优先级换序**：例如"先做调试中心，简化等下个迭代"

收到指示后我开始第一步动手。
