"""
PXE 部署 API v2 - 鲲鹏集群 22 节点三平面部署
"""

import asyncio
import functools
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# 规划自动生成的主机名模板: master-01 / slave-12 / subswath-02 / gstorage-01 / acquisition-03
# 两位以上数字, 严格区分 demo seed 的 master-1 / slave-3 (单位数字, 保留)
_PLAN_HOSTNAME_RE = re.compile(r'^(master|slave|subswath|gstorage|acquisition)-\d{2,}$')

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime

_executor = ThreadPoolExecutor(max_workers=8)


def _ssh_run(host: str, user: str, password: Optional[str], port: int, script: str) -> str:
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs: Dict[str, Any] = {
            "hostname": host, "port": port,
            "username": user, "timeout": 30,
        }
        if password:
            connect_kwargs["password"] = password
        client.connect(**connect_kwargs)
        _, stdout, stderr = client.exec_command(script, timeout=120)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return (out + (("\nSTDERR:\n" + err) if err.strip() else "")).strip()
    finally:
        client.close()

from models.node import Node, PXEConfig, get_db
from pydantic import BaseModel
from services.pxe_service import pxe_service_v2
from services.redfish_service import RedfishClient
from config import ISO_DIR


router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class PXEConfigCreate(BaseModel):
    name: str
    mgmt_subnet: str = "172.16.0.0/24"
    ctrl_subnet: str = "172.16.3.0/24"
    data_subnet: str = "100.1.0.0/16"
    mgmt_gateway: Optional[str] = None
    ctrl_gateway: Optional[str] = "172.16.3.1"
    data_gateway: Optional[str] = None
    dns_servers: Optional[str] = "172.16.3.10"


class PXEConfigResponse(BaseModel):
    id: int
    name: str
    mgmt_subnet: str
    ctrl_subnet: str
    data_subnet: str
    mgmt_gateway: Optional[str]
    ctrl_gateway: Optional[str]
    data_gateway: Optional[str]
    dns_servers: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class NetworkPlanRequest(BaseModel):
    """v2 IP 规划请求（固定六子网，仅需确认各角色数量，允许为 0）"""
    master_count: int = 6
    slave_count: int = 12
    subswath_count: int = 2
    gstorage_count: int = 1
    acquisition_count: int = 0


class DeployRequest(BaseModel):
    node_id: int
    node_type: str  # master / slave / subswath / gstorage
    mgmt_ip: str
    ctrl_ip: str
    data_ip: str
    hostname: Optional[str] = None


class DeployStatus(BaseModel):
    node_id: int
    hostname: str
    status: str
    stage: str
    progress: int
    message: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime] = None
    bmc_ip: Optional[str] = None
    ctrl_ip: Optional[str] = None
    data_ip: Optional[str] = None


# ── 既有端点（保持兼容）──────────────────────────────────────────────────────

@router.get("/configs", response_model=List[PXEConfigResponse])
def get_pxe_configs(db: Session = Depends(get_db)):
    """获取所有 PXE 配置"""
    return db.query(PXEConfig).all()


@router.post("/config", response_model=PXEConfigResponse)
def create_pxe_config(config: PXEConfigCreate, db: Session = Depends(get_db)):
    """创建 PXE 部署配置"""
    db_config = PXEConfig(**config.dict())
    db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return db_config


_STAGE_LABELS = {
    "deploying":   "等待 PXE 引导...",
    "installing":  "正在安装操作系统...",
    "configuring": "正在配置节点...",
}
_STAGE_PROGRESS = {
    "deploying":   20,
    "installing":  55,
    "configuring": 80,
}


@router.get("/status")
def get_deploy_status(db: Session = Depends(get_db)):
    """获取正在部署的节点状态"""
    nodes = db.query(Node).filter(
        Node.status.in_(["deploying", "installing", "configuring"])
    ).all()
    return [
        DeployStatus(
            node_id=node.id,
            hostname=node.hostname,
            status=node.status,
            stage=_STAGE_LABELS.get(node.status, node.status),
            progress=_STAGE_PROGRESS.get(node.status, 50),
            message="正在部署，等待 firstboot 回报...",
            started_at=node.created_at,
            bmc_ip=node.bmc_ip,
            ctrl_ip=node.ctrl_ip,
            data_ip=node.data_ip,
        )
        for node in nodes
    ]


