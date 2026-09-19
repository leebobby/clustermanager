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
os.environ.setdefault("CLUSTER_MANAGER_DATA_DIR", _TMPDIR)

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
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


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


def main():
    print("模板分层 / 组网图 / 诊断计划 测试\n")
    for fn in (test_migrate_v2, test_migrate_v1, test_migrate_idempotent,
               test_key_collision, test_bad_plane_dropped,
               test_expand, test_expand_skips_used, test_expand_two_clusters_dont_collide,
               test_topology_from_template, test_topology_no_data_plane,
               test_topology_live_mismatch, test_topology_legacy_node_still_shows,
               test_plan_shape, test_plan_with_script, test_plan_no_ip,
               test_summary_counts_unchecked, test_sort_puts_faults_first,
               test_ping_windows_error_reply, test_ping_no_command,
               test_unavailable_is_not_a_fault, test_probe_empty_host,
               test_run_all_isolates_failure, test_tcp_refused,
               test_run_builtin_marks_slow_as_warning):
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
