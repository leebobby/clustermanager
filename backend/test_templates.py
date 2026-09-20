#!/usr/bin/env python3
"""
模板分层 / 组网图 / 诊断计划 的决策表测试。

重点盯三件在真机上很难发现、出错了又只会静默变成"数据不对"的事:

  1. 迁移时台数会不会丢 —— 老格式的 counts 按 hostname_prefix 索引, 新格式按 key。
     不跟着改键的话台数全变 0, 而界面上只会显示"这个机台类型 0 台", 不报错
  2. 展开时主机名与 IP 是否始终对齐 —— 跳过被占用的序号之后还得对得上
  3. 没有脚本认领的检查项不能被算成"通过" —— 一份把没查的项算成通过的体检报告
     比没有报告更糟

另外验一条 Windows 上的坑: ping.exe 收到"无法访问目标主机"的 ICMP 差错回包时
退出码也是 0。这条在 Linux 上永远复现不了, 只能靠假 subprocess 顶上来。

    python test_templates.py
"""

import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from console import force_utf8
force_utf8()

FAILED = []


def check(ok, label, extra=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{extra}]" if extra else ""))
    if not ok:
        FAILED.append(label)


def section(title):
    print(f"\n=== {title} ===")


# 模板文件要在导入 template_service 之前指到临时目录, 否则会写到真的 BASE_DIR
_TMPDIR = tempfile.mkdtemp(prefix="cm-tpl-test-")
# config.py 在 import 时就会按 BASE_DIR 建 iso/ firmware/ 目录并定好 db 路径,
# 指到临时目录去, 别在 backend/ 下拉一堆东西出来
os.environ["CLUSTER_MANAGER_DATA"] = _TMPDIR

from services import diag_plan, probe, template_service as ts, topology_service  # noqa: E402

ts.TEMPLATES_PATH = os.path.join(_TMPDIR, "node_templates.json")


# ── 1. 迁移 ───────────────────────────────────────────────────────────────────

def test_migrate_v2():
    section("v2(projects + 扁平网段) → v3(products + planes)")

    v2 = {
        "projects": [{
            "name": "老项目",
            "roles": [
                {"node_type": "master", "hostname_prefix": "mst", "role": "compute",
                 "data_protocol": "DPDK", "bmc_prefix": "172.16.0.", "ctrl_prefix": "172.16.3.",
                 "data_prefix": "200.1.1.", "hostname_start": 1, "ip_start": 11,
                 "cpu_cores": 128},
                {"node_type": "slave", "hostname_prefix": "slv", "role": "compute",
                 "data_protocol": "RDMA", "bmc_prefix": "172.16.0.", "ctrl_prefix": "172.16.3.",
                 "data_prefix": "100.1.1.", "hostname_start": 1, "ip_start": 51},
            ],
            "machine_types": [
                # counts 按 hostname_prefix 索引 —— 迁移后必须变成按 key 索引
                {"name": "标准型", "counts": {"mst": 6, "slv": 12}},
            ],
        }]
    }
    out = ts._normalize(v2)
    product = out["products"][0]
    roles = {r["key"]: r for r in product["roles"]}
    counts = product["machine_types"][0]["counts"]

    check(sorted(roles) == ["master", "slave"], "角色 key 从 node_type 推出",
          str(sorted(roles)))
    check(counts.get("master") == 6 and counts.get("slave") == 12,
          "台数跟着改键, 没有丢", json.dumps(counts, ensure_ascii=False))
    check(roles["master"]["hostname_prefix"] == "mst",
          "主机名前缀原样保留(它和 key 是两回事)")

    master_planes = {p["plane"]: p for p in roles["master"]["planes"]}
    check(sorted(master_planes) == ["control", "data_front", "management"],
          "DPDK 角色的数据面落到前段", str(sorted(master_planes)))
    check(master_planes["data_front"]["protocol"] == "DPDK", "协议带过去了")
    slave_planes = {p["plane"] for p in roles["slave"]["planes"]}
    check("data_back" in slave_planes, "RDMA 角色的数据面落到后段")

    check("dpdk_port" in roles["master"]["checks"], "按协议补上 DPDK 专项检查",
          str(roles["master"]["checks"]))
    check("nfs_mount" in roles["slave"]["checks"], "Slave 补上 NFS 挂载检查")
    check("bmc_prefix" not in roles["master"], "扁平网段字段已清掉")


# ── 1b. key 被规整时台数不能丢 ────────────────────────────────────────────────

def _one_role_product(raw_key, count_key, planes=None):
    """一个角色 + 一个机台类型; counts 按 count_key 索引"""
    if planes is None:
        planes = [{"plane": "management", "prefixes": ["192.168.9."]}]
    return {"products": [{
        "name": "P",
        "roles": [{"key": raw_key, "label": raw_key, "node_type": "slave",
                   "hostname_prefix": "n", "ip_start": 20, "planes": planes,
                   "checks": ["ping"]}],
        "machine_types": [{"name": "M", "counts": {count_key: 3}}],
    }]}


