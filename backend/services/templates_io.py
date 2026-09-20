"""
导入 / 导出机台模板 (node_templates.json)。

模板才是这个工具里真正要搬来搬去的东西 —— 产品有哪些角色、每个角色接哪几个
平面、网段怎么排、机台类型各几台。节点是照着模板生成的产物, 换一台电脑、换一个
现场, 要带走的是模板这一份文件, 不是生成出来的节点表。

存储格式就是 BASE_DIR/node_templates.json 原样:

    {
      "_comment": "...",
      "products": [
        {"name": "...", "description": "...",
         "roles": [{"key": "master", "hostname_prefix": "master", "ip_start": 11,
                    "planes": [{"plane": "data_front", "prefixes": ["200.1.1.", "200.1.2."],
                                "protocol": "DPDK"}], ...}],
         "machine_types": [{"name": "标准型", "counts": {"master": 1, "slave": 5}}]}
      ]
    }

导出的就是这个, 所以导出→改几行→导回来是闭环的。

导入解析放宽一些, 手改过的文件也要能读进来:
  · {"products": [...]} / 直接一个产品数组 / 单独一个产品对象
  · 平面老写法 prefix(单个字符串)、counts 按主机名前缀索引, 都由
    template_service._normalize 那边认

两种写法:
  merge    同名产品整个换掉, 新产品追加, 文件里没提到的产品留着 —— 默认
  replace  整份覆盖, 文件里没有的产品删掉

先预览再写: 哪些产品新增 / 覆盖 / 不变, 覆盖的具体动了哪些角色和机台类型。
存下去之前照样过 template_service.validate —— 导入一份角色没配平面的模板,
后果和手工存一份一样: 节点没 IP、组网图空白。宁可在这里挡住。
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from services import template_service as ts
from services.jsonio import load_bytes  # noqa: F401  (给 api 层用)

MODES = ("merge", "replace")


# ── 解析 ──────────────────────────────────────────────────────────────────────

def _raw_products(data: Any) -> Tuple[List[Dict], List[str]]:
    """从上传的内容里掏出产品列表。认不出来的报上去, 不静默丢掉"""
    problems: List[str] = []

    if isinstance(data, dict):
        if isinstance(data.get("products"), list):
            raw = data["products"]
        elif "roles" in data or "machine_types" in data:
            raw = [data]                      # 单独导出的一个产品
        else:
            keys = ", ".join(list(data.keys())[:5]) or "(空)"
            raise ValueError(
                f"这份文件里找不到 products —— 顶层只有: {keys}。"
                "模板文件长这样: {\"products\": [...]}; 要导 nodes.json 请用节点页那个入口"
            )
    elif isinstance(data, list):
        raw = data
    else:
        raise ValueError("这份文件的顶层既不是对象也不是数组, 认不出来")

    products = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            problems.append(f"第 {i + 1} 个产品不是一个对象, 跳过")
            continue
        if not str(p.get("name") or "").strip():
            problems.append(f"第 {i + 1} 个产品没有 name, 跳过")
            continue
        products.append(p)
    return products, problems


def _scan(raw_products: List[Dict]) -> List[str]:
    """
    规整之前先照着原文扫一遍, 把会被静默丢掉的东西说出来。

    _normalize 那边对不认识的内容一律丢弃(平面名写错就整条平面没了), 读是读进来了,
    但人不知道自己那行没生效 —— 这就是上一轮"模板存住了 IP 却不生成"的老毛病。
    """
    problems: List[str] = []
    for p in raw_products:
        pname = str(p.get("name") or "").strip() or "(未命名)"
        roles = p.get("roles")
        if not isinstance(roles, list) or not roles:
            problems.append(f"产品「{pname}」没有 roles, 导进来会是个空产品")
            roles = []

        keys = set()
        for r in roles:
            if not isinstance(r, dict):
                problems.append(f"产品「{pname}」的 roles 里有一项不是对象, 跳过")
                continue
            rkey = ts.slugify(str(r.get("key") or r.get("node_type") or
                                  r.get("hostname_prefix") or ""))
            keys.add(rkey)
            label = str(r.get("label") or r.get("key") or "(未命名角色)").strip()
            planes = r.get("planes")
            if isinstance(planes, list):
                for x in planes:
                    if not isinstance(x, dict):
                        problems.append(f"「{pname}」/「{label}」的 planes 里有一项不是对象, 跳过")
                        continue
                    name = str(x.get("plane") or "").strip()
                    if name not in ts.PLANES:
                        problems.append(
                            f"「{pname}」/「{label}」的平面「{name or '(空)'}」不是"
                            f"已知取值({'/'.join(ts.PLANE_ORDER)}), 这一条会被丢掉"
                        )
            elif planes is not None:
                problems.append(f"「{pname}」/「{label}」的 planes 不是数组, 会被忽略")

        for m in (p.get("machine_types") or []):
            if not isinstance(m, dict):
                problems.append(f"产品「{pname}」的 machine_types 里有一项不是对象, 跳过")
                continue
            mname = str(m.get("name") or "").strip() or "(未命名)"
            counts = m.get("counts")
            if counts is None:
                continue
            if not isinstance(counts, dict):
                problems.append(f"「{pname}」/「{mname}」的 counts 不是对象, 会按 0 台算")
                continue
            # counts 的键还认主机名前缀和用户原样敲的写法, 所以这里只在完全对不上时才说
            unknown = [k for k in counts
                       if ts.slugify(str(k)) not in keys and str(k).strip() not in keys]
            if unknown:
                problems.append(
                    f"「{pname}」/「{mname}」的台数里有对不上角色的键: "
                    f"{', '.join(map(str, unknown[:4]))} —— 这些台数不会生效"
                )
    return problems


def parse(data: Any) -> Tuple[Dict, List[str]]:
    """上传的内容 → 规整后的 {"products": [...]} + 要报给人看的问题"""
    raw_products, problems = _raw_products(data)
    problems += _scan(raw_products)
    comment = data.get("_comment") if isinstance(data, dict) else None
    incoming = ts._normalize({"_comment": comment, "products": raw_products})
    if not incoming["products"]:
        raise ValueError("这份文件里没认出任何产品")
    return incoming, problems


# ── 比对 ──────────────────────────────────────────────────────────────────────

def _role_note(before: Dict, after: Dict) -> Optional[str]:
    """同一个角色前后有什么不一样 —— 只说人看得懂的那几项"""
    bits = []
    if before.get("hostname_prefix") != after.get("hostname_prefix"):
        bits.append(f"前缀 {before.get('hostname_prefix')} → {after.get('hostname_prefix')}")
    if before.get("ip_start") != after.get("ip_start"):
        bits.append(f"起始序号 {before.get('ip_start')} → {after.get('ip_start')}")

    def planes_of(role):
        return {p["plane"]: list(p.get("prefixes") or []) for p in (role.get("planes") or [])}

    pb, pa = planes_of(before), planes_of(after)
    for plane in ts.PLANE_ORDER:
        if plane not in pb and plane not in pa:
            continue
        label = ts.PLANES[plane]["label"]
        if plane not in pb:
            bits.append(f"+{label}")
        elif plane not in pa:
            bits.append(f"-{label}")
        elif pb[plane] != pa[plane]:
            bits.append(f"{label} 网段 {'/'.join(pb[plane]) or '空'} → {'/'.join(pa[plane]) or '空'}")
    if not bits and before != after:
        bits.append("其它字段有改动")
    return "、".join(bits) if bits else None


def _diff_product(before: Optional[Dict], after: Dict) -> Dict:
    """一个产品的变化。before 为 None 就是新增"""
    if before is None:
        total = {m["name"]: sum(m["counts"].values()) for m in after["machine_types"]}
        return {
            "name": after["name"],
            "action": "create",
            "roles": len(after["roles"]),
            "machine_types": len(after["machine_types"]),
            "notes": [f"角色 {', '.join(r['key'] for r in after['roles']) or '无'}"] +
                     [f"机台类型「{n}」{t} 台" for n, t in total.items()],
        }

    notes: List[str] = []
    rb = {r["key"]: r for r in before["roles"]}
    ra = {r["key"]: r for r in after["roles"]}
    for key in ra:
        if key not in rb:
            notes.append(f"新增角色「{ra[key].get('label') or key}」")
    for key in rb:
        if key not in ra:
            notes.append(f"删掉角色「{rb[key].get('label') or key}」—— 它下面的节点会一起消失")
    for key in ra:
        if key in rb:
            note = _role_note(rb[key], ra[key])
            if note:
                notes.append(f"角色「{ra[key].get('label') or key}」: {note}")

    mb = {m["name"]: m for m in before["machine_types"]}
    ma = {m["name"]: m for m in after["machine_types"]}
    for name in ma:
        if name not in mb:
            notes.append(f"新增机台类型「{name}」{sum(ma[name]['counts'].values())} 台")
    for name in mb:
        if name not in ma:
            notes.append(f"删掉机台类型「{name}」")
    for name in ma:
        if name in mb and mb[name]["counts"] != ma[name]["counts"]:
            changed = []
            for key in sorted(set(mb[name]["counts"]) | set(ma[name]["counts"])):
                b, a = mb[name]["counts"].get(key, 0), ma[name]["counts"].get(key, 0)
                if b != a:
                    changed.append(f"{key} {b} → {a}")
            notes.append(f"机台类型「{name}」台数: {', '.join(changed)}")
    if before.get("description") != after.get("description"):
        notes.append("说明有改动")

    return {
        "name": after["name"],
        "action": "update" if notes else "unchanged",
        "roles": len(after["roles"]),
        "machine_types": len(after["machine_types"]),
        "notes": notes,
    }


def plan(current: Dict, incoming: Dict, mode: str = "merge") -> Dict:
    """
    预览: 导进去会变成什么样。

    返回里的 result 就是真要写的那份内容 —— apply 直接拿它写, 预览和落地
    看到的是同一个东西, 不会"预览一套、存下去另一套"。
    """
    if mode not in MODES:
        raise ValueError(f"不认识的导入方式: {mode}")

    cur = {p["name"]: p for p in (current.get("products") or [])}
    inc = {p["name"]: p for p in (incoming.get("products") or [])}

    items = [_diff_product(cur.get(name), p) for name, p in inc.items()]

    if mode == "replace":
        merged = deepcopy(incoming["products"])
        dropped = [name for name in cur if name not in inc]
        kept: List[str] = []
    else:
        merged = [deepcopy(inc[p["name"]]) if p["name"] in inc else deepcopy(p)
                  for p in (current.get("products") or [])]
        merged += [deepcopy(p) for name, p in inc.items() if name not in cur]
        dropped = []
        kept = [name for name in cur if name not in inc]

    result = {"_comment": current.get("_comment") or ts._DEFAULT_TEMPLATES["_comment"],
              "products": merged}
    errors, warnings = ts.validate(result)

    return {
        "mode": mode,
        "items": items,
        "kept": kept,          # merge 时文件里没提到、原样留着的产品
        "dropped": dropped,    # replace 时会被删掉的产品
        "summary": {
            "create": sum(1 for x in items if x["action"] == "create"),
            "update": sum(1 for x in items if x["action"] == "update"),
            "unchanged": sum(1 for x in items if x["action"] == "unchanged"),
            "kept": len(kept),
            "dropped": len(dropped),
        },
        "errors": errors,
        "warnings": warnings,
        "result": result,
    }


def apply(preview: Dict) -> Dict:
    """把预览里那份 result 写进模板文件。有 errors 就不写"""
    if preview.get("errors"):
        raise ValueError(" ".join(preview["errors"][:3]))
    return ts.write_templates(preview["result"])


# ── 导出 ──────────────────────────────────────────────────────────────────────

_EXPORT_COMMENT = (
    "机台模板 —— 产品定义共用的角色配置(主机名前缀 / 平面 / 网段 / 起始序号), "
    "机台类型只定义各角色的台数。可直接改本文件, 再从「机台与模板」页导回去。"
)


def export(product: Optional[str] = None) -> Dict:
    """
    导出模板。不给 product 就是整份, 给了就只导那一个产品。

    导出的形状和模板文件一致, 所以单个产品也能直接导回来(走 merge 只换它自己)。
    """
    data = ts.read_templates()
    products = data.get("products") or []
    if product:
        picked = [p for p in products if p["name"] == product]
        if not picked:
            raise ValueError(f"产品不存在: {product}")
        products = picked
    return {"_comment": _EXPORT_COMMENT, "products": deepcopy(products)}
