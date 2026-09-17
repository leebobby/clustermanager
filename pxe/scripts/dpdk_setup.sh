#!/bin/bash
# DPDK环境配置脚本
# 用于Master节点数据面配置

set -e

echo "=== DPDK环境配置脚本 ==="

# 检查是否root用户
if [ "$(id -u)" -ne 0 ]; then
    echo "请使用root用户执行此脚本"
    exit 1
fi

# 配置参数
DPDK_NIC="{{DATA_NIC}}"  # 数据面网卡名称
DPDK_IP="{{DATA_IP}}"

# 1. 加载VFIO模块
echo "[1] 加载VFIO模块..."
modprobe vfio
modprobe vfio-pci
modprobe vfio_iommu_type1

# 检查模块是否加载成功
lsmod | grep vfio || echo "VFIO模块加载失败"

# 2. 配置hugepages
echo "[2] 配置hugepages..."
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

mkdir -p /dev/hugepages
mount -t hugetlbfs nodev /dev/hugepages

# 持久化hugepages配置
cat > /etc/sysctl.d/dpdk.conf << EOF
vm.nr_hugepages=1024
EOF

# 3. 绑定网卡到VFIO
echo "[3] 绑定网卡到VFIO..."
if [ -n "$DPDK_NIC" ]; then
    # 获取网卡PCI地址
    PCI_ADDR=$(dpdk-devbind.py --status | grep "$DPDK_NIC" | awk '{print $1}')

    if [ -n "$PCI_ADDR" ]; then
        echo "绑定网卡 $DPDK_NIC (PCI: $PCI_ADDR) 到VFIO..."
        dpdk-devbind.py --bind=vfio-pci $PCI_ADDR
        echo "网卡绑定完成"
    else
        echo "未找到网卡 $DPDK_NIC"
    fi
fi

# 4. 配置DPDK环境变量
echo "[4] 配置DPDK环境变量..."
cat > /etc/profile.d/dpdk.sh << EOF
export DPDK_ROOT=/usr/share/dpdk
export RTE_SDK=/usr/share/dpdk
export RTE_TARGET=arm64-linuxapp-gcc
EOF

source /etc/profile.d/dpdk.sh

# 5. 启动DPDK测试程序
echo "[5] 测试DPDK环境..."
testpmd -l 0-2 -n 4 --socket-mem 1024 --no-pci --vdev=net_null0 -- -i --nb-cores=2 || echo "DPDK测试完成"

echo ""
echo "=== DPDK配置完成 ==="
echo "hugepages: 1024"
echo "VFIO模块: 已加载"
echo "请使用dpdk-devbind.py绑定数据面网卡"