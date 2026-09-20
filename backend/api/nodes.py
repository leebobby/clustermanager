"""
节点管理 API - 支持三平面网络信息

IP 的正主是 plane_ips: {平面: [ip, ...]} —— 一个角色在一个平面上可以有多块网卡,
Master 数据面就是四个 IP(前段 DPDK 两个 + 后段 RDMA 两个)。扁平字段
(mgmt_ip / ctrl_ip / data_ip)只是第一个口的镜像, 留给 PXE、巡检那些按扁平字段
取值的老代码。

两边必须一起改。之前改扁平字段不动 plane_ips, 结果是: 界面上把管理面 IP 改了,
节点表格、组网图、诊断读的都是 plane_ips, 一个都没变 —— 看起来就是"编辑没生效"。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from datetime import datetime

from models.node import Node, get_db
from pydantic import BaseModel


router = APIRouter()

# 数据面走前段还是后段, 按协议判: DPDK 前段, 其余按后段 —— 与模板展开同一套规则
_DATA_PLANES = ("data_front", "data_back")


def _clean_planes(raw: Any) -> Dict[str, List[str]]:
    """规整 plane_ips: 去空、去首尾空格; 一个 IP 都不剩的平面整条丢掉"""
    out: Dict[str, List[str]] = {}
    for plane, ips in (raw or {}).items():
        if isinstance(ips, str):
            ips = [ips]
        ips = [str(x).strip() for x in (ips or []) if str(x).strip()]
        if ips:
            out[str(plane)] = ips
    return out


def _flat_from_planes(node: Node) -> None:
    """plane_ips → 扁平字段(各取第一个口)"""
    planes = node.plane_ips or {}
    mgmt = (planes.get("management") or [None])[0]
    # 管理面与 BMC 同网段, 沿用模板展开时的约定
    node.mgmt_ip = mgmt
    node.bmc_ip = mgmt
    node.ctrl_ip = (planes.get("control") or [None])[0]
    node.data_ip = None
    for plane in _DATA_PLANES:
        first = (planes.get(plane) or [None])[0]
        if first:
            node.data_ip = first
            if not node.data_protocol:
                node.data_protocol = "DPDK" if plane == "data_front" else "RDMA"
            break


def _planes_from_flat(node: Node, changed: Dict[str, Any]) -> None:
    """
    扁平字段 → plane_ips(只动第一个口, 其余网卡原样留着)。

    给只认扁平字段的老调用方用: PXE 写完 mgmt_ip, 节点表格和组网图也得跟着变。
    """
    planes = dict(node.plane_ips or {})

    def put(plane: str, ip: Optional[str]) -> None:
        ips = list(planes.get(plane) or [])
        ip = (ip or "").strip()
        if ip:
            if ips:
                ips[0] = ip
            else:
                ips = [ip]
        elif ips:
            ips = ips[1:]        # 第一个口清空, 后面的网卡留着
        if ips:
            planes[plane] = ips
        else:
            planes.pop(plane, None)

    if "mgmt_ip" in changed or "bmc_ip" in changed:
        put("management", changed.get("mgmt_ip") or changed.get("bmc_ip"))
    if "ctrl_ip" in changed:
        put("control", changed.get("ctrl_ip"))
    if "data_ip" in changed:
        # 写进节点已有的那个数据面; 都没有就按协议挑一个
        target = next((p for p in _DATA_PLANES if planes.get(p)), None)
        if not target:
            protocol = str(changed.get("data_protocol") or node.data_protocol or "").upper()
            target = "data_front" if protocol == "DPDK" else "data_back"
        put(target, changed.get("data_ip"))

    node.plane_ips = planes


def _apply_ips(node: Node, submitted: Dict[str, Any]) -> None:
    """
    把这次提交的 IP 落到两边。plane_ips 给了就以它为准, 没给就按扁平字段反推。
    """
    if "plane_ips" in submitted:
        node.plane_ips = _clean_planes(submitted["plane_ips"])
        _flat_from_planes(node)
    elif {"mgmt_ip", "bmc_ip", "ctrl_ip", "data_ip"} & set(submitted):
        _planes_from_flat(node, submitted)


class NodeCreate(BaseModel):
    hostname: str
    node_type: str  # master/slave/subswath/gstorage/sensor
    role: Optional[str] = None
    product: Optional[str] = None
    machine_type: Optional[str] = None
    role_key: Optional[str] = None
    mgmt_ip: Optional[str] = None
    mgmt_mac: Optional[str] = None
    bmc_ip: Optional[str] = None
    bmc_mac: Optional[str] = None
    ctrl_ip: Optional[str] = None
    ctrl_mac: Optional[str] = None
    data_ip: Optional[str] = None
    data_mac: Optional[str] = None
    data_protocol: Optional[str] = None
    # {平面: [ip, ...]} —— 一个平面可以有多块网卡
    plane_ips: Optional[Dict[str, List[str]]] = None
    os_version: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_gb: Optional[int] = None
    disk_gb: Optional[int] = None


class NodeUpdate(BaseModel):
    hostname: Optional[str] = None
    node_type: Optional[str] = None
    role: Optional[str] = None
    product: Optional[str] = None
    machine_type: Optional[str] = None
    role_key: Optional[str] = None
    mgmt_ip: Optional[str] = None
    mgmt_mac: Optional[str] = None
    bmc_ip: Optional[str] = None
    bmc_mac: Optional[str] = None
    ctrl_ip: Optional[str] = None
    ctrl_mac: Optional[str] = None
    data_ip: Optional[str] = None
    data_mac: Optional[str] = None
    data_protocol: Optional[str] = None
    plane_ips: Optional[Dict[str, List[str]]] = None
    ctrl_status: Optional[str] = None
    data_status: Optional[str] = None
    status: Optional[str] = None
    os_version: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_gb: Optional[int] = None
    disk_gb: Optional[int] = None


class NodeResponse(BaseModel):
    id: int
    hostname: str
    node_type: str
    role: Optional[str]
    # 来源模板 —— 集群那一层已经撤掉了, 不要再往这儿加 cluster_id
    product: Optional[str] = None
    machine_type: Optional[str] = None
    role_key: Optional[str] = None
    # 管理面
    mgmt_ip: Optional[str]
    mgmt_mac: Optional[str]
    bmc_ip: Optional[str]
    bmc_mac: Optional[str]
    # 控制面
    ctrl_ip: Optional[str]
    ctrl_mac: Optional[str]
    ctrl_status: Optional[str]
    # 数据面
    data_ip: Optional[str]
    data_mac: Optional[str]
    data_status: Optional[str]
    data_protocol: Optional[str]
    # 各平面的全部 IP 与实测状态 —— 扁平字段只是第一个口
    plane_ips: Optional[Dict[str, List[str]]] = None
    plane_status: Optional[Dict[str, str]] = None
    # 整体状态
    status: str
    os_version: Optional[str]
    cpu_cores: Optional[int]
    memory_gb: Optional[int]
    disk_gb: Optional[int]
    created_at: datetime
    last_seen: Optional[datetime]

    class Config:
        from_attributes = True


class NodeNetworkUpdate(BaseModel):
    """三平面网络配置更新"""
    mgmt_ip: Optional[str] = None
    mgmt_mac: Optional[str] = None
    bmc_ip: Optional[str] = None
    ctrl_ip: Optional[str] = None
    ctrl_mac: Optional[str] = None
    data_ip: Optional[str] = None
    data_mac: Optional[str] = None
    data_protocol: Optional[str] = None


@router.get("", response_model=List[NodeResponse])
def get_nodes(
    node_type: Optional[str] = None,
    status: Optional[str] = None,
    product: Optional[str] = None,
    machine_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取节点列表，可按类型、状态、所属产品 / 机台类型筛选"""
    query = db.query(Node)
    if node_type:
        query = query.filter(Node.node_type == node_type)
    if status:
        query = query.filter(Node.status == status)
    if product:
        query = query.filter(Node.product == product)
    if machine_type:
        query = query.filter(Node.machine_type == machine_type)
    return query.all()


