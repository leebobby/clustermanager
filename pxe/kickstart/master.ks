# Kickstart配置模板 - Master节点
# 包含三平面网络配置和DPDK环境
# 由Cluster Manager自动生成

# 基础配置
lang en_US.UTF-8
keyboard us
timezone Asia/Shanghai --utc

# 认证配置
auth --enableshadow --passalgo=sha512
rootpw --plaintext {{ROOT_PASSWORD}}

# 安装源
url --url=http://{{PXE_SERVER}}/openEuler/

# 分区配置
autopart --type=lvm

# 网络配置 - 三平面
# 管理面 (eth0) - GE口 - 用于BMC管理和SSH访问
network --device=eth0 --bootproto=static --ip={{MGMT_IP}} --netmask={{MGMT_NETMASK}} --gateway={{MGMT_GATEWAY}} --nameserver={{DNS_SERVERS}} --hostname={{HOSTNAME}} --activate

# 控制面 (eth1) - 10GE - 用于心跳检测和配置同步
network --device=eth1 --bootproto=static --ip={{CTRL_IP}} --netmask={{CTRL_NETMASK}} --gateway={{CTRL_GATEWAY}} --noipv6 --activate

# 数据面 (eth2) - 100GE - 用于DPDK数据接收
network --device=eth2 --bootproto=static --ip={{DATA_IP}} --netmask={{DATA_NETMASK}} --noipv6 --activate

# 安装包
%packages
@core
@base
openssh-server
openssh-clients
python3
python3-pip
vim
net-tools
tar
gzip
# DPDK相关包
dpdk
dpdk-tools
libdpdk
vfio-utils
%end

# 后置脚本
%post --log=/root/ks-post.log
#!/bin/bash

echo "=== Master节点后配置脚本 ==="
echo "时间: $(date)"

# 1. DPDK环境配置
echo "[1] 配置DPDK环境..."

# 加载VFIO模块
modprobe vfio
modprobe vfio-pci
modprobe vfio_iommu_type1

# 设置开机自动加载
cat > /etc/modules-load.d/dpdk.conf << 'MODCONF'
vfio
vfio-pci
vfio_iommu_type1
MODCONF

# 配置IOMMU
if [ -f /proc/cmdline ]; then
    sed -i 's/GRUB_CMDLINE_LINUX="/GRUB_CMDLINE_LINUX="intel_iommu=on iommu=pt /' /etc/default/grub
    grub2-mkconfig -o /boot/grub2/grub.cfg
fi

# 2. 配置数据面网卡绑定DPDK
echo "[2] 准备DPDK网卡绑定..."
# 实际绑定需要在系统启动后手动执行
# dpdk-devbind.py --bind=vfio-pci eth2

echo "DPDK配置脚本已准备，请系统启动后手动绑定网卡"

# 3. 安装监控Agent
echo "[3] 安装监控Agent..."
mkdir -p /opt/cluster-agent
curl -s http://{{PXE_SERVER}}:8000/agent/install.sh -o /opt/cluster-agent/install.sh
chmod +x /opt/cluster-agent/install.sh
/opt/cluster-agent/install.sh

# 4. 注册到管理平台
echo "[4] 注册到管理平台..."
curl -X POST http://{{PXE_SERVER}}:8000/api/nodes/register \
    -H "Content-Type: application/json" \
    -d '{"hostname":"{{HOSTNAME}}","node_type":"master","mgmt_ip":"{{MGMT_IP}}","ctrl_ip":"{{CTRL_IP}}","data_ip":"{{DATA_IP}}","data_protocol":"DPDK"}'

# 5. 配置心跳服务
echo "[5] 配置心跳服务..."
cat > /opt/heartbeat/config.json << 'HBCONF'
{
    "mgmt_ip": "{{MGMT_IP}}",
    "ctrl_ip": "{{CTRL_IP}}",
    "server": "{{PXE_SERVER}}",
    "port": 8000,
    "interval": 10
}
HBCONF

echo "=== 后配置脚本完成 ==="
%end

# 安装完成后重启
reboot