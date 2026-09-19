"""
机台模板服务 —— 三层结构: 产品 → 机台类型 → (实例化出)集群。

  产品 (product)      定义本产品共用的角色配置: 主机名前缀、每个角色接哪几个
                      平面、网段与起始序号、数据面协议、硬件规格、角色专项检查
  机台类型 (machine)  只定义每种角色各几台 —— 同一产品下不同机台类型的区别就
                      在服务器台数, 其余配置沿用产品级定义
  集群 (cluster)      现场一台真机台 = 一套集群, 存数据库(见 models.node.Cluster)

角色以 `key` 为标识(host / master / slave / subswath / gstorage ...), 机台类型的
counts 按 key 索引。key 一旦定下就不再变, 主机名前缀可以随便改而不会串台 ——
这是与上一版的关键区别: 上一版拿 hostname_prefix 当标识, 改前缀台数就丢了。

每个角色用 `planes` 声明接哪几个平面。有了它, 组网图不需要先有真节点就能画出来,
诊断项也能直接从"该接哪些平面"推导出来。

存储: BASE_DIR/node_templates.json (文件不存在时用内置默认模板初始化)
"""

import json
import os
import re
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from config import BASE_DIR

TEMPLATES_PATH = os.path.join(BASE_DIR, "node_templates.json")


# ── 平面 ──────────────────────────────────────────────────────────────────────
# 取值与 NetworkLink.plane / 组网图 API 保持一致

PLANES: Dict[str, Dict] = {
    "management": {"label": "管理面 GE", "bandwidth": "GE", "switch": "sw-mgmt"},
    "control": {"label": "控制面 10GE", "bandwidth": "10GE", "switch": "sw-ctrl"},
    "data_front": {"label": "数据面前段 DPDK", "bandwidth": "100GE", "switch": "sw-data-100g"},
    "data_back": {"label": "数据面后段 RDMA", "bandwidth": "100GE", "switch": "sw-data-100g"},
}

PLANE_ORDER = ["management", "control", "data_front", "data_back"]


# ── 角色专项检查 ──────────────────────────────────────────────────────────────
# 计划生成器认得这些 id; 认不出来的照样列进计划并标"未实现", 不会静默丢掉

CHECKS: Dict[str, Dict] = {
    "ping": {"label": "节点可达", "kind": "builtin"},
    "bmc": {"label": "BMC 可达", "kind": "builtin"},
    "ssh": {"label": "SSH 可达", "kind": "builtin"},
    "dpdk_port": {"label": "DPDK 端口已绑定", "kind": "script"},
    "rdma_link": {"label": "RDMA 链路 Active", "kind": "script"},
    "nfs_mount": {"label": "NFS 已挂载", "kind": "script"},
    "nfs_export": {"label": "NFS 已导出", "kind": "script"},
    "pxe_service": {"label": "PXE 服务在跑", "kind": "script"},
    "disk_usage": {"label": "磁盘使用率", "kind": "script"},
    "firmware": {"label": "固件版本一致", "kind": "script"},
}


# ── 内置默认模板 ──────────────────────────────────────────────────────────────
# 按 README 的 v2 六子网规划编写, 首次启动时写入文件, 之后用户可自行增删改。

