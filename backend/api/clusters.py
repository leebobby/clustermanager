"""
集群 API —— 现场一台机台 = 一套集群。

建集群 = 选产品 + 选机台类型 + 填一个机台编号, 后端按模板把节点一次排出来。
之后组网图、一键诊断、节点清单全部按 cluster_id 收口, 现场只看眼前这一套。

一键诊断 (POST /{id}/diagnose) 只当场跑内建项 —— ping / BMC / SSH, 从本机探,
不需要登录被测机, 几秒出结果。要登机器才能看的角色专项(RDMA 链路、NFS 挂载、
磁盘水位)由诊断脚本实现, 计划里带着脚本 id 返回 pending, 由前端接着调
/api/diagnose/scripts/batch-run 执行。没有脚本认领的项如实标成"未配置", 不会
算成通过 —— 一份把没查的项算成通过的体检报告比没有报告更糟。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.node import Cluster, DiagScript, Node, get_db
from services import diag_plan, template_service, topology_service

router = APIRouter()


# ── Pydantic ──────────────────────────────────────────────────────────────────

class ClusterCreate(BaseModel):
    name: str
    product: str
    machine_type: str
    site: str = ""
    note: str = ""
    create_nodes: bool = True


class ClusterUpdate(BaseModel):
    name: Optional[str] = None
    site: Optional[str] = None
    note: Optional[str] = None


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _cluster_or_404(cluster_id: int, db: Session) -> Cluster:
    cluster = db.query(Cluster).filter(Cluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail=f"集群不存在: {cluster_id}")
    return cluster


def _template_or_404(product_name: str, machine_name: str):
    product, machine = template_service.find_machine_type(product_name, machine_name)
    if not product:
        raise HTTPException(status_code=404, detail=f"产品不存在: {product_name}")
    if not machine:
        raise HTTPException(status_code=404, detail=f"机台类型不存在: {machine_name}")
    return product, machine


def _serialize(cluster: Cluster, node_count: int = 0) -> Dict[str, Any]:
    return {
        "id": cluster.id,
        "name": cluster.name,
        "product": cluster.product,
        "machine_type": cluster.machine_type,
        "site": cluster.site or "",
        "note": cluster.note or "",
        "node_count": node_count,
        "created_at": cluster.created_at,
        "last_diagnosed_at": cluster.last_diagnosed_at,
    }


def _scripts_by_check(db: Session) -> Dict[str, Dict]:
    """
    {check_key: 脚本}。一个检查项被多个脚本认领时取 id 最小的那个 —— 取哪个都行,
    但必须稳定, 否则每次诊断挑中的脚本不一样, 结果就没法比对。
    """
    rows = (db.query(DiagScript)
            .filter(DiagScript.enabled.is_(True))
            .filter(DiagScript.check_key.isnot(None))
            .filter(DiagScript.check_key != "")
            .order_by(DiagScript.id.asc())
            .all())
    out: Dict[str, Dict] = {}
    for row in rows:
        out.setdefault(row.check_key, {"id": row.id, "name": row.name})
    return out


# ── 集群 CRUD ─────────────────────────────────────────────────────────────────

@router.get("")
def list_clusters(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """列出全部集群, 带节点数"""
    clusters = db.query(Cluster).order_by(Cluster.created_at.desc()).all()
    counts = {}
    for cluster_id, in db.query(Node.cluster_id).filter(Node.cluster_id.isnot(None)).all():
        counts[cluster_id] = counts.get(cluster_id, 0) + 1
    return [_serialize(c, counts.get(c.id, 0)) for c in clusters]


@router.post("")
def create_cluster(req: ClusterCreate, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """按 产品 + 机台类型 建一套集群, 默认同时把节点排出来"""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="机台编号不能为空")
    if db.query(Cluster).filter(Cluster.name == name).first():
        raise HTTPException(status_code=400, detail=f"机台编号已存在: {name}")

    product, machine = _template_or_404(req.product, req.machine_type)

    cluster = Cluster(
        name=name, product=product["name"], machine_type=machine["name"],
        site=req.site.strip(), note=req.note,
    )
    db.add(cluster)
    db.flush()          # 先拿到 id, 节点要挂上去

    created: List[str] = []
    conflicts: List[str] = []
    if req.create_nodes:
        used_hostnames, used_ips = _collect_used(db)
        planned, conflicts = template_service.expand(
            product, machine, used_hostnames, used_ips
        )
        for spec in planned:
            db.add(Node(cluster_id=cluster.id, product=product["name"],
                        machine_type=machine["name"], **spec))
            created.append(spec["hostname"])

    db.commit()
    db.refresh(cluster)
    return {**_serialize(cluster, len(created)), "created": len(created),
            "hostnames": created, "conflicts": conflicts}


@router.get("/{cluster_id}")
def get_cluster(cluster_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    cluster = _cluster_or_404(cluster_id, db)
    count = db.query(Node).filter(Node.cluster_id == cluster_id).count()
    return _serialize(cluster, count)


@router.put("/{cluster_id}")
def update_cluster(cluster_id: int, req: ClusterUpdate,
                   db: Session = Depends(get_db)) -> Dict[str, Any]:
    cluster = _cluster_or_404(cluster_id, db)
    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="机台编号不能为空")
        clash = db.query(Cluster).filter(Cluster.name == name,
                                         Cluster.id != cluster_id).first()
        if clash:
            raise HTTPException(status_code=400, detail=f"机台编号已存在: {name}")
        cluster.name = name
    if req.site is not None:
        cluster.site = req.site.strip()
    if req.note is not None:
        cluster.note = req.note
    db.commit()
    db.refresh(cluster)
    count = db.query(Node).filter(Node.cluster_id == cluster_id).count()
    return _serialize(cluster, count)


@router.delete("/{cluster_id}")
def delete_cluster(
    cluster_id: int,
    with_nodes: bool = Query(False, description="连同这套集群的节点一起删"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    默认只删集群本身, 节点留着变成"无归属" —— 删一套集群顺手清掉几十台机器的
    记录是不可逆的, 要删得明着说。
    """
    cluster = _cluster_or_404(cluster_id, db)
    nodes = db.query(Node).filter(Node.cluster_id == cluster_id).all()

    if with_nodes:
        for node in nodes:
            db.delete(node)
        removed = len(nodes)
    else:
        for node in nodes:
            node.cluster_id = None
        removed = 0

    db.delete(cluster)
    db.commit()
    return {"deleted": cluster.name, "nodes_deleted": removed,
            "nodes_detached": 0 if with_nodes else len(nodes)}


