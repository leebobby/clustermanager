"""
节点模板 API — 两级结构: 项目 → 机台类型

模板存 JSON 文件 (BASE_DIR/node_templates.json), 不入库。
项目定义共用的角色配置, 机台类型只定义各角色的台数。

展开时自动跳过数据库里已被占用的主机名 / IP; 创建出来的节点会记录
来源的项目与机台类型, 供组网图与运维侧按机台归类。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.node import Node, get_db
from services import template_service

router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class RoleSpec(BaseModel):
    """项目级角色定义 — 不含台数, 台数由机台类型给"""
    node_type: str = "slave"
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


class MachineTypeSpec(BaseModel):
    """机台类型 — counts 按角色的 hostname_prefix 索引"""
    name: str
    description: str = ""
    counts: Dict[str, int] = {}


class ProjectSpec(BaseModel):
    name: str
    description: str = ""
    roles: List[RoleSpec] = []
    machine_types: List[MachineTypeSpec] = []


class TemplatesSave(BaseModel):
    projects: List[ProjectSpec] = []


class ApplyRequest(BaseModel):
    project: str
    machine_type: str


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


def _expand(project_name: str, machine_name: str, db: Session):
    project, machine = template_service.find_machine_type(project_name, machine_name)
    if not project:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_name}")
    if not machine:
        raise HTTPException(status_code=404, detail=f"机台类型不存在: {machine_name}")
    used_hostnames, used_ips = _collect_used(db)
    planned, conflicts = template_service.expand(project, machine, used_hostnames, used_ips)
    # 记录来源, 供组网图 / 运维按机台归类
    for spec in planned:
        spec["project"] = project["name"]
        spec["machine_type"] = machine["name"]
    return planned, conflicts


# ── 模板维护 ──────────────────────────────────────────────────────────────────

@router.get("")
def list_templates() -> Dict[str, Any]:
    """列出全部项目及其机台类型"""
    return template_service.read_templates()


@router.put("")
def save_templates(body: TemplatesSave) -> Dict[str, Any]:
    """整份覆盖保存模板文件"""
    names = [p.name.strip() for p in body.projects]
    if any(not n for n in names):
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise HTTPException(status_code=400, detail=f"项目名称重复: {', '.join(sorted(dup))}")

    for project in body.projects:
        machines = [m.name.strip() for m in project.machine_types]
        if any(not m for m in machines):
            raise HTTPException(
                status_code=400, detail=f"项目「{project.name}」下有机台类型未填名称"
            )
        dup_m = {m for m in machines if machines.count(m) > 1}
        if dup_m:
            raise HTTPException(
                status_code=400,
                detail=f"项目「{project.name}」下机台类型名称重复: {', '.join(sorted(dup_m))}",
            )

    return template_service.write_templates(body.dict())


# ── 展开与应用 ────────────────────────────────────────────────────────────────

@router.get("/preview")
def preview(
    project: str = Query(..., description="项目名称"),
    machine_type: str = Query(..., description="机台类型名称"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """预览某项目某机台类型将创建的节点, 不写库"""
    planned, conflicts = _expand(project, machine_type, db)
    return {
        "project": project,
        "machine_type": machine_type,
        "total": len(planned),
        "nodes": planned,
        "conflicts": conflicts,
    }


@router.post("/apply")
def apply_template(req: ApplyRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """按项目 + 机台类型批量创建节点"""
    planned, conflicts = _expand(req.project, req.machine_type, db)
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
        "project": req.project,
        "machine_type": req.machine_type,
        "created": len(created),
        "hostnames": created,
        "conflicts": conflicts,
    }