# ── 静态路径必须放在 /{node_id} 之前, 否则会被吃成无效 int ───────────────────
@router.get("/masters", response_model=List[NodeResponse])
def get_master_nodes(db: Session = Depends(get_db)):
    """获取所有 Master 节点"""
    return db.query(Node).filter(Node.node_type == 'master').all()


@router.get("/slaves", response_model=List[NodeResponse])
def get_slave_nodes(db: Session = Depends(get_db)):
    """获取所有 Slave 节点"""
    return db.query(Node).filter(Node.node_type == 'slave').all()


@router.get("/topology")
def get_topology(db: Session = Depends(get_db)):
    """获取三平面网络拓扑数据"""
    nodes = db.query(Node).all()

    topology = {"masters": [], "slaves": [], "links": []}

    for node in nodes:
        node_data = {
            "id": node.id,
            "hostname": node.hostname,
            "node_type": node.node_type,
            "status": node.status,
            "planes": {
                "management": {
                    "ip": node.mgmt_ip,
                    "mac": node.mgmt_mac,
                    "bmc_ip": node.bmc_ip,
                    "status": node.status,
                },
                "control": {
                    "ip": node.ctrl_ip,
                    "mac": node.ctrl_mac,
                    "status": node.ctrl_status,
                },
                "data": {
                    "ip": node.data_ip,
                    "mac": node.data_mac,
                    "status": node.data_status,
                    "protocol": node.data_protocol,
                },
            },
        }
        if node.node_type == 'master':
            topology["masters"].append(node_data)
        elif node.node_type == 'slave':
            topology["slaves"].append(node_data)

    return topology