_DEFAULT_TEMPLATES: Dict = {
    "_comment": (
        "机台模板 —— 产品定义共用的角色配置, 机台类型只定义各角色的台数。"
        "可直接编辑本文件, 或在集群管理页维护。"
    ),
    "products": [
        {
            "name": "鲲鹏三平面集群",
            "description": "鲲鹏 ARM64 + HNS, 三平面物理隔离, 对应 README 的 v2 六子网规划",
            "roles": [
                {
                    "key": "host",
                    "label": "Host",
                    "node_type": "host",
                    "hostname_prefix": "host",
                    "role": "deploy",
                    "hostname_start": 1,
                    "ip_start": 10,
                    "planes": [
                        {"plane": "management", "prefix": "172.16.0."},
                        {"plane": "control", "prefix": "172.16.3."},
                    ],
                    "checks": ["ping", "bmc", "ssh", "pxe_service"],
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 64,
                    "memory_gb": 256,
                    "disk_gb": 3840,
                    "note": "部署 / 管理主机, 跑 PXE、NTP、软件仓库, 不接数据面",
                },
                {
                    "key": "master",
                    "label": "Master",
                    "node_type": "master",
                    "hostname_prefix": "master",
                    "role": "compute",
                    "hostname_start": 1,
                    "ip_start": 11,
                    "planes": [
                        {"plane": "management", "prefix": "172.16.0."},
                        {"plane": "control", "prefix": "172.16.3."},
                        {"plane": "data_front", "prefix": "200.1.1.", "protocol": "DPDK"},
                    ],
                    "checks": ["ping", "bmc", "ssh", "dpdk_port"],
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 128,
                    "memory_gb": 512,
                    "disk_gb": 1920,
                },
                {
                    "key": "slave",
                    "label": "Slave",
                    "node_type": "slave",
                    "hostname_prefix": "slave",
                    "role": "compute",
                    "hostname_start": 1,
                    "ip_start": 51,
                    "planes": [
                        {"plane": "management", "prefix": "172.16.0."},
                        {"plane": "control", "prefix": "172.16.3."},
                        {"plane": "data_back", "prefix": "100.1.1.", "protocol": "RDMA"},
                    ],
                    "checks": ["ping", "bmc", "ssh", "rdma_link", "nfs_mount"],
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 128,
                    "memory_gb": 256,
                    "disk_gb": 1920,
                },
                {
                    "key": "subswath",
                    "label": "SubSwath",
                    "node_type": "subswath",
                    "hostname_prefix": "subswath",
                    "role": "nfs-server",
                    "hostname_start": 1,
                    "ip_start": 170,
                    "planes": [
                        {"plane": "management", "prefix": "172.16.0."},
                        {"plane": "control", "prefix": "172.16.3."},
                        {"plane": "data_back", "prefix": "100.1.1.", "protocol": "RDMA"},
                    ],
                    "checks": ["ping", "bmc", "ssh", "rdma_link", "nfs_export", "disk_usage"],
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 64,
                    "memory_gb": 256,
                    "disk_gb": 30720,
                },
                {
                    "key": "gstorage",
                    "label": "GlobalStorage",
                    "node_type": "gstorage",
                    "hostname_prefix": "gstorage",
                    "role": "nfs-server",
                    "hostname_start": 1,
                    "ip_start": 172,
                    "planes": [
                        {"plane": "management", "prefix": "172.16.0."},
                        {"plane": "control", "prefix": "172.16.3."},
                        {"plane": "data_back", "prefix": "100.1.2.", "protocol": "RDMA"},
                    ],
                    "checks": ["ping", "bmc", "ssh", "rdma_link", "nfs_export", "disk_usage"],
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 64,
                    "memory_gb": 128,
                    "disk_gb": 102400,
                    "note": "全局存储, Slave 挂它的 /data",
                },
            ],
            "machine_types": [
                {
                    "name": "标准型 (22 节点)",
                    "description": "1 Host + 6 Master + 12 Slave + 2 SubSwath + 1 GlobalStorage",
                    "counts": {"host": 1, "master": 6, "slave": 12, "subswath": 2, "gstorage": 1},
                },
                {
                    "name": "精简型 (11 节点)",
                    "description": "1 Host + 3 Master + 5 Slave + 1 SubSwath + 1 GlobalStorage",
                    "counts": {"host": 1, "master": 3, "slave": 5, "subswath": 1, "gstorage": 1},
                },
            ],
        }
    ],
}


_ROLE_DEFAULTS: Dict = {
    "key": "",
    "label": "",
    "node_type": "slave",
    "hostname_prefix": "node",
    "role": "",
    "hostname_start": 1,
    "ip_start": 1,
    "planes": [],
    "checks": [],
    "os_version": "",
    "cpu_cores": None,
    "memory_gb": None,
    "disk_gb": None,
    "note": "",
}


# ── 规整 ──────────────────────────────────────────────────────────────────────

def slugify(text: str, fallback: str = "role") -> str:
    """把任意文本压成一个可做 key 的短标识"""
    s = re.sub(r"[^0-9a-zA-Z_-]+", "-", str(text or "").strip().lower()).strip("-_")
    return s or fallback


def _normalize_plane(raw: Dict) -> Optional[Dict]:
    """一条平面声明; plane 不在已知取值里就丢掉 —— 写错了总比静默画错图强"""
    plane = str((raw or {}).get("plane", "")).strip()
    if plane not in PLANES:
        return None
    meta = PLANES[plane]
    return {
        "plane": plane,
        "prefix": str((raw or {}).get("prefix", "")).strip(),
        "protocol": str((raw or {}).get("protocol", "")).strip(),
        "bandwidth": str((raw or {}).get("bandwidth", "")).strip() or meta["bandwidth"],
        "switch": str((raw or {}).get("switch", "")).strip() or meta["switch"],
    }


