"""
固件仓库 API — 管理 NIC / HBA / SSD 等设备固件包

目录结构 (FIRMWARE_DIR):
    firmware/
    ├── manifest.json                          # 匹配规则总清单
    ├── mellanox/ConnectX-5/22.36.1010/fw.bin  # vendor/model/version/file
    ├── huawei/hinic_4x25GE/2.5.0.0/hinic.bin
    └── tools/                                 # 烧写工具 (mstflint / hinicadm 等)
        └── mstflint_aarch64.rpm

节点 firstboot 阶段:
    1. curl /firmware/manifest.json
    2. lspci -nn -> vendor_id:device_id 匹配 rules[]
    3. 比对当前 FW 版本, 不一致则 curl 拉镜像
    4. 执行 flash_cmd, 回报 POST /api/pxe/report
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from config import FIRMWARE_DIR

router = APIRouter()
log = logging.getLogger("firmware")

MANIFEST_PATH = Path(FIRMWARE_DIR) / "manifest.json"
_SAFE_SEG_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _safe_segment(s: str, field: str) -> str:
    s = (s or "").strip()
    if not s or not _SAFE_SEG_RE.match(s):
        raise HTTPException(status_code=400, detail=f"非法 {field}: 仅允许字母/数字/._-")
    if s.startswith(".") or ".." in s:
        raise HTTPException(status_code=400, detail=f"非法 {field}: 禁止 . 或 ..")
    return s


def _read_manifest() -> Dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"version": "", "updated_at": "", "rules": []}
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.exception(f"读取 manifest 失败: {e}")
        return {"version": "", "updated_at": "", "rules": [], "error": str(e)}


def _write_manifest(data: Dict[str, Any]) -> None:
    data["updated_at"] = datetime.utcnow().isoformat() + "Z"
    if not data.get("version"):
        data["version"] = data["updated_at"]
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 列表 ──────────────────────────────────────────────────────────────────────

@router.get("/list")
def list_firmware():
    """
    扫描 FIRMWARE_DIR, 返回所有 vendor/model/version/file 三层目录下的固件文件。
    每个固件附带 SHA256 (若存在 .sha256 旁文件) 和 manifest 中是否引用。
    """
    root = Path(FIRMWARE_DIR)
    manifest = _read_manifest()
    referenced = {r.get("image", "") for r in manifest.get("rules", [])}

    items: List[Dict[str, Any]] = []
    if not root.exists():
        return {"firmware_dir": str(root), "items": items}

    for vendor_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "tools"):
        for model_dir in sorted(p for p in vendor_dir.iterdir() if p.is_dir()):
            for ver_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
                for f in sorted(p for p in ver_dir.iterdir() if p.is_file() and not p.name.endswith(".sha256")):
                    rel = f.relative_to(root).as_posix()
                    sha_file = f.with_suffix(f.suffix + ".sha256")
                    sha = ""
                    if sha_file.exists():
                        try:
                            sha = sha_file.read_text(encoding="utf-8").strip().split()[0]
                        except Exception:
                            sha = ""
                    items.append({
                        "vendor":   vendor_dir.name,
                        "model":    model_dir.name,
                        "version":  ver_dir.name,
                        "filename": f.name,
                        "rel_path": rel,
                        "size_mb":  round(f.stat().st_size / (1024 * 1024), 2),
                        "sha256":   sha,
                        "referenced_by_manifest": rel in referenced,
                    })
    return {"firmware_dir": str(root), "items": items}


@router.get("/tools")
def list_tools():
    """列出 tools/ 子目录下的烧写工具(mstflint / hinicadm 等)"""
    tools_dir = Path(FIRMWARE_DIR) / "tools"
    if not tools_dir.exists():
        return {"items": []}
    items = []
    for f in sorted(tools_dir.iterdir()):
        if f.is_file():
            items.append({
                "filename": f.name,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "rel_path": f"tools/{f.name}",
            })
    return {"items": items}


# ── 上传 ──────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_firmware(
    vendor:  str = Form(..., description="厂商目录, 如 mellanox/huawei/intel"),
    model:   str = Form(..., description="设备型号, 如 ConnectX-5"),
    version: str = Form(..., description="固件版本, 如 22.36.1010"),
    file:    UploadFile = File(...),
):
    """上传固件文件到 firmware/{vendor}/{model}/{version}/{filename}"""
    v = _safe_segment(vendor,  "vendor")
    m = _safe_segment(model,   "model")
    ver = _safe_segment(version, "version")
    fname = _safe_segment(file.filename or "fw.bin", "filename")

    dest_dir = Path(FIRMWARE_DIR) / v / m / ver
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / fname

    written = 0
    h = hashlib.sha256()
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            written += len(chunk)

    sha = h.hexdigest()
    sha_file = dest.with_suffix(dest.suffix + ".sha256")
    sha_file.write_text(f"{sha}  {fname}\n", encoding="utf-8")

    rel = dest.relative_to(Path(FIRMWARE_DIR)).as_posix()
    return {
        "ok": True,
        "rel_path": rel,
        "size_bytes": written,
        "sha256": sha,
    }


@router.post("/upload-tool")
async def upload_tool(file: UploadFile = File(...)):
    """上传烧写工具(rpm / 二进制)到 firmware/tools/"""
    fname = _safe_segment(file.filename or "tool", "filename")
    dest_dir = Path(FIRMWARE_DIR) / "tools"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / fname
    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            written += len(chunk)
    return {"ok": True, "rel_path": f"tools/{fname}", "size_bytes": written}


# ── 删除 ──────────────────────────────────────────────────────────────────────

class DeleteRequest(BaseModel):
    rel_path: str


@router.delete("/file")
def delete_firmware(rel_path: str):
    """
    删除 firmware/{rel_path} 单个文件。
    rel_path 必须落在 FIRMWARE_DIR 内, 且不会触碰 manifest.json。
    """
    if not rel_path or rel_path == "manifest.json":
        raise HTTPException(status_code=400, detail="非法路径")
    root = Path(FIRMWARE_DIR).resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径越界")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {rel_path}")

    target.unlink()
    sha = target.with_suffix(target.suffix + ".sha256")
    if sha.exists():
        sha.unlink()

    # 顺手清空向上的空目录(到 FIRMWARE_DIR 为止)
    parent = target.parent
    while parent != root and parent.exists() and not any(parent.iterdir()):
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent

    return {"ok": True, "deleted": rel_path}


# ── manifest ──────────────────────────────────────────────────────────────────

class ManifestRule(BaseModel):
    match_vendor_id: str            # 4 位 16 进制, 如 "15b3"
    match_device_id: str            # 4 位 16 进制, 如 "1019"
    name: str                       # 给人看的名字, 如 "Mellanox ConnectX-5"
    target_fw: str                  # 目标版本, 如 "22.36.1010"
    image: str                      # rel_path, 如 "mellanox/ConnectX-5/22.36.1010/fw.bin"
    tool: str = "mstflint"          # 烧写工具名
    flash_cmd: str                  # 烧写命令模板, 支持 {pci} {ifname} {image}
    query_cmd: str                  # 查询当前版本命令模板
    post_action: str = "cold_reboot"  # cold_reboot / warm_reboot / none
    enabled: bool = True


class ManifestSave(BaseModel):
    version: Optional[str] = None
    rules: List[ManifestRule]


@router.get("/manifest")
def get_manifest():
    """读取固件匹配规则清单(供节点 firstboot 直接 curl 的端点)"""
    return _read_manifest()


@router.get("/manifest.json", response_class=PlainTextResponse)
def get_manifest_plain():
    """
    节点 firstboot 直接拉的入口:
        curl http://<pxe-host>/firmware/manifest.json
    返回与 GET /manifest 同样的 JSON, 仅 Content-Type 不同。
    注意: 节点真正运行时也可直接走静态挂载 /firmware/manifest.json,
          这里多保留一份 API 便于在 Windows 管理机本地调试。
    """
    if not MANIFEST_PATH.exists():
        return '{"version":"","rules":[]}'
    return MANIFEST_PATH.read_text(encoding="utf-8")


@router.put("/manifest")
def save_manifest(body: ManifestSave):
    """整体覆盖保存固件匹配规则清单。"""
    root = Path(FIRMWARE_DIR)
    rules: List[Dict[str, Any]] = []
    for r in body.rules:
        # 校验 image 必须存在
        img_path = (root / r.image).resolve()
        try:
            img_path.relative_to(root.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"image 越界: {r.image}")
        if not img_path.exists():
            raise HTTPException(status_code=400, detail=f"image 不存在: {r.image}")

        rules.append({
            "match":       {"vendor_id": r.match_vendor_id.lower(), "device_id": r.match_device_id.lower()},
            "name":        r.name,
            "target_fw":   r.target_fw,
            "image":       r.image,
            "tool":        r.tool,
            "flash_cmd":   r.flash_cmd,
            "query_cmd":   r.query_cmd,
            "post_action": r.post_action,
            "enabled":     r.enabled,
        })
    data = {"version": body.version or "", "rules": rules}
    _write_manifest(data)
    return {"ok": True, "rule_count": len(rules), "manifest": _read_manifest()}
