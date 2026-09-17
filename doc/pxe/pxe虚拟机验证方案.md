# VMware Workstation 端到端 PXE 部署验证方案

> **目标**:在 Windows + VMware Workstation Pro(免费)上,用 x86_64 虚拟机完整验证
> 鲲鹏集群 PXE 部署方案的核心流程:DHCP → PXE 引导 → 镜像下载 → firstboot 差异化注入
>
> **验证策略**:用 x86_64 Rocky Linux 9 替代 aarch64 鲲鹏节点。
> PXE 引导流程、DHCP 逻辑、firstboot 脚本**完全与架构无关**,验证结论可直接映射到真实硬件。

---

## 目录

- [0 验证设计思路](#0-验证设计思路)
- [1 环境准备](#1-环境准备)
- [2 VMware 虚拟网络配置](#2-vmware-虚拟网络配置)
- [3 虚拟机规划](#3-虚拟机规划)
- [4 PXE Host 虚拟机配置](#4-pxe-host-虚拟机配置)
- [5 构建 x86_64 测试镜像](#5-构建-x86_64-测试镜像)
- [6 PXE 服务配置](#6-pxe-服务配置)
- [7 node-config API 服务](#7-node-config-api-服务)
- [8 firstboot 脚本适配(x86 版)](#8-firstboot-脚本适配x86-版)
- [9 执行验证](#9-执行验证)
- [10 验证检查点与预期结果](#10-验证检查点与预期结果)
- [11 常见问题排查](#11-常见问题排查)
- [附录:与真实鲲鹏环境的差异对照](#附录与真实鲲鹏环境的差异对照)
- [12 实测问题记录(2026-05-08)](#12-实测问题记录2026-05-08)

---

## 0 验证设计思路

### 0.1 验证覆盖范围

```
┌─────────────────────────────────────────────────────────────────┐
│                      端到端验证覆盖范围                           │
│                                                                   │
│  ✅ DHCP 固定 IP 分配(按 MAC 绑定)                               │
│  ✅ TFTP 传输 PXE 引导文件(grub.efi)                            │
│  ✅ GRUB 菜单渲染与 kernel/initrd 加载                           │
│  ✅ initrd 阶段:系统盘探测 → 分区 → 格式化 → 镜像解压           │
│  ✅ HTTP 镜像下载(base.tar.zst)带宽与完整性                     │
│  ✅ GRUB 安装(UEFI 模式)                                        │
│  ✅ 首次重启进入新系统                                            │
│  ✅ firstboot.service 触发                                       │
│  ✅ detect.sh 查询 node-config API(MAC → role/IP/disk)          │
│  ✅ 10-hostname.sh:主机名注入                                   │
│  ✅ 20-network.sh:多网口配置(ctrl/rdma 角色分离)               │
│  ✅ 30-hugepages.sh:大页内存(master 角色)                       │
│  ✅ 40-sysctl.sh:内核参数注入                                   │
│  ✅ 50-dirs.sh:目录创建                                         │
│  ✅ 55-disks.sh:数据盘挂载(subswath/gstorage 角色)             │
│  ✅ 70-nfs.sh:NFS Server 配置 + Client 挂载验证                 │
│  ✅ firstboot 完成回调(api/done)                                │
│                                                                   │
│  ⬜ DPDK 网口绑定(需要真实 HNS 网卡,无法虚拟化)                 │
│  ⬜ RDMA(需要 RoCE 硬件支持)                                    │
│  ⬜ 100GE 线速带宽测试                                           │
└─────────────────────────────────────────────────────────────────┘
```

### 0.2 虚拟化映射关系

| 真实集群 | 虚拟机模拟 | 说明 |
|---|---|---|
| PXE Host(物理机 100GE 上行) | **PXE-Host VM** | VMnet2 作为控制面网络,等价于 10G 交换机 |
| Master 节点(ARM64) | **Master-01 VM** | x86_64 Rocky 9,验证 master role |
| Slave 节点(ARM64) | **Slave-01 VM** | x86_64 Rocky 9,验证 slave role + NFS |
| SubSwath 节点(ARM64) | **SubSwath-01 VM** | x86_64 Rocky 9,验证 NFS Server + 数据盘 |
| GE 交换机(BMC 管理面) | **不需要**单独模拟 | VMware Host-only 网络天然隔离 |
| 10G 交换机(控制面) | **VMnet2(Host-only)** | 等价于 10G 交换机 L2 域 |
| 100G 交换机(数据面) | **VMnet3(Host-only)** | 等价于 100G 交换机(无线速限制,验证连通性) |

### 0.3 内存分配规划(32GB 主机)

```
Windows 系统自身        :  4 GB
VMware 开销             :  1 GB
─────────────────────────────────
PXE-Host VM             :  4 GB  ← 运行 DHCP/TFTP/HTTP/API 全部服务
Master-01 VM            :  4 GB  ← 验证 master role,hugepages
Slave-01 VM             :  3 GB  ← 验证 slave role,NFS 客户端
SubSwath-01 VM          :  3 GB  ← 验证 subswath role,NFS 服务端
─────────────────────────────────
合计                    : 19 GB  ← 安全范围内,剩余 13GB 缓冲
```

> 💡 如果想同时验证更多节点(如 slave-02、gstorage-01),可把各节点减到 2GB,
> Rocky 9 minimal 安装只需 ~1.2GB 可以正常运行。

---

## 1 环境准备

### 1.1 下载 VMware Workstation Pro(免费)

1. 访问 [https://www.vmware.com/products/desktop-hypervisor/workstation-and-fusion](https://www.vmware.com/products/desktop-hypervisor/workstation-and-fusion)
2. 点击 **"Download for Free"** → 选择 Windows 版本
3. 安装时选择 **"Use VMware Workstation Pro for Personal Use"**(免费,无需序列号)

> ⚠️ 注意:如果 Windows 已开启 Hyper-V,VMware 可能无法正常运行。
> 可以在 Windows 功能中关闭 Hyper-V,或者使用 VMware 的 WHP 模式(性能稍差但兼容)。

### 1.2 下载操作系统 ISO

**方案A(原始文档):Rocky Linux 9 x86_64**
```
下载地址:https://rockylinux.org/download
选择: Rocky Linux 9 → x86_64 → Minimal ISO (~2.2GB)
文件名: Rocky-9.x-x86_64-minimal.iso
```

**方案B(实测可用):OpenEuler 22.03-LTS-SP3 x86_64**
```
下载地址:https://www.openeuler.org/zh/download/
选择: openEuler 22.03 LTS SP3 → x86_64 → everything ISO
```

> ✅ 只需下载一次,PXE Host 的构建和所有节点 VM 的备用启动都用这个 ISO。
>
> ⚠️ **实测注意**:使用 OpenEuler ISO 时,后续 dnf repo 文件只需一个 `[local-openeuler]` 段,
> `baseurl=file:///mnt/iso` 指向挂载根目录即可(OpenEuler ISO repodata 在根目录)。

### 1.3 准备工作目录

在 Windows 上创建一个工作目录用于存放所有 VM 和脚本文件:

```
D:\pxe-lab\
├── isos\
│   └── Rocky-9.x-x86_64-minimal.iso
├── vms\
│   ├── pxe-host\
│   ├── master-01\
│   ├── slave-01\
│   └── subswath-01\
└── scripts\         ← 后面会在这里存放各种辅助脚本
```

---

## 2 VMware 虚拟网络配置

这是整个验证环境的**基础**,必须最先配置。我们需要 3 个虚拟网络:

```
VMnet1 (Host-only, 已有) → 不使用,避免冲突
VMnet2 (Host-only, 新建) → 控制面/PXE 网络  172.16.3.0/24
VMnet3 (Host-only, 新建) → 数据面网络        100.1.1.0/24
```

### 2.1 打开虚拟网络编辑器

```
VMware 菜单栏 → Edit → Virtual Network Editor → Change Settings(需要管理员权限)
```

### 2.2 配置 VMnet2(控制面,等价于 10G 交换机)

```
点击 "Add Network..." → 选择 VMnet2 → OK

VMnet2 配置:
  类型:           Host-only
  ☑ Connect a host virtual adapter to this network
  ☐ Use local DHCP service (必须关闭!我们自己的 dhcpd 来接管)
  子网 IP:        172.16.3.0
  子网掩码:       255.255.255.0
```

> 🔑 **关键**:必须关闭 VMware 自带的 DHCP,否则会与我们部署的 dhcpd 产生冲突,
> 导致节点拿到错误的 IP 地址而 PXE 引导失败。

### 2.3 配置 VMnet3(数据面,等价于 100G 交换机)

```
点击 "Add Network..." → 选择 VMnet3 → OK

VMnet3 配置:
  类型:           Host-only
  ☑ Connect a host virtual adapter to this network
  ☐ Use local DHCP service (同样关闭)
  子网 IP:        100.1.1.0
  子网掩码:       255.255.255.0
```

### 2.4 验证网络配置

打开 Windows PowerShell,查看 VMware 虚拟网卡:

```powershell
Get-NetAdapter | Where-Object {$_.Name -like "VMware*"}
# 应该看到:
# VMware Network Adapter VMnet2  →  172.16.3.x (Windows 主机侧地址)
# VMware Network Adapter VMnet3  →  100.1.1.x
```

如果 Windows 主机侧的 VMnet2 没有自动获得 172.16.3 网段的地址,手动配置:

```powershell
# 给 Windows 主机侧 VMnet2 配置地址(方便后续 SSH 进入 PXE Host)
New-NetIPAddress -InterfaceAlias "VMware Network Adapter VMnet2" `
    -IPAddress 172.16.3.1 -PrefixLength 24
```

### 2.5 网络拓扑示意

```
Windows 主机 (172.16.3.1 on VMnet2)
    │
    │  VMnet2 (172.16.3.0/24) — 等价于真实环境中的 10G 交换机
    ├─────────────────────────────────────────────────┐
    │                                                 │
PXE-Host VM                                    被安装的节点 VM
  eno1: 172.16.3.10 (VMnet2)                  eno1: (DHCP 获取 172.16.3.x)
  eno2: 100.1.1.10  (VMnet3)                  eno2: 100.1.1.x (firstboot 配置)
    │
    │  运行:dhcpd / tftpd / httpd / node-config-api
```

---

## 3 虚拟机规划

### 3.1 虚拟机配置表

| VM 名称 | CPU | 内存 | 系统盘 | 数据盘 | 网口 1 (VMnet2) | 网口 2 (VMnet3) | 用途 |
|---|---|---|---|---|---|---|---|
| **PXE-Host** | 2 核 | **≥4 GB** | **≥60 GB** | 无 | eno1: 172.16.3.10 | eno2: 100.1.1.10 | DHCP/TFTP/HTTP/API |
| **Master-01** | 2 核 | 4 GB | 40 GB | 无 | eno1: DHCP→172.16.3.11 | eno2: 100.1.1.11 | 验证 master role |
| **Slave-01** | 2 核 | 3 GB | 40 GB | 无 | eno1: DHCP→172.16.3.51 | eno2: 100.1.1.51 | 验证 slave role + NFS |
| **SubSwath-01** | 2 核 | 3 GB | 40 GB | 20 GB×2 | eno1: DHCP→172.16.3.170 | eno2: 100.1.1.170 | 验证 NFS Server + 数据盘 |

> 💡 SubSwath 添加 2 块独立虚拟磁盘(每块 20GB)来模拟 2 块 NVMe(用 mdadm RAID1 代替 RAID10,
> 因为 RAID10 至少需要 4 块盘;功能验证不影响)。

### 3.2 创建 Master-01 / Slave-01 / SubSwath-01 虚拟机(通用步骤)

以 **Master-01** 为例,其他节点相同:

```
VMware 菜单 → File → New Virtual Machine → Custom

步骤 1: Compatibility → 选择最新版本
步骤 2: Guest OS Installation → "I will install the OS later"(不要直接从 ISO 安装!)
步骤 3: Guest OS → Linux → Rocky Linux 9 64-bit
步骤 4: VM Name → master-01 | Location → D:\pxe-lab\vms\master-01
步骤 5: CPUs → 2 socket × 1 core
步骤 6: Memory → 4096 MB
步骤 7: Network → "Do not add a network connection"(稍后手动添加)
步骤 8: SCSI → LSI Logic(默认)
步骤 9: Disk → Create a new virtual disk
           大小: 40 GB
           ☑ Allocate all disk space now(加速 PXE 测试时的格式化)
步骤 10: Disk file → master-01.vmdk
步骤 11: Finish
```

**完成后,编辑 VM 设置,添加两块网卡**:

```
VM Settings → Add → Network Adapter
  Network connection: Custom → VMnet2   ← 控制面

VM Settings → Add → Network Adapter
  Network connection: Custom → VMnet3   ← 数据面
```

**关键:开启 UEFI 固件**(真实鲲鹏节点是 UEFI PXE):

```
VM Settings → Options → Advanced → Firmware type → UEFI
             ☑ Enable secure boot → 取消勾选(简化测试)
```

**SubSwath-01 额外添加 2 块数据盘**:

```
VM Settings → Add → Hard Disk → SCSI → Create new
  大小: 20 GB → sdb.vmdk

VM Settings → Add → Hard Disk → SCSI → Create new
  大小: 20 GB → sdc.vmdk

(这样 SubSwath-01 有 3 块盘:/dev/sda 系统盘,/dev/sdb /dev/sdc 数据盘)
```

---

## 4 PXE Host 虚拟机配置

PXE-Host 是整个验证环境的核心,安装方式与节点不同,需要**从 ISO 手动安装 Rocky Linux 9**。

### 4.1 创建并安装 PXE-Host VM

```
参考第 3.2 节创建 VM,以下有所不同:
  - VM Name: pxe-host
  - Memory: 4096 MB
  - Disk: 60 GB(需要存放镜像文件)
  - 安装方式:挂载 ISO 安装,而不是 PXE 引导

VM Settings → CD/DVD → Use ISO image file → D:\pxe-lab\isos\Rocky-9.x-x86_64-minimal.iso
```

启动 PXE-Host VM,完成 Rocky Linux 9 安装:

```
安装选项(最简配置):
  语言:         English
  Installation Destination: 选择 40GB 磁盘,自动分区
  Software Selection: Minimal Install
  Network:
    ens160(VMnet2): 手动配置
      IP:      172.16.3.10
      Mask:    255.255.255.0
      Gateway: 172.16.3.1
      DNS:     172.16.3.10
    ens192(VMnet3): 手动配置
      IP:      100.1.1.10
      Mask:    255.255.255.0
  Root password: 设置一个你记得住的密码
  Begin Installation → Reboot
```

> ⚠️ 注意网口名称:VMware 下通常是 `ens160`、`ens192`,而不是真实鲲鹏上的 `eno1`、`eno2`。
> 后面的脚本会用变量处理这个差异。

### 4.2 安装完成后基础配置

SSH 进入 PXE-Host(从 Windows PowerShell):

```powershell
ssh root@172.16.3.10
```

```bash
# 关闭 firewalld(测试环境)
systemctl stop firewalld && systemctl disable firewalld

# 关闭 SELinux
setenforce 0
sed -i 's/SELINUX=enforcing/SELINUX=disabled/' /etc/selinux/config

# 安装所有 PXE 服务所需的包
dnf install -y \
    dhcp-server \
    tftp-server \
    httpd \
    wget curl \
    python3 \
    tar xz zstd \
    grub2-efi-x64 grub2-tools \
    dracut dracut-network gdisk dosfstools

# 挂载 ISO 作为本地源(加速后续 chroot 构建)
mkdir -p /mnt/iso
# 先把 ISO 传到 PXE-Host(从 Windows 用 scp 或共享目录)
```

> ⚠️ **实测注意(OpenEuler)**:
> - `jq` 不在 OpenEuler 本地 ISO 中，且实际脚本不需要，**去掉 jq**
> - `tar` 在 OpenEuler minimal 安装中**未预装**，必须显式安装
> - `shim-x64` 在 OpenEuler 中不存在，可跳过
> - `python3-pip` 非必需，可跳过
> - 网络未配置时无法访问外网，**建议挂载本地 ISO 作为 dnf 源**后再执行此步骤
>
> **安装完成后确认网络可用**(`ifconfig` 在 minimal 安装中不存在，用 `ip a` 替代):

### 4.3 传输 ISO 到 PXE-Host

从 Windows PowerShell:

```powershell
# 方法1:scp(推荐,直接)
scp "D:\pxe-lab\isos\Rocky-9.x-x86_64-minimal.iso" root@172.16.3.10:/opt/

# 方法2:如果 scp 太慢,可以在 VMware 里用"共享文件夹"功能:
# VM Settings → Options → Shared Folders → Add → D:\pxe-lab
# 在 VM 里: ls /mnt/hgfs/pxe-lab/isos/
```

---

## 5 构建 x86_64 测试镜像

这是对真实部署中"构建 aarch64 黄金镜像"步骤的**等效验证**,
区别仅在于目标架构是 x86_64,所有构建脚本逻辑完全一致。

### 5.1 挂载 ISO 并配置本地源

```bash
# 在 PXE-Host 上
mount -o loop /opt/Rocky-9.x-x86_64-minimal.iso /mnt/iso

cat > /etc/yum.repos.d/local-x86.repo << 'EOF'
[local-baseos]
name=Rocky9 x86_64 BaseOS
baseurl=file:///mnt/iso/BaseOS
gpgcheck=0
enabled=1
[local-appstream]
name=Rocky9 x86_64 AppStream
baseurl=file:///mnt/iso/AppStream
gpgcheck=0
enabled=1
EOF
```

### 5.2 构建 buildroot(chroot 环境)

```bash
BUILDROOT=/opt/buildroot-x86

mkdir -p $BUILDROOT

# 最小化安装到 buildroot
dnf --installroot=$BUILDROOT --releasever=9 \
    --repo=local-baseos --repo=local-appstream \
    install -y \
    basesystem bash coreutils systemd \
    NetworkManager openssh-server \
    grub2-pc grub2-efi-x64 grub2-tools shim-x64 \
    kernel \
    mdadm nfs-utils xfsprogs dosfstools \
    wget curl tar zstd \
    --nogpgcheck

# 挂载必要的虚拟文件系统
for fs in dev dev/pts proc sys run; do
    mount --bind /$fs $BUILDROOT/$fs
done
```

### 5.3 chroot 内基础配置

```bash
chroot $BUILDROOT bash << 'CHROOT'
# 启用 sshd
systemctl enable sshd

# 设置 root 密码(测试用,真实环境改为 SSH key)
echo "root:root123" | chpasswd

# 允许 root SSH 登录(测试用)
sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# 创建 firstboot 目录结构
mkdir -p /etc/node-role/scripts
mkdir -p /var/log/firstboot

# 标记:需要运行 firstboot
touch /etc/node-role/FIRSTBOOT_PENDING

CHROOT
```

### 5.4 复制 firstboot 脚本进 buildroot

```bash
# 创建脚本目录并写入各脚本(见 §8)
mkdir -p $BUILDROOT/etc/node-role/scripts

# 复制 firstboot-main.sh, detect.sh, 各 xx-*.sh
# (内容详见第 8 节)

# 创建 firstboot.service
cat > $BUILDROOT/etc/systemd/system/firstboot.service << 'EOF'
[Unit]
Description=Node First Boot Configuration
After=network-online.target
Wants=network-online.target
ConditionPathExists=/etc/node-role/FIRSTBOOT_PENDING

[Service]
Type=oneshot
ExecStart=/etc/node-role/firstboot-main.sh
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
EOF

chroot $BUILDROOT systemctl enable firstboot
```

### 5.5 打包镜像

```bash
# 卸载虚拟文件系统
for fs in dev/pts dev sys proc run; do umount $BUILDROOT/$fs 2>/dev/null; done

# 打包(与真实方案相同的 zstd 压缩)
echo "打包镜像中,请稍候..."
tar --zstd -cpf /var/www/html/images/base.tar.zst \
    --numeric-owner \
    --exclude='/proc/*' --exclude='/sys/*' --exclude='/dev/*' \
    -C $BUILDROOT .

# 生成校验文件
sha256sum /var/www/html/images/base.tar.zst > /var/www/html/images/SHA256SUMS
echo "镜像大小:"
du -sh /var/www/html/images/base.tar.zst

# 确认镜像可解压
echo "验证镜像完整性..."
tar --zstd -tf /var/www/html/images/base.tar.zst | tail -5
echo "镜像构建完成 ✓"
```

---

## 6 PXE 服务配置

### 6.1 HTTP 服务(Apache)

```bash
# /etc/httpd/conf.d/pxe.conf
cat > /etc/httpd/conf.d/pxe.conf << 'EOF'
<Directory "/var/www/html/images">
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted
</Directory>
EOF

mkdir -p /var/www/html/images
systemctl enable --now httpd

# 验证可访问
curl -I http://172.16.3.10/images/base.tar.zst
# 预期:HTTP/1.1 200 OK
```

### 6.2 TFTP 服务

```bash
mkdir -p /var/lib/tftpboot
systemctl enable --now tftp.socket

# 复制 UEFI PXE 文件
# Rocky Linux 9:
#   cp /boot/efi/EFI/rocky/grubx64.efi /var/lib/tftpboot/
#   cp /boot/efi/EFI/rocky/shimx64.efi /var/lib/tftpboot/
# OpenEuler 22.03 (EFI 目录为 openEuler,无 shim):
ls /boot/efi/EFI/          # 确认目录名(rocky 或 openEuler)
cp /boot/efi/EFI/openEuler/grubx64.efi /var/lib/tftpboot/

# 复制内核和 initrd (从节点 ISO 提取)
cp /mnt/iso/images/pxeboot/vmlinuz   /var/lib/tftpboot/vmlinuz-x64
cp /mnt/iso/images/pxeboot/initrd.img /var/lib/tftpboot/initrd-x64-stock.img

# ⚠️ 关键：必须给所有 tftpboot 文件设置可读权限
# TFTP 服务以非 root 用户运行，文件权限不足会导致 "Permission denied"
chmod 644 /var/lib/tftpboot/*

# 验证 TFTP 可以传文件(curl 支持 tftp 协议)
curl -v tftp://172.16.3.10/grubx64.efi -o /tmp/test.efi && echo "TFTP OK"
```

> ⚠️ **实测问题**:从 `/boot/efi/EFI/openEuler/` 复制的 `grubx64.efi` 权限为 `700`(仅 root 可读),
> TFTP 服务无法读取,导致节点 PXE 启动时一直返回 Boot Manager 界面。
> **必须执行 `chmod 644 /var/lib/tftpboot/*`** 后 TFTP 才能正常传文件。

### 6.3 构建自定义部署 initrd

```bash
# 在 PXE-Host 上创建部署脚本
cat > /tmp/deploy.sh << 'DEPLOY'
#!/bin/bash
# 部署脚本:运行在节点的 RAM 环境里
set -euo pipefail
exec > /dev/console 2>&1

PXE_SERVER=$(cat /proc/cmdline | grep -o 'pxe_server=[^ ]*' | cut -d= -f2)
echo "[deploy] PXE Server: $PXE_SERVER"

# 等待网络就绪
for i in $(seq 1 30); do
    ip route get $PXE_SERVER &>/dev/null && break
    echo "[deploy] waiting for network... ($i/30)"
    sleep 2
done

# 获取 MAC 地址
IFACE=$(ip route get $PXE_SERVER | awk '/dev/{print $3}' | head -1)
MAC=$(cat /sys/class/net/$IFACE/address)
echo "[deploy] Detected MAC: $MAC on $IFACE"

# 查询目标磁盘
SYSTEM_DISK=$(curl -sf "http://$PXE_SERVER:8888/api/node-env?mac=$MAC" \
    | grep '^SYSTEM_DISK=' | cut -d= -f2)

# 自动探测最小盘(fallback)
if [ -z "${SYSTEM_DISK:-}" ]; then
    SYSTEM_DISK=$(lsblk -dno NAME,TYPE,SIZE,MOUNTPOINT \
        | awk '$2=="disk" && $4==""' \
        | sort -h -k3 \
        | head -1 \
        | awk '{print "/dev/"$1}')
    echo "[deploy] API fallback, auto-detected: $SYSTEM_DISK"
fi

echo "[deploy] Target disk: $SYSTEM_DISK"
[ -b "$SYSTEM_DISK" ] || { echo "ERROR: disk not found!"; sleep 30; exit 1; }

# 分区 GPT: EFI 512M + root 剩余
sgdisk -Z $SYSTEM_DISK
sgdisk -n 1:0:+512M -t 1:ef00 -c 1:EFI  $SYSTEM_DISK
sgdisk -n 2:0:0     -t 2:8300 -c 2:root $SYSTEM_DISK
partprobe $SYSTEM_DISK
sleep 2

PART1="${SYSTEM_DISK}1"
PART2="${SYSTEM_DISK}2"
[ -b "${SYSTEM_DISK}p1" ] && PART1="${SYSTEM_DISK}p1" && PART2="${SYSTEM_DISK}p2"

mkfs.vfat -F32 -n EFI $PART1
mkfs.xfs  -f   -L root $PART2

mkdir /newroot
mount $PART2 /newroot
mkdir -p /newroot/boot/efi
mount $PART1 /newroot/boot/efi

echo "[deploy] Downloading and extracting base image..."
echo "[deploy] This may take 2-5 minutes..."
wget -q --show-progress \
     -O - "http://$PXE_SERVER/images/base.tar.zst" \
     | tar --zstd -xpf - -C /newroot 2>/dev/null

echo "[deploy] Installing GRUB..."
for fs in dev dev/pts proc sys; do
    mount --bind /$fs /newroot/$fs 2>/dev/null || true
done

chroot /newroot bash -c "
    grub2-install --target=x86_64-efi \
        --efi-directory=/boot/efi \
        --bootloader-id=rocky \
        --recheck 2>/dev/null || true
    grub2-mkconfig -o /boot/grub2/grub.cfg 2>/dev/null
    echo 'GRUB installed'
"

# 写 fstab
UUID1=\$(blkid -s UUID -o value $PART1)
UUID2=\$(blkid -s UUID -o value $PART2)
cat > /newroot/etc/fstab << EOF
UUID=\$UUID2  /          xfs   defaults,noatime  0 0
UUID=\$UUID1  /boot/efi  vfat  umask=0077         0 2
EOF

# 写 FIRSTBOOT_PENDING
touch /newroot/etc/node-role/FIRSTBOOT_PENDING

for fs in dev/pts dev sys proc; do
    umount /newroot/$fs 2>/dev/null || true
done
umount /newroot/boot/efi
umount /newroot

echo ""
echo "[deploy] ===================="
echo "[deploy] Deployment complete!"
echo "[deploy] System will reboot in 5 seconds..."
echo "[deploy] ===================="
sleep 5
reboot -f
DEPLOY

# 创建 run-deploy.sh 钩子触发脚本
cat > /tmp/run-deploy.sh << 'EOF'
#!/bin/bash
[ -f /deploy-done ] && return 0
bash /deploy.sh
echo "done" > /deploy-done
EOF
chmod +x /tmp/run-deploy.sh

# 使用 --include 方式构建 initrd（不依赖自定义模块）
# ⚠️ 注意：OpenEuler 的 dracut 不支持自定义模块加载（dracut-initqueue 模块不存在，
#    自定义 99deploy 模块报 "cannot be found or installed"），必须用 --include 方式注入
# ⚠️ 钩子必须放在 initqueue/online（而非 pre-mount）：
#    pre-mount 钩子有 systemd 超时，下载大文件时 dracut 会提前触发 switch-root 失败
dracut --force --no-hostonly \
    --add 'network base' \
    --include /tmp/deploy.sh /deploy.sh \
    --include /tmp/run-deploy.sh /lib/dracut/hooks/initqueue/online/99-deploy.sh \
    --install 'sgdisk mkfs.xfs mkfs.vfat partprobe wget blkid lsblk curl grep awk sed cut tr tar zstd touch sleep reboot chroot mount umount mkdir cat bash' \
    --omit 'plymouth biosdevname' \
    --kver $(rpm -q kernel --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' | tail -1) \
    /var/lib/tftpboot/initrd-x64-deploy.img

chmod 644 /var/lib/tftpboot/initrd-x64-deploy.img
echo "initrd 大小: $(du -sh /var/lib/tftpboot/initrd-x64-deploy.img)"
```

### 6.4 GRUB 菜单

```bash
cat > /var/lib/tftpboot/grub.cfg << 'EOF'
set default=0
set timeout=10

menuentry 'PXE Deploy - x86_64' {
    linuxefi /vmlinuz-x64 \
        ip=dhcp \
        pxe_server=172.16.3.10 \
        rd.neednet=1 \
        console=ttyS0,115200 \
        console=tty0 \
        quiet
    initrdefi /initrd-x64-deploy.img
}

menuentry 'Boot from local disk' { exit }
EOF
```

### 6.5 DHCP 配置

```bash
# 先获取各节点 VM 的 MAC 地址(见 §9.1)
# 这里先用占位符,后面替换

# 配置 dhcpd 监听网口（根据实际网口名修改，VMware 下通常是 ens36 而非 ens160）
cat > /etc/sysconfig/dhcpd << 'EOF'
DHCPDARGS=ens36
EOF

cat > /etc/dhcp/dhcpd.conf << 'DHCPCONF'
option domain-name-servers 172.16.3.10;
default-lease-time 600;
max-lease-time 7200;
authoritative;

# ⚠️ 实测注意：不要用 class 匹配 PXEClient:Arch:00007（32位EFI），
# VMware x86_64 UEFI 发送的是 Arch:00009（64位EFI），class 不匹配则不下发 filename。
# 直接在 subnet 层配置 filename 和 next-server，对所有客户端生效。
subnet 172.16.3.0 netmask 255.255.255.0 {
    range 172.16.3.100 172.16.3.110;
    option routers 172.16.3.1;
    next-server 172.16.3.10;
    filename "grubx64.efi";
}

# ── 节点 MAC 绑定(§9.1 获取真实 MAC 后替换)──
host master-01   { hardware ethernet AA:BB:CC:DD:EE:01; fixed-address 172.16.3.11; }
host slave-01    { hardware ethernet AA:BB:CC:DD:EE:02; fixed-address 172.16.3.51; }
host subswath-01 { hardware ethernet AA:BB:CC:DD:EE:03; fixed-address 172.16.3.170; }
DHCPCONF

systemctl enable --now dhcpd
```

---

## 7 node-config API 服务

这个 API 是 firstboot 脚本的数据源,接收节点 MAC 地址,返回该节点的差异化配置。

### 7.1 nodes.json(虚拟机版)

```bash
mkdir -p /opt/node-config-api

cat > /opt/node-config-api/nodes.json << 'EOF'
{
  "_comment": "虚拟机验证版 nodes.json - 用真实 MAC 地址替换 AA:BB:CC 占位符",

  "AA:BB:CC:DD:EE:01": {
    "hostname_new":  "master-01",
    "role":          "master",
    "ctrl_nic":      "ens160",
    "ctrl_ip":       "172.16.3.11/24",
    "ctrl_gw":       "172.16.3.1",
    "rdma_nics":     "ens192",
    "rdma_ips":      "100.1.1.11/24",
    "hugepages_1g":  "0",
    "_hugepages_note": "VM 内存不足,大页设为 0;真实环境改为 100",
    "system_disk":   "/dev/sda",
    "data_disks":    "",
    "dirs":          "/data"
  },

  "AA:BB:CC:DD:EE:02": {
    "hostname_new":  "slave-01",
    "role":          "slave",
    "ctrl_nic":      "ens160",
    "ctrl_ip":       "172.16.3.51/24",
    "ctrl_gw":       "172.16.3.1",
    "rdma_nics":     "ens192",
    "rdma_ips":      "100.1.1.51/24",
    "nfs_mounts":    "100.1.1.170:/data/export:/mnt/swath1",
    "hugepages_1g":  "0",
    "system_disk":   "/dev/sda",
    "data_disks":    "",
    "dirs":          "/data /mnt/swath1"
  },

  "AA:BB:CC:DD:EE:03": {
    "hostname_new":   "subswath-01",
    "role":           "subswath",
    "ctrl_nic":       "ens160",
    "ctrl_ip":        "172.16.3.170/24",
    "ctrl_gw":        "172.16.3.1",
    "rdma_nics":      "ens192",
    "rdma_ips":       "100.1.1.170/24",
    "nfs_export_ip":  "100.1.1.170",
    "nfs_exports":    "/data/export",
    "hugepages_1g":   "0",
    "system_disk":    "/dev/sda",
    "data_disks":     "/dev/sdb /dev/sdc",
    "data_raid_level":"raid1",
    "_raid_note":     "VM 只有 2 块数据盘,用 RAID1 验证 mdadm 逻辑(真实用 4 块 RAID10)",
    "dirs":           "/data/export",
    "extra_pkgs":     "nfs-utils mdadm"
  }
}
EOF
```

### 7.2 API 服务脚本

```bash
cat > /opt/node-config-api/api-server.py << 'PYEOF'
#!/usr/bin/env python3
"""极简 node-config API Server"""
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, sys

NODES_JSON = os.path.join(os.path.dirname(__file__), 'nodes.json')

def load_nodes():
    with open(NODES_JSON) as f:
        data = json.load(f)
    # 过滤掉注释键
    return {k.upper(): v for k, v in data.items() if not k.startswith('_')}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[API] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/api/node-env':
            mac = params.get('mac', [''])[0].upper()
            nodes = load_nodes()
            node = nodes.get(mac)
            if not node:
                print(f"[API] WARNING: Unknown MAC {mac}")
                self.send_response(404)
                self.end_headers()
                return
            # 返回 shell 可 source 的 KEY=VALUE 格式
            lines = []
            for k, v in node.items():
                if not k.startswith('_'):
                    lines.append(f"{k.upper()}={v}")
            body = '\n'.join(lines).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == '/api/done':
            hostname = params.get('hostname', ['unknown'])[0]
            print(f"[API] ✅ Node DONE: {hostname}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')

        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    port = 8888
    print(f"[API] node-config API listening on 0.0.0.0:{port}")
    print(f"[API] nodes.json: {NODES_JSON}")
    nodes = load_nodes()
    print(f"[API] Loaded {len(nodes)} nodes: {list(nodes.keys())}")
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()
PYEOF

# 创建 systemd 服务
cat > /etc/systemd/system/node-config-api.service << 'EOF'
[Unit]
Description=Node Config API Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/node-config-api/api-server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now node-config-api

# 验证 API
sleep 2
curl -s "http://172.16.3.10:8888/api/node-env?mac=AA:BB:CC:DD:EE:01"
```

---

## 8 firstboot 脚本适配(x86 版)

以下脚本与真实鲲鹏环境**逻辑完全一致**,仅做了两处适配:
1. 网口名 `eno1` → `ens160`,`eno2` → `ens192`(VMware 默认命名)
2. 大页内存设为 0(VM 内存不足)

### 8.1 detect.sh

```bash
cat > /opt/firstboot/detect.sh << 'EOF'
#!/bin/bash
# 通过 IP 路由反查 PXE Server 方向的网口
IFACE=$(ip route get 172.16.3.10 | awk '/dev/{print $3}' | head -1)
MAC=$(cat /sys/class/net/$IFACE/address)
echo "[detect] Iface=$IFACE  MAC=$MAC"

curl -sf "http://172.16.3.10:8888/api/node-env?mac=$MAC" \
     -o /etc/node-role/env

[ -s /etc/node-role/env ] || {
    echo "[detect] FATAL: no config for MAC=$MAC"
    exit 1
}
echo "[detect] Config loaded:"
cat /etc/node-role/env
EOF
chmod +x /opt/firstboot/detect.sh
```

### 8.2 firstboot-main.sh

```bash
cat > /opt/firstboot/firstboot-main.sh << 'EOF'
#!/bin/bash
set -euo pipefail
mkdir -p /var/log/firstboot
exec > >(tee -a /var/log/firstboot/firstboot.log) 2>&1

echo "======================================"
echo "  firstboot started: $(date)"
echo "======================================"

bash /etc/node-role/detect.sh
source /etc/node-role/env
echo "  Hostname : $HOSTNAME_NEW"
echo "  Role     : $ROLE"
echo "  Ctrl NIC : $CTRL_NIC  $CTRL_IP"
echo "  Disk     : $SYSTEM_DISK"

for script in $(ls /etc/node-role/scripts/*.sh | sort); do
    echo ""
    echo "--- $(basename $script) ---"
    bash "$script" || echo "WARNING: $script returned non-zero"
done

rm -f /etc/node-role/FIRSTBOOT_PENDING
systemctl disable firstboot 2>/dev/null || true
curl -sf "http://172.16.3.10:8888/api/done?hostname=$HOSTNAME_NEW" || true

echo ""
echo "======================================"
echo "  firstboot completed: $(date)"
echo "======================================"

if [ -f /etc/node-role/REBOOT_REQUIRED ]; then
    rm -f /etc/node-role/REBOOT_REQUIRED
    echo "  Rebooting to apply settings..."
    sleep 3
    reboot
fi
EOF
chmod +x /opt/firstboot/firstboot-main.sh
```

### 8.3 10-hostname.sh

```bash
cat > /opt/firstboot/scripts/10-hostname.sh << 'EOF'
#!/bin/bash
source /etc/node-role/env
hostnamectl set-hostname "$HOSTNAME_NEW"
echo "127.0.1.1 $HOSTNAME_NEW" >> /etc/hosts
echo "[hostname] Set to: $HOSTNAME_NEW"
EOF
```

### 8.4 20-network.sh

```bash
cat > /opt/firstboot/scripts/20-network.sh << 'EOF'
#!/bin/bash
source /etc/node-role/env

# 控制面(ens160 等价于真实环境 eno1)
nmcli con add type ethernet ifname "$CTRL_NIC" con-name ctrl \
    ip4 "$CTRL_IP" gw4 "$CTRL_GW" ipv4.dns '172.16.3.10' \
    connection.autoconnect yes
nmcli con up ctrl
echo "[network] ctrl: $CTRL_NIC = $CTRL_IP"

case "$ROLE" in
  master|slave)
    RDMA_NIC=$(echo $RDMA_NICS | awk '{print $1}')
    RDMA_IP=$(echo $RDMA_IPS | awk '{print $1}')
    nmcli con add type ethernet ifname $RDMA_NIC con-name rdma1 \
        ip4 $RDMA_IP connection.autoconnect yes
    nmcli con up rdma1
    echo "[network] rdma1: $RDMA_NIC = $RDMA_IP"
    ;;
  subswath|gstorage)
    i=1
    for ip in $RDMA_IPS; do
        nic=$(echo $RDMA_NICS | tr ' ' '\n' | sed -n ${i}p)
        nmcli con add type ethernet ifname $nic con-name rdma$i \
            ip4 $ip connection.autoconnect yes
        nmcli con up rdma$i
        echo "[network] rdma$i: $nic = $ip"
        i=$((i+1))
    done
    ;;
esac
EOF
```

### 8.5 30-hugepages.sh

```bash
cat > /opt/firstboot/scripts/30-hugepages.sh << 'EOF'
#!/bin/bash
source /etc/node-role/env
HUG=${HUGEPAGES_1G:-0}
[ "$HUG" -eq 0 ] && { echo "[hugepages] skip (0)"; exit 0; }

# 修改 GRUB(真实鲲鹏环境必须 reboot)
grubby --update-kernel=ALL \
    --args="default_hugepagesz=1G hugepagesz=1G hugepages=$HUG"
echo "[hugepages] Set $HUG × 1G hugepages, reboot required"
touch /etc/node-role/REBOOT_REQUIRED
EOF
```

### 8.6 50-dirs.sh

```bash
cat > /opt/firstboot/scripts/50-dirs.sh << 'EOF'
#!/bin/bash
source /etc/node-role/env
for dir in ${DIRS:-}; do
    mkdir -p $dir
    echo "[dirs] created: $dir"
done
EOF
```

### 8.7 55-disks.sh

```bash
cat > /opt/firstboot/scripts/55-disks.sh << 'EOF'
#!/bin/bash
source /etc/node-role/env
[ -z "${DATA_DISKS:-}" ] && { echo "[disks] skip (no data disks)"; exit 0; }

DISKS=($DATA_DISKS)
LEVEL="${DATA_RAID_LEVEL:-raid1}"

case "$ROLE" in
  subswath)
    echo "[disks] Creating mdadm $LEVEL on ${DISKS[@]}"
    mdadm --create --verbose /dev/md0 \
          --level=$LEVEL \
          --raid-devices=${#DISKS[@]} \
          "${DISKS[@]}" \
          --metadata=1.2 --run

    sleep 3
    mdadm --detail --scan >> /etc/mdadm.conf
    mkfs.xfs -f -L swathdata /dev/md0
    mkdir -p /data/export
    mount /dev/md0 /data/export
    UUID=$(blkid -s UUID -o value /dev/md0)
    echo "UUID=$UUID /data/export xfs defaults,nofail 0 0" >> /etc/fstab
    echo "[disks] mdadm $LEVEL done -> /data/export"
    df -h /data/export
    ;;
  gstorage)
    DEV=${DISKS[0]}
    mkfs.xfs -f -L globaldata $DEV
    mkdir -p /data/export
    mount $DEV /data/export
    UUID=$(blkid -s UUID -o value $DEV)
    echo "UUID=$UUID /data/export xfs defaults,nofail 0 0" >> /etc/fstab
    echo "[disks] gstorage $DEV -> /data/export"
    ;;
esac
EOF
```

### 8.8 60-pkgs.sh

```bash
cat > /opt/firstboot/scripts/60-pkgs.sh << 'EOF'
#!/bin/bash
source /etc/node-role/env
[ -z "${EXTRA_PKGS:-}" ] && { echo "[pkgs] skip"; exit 0; }
dnf install -y $EXTRA_PKGS
echo "[pkgs] Installed: $EXTRA_PKGS"
EOF
```

### 8.9 70-nfs.sh

```bash
cat > /opt/firstboot/scripts/70-nfs.sh << 'EOF'
#!/bin/bash
source /etc/node-role/env

case "$ROLE" in
  subswath|gstorage)
    systemctl enable --now nfs-server
    mkdir -p "${NFS_EXPORTS}"
    # 导出给 100G 网段
    echo "${NFS_EXPORTS} 100.1.1.0/24(rw,sync,no_root_squash,no_subtree_check)" \
         >> /etc/exports
    exportfs -ra
    echo "[nfs] Server: exporting ${NFS_EXPORTS}"
    showmount -e localhost
    ;;
  slave)
    [ -z "${NFS_MOUNTS:-}" ] && exit 0
    IFS=',' read -ra MOUNTS <<< "$NFS_MOUNTS"
    for entry in "${MOUNTS[@]}"; do
        SRV=$(echo $entry | cut -d: -f1)
        REMOTE=$(echo $entry | cut -d: -f2)
        LOCAL=$(echo $entry | cut -d: -f3)
        mkdir -p $LOCAL
        for i in $(seq 1 30); do
            showmount -e $SRV &>/dev/null && break
            echo "[nfs] waiting for $SRV ($i/30)..." && sleep 10
        done
        mount -t nfs -o rsize=1048576,wsize=1048576 $SRV:$REMOTE $LOCAL
        echo "$SRV:$REMOTE $LOCAL nfs rsize=1048576,wsize=1048576,_netdev 0 0" \
             >> /etc/fstab
        echo "[nfs] Client: mounted $SRV:$REMOTE -> $LOCAL"
    done
    ;;
esac
EOF
```

### 8.10 复制脚本进 buildroot 并重新打包

```bash
# 复制所有 firstboot 脚本到 buildroot
cp /opt/firstboot/detect.sh              $BUILDROOT/etc/node-role/
cp /opt/firstboot/firstboot-main.sh      $BUILDROOT/etc/node-role/
cp /opt/firstboot/scripts/*.sh           $BUILDROOT/etc/node-role/scripts/

chmod +x $BUILDROOT/etc/node-role/detect.sh
chmod +x $BUILDROOT/etc/node-role/firstboot-main.sh
chmod +x $BUILDROOT/etc/node-role/scripts/*.sh

# 更新 nodes.json 到 API
cp /opt/node-config-api/nodes.json /opt/node-config-api/nodes.json.bak

# 重新打包镜像(加入了 firstboot 脚本)
for fs in dev dev/pts proc sys run; do umount $BUILDROOT/$fs 2>/dev/null; done
tar --zstd -cpf /var/www/html/images/base.tar.zst \
    --numeric-owner \
    --exclude='/proc/*' --exclude='/sys/*' --exclude='/dev/*' \
    -C $BUILDROOT .
echo "镜像更新完成: $(du -sh /var/www/html/images/base.tar.zst)"
```

---

## 9 执行验证

### 9.1 获取各节点 VM 的真实 MAC 地址

在开始 PXE 部署之前,必须先获取每台节点 VM 的网卡 MAC 地址:

```
方法一(推荐):启动节点 VM，从 PXE-Host 的 DHCP 日志获取
  journalctl -u dhcpd | grep DHCPDISCOVER
  → 找到各节点的 MAC 地址（格式 00:0c:29:xx:xx:xx）

方法二:从 VMware 图形界面的 Advanced Settings 查看
  VM Settings → Network Adapter → Advanced → MAC Address
  ⚠️ 注意：此处显示的是 VMware 管理 MAC（00:50:56 开头），
     但实际 PXE 网卡使用的是动态生成 MAC（00:0c:29 开头），两者不同！
     务必以 DHCP 日志中出现的 MAC 为准。
```

> ⚠️ **实测关键**:VMware Workstation 动态生成的网卡 MAC 以 `00:0c:29` 开头,
> 与 Advanced Settings 中显示的 `00:50:56` 开头的静态 MAC **不同**。
> 如果用 VMware 界面的 MAC 配置 DHCP,节点会拿到动态 IP(.100~.110 段),
> 而非绑定的固定 IP。**必须先让节点启动一次,从 DHCP 日志取真实 MAC。**

**获取 MAC 后,更新 dhcpd.conf 和 nodes.json**:

```bash
# 在 PXE-Host 上
# 假设获得的真实 MAC 如下:
MASTER_MAC="52:54:00:aa:bb:01"
SLAVE_MAC="52:54:00:aa:bb:02"
SUBSWATH_MAC="52:54:00:aa:bb:03"

# 更新 dhcpd.conf
sed -i "s/AA:BB:CC:DD:EE:01/$MASTER_MAC/g"   /etc/dhcp/dhcpd.conf
sed -i "s/AA:BB:CC:DD:EE:02/$SLAVE_MAC/g"    /etc/dhcp/dhcpd.conf
sed -i "s/AA:BB:CC:DD:EE:03/$SUBSWATH_MAC/g" /etc/dhcp/dhcpd.conf
systemctl restart dhcpd

# 更新 nodes.json
sed -i "s/AA:BB:CC:DD:EE:01/$MASTER_MAC/g"   /opt/node-config-api/nodes.json
sed -i "s/AA:BB:CC:DD:EE:02/$SLAVE_MAC/g"    /opt/node-config-api/nodes.json
sed -i "s/AA:BB:CC:DD:EE:03/$SUBSWATH_MAC/g" /opt/node-config-api/nodes.json
systemctl restart node-config-api

# 验证配置已更新
curl -s "http://172.16.3.10:8888/api/node-env?mac=$MASTER_MAC"
```

### 9.2 部署顺序:SubSwath 先于 Slave

```
                    ┌─ 先部署 ─┐
                    │          │
            SubSwath-01      (可选) gstorage-01
                    │
                    │  ← 等待 showmount -e 100.1.1.170 成功
                    │
            ┌── 再部署 ──┐
            │            │
        Master-01      Slave-01   ← Slave 依赖 NFS Server 就绪
```

### 9.3 触发 PXE 部署

**步骤 1:在 PXE-Host 上开启日志监控**

打开三个终端(或 tmux 三窗口),分别监控各服务日志:

```bash
# 终端 1: DHCP 日志
journalctl -fu dhcpd

# 终端 2: HTTP 访问日志(监控镜像下载)
tail -f /var/log/httpd/access_log

# 终端 3: node-config API 日志
journalctl -fu node-config-api
```

**步骤 2:启动节点 VM 并设置 PXE 优先启动**

在 VMware 里:
```
SubSwath-01 → Power On
  → 看到 VMware 徽标时立刻按 F2 进入 UEFI
  → Boot Manager → EFI Network (VMnet2 那张网卡)
  → Enter
```

或者在 VM 设置中临时修改启动顺序:
```
VM Settings → Options → Boot Options → Boot Delay: 5000ms
Boot firmware: EFI
在 NVRAM 中将 Network 排第一
```

**步骤 3:观察 PXE 引导过程**

节点 VM 的控制台应该依次显示:

```
阶段 1: DHCP 获取地址
  DHCP Discover...
  DHCP Offer from 172.16.3.10
  Got IP: 172.16.3.170 (SubSwath 示例)

阶段 2: 下载 GRUB EFI
  Downloading grubx64.efi...
  Starting GRUB...
  ┌──────────────────────────────┐
  │ PXE Deploy - x86_64         │
  │ Boot from local disk        │
  └──────────────────────────────┘

阶段 3: 内核+initrd 加载
  Loading vmlinuz-x64...
  Loading initrd-x64-deploy.img...
  Booting...

阶段 4: initrd 部署阶段
  [deploy] PXE Server: 172.16.3.10
  [deploy] Detected MAC: 52:54:00:aa:bb:03 on ens160
  [deploy] Target disk: /dev/sda
  [deploy] Downloading and extracting base image...
  ████████░░░░░░░░ 45% 320M/s
  [deploy] Installing GRUB...
  [deploy] Deployment complete!
  [deploy] System will reboot in 5 seconds...

阶段 5: 重启进入新系统
  Rocky Linux 9.x
  Kernel ... on an x86_64

阶段 6: firstboot 自动运行
  ======================================
    firstboot started: Mon May 5 ...
  ======================================
  [detect] Iface=ens160  MAC=52:54:00:aa:bb:03
  [detect] Config loaded: ...
  --- 10-hostname.sh ---
  [hostname] Set to: subswath-01
  --- 20-network.sh ---
  [network] ctrl: ens160 = 172.16.3.170/24
  [network] rdma1: ens192 = 100.1.1.170/24
  --- 55-disks.sh ---
  [disks] Creating mdadm raid1 on /dev/sdb /dev/sdc
  [disks] mdadm raid1 done -> /data/export
  --- 70-nfs.sh ---
  [nfs] Server: exporting /data/export
  Export list for localhost:
  /data/export 100.1.1.0/24
  ======================================
    firstboot completed: Mon May 5 ...
  ======================================
```

---

## 10 验证检查点与预期结果

完成部署后,在 PXE-Host 上运行验证脚本:

```bash
#!/bin/bash
# /opt/verify-lab.sh

PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

echo "============================================"
echo "  PXE 实验室端到端验证"
echo "============================================"

echo ""
echo "─── 1. 控制面连通性(172.16.3.x) ───"
ping -c1 -W3 172.16.3.11  &>/dev/null && ok "master-01 ping"    || fail "master-01 ping"
ping -c1 -W3 172.16.3.51  &>/dev/null && ok "slave-01 ping"     || fail "slave-01 ping"
ping -c1 -W3 172.16.3.170 &>/dev/null && ok "subswath-01 ping"  || fail "subswath-01 ping"

echo ""
echo "─── 2. 主机名注入 ───"
for ip_host in "172.16.3.11:master-01" "172.16.3.51:slave-01" "172.16.3.170:subswath-01"; do
    IP=$(echo $ip_host | cut -d: -f1)
    EXPECT=$(echo $ip_host | cut -d: -f2)
    GOT=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
              root@$IP 'hostname' 2>/dev/null)
    [ "$GOT" = "$EXPECT" ] && ok "hostname $EXPECT" || fail "hostname: got '$GOT', expect '$EXPECT'"
done

echo ""
echo "─── 3. 数据面 IP 配置(100.1.1.x) ───"
for ip_check in "172.16.3.11:100.1.1.11" "172.16.3.51:100.1.1.51" "172.16.3.170:100.1.1.170"; do
    CTRL=$(echo $ip_check | cut -d: -f1)
    DATA=$(echo $ip_check | cut -d: -f2)
    GOT=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
              root@$CTRL "ip addr show | grep -o '$DATA'" 2>/dev/null)
    [ -n "$GOT" ] && ok "data-plane IP $DATA on $CTRL" \
                  || fail "data-plane IP $DATA missing on $CTRL"
done

echo ""
echo "─── 4. NFS Server (subswath-01) ───"
showmount -e 100.1.1.170 &>/dev/null \
    && ok "NFS export visible from PXE-Host" \
    || fail "NFS export not visible"

ping -c1 -W3 100.1.1.170 &>/dev/null \
    && ok "100G network 100.1.1.170 reachable" \
    || fail "100G network 100.1.1.170 unreachable"

echo ""
echo "─── 5. NFS Client (slave-01 挂载) ───"
MOUNTED=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
              root@172.16.3.51 'mountpoint -q /mnt/swath1 && echo yes' 2>/dev/null)
[ "$MOUNTED" = "yes" ] && ok "slave-01 /mnt/swath1 mounted" \
                        || fail "slave-01 /mnt/swath1 NOT mounted"

echo ""
echo "─── 6. NFS 读写测试 ───"
ssh -o StrictHostKeyChecking=no root@172.16.3.170 \
    'echo "nfs-write-test-$(date)" > /data/export/test.txt' 2>/dev/null
CONTENT=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
              root@172.16.3.51 'cat /mnt/swath1/test.txt' 2>/dev/null)
[[ "$CONTENT" == nfs-write-test-* ]] && ok "NFS read/write via 100G network ✓" \
                                      || fail "NFS read/write test failed"

echo ""
echo "─── 7. SubSwath mdadm RAID ───"
RAID=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
           root@172.16.3.170 'cat /proc/mdstat | grep -c "active"' 2>/dev/null)
[ "${RAID:-0}" -gt 0 ] && ok "SubSwath mdadm RAID active" \
                         || fail "SubSwath mdadm RAID not found"

echo ""
echo "─── 8. firstboot 日志完整性 ───"
for ip in 172.16.3.11 172.16.3.51 172.16.3.170; do
    DONE=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
               root@$ip 'grep -c "firstboot completed" /var/log/firstboot/firstboot.log 2>/dev/null' \
               2>/dev/null)
    [ "${DONE:-0}" -gt 0 ] && ok "$ip firstboot completed" \
                             || fail "$ip firstboot NOT completed"
done

echo ""
echo "============================================"
echo "  结果: ${PASS} passed, ${FAIL} failed"
[ $FAIL -eq 0 ] && echo "  🎉 全部验证通过!PXE 流程端到端验证成功" \
                || echo "  ⚠️  存在失败项,请查看上方详情"
echo "============================================"
```

```bash
chmod +x /opt/verify-lab.sh
bash /opt/verify-lab.sh
```

### 预期完整通过输出

```
============================================
  PXE 实验室端到端验证
============================================

─── 1. 控制面连通性(172.16.3.x) ───
  ✅ master-01 ping
  ✅ slave-01 ping
  ✅ subswath-01 ping

─── 2. 主机名注入 ───
  ✅ hostname master-01
  ✅ hostname slave-01
  ✅ hostname subswath-01

─── 3. 数据面 IP 配置(100.1.1.x) ───
  ✅ data-plane IP 100.1.1.11 on 172.16.3.11
  ✅ data-plane IP 100.1.1.51 on 172.16.3.51
  ✅ data-plane IP 100.1.1.170 on 172.16.3.170

─── 4. NFS Server (subswath-01) ───
  ✅ NFS export visible from PXE-Host
  ✅ 100G network 100.1.1.170 reachable

─── 5. NFS Client (slave-01 挂载) ───
  ✅ slave-01 /mnt/swath1 mounted

─── 6. NFS 读写测试 ───
  ✅ NFS read/write via 100G network ✓

─── 7. SubSwath mdadm RAID ───
  ✅ SubSwath mdadm RAID active

─── 8. firstboot 日志完整性 ───
  ✅ 172.16.3.11 firstboot completed
  ✅ 172.16.3.51 firstboot completed
  ✅ 172.16.3.170 firstboot completed

============================================
  结果: 14 passed, 0 failed
  🎉 全部验证通过!PXE 流程端到端验证成功
============================================
```

---

## 11 常见问题排查

### 11.1 节点 VM 拿不到 IP(DHCP 无响应)

```bash
# 检查 dhcpd 是否在正确网卡监听
cat /etc/sysconfig/dhcpd                 # 应该是 ens160
systemctl status dhcpd                   # 是否 active

# 检查 VMware 自带 DHCP 是否被关闭
# VMware → Edit → Virtual Network Editor → VMnet2 → 确认没有勾选 DHCP

# 抓 DHCP 包确认报文到了 PXE-Host
tcpdump -i ens160 port 67 or port 68 -n
```

### 11.2 GRUB 下载成功但内核加载失败

```bash
# 检查 GRUB.cfg 路径与文件名
ls -la /var/lib/tftpboot/
# 应该有:grubx64.efi, vmlinuz-x64, initrd-x64-deploy.img, grub.cfg

# 检查 TFTP 服务
systemctl status tftp.socket
# 测试下载:
tftp 172.16.3.10 -c get grubx64.efi /tmp/test.efi && echo "TFTP OK"
```

### 11.3 镜像下载很慢或中断

```bash
# 检查 httpd 是否运行
curl -I http://172.16.3.10/images/base.tar.zst

# VMware 内部网络理论带宽不受限,如果慢,检查磁盘 I/O
iostat -x 1 5   # 在 PXE-Host 上

# 镜像太大?查看大小
du -sh /var/www/html/images/base.tar.zst
# 建议控制在 2GB 以内,确保测试时不超时
```

### 11.4 firstboot 没有触发

```bash
# SSH 进入已安装的节点 VM
ssh root@172.16.3.11

# 检查 FIRSTBOOT_PENDING 文件是否存在
ls -la /etc/node-role/FIRSTBOOT_PENDING    # 应该存在

# 检查 firstboot.service 状态
systemctl status firstboot

# 手动触发(调试用)
touch /etc/node-role/FIRSTBOOT_PENDING
systemctl start firstboot
journalctl -fu firstboot
```

### 11.5 detect.sh 找不到节点配置(404)

```bash
# 检查 API 服务
curl -s "http://172.16.3.10:8888/api/node-env?mac=节点真实MAC"
# 如果 404,说明 nodes.json 里的 MAC 与实际不符

# 查看节点实际 MAC
ssh root@172.16.3.170 'cat /sys/class/net/ens160/address'

# 更新 nodes.json 里对应的 MAC
vi /opt/node-config-api/nodes.json
systemctl restart node-config-api
```

### 11.6 NFS 挂载超时(slave-01 等不到 subswath-01)

```bash
# 确认 subswath-01 已完成 firstboot 且 NFS Server 运行
ssh root@172.16.3.170 'systemctl status nfs-server && showmount -e localhost'

# 检查 100G 数据面网络连通性
ssh root@172.16.3.51 'ping -c3 100.1.1.170'   # slave -> subswath 100G

# 如果不通,检查 subswath-01 的 ens192 配置
ssh root@172.16.3.170 'ip addr show ens192'    # 应该有 100.1.1.170/24
```

---

## 附录:与真实鲲鹏环境的差异对照

| 验证项目 | 虚拟机环境 | 真实鲲鹏环境 | 影响 |
|---|---|---|---|
| **CPU 架构** | x86_64 | aarch64(鲲鹏) | 镜像和内核需换,脚本逻辑**不变** |
| **PXE EFI 文件** | `grubx64.efi` | `grubaa64.efi` + `shimaa64.efi` | GRUB cfg 的 `linuxefi`→`linux` |
| **网口命名** | `ens160` / `ens192` | `eno1` / `eno2`(鲲鹏) | nodes.json `ctrl_nic` 字段 |
| **系统盘设备名** | `/dev/sda` | `/dev/sda`(RAID1 后相同) | **无差异** |
| **网络带宽** | VMware 内部(软件限速) | 10G/100G 物理网络 | 功能验证**无影响** |
| **DPDK 绑定** | 无法测试(无 DPDK 虚拟化) | HNS DPDK 驱动 | 仅影响 80-dpdk-bind.sh |
| **RDMA** | 无法测试 | RoCEv2 硬件 | 仅影响 RDMA 相关业务 |
| **大页内存** | 设为 0(VM 内存不足) | 100×1G hugepages | grubby 命令相同,仅参数不同 |
| **SubSwath RAID** | 2 盘 RAID1(代替 4 盘 RAID10) | 4×7.68T NVMe RAID10 | mdadm 命令逻辑**完全相同** |
| **BMC 管理面** | 不单独模拟 | 独立 GE 交换机 | ipmitool 相关操作无法测试 |

**结论**:通过本验证方案成功跑通后,在真实鲲鹏环境中:
1. 将 nodes.json 中 `ctrl_nic` 改为鲲鹏实际网口名(`eno1`)
2. 将 GRUB cfg 的 `grubx64.efi` 改为 `grubaa64.efi`
3. 将 `grub2-install --target=x86_64-efi` 改为 `--target=arm-efi`
4. 替换镜像为 aarch64 版本

---

## 12 实测问题记录(2026-05-08)

### 问题1:安装 GoldenOS 时 ISO 挂载卡住

**现象**:在 VMware 中用 ISO 安装 GoldenOS VM 时,安装过程中卡住无法继续。

**原因排查**:
- ISO 中的默认安装流程尝试从网络下载额外软件包(GoldenOS 的默认源),而 VM 没有外网
- 虚拟磁盘空间分配不足(建议至少 60GB)

**解决方案**:

```bash
# 方法1:在安装时先挂载本地 ISO 作为安装源
# 安装器界面 → Installation Source → 选择本地 ISO 文件

# 方法2:VM 磁盘扩容(事后)
# 在 VMware 中:VM Settings → Hard Disk → Expand → 设置更大容量
# 扩容后在 VM 内扩展分区:
growpart /dev/sda 2
xfs_growfs /
```

**实测经验**: 使用 OpenEuler 22.03 LTS SP3 x86_64 Everything ISO,在安装源设置中选择本地 ISO 即可避免联网,安装顺利完成。

---

### 问题2:PXE 部署后节点不带 GoldenOS 上安装的软件和目录

**现象**:PXE 引导后节点启动成功,但 GoldenOS 上手动安装的软件、创建的目录、配置的服务都不存在。

**根本原因**:

```
GoldenOS VM(已安装软件) ←─ 未打包 ─→ base.tar.zst(旧版本,仍是最小化 buildroot)
                                              ↑
                                   PXE 部署时节点下载的是这个
```

PXE 节点部署时执行的 `deploy.sh` 只会下载 `base.tar.zst` 并解压到磁盘。
**如果 `base.tar.zst` 里没有你安装的软件,部署后自然不会有。**

**解决方案:在 GoldenOS 上安装好所有软件后,必须重新打包为 `base.tar.zst`**

```bash
# ── 在 GoldenOS VM 上执行 ──

# 确认已安装的软件在系统中
rpm -qa | sort > /tmp/pkg-list.txt
cat /tmp/pkg-list.txt

# 清理临时文件(减小镜像体积)
dnf clean all
rm -rf /tmp/* /var/tmp/* /root/.bash_history

# 打包整个系统(排除虚拟文件系统)
tar --zstd -cpf /tmp/base.tar.zst \
    --numeric-owner \
    --exclude='/proc/*' \
    --exclude='/sys/*' \
    --exclude='/dev/*' \
    --exclude='/tmp/*' \
    --exclude='/run/*' \
    --exclude='/mnt/*' \
    --exclude='/media/*' \
    --exclude='/var/cache/dnf/*' \
    -C / .

echo "GoldenOS 镜像大小:"
du -sh /tmp/base.tar.zst

# ── 从 GoldenOS 将镜像传到 PXE-Host ──
scp /tmp/base.tar.zst root@172.16.3.10:/var/www/html/images/base.tar.zst

# ── 在 PXE-Host 上验证镜像 ──
sha256sum /var/www/html/images/base.tar.zst > /var/www/html/images/SHA256SUMS
curl -I http://172.16.3.10/images/base.tar.zst   # 确认 HTTP 可访问
```

> ⚠️ **重要**: 每次在 GoldenOS 上修改软件/配置后,都必须重新执行上述打包步骤,  
> 否则 PXE 部署出来的节点仍然是旧版本。

---

### 问题3:GoldenOS 与 buildroot 方案的选择

| 方案 | 说明 | 优点 | 缺点 |
|---|---|---|---|
| **buildroot 方案**(§5) | 在 PXE-Host 上用 `dnf --installroot` 构建最小化镜像 | 镜像体积小(~500MB);全部脚本化,可重复 | 配置灵活度低;需要在脚本里指定所有包 |
| **GoldenOS 方案** | 手动搭建一台完整 VM,安装配置好后打包 | 可交互式安装调试;所见即所得 | 镜像体积大(~2-4GB);需要手动维护 |

**建议流程(GoldenOS 方案)**:

```
1. 创建 GoldenOS VM(从 ISO 安装)
2. 配置网络、安装所需软件、创建目录结构
3. 写入 firstboot 脚本到 /etc/node-role/
4. 打包 → scp 到 PXE-Host
5. 节点 PXE 启动 → 下载镜像 → 解压 → 重启 → firstboot 运行
```

---

### 问题4:TFTP 文件权限导致节点 PXE 启动一直返回 Boot Manager

**现象**:节点 DHCP 获取到 IP、也下载了 `grubx64.efi`,但 GRUB 界面无法出现,一直循环回 UEFI Boot Manager。

**原因**: `grubx64.efi` 从 `/boot/efi/EFI/openEuler/` 复制过来权限是 `700`,TFTP 服务以非 root 用户运行,无读取权限。

**修复**:
```bash
chmod 644 /var/lib/tftpboot/*
chmod 644 /var/lib/tftpboot/grub.cfg
systemctl restart tftp.socket
```

---

### 问题5:DHCP class 匹配失败导致节点拿不到 PXE filename

**现象**:节点 DHCP 获取到 IP,但拿不到 `filename`(即 `grubx64.efi`),无法触发 PXE 引导。

**原因**: VMware x86_64 UEFI 发出的 DHCP Discover 携带 `PXEClient:Arch:00009`(64位 EFI),而文档中用 `class "PXEClient:Arch:00007"` 匹配的是 32 位 EFI,两者不符导致 filename 不下发。

**修复**: 去掉 class 匹配,直接在 subnet 层配置 `filename`:
```conf
subnet 172.16.3.0 netmask 255.255.255.0 {
    range 172.16.3.100 172.16.3.110;
    option routers 172.16.3.1;
    next-server 172.16.3.10;
    filename "grubx64.efi";    # 直接在 subnet 配置,对所有客户端生效
}
```

**其余所有逻辑完全不需要修改。**

---

*验证方案版本:v1 | 对应部署方案:cluster-kunpeng-deploy-v2.md*

---

## 附录B:OpenEuler 22.03 适配与实战问题记录

> 本附录记录实际验证过程中遇到的所有问题及解决方案，按发现顺序排列。
> 验证环境：Windows 11 + VMware Workstation Pro + OpenEuler 22.03-LTS-SP3 x86_64

---

### B.1 PXE-Host VM 内存不足导致安装卡死

**现象**：挂载 OpenEuler ISO 启动安装时，anaconda 安装器界面一直黑屏，按 Enter/Ctrl+L 无响应。

**原因**：VM 内存只有 768MB，OpenEuler 的 anaconda 安装器最低需要 1.5GB，内存不足导致 TUI 无法渲染。

**解决**：关机后将 VM 内存调整至 **4096MB**，硬盘调整至 **60GB**，重新启动安装。

---

### B.2 Minimal 安装没有 ifconfig

**现象**：安装完成后执行 `ifconfig` 报 `command not found`。

**原因**：`ifconfig` 属于 `net-tools` 包，OpenEuler minimal 安装不包含。

**解决**：使用 `ip a`（等价于 `ifconfig -a`）替代。无需安装额外包。

```bash
ip a          # 查看所有网口和 IP
ip a show     # 同上
```

---

### B.3 网络配置（minimal 安装后无网络）

**现象**：安装完成后节点之间无法互通，SSH 不通。

**解决**：使用 `nmtui` 配置网口静态 IP（nmtui 在 minimal 安装中已包含）：

```bash
nmtui  # 进入图形化配置
# Edit a connection → 选择网口 → 手动配置 IP/掩码/网关
nmcli con up ens36   # 激活连接
```

---

### B.4 jq 包不在 OpenEuler 本地 ISO 中

**现象**：执行 `dnf install -y jq` 报找不到包。

**原因**：`jq` 不在 OpenEuler 22.03 的标准 ISO 中，且实际上 detect.sh 和 API 均不依赖 jq（API 返回的是 shell 可 source 的 KEY=VALUE 纯文本格式）。

**解决**：**去掉 jq**，安装命令中不包含该包。

---

### B.5 tar 命令未预装

**现象**：执行 `tar --zstd -cpf ...` 报 `-bash: tar: command not found`。

**原因**：OpenEuler minimal 安装不包含 `tar`。

**解决**：在安装服务包时显式添加 `tar`：

```bash
dnf install -y tar
```

---

### B.6 密码长度不足 8 位被拒绝

**现象**：chroot 内执行 `echo "root:root123" | chpasswd` 报 `BAD PASSWORD: The password is shorter than 8 characters`。

**原因**：OpenEuler 默认 PAM 密码策略要求最少 8 位。

**解决**：使用 8 位及以上密码，例如 `Huawei12#`：

```bash
chroot /opt/buildroot-x86 bash -c 'echo "root:Huawei12#" | chpasswd'
```

---

### B.7 PXE-Host IP 地址与网口名不同于文档

**现象**：文档使用 `172.16.3.10` 和 `ens160`，实际 VMware 分配的网口名为 `ens36`，IP 配置为 `172.16.3.166`。

**原因**：VMware Workstation 网口命名与文档假设的不同，IP 由实际配置决定。

**影响**：以下文件/配置需全部使用实际 IP 和网口名：
- detect.sh、firstboot-main.sh 中的 IP 地址
- grub.cfg 中的 `pxe_server=`
- dhcpd.conf 中的 `next-server` 和 `domain-name-servers`
- nodes.json 中的 `ctrl_gw`
- /etc/sysconfig/dhcpd 中的 `DHCPDARGS`

**操作**：确认实际 IP 后全局替换：

```bash
# 更新 firstboot 脚本中的 IP
sed -i 's/172.16.3.10/实际IP/g' /opt/firstboot/detect.sh
sed -i 's/172.16.3.10/实际IP/g' /opt/firstboot/firstboot-main.sh
# 同步更新 buildroot 内的副本
sed -i 's/172.16.3.10/实际IP/g' /opt/buildroot-x86/etc/node-role/detect.sh
sed -i 's/172.16.3.10/实际IP/g' /opt/buildroot-x86/etc/node-role/firstboot-main.sh
# 重新打包镜像
```

---

### B.8 DHCP 监听网口配置错误

**现象**：dhcpd 启动失败，`journalctl` 报 `No subnet declaration for ens160 (no IPv4 addresses)`。

**原因**：`/etc/sysconfig/dhcpd` 中配置的 `DHCPDARGS=ens160`，但实际网口名为 `ens36`，该网口上没有 IP 地址，dhcpd 拒绝在无 IP 的网口上监听。

**解决**：用实际网口名更新配置：

```bash
# 先确认 PXE 网口名
ip a  # 找到有 172.16.3.x 地址的网口

cat > /etc/sysconfig/dhcpd << 'EOF'
DHCPDARGS=ens36   # 替换为实际网口名
EOF
systemctl restart dhcpd
```

---

### B.9 MAC 地址获取方式错误导致 DHCP 固定 IP 绑定失败

**现象**：节点启动后 DHCP 分配到动态 IP（172.16.3.100），而非绑定的固定 IP（如 172.16.3.170）。

**原因**：从 VMware `VM Settings → Network Adapter → Advanced → MAC Address` 看到的是 `00:50:56` 开头的静态管理 MAC，而节点 PXE 网卡实际使用的是 VMware 动态生成的 `00:0c:29` 开头的 MAC，两者不同。

**解决**：让节点 VM 启动一次，从 PXE-Host 的 DHCP 日志中读取真实 MAC：

```bash
journalctl -u dhcpd | grep DHCPDISCOVER
# 输出示例: DHCPDISCOVER from 00:0c:29:c9:e7:77 via ens36
# 00:0c:29:c9:e7:77 即为真实 MAC
```

---

### B.10 DHCP 旧租约冲突

**现象**：更新 MAC 绑定后 dhcpd 日志出现红色 `uid lease 172.16.3.100 for client xx is duplicate on 172.16.3.0/24`。

**原因**：节点之前拿过动态 IP（.100），旧租约记录仍在 `dhcpd.leases` 文件中，与新固定地址冲突。

**解决**：清空租约文件并重启：

```bash
systemctl stop dhcpd
> /var/lib/dhcpd/dhcpd.leases
systemctl start dhcpd
```

> ✅ 这只是告警，不影响实际 IP 分配（节点仍会拿到正确的固定 IP）。

---

### B.11 TFTP 文件权限不足

**现象**：节点 PXE 启动时 UEFI 一直回到 Boot Manager，或用 curl 测试 TFTP 报 `Permission denied`。

**原因**：从 `/boot/efi/EFI/openEuler/` 复制的 `grubx64.efi` 保留了原始权限 `700`（仅 root 可读），TFTP 服务以非 root 用户运行，无法读取。

**解决**：复制文件后立即修改权限：

```bash
chmod 644 /var/lib/tftpboot/*
# 验证
curl -v tftp://172.16.3.166/grubx64.efi -o /tmp/test.efi
```

---

### B.12 DHCP class 架构匹配错误（PXEClient:Arch:00007 vs 00009）

**现象**：DHCP 分配了 IP，但节点收不到 `filename`，不知道去 TFTP 取什么文件，PXE 失败。

**原因**：文档中 `class "x86-uefi"` 匹配 `PXEClient:Arch:00007`（32位 EFI），但 VMware x86_64 UEFI 实际发送的是 `PXEClient:Arch:00009`（64位 EFI），class 不匹配，`filename "grubx64.efi"` 不下发。

**解决**：去掉 class 匹配，直接在 subnet 层配置 filename：

```bash
subnet 172.16.3.0 netmask 255.255.255.0 {
    range 172.16.3.100 172.16.3.110;
    option routers 172.16.3.1;
    next-server 172.16.3.166;
    filename "grubx64.efi";   # ← 直接在 subnet 层配置，所有客户端生效
}
```

---

### B.13 dracut 自定义模块在 OpenEuler 中无法加载

**现象**：dracut 报 `dracut module '99deploy' cannot be found or installed` 或 `dracut module 'dracut-initqueue' cannot be found or installed`。

**原因**：OpenEuler 22.03 的 dracut 版本对自定义模块的加载机制与 Rocky Linux 9 不同，`dracut-initqueue` 已内置无需单独指定，自定义 `99deploy` 模块报找不到。

**解决**：改用 `--include` 方式直接注入文件，不依赖模块系统：

```bash
dracut --force --no-hostonly \
    --add 'network base' \
    --include /tmp/deploy.sh /deploy.sh \
    --include /tmp/run-deploy.sh /lib/dracut/hooks/initqueue/online/99-deploy.sh \
    --install 'sgdisk mkfs.xfs mkfs.vfat partprobe wget blkid lsblk curl grep awk sed cut tr tar zstd touch sleep reboot chroot mount umount mkdir cat bash' \
    --omit 'plymouth biosdevname' \
    --kver $(rpm -q kernel --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' | tail -1) \
    /var/lib/tftpboot/initrd-x64-deploy.img
chmod 644 /var/lib/tftpboot/initrd-x64-deploy.img
```

> ⚠️ 如果之前创建过 `/usr/lib/dracut/modules.d/99deploy/` 目录，**必须删除**，否则会覆盖 `--include` 注入的新文件：
> ```bash
> rm -rf /usr/lib/dracut/modules.d/99deploy
> ```

---

### B.14 initrd 缺少必要命令（seq/head/zstd）

**现象**：节点进入 initrd 后 deploy.sh 报 `seq: command not found`、`head: command not found`，或 tar 解压失败（zstd 不可用）。

**原因**：`seq`、`head` 是 coreutils 命令，`zstd` 是独立的压缩工具，这些命令在默认 initrd 中不包含，需要用 `--install` 显式加入。另外 `tar --zstd` 依赖外部 `zstd` 二进制，也需要单独包含。

**解决**：
1. 修改 deploy.sh 避免使用 `seq` 和 `head`（用 while 循环和 awk 替代）：
```bash
# 替换 for i in $(seq 1 30)
i=0; while [ $i -lt 30 ]; do ...; i=$((i+1)); done

# 替换 head -1
awk 'NR==1'

# 替换 tar --zstd 管道
wget -q -O - "..." | zstd -d | tar -xpf - -C /newroot
```
2. 在 dracut `--install` 中加入 `zstd`（见 B.13）。

---

### B.15 pre-mount 钩子超时导致 switch-root 失败

**现象**：deploy.sh 打印 `[deploy] Downloading and extracting base image...` 后立刻出现 `[FAILED] Failed to start Switch Root`，下载实际没有完成。

**原因**：`pre-mount` 钩子有 systemd 超时限制，dracut 在后台并行寻找根文件系统，发现无根文件系统后触发 switch-root 失败，不等待 pre-mount 中的长时间下载操作。

**解决**：将钩子从 `pre-mount` 改为 **`initqueue/online`**。`initqueue/online` 在网络就绪时触发，dracut 会等待 initqueue 处理完成才进入下一阶段：

```bash
# 错误：--include /tmp/run-deploy.sh /lib/dracut/hooks/pre-mount/99-deploy.sh
# 正确：
--include /tmp/run-deploy.sh /lib/dracut/hooks/initqueue/online/99-deploy.sh
```

---

### B.16 当前验证进度（截止本次）

| 阶段 | 状态 | 说明 |
|---|---|---|
| VMware 网络配置 | ✅ | VMnet2(172.16.3.0/24) + VMnet3(100.1.1.0/24) |
| goldenos OS 安装 | ✅ | OpenEuler 22.03-LTS-SP3，IP: 172.16.3.166 |
| buildroot 构建 | ✅ | /opt/buildroot-x86，含 firstboot 脚本 |
| base.tar.zst 打包 | ✅ | /var/www/html/images/base.tar.zst |
| HTTP 服务 | ✅ | httpd 运行正常 |
| TFTP 服务 | ✅ | tftp.socket 运行，权限已修正 |
| GRUB 菜单 | ✅ | grub.cfg 配置正确 |
| DHCP 服务 | ✅ | ens36 监听，subnet 级 filename，固定 IP 绑定 |
| node-config API | ✅ | 8888 端口，返回正确 KEY=VALUE |
| deploy initrd | ✅ | --include 方式构建，含 zstd/tar 等命令 |
| 节点 PXE 引导 | ✅ | subswath-01 成功 DHCP→TFTP→GRUB→initrd |
| 磁盘分区格式化 | ✅ | GPT + EFI 512M + root xfs |
| 镜像下载解压 | ⬜ | 待验证（initqueue/online 钩子调整后） |
| GRUB 安装 | ⬜ | 待验证 |
| firstboot 触发 | ⬜ | 待验证 |
| 完整端到端验证 | ⬜ | 待验证 |