def _normalize_role(raw: Dict) -> Dict:
    role = {**_ROLE_DEFAULTS, **(raw or {})}

    for field in ("hostname_start", "ip_start"):
        try:
            role[field] = max(0, int(role[field]))
        except (TypeError, ValueError):
            role[field] = _ROLE_DEFAULTS[field]
    for field in ("cpu_cores", "memory_gb", "disk_gb"):
        try:
            role[field] = int(role[field]) if role[field] not in (None, "") else None
        except (TypeError, ValueError):
            role[field] = None

    role["hostname_prefix"] = str(role["hostname_prefix"] or "node").strip() or "node"
    # key 缺失时从 node_type / 前缀推一个, 保证老文件也能用
    role["key"] = slugify(role["key"] or role["node_type"] or role["hostname_prefix"])
    role["label"] = str(role["label"] or "").strip() or role["key"].title()
    role["node_type"] = str(role["node_type"] or role["key"]).strip()
    role["note"] = str(role.get("note") or "")

    planes = [p for p in (_normalize_plane(x) for x in (role.get("planes") or [])) if p]
    # 同一平面只留第一条, 并按固定顺序排 —— 免得组网图的连线顺序随文件写法变
    seen, ordered = set(), []
    for plane_name in PLANE_ORDER:
        for p in planes:
            if p["plane"] == plane_name and plane_name not in seen:
                seen.add(plane_name)
                ordered.append(p)
    role["planes"] = ordered

    checks = []
    for c in (role.get("checks") or []):
        c = str(c).strip()
        if c and c not in checks:
            checks.append(c)
    role["checks"] = checks

    return {k: role[k] for k in _ROLE_DEFAULTS}


def _normalize_machine(raw: Dict, role_keys: List[str]) -> Dict:
    counts_raw = (raw or {}).get("counts") or {}
    counts = {}
    for key in role_keys:
        try:
            counts[key] = max(0, int(counts_raw.get(key, 0) or 0))
        except (TypeError, ValueError):
            counts[key] = 0
    return {
        "name": str((raw or {}).get("name", "")).strip(),
        "description": str((raw or {}).get("description", "")),
        "counts": counts,
    }


def _normalize_product(raw: Dict) -> Optional[Dict]:
    name = str((raw or {}).get("name", "")).strip()
    if not name:
        return None

    roles: List[Dict] = []
    seen = set()
    for r in (raw.get("roles") or []):
        role = _normalize_role(r)
        base = role["key"]
        if base in seen:            # key 撞了就加后缀, 否则 counts 会串台
            n = 2
            while f"{base}-{n}" in seen:
                n += 1
            role["key"] = f"{base}-{n}"
        seen.add(role["key"])
        roles.append(role)

    role_keys = [r["key"] for r in roles]
    machines = [
        m for m in (_normalize_machine(x, role_keys) for x in (raw.get("machine_types") or []))
        if m["name"]
    ]
    return {
        "name": name,
        "description": str(raw.get("description", "")),
        "roles": roles,
        "machine_types": machines,
    }


# ── 迁移 ──────────────────────────────────────────────────────────────────────

def _planes_from_flat(raw: Dict) -> List[Dict]:
    """
    上一版把三个平面写成三个扁平字段(bmc_prefix / ctrl_prefix / data_prefix)。
    数据面走前段还是后段由 data_protocol 判断: DPDK 前段, 其余按 RDMA 后段。
    """
    protocol = str(raw.get("data_protocol") or "").strip()
    data_plane = "data_front" if protocol.upper() == "DPDK" else "data_back"
    out = []
    for prefix_key, plane in (("bmc_prefix", "management"),
                              ("ctrl_prefix", "control"),
                              ("data_prefix", data_plane)):
        prefix = str(raw.get(prefix_key) or "").strip()
        if prefix:
            out.append({"plane": plane, "prefix": prefix,
                        "protocol": protocol if plane.startswith("data") else ""})
    return out


def _checks_for(node_type: str, planes: List[Dict]) -> List[str]:
    """迁移时给一套合理的默认检查集, 用户之后可以再改"""
    checks = ["ping", "bmc", "ssh"]
    protocols = {(p.get("protocol") or "").upper() for p in planes}
    if "DPDK" in protocols:
        checks.append("dpdk_port")
    if "RDMA" in protocols:
        checks.append("rdma_link")
    if node_type in ("subswath", "gstorage"):
        checks += ["nfs_export", "disk_usage"]
    elif node_type == "slave":
        checks.append("nfs_mount")
    elif node_type in ("host", "pxe_host"):
        checks.append("pxe_service")
    return checks


