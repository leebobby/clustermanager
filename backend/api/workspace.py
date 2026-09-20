"""
当前机台 API —— 本工具一次只对着一台机台。

没有"新建集群"这一步, 也没有机台编号 / 厂区 / 产线: 打开工具选一个机台类型,
节点就按模板加载出来。换机台类型 = 按新模板重新加载。

一键诊断可以只跑勾上的项。全量跑在现场不现实(几十台机器 × 几百项), 所以
GET /diagnose/options 列出这次能勾什么, POST /diagnose 带上勾选结果。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.node import DiagScript, Node, get_db
from services import (diag_plan, nodes_import, template_service, topology_service,
                      workspace_service)

router = APIRouter()

# 上一次诊断的时间, 只是给界面显示用, 不值得为它建表
_LAST_DIAGNOSED: Dict[str, Optional[datetime]] = {"at": None}


class SelectRequest(BaseModel):
    product: str
    machine_type: str


class DiagnoseRequest(BaseModel):
    """两个都不给就是全都要"""
    checks: List[str] = []
    roles: List[str] = []
    timeout_ms: int = 1000


def _current():
    product, machine = workspace_service.resolve()
    if not product:
        raise HTTPException(status_code=400,
                            detail="模板里还没有产品, 先到「机台与模板」页建一个")
    if not machine:
        raise HTTPException(
            status_code=400,
            detail=f"产品「{product['name']}」下还没有机台类型, 先到「机台与模板」页加一个")
    return product, machine


def _scripts_by_check(db: Session) -> Dict[str, Dict]:
    """
    {check_key: 脚本}。一个检查项被多个脚本认领时取 id 最小的 —— 取哪个都行,
    但必须稳定, 否则每次诊断挑中的脚本不一样, 结果没法比对。
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


def _topology(db: Session, product: Dict, machine: Dict) -> Dict:
    nodes = workspace_service.current_nodes(db, product, machine)
    graph = topology_service.build(product, machine, nodes)
    return graph


# ── 当前机台 ──────────────────────────────────────────────────────────────────

