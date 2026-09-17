"""
三平面网络配置 API
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from models.node import Node, NetworkLink, get_db
from pydantic import BaseModel
from services.pxe_service import pxe_service_v2


router = APIRouter()


class LinkCreate(BaseModel):
    """链路创建"""
    source_node_id: int
    target_node_id: int
    plane: str  # management/control/data_front/data_back
    protocol: str  # IPMI/TCP/DPDK/RDMA
    bandwidth: str  # GE/10GE/100GE


class LinkResponse(BaseModel):
    id: int
    source_node_id: int
    target_node_id: int
    plane: str
    protocol: str
    bandwidth: str
    status: str
    latency_ms: Optional[float]
    packet_loss_rate: Optional[float]
    throughput_mbps: Optional[float]
    last_check: Optional[datetime]

    class Config:
        from_attributes = True


class NetworkStatusResponse(BaseModel):
    """三平面网络状态"""
    management: dict
    control: dict
    data_front: dict
    data_back: dict


@router.get("/links", response_model=List[LinkResponse])
def get_links(
    plane: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取网络链路列表"""
    query = db.query(NetworkLink)
    if plane:
        query = query.filter(NetworkLink.plane == plane)
    return query.all()


@router.post("/links", response_model=LinkResponse)
def create_link(link: LinkCreate, db: Session = Depends(get_db)):
    """创建网络链路"""
    # 验证节点存在
    source = db.query(Node).filter(Node.id == link.source_node_id).first()
    target = db.query(Node).filter(Node.id == link.target_node_id).first()

    if not source or not target:
        raise HTTPException(status_code=404, detail="源节点或目标节点不存在")

    db_link = NetworkLink(**link.dict())
    db.add(db_link)
    db.commit()
    db.refresh(db_link)
    return db_link


@router.get("/status")
def get_network_status(db: Session = Depends(get_db)):
    """获取三平面网络整体状态"""
    nodes = db.query(Node).all()
    links = db.query(NetworkLink).all()

    # 统计各平面状态
    management_nodes = sum(1 for n in nodes if n.bmc_ip and n.status == 'online')
    control_nodes = sum(1 for n in nodes if n.ctrl_ip and n.ctrl_status == 'online')
    data_nodes = sum(1 for n in nodes if n.data_ip and n.data_status == 'online')

    # 统计链路状态
    management_links = [l for l in links if l.plane == 'management']
    control_links = [l for l in links if l.plane == 'control']
    data_front_links = [l for l in links if l.plane == 'data_front']
    data_back_links = [l for l in links if l.plane == 'data_back']

    def calc_link_stats(link_list):
        if not link_list:
            return {"total": 0, "normal": 0, "degraded": 0, "down": 0, "avg_latency": 0}
        return {
            "total": len(link_list),
            "normal": sum(1 for l in link_list if l.status == 'normal'),
            "degraded": sum(1 for l in link_list if l.status == 'degraded'),
            "down": sum(1 for l in link_list if l.status == 'down'),
            "avg_latency": sum(l.latency_ms or 0 for l in link_list) / len(link_list) if link_list else 0
        }

    return {
        "management": {
            "nodes_online": management_nodes,
            "nodes_total": sum(1 for n in nodes if n.bmc_ip),
            "links": calc_link_stats(management_links),
            "description": "管理面 - GE口，IPMI/BMC管理"
        },
        "control": {
            "nodes_online": control_nodes,
            "nodes_total": sum(1 for n in nodes if n.ctrl_ip),
            "links": calc_link_stats(control_links),
            "description": "控制面 - 10GE，心跳/配置同步"
        },
        "data_front": {
            "nodes_online": sum(1 for n in nodes if n.node_type == 'master' and n.data_status == 'online'),
            "nodes_total": sum(1 for n in nodes if n.node_type == 'master'),
            "links": calc_link_stats(data_front_links),
            "description": "数据面前段 - 100GE，DPDK协议"
        },
        "data_back": {
            "nodes_online": sum(1 for n in nodes if n.node_type == 'slave' and n.data_status == 'online'),
            "nodes_total": sum(1 for n in nodes if n.node_type == 'slave'),
            "links": calc_link_stats(data_back_links),
            "description": "数据面后段 - 100GE，RDMA协议"
        }
    }


