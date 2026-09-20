"""
导入 / 导出 nodes.json。

现场那份 nodes.json 是 PXE 流程产出的, 顶层按 PXE 引导网卡的 MAC 索引:

    {
      "_comment": "...",                       # 下划线开头的都是注释, 跳过
      "aa:bb:cc:11:00:01": {
        "hostname_new": "master-01",
        "role":         "master",
        "ctrl_ip":      "172.16.3.11/24",
        "dpdk_ips":     "200.1.1.11/24 200.1.2.31/24",
        "rdma_ips":     "100.1.1.11/24 100.1.2.31/24",
        "bmc_ip":       "172.16.0.11"
      }
    }

四个数据面 IP 就写在 dpdk_ips / rdma_ips 里, 空格分隔、带掩码 —— 正好对上
plane_ips 的 data_front / data_back 各两个口。

为什么要能导入: 模板是按等差数列排出来的, 而现场的真实 IP 未必对得上(上面这条
dpdk 第二个口就是 .31 不是 .11)。模板负责"该长什么样", nodes.json 是"实际是什么样",
两者对不上时以现场为准。

解析写得宽一些 —— 现场的文件多半是手改的:
  · 顶层是 MAC 索引的字典 / 主机名索引的字典 / {"nodes": [...]} / 直接一个数组
  · IP 带不带掩码都行, 空格或逗号分隔都行, 单个字符串或数组都行
  · 字段名认一批常见别名
认不出来的不静默丢掉, 一条条报上去 —— 导入前先给预览, 人确认了才写库。
"""

import ipaddress
import re
from typing import Any, Dict, List, Optional, Tuple

from models.node import Node
from services import node_ips
from services.jsonio import load_bytes  # noqa: F401  (nodes_import.load_bytes 老调用点还在用)
from services import template_service as ts

# 平面 ← 文件里的哪些字段。顺序即优先级, 前面的先认
_PLANE_FIELDS: Dict[str, Tuple[str, ...]] = {
    "management": ("bmc_ip", "ipmi_ip", "mgmt_ip", "management_ip", "mgmt_ips", "bmc_ips"),
    "control": ("ctrl_ip", "ctrl_ips", "control_ip", "control_ips"),
    "data_front": ("dpdk_ips", "dpdk_ip", "data_front_ips", "data_front_ip"),
    "data_back": ("rdma_ips", "rdma_ip", "data_back_ips", "data_back_ip"),
}

_HOSTNAME_FIELDS = ("hostname_new", "hostname", "name", "host")
_ROLE_FIELDS = ("role", "role_key", "node_type", "type")
_MAC_FIELDS = ("mgmt_mac", "mac", "pxe_mac", "boot_mac")

_MAC_RE = re.compile(r"^[0-9a-f]{2}([:-][0-9a-f]{2}){5}$", re.IGNORECASE)


# ── 解析 ──────────────────────────────────────────────────────────────────────

def _first(raw: Dict, fields: Tuple[str, ...]) -> str:
    for f in fields:
        v = raw.get(f)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _ip_list(value: Any) -> Tuple[List[str], List[str]]:
    """
    "200.1.1.11/24 200.1.2.31/24" → (["200.1.1.11", "200.1.2.31"], [])

    掩码去掉 —— 本工具只用地址探连通性, 不配网。返回 (认出来的, 没认出来的)。
    """
    if value in (None, ""):
        return [], []
    items = value if isinstance(value, (list, tuple)) else re.split(r"[\s,;]+", str(value))
    good, bad = [], []
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        addr = item.split("/")[0].strip()
        try:
            ipaddress.ip_address(addr)
        except ValueError:
            bad.append(item)
            continue
        if addr not in good:
            good.append(addr)
    return good, bad


def _rows_of(data: Any) -> Tuple[List[Tuple[str, Dict]], List[str]]:
    """把几种顶层写法统一成 [(来源键, 节点字典)]"""
    problems: List[str] = []

    if isinstance(data, list):
        return [("", r) for r in data if isinstance(r, dict)], problems

    if not isinstance(data, dict):
        return [], ["文件顶层既不是对象也不是数组, 认不出来"]

    for key in ("nodes", "items", "data"):
        if isinstance(data.get(key), list):
            return [("", r) for r in data[key] if isinstance(r, dict)], problems

    rows = []
    for key, value in data.items():
        if str(key).startswith("_"):        # _comment / _hardware / _role_master ...
            continue
        if not isinstance(value, dict):
            problems.append(f"跳过 `{key}`: 它的值不是一个节点对象")
            continue
        rows.append((str(key), value))
    return rows, problems