def _migrate_role(raw: Dict) -> Dict:
    """扁平网段字段 → planes; 顺带补 key / checks"""
    role = dict(raw or {})
    if not role.get("planes"):
        role["planes"] = _planes_from_flat(role)
    node_type = str(role.get("node_type") or "").strip()
    if not role.get("checks"):
        role["checks"] = _checks_for(node_type, role["planes"])
    if not role.get("key"):
        role["key"] = slugify(node_type or role.get("hostname_prefix"))
    for dead in ("bmc_prefix", "ctrl_prefix", "data_prefix", "data_protocol"):
        role.pop(dead, None)
    return role


def _migrate(data: Dict) -> Dict:
    """
    把三种历史格式统一成 products:

      v1  {"templates": [{model, description, roles: [{..., count}]}]}
      v2  {"projects":  [{name, roles: [扁平网段字段], machine_types}]}
      v3  {"products":  [...]}            已是新格式, 只补角色里缺的字段

    counts 在 v2 里按 hostname_prefix 索引, 迁到 key 之后要跟着改键, 否则台数全丢。
    """
    data = data or {}

    if "products" in data:
        products = deepcopy(data["products"])
        for product in products:
            product["roles"] = [_migrate_role(r) for r in (product.get("roles") or [])]
        return {"_comment": data.get("_comment", _DEFAULT_TEMPLATES["_comment"]),
                "products": products}

    if "projects" in data:
        products = []
        for project in (data.get("projects") or []):
            roles, remap = [], {}
            for raw in (project.get("roles") or []):
                old_key = str(raw.get("hostname_prefix") or "").strip()
                role = _migrate_role(raw)
                roles.append(role)
                if old_key:
                    remap[old_key] = role["key"]
            machines = []
            for m in (project.get("machine_types") or []):
                counts = {remap.get(k, k): v for k, v in (m.get("counts") or {}).items()}
                machines.append({**m, "counts": counts})
            products.append({**project, "roles": roles, "machine_types": machines})
        return {"_comment": data.get("_comment", _DEFAULT_TEMPLATES["_comment"]),
                "products": products}

    legacy = data.get("templates")
    if not legacy:
        return {"_comment": data.get("_comment", _DEFAULT_TEMPLATES["_comment"]), "products": []}

    products = []
    for tpl in legacy:
        name = str(tpl.get("model", "")).strip()
        if not name:
            continue
        roles, counts = [], {}
        for raw in (tpl.get("roles") or []):
            raw = dict(raw)
            count = raw.pop("count", 0)
            role = _migrate_role(raw)
            roles.append(role)
            try:
                counts[role["key"]] = max(0, int(count or 0))
            except (TypeError, ValueError):
                counts[role["key"]] = 0
        products.append({
            "name": name,
            "description": str(tpl.get("description", "")),
            "roles": roles,
            "machine_types": [{"name": name, "description": "由旧版模板迁移", "counts": counts}],
        })
    return {"_comment": data.get("_comment", _DEFAULT_TEMPLATES["_comment"]), "products": products}


def _normalize(data: Dict) -> Dict:
    data = _migrate(data or {})
    products = [p for p in (_normalize_product(x) for x in (data.get("products") or [])) if p]
    return {"_comment": data.get("_comment", _DEFAULT_TEMPLATES["_comment"]),
            "products": products}


# ── 读写 ──────────────────────────────────────────────────────────────────────

def read_templates() -> Dict:
    """读模板文件; 不存在时写入内置默认模板, 读坏时用默认模板兜底(不覆盖原文件)"""
    if not os.path.exists(TEMPLATES_PATH):
        return write_templates(deepcopy(_DEFAULT_TEMPLATES))
    try:
        with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _normalize(deepcopy(_DEFAULT_TEMPLATES))

    normalized = _normalize(raw)
    # 老格式读到后就地升级, 免得每次启动都要重新迁移一遍
    if "products" not in raw:
        try:
            write_templates(normalized)
        except OSError:
            pass
    return normalized


