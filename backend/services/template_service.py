"""
机台型号模板服务 — 存 JSON 文件, 不入库。

一个「机台型号」定义一整套集群的节点组成: 每种角色几台、主机名前缀、
三平面网段与起始序号、数据面协议、硬件规格。选定型号后可一次性展开整组节点。

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
    "_comment": "机台型号模板 — 每个型号定义一整套集群的节点组成。可直接编辑本文件, 或在节点管理页维护。",
    "templates": [
        {
            "model": "标准 22 节点集群",
            "description": "鲲鹏 ARM64 + HNS, 三平面物理隔离, 对应 README 的 v2 六子网规划",
            "roles": [
                {
                    "node_type": "master",
                    "count": 6,
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
                    "count": 12,
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
                    "count": 2,
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
                    "count": 1,
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
        }
    ],
}

# 角色条目的字段默认值 — 读模板时补齐, 容忍用户手写的残缺条目
_ROLE_DEFAULTS: Dict = {
    "node_type": "slave",
    "count": 1,
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


# ── 读写 ──────────────────────────────────────────────────────────────────────

def _normalize_role(raw: Dict) -> Dict:
    """补齐角色条目缺失字段, 并把数值字段转成正确类型"""
    role = {**_ROLE_DEFAULTS, **(raw or {})}
    for key in ("count", "hostname_start", "ip_start"):
        try:
            role[key] = max(0, int(role[key]))
        except (TypeError, ValueError):
            role[key] = _ROLE_DEFAULTS[key]
    for key in ("cpu_cores", "memory_gb", "disk_gb"):
        try:
            role[key] = int(role[key]) if role[key] not in (None, "") else None
        except (TypeError, ValueError):
            role[key] = None
    return role


def _normalize(data: Dict) -> Dict:
    """把任意形状的模板文件规整成 {"templates": [{model, description, roles: [...]}, ...]}"""
    templates = []
    for tpl in (data or {}).get("templates", []) or []:
        model = str(tpl.get("model", "")).strip()
        if not model:
            continue
        templates.append({
            "model": model,
            "description": str(tpl.get("description", "")),
            "roles": [_normalize_role(r) for r in (tpl.get("roles") or [])],
        })
    return {"_comment": (data or {}).get("_comment", _DEFAULT_TEMPLATES["_comment"]),
            "templates": templates}


def read_templates() -> Dict:
    """读模板文件; 不存在或读坏时回落到内置默认模板并落盘"""
    if not os.path.exists(TEMPLATES_PATH):
        write_templates(deepcopy(_DEFAULT_TEMPLATES))
        return _normalize(deepcopy(_DEFAULT_TEMPLATES))
    try:
        with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
            return _normalize(json.load(f))
    except (OSError, json.JSONDecodeError):
        # 文件被手工改坏时不让整个页面挂掉, 用默认模板兜底(不覆盖原文件, 保留现场)
        return _normalize(deepcopy(_DEFAULT_TEMPLATES))


def write_templates(data: Dict) -> Dict:
    """整份覆盖写入; 返回规整后的内容"""
    normalized = _normalize(data)
    os.makedirs(os.path.dirname(TEMPLATES_PATH) or ".", exist_ok=True)
    with open(TEMPLATES_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    return normalized


def find_template(model: str) -> Optional[Dict]:
    for tpl in read_templates()["templates"]:
        if tpl["model"] == model:
            return tpl
    return None


# ── 展开成节点 ────────────────────────────────────────────────────────────────

def _compose(prefix: str, index: int) -> str:
    """网段前缀 + 序号 → IP; 前缀为空则不生成该平面的 IP"""
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    return f"{prefix.rstrip('.')}.{index}"


def expand_template(
    tpl: Dict,
    used_hostnames: set,
    used_ips: set,
) -> Tuple[List[Dict], List[str]]:
    """
    把模板展开成待创建的节点列表。

    主机名序号与 IP 末段是两条独立的计数, 同步推进:
      主机名 = `{hostname_prefix}-{hostname_start + n:02d}`
      各平面 IP = `{平面前缀}.{ip_start + n}`
    对应 README 的 v2 规划 —— master-01 ↔ 172.16.3.11, gstorage-01 ↔ .172。

    某个 n 对应的主机名或任一 IP 已被占用时整体跳过, n 加一重试, 直到凑够 count 台。
    两条计数一起推进, 所以跳过后主机名与 IP 仍然对齐。

    used_hostnames / used_ips 由调用方从数据库收集, 并在本函数内随分配结果增长,
    因此同一次展开中的多个角色之间也不会互相撞号。

    返回 (节点列表, 冲突说明列表)。
    """
    planned: List[Dict] = []
    conflicts: List[str] = []

    for role in tpl.get("roles", []):
        count = role["count"]
        if count <= 0:
            continue

        prefix = role["hostname_prefix"] or "node"
        offset = 0
        placed = 0
        skipped = 0
        # 上限防御: 用户把 count 填得过大或网段被占满时不至于死循环
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
            conflicts.append(f"{role['node_type']}: 跳过 {skipped} 个已占用的序号")
        if placed < count:
            conflicts.append(
                f"{role['node_type']}: 只排到 {placed}/{count} 台, 可用序号不足"
            )

    return planned, conflicts
