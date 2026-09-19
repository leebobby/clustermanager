"""
节点模板服务 — 两级结构: 项目 → 机台类型。存 JSON 文件, 不入库。

  项目 (project)     定义本项目共用的角色配置: 主机名前缀、三平面网段、
                     IP 起始序号、数据面协议、硬件规格
  机台类型 (machine) 只定义每种角色各几台 —— 同一项目下不同机台类型的区别
                     就在服务器台数, 其余配置沿用项目级定义

角色在项目内以 hostname_prefix 为标识, 机台类型的 counts 按这个标识索引。

存储: BASE_DIR/node_templates.json (文件不存在时用内置默认模板初始化)
"""

import json
import os
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from config import BASE_DIR

TEMPLATES_PATH = os.path.join(BASE_DIR, "node_templates.json")


# ── 内置默认模板 ──────────────────────────────────────────────────────────────
# 按 README 的 v2 六子网规划编写, 首次启动时写入文件, 之后用户可自行增删改。
_DEFAULT_TEMPLATES: Dict = {
    "_comment": (
        "节点模板 — 项目定义共用的角色配置, 机台类型只定义各角色的台数。"
        "可直接编辑本文件, 或在节点管理页维护。"
    ),
    "projects": [
        {
            "name": "鲲鹏三平面集群",
            "description": "鲲鹏 ARM64 + HNS, 三平面物理隔离, 对应 README 的 v2 六子网规划",
            "roles": [
                {
                    "node_type": "master",
                    "hostname_prefix": "master",
                    "role": "compute",
                    "data_protocol": "DPDK",
                    "bmc_prefix": "172.16.0.",
                    "ctrl_prefix": "172.16.3.",
                    "data_prefix": "200.1.1.",
                    "hostname_start": 1,
                    "ip_start": 11,
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 128,
                    "memory_gb": 512,
                    "disk_gb": 1920,
                },
                {
                    "node_type": "slave",
                    "hostname_prefix": "slave",
                    "role": "compute",
                    "data_protocol": "RDMA",
                    "bmc_prefix": "172.16.0.",
                    "ctrl_prefix": "172.16.3.",
                    "data_prefix": "100.1.1.",
                    "hostname_start": 1,
                    "ip_start": 51,
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 128,
                    "memory_gb": 256,
                    "disk_gb": 1920,
                },
                {
                    "node_type": "subswath",
                    "hostname_prefix": "subswath",
                    "role": "nfs-server",
                    "data_protocol": "RDMA",
                    "bmc_prefix": "172.16.0.",
                    "ctrl_prefix": "172.16.3.",
                    "data_prefix": "100.1.1.",
                    "hostname_start": 1,
                    "ip_start": 170,
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 64,
                    "memory_gb": 256,
                    "disk_gb": 30720,
                },
                {
                    "node_type": "gstorage",
                    "hostname_prefix": "gstorage",
                    "role": "nfs-server",
                    "data_protocol": "RDMA",
                    "bmc_prefix": "172.16.0.",
                    "ctrl_prefix": "172.16.3.",
                    "data_prefix": "100.1.2.",
                    "hostname_start": 1,
                    "ip_start": 172,
                    "os_version": "openEuler 22.03 LTS",
                    "cpu_cores": 64,
                    "memory_gb": 128,
                    "disk_gb": 102400,
                },
            ],
            "machine_types": [
                {
                    "name": "标准型 (22 节点)",
                    "description": "6 Master + 12 Slave + 2 SubSwath + 1 GStorage",
                    "counts": {"master": 6, "slave": 12, "subswath": 2, "gstorage": 1},
                },
                {
                    "name": "精简型 (10 节点)",
                    "description": "3 Master + 5 Slave + 1 SubSwath + 1 GStorage",
                    "counts": {"master": 3, "slave": 5, "subswath": 1, "gstorage": 1},
                },
            ],
        }
    ],
}

