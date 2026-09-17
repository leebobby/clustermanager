"""
机台型号模板 API — 模板维护 + 按型号批量展开节点

模板存 JSON 文件 (BASE_DIR/node_templates.json), 不入库。
展开时按角色的起始序号自增, 自动跳过数据库里已被占用的主机名 / IP。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.node import Node, get_db
from services import template_service

router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class RoleSpec(BaseModel):
    node_type: str = "slave"
    count: int = 1
    hostname_prefix: str = "node"
    role: str = ""
    data_protocol: str = ""
    bmc_prefix: str = ""
    ctrl_prefix: str = ""
    data_prefix: str = ""
    hostname_start: int = 1
    ip_start: int = 1
    os_version: str = ""
    cpu_cores: Optional[int] = None
    memory_gb: Optional[int] = None
    disk_gb: Optional[int] = None


class TemplateSpec(BaseModel):
    model: str
    description: str = ""
    roles: List[RoleSpec] = []


class TemplatesSave(BaseModel):
    templates: List[TemplateSpec] = []


class ApplyRequest(BaseModel):
    model: str


# ── 当前占用情况 ──────────────────────────────────────────────────────────────

def _collect_used(db: Session):
    """从数据库收集已占用的主机名与 IP, 供展开时避让"""
    used_hostnames = set()
    used_ips = set()
    for node in db.query(Node).all():
        if node.hostname:
            used_hostnames.add(node.hostname)
        for ip in (node.mgmt_ip, node.bmc_ip, node.ctrl_ip, node.data_ip):
            if ip:
                used_ips.add(ip)
    return used_hostnames, used_ips


def _expand(model: str, db: Session):
    tpl = template_service.find_template(model)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"模板不存在: {model}")
    used_hostnames, used_ips = _collect_used(db)
    return template_service.expand_template(tpl, used_hostnames, used_ips)


# ── 模板维护 ──────────────────────────────────────────────────────────────────

@router.get("")
def list_templates() -> Dict[str, Any]:
    """列出全部机台型号模板"""
    return template_service.read_templates()


@router.put("")
def save_templates(body: TemplatesSave) -> Dict[str, Any]:
    """整份覆盖保存模板文件"""
    models = [t.model.strip() for t in body.templates]
    if any(not m for m in models):
        raise HTTPException(status_code=400, detail="型号名称不能为空")
    duplicates = {m for m in models if models.count(m) > 1}
    if duplicates:
        raise HTTPException(status_code=400, detail=f"型号名称重复: {', '.join(sorted(duplicates))}")
    return template_service.write_templates(body.dict())


# ── 展开与应用 ────────────────────────────────────────────────────────────────

@router.get("/{model}/preview")
def preview_template(model: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """预览某型号将创建的节点, 不写库"""
    planned, conflicts = _expand(model, db)
    return {"model": model, "total": len(planned), "nodes": planned, "conflicts": conflicts}


@router.post("/apply")
def apply_template(req: ApplyRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """按型号批量创建节点"""
    planned, conflicts = _expand(req.model, db)
    if not planned:
        raise HTTPException(
            status_code=400,
            detail="没有可创建的节点" + (f": {'; '.join(conflicts)}" if conflicts else ""),
        )

    created = []
    for spec in planned:
        db.add(Node(**spec))
        created.append(spec["hostname"])
    db.commit()

    return {
        "model": req.model,
        "created": len(created),
        "hostnames": created,
        "conflicts": conflicts,
    }
