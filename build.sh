#!/bin/bash
# ============================================================
#  Cluster Manager — 构建入口(兼容保留)
#
#  构建流程的实际实现在 build_app.py(跨平台, 唯一一份)。
#  本脚本只是转发, 默认按 server 模式构建(无图形环境的 Linux 服务器):
#
#      ./build.sh                    等价于 python3 build_app.py --mode server
#      ./build.sh --skip-frontend    额外参数原样透传
#
#  产物: backend/dist/cluster-manager/ + cluster-manager-linux-<arch>-server.tar.gz
# ============================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "[错误] 未找到 python3, 请先安装 Python 3.10+" >&2
    exit 1
fi

exec "$PY" "$DIR/build_app.py" --mode server "$@"