def parse(data: Any) -> Tuple[List[Dict], List[str]]:
    """文件内容 → [{hostname, role_raw, mac, plane_ips, notes}], 以及整体性的问题"""
    rows, problems = _rows_of(data)
    out: List[Dict] = []

    for source_key, raw in rows:
        hostname = _first(raw, _HOSTNAME_FIELDS)
        if not hostname and not _MAC_RE.match(source_key or ""):
            # 顶层键不是 MAC 时, 它本身多半就是主机名
            hostname = (source_key or "").strip()
        if not hostname:
            problems.append(f"跳过 `{source_key}`: 没有主机名(hostname_new / hostname)")
            continue

        mac = _first(raw, _MAC_FIELDS)
        if not mac and _MAC_RE.match(source_key or ""):
            mac = source_key

        notes: List[str] = []
        planes: Dict[str, List[str]] = {}

        # 我们自己导出的格式里直接就有 plane_ips, 原样收下
        for plane, ips in node_ips.clean_planes(raw.get("plane_ips")).items():
            planes[plane] = ips

        for plane, fields in _PLANE_FIELDS.items():
            if planes.get(plane):
                continue
            for field in fields:
                if field not in raw:
                    continue
                good, bad = _ip_list(raw[field])
                if bad:
                    notes.append(f"{field} 里有认不出的地址: {', '.join(bad)}")
                if good:
                    planes[plane] = good
                    break

        if not planes:
            problems.append(f"跳过 {hostname}: 一个能认出来的 IP 都没有")
            continue
        if not planes.get("management"):
            notes.append("没有管理面 / BMC IP, 这台机器的管理面不参与诊断")

        out.append({
            "source_key": source_key,
            "hostname": hostname,
            "role_raw": _first(raw, _ROLE_FIELDS),
            "mac": mac,
            "plane_ips": planes,
            "os_version": _first(raw, ("os_version", "os")),
            "notes": notes,
        })

    names: Dict[str, int] = {}
    for row in out:
        names[row["hostname"]] = names.get(row["hostname"], 0) + 1
    for name, n in names.items():
        if n > 1:
            problems.append(f"{name} 在文件里出现了 {n} 次, 只会用最后一条")

    return out, problems


# ── 对上模板里的角色 ──────────────────────────────────────────────────────────

def match_role(product: Dict, role_raw: str, hostname: str) -> Optional[Dict]:
    """
    文件里的 role 字段 → 模板里的角色。

    按 key / 显示名 / node_type / 主机名前缀依次认, 都认不上再拿主机名的前缀兜底
    (master-01 → master)。认不上不是致命的: 节点照样导进来, 只是它不归到任何角色下,
    组网图按 node_type 兜底显示 —— 但要在预览里说出来。
    """
    roles = product.get("roles") or []
    probe = (role_raw or "").strip().lower()
    if probe:
        for field in ("key", "label", "node_type", "hostname_prefix"):
            for role in roles:
                if str(role.get(field, "")).strip().lower() == probe:
                    return role

    guess = re.split(r"[-_0-9]", hostname.strip().lower(), 1)[0]
    if guess:
        for role in roles:
            if str(role.get("hostname_prefix", "")).strip().lower() == guess:
                return role
            if str(role.get("key", "")).strip().lower() == guess:
                return role
    return None


# ── 预览 ──────────────────────────────────────────────────────────────────────

