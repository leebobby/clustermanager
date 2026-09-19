"""
当前机台 —— 本工具一次只对着一台机台。

没有"集群实例"这一层, 也不需要机台编号: 打开工具选一个机台类型(比如 A 产品的
A11), 节点就按模板加载出来, 之后组网图、一键诊断看的都是这一套。

选择记在 BASE_DIR/workspace.json 里, 跟模板文件放一起 —— 就一个选择, 不值得为它
建表。

切机台类型 = 按新模板重新加载节点列表。上一套模板生成的节点会被删掉, 因为
master-01 这种主机名在两种机台类型里都会出现, 留着必然撞号。手工加的节点
(role_key 为空)不受影响。
"""

import json
import os
from typing import Dict, List, Optional, Tuple

from config import BASE_DIR
from models.node import Node
from services import template_service as ts

WORKSPACE_PATH = os.path.join(BASE_DIR, "workspace.json")

# 模板里的这些字段是"该长什么样", 每次同步都按模板刷新
_SPEC_FIELDS = (
    "node_type", "role", "role_key", "os_version", "cpu_cores", "memory_gb",
    "disk_gb", "mgmt_ip", "bmc_ip", "ctrl_ip", "data_ip", "data_protocol",
    "plane_ips",
)


# ── 选择的读写 ────────────────────────────────────────────────────────────────

def read_selection() -> Dict[str, str]:
    """当前选的产品与机台类型; 没选过时两个都是空串"""
    try:
        with open(WORKSPACE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"product": "", "machine_type": ""}
    return {
        "product": str((raw or {}).get("product", "")),
        "machine_type": str((raw or {}).get("machine_type", "")),
    }


def write_selection(product: str, machine_type: str) -> Dict[str, str]:
    sel = {"product": str(product or ""), "machine_type": str(machine_type or "")}
    os.makedirs(os.path.dirname(WORKSPACE_PATH) or ".", exist_ok=True)
    with open(WORKSPACE_PATH, "w", encoding="utf-8") as f:
        json.dump(sel, f, ensure_ascii=False, indent=2)
    return sel


def resolve() -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    当前选择对应的 (产品, 机台类型)。

    没选过 —— 或者选的那个后来被从模板里删了 —— 就落到第一个可用的机台类型上,
    免得界面空在那里没法用。
    """
    data = ts.read_templates()
    products = data.get("products") or []
    if not products:
        return None, None

    sel = read_selection()
    product = next((p for p in products if p["name"] == sel["product"]), None)
    if product:
        machine = next(
            (m for m in product["machine_types"] if m["name"] == sel["machine_type"]), None
        )
        if machine:
            return product, machine

    for p in products:
        if p["machine_types"]:
            return p, p["machine_types"][0]
    return products[0], None


# ── 按模板加载节点 ────────────────────────────────────────────────────────────

def sync_nodes(db, product: Dict, machine: Dict) -> Dict[str, List[str]]:
    """
    把节点表对齐到 (产品, 机台类型) 的模板。幂等 —— 改完模板再点一次就是重新对齐。

    实测状态(status / plane_status / last_seen)按主机名保留下来, 不会因为改了
    一下硬件规格就把刚测出来的结果抹掉。

    返回 {created, updated, removed} 三个主机名列表。
    """
    planned, _conflicts = ts.expand(product, machine, set(), set())
    for spec in planned:
        spec["product"] = product["name"]
        spec["machine_type"] = machine["name"]
    planned_by_name = {spec["hostname"]: spec for spec in planned}

    created, updated, removed = [], [], []

    # 先清场: 模板生成的节点里, 不属于这套机台类型的一律删掉。
    # 手工加的(role_key 为空)留着 —— 那是人自己补的, 不该被模板同步顺手带走。
    for node in db.query(Node).all():
        if not node.role_key:
            continue
        stale = (node.product != product["name"]
                 or node.machine_type != machine["name"]
                 or node.hostname not in planned_by_name)
        if stale:
            removed.append(node.hostname)
            db.delete(node)
    db.flush()

    existing = {n.hostname: n for n in db.query(Node).all()}
    for hostname, spec in planned_by_name.items():
        node = existing.get(hostname)
        if node is None:
            db.add(Node(**spec))
            created.append(hostname)
            continue
        changed = False
        for field in _SPEC_FIELDS:
            if getattr(node, field, None) != spec.get(field):
                setattr(node, field, spec.get(field))
                changed = True
        node.product = product["name"]
        node.machine_type = machine["name"]
        if changed:
            updated.append(hostname)

    db.commit()
    return {"created": created, "updated": updated, "removed": removed}


def current_nodes(db, product: Dict, machine: Dict) -> List[Node]:
    return (db.query(Node)
            .filter(Node.product == product["name"])
            .filter(Node.machine_type == machine["name"])
            .order_by(Node.hostname.asc())
            .all())