# 角色条目的字段默认值 — 读模板时补齐, 容忍用户手写的残缺条目
_ROLE_DEFAULTS: Dict = {
    "node_type": "slave",
    "hostname_prefix": "node",
    "role": "",
    "data_protocol": "",
    "bmc_prefix": "",
    "ctrl_prefix": "",
    "data_prefix": "",
    "hostname_start": 1,
    "ip_start": 1,
    "os_version": "",
    "cpu_cores": None,
    "memory_gb": None,
    "disk_gb": None,
}


# ── 规整 ──────────────────────────────────────────────────────────────────────

def _normalize_role(raw: Dict) -> Dict:
    """补齐角色条目缺失字段, 并把数值字段转成正确类型"""
    role = {**_ROLE_DEFAULTS, **(raw or {})}
    for key in ("hostname_start", "ip_start"):
        try:
            role[key] = max(0, int(role[key]))
        except (TypeError, ValueError):
            role[key] = _ROLE_DEFAULTS[key]
    for key in ("cpu_cores", "memory_gb", "disk_gb"):
        try:
            role[key] = int(role[key]) if role[key] not in (None, "") else None
        except (TypeError, ValueError):
            role[key] = None
    role["hostname_prefix"] = str(role["hostname_prefix"] or "node").strip() or "node"
    return role


def _normalize_machine(raw: Dict, role_keys: List[str]) -> Dict:
    """机台类型: 只保留项目现有角色的台数, 缺的补 0"""
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


def _normalize_project(raw: Dict) -> Optional[Dict]:
    name = str((raw or {}).get("name", "")).strip()
    if not name:
        return None

    roles: List[Dict] = []
    seen = set()
    for r in (raw.get("roles") or []):
        role = _normalize_role(r)
        # hostname_prefix 是角色在项目内的标识, 重名的后来者自动加后缀以免 counts 串台
        base = role["hostname_prefix"]
        if base in seen:
            n = 2
            while f"{base}-{n}" in seen:
                n += 1
            role["hostname_prefix"] = f"{base}-{n}"
        seen.add(role["hostname_prefix"])
        roles.append(role)

    role_keys = [r["hostname_prefix"] for r in roles]
    machines = [
        m for m in (_normalize_machine(x, role_keys) for x in (raw.get("machine_types") or []))
        if m["name"]
    ]
    return {"name": name, "description": str(raw.get("description", "")),
            "roles": roles, "machine_types": machines}


def _migrate_legacy(data: Dict) -> Dict:
    """
    旧格式 {"templates": [{model, description, roles:[{..., count}]}]} → 新的两级结构。

    每个旧模板变成一个项目, 其 roles 剥掉 count 作为项目级角色定义,
    count 转成一个同名机台类型。已是新格式时原样返回。
    """
    if "projects" in (data or {}):
        return data
    legacy = (data or {}).get("templates")
    if not legacy:
        return data

    projects = []
    for tpl in legacy:
        name = str(tpl.get("model", "")).strip()
        if not name:
            continue
        roles, counts = [], {}
        for r in (tpl.get("roles") or []):
            role = dict(r)
            count = role.pop("count", 0)
            role = _normalize_role(role)
            key = role["hostname_prefix"]
            roles.append(role)
            try:
                counts[key] = max(0, int(count or 0))
            except (TypeError, ValueError):
                counts[key] = 0
        projects.append({
            "name": name,
            "description": str(tpl.get("description", "")),
            "roles": roles,
            "machine_types": [{"name": name, "description": "由旧版模板迁移", "counts": counts}],
        })
    return {"_comment": data.get("_comment", _DEFAULT_TEMPLATES["_comment"]), "projects": projects}


def _normalize(data: Dict) -> Dict:
    data = _migrate_legacy(data or {})
    projects = [p for p in (_normalize_project(x) for x in (data.get("projects") or [])) if p]
    return {"_comment": data.get("_comment", _DEFAULT_TEMPLATES["_comment"]),
            "projects": projects}


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
    # 旧格式读到后就地升级, 免得每次都要重新迁移
    if "projects" not in raw:
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


