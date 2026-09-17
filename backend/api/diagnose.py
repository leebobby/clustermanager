"""
故障诊断 API
"""

import asyncio
import json
import os
import threading
import uuid
import shlex
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import re

from models.node import Node, Log, FaultPoint, DPDKStats, RDMAStats, DiagScript, get_db, SessionLocal
from pydantic import BaseModel
from services.diag_service import (
    run_ssh_command, collect_node_logs, export_files_via_sftp,
    EXIT_TIMEOUT, EXIT_CANCELLED, EXIT_ERROR,
)
from services import cred_service
from config import SCRIPTS_BUNDLE_PATH, BASE_DIR

# 全局执行器: 诊断脚本通常都不算 CPU 密集, 给一个共享池足够
_SSH_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ssh-exec")

# 当前活跃的运行: run_id -> {"cancel": threading.Event, "clients": list, "lock": Lock}
# 用于支持「终止运行」按钮 — 终止请求会 set cancel 并 close 所有已建立的 paramiko 连接,
# 把阻塞在 channel.recv 上的 SSH 线程立即唤醒。
_ACTIVE_RUNS: Dict[str, Dict[str, Any]] = {}
_RUNS_LOCK = threading.Lock()


def _make_run_state() -> Dict[str, Any]:
    return {
        "cancel": threading.Event(),
        "clients": [],            # paramiko.SSHClient 列表
        "lock": threading.Lock(),
    }


def _cancel_run(run_id: str) -> bool:
    """触发运行终止: set cancel event + 强关所有已连上的 SSH。返回是否找到该运行。"""
    with _RUNS_LOCK:
        state = _ACTIVE_RUNS.get(run_id)
    if not state:
        return False
    state["cancel"].set()
    with state["lock"]:
        for c in state["clients"]:
            try: c.close()
            except Exception: pass
    return True


router = APIRouter()


