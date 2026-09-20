"""
节点 IP 的两种写法, 保持一致。

正主是 plane_ips: {平面: [ip, ...]} —— 一个角色在一个平面上可以有多块网卡,
Master 数据面就是四个 IP(前段 DPDK 两个 + 后段 RDMA 两个)。

扁平字段(mgmt_ip / bmc_ip / ctrl_ip / data_ip)是第一个口的镜像, 留给 PXE、巡检
那些按扁平字段取值的老代码。两边必须一起改: 只改一边的话, 界面上改了 IP 而表格、
组网图、诊断(都读 plane_ips)纹丝不动, 看起来就是"编辑没生效"。

节点 API 与 nodes.json 导入都走这里, 不各写一份。
"""

from typing import Any, Dict, List, Optional

# 数据面走前段还是后段, 按协议判: DPDK 前段, 其余按后段 —— 与模板展开同一套规则
_DATA_PLANES = ("data_front", "data_back")


def clean_planes(raw: Any) -> Dict[str, List[str]]:
    """规整 plane_ips: 去空、去首尾空格; 一个 IP 都不剩的平面整条丢掉"""
    out: Dict[str, List[str]] = {}
    for plane, ips in (raw or {}).items():
        if isinstance(ips, str):
            ips = [ips]
        ips = [str(x).strip() for x in (ips or []) if str(x).strip()]
        if ips:
            out[str(plane)] = ips
    return out


def flat_from_planes(node) -> None:
    """plane_ips → 扁平字段(各取第一个口)"""
    planes = node.plane_ips or {}
    mgmt = (planes.get("management") or [None])[0]
    # 管理面与 BMC 同网段, 沿用模板展开时的约定
    node.mgmt_ip = mgmt
    node.bmc_ip = mgmt
    node.ctrl_ip = (planes.get("control") or [None])[0]
    node.data_ip = None
    for plane in _DATA_PLANES:
        first = (planes.get(plane) or [None])[0]
        if first:
            node.data_ip = first
            if not node.data_protocol:
                node.data_protocol = "DPDK" if plane == "data_front" else "RDMA"
            break


def planes_from_flat(node, changed: Dict[str, Any]) -> None:
    """
    扁平字段 → plane_ips(只动第一个口, 其余网卡原样留着)。

    给只认扁平字段的老调用方用: PXE 写完 mgmt_ip, 节点表格和组网图也得跟着变。
    """
    planes = dict(node.plane_ips or {})

    def put(plane: str, ip: Optional[str]) -> None:
        ips = list(planes.get(plane) or [])
        ip = (ip or "").strip()
        if ip:
            if ips:
                ips[0] = ip
            else:
                ips = [ip]
        elif ips:
            ips = ips[1:]        # 第一个口清空, 后面的网卡留着
        if ips:
            planes[plane] = ips
        else:
            planes.pop(plane, None)

    if "mgmt_ip" in changed or "bmc_ip" in changed:
        put("management", changed.get("mgmt_ip") or changed.get("bmc_ip"))
    if "ctrl_ip" in changed:
        put("control", changed.get("ctrl_ip"))
    if "data_ip" in changed:
        # 写进节点已有的那个数据面; 都没有就按协议挑一个
        target = next((p for p in _DATA_PLANES if planes.get(p)), None)
        if not target:
            protocol = str(changed.get("data_protocol") or node.data_protocol or "").upper()
            target = "data_front" if protocol == "DPDK" else "data_back"
        put(target, changed.get("data_ip"))

    node.plane_ips = planes


def apply_ips(node, submitted: Dict[str, Any]) -> None:
    """
    把这次提交的 IP 落到两边。plane_ips 给了就以它为准, 没给就按扁平字段反推。
    """
    if "plane_ips" in submitted:
        node.plane_ips = clean_planes(submitted["plane_ips"])
        flat_from_planes(node)
    elif {"mgmt_ip", "bmc_ip", "ctrl_ip", "data_ip"} & set(submitted):
        planes_from_flat(node, submitted)
