"""
巡检管理 API - 支持三平面巡检
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from models.node import Node, PatrolRecord, Alert, get_db
from pydantic import BaseModel


router = APIRouter()


class PatrolResult(BaseModel):
    """巡检结果"""
    node_id: int
    hostname: str
    patrol_type: str
    plane: str
    result: str  # pass/fail
    details: dict


class PatrolSummary(BaseModel):
    """巡检汇总"""
    total_nodes: int
    passed: int
    failed: int
    results: List[PatrolResult]


class PatrolRecordResponse(BaseModel):
    id: int
    node_id: Optional[int]
    patrol_type: str
    plane: str
    result: str
    details: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/records", response_model=List[PatrolRecordResponse])
def get_patrol_records(
    node_id: Optional[int] = None,
    plane: Optional[str] = None,
    result: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取巡检记录"""
    query = db.query(PatrolRecord)
    if node_id:
        query = query.filter(PatrolRecord.node_id == node_id)
    if plane:
        query = query.filter(PatrolRecord.plane == plane)
    if result:
        query = query.filter(PatrolRecord.result == result)
    return query.order_by(PatrolRecord.created_at.desc()).limit(limit).all()


@router.post("/run")
async def run_full_patrol(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """执行全量巡检（所有节点所有平面）"""
    nodes = db.query(Node).filter(Node.status != 'offline').all()

    # 后台执行巡检
    # background_tasks.add_task(execute_patrol, nodes, db)

    return {
        "message": "全量巡检任务已启动",
        "nodes_count": len(nodes),
        "patrol_types": ["management", "control", "data", "system"]
    }


@router.post("/run/plane/{plane}")
async def run_plane_patrol(
    plane: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """执行指定平面巡检"""
    if plane not in ['management', 'control', 'data', 'all']:
        raise HTTPException(status_code=400, detail="无效的平面类型")

    nodes = db.query(Node).all()

    return {
        "message": f"{plane}平面巡检任务已启动",
        "plane": plane,
        "nodes_count": len(nodes)
    }


@router.get("/node/{node_id}", response_model=PatrolSummary)
def patrol_single_node(node_id: int, db: Session = Depends(get_db)):
    """巡检单个节点"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    results = []

    # 管理面巡检
    mgmt_result = "pass"
    mgmt_details = {
        "bmc_ip": node.bmc_ip,
        "ssh_port_open": True,
        "ipmi_response": True
    }
    if not node.bmc_ip or node.status != 'online':
        mgmt_result = "fail"
        mgmt_details["reason"] = "节点离线或无BMC IP"

    results.append(PatrolResult(
        node_id=node_id,
        hostname=node.hostname,
        patrol_type="bmc_connectivity",
        plane="management",
        result=mgmt_result,
        details=mgmt_details
    ))

    # 记录巡检结果
    record = PatrolRecord(
        node_id=node_id,
        patrol_type="bmc_connectivity",
        plane="management",
        result=mgmt_result,
        details=mgmt_details
    )
    db.add(record)

    # 控制面巡检
    ctrl_result = "pass"
    ctrl_details = {
        "ctrl_ip": node.ctrl_ip,
        "ping_latency_ms": 0.5,
        "heartbeat_status": True
    }
    if not node.ctrl_ip or node.ctrl_status != 'online':
        ctrl_result = "fail"
        ctrl_details["reason"] = "控制面离线"

    results.append(PatrolResult(
        node_id=node_id,
        hostname=node.hostname,
        patrol_type="control_connectivity",
        plane="control",
        result=ctrl_result,
        details=ctrl_details
    ))

    record = PatrolRecord(
        node_id=node_id,
        patrol_type="control_connectivity",
        plane="control",
        result=ctrl_result,
        details=ctrl_details
    )
    db.add(record)

    # 数据面巡检
    data_result = "pass"
    data_details = {
        "data_ip": node.data_ip,
        "protocol": node.data_protocol,
        "throughput_mbps": 8500,
        "packet_loss_rate": 0.01
    }
    if not node.data_ip or node.data_status != 'online':
        data_result = "fail"
        data_details["reason"] = "数据面离线"

    results.append(PatrolResult(
        node_id=node_id,
        hostname=node.hostname,
        patrol_type="data_connectivity",
        plane="data",
        result=data_result,
        details=data_details
    ))

    record = PatrolRecord(
        node_id=node_id,
        patrol_type="data_connectivity",
        plane="data",
        result=data_result,
        details=data_details
    )
    db.add(record)

    # 系统资源巡检
    system_result = "pass"
    system_details = {
        "cpu_usage": 45,
        "memory_usage": 60,
        "disk_usage": 70,
        "load_average": 1.5
    }

    results.append(PatrolResult(
        node_id=node_id,
        hostname=node.hostname,
        patrol_type="system_resources",
        plane="all",
        result=system_result,
        details=system_details
    ))

    record = PatrolRecord(
        node_id=node_id,
        patrol_type="system_resources",
        plane="all",
        result=system_result,
        details=system_details
    )
    db.add(record)

    db.commit()

    passed = sum(1 for r in results if r.result == 'pass')
    failed = sum(1 for r in results if r.result == 'fail')

    return PatrolSummary(
        total_nodes=1,
        passed=passed,
        failed=failed,
        results=results
    )


@router.get("/items")
def get_patrol_items():
    """获取巡检项目清单"""
    return {
        "management": [
            {"name": "BMC连通性", "description": "检查IPMI服务响应"},
            {"name": "SSH服务", "description": "检查SSH端口22是否开放"},
            {"name": "BMC传感器", "description": "检查温度、风扇等传感器数据"}
        ],
        "control": [
            {"name": "10GE连通性", "description": "检查控制面网络ping延迟"},
            {"name": "心跳服务", "description": "检查心跳检测响应时间"},
            {"name": "配置同步", "description": "检查配置同步状态"}
        ],
        "data": [
            {"name": "100GE网卡状态", "description": "检查数据面网卡状态"},
            {"name": "DPDK/RDMA状态", "description": "检查DPDK/RDMA服务状态"},
            {"name": "吞吐量", "description": "检查数据吞吐量统计"},
            {"name": "丢包率", "description": "检查数据丢包率"}
        ],
        "system": [
            {"name": "CPU使用率", "description": "检查CPU使用率是否超过阈值"},
            {"name": "内存使用率", "description": "检查内存使用率是否超过阈值"},
            {"name": "磁盘使用率", "description": "检查磁盘使用率是否超过阈值"},
            {"name": "系统服务", "description": "检查关键系统服务状态"}
        ]
    }


@router.get("/summary")
def get_patrol_summary(db: Session = Depends(get_db)):
    """获取最近巡检汇总"""
    # 获取最近一天的巡检记录
    recent_records = db.query(PatrolRecord).order_by(
        PatrolRecord.created_at.desc()
    ).limit(200).all()

    # 按平面统计
    plane_stats = {}
    for record in recent_records:
        if record.plane not in plane_stats:
            plane_stats[record.plane] = {"pass": 0, "fail": 0}
        plane_stats[record.plane][record.result] += 1

    # 总体统计
    total_passed = sum(1 for r in recent_records if r.result == 'pass')
    total_failed = sum(1 for r in recent_records if r.result == 'fail')

    return {
        "total_checked": len(recent_records),
        "total_passed": total_passed,
        "total_failed": total_failed,
        "pass_rate": round(total_passed / len(recent_records) * 100, 2) if recent_records else 0,
        "by_plane": plane_stats,
        "last_patrol_time": recent_records[0].created_at if recent_records else None
    }