def test_counts_survive_key_normalization():
    section("key 被规整之后, 机台类型的台数要跟着改键")

    # 界面上 key 是个自由输入框。这三种写法都会被 _normalize_role 改掉, 而 counts 是
    # 按用户敲的那个键写进来的 —— 不跟着改键, 台数就静默变 0: 机台类型显示 0 台,
    # 节点一台不生成, IP 全空, 组网图也是空的, 一路上没有任何一处报错
    for raw in ("Master", "my master", "主节点", " master "):
        data = ts._normalize(_one_role_product(raw, raw))
        product = data["products"][0]
        key = product["roles"][0]["key"]
        counts = product["machine_types"][0]["counts"]
        check(counts.get(key) == 3,
              f"key {raw!r} 规整成 {key!r} 后台数还是 3", f"counts={counts}")

    # 中文 key 不该被压成空再落到 fallback —— 两个中文角色否则都会叫 role
    data = ts._normalize({"products": [{
        "name": "P",
        "roles": [
            {"key": "主节点", "node_type": "a", "hostname_prefix": "a",
             "planes": [{"plane": "management", "prefixes": ["10.0.0."]}], "checks": ["ping"]},
            {"key": "从节点", "node_type": "b", "hostname_prefix": "b",
             "planes": [{"plane": "management", "prefixes": ["10.0.1."]}], "checks": ["ping"]},
        ],
        "machine_types": [{"name": "M", "counts": {"主节点": 2, "从节点": 5}}],
    }]})
    product = data["products"][0]
    keys = [r["key"] for r in product["roles"]]
    check(keys == ["主节点", "从节点"], "中文 key 原样留着, 不会两个都变成 role", str(keys))
    check(product["machine_types"][0]["counts"] == {"主节点": 2, "从节点": 5},
          "中文 key 的台数也对得上", str(product["machine_types"][0]["counts"]))

    # counts 按老格式的 hostname_prefix 索引也认
    data = ts._normalize(_one_role_product("master", "n"))
    counts = data["products"][0]["machine_types"][0]["counts"]
    check(counts.get("master") == 3, "counts 按 hostname_prefix 索引也能认出来", str(counts))

    # 前缀别名不能把另一个角色的 key 抢过去: master 的前缀叫 node, 而 node 是另一个
    # 角色真正的 key —— counts["node"] 必须算给后者
    data = ts._normalize({"products": [{
        "name": "P",
        "roles": [
            {"key": "master", "node_type": "m", "hostname_prefix": "node",
             "planes": [{"plane": "management", "prefixes": ["10.0.0."]}], "checks": ["ping"]},
            {"key": "node", "node_type": "n", "hostname_prefix": "slave",
             "planes": [{"plane": "management", "prefixes": ["10.0.1."]}], "checks": ["ping"]},
        ],
        "machine_types": [{"name": "M", "counts": {"master": 2, "node": 7}}],
    }]})
    counts = data["products"][0]["machine_types"][0]["counts"]
    check(counts == {"master": 2, "node": 7}, "前缀别名不会抢走另一个角色的 key", str(counts))


def test_key_normalization_end_to_end():
    section("key 规整之后, 节点和组网图都得有东西")

    data = ts._normalize(_one_role_product("Master", "Master"))
    product = data["products"][0]
    machine = product["machine_types"][0]
    planned, _ = ts.expand(product, machine, set(), set())
    check(len(planned) == 3, "展开出 3 台", f"{len(planned)} 台")
    check(all(n["status"] == "unknown" for n in planned),
          "刚生成的节点是'还没测过'而不是'断了'", str({n["status"] for n in planned}))
    check(all(n["mgmt_ip"] for n in planned), "每台都有管理面 IP",
          str([n["mgmt_ip"] for n in planned]))
    graph = topology_service.build(product, machine)
    check(graph["total_nodes"] == 3 and len(graph["planes"]) == 1,
          "组网图不是空的", f"nodes={graph['total_nodes']} planes={len(graph['planes'])}")


# ── 1c. 存下去也画不出东西的模板要被挡住 ──────────────────────────────────────

def test_validate_blocks_role_without_planes():
    section("角色没配平面 —— 存下去不报错, 但节点没 IP、组网图是空的")

    data = ts._normalize(_one_role_product("master", "master", planes=[]))
    product, machine = data["products"][0], data["products"][0]["machine_types"][0]

    # 先确认这确实是一条静默的坑: 节点建得出来, 但一个 IP 都没有
    planned, _ = ts.expand(product, machine, set(), set())
    check(len(planned) == 3 and not any(ts.all_ips(n) for n in planned),
          "没配平面时节点照样建 3 台, 但 IP 全空 —— 所以必须在保存时挡住",
          f"{len(planned)} 台")

    graph = topology_service.build(product, machine)
    check(not graph["planes"] and not graph["links"] and not graph["switches"],
          "组网图没有总线 / 连线 / 交换机")
    check(any("没勾任何平面" in x for x in graph["problems"]),
          "组网图自己说得出为什么是空的", str(graph["problems"]))

    errors, _ = ts.validate(data)
    check(len(errors) == 1 and "没勾任何平面" in errors[0],
          "validate 挡住并说清怎么改", str(errors))


def test_validate_blocks_plane_without_prefix():
    section("勾了平面但没填网段 —— 那个平面不会生成 IP")

    data = ts._normalize(_one_role_product(
        "master", "master",
        planes=[{"plane": "management", "prefixes": ["192.168.9."]},
                {"plane": "control", "prefixes": ["  "]}]))
    errors, _ = ts.validate(data)
    check(len(errors) == 1 and "没填网段前缀" in errors[0], "只报没填网段的那一个平面",
          str(errors))

    product, machine = data["products"][0], data["products"][0]["machine_types"][0]
    planned, _ = ts.expand(product, machine, set(), set())
    check(planned[0]["mgmt_ip"] and not planned[0]["ctrl_ip"],
          "确实只缺控制面那一个 IP", str(planned[0]["plane_ips"]))