@router.get("")
def get_workspace(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """当前选的产品 / 机台类型, 以及可选的全部机台类型"""
    data = template_service.read_templates()
    available = [{
        "product": p["name"],
        "description": p.get("description", ""),
        "machine_types": [{
            "name": m["name"],
            "description": m.get("description", ""),
            "total": sum(m.get("counts", {}).values()),
        } for m in p["machine_types"]],
    } for p in data.get("products", [])]

    product, machine = workspace_service.resolve()
    node_count = 0
    if product and machine:
        node_count = len(workspace_service.current_nodes(db, product, machine))

    return {
        "product": product["name"] if product else "",
        "machine_type": machine["name"] if machine else "",
        "node_count": node_count,
        # 没选过就让界面弹选择框 —— 这是打开工具的第一步
        "chosen": bool(workspace_service.read_selection()["machine_type"]),
        "last_diagnosed_at": _LAST_DIAGNOSED["at"],
        "available": available,
    }


@router.put("")
def select_machine(req: SelectRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    选机台类型 —— 选完节点就按模板加载好了, 不需要再点第二下。

    换机台类型会按新模板重新加载节点列表: master-01 这种主机名在两种机台类型里
    都会出现, 旧的不清掉必然撞号。手工加的节点不受影响。
    """
    product, machine = template_service.find_machine_type(req.product, req.machine_type)
    if not product:
        raise HTTPException(status_code=404, detail=f"产品不存在: {req.product}")
    if not machine:
        raise HTTPException(status_code=404, detail=f"机台类型不存在: {req.machine_type}")

    workspace_service.write_selection(product["name"], machine["name"])
    result = workspace_service.sync_nodes(db, product, machine)
    return {
        "product": product["name"],
        "machine_type": machine["name"],
        "node_count": len(workspace_service.current_nodes(db, product, machine)),
        **result,
    }


@router.post("/reload")
def reload_nodes(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """改完模板按这里重新对齐节点。实测状态按主机名保留, 不会白测一遍"""
    product, machine = _current()
    result = workspace_service.sync_nodes(db, product, machine)
    return {
        "product": product["name"],
        "machine_type": machine["name"],
        "node_count": len(workspace_service.current_nodes(db, product, machine)),
        **result,
    }


@router.get("/nodes")
def list_nodes(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    product, machine = _current()
    return [{
        "id": n.id, "hostname": n.hostname, "node_type": n.node_type,
        "role_key": n.role_key, "role": n.role, "status": n.status,
        "mgmt_ip": n.mgmt_ip, "bmc_ip": n.bmc_ip, "ctrl_ip": n.ctrl_ip,
        "data_ip": n.data_ip, "data_protocol": n.data_protocol,
        "plane_ips": n.plane_ips or {}, "plane_status": n.plane_status or {},
        "os_version": n.os_version, "cpu_cores": n.cpu_cores,
        "memory_gb": n.memory_gb, "disk_gb": n.disk_gb,
    } for n in workspace_service.current_nodes(db, product, machine)]


# ── 导入 / 导出 nodes.json ────────────────────────────────────────────────────

@router.post("/nodes/import")
async def import_nodes(
    file: UploadFile = File(..., description="现场那份 nodes.json"),
    dry_run: bool = Query(True, description="true = 只看会改什么, 不写库"),
    remove_missing: bool = Query(False, description="把文件里没有的模板节点一并删掉"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    导入 nodes.json —— 模板排出来的是"该长什么样", 这份文件是现场"实际是什么样"。

    默认只预览: 哪几台新增、哪几台改了哪个平面、哪几台模板里有而文件里没有。
    确认之后再带 dry_run=false 传一次才写库。实测状态不会被这一步抹掉。
    """
    product, machine = _current()
    try:
        data = nodes_import.load_bytes(await file.read())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    rows, problems = nodes_import.parse(data)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="这份文件里没认出任何节点" + (f": {problems[0]}" if problems else ""))

    existing = workspace_service.current_nodes(db, product, machine)
    preview = nodes_import.plan(rows, product, machine, existing)
    preview["problems"] = problems
    preview["filename"] = file.filename
    preview["dry_run"] = dry_run
    if dry_run:
        return preview

    result = nodes_import.apply(db, preview, product, machine, remove_missing=remove_missing)
    preview["applied"] = result
    preview["node_count"] = len(workspace_service.current_nodes(db, product, machine))
    return preview


@router.get("/nodes/export")
def export_nodes(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """当前机台的节点导出成同一种 nodes.json —— 导出改几行再导回来"""
    product, machine = _current()
    nodes = workspace_service.current_nodes(db, product, machine)
    return nodes_import.export(nodes, product, machine)


# ── 组网图 ────────────────────────────────────────────────────────────────────

@router.get("/topology")
def topology(
    live: bool = Query(True, description="false = 只按模板画, 不看实测状态"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    product, machine = _current()
    if not live:
        return topology_service.build(product, machine)
    return _topology(db, product, machine)


# ── 一键诊断 ──────────────────────────────────────────────────────────────────

@router.get("/diagnose/options")
def diagnose_options(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """这次能勾哪些检查项、哪些角色, 各有多少个检查点"""
    product, machine = _current()
    graph = _topology(db, product, machine)
    items = diag_plan.build_plan(graph, _scripts_by_check(db))
    return {
        "product": product["name"],
        "machine_type": machine["name"],
        **diag_plan.options(items),
        "total": len(items),
    }


@router.post("/diagnose")
def diagnose(req: DiagnoseRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    跑一次诊断, 只跑勾上的。

    内建项(ping / BMC / SSH)当场并发实测; 角色专项返回 pending 并带脚本 id,
    由前端接着走 /api/diagnose/scripts/batch-run。
    """
    product, machine = _current()
    graph = _topology(db, product, machine)
    nodes = workspace_service.current_nodes(db, product, machine)
    if not nodes:
        raise HTTPException(
            status_code=400,
            detail=f"「{machine['name']}」下还没有节点, 到「机台与模板」页点一下「重新加载」")

    items = diag_plan.build_plan(graph, _scripts_by_check(db))
    items = diag_plan.select(items, req.checks, req.roles)
    if not items:
        raise HTTPException(status_code=400, detail="按当前勾选没有可跑的检查项")

    started = datetime.utcnow()
    diag_plan.run_builtin(items, timeout_ms=req.timeout_ms)
    elapsed = (datetime.utcnow() - started).total_seconds()

    # 把每平面的实测结果写回节点 —— 组网图靠它把通和断画成两个颜色。
    # 这次没查的平面保持原样, 不要用"没查"去覆盖上一次的有效结果。
    per_node = diag_plan.plane_status(items)
    by_name = {n.hostname: n for n in nodes}
    for hostname, planes in per_node.items():
        node = by_name.get(hostname)
        if not node:
            continue
        merged = dict(node.plane_status or {})
        for plane, state in planes.items():
            if state != "unknown":
                merged[plane] = state
        node.plane_status = merged
        mgmt = merged.get("management")
        if mgmt in ("online", "offline"):
            node.status = mgmt
            if mgmt == "online":
                node.last_seen = started

    _LAST_DIAGNOSED["at"] = started
    db.commit()

    return {
        "product": product["name"],
        "machine_type": machine["name"],
        "summary": diag_plan.summarize(items),
        "items": diag_plan.sort_items(items),
        "mismatches": graph["mismatches"],
        "elapsed_seconds": round(elapsed, 1),
        "diagnosed_at": started,
    }
