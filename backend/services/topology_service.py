"""
组网图 —— 从模板直接生成, 实况可选叠加。

这是模板分层的落点: 选完「产品 + 机台类型」就能画出整张组网图, 不需要先有真节点、
不需要先扫网。图里每个角色接哪几个平面, 全部来自模板里的 roles[].planes。

两种模式:
  模板组网  只给 (product, machine) —— 节点是按模板排出来的规划值, status 一律
            "planned", 用于装机前确认组网是否符合预期
  叠加实况  再给 nodes(某个集群的真节点) —— 用真主机名 / 真 IP / 真状态替换规划值,
            数量对不上时按角色标出来(多了几台、少了几台)

版式是固定的, 不是力导向: 三条平面总线横着走, 角色分组挂在下面。前端照着
groups / switches / links 画, 位置每次都一样, 台数再多也只是组里多几个方块。
"""

from typing import Dict, List, Optional

from services import template_service as ts


STATION = {
    "id": "mgmt-station",
    "label": "管理站(Windows)",
    "note": "现场笔记本, 跑本工具",
    "planes": ["management"],
}


def _switches(roles: List[Dict]) -> List[Dict]:
    """只画真正有角色接上去的交换机 —— 模板里没人接数据面就不画数据交换机"""
    used = []
    for plane in ts.PLANE_ORDER:
        for role in roles:
            if any(p["plane"] == plane for p in role["planes"]):
                used.append(plane)
                break

    out, seen = [], set()
    for plane in used:
        meta = ts.PLANES[plane]
        sw_id = meta["switch"]
        if sw_id in seen:
            # 前后段共用一台 100GE 交换机, 合并成一个盒子, 平面记两条
            for sw in out:
                if sw["id"] == sw_id:
                    sw["planes"].append(plane)
            continue
        seen.add(sw_id)
        out.append({
            "id": sw_id,
            "label": meta["label"].split()[0] + "交换机 " + meta["bandwidth"],
            "planes": [plane],
            "bandwidth": meta["bandwidth"],
        })
    return out


def _planned_nodes(role: Dict, count: int) -> List[Dict]:
    nodes = []
    for offset in range(count):
        spec = ts.plan_node(role, offset)
        nodes.append({
            "hostname": spec["hostname"],
            "role_key": role["key"],
            "node_type": spec["node_type"],
            "mgmt_ip": spec["mgmt_ip"],
            "ctrl_ip": spec["ctrl_ip"],
            "data_ip": spec["data_ip"],
            "data_protocol": spec["data_protocol"],
            "plane_ips": spec["plane_ips"],
            "plane_status": {},
            "status": "planned",
            "id": None,
        })
    return nodes


def _live_nodes(rows: List, role: Dict) -> List[Dict]:
    """
    把数据库里的节点归到角色下。

    优先按 role_key 认 —— 这是模板展开时写进去的。认不到的(手工加的节点、
    老数据)退回按 node_type 认, 免得它们从图上凭空消失。
    """
    picked = [n for n in rows if (n.role_key or "") == role["key"]]
    if not picked:
        picked = [n for n in rows if not n.role_key and (n.node_type or "") == role["node_type"]]
    return [{
        "id": n.id,
        "hostname": n.hostname,
        "role_key": role["key"],
        "node_type": n.node_type,
        "mgmt_ip": n.mgmt_ip or n.bmc_ip,
        "ctrl_ip": n.ctrl_ip,
        "data_ip": n.data_ip,
        "data_protocol": n.data_protocol,
        "plane_ips": n.plane_ips or {},
        "plane_status": n.plane_status or {},
        "status": n.status or "unknown",
    } for n in sorted(picked, key=lambda x: (x.hostname or ""))]


