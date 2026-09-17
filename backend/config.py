"""
运行时路径解析 — 兼容以下四种运行方式：
  1. 开发模式       : python main.py（__file__ 在 backend/）
  2. PyInstaller    : ./cluster-manager（sys.executable 在部署目录）
  3. 部署包直接运行  : python main.py（与上面相同）
  4. Docker 容器    : 通过 CLUSTER_MANAGER_DATA 环境变量指定数据目录
"""

import os
import sys


def _base_dir() -> str:
    # Docker / 任意环境：通过环境变量显式指定数据目录
    data_dir = os.environ.get("CLUSTER_MANAGER_DATA")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    # PyInstaller 打包后运行
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # 开发 / 部署包直接用 python 运行：此文件位于 backend/
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR      = _base_dir()
DATABASE_PATH = os.path.join(BASE_DIR, "cluster_manager.db")
PXE_DATA_DIR  = os.path.join(BASE_DIR, "pxe_data")
STATIC_DIR    = os.path.join(BASE_DIR, "static")
# PXE Host 部署 ISO 存放目录（Windows 管理站本地，通过 HTTP 暴露给 BMC）
ISO_DIR             = os.environ.get("CLUSTER_MANAGER_ISO_DIR") or os.path.join(BASE_DIR, "iso")
# 固件仓库目录: 集群节点 firstboot 阶段从此处拉取 NIC/HBA/SSD 固件
FIRMWARE_DIR        = os.environ.get("CLUSTER_MANAGER_FIRMWARE_DIR") or os.path.join(BASE_DIR, "firmware")
SCRIPTS_BUNDLE_PATH = os.path.join(BASE_DIR, "scripts_bundle.json")
os.makedirs(ISO_DIR, exist_ok=True)
os.makedirs(FIRMWARE_DIR, exist_ok=True)