def plan(rows: List[Dict], product: Dict, machine: Dict, existing: List[Node]) -> Dict:
    """
    算出这次导入会做什么, 一条都不写库。界面拿它渲染预览, 人点了确认才真导。
    """
    by_name = {n.hostname: n for n in existing}
    planned_names = {
        spec["hostname"] for spec in ts.expand(product, machine, set(), set())[0]
    }

    items = []
    for row in rows:
        role = match_role(product, row["role_raw"], row["hostname"])
        node = by_name.get(row["hostname"])
        notes = list(row["notes"])
        if not role:
            notes.append(
                f"模板里没有和 `{row['role_raw'] or row['hostname']}` 对得上的角色, "
                f"这台会作为独立节点导进来"
            )

        before = dict((node.plane_ips or {}) if node else {})
        after = row["plane_ips"]
        if node is None:
            action = "create"
        elif before == after and (node.role_key or "") == (role["key"] if role else ""):
            action = "unchanged"
        else:
            action = "update"

        items.append({
            "hostname": row["hostname"],
            "role_key": role["key"] if role else "",
            "role_label": role["label"] if role else (row["role_raw"] or "—"),
            "mac": row["mac"],
            "action": action,
            "plane_ips": after,
            "before": before,
            "changed_planes": sorted(
                p for p in set(before) | set(after) if before.get(p) != after.get(p)
            ),
            "notes": notes,
        })

    in_file = {row["hostname"] for row in rows}
    # 模板排出来、但文件里没有的 —— 现场少装了一台? 还是文件不全? 让人自己判断
    missing = sorted(n.hostname for n in existing
                     if n.hostname not in in_file and n.hostname in planned_names)

    return {
        "product": product["name"],
        "machine_type": machine["name"],
        "items": items,
        "missing": missing,
        "summary": {
            "create": sum(1 for x in items if x["action"] == "create"),
            "update": sum(1 for x in items if x["action"] == "update"),
            "unchanged": sum(1 for x in items if x["action"] == "unchanged"),
            "missing": len(missing),
        },
    }


# ── 写库 ──────────────────────────────────────────────────────────────────────

def apply(db, preview: Dict, product: Dict, machine: Dict,
          remove_missing: bool = False) -> Dict:
    """
    按预览结果写库。

    实测状态(status / plane_status / last_seen)一律保留 —— 导一次 IP 不该把刚测出来
    的结果抹掉。
    """
    existing = {n.hostname: n for n in db.query(Node).all()}
    created, updated = [], []

    for item in preview["items"]:
        node = existing.get(item["hostname"])
        if node is None:
            node = Node(hostname=item["hostname"], status="unknown")
            db.add(node)
            created.append(item["hostname"])
        elif item["action"] != "unchanged":
            updated.append(item["hostname"])

        node.product = product["name"]
        node.machine_type = machine["name"]
        node.role_key = item["role_key"] or None
        if item["role_key"]:
            role = ts.find_role(product, item["role_key"])
            if role:
                node.node_type = role["node_type"]
                node.role = role["role"] or node.role
        elif not node.node_type:
            node.node_type = item["role_label"] or "slave"
        if item.get("mac"):
            node.mgmt_mac = item["mac"]
        node.plane_ips = node_ips.clean_planes(item["plane_ips"])
        node_ips.flat_from_planes(node)

    removed = []
    if remove_missing:
        for hostname in preview["missing"]:
            node = existing.get(hostname)
            if node is not None:
                db.delete(node)
                removed.append(hostname)

    db.commit()
    return {"created": created, "updated": updated, "removed": removed}


# ── 导出 ──────────────────────────────────────────────────────────────────────

def export(nodes: List[Node], product: Dict, machine: Dict) -> Dict:
    """
    导出成同一种 nodes.json —— 导出改几行再导回来, 比手改数据库现实得多。

    写的是裸地址不带掩码: 本工具只拿它探连通性, 存的时候掩码就没留。要拿去喂 PXE
    的话, 掩码得自己补回去。
    """
    out: Dict[str, Any] = {
        "_comment": (
            f"{product['name']} / {machine['name']} —— 由集群运维工具导出; "
            f"IP 不带掩码, 回导本工具没问题, 喂 PXE 前要自己补 /24"
        ),
    }
    for node in sorted(nodes, key=lambda n: n.hostname or ""):
        planes = node.plane_ips or {}
        entry = {
            "hostname_new": node.hostname,
            "role": node.role_key or node.node_type or "",
        }
        if planes.get("management"):
            entry["bmc_ip"] = " ".join(planes["management"])
        if planes.get("control"):
            entry["ctrl_ip"] = " ".join(planes["control"])
        if planes.get("data_front"):
            entry["dpdk_ips"] = " ".join(planes["data_front"])
        if planes.get("data_back"):
            entry["rdma_ips"] = " ".join(planes["data_back"])
        if node.os_version:
            entry["os_version"] = node.os_version
        # MAC 是 nodes.json 的天然主键(PXE 靠它认机器); 没有就退回主机名
        out[node.mgmt_mac or node.hostname] = entry
    return out