@router.get("/{cluster_id}/nodes")
def list_cluster_nodes(cluster_id: int, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    _cluster_or_404(cluster_id, db)
    nodes = (db.query(Node).filter(Node.cluster_id == cluster_id)
             .order_by(Node.hostname.asc()).all())
    return [{
        "id": n.id, "hostname": n.hostname, "node_type": n.node_type,
        "role_key": n.role_key, "role": n.role, "status": n.status,
        "mgmt_ip": n.mgmt_ip, "bmc_ip": n.bmc_ip, "ctrl_ip": n.ctrl_ip,
        "data_ip": n.data_ip, "data_protocol": n.data_protocol,
        "os_version": n.os_version, "cpu_cores": n.cpu_cores,
        "memory_gb": n.memory_gb, "disk_gb": n.disk_gb,
    } for n in nodes]


# ── 组网图 ────────────────────────────────────────────────────────────────────

@router.get("/{cluster_id}/topology")
def cluster_topology(cluster_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """这套集群的组网图, 用真节点叠在模板版式上"""
    cluster = _cluster_or_404(cluster_id, db)
    product, machine = _template_or_404(cluster.product, cluster.machine_type)
    nodes = db.query(Node).filter(Node.cluster_id == cluster_id).all()
    graph = topology_service.build(product, machine, nodes)
    graph["cluster"] = {"id": cluster.id, "name": cluster.name, "site": cluster.site or ""}
    return graph


# ── 一键诊断 ──────────────────────────────────────────────────────────────────

@router.get("/{cluster_id}/diagnose/plan")
def diagnose_plan(cluster_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """只出检查计划, 不实际探测 —— 用来确认"这次会查哪些东西"""
    cluster = _cluster_or_404(cluster_id, db)
    product, machine = _template_or_404(cluster.product, cluster.machine_type)
    nodes = db.query(Node).filter(Node.cluster_id == cluster_id).all()
    graph = topology_service.build(product, machine, nodes)
    items = diag_plan.build_plan(graph, _scripts_by_check(db))
    return {
        "cluster": {"id": cluster.id, "name": cluster.name},
        "summary": diag_plan.summarize(items),
        "items": diag_plan.sort_items(items),
        "mismatches": graph["mismatches"],
    }


@router.post("/{cluster_id}/diagnose")
def diagnose(
    cluster_id: int,
    timeout_ms: int = Query(1000, ge=200, le=10000, description="单次探测超时(毫秒)"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    跑一次一键诊断。

    内建项(ping / BMC / SSH)当场并发实测; 角色专项返回 pending 并带脚本 id,
    由前端接着走 /api/diagnose/scripts/batch-run。
    """
    cluster = _cluster_or_404(cluster_id, db)
    product, machine = _template_or_404(cluster.product, cluster.machine_type)
    nodes = db.query(Node).filter(Node.cluster_id == cluster_id).all()
    if not nodes:
        raise HTTPException(status_code=400,
                            detail=f"集群「{cluster.name}」下还没有节点, 先从模板生成节点再诊断")

    graph = topology_service.build(product, machine, nodes)
    items = diag_plan.build_plan(graph, _scripts_by_check(db))
    started = datetime.utcnow()
    diag_plan.run_builtin(items, timeout_ms=timeout_ms)
    elapsed = (datetime.utcnow() - started).total_seconds()

    # 顺手把探测结果回写到节点状态 —— 管理面通不通就是这台机器在不在线
    reachable = {}
    for item in items:
        if item["check"] == "ping" and item.get("plane") == "management":
            reachable[item["target"]] = item["status"]
    for node in nodes:
        status = reachable.get(node.hostname)
        if status in (diag_plan.PASS, diag_plan.WARN):
            node.status = "online"
            node.last_seen = started
        elif status == diag_plan.FAIL:
            node.status = "offline"

    cluster.last_diagnosed_at = started
    db.commit()

    return {
        "cluster": {"id": cluster.id, "name": cluster.name,
                    "product": cluster.product, "machine_type": cluster.machine_type},
        "summary": diag_plan.summarize(items),
        "items": diag_plan.sort_items(items),
        "mismatches": graph["mismatches"],
        "elapsed_seconds": round(elapsed, 1),
        "diagnosed_at": started,
    }


# ── 与 templates.py 共用 ──────────────────────────────────────────────────────

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