def _evaluate_verdict(res: dict, expect_mode: str, expect_pattern: str) -> str:
    """
    根据脚本判定规则把一次执行结果归成三态:
      pass  正常 | fail 异常 | error 执行错误(连接失败/超时/取消, 无法判定健康度)

    expect_mode:
      exit_code      退出码 0=正常 否则异常 (默认)
      fault_if_match stdout/stderr 命中 expect_pattern → 异常
      pass_if_match  命中 expect_pattern → 正常, 否则异常
    """
    exit_code = res.get("exit_code", -1)
    if exit_code in (EXIT_ERROR, EXIT_TIMEOUT, EXIT_CANCELLED):
        return "error"

    mode = (expect_mode or "exit_code").lower()
    pattern = (expect_pattern or "").strip()
    if mode in ("fault_if_match", "pass_if_match") and pattern:
        haystack = (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
        try:
            matched = re.search(pattern, haystack, re.IGNORECASE | re.MULTILINE) is not None
        except re.error:
            matched = pattern.lower() in haystack.lower()   # 正则非法 → 退化为子串匹配
        if mode == "fault_if_match":
            return "fail" if matched else "pass"
        return "pass" if matched else "fail"

    return "pass" if exit_code == 0 else "fail"


class FaultPointResponse(BaseModel):
    id: int
    node_id: Optional[int]
    link_id: Optional[int]
    plane: str
    fault_type: str
    description: str
    severity: str
    related_logs: Optional[dict]
    suggestions: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class LogResponse(BaseModel):
    id: int
    node_id: Optional[int]
    log_type: str
    level: str
    message: str
    raw_content: Optional[str]
    collected_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class DiagnosisResult(BaseModel):
    """诊断结果"""
    node_id: int
    hostname: str
    overall_status: str
    faults: List[FaultPointResponse]
    recent_logs: List[LogResponse]
    suggestions: List[str]


@router.get("/faults", response_model=List[FaultPointResponse])
def get_fault_points(
    plane: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取故障点列表"""
    query = db.query(FaultPoint)
    if plane:
        query = query.filter(FaultPoint.plane == plane)
    if severity:
        query = query.filter(FaultPoint.severity == severity)
    if status:
        query = query.filter(FaultPoint.status == status)
    return query.order_by(FaultPoint.created_at.desc()).all()


@router.get("/faults/{fault_id}", response_model=FaultPointResponse)
def get_fault_detail(fault_id: int, db: Session = Depends(get_db)):
    """获取故障点详情"""
    fault = db.query(FaultPoint).filter(FaultPoint.id == fault_id).first()
    if not fault:
        raise HTTPException(status_code=404, detail="故障点不存在")
    return fault


@router.get("/nodes/{node_id}", response_model=DiagnosisResult)
def diagnose_node(node_id: int, db: Session = Depends(get_db)):
    """诊断指定节点"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    # 获取节点故障点
    faults = db.query(FaultPoint).filter(
        FaultPoint.node_id == node_id,
        FaultPoint.status == 'active'
    ).all()

    # 获取最近日志
    logs = db.query(Log).filter(Log.node_id == node_id).order_by(Log.created_at.desc()).limit(50).all()

    # 根据节点状态生成建议
    suggestions = []

    if node.status != 'online':
        suggestions.append("检查BMC连通性，确认IPMI服务正常")
        suggestions.append("通过BMC远程查看系统日志")

    if node.ctrl_status != 'online':
        suggestions.append("检查控制面10GE网络连通性")
        suggestions.append("确认心跳服务正常运行")

    if node.data_status != 'online':
        if node.node_type == 'master':
            suggestions.append("检查DPDK环境配置")
            suggestions.append("确认100GE网卡绑定正确")
            suggestions.append("查看DPDK收包统计")
        elif node.node_type == 'slave':
            suggestions.append("检查RDMA网卡状态")
            suggestions.append("确认RDMA连接配置正确")

    overall_status = "healthy"
    if faults:
        if any(f.severity == 'critical' for f in faults):
            overall_status = "critical"
        elif any(f.severity == 'warning' for f in faults):
            overall_status = "warning"
        else:
            overall_status = "info"

    return DiagnosisResult(
        node_id=node_id,
        hostname=node.hostname,
        overall_status=overall_status,
        faults=faults,
        recent_logs=logs,
        suggestions=suggestions
    )


@router.post("/nodes/{node_id}/collect-logs")
def collect_logs(node_id: int, db: Session = Depends(get_db)):
    """收集节点日志"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    # 模拟日志收集（实际需要SSH到节点收集）
    collected_logs = []

    log_types = ['syslog', 'kernel', 'dmesg']
    if node.node_type == 'master':
        log_types.append('dpdk')
    elif node.node_type == 'slave':
        log_types.append('rdma')

    # 模拟日志数据
    for log_type in log_types:
        log_entry = Log(
            node_id=node_id,
            log_type=log_type,
            level='info',
            message=f"{log_type} 日志收集完成",
            collected_at=datetime.utcnow()
        )
        db.add(log_entry)
        collected_logs.append(log_type)

    db.commit()

    return {
        "node_id": node_id,
        "hostname": node.hostname,
        "collected_types": collected_logs,
        "message": "日志收集完成"
    }


@router.get("/logs", response_model=List[LogResponse])
def get_logs(
    node_id: Optional[int] = None,
    log_type: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """查询日志"""
    query = db.query(Log)
    if node_id:
        query = query.filter(Log.node_id == node_id)
    if log_type:
        query = query.filter(Log.log_type == log_type)
    if level:
        query = query.filter(Log.level == level)
    return query.order_by(Log.created_at.desc()).limit(limit).all()


@router.post("/analyze")
def analyze_all_nodes(db: Session = Depends(get_db)):
    """分析所有节点，发现故障"""
    nodes = db.query(Node).all()
    found_faults = []

    for node in nodes:
        # 检查节点状态并创建故障点

        if node.status == 'offline':
            existing = db.query(FaultPoint).filter(
                FaultPoint.node_id == node.id,
                FaultPoint.fault_type == 'node_offline',
                FaultPoint.status == 'active'
            ).first()

            if not existing:
                fault = FaultPoint(
                    node_id=node.id,
                    plane='管理面',
                    fault_type='node_offline',
                    description=f"节点 {node.hostname} 完全离线",
                    severity='critical',
                    suggestions="1. 检查BMC电源状态\n2. 检查管理面网络\n3. 通过IPMI重启节点"
                )
                db.add(fault)
                found_faults.append({
                    "node_id": node.id,
                    "hostname": node.hostname,
                    "fault_type": "node_offline",
                    "plane": "管理面"
                })

        if node.ctrl_status == 'offline' and node.status == 'online':
            existing = db.query(FaultPoint).filter(
                FaultPoint.node_id == node.id,
                FaultPoint.fault_type == 'control_plane_down',
                FaultPoint.status == 'active'
            ).first()

            if not existing:
                fault = FaultPoint(
                    node_id=node.id,
                    plane='控制面',
                    fault_type='control_plane_down',
                    description=f"节点 {node.hostname} 控制面断开",
                    severity='warning',
                    suggestions="1. 检查10GE网卡状态\n2. 检查心跳服务\n3. 检查控制面网络配置"
                )
                db.add(fault)
                found_faults.append({
                    "node_id": node.id,
                    "hostname": node.hostname,
                    "fault_type": "control_plane_down",
                    "plane": "控制面"
                })

        if node.data_status == 'offline' and node.status == 'online':
            existing = db.query(FaultPoint).filter(
                FaultPoint.node_id == node.id,
                FaultPoint.fault_type == 'data_plane_down',
                FaultPoint.status == 'active'
            ).first()

            if not existing:
                protocol = node.data_protocol or "unknown"
                fault = FaultPoint(
                    node_id=node.id,
                    plane='数据面',
                    fault_type='data_plane_down',
                    description=f"节点 {node.hostname} 数据面断开 ({protocol})",
                    severity='critical',
                    suggestions=f"1. 检查100GE网卡状态\n2. 检查{protocol}配置\n3. 检查数据面网络连接"
                )
                db.add(fault)
                found_faults.append({
                    "node_id": node.id,
                    "hostname": node.hostname,
                    "fault_type": "data_plane_down",
                    "plane": "数据面"
                })

    db.commit()

    return {
        "message": "故障分析完成",
        "nodes_analyzed": len(nodes),
        "faults_found": len(found_faults),
        "faults": found_faults
    }


@router.get("/dpdk-stats/{node_id}")
def get_dpdk_stats(node_id: int, db: Session = Depends(get_db)):
    """获取DPDK统计（Master节点）"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    if node.node_type != 'master':
        raise HTTPException(status_code=400, detail="该节点不是Master节点")

    stats = db.query(DPDKStats).filter(DPDKStats.node_id == node_id).order_by(
        DPDKStats.collection_time.desc()
    ).limit(10).all()

    return {
        "node_id": node_id,
        "hostname": node.hostname,
        "data_ip": node.data_ip,
        "stats": stats
    }


@router.get("/rdma-stats/{node_id}")
def get_rdma_stats(node_id: int, db: Session = Depends(get_db)):
    """获取RDMA统计（Slave节点）"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    if node.node_type != 'slave':
        raise HTTPException(status_code=400, detail="该节点不是Slave节点")

    stats = db.query(RDMAStats).filter(RDMAStats.node_id == node_id).order_by(
        RDMAStats.collection_time.desc()
    ).limit(10).all()

    return {
        "node_id": node_id,
        "hostname": node.hostname,
        "data_ip": node.data_ip,
        "stats": stats
    }


@router.post("/faults/{fault_id}/resolve")
def resolve_fault(fault_id: int, db: Session = Depends(get_db)):
    """标记故障已解决"""
    fault = db.query(FaultPoint).filter(FaultPoint.id == fault_id).first()
    if not fault:
        raise HTTPException(status_code=404, detail="故障点不存在")

    fault.status = 'resolved'
    db.commit()

    return {"message": "故障已标记为解决", "fault_id": fault_id}


# ─────────────────────────────────────────────
#  诊断脚本 CRUD
# ─────────────────────────────────────────────

class DiagScriptCreate(BaseModel):
    name: str
    description: Optional[str] = ''
    script_tab: str = 'hardware'          # business / hardware / log_export
    category: str = '通用诊断'
    script_content: str
    target_node_type: str = 'all'
    timeout: int = 30
    enabled: bool = True
    output_mode: str = 'stdout'           # stdout / files (仅 log_export 用到)
    expect_mode: str = 'exit_code'        # exit_code / fault_if_match / pass_if_match
    expect_pattern: Optional[str] = ''    # 判定用的关键字/正则
    suggestion: Optional[str] = ''        # 判异常时展示的处置建议


class DiagScriptResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    script_tab: str
    category: str
    script_content: str
    target_node_type: str
    timeout: int
    enabled: bool
    output_mode: Optional[str] = 'stdout'
    expect_mode: Optional[str] = 'exit_code'
    expect_pattern: Optional[str] = ''
    suggestion: Optional[str] = ''
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/scripts", response_model=List[DiagScriptResponse])
def list_scripts(
    script_tab: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取诊断脚本列表"""
    q = db.query(DiagScript)
    if script_tab:
        q = q.filter(DiagScript.script_tab == script_tab)
    if category:
        q = q.filter(DiagScript.category == category)
    return q.order_by(DiagScript.category, DiagScript.name).all()


@router.post("/scripts", response_model=DiagScriptResponse)
def create_script(data: DiagScriptCreate, db: Session = Depends(get_db)):
    """新建诊断脚本"""
    script = DiagScript(**data.model_dump())
    db.add(script)
    db.commit()
    db.refresh(script)
    return script


@router.put("/scripts/{script_id}", response_model=DiagScriptResponse)
def update_script(script_id: int, data: DiagScriptCreate, db: Session = Depends(get_db)):
    """更新诊断脚本"""
    script = db.query(DiagScript).filter(DiagScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")
    for k, v in data.model_dump().items():
        setattr(script, k, v)
    script.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(script)
    return script


@router.delete("/scripts/{script_id}")
def delete_script(script_id: int, db: Session = Depends(get_db)):
    """删除诊断脚本"""
    script = db.query(DiagScript).filter(DiagScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")
    db.delete(script)
    db.commit()
    return {"message": "删除成功", "script_id": script_id}


# ─────────────────────────────────────────────
#  脚本配置 导出 / 导入 / 保存发布包
# ─────────────────────────────────────────────

def _scripts_to_list(scripts) -> list:
    return [
        {
            "name": s.name,
            "description": s.description or "",
            "script_tab": s.script_tab,
            "category": s.category,
            "script_content": s.script_content,
            "target_node_type": s.target_node_type,
            "timeout": s.timeout,
            "enabled": s.enabled,
            "output_mode": getattr(s, "output_mode", "stdout") or "stdout",
            "expect_mode": getattr(s, "expect_mode", "exit_code") or "exit_code",
            "expect_pattern": getattr(s, "expect_pattern", "") or "",
            "suggestion": getattr(s, "suggestion", "") or "",
        }
        for s in scripts
    ]


@router.get("/scripts/export")
def export_scripts(db: Session = Depends(get_db)):
    """导出全部诊断脚本为 JSON 文件（Content-Disposition: attachment）"""
    scripts = db.query(DiagScript).order_by(
        DiagScript.script_tab, DiagScript.category, DiagScript.name
    ).all()
    payload = {"version": "1.0", "scripts": _scripts_to_list(scripts)}
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=scripts_bundle.json"},
    )


class ScriptImportRequest(BaseModel):
    scripts: List[DiagScriptCreate]
    mode: str = "merge"   # merge=upsert, replace=先清空再导入


@router.post("/scripts/import")
def import_scripts(req: ScriptImportRequest, db: Session = Depends(get_db)):
    """批量导入脚本；merge 模式按 (script_tab+category+name) upsert，replace 先清空"""
    if req.mode == "replace":
        db.query(DiagScript).delete()
        db.commit()

    created = updated = 0
    for item in req.scripts:
        existing = db.query(DiagScript).filter(
            DiagScript.script_tab == item.script_tab,
            DiagScript.category == item.category,
            DiagScript.name == item.name,
        ).first()
        if existing:
            for k, v in item.model_dump().items():
                setattr(existing, k, v)
            existing.updated_at = datetime.utcnow()
            updated += 1
        else:
            db.add(DiagScript(**item.model_dump()))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}


@router.post("/scripts/save-bundle")
def save_bundle(db: Session = Depends(get_db)):
    """将当前数据库脚本快照写入 scripts_bundle.json（用于生成发布包）"""
    scripts = db.query(DiagScript).order_by(
        DiagScript.script_tab, DiagScript.category, DiagScript.name
    ).all()
    payload = {"version": "1.0", "scripts": _scripts_to_list(scripts)}
    with open(SCRIPTS_BUNDLE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {
        "message": f"已保存 {len(scripts)} 个脚本到发布配置",
        "path": SCRIPTS_BUNDLE_PATH,
        "count": len(scripts),
    }


@router.get("/scripts/bundle-info")
def get_bundle_info():
    """返回当前发布包信息（是否存在、脚本数量、修改时间）"""
    if not os.path.exists(SCRIPTS_BUNDLE_PATH):
        return {"exists": False, "count": 0, "mtime": None}
    try:
        with open(SCRIPTS_BUNDLE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        mtime = os.path.getmtime(SCRIPTS_BUNDLE_PATH)
        from datetime import timezone
        return {
            "exists": True,
            "count": len(data.get("scripts", [])),
            "mtime": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"exists": True, "count": 0, "mtime": None, "error": str(e)}


# ─────────────────────────────────────────────
#  .sh 文件夹包: 每脚本一个 .sh 文件 (带 #@ 元数据头), tab/分类 用两级目录承载
#  方便用 VSCode / git 在外部管理复杂脚本, 再整目录导回
# ─────────────────────────────────────────────

KNOWN_TABS = ("business", "hardware", "log_export")
DEFAULT_SCRIPTS_DIR = os.path.join(BASE_DIR, "diag_scripts")
_SH_META_RE = re.compile(r"^#@\s*([A-Za-z_]+)\s*:\s?(.*)$")


def _resolve_scripts_dir(d: Optional[str]) -> str:
    return (d or "").strip() or DEFAULT_SCRIPTS_DIR


def _script_to_sh(s: dict) -> str:
    """把一条脚本序列化成自带 #@ 头的 .sh 文本。tab/分类由目录承载, 不写进头。"""
    def one_line(v):
        return (v or "").replace("\r", "").replace("\n", " ").strip()
    head = [
        f"#@ name: {one_line(s.get('name'))}",
        f"#@ description: {one_line(s.get('description'))}",
        f"#@ target_node_type: {s.get('target_node_type') or 'all'}",
        f"#@ timeout: {s.get('timeout') or 30}",
        f"#@ enabled: {'true' if s.get('enabled', True) else 'false'}",
        f"#@ output_mode: {s.get('output_mode') or 'stdout'}",
        f"#@ expect_mode: {s.get('expect_mode') or 'exit_code'}",
        f"#@ expect_pattern: {one_line(s.get('expect_pattern'))}",
        f"#@ suggestion: {one_line(s.get('suggestion'))}",
        "",
    ]
    body = (s.get("script_content") or "").replace("\r\n", "\n")
    if not body.endswith("\n"):
        body += "\n"
    return "\n".join(head) + body


def _parse_sh(text: str):
    """解析 .sh 文本 → (meta dict, body str)。头部连续的 #@ 行为元数据, 其后为正文。"""
    lines = text.splitlines()
    meta, i = {}, 0
    while i < len(lines):
        m = _SH_META_RE.match(lines[i])
        if not m:
            break
        meta[m.group(1).lower()] = m.group(2).rstrip()
        i += 1
    while i < len(lines) and lines[i].strip() == "":   # 跳过头与正文间的空行
        i += 1
    return meta, "\n".join(lines[i:])


def _sh_to_script(meta: dict, body: str, tab: str, category: str) -> dict:
    def to_int(v, d):
        try: return int(str(v).strip())
        except Exception: return d
    def to_bool(v, d):
        if v is None or v == "": return d
        return str(v).strip().lower() in ("1", "true", "yes", "on", "y")
    return {
        "name": meta.get("name") or "",
        "description": meta.get("description", ""),
        "script_tab": tab,
        "category": category,
        "script_content": body,
        "target_node_type": meta.get("target_node_type") or "all",
        "timeout": to_int(meta.get("timeout"), 30),
        "enabled": to_bool(meta.get("enabled"), True),
        "output_mode": meta.get("output_mode") or "stdout",
        "expect_mode": meta.get("expect_mode") or "exit_code",
        "expect_pattern": meta.get("expect_pattern", ""),
        "suggestion": meta.get("suggestion", ""),
    }


class ScriptsDirRequest(BaseModel):
    dir: Optional[str] = ""          # 空 → BASE_DIR/diag_scripts
    mode: str = "merge"              # 仅导入用: merge=upsert / replace=先清空


@router.post("/scripts/export-dir")
def export_scripts_dir(req: ScriptsDirRequest, db: Session = Depends(get_db)):
    """把全部脚本写成 {dir}/{tab}/{分类}/{名称}.sh 文件树 (每文件带 #@ 头)。"""
    root = _resolve_scripts_dir(req.dir)
    scripts = db.query(DiagScript).order_by(
        DiagScript.script_tab, DiagScript.category, DiagScript.name
    ).all()
    items = _scripts_to_list(scripts)
    used = set()
    count = 0
    for d in items:
        tab = _safe_filename(d["script_tab"] or "hardware")
        cat = _safe_filename(d["category"] or "通用诊断")
        sub = os.path.join(root, tab, cat)
        os.makedirs(sub, exist_ok=True)
        base = _safe_filename(d["name"] or "untitled")
        path = os.path.join(sub, base + ".sh")
        n = 2
        while path in used:               # 同目录同名脚本去重
            path = os.path.join(sub, f"{base}-{n}.sh"); n += 1
        used.add(path)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_script_to_sh(d))
        count += 1
    return {"ok": True, "dir": root, "count": count}


@router.post("/scripts/import-dir")
def import_scripts_dir(req: ScriptsDirRequest, db: Session = Depends(get_db)):
    """扫描 {dir} 下所有 .sh, 按 (tab+分类+名称) upsert。tab/分类优先取目录层级。"""
    root = _resolve_scripts_dir(req.dir)
    if not os.path.isdir(root):
        raise HTTPException(status_code=404, detail=f"目录不存在: {root}")

    found = []
    for dirpath, _dirs, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".sh"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            parts = rel.split("/")
            # tab/分类 由目录层级推断: {tab}/{category}/.../file.sh
            tab = parts[0] if len(parts) >= 2 and parts[0] in KNOWN_TABS else None
            category = parts[-2] if len(parts) >= 3 else None
            try:
                with open(full, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                continue
            meta, body = _parse_sh(text)
            tab = tab or meta.get("tab") or "hardware"
            category = category or meta.get("category") or "通用诊断"
            if not meta.get("name"):
                meta["name"] = os.path.splitext(fn)[0]
            found.append(_sh_to_script(meta, body, tab, category))

    if not found:
        raise HTTPException(status_code=400, detail=f"目录下未找到 .sh 脚本: {root}")

    if req.mode == "replace":
        db.query(DiagScript).delete()
        db.commit()

    created = updated = 0
    for item in found:
        existing = db.query(DiagScript).filter(
            DiagScript.script_tab == item["script_tab"],
            DiagScript.category == item["category"],
            DiagScript.name == item["name"],
        ).first()
        if existing:
            for k, v in item.items():
                setattr(existing, k, v)
            existing.updated_at = datetime.utcnow()
            updated += 1
        else:
            db.add(DiagScript(**item))
            created += 1
    db.commit()
    return {"ok": True, "dir": root, "created": created, "updated": updated,
            "total": created + updated}


class ScriptRunRequest(BaseModel):
    node_ids: List[int] = []           # 从节点管理中选择的节点 ID
    target_ips: List[str] = []         # 直接指定 IP（不依赖节点管理）
    ssh_user: str = "root"
    ssh_password: str = ""
    ssh_port: int = 22
    # 故障定位时间窗 (可选): 脚本可通过 $ALERT_TIME / $ALERT_FROM / $ALERT_TO 引用
    alert_time: Optional[datetime] = None
    range_before_min: int = 0
    range_after_min: int = 0


def _resolve_host(node: Node) -> Optional[str]:
    """SSH 走控制面 (10GE), 优先 ctrl_ip, 兜底 mgmt_ip"""
    return node.ctrl_ip or node.mgmt_ip


def _build_env_prefix(alert_time: Optional[datetime], before_min: int, after_min: int) -> str:
    """根据故障时间窗生成 shell export 前缀, 脚本里可直接读 $ALERT_TIME / $ALERT_FROM / $ALERT_TO"""
    if not alert_time:
        return ""
    before = max(0, int(before_min or 0))
    after  = max(0, int(after_min  or 0))
    t_from = alert_time - timedelta(minutes=before)
    t_to   = alert_time + timedelta(minutes=after)
    # ISO 8601 不带时区, 节点本地时区使用 (journalctl --since / dmesg --since 都吃这个格式)
    fmt = "%Y-%m-%d %H:%M:%S"
    lines = [
        f"export ALERT_TIME={shlex.quote(alert_time.strftime(fmt))}",
        f"export ALERT_FROM={shlex.quote(t_from.strftime(fmt))}",
        f"export ALERT_TO={shlex.quote(t_to.strftime(fmt))}",
        f"export ALERT_BEFORE_MIN={before}",
        f"export ALERT_AFTER_MIN={after}",
        "",
    ]
    return "\n".join(lines)


@router.post("/scripts/{script_id}/run")
async def run_script(script_id: int, req: ScriptRunRequest, db: Session = Depends(get_db)):
    """
    在指定节点上并行执行诊断脚本, 通过 SSE 流式返回每节点结果。

    返回 text/event-stream, 每条事件形如:
      data: {"type":"start","run_id":"...","total":3}\\n\\n
      data: {"type":"result","node_id":1,"hostname":"slave-01",...}\\n\\n
      data: {"type":"end"}\\n\\n

    终止: POST /api/diagnose/scripts/runs/{run_id}/cancel

    密码处理:
      - ssh_password 为空 或 ******** 时, 使用已保存的凭据
      - 非空且非占位符时, 视为新密码, 执行成功后自动保存到 ssh_credentials.json

    告警时间窗:
      - 传入 alert_time + range_before_min/range_after_min 时, 脚本前会插入
        export ALERT_TIME=... ALERT_FROM=... ALERT_TO=..., 脚本可用这些变量
        过滤 journalctl/dmesg 等日志
    """
    script = db.query(DiagScript).filter(DiagScript.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")

    # 节点列表可以为空(纯手动 IP 模式), 校验放到合并 target_ips 之后
    nodes = db.query(Node).filter(Node.id.in_(req.node_ids)).all() if req.node_ids else []

    # 解析密码: 优先用前端传入的明文, 否则用已保存的
    password = cred_service.resolve_password(req.ssh_password)
    if not password:
        raise HTTPException(status_code=400, detail="未提供密码且无已保存凭据")

    # 凭据被首次提供 → 持久化保存(下次自动预填)
    if req.ssh_password and req.ssh_password != cred_service.PWD_MASK:
        try:
            cred_service.save_creds(req.ssh_user, req.ssh_password, req.ssh_port)
        except Exception:
            pass  # 保存失败不影响执行

    # 合并两种来源：DB 节点 + 手动指定 IP
    nodes_snapshot = [(n.id, n.hostname, _resolve_host(n)) for n in nodes]
    for ip in req.target_ips:
        ip = ip.strip()
        if ip:
            nodes_snapshot.append((None, ip, ip))   # id=None，hostname/host 都用 IP
    if not nodes_snapshot:
        raise HTTPException(status_code=400, detail="请选择目标节点或填写目标 IP")
    total = len(nodes_snapshot)

    # 把告警时间窗作为环境变量注入脚本头部
    env_prefix = _build_env_prefix(req.alert_time, req.range_before_min, req.range_after_min)
    script_content = env_prefix + script.script_content
    script_timeout = script.timeout
    ssh_user = req.ssh_user
    ssh_port = req.ssh_port
    # 判定规则快照 (会话内只读, 提前取出避免在线程里碰 ORM 对象)
    expect_mode = script.expect_mode or "exit_code"
    expect_pattern = script.expect_pattern or ""
    suggestion = script.suggestion or ""

    # 注册运行状态用于「终止」
    run_id = uuid.uuid4().hex[:12]
    state = _make_run_state()
    with _RUNS_LOCK:
        _ACTIVE_RUNS[run_id] = state

    def _register_client(c):
        with state["lock"]:
            state["clients"].append(c)

    def _is_cancelled() -> bool:
        return state["cancel"].is_set()

    async def _stream():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _emit(item: dict):
            return f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        yield _emit({
            "type": "start",
            "run_id": run_id,
            "total": total,
            "script_id": script_id,
            "script_name": script.name,
            "alert_time": req.alert_time.isoformat() if req.alert_time else None,
            "alert_window_min": [req.range_before_min, req.range_after_min] if req.alert_time else None,
        })

        async def _run_one(node_id: Optional[int], hostname: str, host: Optional[str]):
            if not host:
                res = {
                    "success": False, "stdout": "",
                    "stderr": "节点未配置控制面 IP (ctrl_ip), 无法 SSH",
                    "exit_code": EXIT_ERROR,
                }
                host = None
            elif _is_cancelled():
                # 终止时尚未排到的节点直接 short-circuit, 不发起连接
                res = {
                    "success": False, "stdout": "",
                    "stderr": "[已取消, 未执行]",
                    "exit_code": EXIT_CANCELLED,
                }
            else:
                try:
                    res = await loop.run_in_executor(
                        _SSH_EXECUTOR,
                        run_ssh_command,
                        host, ssh_port, ssh_user, password,
                        script_content, script_timeout,
                        _is_cancelled, _register_client,
                    )
                except Exception as e:
                    res = {"success": False, "stdout": "", "stderr": str(e), "exit_code": EXIT_ERROR}

            verdict = _evaluate_verdict(res, expect_mode, expect_pattern)
            payload = {
                "type": "result",
                "node_id": node_id, "hostname": hostname, "host": host,
                "verdict": verdict,
                "suggestion": suggestion if verdict == "fail" else "",
                **res,
            }
            await queue.put(payload)

        # 所有节点并发起跑
        for nid, hn, host in nodes_snapshot:
            asyncio.create_task(_run_one(nid, hn, host))

        # 按完成顺序流式返回
        pass_count = fail_count = error_count = 0
        try:
            for _ in range(total):
                item = await queue.get()
                v = item.get("verdict")
                if v == "pass":
                    pass_count += 1
                elif v == "fail":
                    fail_count += 1
                else:
                    error_count += 1
                yield _emit(item)

            yield _emit({
                "type": "end",
                "run_id": run_id,
                "total": total,
                # success 保留为"正常项数", 兼容旧前端
                "success": pass_count,
                "passed": pass_count,
                "failed": fail_count,
                "errored": error_count,
                "cancelled": _is_cancelled(),
            })
        finally:
            with _RUNS_LOCK:
                _ACTIVE_RUNS.pop(run_id, None)

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────
#  一键体检: 一组节点 × 一组脚本 并发执行, 自动判定三态, SSE 汇总
# ─────────────────────────────────────────────

class BatchRunRequest(BaseModel):
    node_ids: List[int] = []
    target_ips: List[str] = []
    ssh_user: str = "root"
    ssh_password: str = ""
    ssh_port: int = 22
    # 脚本选择: script_ids 显式优先; 否则按 script_tab(+可选 category) 取全部启用脚本
    script_ids: List[int] = []
    script_tab: Optional[str] = None       # business / hardware
    category: Optional[str] = None
    alert_time: Optional[datetime] = None
    range_before_min: int = 0
    range_after_min: int = 0


@router.post("/scripts/batch-run")
async def batch_run(req: BatchRunRequest, db: Session = Depends(get_db)):
    """
    一键体检: 把选定的诊断脚本在选定的一组目标上全部跑一遍 (脚本 × 目标 笛卡尔积),
    每个组合并发执行并自动判定 pass/fail/error, 通过 SSE 流式回报, 供前端汇总成体检报告。

    脚本范围:
      - 传 script_ids 时按 id 取 (保留前端顺序)
      - 否则按 script_tab(+category) 取全部 enabled 脚本
      - 一律排除 log_export (那是日志导出, 不参与健康判定)

    节点类型过滤:
      - DB 节点会按脚本 target_node_type 过滤 (master 脚本不会跑到 slave 上)
      - 手动 IP 因为不知道角色, 一律执行
    """
    # ── 解析脚本 ──
    q = db.query(DiagScript).filter(DiagScript.script_tab != "log_export")
    if req.script_ids:
        rows = q.filter(DiagScript.id.in_(req.script_ids)).all()
        by_id = {s.id: s for s in rows}
        scripts = [by_id[i] for i in req.script_ids if i in by_id]
    else:
        if req.script_tab:
            q = q.filter(DiagScript.script_tab == req.script_tab)
        if req.category:
            q = q.filter(DiagScript.category == req.category)
        scripts = q.filter(DiagScript.enabled == True).order_by(
            DiagScript.category, DiagScript.name
        ).all()
    if not scripts:
        raise HTTPException(status_code=400, detail="没有可执行的诊断脚本")

    # ── 解析密码 ──
    password = cred_service.resolve_password(req.ssh_password)
    if not password:
        raise HTTPException(status_code=400, detail="未提供密码且无已保存凭据")
    if req.ssh_password and req.ssh_password != cred_service.PWD_MASK:
        try:
            cred_service.save_creds(req.ssh_user, req.ssh_password, req.ssh_port)
        except Exception:
            pass

    # ── 解析目标 (node_id, hostname, host, node_type) ──
    nodes = db.query(Node).filter(Node.id.in_(req.node_ids)).all() if req.node_ids else []
    targets = [(n.id, n.hostname, _resolve_host(n), n.node_type) for n in nodes]
    for ip in req.target_ips:
        ip = ip.strip()
        if ip:
            targets.append((None, ip, ip, None))
    if not targets:
        raise HTTPException(status_code=400, detail="请选择目标节点或填写目标 IP")

    # ── 脚本快照 + 告警时间窗注入 ──
    env_prefix = _build_env_prefix(req.alert_time, req.range_before_min, req.range_after_min)
    script_snap = [{
        "id": s.id, "name": s.name, "category": s.category,
        "content": env_prefix + s.script_content,
        "timeout": s.timeout,
        "target_node_type": s.target_node_type or "all",
        "expect_mode": s.expect_mode or "exit_code",
        "expect_pattern": s.expect_pattern or "",
        "suggestion": s.suggestion or "",
    } for s in scripts]

    # ── 组装 (脚本 × 目标) 任务对, 按节点类型过滤 ──
    pairs = []
    for t_nid, t_host_name, t_host, t_ntype in targets:
        for sc in script_snap:
            want = sc["target_node_type"]
            if t_ntype is not None and want != "all" and want != t_ntype:
                continue  # master 脚本不下发到 slave
            pairs.append((sc, t_nid, t_host_name, t_host, t_ntype))
    if not pairs:
        raise HTTPException(status_code=400, detail="选定脚本与目标节点类型不匹配, 无可执行项")
    total = len(pairs)

    ssh_user = req.ssh_user
    ssh_port = req.ssh_port

    run_id = uuid.uuid4().hex[:12]
    state = _make_run_state()
    with _RUNS_LOCK:
        _ACTIVE_RUNS[run_id] = state

    def _register_client(c):
        with state["lock"]:
            state["clients"].append(c)

    def _is_cancelled() -> bool:
        return state["cancel"].is_set()

    async def _stream():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _emit(item: dict):
            return f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        yield _emit({
            "type": "start",
            "run_id": run_id,
            "total": total,
            "script_count": len(script_snap),
            "target_count": len(targets),
            "alert_time": req.alert_time.isoformat() if req.alert_time else None,
        })

        async def _run_pair(sc, node_id, hostname, host, ntype):
            if not host:
                res = {"success": False, "stdout": "",
                       "stderr": "节点未配置控制面 IP (ctrl_ip), 无法 SSH",
                       "exit_code": EXIT_ERROR}
                host = None
            elif _is_cancelled():
                res = {"success": False, "stdout": "",
                       "stderr": "[已取消, 未执行]", "exit_code": EXIT_CANCELLED}
            else:
                try:
                    res = await loop.run_in_executor(
                        _SSH_EXECUTOR,
                        run_ssh_command,
                        host, ssh_port, ssh_user, password,
                        sc["content"], sc["timeout"],
                        _is_cancelled, _register_client,
                    )
                except Exception as e:
                    res = {"success": False, "stdout": "", "stderr": str(e),
                           "exit_code": EXIT_ERROR}

            verdict = _evaluate_verdict(res, sc["expect_mode"], sc["expect_pattern"])
            await queue.put({
                "type": "result",
                "script_id": sc["id"], "script_name": sc["name"], "category": sc["category"],
                "node_id": node_id, "hostname": hostname, "host": host,
                "node_type": ntype,
                "verdict": verdict,
                "suggestion": sc["suggestion"] if verdict == "fail" else "",
                **res,
            })

        for sc, nid, hn, host, ntype in pairs:
            asyncio.create_task(_run_pair(sc, nid, hn, host, ntype))

        pass_count = fail_count = error_count = 0
        try:
            for _ in range(total):
                item = await queue.get()
                v = item.get("verdict")
                if v == "pass":
                    pass_count += 1
                elif v == "fail":
                    fail_count += 1
                else:
                    error_count += 1
                yield _emit(item)

            yield _emit({
                "type": "end",
                "run_id": run_id,
                "total": total,
                "passed": pass_count,
                "failed": fail_count,
                "errored": error_count,
                "cancelled": _is_cancelled(),
            })
        finally:
            with _RUNS_LOCK:
                _ACTIVE_RUNS.pop(run_id, None)

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/scripts/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    """终止正在执行的诊断脚本运行: 强关 SSH, 让阻塞的读取立刻退出。"""
    ok = _cancel_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="未找到该运行 (可能已结束)")
    return {"message": "终止信号已发送", "run_id": run_id}


@router.get("/scripts/runs/active")
def list_active_runs():
    """返回当前活跃运行 (调试用)"""
    with _RUNS_LOCK:
        return {"runs": list(_ACTIVE_RUNS.keys())}


class PickFolderRequest(BaseModel):
    initial: str = ""


@router.post("/pick-folder")
def pick_folder(req: PickFolderRequest):
    """
    开发模式用的目录选择对话框 (subprocess 起 tkinter, 避开 FastAPI 线程池里 tk 必须主线程的坑)。
    生产 (pywebview) 模式前端会先尝试 window.pywebview.api.pick_folder(), 走不通才落到这里。
    PyInstaller 冻结模式下 sys.executable 不是 Python 解释器, 不能 -c 启动, 直接 400。
    """
    import sys
    import subprocess
    if getattr(sys, "frozen", False):
        raise HTTPException(
            status_code=400,
            detail="冻结模式请用 window.pywebview.api.pick_folder() 直接走桌面原生对话框",
        )

    initial = (req.initial or "").replace("\\", "/").strip()
    code = (
        "import sys, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        f"p = filedialog.askdirectory(title='选择日志导出目录', initialdir={initial!r})\n"
        "r.destroy()\n"
        "sys.stdout.write(p or '')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="目录选择超时 (10 分钟未确认)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"打开目录对话框失败: {e}")

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"目录对话框子进程失败 (exit={proc.returncode}): {proc.stderr.strip()}",
        )
    path = (proc.stdout or "").strip()
    # 规范化分隔符 (Windows 习惯反斜杠)
    if path and os.name == "nt":
        path = path.replace("/", "\\")
    return {"path": path}


# ─────────────────────────────────────────────
#  日志导出: SSH 到目标, 按脚本采集 stdout 落盘到本地目录
# ─────────────────────────────────────────────

class LogExportRequest(BaseModel):
    target_host: str               # SSH 目标 IP / 主机名
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_password: str = ""         # 空或 ******** → 用已保存凭据
    script_ids: List[int]          # 选中的 log_export 脚本 id (DiagScript.id, script_tab=log_export)
    output_dir: str                # Windows 本地目录, 例如 D:\logs\export
    alert_time: Optional[datetime] = None
    range_before_min: int = 0
    range_after_min: int = 0


def _safe_filename(name: str) -> str:
    """把脚本/分类名规范成安全的文件名片段"""
    cleaned = re.sub(r'[^\w\-_.一-鿿]+', '_', name.strip())
    return cleaned.strip('_') or "untitled"


@router.post("/log-export/run")
async def run_log_export(req: LogExportRequest):
    """
    日志导出: 对单个目标 SSH 顺序执行多个采集脚本, 每个脚本 stdout 落地到一个 .log 文件,
    SSE 流式回报进度。支持 run_id 取消、告警时间窗。

    输出目录结构:
      {output_dir}/{timestamp}/{target_host}/{category}-{name}.log
    """
    if not req.target_host.strip():
        raise HTTPException(status_code=400, detail="请填写目标 IP / 主机名")
    if not req.script_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个采集脚本")
    if not req.output_dir.strip():
        raise HTTPException(status_code=400, detail="请填写输出目录")

    # 解析密码
    password = cred_service.resolve_password(req.ssh_password)
    if not password:
        raise HTTPException(status_code=400, detail="未提供密码且无已保存凭据")
    if req.ssh_password and req.ssh_password != cred_service.PWD_MASK:
        try: cred_service.save_creds(req.ssh_user, req.ssh_password, req.ssh_port)
        except Exception: pass

    # 准备输出根目录: {output_dir}/{YYYYmmdd_HHMMSS}/{target_host}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_safe = _safe_filename(req.target_host)
    out_root = os.path.join(req.output_dir, timestamp, target_safe)
    try:
        os.makedirs(out_root, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建输出目录失败: {e}")

    # 加载选中的脚本(保留前端顺序), 防止 id 不存在
    db_session = SessionLocal()
    try:
        rows = db_session.query(DiagScript).filter(
            DiagScript.id.in_(req.script_ids),
            DiagScript.script_tab == "log_export",
        ).all()
        by_id = {s.id: s for s in rows}
        scripts = [by_id[i] for i in req.script_ids if i in by_id]
    finally:
        db_session.close()
    if not scripts:
        raise HTTPException(status_code=400, detail="选中的脚本不存在 (script_tab 必须为 log_export)")

    env_prefix = _build_env_prefix(req.alert_time, req.range_before_min, req.range_after_min)
    target_host  = req.target_host.strip()
    ssh_user     = req.ssh_user
    ssh_port     = req.ssh_port

    run_id = uuid.uuid4().hex[:12]
    state = _make_run_state()
    with _RUNS_LOCK:
        _ACTIVE_RUNS[run_id] = state

    def _register_client(c):
        with state["lock"]:
            state["clients"].append(c)

    def _is_cancelled() -> bool:
        return state["cancel"].is_set()

    async def _stream():
        loop = asyncio.get_event_loop()

        def _emit(item: dict):
            return f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        yield _emit({
            "type": "start",
            "run_id": run_id,
            "total": len(scripts),
            "target": target_host,
            "output_dir": out_root,
            "alert_time": req.alert_time.isoformat() if req.alert_time else None,
        })

        try:
            for s in scripts:
                if _is_cancelled():
                    yield _emit({
                        "type": "result", "script_id": s.id, "name": s.name,
                        "category": s.category, "mode": s.output_mode or "stdout",
                        "success": False, "exit_code": -3, "file": None, "size": 0,
                        "stderr": "[已取消, 未执行]",
                    })
                    continue

                script_body = env_prefix + s.script_content
                mode = (s.output_mode or "stdout").lower()

                # ── files 模式: SSH 跑脚本得到路径清单, SFTP 完整拉文件 ──────────
                if mode == "files":
                    # 每个 files 脚本一个独立子目录, 避免不同脚本下文件重名互相覆盖
                    script_dir = os.path.join(
                        out_root, f"{_safe_filename(s.category)}-{_safe_filename(s.name)}"
                    )
                    try:
                        res = await loop.run_in_executor(
                            _SSH_EXECUTOR,
                            export_files_via_sftp,
                            target_host, ssh_port, ssh_user, password,
                            script_body, script_dir, s.timeout,
                            _is_cancelled, _register_client,
                        )
                    except Exception as e:
                        res = {"discover_error": str(e), "files": []}

                    if res.get("discover_error"):
                        yield _emit({
                            "type": "result", "script_id": s.id, "name": s.name,
                            "category": s.category, "mode": "files",
                            "success": False, "exit_code": -10,
                            "file": None, "size": 0,
                            "stderr": f"发现阶段失败: {res['discover_error']}",
                        })
                        continue

                    file_list = res.get("files", [])
                    if not file_list:
                        # 没匹配到文件, 也回一条说明
                        yield _emit({
                            "type": "result", "script_id": s.id, "name": s.name,
                            "category": s.category, "mode": "files",
                            "success": True, "exit_code": 0,
                            "file": script_dir, "size": 0,
                            "stderr": "未匹配到任何文件 (脚本输出为空)",
                        })
                    else:
                        for f in file_list:
                            yield _emit({
                                "type": "result", "script_id": s.id, "name": s.name,
                                "category": s.category, "mode": "files",
                                "success": f["success"],
                                "exit_code": 0 if f["success"] else -11,
                                "file": f.get("local"),
                                "remote": f.get("remote"),
                                "size": f.get("size", 0),
                                "stderr": f.get("error") or "",
                                "note": f.get("note"),
                            })
                    continue

                # ── stdout 模式 (默认): 跑脚本, stdout 落一个文件 ────────────────
                try:
                    res = await loop.run_in_executor(
                        _SSH_EXECUTOR,
                        run_ssh_command,
                        target_host, ssh_port, ssh_user, password,
                        script_body, s.timeout,
                        _is_cancelled, _register_client,
                    )
                except Exception as e:
                    res = {"success": False, "stdout": "", "stderr": str(e), "exit_code": -1}

                filename = f"{_safe_filename(s.category)}-{_safe_filename(s.name)}.log"
                fpath = os.path.join(out_root, filename)
                file_size = 0
                file_err: Optional[str] = None
                try:
                    with open(fpath, "w", encoding="utf-8", newline="") as f:
                        f.write(res.get("stdout") or "")
                        if res.get("stderr"):
                            f.write("\n\n=== STDERR ===\n")
                            f.write(res["stderr"])
                    file_size = os.path.getsize(fpath)
                except Exception as e:
                    file_err = str(e)

                yield _emit({
                    "type": "result",
                    "script_id": s.id,
                    "name": s.name,
                    "category": s.category,
                    "mode": "stdout",
                    "success": res.get("success", False) and not file_err,
                    "exit_code": res.get("exit_code", -1),
                    "file": fpath if not file_err else None,
                    "size": file_size,
                    "stderr": file_err or res.get("stderr") or "",
                })

            yield _emit({
                "type": "end",
                "run_id": run_id,
                "output_dir": out_root,
                "cancelled": _is_cancelled(),
            })
        finally:
            with _RUNS_LOCK:
                _ACTIVE_RUNS.pop(run_id, None)

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────
#  SSH 凭据 (持久化, 仅本机存储)
# ─────────────────────────────────────────────

class SSHCredsRequest(BaseModel):
    ssh_user: str = "root"
    ssh_password: str
    ssh_port: int = 22


@router.get("/ssh-creds")
def get_ssh_creds():
    """返回非敏感字段供前端预填; 不返回真实密码"""
    return cred_service.get_public_info()


@router.post("/ssh-creds")
def update_ssh_creds(req: SSHCredsRequest):
    """保存 SSH 凭据。空密码视为清除, ******** 视为不修改"""
    if not req.ssh_password:
        cred_service.clear_creds()
        return {"message": "已清除保存的凭据", "has_saved": False}
    if req.ssh_password == cred_service.PWD_MASK:
        # 仅修改 user/port, 密码保持不变
        existing = cred_service.load_creds() or {}
        cred_service.save_creds(
            req.ssh_user,
            existing.get("ssh_password", ""),
            req.ssh_port,
        )
    else:
        cred_service.save_creds(req.ssh_user, req.ssh_password, req.ssh_port)
    return {"message": "凭据已保存", "has_saved": True}


@router.delete("/ssh-creds")
def delete_ssh_creds():
    cred_service.clear_creds()
    return {"message": "已清除", "has_saved": False}


# ─────────────────────────────────────────────
#  日志查询（按角色+类型+时间段）
# ─────────────────────────────────────────────

# 角色 → node_type 映射
ROLE_TO_NODE_TYPE = {
    "master":        ["master"],
    "slave":         ["slave"],
    "subswath":      ["subswath"],
    "globalstorage": ["globalstorage"],
}

# 日志类型 → log_type 映射
LOG_CATEGORY_MAP = {
    "business": ["dpdk", "rdma", "app"],
    "system":   ["syslog"],
    "kernel":   ["kernel"],
    "network":  ["rdma", "dpdk"],
}

# 示例日志模板（当DB中无真实日志时补充演示数据）
_DEMO_LOG_TEMPLATES = {
    "business": [
        ("info",    "业务流程启动完成"),
        ("info",    "数据帧处理速率: 8500 Mbps"),
        ("warning", "丢包率超过阈值: 0.05%"),
        ("info",    "LT流程初始化完成"),
        ("error",   "PDA数据帧校验失败，重试中"),
    ],
    "system": [
        ("info",    "systemd: Started Cluster Agent Service"),
        ("warning", "kernel: CPU soft lockup detected"),
        ("info",    "sshd: Accepted publickey for root"),
        ("error",   "Out of memory: Kill process"),
    ],
    "kernel": [
        ("info",    "Linux version 5.10.0-136.12.0 (openEuler)"),
        ("warning", "ACPI: IRQ override for 0:6, enabled at level"),
        ("error",   "EDAC MC0: 1 CE error"),
        ("info",    "EXT4-fs: mounted filesystem"),
    ],
    "network": [
        ("info",    "mlx5_core: Link up for port 0"),
        ("warning", "RDMA: CQ overrun detected on port 1"),
        ("info",    "ib0: RoCE link state: ACTIVE"),
        ("error",   "mlx5e: tx timeout on queue"),
    ],
}


class LogQueryRequest(BaseModel):
    roles: List[str]              # master/slave/subswath/globalstorage
    log_types: List[str]          # business/system/kernel/network
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@router.post("/query-logs")
def query_logs_by_role(req: LogQueryRequest, db: Session = Depends(get_db)):
    """
    按角色、日志类型、时间段查询日志。
    先从数据库查询真实记录，不足时补充演示数据。
    """
    if not req.roles or not req.log_types:
        raise HTTPException(status_code=400, detail="请选择角色和日志类型")

    # 确定查询的 node_type 列表
    node_types = []
    for role in req.roles:
        node_types.extend(ROLE_TO_NODE_TYPE.get(role, [role]))

    # 确定查询的 log_type 列表
    db_log_types = []
    for lt in req.log_types:
        db_log_types.extend(LOG_CATEGORY_MAP.get(lt, [lt]))
    db_log_types = list(set(db_log_types))

    # 查询节点
    node_query = db.query(Node)
    if node_types:
        node_query = node_query.filter(Node.node_type.in_(node_types))
    matched_nodes = node_query.all()
    node_ids = [n.id for n in matched_nodes]
    node_map = {n.id: n for n in matched_nodes}

    # 查询 DB 日志
    log_query = db.query(Log)
    if node_ids:
        log_query = log_query.filter(Log.node_id.in_(node_ids))
    if db_log_types:
        log_query = log_query.filter(Log.log_type.in_(db_log_types))
    if req.start_time:
        log_query = log_query.filter(Log.created_at >= req.start_time)
    if req.end_time:
        log_query = log_query.filter(Log.created_at <= req.end_time)
    db_logs = log_query.order_by(Log.created_at.desc()).limit(500).all()

    entries = []
    for log in db_logs:
        node = node_map.get(log.node_id)
        entries.append({
            "id": log.id,
            "timestamp": log.created_at.isoformat() if log.created_at else None,
            "node": node.hostname if node else f"node-{log.node_id}",
            "role": node.node_type if node else "unknown",
            "log_type": log.log_type,
            "level": log.level,
            "message": log.message,
        })

    # 若无真实日志，生成演示条目
    if not entries:
        demo_time = datetime.utcnow()
        import random
        for role in req.roles:
            node_name = f"{role}-demo"
            for lt in req.log_types:
                templates = _DEMO_LOG_TEMPLATES.get(lt, [("info", "日志记录")])
                for level, msg in templates:
                    from datetime import timedelta
                    ts = demo_time - timedelta(minutes=random.randint(0, 60))
                    entries.append({
                        "id": None,
                        "timestamp": ts.isoformat(),
                        "node": node_name,
                        "role": role,
                        "log_type": lt,
                        "level": level,
                        "message": msg,
                    })

    entries.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return {
        "total": len(entries),
        "roles": req.roles,
        "log_types": req.log_types,
        "entries": entries
    }