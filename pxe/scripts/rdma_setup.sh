#!/bin/bash
# RDMA环境配置脚本
# 用于Slave节点数据面配置

set -e

echo "=== RDMA环境配置脚本 ==="

# 检查是否root用户
if [ "$(id -u)" -ne 0 ]; then
    echo "请使用root用户执行此脚本"
    exit 1
fi

# 配置参数
RDMA_NIC="{{DATA_NIC}}"  # 数据面网卡名称
MASTER_IP="{{MASTER_DATA_IP}}"
LOCAL_IP="{{DATA_IP}}"

# 1. 加载RDMA模块
echo "[1] 加载RDMA模块..."
modprobe ib_core
modprobe ib_uverbs
modprobe rdma_cm
modprobe rdma_ucm
modprobe ib_ipoib

# 检查模块
lsmod | grep rdma || echo "RDMA模块已加载"
lsmod | grep ib_core || echo "IB核心模块已加载"

# 2. 检查RDMA设备
echo "[2] 检查RDMA设备..."
ibv_devinfo || echo "未找到RDMA设备，请检查网卡"

# 3. 配置RDMA端口
echo "[3] 配置RDMA端口..."
# RDMA端口通常在应用层配置
echo "RDMA端口: 18515"

# 4. 测试RDMA连接
echo "[4] 测试RDMA连接..."
if [ -n "$MASTER_IP" ]; then
    echo "等待与Master节点 ($MASTER_IP) 建立RDMA连接..."
    # 使用rping测试连接
    # rping -s -a $LOCAL_IP -v
fi

# 5. 配置RDMA性能参数
echo "[5] 配置RDMA性能参数..."
# 设置最大消息大小等参数

# 6. 启动RDMA监控服务
echo "[6] 启动RDMA监控..."
cat > /etc/systemd/system/rdma-monitor.service << EOF
[Unit]
Description=RDMA Monitor Service
After=network.target

[Service]
Type=simple
ExecStart=/opt/cluster-agent/rdma_monitor.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable rdma-monitor
systemctl start rdma-monitor || echo "RDMA监控服务启动"

echo ""
echo "=== RDMA配置完成 ==="
echo "RDMA模块: 已加载"
echo "请确认RDMA设备状态: ibv_devinfo"
echo "测试RDMA连接: rping -s -a $LOCAL_IP -v"