@router.get("/topology-graph")
def get_topology_graph(db: Session = Depends(get_db)):
    """获取组网图数据（用于前端D3.js渲染）"""
    nodes = db.query(Node).all()

    masters      = [n for n in nodes if n.node_type == 'master']
    slaves       = [n for n in nodes if n.node_type == 'slave']
    sensors      = [n for n in nodes if n.node_type == 'sensor']
    storages     = [n for n in nodes if n.node_type in ('subswath', 'gstorage')]
    acquisitions = [n for n in nodes if n.node_type == 'acquisition']

    # ── 从 nodes.json 读取每节点的 NIC 清单 ──────────────────
    nic_map: dict = {}
    try:
        nj = pxe_service_v2.read_nodes_json()
        for mac, nd in nj.items():
            if mac.startswith("_"):
                continue
            hn = nd.get("hostname_new", "")
            def _split(s): return s.split() if s else []
            nic_map[hn] = {
                "dpdk_nics": _split(nd.get("dpdk_nics", "")),
                "dpdk_ips":  _split(nd.get("dpdk_ips",  "")),
                "rdma_nics": _split(nd.get("rdma_nics", "")),
                "rdma_ips":  _split(nd.get("rdma_ips",  "")),
            }
    except Exception:
        pass

    has_data = bool(masters or slaves or sensors or storages or acquisitions)

    # ── 管理站（Windows）+ PXE Host 配置读取 ─────────────────
    pxe_host_cfg = pxe_service_v2.read_pxe_host_config()
    pxe_host_db = next(
        (n for n in nodes if n.node_type == "pxe_host" or n.hostname == pxe_host_cfg.get("hostname")),
        None,
    )
    pxe_host_status = pxe_host_db.status if pxe_host_db else "offline"

    # ── 基础设施虚拟节点 ──────────────────────────────────────
    graph_nodes = [
        {
            "id": "mgmt-station",
            "name": "管理站 (Windows)",
            "type": "mgmt_station",
            "status": "online",
            "planes": {
                "management": {"ip": pxe_host_cfg.get("iso_http_host") or "—", "status": "online"},
                "control":    {"ip": "—", "status": "online"},
            },
        },
        {
            "id": "sw-mgmt",
            "name": "管理交换机 GE",
            "type": "switch",
            "switch_plane": "management",
            "status": "online"
        },
        {
            "id": "sw-ctrl",
            "name": "控制交换机 10GE",
            "type": "switch",
            "switch_plane": "control",
            "status": "online" if any(n.ctrl_status == 'online' for n in nodes) else "offline"
        },
        {
            "id": "sw-data-100g",
            "name": "数据交换机 100GE",
            "type": "switch",
            "switch_plane": "data_front",
            "status": "online" if has_data else "offline"
        },
        {
            "id": "pxe-host",
            "name": pxe_host_cfg.get("hostname") or "host-server",
            "type": "pxe_host",
            "status": pxe_host_status,
            "planes": {
                "management": {
                    "ip":     pxe_host_cfg.get("bmc_ip") or "—",
                    "bmc_ip": pxe_host_cfg.get("bmc_ip") or "—",
                    "status": "online" if pxe_host_cfg.get("bmc_ip") else "offline",
                },
                "control": {
                    "ip":     pxe_host_cfg.get("ctrl_ip") or "—",
                    "status": pxe_host_status,
                },
            },
        },
    ]

    # ── 服务器节点 ────────────────────────────────────────────
    for node in nodes:
        graph_nodes.append({
            "id": str(node.id),
            "name": node.hostname,
            "type": node.node_type,
            "status": node.status,
            "planes": {
                "management": {
                    "ip": node.mgmt_ip,
                    "bmc_ip": node.bmc_ip,
                    "status": "online" if node.bmc_ip else "offline"
                },
                "control": {
                    "ip": node.ctrl_ip,
                    "status": node.ctrl_status or "offline"
                },
                "data": {
                    "ip": node.data_ip,
                    "status": node.data_status or "offline",
                    "protocol": node.data_protocol
                }
            }
        })

    graph_links = []

    # ── 管理面：管理站 → 管理交换机 → 所有节点（含 PXE Host）─
    graph_links.append({
        "source": "mgmt-station", "target": "sw-mgmt",
        "plane": "management", "protocol": "IPMI/Redfish",
        "bandwidth": "GE", "status": "normal", "latency": 0.5, "packet_loss": 0
    })
    # 管理站 → PXE Host BMC（Redfish 部署通道）
    if pxe_host_cfg.get("bmc_ip"):
        graph_links.append({
            "source": "sw-mgmt", "target": "pxe-host",
            "plane": "management", "protocol": "Redfish",
            "bandwidth": "GE",
            "status": "normal" if pxe_host_status != "offline" else "down",
            "latency": 1.0, "packet_loss": 0
        })
    for node in nodes:
        if node.node_type == "pxe_host":
            continue   # PXE Host 已在上面单独连过
        if node.bmc_ip or node.mgmt_ip:
            graph_links.append({
                "source": "sw-mgmt", "target": str(node.id),
                "plane": "management", "protocol": "IPMI",
                "bandwidth": "GE",
                "status": "normal" if node.status == "online" else "down",
                "latency": 1.0, "packet_loss": 0
            })

    # ── 控制面：管理站 + PXE Host + 节点 ↔ 控制交换机 ────────
    graph_links.append({
        "source": "mgmt-station", "target": "sw-ctrl",
        "plane": "control", "protocol": "TCP",
        "bandwidth": "10GE", "status": "normal", "latency": 0.5, "packet_loss": 0
    })
    if pxe_host_cfg.get("ctrl_ip"):
        graph_links.append({
            "source": "pxe-host", "target": "sw-ctrl",
            "plane": "control", "protocol": "DHCP/TFTP/HTTP",
            "bandwidth": "10GE",
            "status": "normal" if pxe_host_status != "offline" else "down",
            "latency": 0.5, "packet_loss": 0
        })
    for node in nodes:
        if node.node_type == "pxe_host":
            continue
        if node.ctrl_ip:
            graph_links.append({
                "source": "sw-ctrl", "target": str(node.id),
                "plane": "control", "protocol": "TCP",
                "bandwidth": "10GE",
                "status": "normal" if node.ctrl_status == "online" else "down",
                "latency": 0.5, "packet_loss": 0
            })

    def _data_links(node, plane, proto, is_online):
        """生成节点 ↔ 100G 数据交换机的逐接口链路"""
        nics_key = "dpdk_nics" if plane == "data_front" else "rdma_nics"
        ips_key  = "dpdk_ips"  if plane == "data_front" else "rdma_ips"
        info = nic_map.get(node.hostname, {})
        nics = info.get(nics_key, []) or (["eno2"] if plane == "data_back" else [])
        ips  = info.get(ips_key, [])
        port_count = max(len(nics), 1)
        for idx, nic in enumerate(nics):
            ip = ips[idx].split("/")[0] if idx < len(ips) else ""
            graph_links.append({
                "source": str(node.id), "target": "sw-data-100g",
                "plane": plane, "protocol": proto,
                "bandwidth": "100GE",
                "nic": nic, "ip": ip,
                "port_index": idx, "port_count": port_count,
                "status": "normal" if is_online else "down",
                "latency": 0.1, "packet_loss": 0
            })

    # ── 数据面前段（DPDK）：传感器 + Master + Acquisition ↔ 数据交换机 ─
    for node in sensors + masters + acquisitions:
        _data_links(node, "data_front", "DPDK",
                    node.data_status == "online")

    # ── 数据面后段（RDMA）：Master + Slave + 存储 + Acquisition ↔ 数据交换机
    for node in masters + slaves + storages + acquisitions:
        _data_links(node, "data_back", "RDMA",
                    node.data_status == "online")

    return {
        "nodes": graph_nodes,
        "links": graph_links,
        "metadata": {
            "total_nodes": len(graph_nodes),
            "total_links": len(graph_links),
            "planes": ["management", "control", "data_front", "data_back"]
        }
    }


@router.post("/check/{node_id}")
def check_node_network(node_id: int, db: Session = Depends(get_db)):
    """检查节点三平面网络连通性"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    # 模拟网络检查结果
    results = {
        "node_id": node_id,
        "hostname": node.hostname,
        "planes": {
            "management": {
                "ip": node.mgmt_ip,
                "bmc_ip": node.bmc_ip,
                "reachable": node.bmc_ip is not None,
                "latency_ms": 1.2 if node.bmc_ip else None,
                "last_check": datetime.utcnow()
            },
            "control": {
                "ip": node.ctrl_ip,
                "reachable": node.ctrl_status == 'online',
                "latency_ms": 0.5 if node.ctrl_status == 'online' else None,
                "last_check": datetime.utcnow()
            },
            "data": {
                "ip": node.data_ip,
                "protocol": node.data_protocol,
                "reachable": node.data_status == 'online',
                "throughput_mbps": 8500 if node.data_status == 'online' else None,
                "last_check": datetime.utcnow()
            }
        },
        "overall_status": "online" if node.status == 'online' else "degraded"
    }

    return results