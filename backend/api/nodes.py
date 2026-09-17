"""
节点管理 API - 支持三平面网络信息
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from models.node import Node, get_db
from pydantic import BaseModel


router = APIRouter()


class NodeCreate(BaseModel):
    hostname: str
    node_type: str  # master/slave/subswath/gstorage/sensor
    role: Optional[str] = None
    mgmt_ip: Optional[str] = None
    mgmt_mac: Optional[str] = None
    bmc_ip: Optional[str] = None
    bmc_mac: Optional[str] = None
    ctrl_ip: Optional[str] = None
    ctrl_mac: Optional[str] = None
    data_ip: Optional[str] = None
    data_mac: Optional[str] = None
    data_protocol: Optional[str] = None
    os_version: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_gb: Optional[int] = None
    disk_gb: Optional[int] = None


class NodeUpdate(BaseModel):
    hostname: Optional[str] = None
    node_type: Optional[str] = None
    role: Optional[str] = None
    mgmt_ip: Optional[str] = None
    mgmt_mac: Optional[str] = None
    bmc_ip: Optional[str] = None
    bmc_mac: Optional[str] = None
    ctrl_ip: Optional[str] = None
    ctrl_mac: Optional[str] = None
    data_ip: Optional[str] = None
    data_mac: Optional[str] = None
    data_protocol: Optional[str] = None
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
    db: Session = Depends(get_db)
):
    """获取节点列表，可按类型和状态筛选"""
    query = db.query(Node)
    if node_type:
        query = query.filter(Node.node_type == node_type)
    if status:
        query = query.filter(Node.status == status)
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
    db_node = Node(**node.dict())
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
    for key, value in update_data.items():
        setattr(db_node, key, value)

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


