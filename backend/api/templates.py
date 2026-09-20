"""
机台模板 API —— 产品 → 机台类型

模板存 JSON 文件 (BASE_DIR/node_templates.json), 不入库。产品定义共用的角色配置,
机台类型只定义各角色的台数。

这里最关键的一个接口是 GET /topology: 只给产品和机台类型就能返回整张组网图,
不碰数据库、不需要先有真节点 —— 这正是"搞模板是为了能快速生成某个产品机台的
组网图"那句话的落点。

选机台类型、把节点加载出来走 /api/workspace; 本模块管的是模板本身。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.node import Node, get_db
from services import template_service, templates_io, topology_service

router = APIRouter()


# ── Pydantic 模型 ─────────────────────────────────────────────────────────────

class PlaneSpec(BaseModel):
    """
    角色接入某个平面的声明 —— 组网图和诊断项都从这里推导。

    prefixes 是列表: 同一个平面上可以有多块网卡。Master 数据面就是四个 IP ——
    前段 DPDK 两个 + 后段 RDMA 两个。
    """
    plane: str                       # management / control / data_front / data_back
    prefixes: List[str] = []         # 网段前缀, 如 ["200.1.1.", "200.1.2."]
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
    """
    列出全部产品及其角色、机台类型。

    带上 problems/warnings —— 老文件里可能就存着"角色没配平面"这种画不出图的模板,
    打开模板页就该看见, 不用等到发现节点没 IP 才回来查。
    """
    data = template_service.read_templates()
    errors, warnings = template_service.validate(data)
    return {**data, "problems": errors, "warnings": warnings}


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

    # 规整一遍再体检 —— 体检看的是"真正会存下去的样子", 不是请求里写的样子
    normalized = template_service._normalize(body.dict())
    errors, warnings = template_service.validate(normalized)
    if errors:
        # 这一类错误存下去不会报错, 但节点会没有 IP、组网图会是空的。宁可在这里挡住
        raise HTTPException(status_code=400, detail=" ".join(errors[:3]))

    saved = template_service.write_templates(body.dict())
    return {**saved, "warnings": warnings}


# ── 导入 / 导出 ───────────────────────────────────────────────────────────────

@router.get("/export")
def export_templates(
    product: Optional[str] = Query(None, description="只导这一个产品; 不给就是整份"),
) -> Dict[str, Any]:
    """
    导出模板文件。

    模板才是要在机器之间搬的那份东西 —— 节点是照着它生成出来的。导出→改几行→
    导回来是闭环的: 形状和 node_templates.json 一致, 单个产品也能直接导回去。
    """
    try:
        return templates_io.export(product)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/import")
async def import_templates(
    file: UploadFile = File(..., description="node_templates.json"),
    dry_run: bool = Query(True, description="true = 只看会变成什么样, 不写文件"),
    mode: str = Query("merge", description="merge = 同名产品换掉其余留着; replace = 整份覆盖"),
) -> Dict[str, Any]:
    """
    导入模板。默认只预览: 哪些产品新增 / 覆盖(具体动了哪些角色和台数) / 不变。

    确认之后带 dry_run=false 再传一次才写文件。写完记得让前端点一下
    POST /api/workspace/reload 把节点对齐过来。
    """
    if mode not in templates_io.MODES:
        raise HTTPException(status_code=400, detail=f"不认识的导入方式: {mode}")
    try:
        raw = templates_io.load_bytes(await file.read())
        incoming, problems = templates_io.parse(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    preview = templates_io.plan(template_service.read_templates(), incoming, mode=mode)
    preview["problems"] = problems
    preview["filename"] = file.filename
    preview["dry_run"] = dry_run

    saved = None
    if not dry_run:
        try:
            saved = templates_io.apply(preview)
        except ValueError as e:
            # 角色没配平面这一类: 存进去不报错, 但节点会没 IP、组网图会是空的
            raise HTTPException(status_code=400, detail=str(e))

    # result 是整份合并后的模板, 只给 apply 用 —— 没必要再回一份给前端
    preview.pop("result", None)
    if saved:
        preview["products"] = saved["products"]
    return preview


# ── 组网图 (不碰数据库) ───────────────────────────────────────────────────────

@router.get("/topology")
def template_topology(
    product: str = Query(..., description="产品名称"),
    machine_type: str = Query(..., description="机台类型名称"),
) -> Dict[str, Any]:
    """
    只按模板画组网图 —— 装机之前就能确认组网是不是想要的那样。

    这里不查数据库: 节点是按模板排出来的规划值, 状态一律 planned。要看实际状态
    请用 /api/workspace/topology。
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
    按产品 + 机台类型批量创建节点, 避开已被占用的主机名 / IP。

    正常流程是 PUT /api/workspace 选机台类型, 那条路会把节点整体对齐到模板。
    这个接口留给"往现有节点表里补几台"这种零散场景。
    """
    planned, conflicts = _expand(req.product, req.machine_type, db)
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
        "product": req.product,
        "machine_type": req.machine_type,
        "created": len(created),
        "hostnames": created,
        "conflicts": conflicts,
    }