@router.get("/{node_id}", response_model=NodeResponse)
def get_node(node_id: int, db: Session = Depends(get_db)):
    """获取单个节点详情"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    return node


@router.post("", response_model=NodeResponse)
def create_node(node: NodeCreate, db: Session = Depends(get_db)):
    """创建新节点"""
    submitted = node.dict(exclude_unset=True)
    # 只取 Node 真有的列: 请求模型多出一个字段就会让这里 TypeError, 整个"加节点"
    # 变成 500。cluster_id 就是这么漏过去的 —— 集群那层撤掉后模型没有它了
    columns = {c.name for c in Node.__table__.columns}
    db_node = Node(**{k: v for k, v in node.dict().items() if k in columns})
    _apply_ips(db_node, submitted)
    db.add(db_node)
    db.commit()
    db.refresh(db_node)
    return db_node


@router.put("/{node_id}", response_model=NodeResponse)
def update_node(node_id: int, node: NodeUpdate, db: Session = Depends(get_db)):
    """更新节点信息"""
    db_node = db.query(Node).filter(Node.id == node_id).first()
    if not db_node:
        raise HTTPException(status_code=404, detail="节点不存在")

    update_data = node.dict(exclude_unset=True)
    columns = {c.name for c in Node.__table__.columns}
    for key, value in update_data.items():
        if key in columns:
            setattr(db_node, key, value)
    _apply_ips(db_node, update_data)

    db.commit()
    db.refresh(db_node)
    return db_node


@router.put("/{node_id}/network", response_model=NodeResponse)
def update_node_network(node_id: int, network: NodeNetworkUpdate, db: Session = Depends(get_db)):
    """更新节点三平面网络配置"""
    db_node = db.query(Node).filter(Node.id == node_id).first()
    if not db_node:
        raise HTTPException(status_code=404, detail="节点不存在")

    update_data = network.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_node, key, value)
    _apply_ips(db_node, update_data)

    db.commit()
    db.refresh(db_node)
    return db_node


@router.delete("/{node_id}")
def delete_node(node_id: int, db: Session = Depends(get_db)):
    """删除节点"""
    db_node = db.query(Node).filter(Node.id == node_id).first()
    if not db_node:
        raise HTTPException(status_code=404, detail="节点不存在")

    db.delete(db_node)
    db.commit()
    return {"message": "节点已删除"}


