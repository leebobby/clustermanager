#!/bin/bash
# PXE服务器安装配置脚本
# 用于openEuler-ARM集群自动化部署

set -e

echo "=== PXE服务器配置脚本 ==="
echo "配置三平面网络PXE部署环境"

# 配置参数
TFTP_DIR="/tftpboot"
NFS_DIR="/nfs/openEuler"
DHCP_CONF="/etc/dhcp/dhcpd.conf"
PXE_SERVER_IP="192.168.1.10"

# 1. 安装必要服务
echo "[1] 安装必要服务..."
yum install -y tftp-server dhcp-server nfs-utils xinetd

# 2. 配置TFTP服务
echo "[2] 配置TFTP服务..."
mkdir -p $TFTP_DIR
mkdir -p $TFTP_DIR/pxelinux.cfg

# 复制引导文件
cp /usr/share/syslinux/pxelinux.0 $TFTP_DIR/
cp /usr/share/syslinux/ldlinux.c32 $TFTP_DIR/

# 配置TFTP服务
cat > /etc/xinetd.d/tftp << EOF
service tftp
{
    socket_type = dgram
    protocol = udp
    wait = yes
    user = root
    server = /usr/sbin/in.tftpd
    server_args = -s $TFTP_DIR
    disable = no
    per_source = 11
    cps = 100 2
    flags = IPv4
}
EOF

# 3. 配置DHCP服务
echo "[3] 配置DHCP服务..."
cat > $DHCP_CONF << EOF
# DHCP配置 - Cluster Manager PXE
# 管理面网络 (GE口)

subnet 192.168.1.0 netmask 255.255.255.0 {
    option routers 192.168.1.1;
    option domain-name-servers 8.8.8.8;
    option subnet-mask 255.255.255.0;
    range 192.168.1.200 192.168.1.250;

    # PXE引导配置
    next-server $PXE_SERVER_IP;
    filename "pxelinux.0";

    option root-path "$NFS_DIR";
}
EOF

# 4. 配置NFS服务
echo "[4] 配置NFS服务..."
mkdir -p $NFS_DIR

cat >> /etc/exports << EOF
$NFS_DIR *(rw,sync,no_root_squash)
EOF

# 5. 创建默认PXE配置
echo "[5] 创建默认PXE引导配置..."
cat > $TFTP_DIR/pxelinux.cfg/default << EOF
DEFAULT menu
PROMPT 0
TIMEOUT 30
MENU TITLE Cluster PXE Boot Menu

LABEL local
    MENU LABEL Boot from local disk
    LOCALBOOT 0

LABEL openEuler
    MENU LABEL Install openEuler-ARM
    KERNEL vmlinuz
    APPEND initrd=initrd.img inst.repo=http://$PXE_SERVER_IP/openEuler/
EOF

# 6. 准备openEuler引导文件
echo "[6] 请将openEuler ISO中的以下文件复制到 $TFTP_DIR:"
echo "  - vmlinuz"
echo "  - initrd.img"
echo ""
echo "并挂载ISO到 $NFS_DIR 或配置HTTP服务器"

# 7. 启动服务
echo "[7] 启动服务..."
systemctl enable tftp
systemctl enable dhcpd
systemctl enable nfs-server
systemctl enable xinetd

systemctl start tftp
systemctl start dhcpd
systemctl start nfs-server
systemctl start xinetd

# 8. 配置防火墙
echo "[8] 配置防火墙..."
firewall-cmd --permanent --add-service=tftp
firewall-cmd --permanent --add-service=dhcp
firewall-cmd --permanent --add-service=nfs
firewall-cmd --reload

echo ""
echo "=== PXE服务器配置完成 ==="
echo "TFTP目录: $TFTP_DIR"
echo "NFS目录: $NFS_DIR"
echo "DHCP配置: $DHCP_CONF"
echo ""
echo "下一步操作:"
echo "1. 将openEuler ARM ISO文件挂载或复制到 $NFS_DIR"
echo "2. 复制引导文件(vmlinuz, initrd.img)到 $TFTP_DIR"
echo "3. 使用Cluster Manager API添加节点并启动部署"