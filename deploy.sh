#!/bin/bash
# ============================================================
# Cluster Manager — Linux ARM 部署脚本
# 用法：将 cluster-manager-deploy.zip 解压后，在 backend/ 目录执行此脚本
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${CLUSTER_MANAGER_INSTALL_DIR:-/opt/cluster-manager}"
SERVICE_NAME="cluster-manager"
PYTHON_BIN="${PYTHON:-python3}"

echo "========================================"
echo " Cluster Manager 部署脚本"
echo " 安装目录: $INSTALL_DIR"
echo "========================================"

# ── 检查 Python ──────────────────────────────────────────────
echo ""
echo "[1/5] 检查 Python 环境..."
$PYTHON_BIN --version 2>&1 | grep -E "Python 3\.(9|10|11|12)" || {
    echo "[错误] 需要 Python 3.9+，当前版本："
    $PYTHON_BIN --version
    exit 1
}
echo "  -> $($PYTHON_BIN --version)"

# ── 安装到目标目录 ───────────────────────────────────────────
echo ""
echo "[2/5] 安装到 $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"

# 如果从项目根目录运行（build.bat 解压后的结构）
if [ -d "$SCRIPT_DIR/backend" ]; then
    cp -r "$SCRIPT_DIR/backend/." "$INSTALL_DIR/"
else
    # 已经在 backend/ 目录内
    cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
fi
echo "  -> 文件已复制到 $INSTALL_DIR"

# ── 安装 Python 依赖 ─────────────────────────────────────────
echo ""
echo "[3/5] 安装 Python 依赖..."
cd "$INSTALL_DIR"

# 使用虚拟环境隔离依赖
if [ ! -d "venv" ]; then
    $PYTHON_BIN -m venv venv
    echo "  -> 已创建虚拟环境 venv/"
fi

source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  -> 依赖安装完成"

# ── 生成启动脚本 ─────────────────────────────────────────────
echo ""
echo "[4/5] 生成启动脚本..."
cat > "$INSTALL_DIR/start.sh" << STARTEOF
#!/bin/bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
cd "\$SCRIPT_DIR"
source venv/bin/activate

HOST="\${CLUSTER_MANAGER_HOST:-0.0.0.0}"
PORT="\${CLUSTER_MANAGER_PORT:-8000}"

echo "Starting Cluster Manager..."
echo "  Frontend : http://\$(hostname -I | awk '{print \$1}'):\$PORT"
echo "  API Docs : http://\$(hostname -I | awk '{print \$1}'):\$PORT/docs"

python main.py
STARTEOF
chmod +x "$INSTALL_DIR/start.sh"
echo "  -> start.sh 已生成"

# ── 注册 systemd 服务 ────────────────────────────────────────
echo ""
echo "[5/5] 配置 systemd 服务..."

cat > /etc/systemd/system/${SERVICE_NAME}.service << SVCEOF
[Unit]
Description=Cluster Manager Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/main.py
Environment=CLUSTER_MANAGER_HOST=0.0.0.0
Environment=CLUSTER_MANAGER_PORT=8000
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl restart ${SERVICE_NAME}
echo "  -> systemd 服务已启动"

# ── 部署完成 ─────────────────────────────────────────────────
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================"
echo " 部署成功！"
echo "========================================"
echo ""
echo " 服务状态 : systemctl status $SERVICE_NAME"
echo " 查看日志 : journalctl -u $SERVICE_NAME -f"
echo " 停止服务 : systemctl stop $SERVICE_NAME"
echo ""
echo " Windows 浏览器访问："
echo "   http://$LOCAL_IP:8000"
echo "========================================"
