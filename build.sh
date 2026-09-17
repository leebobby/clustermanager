#!/bin/bash
# ============================================================
# Cluster Manager — ARM 构建脚本
#
# 运行环境：OpenEuler / Rocky Linux aarch64（构建机）
#   需要：Node.js ≥ 18、Python ≥ 3.10、pip
#
# 产物：cluster-manager-linux-arm64.tar.gz
#   解压后直接运行 ./cluster-manager/start.sh
#   生产机无需安装 Python / Node / pip
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
BACKEND_DIR="$SCRIPT_DIR/backend"
DIST_DIR="$BACKEND_DIR/dist/cluster-manager"
ARCH="$(uname -m)"                          # aarch64 / x86_64
PKG_NAME="cluster-manager-linux-${ARCH}.tar.gz"
PKG_PATH="$SCRIPT_DIR/$PKG_NAME"

echo "========================================================"
echo " Cluster Manager 构建脚本"
echo " 架构: $ARCH"
echo "========================================================"

# ── 前置检查 ─────────────────────────────────────────────────
check_cmd() {
    command -v "$1" &>/dev/null || { echo "[错误] 未找到 $1，请先安装"; exit 1; }
}
check_cmd node
check_cmd npm
check_cmd python3
check_cmd pip3

echo ""
echo "  node   : $(node -v)"
echo "  python : $(python3 --version)"

# ── 步骤 1：构建前端 ─────────────────────────────────────────
echo ""
echo "[1/4] 构建前端 (npm run build) ..."
cd "$FRONTEND_DIR"
npm install --prefer-offline 2>/dev/null || npm install
npm run build
# 产物已输出到 backend/static/（vite.config.js 配置）
echo "  -> 前端已构建到 backend/static/"

# ── 步骤 2：安装 Python 依赖（仅构建机需要）────────────────
echo ""
echo "[2/4] 安装 Python 依赖（构建机专用，生产机不需要）..."
cd "$BACKEND_DIR"
pip3 install -r requirements.txt -q
pip3 install pyinstaller -q
echo "  -> 依赖安装完成"

# ── 步骤 3：PyInstaller 打包 ─────────────────────────────────
echo ""
echo "[3/4] PyInstaller 打包 ..."
cd "$BACKEND_DIR"
pyinstaller cluster_manager.spec --clean --noconfirm

# static/ 不在 spec 的 datas 里，手动复制到 dist 目录
# 这样 config.py 里 BASE_DIR=dirname(sys.executable) 能直接找到 static/
echo "  -> 复制前端静态文件到 dist/ ..."
cp -r "$BACKEND_DIR/static" "$DIST_DIR/static"
echo "  -> PyInstaller 打包完成: $DIST_DIR"

# ── 步骤 4：写入辅助文件，打包 tar.gz ────────────────────────
echo ""
echo "[4/4] 打包发布包 ..."

# start.sh：生产机直接运行
cat > "$DIST_DIR/start.sh" << 'EOF'
#!/bin/bash
# Cluster Manager 启动脚本（生产机直接运行，无需任何依赖）
cd "$(dirname "${BASH_SOURCE[0]}")"

HOST="${CLUSTER_MANAGER_HOST:-0.0.0.0}"
PORT="${CLUSTER_MANAGER_PORT:-8000}"

LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo "================================================"
echo " Cluster Manager 启动中..."
echo " 前端界面: http://$LOCAL_IP:$PORT"
echo " API 文档: http://$LOCAL_IP:$PORT/docs"
echo " 停止服务: Ctrl+C"
echo "================================================"

./cluster-manager
EOF
chmod +x "$DIST_DIR/start.sh"

# install-service.sh：注册为 systemd 开机自启服务（可选）
cat > "$DIST_DIR/install-service.sh" << 'SVCEOF'
#!/bin/bash
# 将 Cluster Manager 注册为 systemd 服务（开机自启）
# 用法：sudo ./install-service.sh [安装目录，默认 /opt/cluster-manager]
set -e

INSTALL_DIR="${1:-/opt/cluster-manager}"
SERVICE_FILE="/etc/systemd/system/cluster-manager.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "安装到: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/cluster-manager" "$INSTALL_DIR/start.sh"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Cluster Manager Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/cluster-manager
Environment=CLUSTER_MANAGER_HOST=0.0.0.0
Environment=CLUSTER_MANAGER_PORT=8000
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cluster-manager

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cluster-manager
systemctl restart cluster-manager

LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "your-server-ip")
echo ""
echo "================================================"
echo " 服务已注册并启动！"
echo " 前端界面: http://$LOCAL_IP:8000"
echo " 查看日志: journalctl -u cluster-manager -f"
echo " 停止服务: systemctl stop cluster-manager"
echo "================================================"
SVCEOF
chmod +x "$DIST_DIR/install-service.sh"

# 打包成 tar.gz
cd "$BACKEND_DIR/dist"
tar -czf "$PKG_PATH" cluster-manager/
echo "  -> 发布包: $PKG_PATH ($(du -sh "$PKG_PATH" | cut -f1))"

# ── 构建完成 ─────────────────────────────────────────────────
echo ""
echo "========================================================"
echo " 构建成功！"
echo "========================================================"
echo ""
echo " 发布包: $PKG_NAME"
echo ""
echo " ── 部署到生产机（无需安装任何依赖）────────────────"
echo ""
echo " 1. 传输到生产机："
echo "    scp $PKG_NAME root@<prod-ip>:/opt/"
echo ""
echo " 2a. 直接运行："
echo "    ssh root@<prod-ip> 'cd /opt && tar -xzf $PKG_NAME && ./cluster-manager/start.sh'"
echo ""
echo " 2b. 注册开机自启服务："
echo "    ssh root@<prod-ip> 'cd /opt && tar -xzf $PKG_NAME && cd cluster-manager && sudo ./install-service.sh'"
echo ""
echo " 3. Windows 浏览器访问："
echo "    http://<prod-ip>:8000"
echo "========================================================"