def test_validate_default_template_is_clean():
    section("内置默认模板本身要过体检")

    errors, warnings = ts.validate(ts._normalize(ts._DEFAULT_TEMPLATES))
    check(not errors, "默认模板没有错误", str(errors))
    check(not warnings, "默认模板没有提醒", str(warnings))


def test_validate_warns_all_zero_counts():
    section("机台类型台数全 0 —— 提醒, 但不挡")

    data = ts._normalize(_one_role_product("master", "master"))
    data["products"][0]["machine_types"][0]["counts"]["master"] = 0
    errors, warnings = ts.validate(data)
    check(not errors, "不挡", str(errors))
    check(any("台数都是 0" in x for x in warnings), "提醒一句", str(warnings))


def test_migrate_v1():
    section("v1(templates + 角色内嵌 count) → v3")

    v1 = {"templates": [{
        "model": "老型号",
        "roles": [
            {"node_type": "master", "hostname_prefix": "master", "count": 3,
             "bmc_prefix": "10.0.0.", "ip_start": 11},
            {"node_type": "slave", "hostname_prefix": "slave", "count": 5,
             "bmc_prefix": "10.0.0.", "ip_start": 51},
        ],
    }]}
    product = ts._normalize(v1)["products"][0]
    counts = product["machine_types"][0]["counts"]
    check(counts == {"master": 3, "slave": 5}, "count 变成同名机台类型的台数",
          json.dumps(counts))
    check(product["machine_types"][0]["name"] == "老型号", "机台类型沿用型号名")


def test_migrate_idempotent():
    section("已经是 v3 的再迁一次不变形")
    once = ts._normalize({"products": ts._normalize({"projects": [{
        "name": "P", "roles": [{"node_type": "master", "hostname_prefix": "m",
                                "bmc_prefix": "10.0.0.", "ip_start": 5}],
        "machine_types": [{"name": "T", "counts": {"m": 2}}],
    }]})["products"]})
    twice = ts._normalize(once)
    check(once == twice, "二次规整结果一致")
    check(twice["products"][0]["machine_types"][0]["counts"] == {"master": 2},
          "台数经两次规整仍在")


def test_key_collision():
    section("两个角色推出同一个 key")
    out = ts._normalize({"products": [{
        "name": "P",
        "roles": [{"node_type": "slave", "hostname_prefix": "a"},
                  {"node_type": "slave", "hostname_prefix": "b"}],
        "machine_types": [{"name": "T", "counts": {"slave": 4}}],
    }]})
    keys = [r["key"] for r in out["products"][0]["roles"]]
    check(len(set(keys)) == 2, "后来者自动改名, 不会串台", str(keys))


def test_bad_plane_dropped():
    section("平面名写错")
    role = ts._normalize_role({"key": "x", "planes": [
        {"plane": "management", "prefix": "10.0.0."},
        {"plane": "存储面", "prefix": "10.9.9."},
    ]})
    check([p["plane"] for p in role["planes"]] == ["management"],
          "不认识的平面直接丢掉, 不画进图里")


def test_plane_prefixes():
    section("一个平面多块网卡")
    role = ts._normalize_role({"key": "master", "planes": [
        {"plane": "data_front", "prefixes": ["200.1.1.", "200.1.2."], "protocol": "DPDK"},
        {"plane": "data_back", "prefix": "100.1.1.", "protocol": "RDMA"},   # 老写法
    ]})
    front = next(p for p in role["planes"] if p["plane"] == "data_front")
    back = next(p for p in role["planes"] if p["plane"] == "data_back")
    check(front["prefixes"] == ["200.1.1.", "200.1.2."], "多个前缀原样保留",
          str(front["prefixes"]))
    check(back["prefixes"] == ["100.1.1."], "老的单个 prefix 也读得进来",
          str(back["prefixes"]))


def test_master_four_data_ips():
    section("Master 数据面四个 IP")
    product = ts._normalize(ts._DEFAULT_TEMPLATES)["products"][0]
    master = ts.find_role(product, "master")
    spec = ts.plan_node(master, 0)

    check(len(spec["plane_ips"].get("data_front", [])) == 2, "前段 DPDK 两个",
          str(spec["plane_ips"].get("data_front")))
    check(len(spec["plane_ips"].get("data_back", [])) == 2, "后段 RDMA 两个",
          str(spec["plane_ips"].get("data_back")))
    check(len(ts.all_ips(spec)) == 6, "连管理面控制面一共六个 IP",
          str(sorted(ts.all_ips(spec))))
    check(spec["data_ip"] == "200.1.1.11" and spec["data_protocol"] == "DPDK",
          "扁平 data_ip 取第一个, 老代码不受影响", f"{spec['data_ip']} {spec['data_protocol']}")

    # 四个 IP 必须各自成一项检查 —— 合成一项会把断掉的那口盖住
    graph = topology_service.build(product, product["machine_types"][0])
    items = [i for i in diag_plan.build_plan(graph, {})
             if i["target"] == "master-01" and i["check"] == "ping"]
    hosts = [i["host"] for i in items]
    check(len(items) == 6, "master-01 排出六项可达性检查", str(len(items)))
    check(len(set(hosts)) == 6, "六个检查点是六个不同的 IP", str(hosts))
    check(any("第 2 口" in i["title"] for i in items), "多网卡时标出是第几口",
          str([i["title"] for i in items if "口" in i["title"]]))