@router.post("/nodes/{node_id}/deploy")
async def deploy_node(
    node_id: int,
    request: DeployRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """部署指定节点"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    node.hostname = request.hostname or node.hostname
    node.node_type = request.node_type
    node.mgmt_ip = request.mgmt_ip
    node.ctrl_ip = request.ctrl_ip
    node.data_ip = request.data_ip
    node.data_protocol = "DPDK" if request.node_type == "master" else "RDMA"
    node.status = "deploying"
    db.commit()

    return {
        "node_id": node_id,
        "hostname": node.hostname,
        "status": "deploying",
        "message": "部署任务已启动，请等待完成",
        "network_config": {
            "management_bmc": request.mgmt_ip,
            "control_10ge": request.ctrl_ip,
            "data_100ge": request.data_ip,
        },
    }


@router.post("/batch-deploy")
async def batch_deploy_nodes(
    nodes: List[DeployRequest],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """批量部署多个节点"""
    results = []
    for req in nodes:
        node = db.query(Node).filter(Node.id == req.node_id).first()
        if node:
            node.hostname = req.hostname or node.hostname
            node.node_type = req.node_type
            node.mgmt_ip = req.mgmt_ip
            node.ctrl_ip = req.ctrl_ip
            node.data_ip = req.data_ip
            node.data_protocol = "DPDK" if req.node_type == "master" else "RDMA"
            node.status = "deploying"
            results.append({
                "node_id": req.node_id,
                "hostname": node.hostname,
                "status": "deploying",
            })
    db.commit()
    return {"message": "批量部署已启动", "total_nodes": len(nodes), "results": results}


@router.get("/kickstart/{node_type}")
def get_kickstart_template(node_type: str):
    """v2 改用 firstboot 差异化注入，此接口返回各角色特性说明"""
    role_features = {
        "master":   ["100G×4 DPDK+RDMA", "大页内存 100×1G", "无数据盘"],
        "slave":    ["100G×1 RDMA 计算", "NFS 客户端三路挂载"],
        "subswath": ["100G×2 双平面独立 IP", "4×7.68T NVMe 软件 RAID10", "NFS Server 导出"],
        "gstorage": ["100G×1 RDMA-2", "硬件 RAID50（BMC 预配置）", "NFS Server 归档"],
    }
    if node_type not in role_features:
        raise HTTPException(status_code=400, detail="node_type 必须为 master/slave/subswath/gstorage")
    return {
        "node_type": node_type,
        "deployment_method": "firstboot 差异化注入（base.tar.zst + nodes.json）",
        "features": role_features[node_type],
    }


# ── v2 新增端点 ───────────────────────────────────────────────────────────────

@router.post("/network-plan")
def plan_network_ips(request: NetworkPlanRequest):
    """
    v2 六子网 IP 规划
    管理面 172.16.0.0/24 | 控制面 172.16.3.0/24 |
    DPDK-1 200.1.1.0/24 | DPDK-2 200.1.2.0/24 |
    RDMA-1 100.1.1.0/24 | RDMA-2 100.1.2.0/24
    """
    return pxe_service_v2.generate_ip_plan(
        master_count=request.master_count,
        slave_count=request.slave_count,
        subswath_count=request.subswath_count,
        gstorage_count=request.gstorage_count,
        acquisition_count=request.acquisition_count,
    )


@router.get("/nodes-json")
def get_nodes_json():
    """获取当前 nodes.json（节点配置清单）"""
    return pxe_service_v2.read_nodes_json()


@router.post("/nodes-json")
def update_nodes_json(data: Dict[str, Any]):
    """更新 nodes.json（保存 MAC→配置 映射）"""
    pxe_service_v2.write_nodes_json(data)
    node_count = sum(1 for k in data if not k.startswith("_"))
    return {"message": "nodes.json 已更新", "node_count": node_count}


@router.get("/nodes-json/node-list")
def get_node_list():
    """获取节点列表（供前端表格展示）"""
    return pxe_service_v2.get_node_list()


@router.patch("/nodes-json/update-mac")
def update_node_mac(old_mac: str, new_mac: str):
    """更新节点 MAC 地址（用实际硬件 MAC 替换占位符）"""
    data = pxe_service_v2.read_nodes_json()
    old_mac = old_mac.lower()
    new_mac = new_mac.lower()
    if old_mac not in data:
        raise HTTPException(status_code=404, detail=f"MAC {old_mac} 不在 nodes.json 中")
    if old_mac == new_mac:
        return {"message": "MAC 未变化"}
    data[new_mac] = data.pop(old_mac)
    pxe_service_v2.write_nodes_json(data)
    return {"message": f"MAC 已从 {old_mac} 更新为 {new_mac}"}


@router.get("/node-env", response_class=PlainTextResponse)
def get_node_env(mac: str = Query(..., description="节点 10GE 控制面网卡 MAC 地址")):
    """
    返回节点 shell 环境变量文本（firstboot detect.sh 使用）。

    用法（在节点上执行）：
        curl -sf http://172.16.3.10:8000/api/pxe/node-env?mac=aa:bb:cc:11:00:01 \\
             -o /etc/node-role/env
    """
    env_text = pxe_service_v2.get_node_env_vars(mac.lower())
    if env_text is None:
        raise HTTPException(status_code=404, detail=f"MAC {mac} 未在 nodes.json 中配置")
    return env_text


@router.get("/dhcp-config", response_class=PlainTextResponse)
def get_dhcp_config():
    """生成 dhcpd.conf（基于当前 nodes.json，监听控制面 172.16.3.0/24）"""
    return pxe_service_v2.generate_dhcpd_conf()


@router.get("/grub-config", response_class=PlainTextResponse)
def get_grub_config():
    """生成 aarch64 UEFI grub.cfg（部署至 /var/lib/tftpboot/grub.cfg）"""
    return pxe_service_v2.generate_grub_cfg()


@router.get("/setup-raid1-script", response_class=PlainTextResponse)
def get_setup_raid1_script():
    """生成批量创建 RAID1 系统盘的 Redfish 脚本（部署前在 PXE Host 执行）"""
    return pxe_service_v2.generate_setup_raid1_script()


@router.get("/pxe-boot-script", response_class=PlainTextResponse)
def get_pxe_boot_script():
    """生成 ipmitool 批量设置 PXE 启动的脚本"""
    return pxe_service_v2.generate_pxe_boot_script()


class RegenerateRequest(BaseModel):
    master_count: int = 6
    slave_count: int = 12
    subswath_count: int = 2
    gstorage_count: int = 1
    acquisition_count: int = 0


def _is_placeholder_mac(mac: str) -> bool:
    """默认模板生成的 MAC 形如 aa:bb:cc:xx:xx:xx, 属于占位符"""
    return mac.lower().startswith("aa:bb:cc")


def _index_by_hostname(data: dict) -> dict:
    """nodes.json -> {hostname: (mac, node_dict)}; 跳过 _ 开头的元数据键"""
    result = {}
    for mac, node in data.items():
        if mac.startswith("_"):
            continue
        hn = node.get("hostname_new", "")
        if hn:
            result[hn] = (mac, node)
    return result


def _merge_nodes_json(new_data: dict, old_data: dict) -> dict:
    """
    按 hostname 合并新旧 nodes.json (新规划为准):
      - 同 hostname    : 用旧 MAC (若为真实 MAC), 其余字段用新规划值
      - 新 hostname    : 直接加入 (用默认占位 MAC)
      - 旧 hostname 不在新的中 : 删除 (新规划是 source of truth)
    元数据 (_default_*) 用新的覆盖。
    """
    old_by_hn = _index_by_hostname(old_data)
    merged: dict = {}

    # 1. 元数据从新数据取
    for k, v in new_data.items():
        if k.startswith("_"):
            merged[k] = v

    # 2. 以新数据为主, 按 hostname 找旧条目
    for new_mac, new_node in new_data.items():
        if new_mac.startswith("_"):
            continue
        hn = new_node.get("hostname_new", "")
        if hn in old_by_hn:
            old_mac, _ = old_by_hn[hn]
            # 旧 MAC 是真实的 (用户填过/PXE 发现过) → 保留; 否则用新的占位
            use_mac = old_mac if not _is_placeholder_mac(old_mac) else new_mac
            merged[use_mac] = dict(new_node)
        else:
            merged[new_mac] = new_node

    # 旧规划里有但本次不在的 hostname → 不写入 merged, 即被移除

    return merged


@router.post("/nodes-json/regenerate")
def regenerate_nodes_json(req: RegenerateRequest, db: Session = Depends(get_db)):
    """
    按指定节点数量重新生成 nodes.json。语义为「合并」而非「替换」:
      - 同 hostname 覆盖 IP 规划字段, 保留已填写的真实 MAC
      - 新 hostname 追加 (默认占位 MAC)
      - 旧 hostname 不在本次规划 → 保留不删
    生成后自动同步到 DB (节点管理页直接可见, 未部署节点显示为离线状态)。
    """
    new_data = pxe_service_v2._default_nodes_json(
        master_count=req.master_count,
        slave_count=req.slave_count,
        subswath_count=req.subswath_count,
        gstorage_count=req.gstorage_count,
        acquisition_count=req.acquisition_count,
    )
    old_data = pxe_service_v2.read_nodes_json()

    old_hns = set(_index_by_hostname(old_data).keys())
    new_hns = set(_index_by_hostname(new_data).keys())
    added_hns   = new_hns - old_hns
    updated_hns = new_hns & old_hns
    removed_hns = old_hns - new_hns      # 旧规划里有, 新规划里没有 → 本次将删除

    merged = _merge_nodes_json(new_data, old_data)
    pxe_service_v2.write_nodes_json(merged)

    # 顺手同步 DB, 让节点管理立即可见
    db_stats = _sync_nodes_json_to_db_impl(db)

    return {
        "message": (
            f"nodes.json: 新增 {len(added_hns)} / 更新 {len(updated_hns)} / "
            f"删除 {len(removed_hns)}  ‖  节点管理: 新建 {db_stats['created']} 离线 / "
            f"更新 {db_stats['updated']} / 删除规划残留 {db_stats['deleted']}"
        ),
        "added":   sorted(added_hns),
        "updated": sorted(updated_hns),
        "removed": sorted(removed_hns),
        "db":      db_stats,
    }


def _sync_nodes_json_to_db_impl(db: Session) -> dict:
    """
    将 nodes.json 同步到 DB, 以「nodes.json 是规划唯一真实来源」为原则:
      - nodes.json 中的节点 → upsert (新建/更新)
      - DB 中匹配规划主机名模板 (master-01 / slave-12 …) 但不在 nodes.json 中
        → 删除 (清理上一次规划残留)
      - DB 中不匹配模板的主机名 (demo seed: master-1; 手动添加: 自定义名称)
        → 一律保留, 规划不会动它们
    """
    import logging
    log = logging.getLogger("pxe.sync")

    nodes_json = pxe_service_v2.read_nodes_json()
    created_list: list = []
    updated_list: list = []
    deleted_list: list = []
    skipped_list: list = []

    # ── 1. 收集本次规划中的主机名集合 ────────────────────────────
    plan_hostnames: set = set()
    for mac, node in nodes_json.items():
        if mac.startswith("_") or not isinstance(node, dict):
            continue
        hn = node.get("hostname_new")
        if hn:
            plan_hostnames.add(hn)

    log.info(f"[sync] nodes.json 共 {len(plan_hostnames)} 个规划节点")
    print(f"[sync] nodes.json 共 {len(plan_hostnames)} 个规划节点")

    # ── 2. 清理 DB 中"规划残留": 主机名像 master-01 / slave-12 但不在本次规划里 ──
    try:
        for existing in db.query(Node).all():
            hn = existing.hostname or ""
            if _PLAN_HOSTNAME_RE.match(hn) and hn not in plan_hostnames:
                deleted_list.append(hn)
                db.delete(existing)
        if deleted_list:
            db.flush()
            print(f"[sync] 清理规划残留: {deleted_list}")
    except Exception as e:
        log.exception(f"[sync] 清理残留失败: {e}")
        print(f"[sync][prune error] {e}")
        db.rollback()
        raise

    # ── 3. upsert 本次规划节点 ────────────────────────────────────
    for mac, node in nodes_json.items():
        if mac.startswith("_"):
            continue
        if not isinstance(node, dict):
            skipped_list.append(f"{mac}(非dict)")
            continue
        hostname = node.get("hostname_new") or ""
        if not hostname:
            skipped_list.append(f"{mac}(无hostname_new)")
            continue
        role      = node.get("role", "slave")
        ctrl_ip   = (node.get("ctrl_ip") or "").split("/")[0]
        bmc_ip    = node.get("bmc_ip") or ""
        rdma_ips  = node.get("rdma_ips") or ""
        first_rdma_ip = rdma_ips.split()[0].split("/")[0] if rdma_ips else ""

        try:
            existing = db.query(Node).filter(Node.hostname == hostname).first()
            if existing:
                if ctrl_ip:        existing.ctrl_ip = ctrl_ip
                existing.ctrl_mac = mac
                if bmc_ip:         existing.mgmt_ip = bmc_ip
                if bmc_ip:         existing.bmc_ip  = bmc_ip
                if first_rdma_ip:  existing.data_ip = first_rdma_ip
                existing.node_type = role
                updated_list.append(hostname)
            else:
                db.add(Node(
                    hostname=hostname, node_type=role, role=role,
                    ctrl_ip=ctrl_ip, ctrl_mac=mac,
                    mgmt_ip=bmc_ip, bmc_ip=bmc_ip, data_ip=first_rdma_ip,
                    status="offline", ctrl_status="offline", data_status="offline",
                ))
                created_list.append(hostname)
        except Exception as e:
            log.exception(f"[sync] {hostname} 失败: {e}")
            print(f"[sync][error] {hostname}: {e}")
            skipped_list.append(f"{hostname}(异常:{e})")

    try:
        db.commit()
    except Exception as e:
        log.exception(f"[sync] commit 失败: {e}")
        print(f"[sync][commit error] {e}")
        db.rollback()
        raise

    total_in_db = db.query(Node).count()
    print(
        f"[sync] OK: created={len(created_list)} updated={len(updated_list)} "
        f"deleted={len(deleted_list)} skipped={len(skipped_list)} db_total={total_in_db}"
    )
    log.info(
        f"[sync] OK: created={len(created_list)} updated={len(updated_list)} "
        f"deleted={len(deleted_list)} db_total={total_in_db}"
    )

    return {
        "created": len(created_list),
        "updated": len(updated_list),
        "deleted": len(deleted_list),
        "skipped": skipped_list,
        "created_hostnames": created_list,
        "updated_hostnames": updated_list,
        "deleted_hostnames": deleted_list,
        "db_total": total_in_db,
    }


@router.post("/nodes-json/sync-to-db")
def sync_nodes_json_to_db(db: Session = Depends(get_db)):
    """将 nodes.json 同步到 DB 节点表 (上游通常已由 regenerate 自动调用, 此端点为手动入口)"""
    stats = _sync_nodes_json_to_db_impl(db)
    return {
        "message": f"已同步 (新建 {stats['created']} 离线, 更新 {stats['updated']} 保留状态)",
        **stats,
    }


@router.get("/debug-state")
def debug_state(db: Session = Depends(get_db)):
    """
    诊断端点: 一次返回 nodes.json 内容、DB 节点列表、DB 表实际列名。
    用于排查"应用规划后节点管理为空"这类同步问题。
    在浏览器地址栏直接打开 http://<host>:<port>/api/pxe/debug-state 即可看 JSON。
    """
    from sqlalchemy import inspect, text
    from config import DATABASE_PATH

    # 1. nodes.json 现状
    try:
        nodes_json = pxe_service_v2.read_nodes_json()
        nj_hostnames = []
        for mac, node in nodes_json.items():
            if mac.startswith("_") or not isinstance(node, dict):
                continue
            hn = node.get("hostname_new")
            if hn:
                nj_hostnames.append({"mac": mac, "hostname": hn, "role": node.get("role")})
    except Exception as e:
        nj_hostnames = []
        nodes_json_error = str(e)
    else:
        nodes_json_error = None

    # 2. DB 中 nodes 表的实际列
    insp = inspect(db.bind)
    try:
        cols = [c["name"] for c in insp.get_columns("nodes")]
    except Exception as e:
        cols = []
        cols_error = str(e)
    else:
        cols_error = None

    # 3. DB 中所有节点
    try:
        all_nodes = db.query(Node).all()
        db_nodes = [
            {
                "id": n.id, "hostname": n.hostname, "node_type": n.node_type,
                "status": n.status, "ctrl_ip": n.ctrl_ip, "bmc_ip": n.bmc_ip,
            }
            for n in all_nodes
        ]
    except Exception as e:
        db_nodes = []
        db_error = str(e)
    else:
        db_error = None

    # 4. 用底层 SQL 再 count 一次（绕开 ORM 验证）
    try:
        raw_count = db.execute(text("SELECT COUNT(*) FROM nodes")).scalar()
    except Exception as e:
        raw_count = f"error: {e}"

    return {
        "database_path": str(DATABASE_PATH),
        "nodes_json_path": str(pxe_service_v2.nodes_json_path),
        "nodes_json": {
            "entries": len(nj_hostnames),
            "hostnames": nj_hostnames,
            "error": nodes_json_error,
        },
        "db": {
            "raw_count": raw_count,
            "orm_count": len(db_nodes),
            "columns": cols,
            "columns_error": cols_error,
            "nodes": db_nodes,
            "error": db_error,
        },
    }


class NodeFieldsUpdate(BaseModel):
    """更新 nodes.json 中指定节点的 NIC / IP 字段"""
    mac: str
    ctrl_nic: Optional[str] = None
    dpdk_nics: Optional[str] = None
    dpdk_ips: Optional[str] = None
    rdma_nics: Optional[str] = None
    rdma_ips: Optional[str] = None


@router.patch("/nodes-json/update-node")
def update_node_fields(req: NodeFieldsUpdate):
    """更新节点控制面/DPDK/RDMA 网卡名和 IP（保留 MAC 不变）"""
    data = pxe_service_v2.read_nodes_json()
    mac = req.mac.lower()
    if mac not in data:
        raise HTTPException(status_code=404, detail=f"MAC {mac} 不在 nodes.json 中")
    updates = {k: v for k, v in req.dict(exclude={"mac"}).items() if v is not None}
    if not updates:
        return {"message": "无字段需要更新"}
    data[mac].update(updates)
    pxe_service_v2.write_nodes_json(data)
    return {"message": "节点配置已更新", "mac": mac, "updated": list(updates.keys())}


class ScriptRunRequest(BaseModel):
    macs: List[str]
    script: str
    ssh_user: str = "root"
    ssh_password: Optional[str] = None
    ssh_port: int = 22


_WAVE_ROLES: dict = {
    1: ["subswath", "gstorage"],
    2: ["master"],
    3: ["slave", "acquisition"],
}


def _pxe_host_install_via_redfish(db: Session) -> dict:
    """
    PXE Host 一次性装机（Bootstrap）：通过 Redfish 虚拟介质把 ISO 挂为 BMC 虚拟光驱。
    仅在 PXE Host 首次部署时使用 — PXE Host 装好后稳定运行，无需重复触发。
    """
    cfg = pxe_service_v2.read_pxe_host_config()
    bmc_ip   = cfg.get("bmc_ip", "")
    iso_file = cfg.get("iso_filename", "")
    if not bmc_ip:
        raise HTTPException(status_code=400, detail="未配置 PXE Host BMC IP")
    if not iso_file:
        raise HTTPException(status_code=400, detail="未选择 ISO 文件")

    iso_path = Path(ISO_DIR) / iso_file
    if not iso_path.exists():
        raise HTTPException(status_code=404, detail=f"ISO 不存在: {iso_file}")

    iso_host = cfg.get("iso_http_host") or ""
    iso_port = int(cfg.get("iso_http_port") or 8000)
    if not iso_host:
        raise HTTPException(status_code=400, detail="未配置 ISO HTTP 主机地址（iso_http_host）")
    image_url = f"http://{iso_host}:{iso_port}/iso/{iso_file}"

    client = RedfishClient(
        bmc_ip=bmc_ip,
        username=cfg.get("bmc_user", "Administrator"),
        password=cfg.get("bmc_password", ""),
        manager_id=cfg.get("redfish_manager_id", "1"),
        system_id=cfg.get("redfish_system_id", "1"),
        virtual_media_id=cfg.get("redfish_virtual_media_id", "CD"),
    )
    redfish_result = client.deploy_iso(image_url)

    # 写入/更新 DB 节点记录用于状态监控页展示
    hostname = cfg.get("hostname") or "host-server"
    ctrl_ip = cfg.get("ctrl_ip", "")
    db_status = "deploying" if redfish_result["ok"] else "error"

    existing = db.query(Node).filter(Node.hostname == hostname).first()
    if existing:
        existing.bmc_ip    = bmc_ip
        existing.mgmt_ip   = bmc_ip
        existing.ctrl_ip   = ctrl_ip
        existing.node_type = "pxe_host"
        existing.status    = db_status
    else:
        existing = Node(
            hostname=hostname,
            node_type="pxe_host",
            role="pxe_host",
            ctrl_ip=ctrl_ip,
            mgmt_ip=bmc_ip,
            bmc_ip=bmc_ip,
            status=db_status,
        )
        db.add(existing)
        db.flush()
    db.commit()

    return {
        "ok": redfish_result["ok"],
        "hostname": hostname,
        "iso": iso_file,
        "image_url": image_url,
        "redfish": redfish_result,
    }


@router.post("/pxe-host/install")
def install_pxe_host(db: Session = Depends(get_db)):
    """
    PXE Host 首次装机（Bootstrap，一次性）：通过 Redfish 虚拟介质挂载 ISO 触发自动装机。
    PXE Host 装好后无需重复触发 — 后续节点部署走 /wave-deploy/1|2|3。
    """
    return _pxe_host_install_via_redfish(db)


@router.post("/wave-deploy/{wave}")
def trigger_wave_deploy(wave: int, db: Session = Depends(get_db)):
    """
    触发分批部署：从 nodes.json 读取对应角色节点并置 DB 状态为 deploying。
      wave=1 → SubSwath + GStorage
      wave=2 → Master
      wave=3 → Slave
    """
    if wave not in _WAVE_ROLES:
        raise HTTPException(status_code=400, detail="wave 必须为 1 / 2 / 3")

    roles = _WAVE_ROLES[wave]
    nodes_json = pxe_service_v2.read_nodes_json()
    deployed_nodes = []

    for mac, node in nodes_json.items():
        if mac.startswith("_"):
            continue
        role = node.get("role", "slave")
        if role not in roles:
            continue
        hostname = node.get("hostname_new", "")
        if not hostname:
            continue

        ctrl_ip    = node.get("ctrl_ip", "").split("/")[0]
        bmc_ip     = node.get("bmc_ip", "")
        rdma_ips   = node.get("rdma_ips", "")
        first_rdma = rdma_ips.split()[0].split("/")[0] if rdma_ips else ""

        existing = db.query(Node).filter(Node.hostname == hostname).first()
        if existing:
            existing.ctrl_ip   = ctrl_ip
            existing.ctrl_mac  = mac
            existing.mgmt_ip   = bmc_ip
            existing.bmc_ip    = bmc_ip
            existing.data_ip   = first_rdma
            existing.node_type = role
            existing.status    = "deploying"
            deployed_nodes.append(existing)
        else:
            new_node = Node(
                hostname=hostname,
                node_type=role,
                role=role,
                ctrl_ip=ctrl_ip,
                ctrl_mac=mac,
                mgmt_ip=bmc_ip,
                bmc_ip=bmc_ip,
                data_ip=first_rdma,
                status="deploying",
            )
            db.add(new_node)
            db.flush()
            deployed_nodes.append(new_node)

    db.commit()
    return {
        "wave": wave,
        "roles": roles,
        "triggered": len(deployed_nodes),
        "nodes": [n.hostname for n in deployed_nodes],
    }


# ── PXE Host 自身配置 + ISO 管理 ─────────────────────────────────────────────

class PxeHostConfig(BaseModel):
    hostname: Optional[str] = None
    bmc_ip: Optional[str] = None
    bmc_user: Optional[str] = None
    bmc_password: Optional[str] = None
    redfish_manager_id: Optional[str] = None
    redfish_system_id: Optional[str] = None
    redfish_virtual_media_id: Optional[str] = None
    ctrl_ip: Optional[str] = None
    iso_filename: Optional[str] = None
    iso_http_host: Optional[str] = None
    iso_http_port: Optional[int] = None


@router.get("/pxe-host/config")
def get_pxe_host_config():
    """读取 PXE Host 部署配置（BMC / Redfish / ISO）"""
    cfg = pxe_service_v2.read_pxe_host_config()
    # 不向前端回传明文密码（只显示是否已设置）
    safe = {**cfg, "bmc_password": "********" if cfg.get("bmc_password") else ""}
    return safe


@router.put("/pxe-host/config")
def update_pxe_host_config(req: PxeHostConfig):
    """更新 PXE Host 部署配置（仅写入提交的字段）"""
    cfg = pxe_service_v2.read_pxe_host_config()
    updates = {k: v for k, v in req.dict().items() if v is not None}
    # 占位密码视为不变
    if updates.get("bmc_password") == "********":
        updates.pop("bmc_password")
    cfg.update(updates)
    pxe_service_v2.write_pxe_host_config(cfg)
    return {"message": "PXE Host 配置已更新", "updated": list(updates.keys())}


@router.get("/pxe-host/iso-list")
def list_pxe_host_iso():
    """列出 Windows 安装目录下 iso/ 子目录中的 ISO 文件"""
    return {
        "iso_dir": str(ISO_DIR),
        "files": pxe_service_v2.list_iso_files(ISO_DIR),
    }


@router.get("/pxe-host/status")
def get_pxe_host_status(db: Session = Depends(get_db)):
    """
    返回 PXE Host 当前部署状态，用于前端判断是否需要做 Bootstrap：
      not_configured —— 尚未填写 BMC/ISO 配置
      not_installed   —— 配置已就绪，但从未触发过装机
      installing      —— 装机进行中（DB 中 status=deploying）
      online          —— PXE Host 已就绪可用
      error           —— 上次装机失败
    """
    cfg = pxe_service_v2.read_pxe_host_config()
    hostname = cfg.get("hostname") or "host-server"
    has_config = bool(cfg.get("bmc_ip") and cfg.get("iso_filename"))

    db_node = db.query(Node).filter(Node.hostname == hostname).first()

    if not has_config and not db_node:
        state = "not_configured"
    elif not db_node:
        state = "not_installed"
    elif db_node.status == "deploying":
        state = "installing"
    elif db_node.status == "online":
        state = "online"
    elif db_node.status == "error":
        state = "error"
    else:
        state = db_node.status or "not_installed"

    return {
        "state": state,
        "hostname": hostname,
        "bmc_ip": cfg.get("bmc_ip", ""),
        "ctrl_ip": cfg.get("ctrl_ip", ""),
        "iso_filename": cfg.get("iso_filename", ""),
        "has_config": has_config,
    }


# ── 节点回报端点(firstboot 阶段触发)─────────────────────────────────────────

class NodeReport(BaseModel):
    """
    节点 firstboot 阶段向管理面回报事件。
    典型事件:
      - stage:        阶段切换(network_ok / firmware_check / pkg_done / online)
      - fw_flashed:   单张设备固件升级成功
      - fw_failed:    单张设备固件升级失败
      - need_cold_reboot: 升级后需冷启动(管理面应发 IPMI power cycle)
      - finished:     firstboot 全部完成,节点进入 online
    """
    hostname: str
    event: str
    # 固件相关
    device: Optional[str] = None        # PCI 地址或网口名
    nic_name: Optional[str] = None      # ConnectX-5 / hinic 等
    fw_from: Optional[str] = None
    fw_to: Optional[str] = None
    # 通用
    stage: Optional[str] = None
    message: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None


@router.post("/report")
def node_report(req: NodeReport, db: Session = Depends(get_db)):
    """
    接收节点 firstboot 上报。除了写日志, 还要:
      - fw_flashed   → 把固件版本写入 Node.nic_firmware (累积式 list)
      - finished     → 节点 status = online
      - need_cold_reboot → 节点 status = need_cold_reboot, 等管理面调度
    """
    import logging
    log = logging.getLogger("pxe.report")
    log.info(f"[report] {req.hostname} event={req.event} stage={req.stage} msg={req.message}")
    print(f"[report] {req.hostname} {req.event} stage={req.stage} dev={req.device} {req.fw_from}->{req.fw_to}")

    node = db.query(Node).filter(Node.hostname == req.hostname).first()
    if not node:
        # 不知道的主机名也接受,只是不落库;避免节点早期上报因时序问题被拒
        return {"ok": True, "known": False}

    now_iso = datetime.utcnow().isoformat() + "Z"

    if req.event == "fw_flashed":
        existing = list(node.nic_firmware or [])
        existing.append({
            "pci":      req.device or "",
            "name":     req.nic_name or "",
            "from":     req.fw_from or "",
            "to":       req.fw_to or "",
            "at":       now_iso,
            "status":   "ok",
        })
        node.nic_firmware = existing

    elif req.event == "fw_failed":
        existing = list(node.nic_firmware or [])
        existing.append({
            "pci":      req.device or "",
            "name":     req.nic_name or "",
            "from":     req.fw_from or "",
            "to":       req.fw_to or "",
            "at":       now_iso,
            "status":   "failed",
            "message":  req.message or "",
        })
        node.nic_firmware = existing
        node.status = "error"

    elif req.event == "need_cold_reboot":
        node.status = "need_cold_reboot"

    elif req.event == "finished":
        node.status = "online"
        node.last_seen = datetime.utcnow()

    elif req.event == "stage":
        if req.stage in ("installing", "configuring", "deploying"):
            node.status = req.stage

    db.commit()
    return {"ok": True, "known": True, "status": node.status}


@router.post("/run-script")
async def run_script(req: ScriptRunRequest):
    """通过 SSH 在指定节点（控制面 IP）上执行 Shell 脚本"""
    nodes_json = pxe_service_v2.read_nodes_json()
    loop = asyncio.get_event_loop()
    results: List[Dict[str, Any]] = []
    pending = []

    for mac in req.macs:
        node = nodes_json.get(mac.lower())
        if not node:
            results.append({"hostname": mac, "status": "error", "output": "MAC 未在 nodes.json 中配置"})
            continue
        ctrl_ip = node.get("ctrl_ip", "").split("/")[0]
        hostname = node.get("hostname_new", mac)
        fn = functools.partial(
            _ssh_run, ctrl_ip, req.ssh_user, req.ssh_password, req.ssh_port, req.script
        )
        pending.append((hostname, loop.run_in_executor(_executor, fn)))

    for hostname, fut in pending:
        try:
            output = await fut
            results.append({"hostname": hostname, "status": "success", "output": output})
        except Exception as exc:
            results.append({"hostname": hostname, "status": "error", "output": str(exc)})

    return results
