"""
Cluster Manager - FastAPI 主入口
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from sqlalchemy import text

from config import STATIC_DIR, ISO_DIR, FIRMWARE_DIR
from models.node import init_db, engine
from models.seed import seed_demo_data
from api import nodes, pxe, ipmi, network, alerts, diagnose, patrol, firmware


def _run_migrations():
    """简单列迁移：为已存在的表添加新列"""
    migrations = [
        "ALTER TABLE diag_scripts ADD COLUMN script_tab VARCHAR(20) DEFAULT 'hardware'",
        "ALTER TABLE diag_scripts ADD COLUMN output_mode VARCHAR(20) DEFAULT 'stdout'",
        # 诊断结果判定规则 + 处置建议
        "ALTER TABLE diag_scripts ADD COLUMN expect_mode VARCHAR(20) DEFAULT 'exit_code'",
        "ALTER TABLE diag_scripts ADD COLUMN expect_pattern TEXT DEFAULT ''",
        "ALTER TABLE diag_scripts ADD COLUMN suggestion TEXT DEFAULT ''",
        # v2: PXE 节点新增字段
        "ALTER TABLE nodes ADD COLUMN rdma_nics VARCHAR(100)",
        "ALTER TABLE nodes ADD COLUMN rdma_ips  VARCHAR(200)",
        "ALTER TABLE nodes ADD COLUMN dpdk_nics VARCHAR(100)",
        "ALTER TABLE nodes ADD COLUMN dpdk_ips  VARCHAR(200)",
        "ALTER TABLE nodes ADD COLUMN hugepages_1g INTEGER DEFAULT 0",
        "ALTER TABLE nodes ADD COLUMN system_disk VARCHAR(50)",
        "ALTER TABLE nodes ADD COLUMN data_disks  VARCHAR(200)",
        "ALTER TABLE nodes ADD COLUMN data_raid_level VARCHAR(20)",
        "ALTER TABLE nodes ADD COLUMN nfs_mounts  TEXT",
        "ALTER TABLE nodes ADD COLUMN nfs_export_ip VARCHAR(45)",
        "ALTER TABLE nodes ADD COLUMN nfs_exports  VARCHAR(200)",
        "ALTER TABLE nodes ADD COLUMN extra_pkgs   VARCHAR(200)",
        # 防御: 老库可能缺这两列, sync 在 INSERT 时会因为列不存在静默失败
        "ALTER TABLE nodes ADD COLUMN ctrl_status VARCHAR(20) DEFAULT 'offline'",
        "ALTER TABLE nodes ADD COLUMN data_status VARCHAR(20) DEFAULT 'offline'",
        # 节点固件版本快照(firstboot 阶段刷固件后回报)
        "ALTER TABLE nodes ADD COLUMN nic_firmware JSON",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # 列已存在则忽略

    # 确保 nodes.json 存储目录存在，并预生成默认配置
    from services.pxe_service import pxe_service_v2
    pxe_service_v2.read_nodes_json()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _run_migrations()
    seed_demo_data()
    yield


app = FastAPI(
    title="Cluster Manager",
    description="集群配置、管理、诊断系统 - 支持三平面网络架构",
    version="2.0.0",
    lifespan=lifespan
)

# CORS（开发模式前后端分离时需要；打包后同源访问仍保留）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API 路由（必须在静态文件挂载之前注册）────────────────────────────────────
app.include_router(nodes.router,   prefix="/api/nodes",   tags=["节点管理"])
app.include_router(pxe.router,     prefix="/api/pxe",     tags=["PXE部署"])
app.include_router(ipmi.router,    prefix="/api/ipmi",    tags=["IPMI/BMC"])
app.include_router(network.router, prefix="/api/network", tags=["网络配置"])
app.include_router(alerts.router,  prefix="/api/alerts",  tags=["告警管理"])
app.include_router(diagnose.router,prefix="/api/diagnose",tags=["故障诊断"])
app.include_router(patrol.router,  prefix="/api/patrol",  tags=["巡检管理"])
app.include_router(firmware.router,prefix="/api/firmware",tags=["固件仓库"])


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "2.0.0"}


# ── PXE Host 部署 ISO 目录（BMC 通过 HTTP 拉取）─────────────────────────────
# 必须在 SPA catch-all 之前挂载，否则会被 index.html 兜底拦截
if os.path.isdir(ISO_DIR):
    app.mount("/iso", StaticFiles(directory=ISO_DIR), name="iso")

# ── 固件仓库（节点 firstboot 阶段拉取 NIC/HBA/SSD 固件）─────────────────────
# 路径同样需要在 SPA catch-all 之前挂载
if os.path.isdir(FIRMWARE_DIR):
    app.mount("/firmware", StaticFiles(directory=FIRMWARE_DIR), name="firmware")


# ── 前端静态文件（打包后 static/ 目录存在则启用）────────────────────────────
# Vue Router 使用 history 模式，所有非 /api 路径均返回 index.html
if os.path.isdir(STATIC_DIR):
    # 先挂载 /assets 目录（Vite 生成的 JS/CSS hash 文件）
    _assets = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    # favicon 等根目录静态资源
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        f = os.path.join(STATIC_DIR, "favicon.ico")
        return FileResponse(f) if os.path.exists(f) else FileResponse(
            os.path.join(STATIC_DIR, "index.html")
        )

    # SPA 入口：所有其他路径返回 index.html（Vue Router 客户端路由）
    # 重要：必须显式排除 /api 和 /iso, 否则贪婪 path 匹配会优先于
    # FastAPI 的 redirect_slashes, 把 GET /api/nodes 这种无尾斜杠的请求
    # 直接兜底成 HTML, 前端 axios 拿到 HTML 解析失败 → 节点表永远是空
    from fastapi import HTTPException as _HTTPException
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith(("api/", "iso/", "firmware/")):
            raise _HTTPException(status_code=404)
        index = os.path.join(STATIC_DIR, "index.html")
        return FileResponse(index)


# ── 可执行入口（PyInstaller / python main.py 直接运行）────────────────────────
if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("CLUSTER_MANAGER_HOST", "0.0.0.0")
    port = int(os.environ.get("CLUSTER_MANAGER_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")