def write_templates(data: Dict) -> Dict:
    """整份覆盖写入; 返回规整后的内容"""
    normalized = _normalize(data)
    os.makedirs(os.path.dirname(TEMPLATES_PATH) or ".", exist_ok=True)
    with open(TEMPLATES_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    return normalized


def find_machine_type(product_name: str, machine_name: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    """按 (产品, 机台类型) 定位; 返回 (产品, 机台类型), 找不到的那一项为 None"""
    product = next(
        (p for p in read_templates()["products"] if p["name"] == product_name), None
    )
    if not product:
        return None, None
    machine = next(
        (m for m in product["machine_types"] if m["name"] == machine_name), None
    )
    return product, machine


def find_role(product: Dict, key: str) -> Optional[Dict]:
    return next((r for r in (product or {}).get("roles", []) if r["key"] == key), None)


# ── 展开成节点 ────────────────────────────────────────────────────────────────

def _compose(prefix: str, index: int) -> str:
    """网段前缀 + 序号 → IP; 前缀为空则不生成该平面的 IP"""
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    return f"{prefix.rstrip('.')}.{index}"


def plan_node(role: Dict, offset: int) -> Dict:
    """
    角色 + 序号偏移 → 一台节点的规格。

    主机名序号与 IP 末段是两条独立的计数, 同步推进:
      主机名 = `{hostname_prefix}-{hostname_start + n:02d}`
      各平面 IP = `{平面前缀}.{ip_start + n}`
    对应 README 的 v2 规划 —— master-01 ↔ 172.16.3.11, gstorage-01 ↔ .172。

    平面 IP 同时填进 Node 上原有的扁平字段, 这样组网图、诊断、PXE 那些按
    mgmt_ip / ctrl_ip / data_ip 取值的既有代码不用改。
    """
    index = role["ip_start"] + offset
    spec = {
        "hostname": f"{role['hostname_prefix']}-{role['hostname_start'] + offset:02d}",
        "node_type": role["node_type"],
        "role_key": role["key"],
        "role": role["role"] or None,
        "os_version": role["os_version"] or None,
        "cpu_cores": role["cpu_cores"],
        "memory_gb": role["memory_gb"],
        "disk_gb": role["disk_gb"],
        "status": "offline",
        "mgmt_ip": None, "bmc_ip": None, "ctrl_ip": None,
        "data_ip": None, "data_protocol": None,
    }
    for p in role["planes"]:
        ip = _compose(p["prefix"], index)
        if not ip:
            continue
        if p["plane"] == "management":
            # 管理面与 BMC 同网段, 沿用 wave-deploy 里 mgmt_ip = bmc_ip 的既有约定
            spec["mgmt_ip"] = spec["bmc_ip"] = ip
        elif p["plane"] == "control":
            spec["ctrl_ip"] = ip
        else:
            spec["data_ip"] = ip
            spec["data_protocol"] = p["protocol"] or None
    return spec


def expand(
    product: Dict,
    machine: Dict,
    used_hostnames: set,
    used_ips: set,
) -> Tuple[List[Dict], List[str]]:
    """
    把 (产品角色定义 + 机台类型台数) 展开成待创建的节点列表。

    某个序号对应的主机名或任一 IP 已被占用时整体跳过, 序号加一重试, 直到凑够台数。
    主机名与 IP 两条计数一起推进, 所以跳过之后二者仍然对齐。

    used_hostnames / used_ips 由调用方从数据库收集, 并在本函数内随分配结果增长,
    因此同一次展开中的多个角色之间也不会互相撞号。

    返回 (节点列表, 冲突说明列表)。
    """
    planned: List[Dict] = []
    conflicts: List[str] = []
    counts = machine.get("counts") or {}

    for role in product.get("roles", []):
        count = counts.get(role["key"], 0)
        if count <= 0:
            continue

        offset = placed = skipped = 0
        limit = count + 254      # 台数填得过大或网段被占满时不至于死循环

        while placed < count and offset <= limit:
            spec = plan_node(role, offset)
            candidate_ips = {ip for ip in (spec["mgmt_ip"], spec["bmc_ip"],
                                           spec["ctrl_ip"], spec["data_ip"]) if ip}
            if spec["hostname"] in used_hostnames or (candidate_ips & used_ips):
                offset += 1
                skipped += 1
                continue

            planned.append(spec)
            used_hostnames.add(spec["hostname"])
            used_ips |= candidate_ips
            placed += 1
            offset += 1

        if skipped:
            conflicts.append(f"{role['label']}: 跳过 {skipped} 个已占用的序号")
        if placed < count:
            conflicts.append(f"{role['label']}: 只排到 {placed}/{count} 台, 可用序号不足")

    return planned, conflicts
