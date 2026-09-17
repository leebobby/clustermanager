"""
告警管理 API - 区分三平面
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from models.node import Alert, Node, get_db
from pydantic import BaseModel


router = APIRouter()


class AlertCreate(BaseModel):
    """告警创建"""
    node_id: Optional[int] = None
    link_id: Optional[int] = None
    plane: str  # 管理面/控制面/数据面
    alert_type: str
    severity: str  # critical/warning/info
    message: str


class AlertResponse(BaseModel):
    id: int
    node_id: Optional[int]
    link_id: Optional[int]
    plane: str
    alert_type: str
    severity: str
    message: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class AlertStats(BaseModel):
    """告警统计"""
    total: int
    critical: int
    warning: int
    info: int
    active: int
    resolved: int
    by_plane: dict


@router.get("/", response_model=List[AlertResponse])
def get_alerts(
    severity: Optional[str] = None,
    plane: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取告警列表，可按严重级别、平面、状态筛选"""
    query = db.query(Alert)
    if severity:
        query = query.filter(Alert.severity == severity)
    if plane:
        query = query.filter(Alert.plane == plane)
    if status:
        query = query.filter(Alert.status == status)
    return query.order_by(Alert.created_at.desc()).all()


@router.get("/active", response_model=List[AlertResponse])
def get_active_alerts(db: Session = Depends(get_db)):
    """获取所有活跃告警"""
    return db.query(Alert).filter(Alert.status == 'active').order_by(Alert.created_at.desc()).all()


@router.get("/stats", response_model=AlertStats)
def get_alert_stats(db: Session = Depends(get_db)):
    """获取告警统计"""
    alerts = db.query(Alert).all()

    total = len(alerts)
    critical = sum(1 for a in alerts if a.severity == 'critical' and a.status == 'active')
    warning = sum(1 for a in alerts if a.severity == 'warning' and a.status == 'active')
    info = sum(1 for a in alerts if a.severity == 'info' and a.status == 'active')
    active = sum(1 for a in alerts if a.status == 'active')
    resolved = sum(1 for a in alerts if a.status == 'resolved')

    by_plane = {
        "管理面": sum(1 for a in alerts if a.plane == '管理面' and a.status == 'active'),
        "控制面": sum(1 for a in alerts if a.plane == '控制面' and a.status == 'active'),
        "数据面": sum(1 for a in alerts if a.plane == '数据面' and a.status == 'active')
    }

    return AlertStats(
        total=total,
        critical=critical,
        warning=warning,
        info=info,
        active=active,
        resolved=resolved,
        by_plane=by_plane
    )


@router.post("/", response_model=AlertResponse)
def create_alert(alert: AlertCreate, db: Session = Depends(get_db)):
    """创建新告警"""
    db_alert = Alert(**alert.dict())
    db.add(db_alert)
    db.commit()
    db.refresh(db_alert)
    return db_alert


@router.put("/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    """确认告警"""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    alert.status = 'acknowledged'
    db.commit()
    return {"message": "告警已确认", "alert_id": alert_id}


@router.put("/{alert_id}/resolve")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    """解决告警"""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")

    alert.status = 'resolved'
    alert.resolved_at = datetime.utcnow()
    db.commit()
    return {"message": "告警已解决", "alert_id": alert_id}


@router.get("/by-node/{node_id}", response_model=List[AlertResponse])
def get_node_alerts(node_id: int, db: Session = Depends(get_db)):
    """获取指定节点的所有告警"""
    return db.query(Alert).filter(Alert.node_id == node_id).order_by(Alert.created_at.desc()).all()


@router.post("/check-rules")
def check_alert_rules(db: Session = Depends(get_db)):
    """检查告警规则（触发巡检）"""
    nodes = db.query(Node).all()
    triggered_alerts = []

    for node in nodes:
        # 检查管理面失联
        if node.bmc_ip and node.status != 'online':
            # 检查是否已有相同告警
            existing = db.query(Alert).filter(
                Alert.node_id == node.id,
                Alert.alert_type == 'node_offline',
                Alert.status == 'active'
            ).first()

            if not existing:
                alert = Alert(
                    node_id=node.id,
                    plane='管理面',
                    alert_type='node_offline',
                    severity='critical',
                    message=f"节点 {node.hostname} 管理面失联"
                )
                db.add(alert)
                triggered_alerts.append({
                    "node_id": node.id,
                    "hostname": node.hostname,
                    "alert_type": "node_offline",
                    "plane": "管理面"
                })

        # 检查控制面
        if node.ctrl_ip and node.ctrl_status != 'online':
            existing = db.query(Alert).filter(
                Alert.node_id == node.id,
                Alert.alert_type == 'control_plane_down',
                Alert.status == 'active'
            ).first()

            if not existing:
                alert = Alert(
                    node_id=node.id,
                    plane='控制面',
                    alert_type='control_plane_down',
                    severity='warning',
                    message=f"节点 {node.hostname} 控制面断开"
                )
                db.add(alert)
                triggered_alerts.append({
                    "node_id": node.id,
                    "hostname": node.hostname,
                    "alert_type": "control_plane_down",
                    "plane": "控制面"
                })

        # 检查数据面
        if node.data_ip and node.data_status != 'online':
            existing = db.query(Alert).filter(
                Alert.node_id == node.id,
                Alert.alert_type == 'data_plane_down',
                Alert.status == 'active'
            ).first()

            if not existing:
                alert = Alert(
                    node_id=node.id,
                    plane='数据面',
                    alert_type='data_plane_down',
                    severity='critical',
                    message=f"节点 {node.hostname} 数据面断开 ({node.data_protocol})"
                )
                db.add(alert)
                triggered_alerts.append({
                    "node_id": node.id,
                    "hostname": node.hostname,
                    "alert_type": "data_plane_down",
                    "plane": "数据面"
                })

    db.commit()

    return {
        "message": "告警规则检查完成",
        "triggered_count": len(triggered_alerts),
        "triggered_alerts": triggered_alerts
    }