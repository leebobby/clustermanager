"""
一键诊断 —— 检查计划由组网图推导, 内建项当场实测。

「基于组网的基本信息进行诊断」落到这里:
  组网图说 slave 接管理面 / 控制面 / 数据面后段(RDMA)  →  就为每台 slave 的
  这三个平面各排一项可达性检查; 角色的 checks 里写了 rdma_link / nfs_mount  →
  再排上这两项角色专项。

检查项分两类:
  内建 (builtin)  ping / BMC / SSH —— 本机直接探, 不需要登录被测机, 当场出结果
  脚本 (script)   RDMA 链路、NFS 挂载、磁盘水位这些必须登到机器上看的, 由诊断
                  脚本实现。脚本用 check_key 认领某一项检查

没有脚本认领的项不会假装通过, 也不会被悄悄跳过 —— 它照样列在计划里, 状态是
"未配置", 让人看得见这块没查。这是刻意的: 一份把没查的项算成"通过"的体检报告
比没有报告更糟。
"""

from typing import Dict, List, Optional

from services import probe
from services import template_service as ts

# 状态
PASS = "pass"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"          # 没有脚本认领 / 缺地址, 没查
PENDING = "pending"    # 有脚本认领, 等着跑

SEVERITY_ORDER = {FAIL: 0, WARN: 1, PENDING: 2, SKIP: 3, PASS: 4}

# 各平面的延迟基线(毫秒), 超过算警告不算故障
LATENCY_BUDGET_MS = {
    "management": 10.0,
    "control": 2.0,
    "data_front": 1.0,
    "data_back": 1.0,
}

BMC_PORTS = [443, 80]
SSH_PORT = 22

# 每个平面用哪个字段上的地址
_PLANE_IP_FIELD = {
    "management": "mgmt_ip",
    "control": "ctrl_ip",
    "data_front": "data_ip",
    "data_back": "data_ip",
}


def _suggest(check: str, plane: Optional[str], node: Dict, detail: str) -> str:
    """失败时给一句能照做的话, 而不是把内部错误原样抛给现场"""
    name = node.get("hostname") or "该节点"
    if check == "ping":
        if plane == "management":
            return (f"先确认 {name} 的 BMC / 管理口通电且网线在位; 管理面不通的话, "
                    f"下面那些要登机器的检查也都做不了。")
        if plane == "control":
            return (f"查 {name} 的 10GE 控制口链路灯, 再到控制交换机上确认端口没被 shutdown。")
        return (f"查 {name} 的 100GE 光模块与跳线是否松动; 链路灯正常的话, "
                f"再到数据交换机上确认该口没被 shutdown。")
    if check == "bmc":
        return f"{name} 的 BMC 管理页打不开 —— 确认 BMC 已上电、IP 没被改过。"
    if check == "ssh":
        return (f"{name} 的 22 端口连不上 —— 确认系统已起来(不是卡在 BIOS/PXE)、"
                f"sshd 在跑、防火墙放行。")
    return detail or "查这台机器上对应的服务状态。"


def _label(check: str) -> str:
    return (ts.CHECKS.get(check) or {}).get("label") or check


def _kind(check: str) -> str:
    return (ts.CHECKS.get(check) or {}).get("kind") or "script"