def test_ip_conflict_covers_all_nics():
    section("避让要覆盖全部网卡的 IP")
    product = ts._normalize(ts._DEFAULT_TEMPLATES)["products"][0]
    machine = next(m for m in product["machine_types"] if m["counts"].get("master"))
    # 占住 master-01 第二块 DPDK 网卡的 IP。只看扁平 data_ip 的话这条会漏掉
    planned, conflicts = ts.expand(product, machine, set(), {"200.1.2.11"})
    master = next(n for n in planned if n["role_key"] == "master")
    check(master["hostname"] != "master-01", "被占的序号整体跳过", master["hostname"])
    check(any("跳过" in c for c in conflicts), "冲突有说明", str(conflicts))


def test_selection():
    section("按勾选缩小诊断范围")
    product = ts._normalize(ts._DEFAULT_TEMPLATES)["products"][0]
    graph = topology_service.build(product, product["machine_types"][0])
    items = diag_plan.build_plan(graph, {})

    only_ssh = diag_plan.select(items, checks=["ssh"])
    check(only_ssh and all(i["check"] == "ssh" for i in only_ssh),
          "只勾 SSH 就只剩 SSH", f"{len(only_ssh)} 项")

    only_master = diag_plan.select(items, roles=["master"])
    check(only_master and all(i["role_key"] == "master" for i in only_master),
          "只勾 Master 就只剩 Master", f"{len(only_master)} 项")

    # 标准型有 6 台 Master, 每台 6 个平面检查点 —— 6 x 6
    both = diag_plan.select(items, checks=["ping"], roles=["master"])
    check(len(both) == 36 and all(i["check"] == "ping" and i["role_key"] == "master"
                                  for i in both),
          "两个条件是且的关系", f"{len(both)} 项")

    check(len(diag_plan.select(items)) == len(items), "都不勾就是全都要")

    opts = diag_plan.options(items)
    ready = {c["key"]: c["ready"] for c in opts["checks"]}
    check(ready.get("ping") is True and ready.get("dpdk_port") is False,
          "没脚本认领的标成不可跑, 让人知道勾了也白勾", str(ready))


def test_plane_status_rollup():
    section("每平面通断汇总")
    items = [
        {"check": "ping", "plane": "data_front", "target": "m1", "status": diag_plan.PASS},
        {"check": "ping", "plane": "data_front", "target": "m1", "status": diag_plan.FAIL},
        {"check": "ping", "plane": "control", "target": "m1", "status": diag_plan.PASS},
        {"check": "ssh", "plane": None, "target": "m1", "status": diag_plan.FAIL},
    ]
    out = diag_plan.plane_status(items)
    check(out["m1"]["data_front"] == "offline",
          "四个口断一个, 这个平面就算断 —— 组网图上这条线该是红的")
    check(out["m1"]["control"] == "online", "全通的平面算通")
    check("ssh" not in str(out), "非平面检查不参与平面汇总")


# ── 2. 展开 ───────────────────────────────────────────────────────────────────

def _demo_product():
    return ts._normalize({"products": [{
        "name": "P",
        "roles": [
            {"key": "master", "label": "Master", "node_type": "master",
             "hostname_prefix": "master", "hostname_start": 1, "ip_start": 11,
             "checks": ["ping", "dpdk_port"],
             "planes": [{"plane": "management", "prefix": "172.16.0."},
                        {"plane": "control", "prefix": "172.16.3."},
                        {"plane": "data_front", "prefix": "200.1.1.", "protocol": "DPDK"}]},
            {"key": "slave", "label": "Slave", "node_type": "slave",
             "hostname_prefix": "slave", "hostname_start": 1, "ip_start": 51,
             "checks": ["ping", "rdma_link"],
             "planes": [{"plane": "management", "prefix": "172.16.0."},
                        {"plane": "data_back", "prefix": "100.1.1.", "protocol": "RDMA"}]},
        ],
        "machine_types": [{"name": "T", "counts": {"master": 2, "slave": 3}}],
    }]})["products"][0]


def test_expand():
    section("展开成节点")
    product = _demo_product()
    machine = product["machine_types"][0]
    planned, conflicts = ts.expand(product, machine, set(), set())

    check(len(planned) == 5, "台数对", f"{len(planned)} 台")
    check(not conflicts, "无冲突")

    first = planned[0]
    check(first["hostname"] == "master-01" and first["ctrl_ip"] == "172.16.3.11",
          "主机名序号与 IP 末段对齐", f"{first['hostname']} / {first['ctrl_ip']}")
    check(first["mgmt_ip"] == first["bmc_ip"] == "172.16.0.11",
          "管理面同时填 mgmt_ip 与 bmc_ip(沿用既有约定)")
    check(first["data_protocol"] == "DPDK" and first["data_ip"] == "200.1.1.11",
          "数据面协议与 IP 从 planes 来")
    check(first["role_key"] == "master", "带上 role_key, 组网图靠它归组")

    slave = next(n for n in planned if n["hostname"] == "slave-01")
    check(slave["ctrl_ip"] is None, "模板没声明控制面就不给控制面 IP")


