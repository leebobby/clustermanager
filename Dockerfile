# ============================================================
# Cluster Manager — 多阶段构建
# 支持 linux/amd64 和 linux/arm64 双平台
#
# 在 Windows 上构建 ARM64 镜像：
#   docker buildx build --platform linux/arm64 -t cluster-manager:latest .
#
# 在 ARM 服务器上运行：
#   docker compose up -d
# ============================================================

# ── Stage 1: 构建 Vue 前端 ──────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --quiet
COPY frontend/ ./
RUN npm run build
# 产物位于 /build/dist/ → 对应 backend/static/


# ── Stage 2: Python 后端 ───────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（paramiko 需要 libffi，cryptography 需要 openssl）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（利用 Docker layer 缓存）
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端源码
COPY backend/ .

# 复制前端构建产物到 static/ 目录
COPY --from=frontend-builder /build/dist ./static

# 数据目录（DB + pxe_data 通过 volume 挂载实现持久化）
ENV CLUSTER_MANAGER_DATA=/data
RUN mkdir -p /data

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["python", "main.py"]
