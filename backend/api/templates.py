"""
机台模板 API —— 产品 → 机台类型

模板存 JSON 文件 (BASE_DIR/node_templates.json), 不入库。产品定义共用的角色配置,
机台类型只定义各角色的台数。

这里最关键的一个接口是 GET /topology: 只给产品和机台类型就能返回整张组网图,
不碰数据库、不需要先有真节点 —— 这正是"搞模板是为了能快速生成某个产品机台的
组网图"那句话的落点。

实际建一套集群走 /api/clusters; 本模块的 /preview 与 /apply 是不带集群的散装用法,
留给"往已有集群里补几台"这种场景。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.node import Cluster, Node, get_db
from services import template_service, topology_service

router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class PlaneSpec(BaseModel):
    """角色接入某个平面的声明 —— 组网图和诊断项都从这里推导"""
    plane: str                       # management / control / data_front / data_back
    prefix: str = ""                 # 网段前缀, 如 172.16.3.
    protocol: str = ""               # DPDK / RDMA, 仅数据面有意义
    bandwidth: str = ""
    switch: str = ""


class RoleSpec(BaseModel):
    """产品级角色定义 —— 不含台数, 台数由机台类型给"""
    key: str = ""                    # 角色标识, 留空则从 node_type 推
    label: str = ""
    node_type: str = "slave"
    hostname_prefix: str = "node"
    role: str = ""
    hostname_start: int = 1
    ip_start: int = 1
    planes: List[PlaneSpec] = []
    checks: List[str] = []
    os_version: str = ""
    cpu_cores: Optional[int] = None
    memory_gb: Optional[int] = None
    disk_gb: Optional[int] = None
    note: str = ""


class MachineTypeSpec(BaseModel):
    """机台类型 —— counts 按角色的 key 索引"""
    name: str
    description: str = ""
    counts: Dict[str, int] = {}


class ProductSpec(BaseModel):
    name: str
    description: str = ""
    roles: List[RoleSpec] = []
    machine_types: List[MachineTypeSpec] = []


class TemplatesSave(BaseModel):
    products: List[ProductSpec] = []


class ApplyRequest(BaseModel):
    product: str
    machine_type: str
    cluster_id: Optional[int] = None


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


def _locate(product_name: str, machine_name: str):
    product, machine = template_service.find_machine_type(product_name, machine_name)
    if not product:
        raise HTTPException(status_code=404, detail=f"产品不存在: {product_name}")
    if not machine:
        raise HTTPException(status_code=404, detail=f"机台类型不存在: {machine_name}")
    return product, machine


def _expand(product_name: str, machine_name: str, db: Session):
    product, machine = _locate(product_name, machine_name)
    used_hostnames, used_ips = _collect_used(db)
    planned, conflicts = template_service.expand(product, machine, used_hostnames, used_ips)
    for spec in planned:
        spec["product"] = product["name"]
        spec["machine_type"] = machine["name"]
    return planned, conflicts


# ── 模板维护 ──────────────────────────────────────────────────────────────────

@router.get("")
def list_templates() -> Dict[str, Any]:
    """列出全部产品及其角色、机台类型"""
    return template_service.read_templates()


@router.get("/meta")
def meta() -> Dict[str, Any]:
    """平面与检查项的可选值 —— 前端拿它渲染模板编辑器的下拉框"""
    return {
        "planes": [{"key": k, **template_service.PLANES[k]}
                   for k in template_service.PLANE_ORDER],
        "checks": [{"key": k, **v} for k, v in template_service.CHECKS.items()],
    }


@router.put("")
def save_templates(body: TemplatesSave) -> Dict[str, Any]:
    """整份覆盖保存模板文件"""
    names = [p.name.strip() for p in body.products]
    if any(not n for n in names):
        raise HTTPException(status_code=400, detail="产品名称不能为空")
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise HTTPException(status_code=400, detail=f"产品名称重复: {', '.join(sorted(dup))}")

    for product in body.products:
        machines = [m.name.strip() for m in product.machine_types]
        if any(not m for m in machines):
            raise HTTPException(
                status_code=400, detail=f"产品「{product.name}」下有机台类型未填名称"
            )
        dup_m = {m for m in machines if machines.count(m) > 1}
        if dup_m:
            raise HTTPException(
                status_code=400,
                detail=f"产品「{product.name}」下机台类型名称重复: {', '.join(sorted(dup_m))}",
            )
        if not product.roles:
            raise HTTPException(
                status_code=400, detail=f"产品「{product.name}」至少要有一个角色"
            )

    return template_service.write_templates(body.dict())


# ── 组网图 (不碰数据库) ───────────────────────────────────────────────────────

@router.get("/topology")
def template_topology(
    product: str = Query(..., description="产品名称"),
    machine_type: str = Query(..., description="机台类型名称"),
) -> Dict[str, Any]:
    """
    只按模板画组网图 —— 装机之前就能确认组网是不是想要的那样。

    这里不查数据库: 节点是按模板排出来的规划值, 状态一律 planned。要看实际状态
    请用 /api/clusters/{id}/topology。
    """
    product_tpl, machine = _locate(product, machine_type)
    return topology_service.build(product_tpl, machine)


# ── 展开与应用 ────────────────────────────────────────────────────────────────

@router.get("/preview")
def preview(
    product: str = Query(..., description="产品名称"),
    machine_type: str = Query(..., description="机台类型名称"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """预览某产品某机台类型将创建的节点, 不写库"""
    planned, conflicts = _expand(product, machine_type, db)
    return {
        "product": product,
        "machine_type": machine_type,
        "total": len(planned),
        "nodes": planned,
        "conflicts": conflicts,
    }


@router.post("/apply")
def apply_template(req: ApplyRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    按产品 + 机台类型批量创建节点。

    给了 cluster_id 就挂到那套集群下; 不给则创建无归属节点 —— 正常流程是走
    POST /api/clusters 直接建集群, 那条路会一并把节点排好。
    """
    planned, conflicts = _expand(req.product, req.machine_type, db)
    if not planned:
        raise HTTPException(
            status_code=400,
            detail="没有可创建的节点" + (f": {'; '.join(conflicts)}" if conflicts else ""),
        )

    cluster_id = None
    if req.cluster_id is not None:
        cluster = db.query(Cluster).filter(Cluster.id == req.cluster_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail=f"集群不存在: {req.cluster_id}")
        cluster_id = cluster.id

    created = []
    for spec in planned:
        db.add(Node(cluster_id=cluster_id, **spec))
        created.append(spec["hostname"])
    db.commit()

    return {
        "product": req.product,
        "machine_type": req.machine_type,
        "cluster_id": cluster_id,
        "created": len(created),
        "hostnames": created,
        "conflicts": conflicts,
    }