def test_expand_skips_used():
    section("展开时避让已占用的号")
    product = _demo_product()
    machine = product["machine_types"][0]
    planned, conflicts = ts.expand(product, machine, {"master-01"}, {"172.16.3.12"})

    names = [n["hostname"] for n in planned if n["role_key"] == "master"]
    check("master-01" not in names, "被占用的主机名跳过", str(names))
    check(all(n["ctrl_ip"] != "172.16.3.12" for n in planned), "被占用的 IP 跳过")
    master = next(n for n in planned if n["role_key"] == "master")
    tail = int(master["ctrl_ip"].rsplit(".", 1)[1])
    seq = int(master["hostname"].rsplit("-", 1)[1])
    check(tail - 11 == seq - 1, "跳过之后主机名与 IP 仍然对齐",
          f"{master['hostname']} / {master['ctrl_ip']}")
    check(any("跳过" in c for c in conflicts), "冲突有说明", str(conflicts))


def test_expand_two_clusters_dont_collide():
    section("同一机台类型连开两套集群")
    product = _demo_product()
    machine = product["machine_types"][0]
    used_h, used_ip = set(), set()
    first, _ = ts.expand(product, machine, used_h, used_ip)
    second, _ = ts.expand(product, machine, used_h, used_ip)

    overlap = {n["hostname"] for n in first} & {n["hostname"] for n in second}
    check(not overlap, "两套集群的主机名不重叠", str(sorted(overlap)))
    check(len(second) == 5, "第二套照样排满")


# ── 3. 组网图 ─────────────────────────────────────────────────────────────────

def test_topology_from_template():
    section("只凭模板画组网图(不碰数据库)")
    product = _demo_product()
    graph = topology_service.build(product, product["machine_types"][0])

    check(graph["mode"] == "template", "模式是模板组网")
    check(graph["total_nodes"] == 5, "节点数按模板算出来", str(graph["total_nodes"]))
    check(all(n["status"] == "planned" for g in graph["groups"] for n in g["nodes"]),
          "节点状态一律 planned, 不冒充在线")

    sw = {s["id"] for s in graph["switches"]}
    check(sw == {"sw-mgmt", "sw-ctrl", "sw-data-100g"}, "交换机按实际用到的平面画", str(sorted(sw)))
    data_sw = next(s for s in graph["switches"] if s["id"] == "sw-data-100g")
    check(sorted(data_sw["planes"]) == ["data_back", "data_front"],
          "前后段共用一台 100GE 交换机, 合成一个盒子")

    role_links = [l for l in graph["links"] if l["source"] == "master"]
    check(len(role_links) == 3, "角色按声明的平面各连一根", str(len(role_links)))
    check(all(l["count"] == 2 for l in role_links), "连线上带台数, 22 台也只画一根")
    check(any(l["source"] == "mgmt-station" for l in graph["links"]), "管理站接在管理面上")


def test_topology_no_data_plane():
    section("模板里没人接数据面")
    product = ts._normalize({"products": [{
        "name": "P",
        "roles": [{"key": "host", "node_type": "host", "hostname_prefix": "host",
                   "planes": [{"plane": "management", "prefix": "10.0.0."}]}],
        "machine_types": [{"name": "T", "counts": {"host": 1}}],
    }]})["products"][0]
    graph = topology_service.build(product, product["machine_types"][0])
    check({s["id"] for s in graph["switches"]} == {"sw-mgmt"},
          "就不画数据交换机", str([s["id"] for s in graph["switches"]]))


class _FakeNode:
    """没显式给的属性一律 None —— 对应"列存在但值是空"这种情况"""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return None


def test_topology_live_mismatch():
    section("叠加实况: 实际台数和模板对不上")
    product = _demo_product()
    machine = product["machine_types"][0]      # master 2 台
    nodes = [_FakeNode(id=1, hostname="master-01", node_type="master", role_key="master",
                       mgmt_ip="172.16.0.11", bmc_ip="172.16.0.11", ctrl_ip="172.16.3.11",
                       data_ip="200.1.1.11", data_protocol="DPDK", status="online")]
    graph = topology_service.build(product, machine, nodes)

    check(graph["mode"] == "live", "模式是实况")
    check(any("Master" in m and "少 1 台" in m for m in graph["mismatches"]),
          "少了几台要明说", str(graph["mismatches"]))


def test_topology_legacy_node_still_shows():
    section("老节点没有 role_key")
    product = _demo_product()
    nodes = [_FakeNode(id=9, hostname="master-99", node_type="master", role_key=None,
                       mgmt_ip="1.1.1.1", bmc_ip="1.1.1.1", ctrl_ip=None,
                       data_ip=None, data_protocol=None, status="offline")]
    graph = topology_service.build(product, product["machine_types"][0], nodes)
    master = next(g for g in graph["groups"] if g["key"] == "master")
    check([n["hostname"] for n in master["nodes"]] == ["master-99"],
          "退回按 node_type 认, 不让它从图上凭空消失")


# ── 4. 诊断计划 ───────────────────────────────────────────────────────────────