def build(product: Dict, machine: Dict, nodes: Optional[List] = None) -> Dict:
    """
    生成组网图。nodes 为 None 时是纯模板组网; 给了就叠加实况。

    返回的 links 是"角色 → 交换机"这一级, 不是每台服务器各连一根 —— 22 台机器
    连出来的 66 根线在屏幕上只会糊成一片, 按角色汇总成一根并标上台数, 既看得清
    又不丢信息。
    """
    roles = product.get("roles", [])
    counts = (machine or {}).get("counts") or {}
    live = nodes is not None

    groups, links, mismatches = [], [], []

    for role in roles:
        planned_count = counts.get(role["key"], 0)
        if planned_count <= 0 and not live:
            continue

        members = _live_nodes(nodes, role) if live else _planned_nodes(role, planned_count)
        if planned_count <= 0 and not members:
            continue

        if live and len(members) != planned_count:
            diff = len(members) - planned_count
            mismatches.append(
                f"{role['label']}: 模板 {planned_count} 台, 实际 {len(members)} 台"
                f"({'多' if diff > 0 else '少'} {abs(diff)} 台)"
            )

        plane_rollup = {}
        for p in role["planes"]:
            states = [(n.get("plane_status") or {}).get(p["plane"]) for n in members]
            if any(x == "offline" for x in states):
                plane_rollup[p["plane"]] = "down"
            elif states and all(x == "online" for x in states):
                plane_rollup[p["plane"]] = "up"
            elif any(x == "online" for x in states):
                plane_rollup[p["plane"]] = "partial"
            else:
                plane_rollup[p["plane"]] = "unknown"

        groups.append({
            "key": role["key"],
            "label": role["label"],
            "plane_state": plane_rollup,
            "node_type": role["node_type"],
            "note": role["note"],
            "planned_count": planned_count,
            "count": len(members),
            "planes": [p["plane"] for p in role["planes"]],
            "checks": role["checks"],
            "nodes": members,
        })

        for p in role["planes"]:
            up = down = unknown = 0
            for n in members:
                state = (n.get("plane_status") or {}).get(p["plane"])
                if state == "online":
                    up += 1
                elif state == "offline":
                    down += 1
                else:
                    unknown += 1
            # 一条线代表这个角色所有机器在这个平面上的链路。全通画通的颜色, 有断的
            # 就画断的 —— 现场要的是"这条平面有没有问题", 而不是平均值
            state = "down" if down else ("up" if up and not unknown else
                                         ("partial" if up else "unknown"))
            links.append({
                "source": role["key"],
                "target": ts.PLANES[p["plane"]]["switch"],
                "plane": p["plane"],
                "protocol": p["protocol"] or None,
                "bandwidth": p["bandwidth"],
                "prefixes": p["prefixes"],
                # 一个角色在一个平面上可能有多块网卡, 线上标的是机器数不是网卡数
                "nics": len(p["prefixes"]),
                "count": len(members),
                "up": up, "down": down, "unknown": unknown,
                "state": state,
            })

    switches = _switches(roles)

    # 图为什么是空的 —— 直接说出来, 不要留一张白板让人猜。
    # 角色没勾平面就没有总线、没有连线、节点也没有 IP, 这是最常踩的一个坑。
    problems = []
    for role in roles:
        if counts.get(role["key"], 0) <= 0 and not live:
            continue
        if not role["planes"]:
            problems.append(f"角色「{role['label']}」在模板里没勾任何平面, 画不出连线, "
                            f"生成的节点也不会有 IP")
    if not groups and not problems:
        problems.append(f"机台类型「{(machine or {}).get('name')}」各角色台数都是 0, "
                        f"到「机台与模板」里填上台数")

    # 管理站接管理面 —— 它不是集群的一部分, 但不画上去就看不出运维是从哪儿进来的
    if any(s["id"] == "sw-mgmt" for s in switches):
        links.append({
            "source": STATION["id"], "target": "sw-mgmt", "plane": "management",
            "protocol": None, "bandwidth": "GE", "prefixes": [], "nics": 1,
            "count": 1, "up": 0, "down": 0, "unknown": 1, "state": "unknown",
        })

    return {
        "product": product.get("name"),
        "machine_type": (machine or {}).get("name"),
        "mode": "live" if live else "template",
        "station": STATION,
        "planes": [{"key": k, **ts.PLANES[k]} for k in ts.PLANE_ORDER
                   if any(k in g["planes"] for g in groups)],
        "switches": switches,
        "groups": groups,
        "links": links,
        "mismatches": mismatches,
        "problems": problems,
        "total_nodes": sum(g["count"] for g in groups),
    }
