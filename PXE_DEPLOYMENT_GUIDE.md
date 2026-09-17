# PXE集群自动化部署完整指南

## 目录
1. [系统架构概述](#系统架构概述)
2. [PXE部署流程](#pxe部署流程)
3. [代码模块分析](#代码模块分析)
4. [优化建议](#优化建议)
5. [完整操作步骤](#完整操作步骤)
6. [故障排查](#故障排查)

---

## 系统架构概述

### 三平面网络架构

```
┌─────────────────────────────────────────────────────┐
│                  Cluster Manager PXE                 │
│                  (192.168.1.10)                      │
└─────────────────────────────────────────────────────┘
     │                    │                    │
     │ 管理面(GE)       │ 控制面(10GE)      │ 数据面(100GE)
     │ eth0              │ eth1              │ eth2
     │                    │                    │
  ┌──┴────────┬──────────┴────────┬──────────┴──┐
  │            │                    │              │
Master-1    Master-N           Slave-1        Slave-N
(DPDK)       (DPDK)            (RDMA)         (RDMA)
  │            │                    │              │
  └────────────┴────────────────────┴──────────────┘
        所有节点通过PXE启动并自动部署
```

### 服务栈
| 服务 | 功能 | 端口 |
|------|------|------|
| TFTP | 启动镜像和kickstart配置传输 | 69(UDP) |
| DHCP | IP分配和PXE引导配置 | 67(UDP) |
| NFS | 系统镜像和数据共享 | 2049(TCP) |
| HTTP | 安装源和Agent下载 | 80/8000 |
| API | 部署状态和节点管理 | 8000 |

---

## PXE部署流程

### 1. 服务器端流程

```
┌──────────────────────────────────────────────────────┐
│ 第0步: PXE服务器准备                                 │
├──────────────────────────────────────────────────────┤
│ ✓ 运行 pxe_setup.sh                                 │
│ ✓ 安装: TFTP, DHCP, NFS, HTTP服务                  │
│ ✓ 配置TFTP目录和NFS共享                            │
│ ✓ 准备openEuler启动文件 (vmlinuz, initrd.img)     │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第1步: 配置PXE环境                                   │
├──────────────────────────────────────────────────────┤
│ POST /api/pxe/config                                 │
│ {                                                     │
│   "name": "Cluster-V1",                             │
│   "mgmt_subnet": "192.168.1.0/24",                 │
│   "ctrl_subnet": "10.0.0.0/24",                    │
│   "data_subnet": "192.168.100.0/24",               │
│   "mgmt_gateway": "192.168.1.1",                   │
│   "ctrl_gateway": "10.0.0.1",                      │
│   "data_gateway": "192.168.100.1",                 │
│   "dns_servers": "8.8.8.8,8.8.4.4"                │
│ }                                                    │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第2步: 规划网络IP分配                                 │
├──────────────────────────────────────────────────────┤
│ POST /api/pxe/network-plan                          │
│ {                                                     │
│   "config_id": 1,                                    │
│   "master_count": 1,                                │
│   "slave_count": 5,                                 │
│   "mgmt_ip_start": "192.168.1.100",                │
│   "ctrl_ip_start": "10.0.0.100",                   │
│   "data_ip_start": "192.168.100.100"               │
│ }                                                    │
│                                                      │
│ 响应: 自动分配Master-1/Slave-1~5的三平面IP         │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第3步: 生成Kickstart配置                             │
├──────────────────────────────────────────────────────┤
│ 对每个节点调用 generate_kickstart():                │
│ - Master节点: DPDK配置 (100GE直通)                 │
│ - Slave节点: RDMA配置 (高性能低延迟)               │
│ - 配置三平面网络 (eth0/eth1/eth2)                   │
│ - 自动安装必要软件包和Agent                        │
│ - 节点启动后自动注册到管理平台                      │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第4步: 部署节点                                       │
├──────────────────────────────────────────────────────┤
│ POST /api/pxe/nodes/{node_id}/deploy              │
│ 或 POST /api/pxe/batch-deploy (批量)               │
│                                                      │
│ - 更新节点配置到数据库                              │
│ - 节点启动时向DHCP请求IP                           │
│ - DHCP返回PXE引导配置                              │
│ - 节点加载启动文件并执行Kickstart                   │
└──────────────────────────────────────────────────────┘
```

### 2. 客户端启动流程 (单个节点)

```
┌──────────────────────────────────────────────────────┐
│ 第1步: PXE启动                                        │
├──────────────────────────────────────────────────────┤
│ ✓ 节点冷启 → 网卡PXE启动 (设置为第一启动项)         │
│ ✓ 节点发送DHCP Discover请求                        │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第2步: DHCP分配IP                                    │
├──────────────────────────────────────────────────────┤
│ ✓ DHCP服务器返回:                                   │
│   - 节点IP (按MAC地址固定分配)                      │
│   - next-server (PXE服务器IP)                      │
│   - filename (pxelinux.0)                           │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第3步: TFTP下载启动文件                              │
├──────────────────────────────────────────────────────┤
│ ✓ 从PXE服务器TFTP下载:                             │
│   - pxelinux.0 (PXE bootloader)                    │
│   - ldlinux.c32 (PXE模块)                          │
│   - pxelinux.cfg/01-xx-xx-xx-xx-xx-xx (配置文件) │
│   - vmlinuz (内核)                                  │
│   - initrd.img (初始化磁盘)                         │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第4步: 启动内核                                       │
├──────────────────────────────────────────────────────┤
│ ✓ pxelinux加载vmlinuz和initrd.img                 │
│ ✓ 内核启动参数包含Kickstart配置位置:              │
│   inst.ks=http://PXE_SERVER:8000/ks/master-1.ks  │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第5步: Anaconda安装                                  │
├──────────────────────────────────────────────────────┤
│ ✓ Anaconda读取Kickstart配置                        │
│ ✓ 无人值守安装过程:                                 │
│   1. 配置三平面网络 (eth0/eth1/eth2)               │
│   2. 分配磁盘并创建LVM                             │
│   3. 安装系统和软件包 (DPDK/RDMA)                 │
│   4. 执行后置脚本 (%post)                          │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第6步: 后置配置 (%post脚本)                          │
├──────────────────────────────────────────────────────┤
│ Master节点:                                           │
│  ✓ 加载VFIO/VFIO-PCI内核模块                       │
│  ✓ 配置IOMMU (Intel: intel_iommu=on iommu=pt)    │
│  ✓ DPDK网卡绑定准备                                │
│  ✓ 安装监控Agent                                    │
│                                                      │
│ Slave节点:                                           │
│  ✓ 加载RDMA内核模块 (ib_core, rdma_cm等)          │
│  ✓ 配置RDMA网卡                                    │
│  ✓ 配置RDMA连接参数到Master                        │
│  ✓ 安装监控Agent (--slave模式)                     │
│                                                      │
│ 通用:                                                │
│  ✓ 注册到管理平台 (/api/nodes/register)           │
│  ✓ 配置心跳服务 (每10秒发送一次)                   │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│ 第7步: 重启并进入生产                                 │
├──────────────────────────────────────────────────────┤
│ ✓ 系统自动重启                                       │
│ ✓ 启动顺序: 本地磁盘启动 (不走PXE)                 │
│ ✓ 完成心跳注册: 节点状态 = "online"               │
│ ✓ 可开始工作负载                                     │
└──────────────────────────────────────────────────────┘
```

---

## 代码模块分析

### 模块1: PXEService (核心配置生成)

**文件**: `backend/services/pxe_service.py`

#### 功能分解
```python
PXEService
├── setup_pxe_server()          # 返回PXE服务器配置步骤
├── generate_kickstart()        # 🔥 核心: 生成自动化安装配置
├── generate_dhcp_config()      # 生成DHCP配置 (固定IP分配)
├── create_pxe_boot_entry()     # 创建单个节点PXE启动配置
└── prepare_boot_files()        # 列出所需的启动文件
```

#### 当前问题分析
| 问题 | 影响 | 优先级 |
|------|------|--------|
| `generate_kickstart()` 硬编码IP地址 | 不支持自定义子网 | 高 |
| 未生成实际Kickstart文件到TFTP | 只返回文本, 无法实际使用 | 高 |
| 缺少模板变量验证 | {{MGMT_IP}}等变量可能未替换 | 高 |
| 无错误处理和日志 | 难以调试失败原因 | 中 |
| Kickstart参数硬编码 | root密码明文, 无法自定义 | 中 |

---

### 模块2: PXE API (部署接口)

**文件**: `backend/api/pxe.py`

#### 功能分解
```python
/api/pxe/
├── GET  /configs              # 获取所有PXE配置
├── POST /config               # 创建PXE配置
├── POST /network-plan         # 🔥 智能: IP规划
├── POST /nodes/{id}/deploy    # 单个节点部署
├── POST /batch-deploy         # 批量部署
├── GET  /status               # 部署状态查询
└── GET  /kickstart/{type}     # 获取Kickstart模板
```

#### 当前问题分析
| 问题 | 影响 | 优先级 |
|------|------|--------|
| `/network-plan` 中IP分配有bug | Master从start+1开始，计算不准确 | 高 |
| 部署任务后台执行被注释 | 部署其实没执行 | 高 |
| 进度条固定值(50%) | 无法知道真实进度 | 中 |
| 缺少部署前检查 | 无法验证节点配置合法性 | 中 |
| Kickstart动态生成未调用 | 实际不生成真实配置文件 | 高 |

---

### 模块3: Kickstart模板 (自动安装配置)

**文件**: `pxe/kickstart/master.ks`, `slave.ks`

#### 优势
- ✅ 三平面网络配置完整
- ✅ 支持DPDK和RDMA配置
- ✅ 后置脚本自动注册
- ✅ 心跳配置预留

#### 问题
| 问题 | 影响 |
|------|------|
| 大量{{PLACEHOLDER}}变量 | 需要动态替换, 未实现 |
| GRUB配置脚本有错误 | `sed`命令格式不对 |
| DPDK网卡绑定被注释 | 实际未执行绑定 |
| Agent安装路径硬编码 | `/opt/cluster-agent` 无标准化 |

---

## 优化建议

### 优化1: 完善PXEService - 实现真实文件生成

```python
# 增强功能
class PXEService:
    def save_kickstart_file(self, hostname: str, ks_content: str) -> str:
        """保存kickstart文件到TFTP目录并返回URL"""
        # 生成文件到: /tftpboot/ks/{hostname}.ks
        # 返回访问URL: http://192.168.1.10:8000/ks/{hostname}.ks
        pass
    
    def validate_kickstart(self, ks_content: str) -> Dict:
        """验证Kickstart配置的语法和逻辑"""
        pass
    
    def generate_pxe_config(self, hostname: str, mac: str, ks_url: str) -> str:
        """生成实际的pxelinux.cfg/01-xx-xx-xx-xx-xx-xx配置"""
        pass
    
    def write_dhcp_config(self) -> bool:
        """直接写入/etc/dhcp/dhcpd.conf并重启服务"""
        pass
    
    def reload_services(self) -> Dict:
        """重新加载DHCP和TFTP服务"""
        pass
```

### 优化2: 修复IP分配算法

```python
# 当前bug:
for i in range(request.master_count):
    idx = i + 1
    mgmt_ip = f"{mgmt_base}.{mgmt_start + idx}"  # 从start+1开始是对的

# 问题在Slave节点:
for i in range(request.slave_count):
    idx = request.master_count + i + 1  # 这里重复加1了!
    # 应该是:
    # idx = request.master_count + i

# 修正:
master_ips = []
for i in range(request.master_count):
    master_ips.append(mgmt_start + i)

slave_ips = []
for i in range(request.slave_count):
    slave_ips.append(mgmt_start + request.master_count + i)
```

### 优化3: 实现真实部署流程

```python
# 启用后台任务
async def deploy_node(node_id, request, background_tasks, db):
    # ...
    # 当前被注释的代码需要启用:
    background_tasks.add_task(run_deployment, node_id, request)
    # 实现run_deployment函数
    pass

async def run_deployment(node_id, request, db):
    """实际执行部署的后台任务"""
    try:
        node = db.query(Node).get(node_id)
        
        # 1. 更新状态为discovering
        node.status = "discovering"
        db.commit()
        
        # 2. 生成Kickstart配置
        ks_content = pxe_service.generate_kickstart(
            node_type=request.node_type,
            mgmt_ip=request.mgmt_ip,
            ctrl_ip=request.ctrl_ip,
            data_ip=request.data_ip,
            hostname=request.hostname
        )
        
        # 3. 保存到TFTP
        ks_url = pxe_service.save_kickstart_file(
            request.hostname, ks_content
        )
        
        # 4. 生成PXE启动配置
        pxe_cfg = pxe_service.create_pxe_boot_entry(
            request.hostname, node.mgmt_mac, ks_url
        )
        
        # 5. 写入TFTP目录
        pxe_service.write_pxe_config(pxe_cfg)
        
        # 6. 更新状态为installing
        node.status = "installing"
        db.commit()
        
        # 7. 通过IPMI启动节点
        ipmi_service.power_on(node.bmc_ip)
        
        # 8. 轮询节点状态 (via heartbeat/agent)
        # ... 定期检查直到完成
        
        # 9. 标记为online
        node.status = "online"
        db.commit()
        
    except Exception as e:
        node.status = "error"
        node.error_message = str(e)
        db.commit()
```

### 优化4: 改进Kickstart模板

```bash
# 修复GRUB命令
# 当前错误:
sed -i 's/GRUB_CMDLINE_LINUX="/GRUB_CMDLINE_LINUX="intel_iommu=on iommu=pt /' /etc/default/grub

# 正确做法:
sed -i 's/^GRUB_CMDLINE_LINUX="/GRUB_CMDLINE_LINUX="intel_iommu=on iommu=pt /' /etc/default/grub

# 更优雅的方式:
if ! grep -q "intel_iommu=on" /etc/default/grub; then
    sed -i 's/GRUB_CMDLINE_LINUX="/&intel_iommu=on iommu=pt /' /etc/default/grub
    grub2-mkconfig -o /boot/grub2/grub.cfg
fi

# 启用DPDK网卡绑定
%post --log=/root/ks-dpdk-setup.log
#!/bin/bash
# DPDK网卡绑定脚本 - Master节点
echo "正在绑定数据面网卡到DPDK..."

# 查找100GE网卡 (eth2)
DPDK_DEV="eth2"
DPDK_PCI=$(ethtool -i $DPDK_DEV | grep bus-address | awk '{print $2}')

if [ -n "$DPDK_PCI" ]; then
    echo $DPDK_PCI > /sys/bus/pci/drivers/vfio-pci/bind
    echo "网卡绑定成功: $DPDK_PCI"
else
    echo "网卡绑定失败: 无法获取PCI地址"
fi
%end
```

### 优化5: 增强错误处理和日志

```python
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class PXEService:
    def __init__(self, tftp_dir="/tftpboot", log_dir="/var/log/pxe"):
        self.tftp_dir = tftp_dir
        self.log_dir = log_dir
        self.log_file = f"{log_dir}/pxe-{datetime.now().strftime('%Y%m%d')}.log"
    
    def _log(self, level, msg):
        """记录PXE操作日志"""
        logger.log(level, msg)
        with open(self.log_file, 'a') as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    
    def generate_kickstart(self, **kwargs) -> Dict:
        """
        返回值:
        {
            "success": bool,
            "content": str,
            "errors": [list of validation errors],
            "variables": {validated template variables},
            "file_path": str,
            "url": str
        }
        """
        try:
            # 验证必需参数
            required = ['hostname', 'mgmt_ip', 'ctrl_ip', 'data_ip']
            for key in required:
                if key not in kwargs or not kwargs[key]:
                    return {
                        "success": False,
                        "errors": [f"缺少必需参数: {key}"]
                    }
            
            # 生成内容
            ks_content = self._render_template(**kwargs)
            
            # 保存文件
            file_path = self._save_file(kwargs['hostname'], ks_content)
            
            self._log(logging.INFO, 
                f"成功生成Kickstart: {kwargs['hostname']} -> {file_path}")
            
            return {
                "success": True,
                "content": ks_content,
                "file_path": file_path,
                "url": f"http://192.168.1.10:8000/ks/{kwargs['hostname']}.ks"
            }
        except Exception as e:
            self._log(logging.ERROR, f"生成Kickstart失败: {str(e)}")
            return {
                "success": False,
                "errors": [str(e)]
            }
```

---

## 完整操作步骤

### 第一阶段: 服务器准备 (一次性)

#### 步骤1.1: 执行PXE服务器安装脚本

```bash
# 在PXE服务器上运行 (192.168.1.10)
cd /opt/clustermanager
sudo bash pxe/pxe_setup.sh

# 检查安装结果
systemctl status tftp
systemctl status dhcpd
systemctl status nfs-server

# 检查TFTP目录
ls -la /tftpboot/
# 输出应该包括:
# -rw-r--r-- pxelinux.0
# -rw-r--r-- ldlinux.c32
# drwxr-xr-x pxelinux.cfg/
```

#### 步骤1.2: 准备openEuler启动文件

```bash
# 挂载openEuler ISO (假设为openEuler-22.03-ARM.iso)
sudo mkdir -p /mnt/openeuler
sudo mount -o loop openEuler-22.03-ARM.iso /mnt/openeuler

# 复制启动文件到TFTP
sudo cp /mnt/openeuler/images/pxeboot/vmlinuz /tftpboot/
sudo cp /mnt/openeuler/images/pxeboot/initrd.img /tftpboot/

# 配置HTTP服务器指向安装源
# 编辑 /etc/httpd/conf/httpd.conf 或通过 Alias
sudo ln -s /mnt/openeuler /var/www/html/openEuler

# 重启HTTP服务
sudo systemctl restart httpd

# 验证
curl -I http://192.168.1.10/openEuler/ | head -1
# HTTP/1.1 301 Moved Permanently
```

#### 步骤1.3: 启动Cluster Manager API服务

```bash
cd clustermanager/backend
pip install -r requirements.txt
python main.py
# 输出: Uvicorn running on http://0.0.0.0:8000

# 验证
curl -s http://localhost:8000/api/pxe/configs | jq
# []
```

---

### 第二阶段: 集群规划

#### 步骤2.1: 创建PXE配置

```bash
# API调用
curl -X POST http://192.168.1.10:8000/api/pxe/config \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Cluster-Production-V1",
    "mgmt_subnet": "192.168.1.0/24",
    "ctrl_subnet": "10.0.0.0/24",
    "data_subnet": "192.168.100.0/24",
    "mgmt_gateway": "192.168.1.1",
    "ctrl_gateway": "10.0.0.1",
    "data_gateway": "192.168.100.1",
    "dns_servers": "8.8.8.8,8.8.4.4"
  }'

# 响应:
# {"id": 1, "name": "Cluster-Production-V1", ...}

PXE_CONFIG_ID=1  # 记录config_id
```

#### 步骤2.2: 规划网络IP分配

```bash
# 规划1个Master + 5个Slave的部署
curl -X POST http://192.168.1.10:8000/api/pxe/network-plan \
  -H "Content-Type: application/json" \
  -d '{
    "config_id": 1,
    "master_count": 1,
    "slave_count": 5,
    "mgmt_ip_start": "192.168.1.100",
    "ctrl_ip_start": "10.0.0.100",
    "data_ip_start": "192.168.100.100"
  }'

# 响应:
# {
#   "config_id": 1,
#   "total_nodes": 6,
#   "plan": {
#     "masters": [
#       {
#         "hostname": "master-1",
#         "node_type": "master",
#         "mgmt_ip": "192.168.1.101",
#         "ctrl_ip": "10.0.0.101",
#         "data_ip": "192.168.100.101",
#         "data_protocol": "DPDK",
#         "bmc_ip": "192.168.1.201"
#       }
#     ],
#     "slaves": [
#       {
#         "hostname": "slave-1",
#         "mgmt_ip": "192.168.1.102",
#         ...
#       },
#       ...
#     ]
#   }
# }
```

---

### 第三阶段: 节点注册与部署

#### 步骤3.1: 添加节点到数据库

```bash
# 通过前端或API添加节点 (需要实现Node创建API)
# 关键信息:
# - 节点名称: master-1, slave-1, ..., slave-5
# - MAC地址: (从节点IPMI或预配置获取)
# - BMC IP: 192.168.1.201, 192.168.1.202, ...

# 临时脚本生成节点:
python3 << 'PYTHON'
import requests
import json

PXE_SERVER = "http://192.168.1.10:8000"

# Master节点
node = {
    "hostname": "master-1",
    "node_type": "master",
    "mgmt_mac": "00:1a:2b:3c:4d:5e",  # 从实际节点获取
    "mgmt_ip": "192.168.1.101",
    "ctrl_ip": "10.0.0.101",
    "data_ip": "192.168.100.101",
    "bmc_ip": "192.168.1.201"
}
# POST /api/nodes (需要实现)

# Slave节点 (slave-1 ~ slave-5)
for i in range(1, 6):
    node = {
        "hostname": f"slave-{i}",
        "node_type": "slave",
        "mgmt_mac": f"00:1a:2b:3c:4d:{50+i:02x}",
        "mgmt_ip": f"192.168.1.{101+i}",
        "ctrl_ip": f"10.0.0.{101+i}",
        "data_ip": f"192.168.100.{101+i}",
        "bmc_ip": f"192.168.1.{201+i}"
    }
    # POST /api/nodes
PYTHON
```

#### 步骤3.2: 批量部署所有节点

```bash
# 批量部署
curl -X POST http://192.168.1.10:8000/api/pxe/batch-deploy \
  -H "Content-Type: application/json" \
  -d '{
    "nodes": [
      {
        "node_id": 1,
        "hostname": "master-1",
        "node_type": "master",
        "mgmt_ip": "192.168.1.101",
        "ctrl_ip": "10.0.0.101",
        "data_ip": "192.168.100.101"
      },
      {
        "node_id": 2,
        "hostname": "slave-1",
        "node_type": "slave",
        "mgmt_ip": "192.168.1.102",
        "ctrl_ip": "10.0.0.102",
        "data_ip": "192.168.100.102"
      }
    ]
  }'

# 响应:
# {"message": "批量部署已启动", "total_nodes": 6}
```

#### 步骤3.3: 启动节点PXE启动

```bash
# 通过IPMI启动节点 (Power-On + PXE First Boot)
for i in 1 201 202 203 204 205 206; do
    ipmitool -I lanplus -H 192.168.1.$i -U admin -P admin power on
    sleep 2
done

# 或手动在每个节点的IPMI/BMC中设置:
# - 启动顺序: PXE (Network) 第一位
# - 启动方式: One-shot (仅此次启动)
```

#### 步骤3.4: 监控部署进度

```bash
# 查询部署状态
watch -n 5 'curl -s http://192.168.1.10:8000/api/pxe/status | jq'

# 或轮询单个节点
for node_id in {1..6}; do
    curl -s http://192.168.1.10:8000/api/nodes/$node_id | jq '.status'
done

# 预期状态流转:
# offline -> deploying -> installing -> configuring -> online
# 整个过程约: 5-10分钟 (取决于网络和磁盘速度)
```

#### 步骤3.5: 验证部署完成

```bash
# 登录到节点验证
ssh root@192.168.1.101  # master-1

# 检查三平面网络
ip addr show | grep "inet 192.168.1\|inet 10.0.0\|inet 192.168.100"
# inet 192.168.1.101/24 brd 192.168.1.255 scope global eth0
# inet 10.0.0.101/24 brd 10.0.0.255 scope global eth1
# inet 192.168.100.101/24 brd 192.168.100.255 scope global eth2

# Master节点: 检查DPDK
modprobe -c | grep vfio
lspci -v | grep VFIO

# Slave节点: 检查RDMA
ibv_devinfo
# Device  :ibp<PCI>
#   node GUID           : xxxx:xxxx:xxxx:xxxx
#   SM GUID             : xxxx:xxxx:xxxx:xxxx

# 检查Agent注册
curl -s http://192.168.1.10:8000/api/nodes | jq '.[] | {hostname, status}'
# {"hostname": "master-1", "status": "online"}
# {"hostname": "slave-1", "status": "online"}
# ...
```

---

## 故障排查

### 问题1: 节点无法DHCP获取IP

**症状**: 节点启动到PXE但无法获得IP地址

**排查步骤**:

```bash
# 1. 验证DHCP服务运行
systemctl status dhcpd
ps aux | grep dhcpd

# 2. 检查DHCP日志
tail -50 /var/log/messages | grep DHCPDISCOVER

# 3. 验证DHCP配置
dhcpd -t  # 测试配置文件语法

# 4. 检查网络连接
tcpdump -i eth0 -vv port 67 or port 68

# 5. 常见问题:
# - DHCP服务未启动: systemctl restart dhcpd
# - 配置文件语法错误: dhcpd -t
# - MAC地址未在配置中: 检查/etc/dhcp/dhcpd.conf
# - 网络隔离: 检查交换机VLAN配置
```

### 问题2: TFTP无法下载启动文件

**症状**: DHCP分配IP成功, 但无法加载pxelinux.0

**排查步骤**:

```bash
# 1. 验证TFTP服务
systemctl status tftp
systemctl status xinetd

# 2. 检查TFTP文件
ls -la /tftpboot/
# -rw-r--r-- pxelinux.0
# -rw-r--r-- ldlinux.c32
# drwxr-xr-x pxelinux.cfg/

# 3. 测试TFTP连接
tftp 192.168.1.10
> get pxelinux.0
> quit

# 4. 检查防火墙
firewall-cmd --list-services | grep tftp
firewall-cmd --info-service=tftp

# 5. 检查TFTP日志
tail -50 /var/log/messages | grep in.tftpd

# 6. 常见问题:
# - 文件不存在: cp /usr/share/syslinux/pxelinux.0 /tftpboot/
# - 权限问题: chmod 644 /tftpboot/pxelinux.0
# - xinetd未启动: systemctl restart xinetd
```

### 问题3: Kickstart无法下载或执行

**症状**: 节点加载启动文件成功, 但无法开始Anaconda安装

**排查步骤**:

```bash
# 1. 验证HTTP服务
systemctl status httpd
curl -I http://192.168.1.10/openEuler/

# 2. 检查Kickstart文件位置
ls -la /tftpboot/ks/
# master-1.ks  master-1.ks.log

# 3. 验证Kickstart URL可访问
curl -I http://192.168.1.10:8000/ks/master-1.ks

# 4. 检查Kickstart语法
# 节点启动后, 查看控制台或日志:
# /tmp/anaconda.log
# /tmp/program.log

# 5. 常见问题:
# - URL错误: 检查APPEND参数 inst.ks=...
# - Kickstart文件无效: ksvalidator master-1.ks
# - 安装源不可用: curl -I http://192.168.1.10/openEuler/
```

### 问题4: 安装成功但节点无法启动

**症状**: Anaconda安装完成, reboot后无法进入系统

**排查步骤**:

```bash
# 1. 检查启动顺序
# - 进入BMC/IPMI
# - Boot -> Boot Device: Hard Disk
# - 确保不是仍然PXE优先

# 2. 通过IPMI控制台检查
ipmitool -I lanplus -H 192.168.1.201 -U admin sol activate
# 查看启动信息

# 3. 常见问题:
# - GRUB配置错误: 检查/boot/grub2/grub.cfg
# - 内核模块加载失败: 检查/root/ks-post.log
# - 磁盘分区错误: 查看/root/anaconda-ks.cfg
```

### 问题5: 节点在线但无法通信

**症状**: 节点online但ping失败

**排查步骤**:

```bash
# Master节点验证三平面网络
for plane in eth0 eth1 eth2; do
    echo "=== $plane ==="
    ip addr show $plane
    ping -c 1 $(ip addr show $plane | grep "inet " | awk '{print $2}' | cut -d/ -f1)
done

# 检查网络配置
cat /etc/sysconfig/network-scripts/ifcfg-eth0
# BOOTPROTO=none
# IPADDR=192.168.1.101
# NETMASK=255.255.255.0
# GATEWAY=192.168.1.1

# 检查MAC地址是否匹配
ip link show | grep "ether"
# 应该匹配数据库中的MAC地址

# 常见问题:
# - IPADDR格式: /etc/sysconfig/network-scripts/
# - Gateway不可达: 检查交换机和网络拓扑
# - 防火墙阻止: systemctl disable firewalld (测试)
```

---

## 性能优化建议

### 1. 并行部署多个节点

```python
# 使用线程池加速批量部署
from concurrent.futures import ThreadPoolExecutor, as_completed

async def batch_deploy_optimized(nodes, db):
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(deploy_single_node, node): node 
            for node in nodes
        }
        for future in as_completed(futures):
            result = future.result()
            # 处理结果
```

### 2. 减少安装时间

```bash
# 在Kickstart中使用本地镜像
# 代替: url --url=http://192.168.1.10/openEuler/
# 使用: nfs --server 192.168.1.10 --dir /nfs/openEuler

# 压缩安装包列表
%packages
@core
@base
openssh-server
python3
# 移除不需要的包: vim, network-tools等 (可选)
%end
```

### 3. 优化DHCP分配

```conf
# /etc/dhcp/dhcpd.conf
# 增加DHCP并发连接数
max-lease-time 7200;
default-lease-time 3600;

# 预分配更多IP地址
range 192.168.1.100 192.168.1.250;  # 151个可用IP

# 为高优先级节点设置固定地址
```

---

## 扩展资源

### openEuler官方文档
- [PXE启动文档](https://docs.openeuler.org/)
- [Kickstart配置参考](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_basic_system_settings/kickstart-installations_configuring-basic-system-settings)

### DPDK/RDMA配置
- [DPDK快速入门](https://doc.dpdk.org/)
- [RDMA开发指南](https://github.com/linux-rdma/rdma-core)

### 集群管理最佳实践
- 建立部署前检查清单
- 记录每个部署的日志
- 定期备份Kickstart配置
- 在生产前测试新配置