def test_plan_shape():
    section("检查计划由组网图推导")
    product = _demo_product()
    graph = topology_service.build(product, product["machine_types"][0])
    items = diag_plan.build_plan(graph, scripts_by_check={})

    master_ping = [i for i in items
                   if i["target"] == "master-01" and i["check"] == "ping"]
    check(len(master_ping) == 3, "Master 声明 3 个平面就排 3 项可达性检查",
          str([i["plane"] for i in master_ping]))
    slave_ping = [i for i in items if i["target"] == "slave-01" and i["check"] == "ping"]
    check(len(slave_ping) == 2, "Slave 只声明 2 个平面就只排 2 项",
          str([i["plane"] for i in slave_ping]))

    dpdk = next(i for i in items if i["check"] == "dpdk_port")
    check(dpdk["status"] == diag_plan.SKIP, "没有脚本认领 → 标未配置, 不是通过")
    check("没有脚本认领" in dpdk["detail"], "说清楚为什么没查", dpdk["detail"])
    check("check" not in dpdk["suggestion"] and dpdk["suggestion"],
          "给的是一句能照做的话", dpdk["suggestion"])


def test_plan_with_script():
    section("有脚本认领的专项检查")
    product = _demo_product()
    graph = topology_service.build(product, product["machine_types"][0])
    items = diag_plan.build_plan(graph, {"dpdk_port": {"id": 7, "name": "查 DPDK 端口"}})
    dpdk = next(i for i in items if i["check"] == "dpdk_port")
    check(dpdk["status"] == diag_plan.PENDING and dpdk["script_id"] == 7,
          "带上脚本 id 等着跑", f"{dpdk['status']} / {dpdk['script_id']}")


def test_plan_no_ip():
    section("模板里某个平面没配网段")
    product = ts._normalize({"products": [{
        "name": "P",
        "roles": [{"key": "master", "node_type": "master", "hostname_prefix": "master",
                   "checks": ["ping"],
                   "planes": [{"plane": "management", "prefix": ""}]}],
        "machine_types": [{"name": "T", "counts": {"master": 1}}],
    }]})["products"][0]
    graph = topology_service.build(product, product["machine_types"][0])
    item = next(i for i in diag_plan.build_plan(graph, {}) if i["check"] == "ping")
    check(item["status"] == diag_plan.SKIP and "没有地址" in item["detail"],
          "没地址就标没查, 不算通过", item["detail"])


def test_summary_counts_unchecked():
    section("汇总不能让'通过'盖住'没查'")
    items = [{"status": diag_plan.PASS}, {"status": diag_plan.PASS},
             {"status": diag_plan.SKIP}, {"status": diag_plan.SKIP},
             {"status": diag_plan.PENDING}]
    summary = diag_plan.summarize(items)
    check(summary["verdict"] == diag_plan.PASS, "没有故障和警告时结论是通过")
    check(summary["unchecked"] == 3, "未检查的项单独计数", str(summary["unchecked"]))
    check("3 项未检查" in summary["note"], "并且写在结论旁边", summary["note"])

    with_fail = diag_plan.summarize(items + [{"status": diag_plan.FAIL}])
    check(with_fail["verdict"] == diag_plan.FAIL and "1 项故障" in with_fail["headline"],
          "有故障时故障优先", with_fail["headline"])


def test_sort_puts_faults_first():
    section("排序")
    items = [
        {"status": diag_plan.PASS, "role_key": "a", "target": "n1"},
        {"status": diag_plan.SKIP, "role_key": "a", "target": "n2"},
        {"status": diag_plan.FAIL, "role_key": "b", "target": "n3"},
        {"status": diag_plan.WARN, "role_key": "a", "target": "n4"},
    ]
    order = [i["status"] for i in diag_plan.sort_items(items)]
    check(order[0] == diag_plan.FAIL and order[1] == diag_plan.WARN,
          "故障在最上面, 警告紧跟着", str(order))


# ── 5. 真探测 ─────────────────────────────────────────────────────────────────

class _FakeProc:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def test_ping_windows_error_reply():
    section("Windows 的坑: 差错回包退出码也是 0")

    # "无法访问目标主机" —— 退出码 0, 但没有 TTL=
    with mock.patch.object(probe.subprocess, "run",
                           return_value=_FakeProc(0, b"Reply from 10.0.0.1: Destination host unreachable.")):
        res = probe.ping("10.0.0.9")
    check(not res["ok"], "只看退出码会判成通, 这里判成不通", res["detail"])
    check("不可达" in res["detail"], "说清楚是差错回包", res["detail"])

    # 真 echo reply
    with mock.patch.object(probe.subprocess, "run",
                           return_value=_FakeProc(0, b"Reply from 10.0.0.9: bytes=32 time=3ms TTL=64")):
        res = probe.ping("10.0.0.9")
    check(res["ok"] and res["latency_ms"] == 3.0, "真回包判成通并取到 RTT", str(res))

    # 中文 Windows: "时间=1ms", TTL= 仍是 ASCII
    with mock.patch.object(probe.subprocess, "run",
                           return_value=_FakeProc(0, "来自 10.0.0.9 的回复: 字节=32 时间=1ms TTL=64".encode("gbk"))):
        res = probe.ping("10.0.0.9")
    check(res["ok"] and res["latency_ms"] == 1.0, "中文 locale 也认得出来", str(res))

    # time<1ms
    with mock.patch.object(probe.subprocess, "run",
                           return_value=_FakeProc(0, b"Reply from 1.1.1.1: bytes=32 time<1ms TTL=64")):
        res = probe.ping("1.1.1.1")
    check(res["ok"] and res["latency_ms"] == 1.0, "time<1ms 也能解析", str(res))