def find_machine_type(project_name: str, machine_name: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    """按 (项目, 机台类型) 定位; 返回 (项目, 机台类型), 找不到的那一项为 None"""
    project = next(
        (p for p in read_templates()["projects"] if p["name"] == project_name), None
    )
    if not project:
        return None, None
    machine = next(
        (m for m in project["machine_types"] if m["name"] == machine_name), None
    )
    return project, machine


# ── 展开成节点 ────────────────────────────────────────────────────────────────

def _compose(prefix: str, index: int) -> str:
    """网段前缀 + 序号 → IP; 前缀为空则不生成该平面的 IP"""
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    return f"{prefix.rstrip('.')}.{index}"


def expand(
    project: Dict,
    machine: Dict,
    used_hostnames: set,
    used_ips: set,
) -> Tuple[List[Dict], List[str]]:
    """
    把 (项目角色定义 + 机台类型台数) 展开成待创建的节点列表。

    主机名序号与 IP 末段是两条独立的计数, 同步推进:
      主机名 = `{hostname_prefix}-{hostname_start + n:02d}`
      各平面 IP = `{平面前缀}.{ip_start + n}`
    对应 README 的 v2 规划 —— master-01 ↔ 172.16.3.11, gstorage-01 ↔ .172。

    某个 n 对应的主机名或任一 IP 已被占用时整体跳过, n 加一重试, 直到凑够台数。
    两条计数一起推进, 所以跳过后主机名与 IP 仍然对齐。

    used_hostnames / used_ips 由调用方从数据库收集, 并在本函数内随分配结果增长,
    因此同一次展开中的多个角色之间也不会互相撞号。

    返回 (节点列表, 冲突说明列表)。
    """
    planned: List[Dict] = []
    conflicts: List[str] = []
    counts = machine.get("counts") or {}

    for role in project.get("roles", []):
        prefix = role["hostname_prefix"]
        count = counts.get(prefix, 0)
        if count <= 0:
            continue

        offset = 0
        placed = 0
        skipped = 0
        # 上限防御: 台数填得过大或网段被占满时不至于死循环
        limit = count + 254

        while placed < count and offset <= limit:
            index = role["ip_start"] + offset
            hostname = f"{prefix}-{role['hostname_start'] + offset:02d}"
            bmc_ip = _compose(role["bmc_prefix"], index)
            ctrl_ip = _compose(role["ctrl_prefix"], index)
            data_ip = _compose(role["data_prefix"], index)

            candidate_ips = {ip for ip in (bmc_ip, ctrl_ip, data_ip) if ip}
            if hostname in used_hostnames or (candidate_ips & used_ips):
                offset += 1
                skipped += 1
                continue

            planned.append({
                "hostname": hostname,
                "node_type": role["node_type"],
                "role": role["role"] or None,
                # 管理面与 BMC 同网段, 沿用 wave-deploy 里 mgmt_ip = bmc_ip 的既有约定
                "mgmt_ip": bmc_ip or None,
                "bmc_ip": bmc_ip or None,
                "ctrl_ip": ctrl_ip or None,
                "data_ip": data_ip or None,
                "data_protocol": role["data_protocol"] or None,
                "os_version": role["os_version"] or None,
                "cpu_cores": role["cpu_cores"],
                "memory_gb": role["memory_gb"],
                "disk_gb": role["disk_gb"],
                "status": "offline",
            })
            used_hostnames.add(hostname)
            used_ips |= candidate_ips
            placed += 1
            offset += 1

        if skipped:
            conflicts.append(f"{prefix}: 跳过 {skipped} 个已占用的序号")
        if placed < count:
            conflicts.append(f"{prefix}: 只排到 {placed}/{count} 台, 可用序号不足")

    return planned, conflicts
