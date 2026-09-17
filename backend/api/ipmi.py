"""
IPMI/BMC 管理 API
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import asyncio
import subprocess
import json

from models.node import Node, BMCInfo, get_db
from pydantic import BaseModel


router = APIRouter()


class BMCDiscoverRequest(BaseModel):
    """BMC发现请求"""
    subnet: str  # 例如: 192.168.1.0/24
    timeout: int = 5


class BMCInfoResponse(BaseModel):
    id: int
    node_id: Optional[int]
    bmc_ip: str
    bmc_mac: Optional[str]
    bmc_model: Optional[str]
    bmc_version: Optional[str]
    power_status: Optional[str]
    temperature: Optional[int]
    fan_speed: Optional[int]
    last_update: Optional[datetime]


class PowerControlRequest(BaseModel):
    action: str  # on/off/reset/status


class PowerControlResponse(BaseModel):
    node_id: int
    action: str
    success: bool
    message: str
    power_status: Optional[str]


async def scan_bmc_subnet(subnet: str, timeout: int = 5) -> List[dict]:
    """
    扫描 BMC 子网发现节点
    实际环境需要使用 ipmitool 或 ping 扫描
    """
    # 模拟返回，实际部署时替换为真实扫描逻辑
    discovered = []

    # 示例：使用 nmap 或 ping 扫描
    # 实际代码：
    # result = subprocess.run(['nmap', '-sn', subnet], capture_output=True)
    # 解析结果...

    # 模拟返回数据
    base_ip = subnet.split('/')[0].rsplit('.', 1)[0]
    for i in range(1, 10):
        discovered.append({
            "bmc_ip": f"{base_ip}.{i}",
            "bmc_mac": f"00:1a:2b:3c:4d:{i:02d}",
            "bmc_model": "iKVM",
            "bmc_version": "2.0",
            "power_status": "on"
        })

    return discovered


@router.post("/discover")
async def discover_bmc_nodes(
    request: BMCDiscoverRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    BMC节点发现扫描
    扫描指定子网，发现所有BMC节点
    """
    discovered = await scan_bmc_subnet(request.subnet, request.timeout)

    # 创建或更新节点记录
    new_count = 0
    updated_count = 0

    for bmc in discovered:
        existing = db.query(Node).filter(Node.bmc_ip == bmc["bmc_ip"]).first()
        if existing:
            existing.bmc_mac = bmc.get("bmc_mac")
            existing.status = "discovered"
            updated_count += 1
        else:
            new_node = Node(
                hostname=f"node-{bmc['bmc_ip'].split('.')[-1]}",
                node_type="unknown",  # 待后续确认类型
                bmc_ip=bmc["bmc_ip"],
                bmc_mac=bmc.get("bmc_mac"),
                status="discovered"
            )
            db.add(new_node)
            new_count += 1

    db.commit()

    return {
        "message": "BMC扫描完成",
        "subnet": request.subnet,
        "discovered_count": len(discovered),
        "new_nodes": new_count,
        "updated_nodes": updated_count,
        "nodes": discovered
    }


@router.get("/nodes/{node_id}/info", response_model=BMCInfoResponse)
async def get_bmc_info(node_id: int, db: Session = Depends(get_db)):
    """获取节点BMC详细信息"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    bmc_info = db.query(BMCInfo).filter(BMCInfo.node_id == node_id).first()

    if bmc_info:
        return bmc_info

    # 如果没有记录，返回基本信息
    return BMCInfoResponse(
        id=0,
        node_id=node_id,
        bmc_ip=node.bmc_ip or "",
        bmc_mac=node.bmc_mac,
        power_status="unknown"
    )


@router.post("/nodes/{node_id}/power", response_model=PowerControlResponse)
async def power_control(
    node_id: int,
    request: PowerControlRequest,
    db: Session = Depends(get_db)
):
    """
    远程电源控制
    支持操作: on/off/reset/status
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node or not node.bmc_ip:
        raise HTTPException(status_code=404, detail="节点不存在或无BMC信息")

    # 实际实现需要使用 ipmitool
    # 示例命令: ipmitool -I lanplus -H <bmc_ip> -U <user> -P <pass> power <action>

    success = True
    message = f"电源操作 '{request.action}' 已执行"
    power_status = "on"

    # 更新BMC信息
    bmc_info = db.query(BMCInfo).filter(BMCInfo.node_id == node_id).first()
    if bmc_info:
        bmc_info.power_status = power_status
        bmc_info.last_update = datetime.utcnow()
    else:
        bmc_info = BMCInfo(
            node_id=node_id,
            power_status=power_status,
            last_update=datetime.utcnow()
        )
        db.add(bmc_info)

    db.commit()

    return PowerControlResponse(
        node_id=node_id,
        action=request.action,
        success=success,
        message=message,
        power_status=power_status
    )


@router.post("/nodes/{node_id}/boot-pxe")
async def set_pxe_boot(node_id: int, db: Session = Depends(get_db)):
    """
    设置节点下次启动从PXE网络启动
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node or not node.bmc_ip:
        raise HTTPException(status_code=404, detail="节点不存在或无BMC信息")

    # 实际实现:
    # ipmitool -I lanplus -H <bmc_ip> -U <user> -P <pass> chassis bootdev pxe

    node.status = "deploying"
    db.commit()

    return {
        "node_id": node_id,
        "bmc_ip": node.bmc_ip,
        "message": "已设置PXE启动，等待节点重启",
        "status": "deploying"
    }


@router.get("/nodes/{node_id}/sensors")
async def get_bmc_sensors(node_id: int, db: Session = Depends(get_db)):
    """获取BMC传感器数据（温度、风扇等）"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    # 实际实现:
    # ipmitool -I lanplus -H <bmc_ip> -U <user> -P <pass> sdr list

    # 模拟返回
    return {
        "node_id": node_id,
        "bmc_ip": node.bmc_ip,
        "sensors": [
            {"name": "CPU Temp", "value": 45, "unit": "C", "status": "normal"},
            {"name": "System Temp", "value": 38, "unit": "C", "status": "normal"},
            {"name": "Fan 1", "value": 3200, "unit": "RPM", "status": "normal"},
            {"name": "Fan 2", "value": 3150, "unit": "RPM", "status": "normal"},
            {"name": "Power", "value": 120, "unit": "W", "status": "normal"}
        ]
    }