def test_ping_no_command():
    section("本机没有 ping 命令")
    with mock.patch.object(probe.subprocess, "run", side_effect=FileNotFoundError()):
        res = probe.ping("10.0.0.1")
    check(not res["ok"] and "没有 ping 命令" in res["detail"],
          "不抛异常, 给一句看得懂的话", res["detail"])
    check(res.get("unavailable") is True,
          "标成'工具不可用', 和'探到了但不通'区分开")


def test_unavailable_is_not_a_fault():
    section("探测工具不可用 -> 记未检查, 不记故障")
    # 这条是在容器里截图时发现的: 本机没装 ping, 22 台机器报出 87 项"故障",
    # 建议还是"去查网线"。真实情况是根本没查成 —— 报成故障比不报还糟。
    items = [{
        "id": "n1|management|ping", "kind": "builtin", "status": diag_plan.PENDING,
        "check": "ping", "plane": "management", "host": "10.0.0.1", "target": "n1",
        "detail": "", "suggestion": "", "latency_ms": None,
    }]
    with mock.patch.object(probe, "ping", return_value={
            "ok": False, "latency_ms": None, "unavailable": True,
            "detail": "本机没有 ping 命令(Linux 上装 iputils 即可)"}):
        diag_plan.run_builtin(items)

    check(items[0]["status"] == diag_plan.SKIP, "记未检查", items[0]["status"])
    check("本机" in items[0]["detail"], "说清楚是本机的问题, 不是被测机的", items[0]["detail"])
    check("网线" not in items[0]["suggestion"] and "iputils" in items[0]["suggestion"],
          "建议是装 ping, 不是去查网线", items[0]["suggestion"])

    summary = diag_plan.summarize(items)
    check(summary["counts"][diag_plan.FAIL] == 0 and summary["unchecked"] == 1,
          "汇总里不算故障, 算未检查", str(summary["counts"]))


def test_probe_empty_host():
    section("地址为空")
    check(not probe.ping("")["ok"], "ping 空地址不炸")
    check(not probe.tcp("", 22)["ok"], "tcp 空地址不炸")


def test_run_all_isolates_failure():
    section("单个探测炸掉不带垮整批")
    def boom():
        raise RuntimeError("炸了")
    out = probe.run_all([("a", boom), ("b", lambda: {"ok": True, "latency_ms": 1})])
    check(out["a"]["ok"] is False and "RuntimeError" in out["a"]["detail"],
          "炸掉的那个变成一条失败结果", out["a"]["detail"])
    check(out["b"]["ok"] is True, "另一个照常返回")


def test_tcp_refused():
    section("TCP 连不上")
    # 0 端口不会有人监听, 各平台都会立刻拒绝或报错
    res = probe.tcp("127.0.0.1", 1, timeout=1.0)
    check(not res["ok"] and res["detail"], "给出原因而不是空结果", res["detail"])


def test_run_builtin_marks_slow_as_warning():
    section("通了但慢 → 警告, 不是故障")
    items = [{
        "id": "n1|control|ping", "kind": "builtin", "status": diag_plan.PENDING,
        "check": "ping", "plane": "control", "host": "10.0.0.1", "target": "n1",
        "detail": "", "suggestion": "", "latency_ms": None,
    }]
    with mock.patch.object(probe, "ping", return_value={"ok": True, "latency_ms": 9.0, "detail": ""}):
        diag_plan.run_builtin(items)
    check(items[0]["status"] == diag_plan.WARN, "超基线记警告", items[0]["detail"])
    check("基线" in items[0]["detail"], "说清楚基线是多少", items[0]["detail"])

    items[0].update(status=diag_plan.PENDING, detail="", latency_ms=None)
    with mock.patch.object(probe, "ping", return_value={"ok": True, "latency_ms": 0.4, "detail": ""}):
        diag_plan.run_builtin(items)
    check(items[0]["status"] == diag_plan.PASS, "在基线内记通过")

    items[0].update(status=diag_plan.PENDING, detail="", latency_ms=None)
    with mock.patch.object(probe, "ping", return_value={"ok": False, "latency_ms": None, "detail": "无响应"}):
        diag_plan.run_builtin(items)
    check(items[0]["status"] == diag_plan.FAIL, "不通记故障")
    check("控制口" in items[0]["suggestion"] or "10GE" in items[0]["suggestion"],
          "建议针对的是控制面, 不是通用套话", items[0]["suggestion"])


# ── 5. 节点的 IP: plane_ips 与扁平字段必须一起改 ──────────────────────────────

class _Node:
    """够 _apply_ips 用的假节点"""
    def __init__(self, **kw):
        self.plane_ips = None
        self.mgmt_ip = self.bmc_ip = self.ctrl_ip = self.data_ip = None
        self.data_protocol = None
        self.__dict__.update(kw)