def build_plan(topology: Dict, scripts_by_check: Optional[Dict[str, Dict]] = None) -> List[Dict]:
    """
    组网图 → 检查项清单(还没跑)。

    scripts_by_check 是 {check_key: {id, name}}, 由调用方从 diag_scripts 表查出来;
    对得上的脚本项状态记 pending 并带上脚本 id, 对不上的记 skip。
    """
    scripts_by_check = scripts_by_check or {}
    items: List[Dict] = []

    for group in topology.get("groups", []):
        role_key = group["key"]
        role_label = group["label"]
        planes = group.get("planes", [])
        checks = group.get("checks", [])

        for node in group.get("nodes", []):
            host = node.get("hostname") or "?"

            # ── 平面可达性: 角色声明接几个平面就查几项 ──
            if "ping" in checks or not checks:
                for plane in planes:
                    ip = node.get(_PLANE_IP_FIELD.get(plane, ""))
                    items.append({
                        "id": f"{host}|{plane}|ping",
                        "category": "平面连通",
                        "title": f"{ts.PLANES[plane]['label']} 可达",
                        "role_key": role_key,
                        "role_label": role_label,
                        "node_id": node.get("id"),
                        "target": host,
                        "plane": plane,
                        "check": "ping",
                        "kind": "builtin",
                        "host": ip,
                        "status": SKIP if not ip else PENDING,
                        "detail": "" if ip else "模板里这个平面没配网段, 没有地址可探",
                        "suggestion": "",
                        "latency_ms": None,
                        "script_id": None,
                    })

            # ── 带外与登录 ──
            for check, ip, ports in (("bmc", node.get("mgmt_ip"), BMC_PORTS),
                                     ("ssh", node.get("ctrl_ip") or node.get("mgmt_ip"), [SSH_PORT])):
                if check not in checks:
                    continue
                items.append({
                    "id": f"{host}||{check}",
                    "category": "节点可达",
                    "title": _label(check),
                    "role_key": role_key,
                    "role_label": role_label,
                    "node_id": node.get("id"),
                    "target": host,
                    "plane": None,
                    "check": check,
                    "kind": "builtin",
                    "host": ip,
                    "ports": ports,
                    "status": SKIP if not ip else PENDING,
                    "detail": "" if ip else "没有可用地址",
                    "suggestion": "",
                    "latency_ms": None,
                    "script_id": None,
                })

            # ── 角色专项: 要登机器才能看的 ──
            for check in checks:
                if _kind(check) != "script":
                    continue
                script = scripts_by_check.get(check)
                items.append({
                    "id": f"{host}||{check}",
                    "category": "角色专项",
                    "title": _label(check),
                    "role_key": role_key,
                    "role_label": role_label,
                    "node_id": node.get("id"),
                    "target": host,
                    "plane": None,
                    "check": check,
                    "kind": "script",
                    "host": node.get("ctrl_ip") or node.get("mgmt_ip"),
                    "status": PENDING if script else SKIP,
                    "detail": "" if script else f"没有脚本认领 {check}, 这项没查",
                    "suggestion": "" if script else
                                  f"到「告警与日志 / 诊断脚本」里新建一个脚本, 把它的检查项设成 {check}。",
                    "latency_ms": None,
                    "script_id": (script or {}).get("id"),
                    "script_name": (script or {}).get("name"),
                })

    return items


def run_builtin(items: List[Dict], timeout_ms: int = 1000) -> List[Dict]:
    """
    把计划里的内建项真跑一遍(并发), 就地写回状态。脚本项原样不动。

    延迟超基线记警告不记故障 —— 通了但慢和不通是两回事, 现场处理的紧急程度差很远。
    """
    jobs = []
    for item in items:
        if item["kind"] != "builtin" or item["status"] != PENDING or not item.get("host"):
            continue
        host = item["host"]
        if item["check"] == "ping":
            jobs.append((item["id"], lambda h=host: probe.ping(h, timeout_ms)))
        else:
            ports = item.get("ports") or [SSH_PORT]
            jobs.append((item["id"], lambda h=host, p=ports: probe.tcp_any(h, p, timeout_ms / 1000.0 + 1.0)))

    results = probe.run_all(jobs)

    for item in items:
        res = results.get(item["id"])
        if res is None:
            continue
        item["latency_ms"] = res.get("latency_ms")
        if not res["ok"]:
            item["status"] = FAIL
            item["detail"] = res.get("detail") or "不通"
            item["suggestion"] = _suggest(item["check"], item.get("plane"),
                                          {"hostname": item["target"]}, item["detail"])
            continue

        budget = LATENCY_BUDGET_MS.get(item.get("plane") or "", None)
        latency = res.get("latency_ms")
        if budget is not None and latency is not None and latency > budget:
            item["status"] = WARN
            item["detail"] = f"通, 但延迟 {latency} ms 超过基线 {budget} ms"
            item["suggestion"] = f"观察 {ts.PLANES[item['plane']]['label']} 的交换机上行有没有拥塞。"
        else:
            item["status"] = PASS
            item["detail"] = f"{latency} ms" if latency is not None else "通"
    return items


def summarize(items: List[Dict]) -> Dict:
    """给界面顶上那条大结论用"""
    counts = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0, PENDING: 0}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    if counts[FAIL]:
        verdict, headline = FAIL, f"发现 {counts[FAIL]} 项故障"
    elif counts[WARN]:
        verdict, headline = WARN, f"发现 {counts[WARN]} 项警告"
    elif counts[PASS]:
        verdict, headline = PASS, "全部通过"
    else:
        verdict, headline = SKIP, "没有可执行的检查项"

    # 没查的项要说出来, 不能让"全部通过"盖住"其实有 8 项没查"
    unchecked = counts[SKIP] + counts[PENDING]
    return {
        "verdict": verdict,
        "headline": headline,
        "total": len(items),
        "counts": counts,
        "unchecked": unchecked,
        "note": f"另有 {unchecked} 项未检查" if unchecked else "",
    }


def sort_items(items: List[Dict]) -> List[Dict]:
    """故障在最上面 —— 现场第一眼要看到的是该动手的那几条"""
    return sorted(items, key=lambda i: (SEVERITY_ORDER.get(i["status"], 9),
                                        i.get("role_key") or "", i.get("target") or ""))