def test_node_edit_keeps_all_nics():
    section("编辑节点: 四个数据口都要能改")

    from api import nodes as nodes_api

    node = _Node(plane_ips={"management": ["172.16.0.11"], "control": ["172.16.3.11"],
                            "data_front": ["200.1.1.11", "200.1.2.11"],
                            "data_back": ["100.1.1.11", "100.1.2.11"]})
    submitted = {"plane_ips": {"management": ["172.16.0.211"], "control": ["172.16.3.211"],
                               "data_front": ["200.1.1.211", "200.1.2.211"],
                               "data_back": ["100.1.1.211", "100.1.2.211"]}}
    nodes_api._apply_ips(node, submitted)

    check(node.plane_ips["data_back"] == ["100.1.1.211", "100.1.2.211"],
          "后段第二个口存下来了", str(node.plane_ips.get("data_back")))
    check(node.mgmt_ip == node.bmc_ip == "172.16.0.211",
          "扁平的管理面/BMC 跟着第一个口走", f"{node.mgmt_ip} / {node.bmc_ip}")
    check(node.data_ip == "200.1.1.211", "扁平数据面取前段第一个口", str(node.data_ip))


def test_node_flat_edit_reaches_planes():
    section("只改扁平字段(老接口)时, plane_ips 也得跟着变")

    from api import nodes as nodes_api

    # 这是之前真正的坑: 界面把管理面 IP 改了, 而节点表格 / 组网图 / 诊断读的都是
    # plane_ips —— 一个都没变, 看起来就是"编辑没生效"
    node = _Node(plane_ips={"management": ["172.16.0.11"],
                            "data_front": ["200.1.1.11", "200.1.2.11"]},
                 mgmt_ip="172.16.0.11")
    nodes_api._apply_ips(node, {"mgmt_ip": "9.9.9.9"})
    check(node.plane_ips["management"] == ["9.9.9.9"], "管理面跟着改了",
          str(node.plane_ips["management"]))
    check(node.plane_ips["data_front"] == ["200.1.1.11", "200.1.2.11"],
          "其它平面的网卡原样不动", str(node.plane_ips["data_front"]))

    # 第一个口清空时, 后面的网卡不能跟着没了
    node = _Node(plane_ips={"data_front": ["200.1.1.11", "200.1.2.11"]})
    nodes_api._apply_ips(node, {"data_ip": ""})
    check(node.plane_ips.get("data_front") == ["200.1.2.11"],
          "清掉第一个口, 第二个口还在", str(node.plane_ips))


def test_node_data_protocol_inferred():
    section("只有后段时, 扁平数据面落到后段并认出 RDMA")

    from api import nodes as nodes_api

    node = _Node()
    nodes_api._apply_ips(node, {"plane_ips": {"management": ["172.16.0.99"],
                                              "data_back": ["100.1.1.99", "100.1.2.99"]}})
    check(node.data_ip == "100.1.1.99", "数据面取后段第一个口", str(node.data_ip))
    check(node.data_protocol == "RDMA", "协议认成 RDMA", str(node.data_protocol))
    check("control" not in node.plane_ips, "没填的平面不会留一个空壳", str(node.plane_ips))


def test_node_create_ignores_unknown_columns():
    section("请求模型里多出来的字段不能让'加节点'炸掉")

    from models.node import Node

    columns = {c.name for c in Node.__table__.columns}
    check("cluster_id" not in columns,
          "模型里确实没有 cluster_id 了(集群那层已撤)")
    # 之前 NodeCreate 还留着 cluster_id, Node(**node.dict()) 直接 TypeError ——
    # 整个"加节点"是 500。现在按列过滤
    payload = {"hostname": "n1", "node_type": "slave", "cluster_id": 3, "不存在的字段": 1}
    kept = {k: v for k, v in payload.items() if k in columns}
    check(kept == {"hostname": "n1", "node_type": "slave"}, "只留模型真有的列", str(kept))
    node = Node(**kept)
    check(node.hostname == "n1", "构造得出来, 不抛 TypeError")



def main():
    print("模板分层 / 组网图 / 诊断计划 测试\n")
    for fn in (test_migrate_v2, test_migrate_v1, test_migrate_idempotent,
               test_counts_survive_key_normalization, test_key_normalization_end_to_end,
               test_validate_blocks_role_without_planes,
               test_validate_blocks_plane_without_prefix,
               test_validate_default_template_is_clean,
               test_validate_warns_all_zero_counts,
               test_key_collision, test_bad_plane_dropped,
               test_plane_prefixes, test_master_four_data_ips,
               test_ip_conflict_covers_all_nics, test_selection, test_plane_status_rollup,
               test_expand, test_expand_skips_used, test_expand_two_clusters_dont_collide,
               test_topology_from_template, test_topology_no_data_plane,
               test_topology_live_mismatch, test_topology_legacy_node_still_shows,
               test_plan_shape, test_plan_with_script, test_plan_no_ip,
               test_summary_counts_unchecked, test_sort_puts_faults_first,
               test_ping_windows_error_reply, test_ping_no_command,
               test_unavailable_is_not_a_fault, test_probe_empty_host,
               test_run_all_isolates_failure, test_tcp_refused,
               test_run_builtin_marks_slow_as_warning,
               test_node_edit_keeps_all_nics, test_node_flat_edit_reaches_planes,
               test_node_data_protocol_inferred, test_node_create_ignores_unknown_columns):
        fn()

    print()
    if FAILED:
        print(f"{len(FAILED)} 项失败:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
