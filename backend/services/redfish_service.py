"""
Redfish 客户端 — PXE Host 自部署使用 BMC 虚拟介质 + 一次性引导。

典型流程（华为 iBMC / Dell iDRAC / 标准 DMTF Redfish 一致）：
  1. POST  Managers/<mgr>/VirtualMedia/<media>/Actions/VirtualMedia.InsertMedia
           body: { "Image": "http://<windows>:<port>/iso/xxx.iso", "Inserted": true }
  2. PATCH Systems/<sys>
           body: { "Boot": { "BootSourceOverrideTarget": "Cd",
                             "BootSourceOverrideEnabled": "Once" } }
  3. POST  Systems/<sys>/Actions/ComputerSystem.Reset
           body: { "ResetType": "ForceRestart" }
"""

from typing import Dict, Any, Optional
import httpx


class RedfishClient:
    def __init__(
        self,
        bmc_ip: str,
        username: str,
        password: str,
        manager_id: str = "1",
        system_id: str = "1",
        virtual_media_id: str = "CD",
        verify_tls: bool = False,
        timeout: float = 20.0,
    ):
        self.base = f"https://{bmc_ip}"
        self.auth = (username, password)
        self.manager_id = manager_id
        self.system_id = system_id
        self.virtual_media_id = virtual_media_id
        self.verify_tls = verify_tls
        self.timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(
            verify=self.verify_tls,
            auth=self.auth,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )

    # ── 单步操作 ─────────────────────────────────────────────────────────────

    def insert_media(self, image_url: str) -> Dict[str, Any]:
        """挂载远程 ISO。Image 必须为 BMC 可访问的 HTTP/HTTPS URL。"""
        url = (
            f"{self.base}/redfish/v1/Managers/{self.manager_id}"
            f"/VirtualMedia/{self.virtual_media_id}"
            f"/Actions/VirtualMedia.InsertMedia"
        )
        payload = {"Image": image_url, "Inserted": True, "WriteProtected": True}
        with self._client() as c:
            r = c.post(url, json=payload)
        return {"status_code": r.status_code, "body": _safe_body(r)}

    def eject_media(self) -> Dict[str, Any]:
        url = (
            f"{self.base}/redfish/v1/Managers/{self.manager_id}"
            f"/VirtualMedia/{self.virtual_media_id}"
            f"/Actions/VirtualMedia.EjectMedia"
        )
        with self._client() as c:
            r = c.post(url, json={})
        return {"status_code": r.status_code, "body": _safe_body(r)}

    def set_boot_once_cd(self) -> Dict[str, Any]:
        """设置一次性 CD/DVD 引导（下次启动后恢复默认顺序）。"""
        url = f"{self.base}/redfish/v1/Systems/{self.system_id}"
        payload = {
            "Boot": {
                "BootSourceOverrideTarget": "Cd",
                "BootSourceOverrideEnabled": "Once",
                "BootSourceOverrideMode": "UEFI",
            }
        }
        with self._client() as c:
            r = c.patch(url, json=payload)
        return {"status_code": r.status_code, "body": _safe_body(r)}

    def reset(self, reset_type: str = "ForceRestart") -> Dict[str, Any]:
        url = (
            f"{self.base}/redfish/v1/Systems/{self.system_id}"
            f"/Actions/ComputerSystem.Reset"
        )
        with self._client() as c:
            r = c.post(url, json={"ResetType": reset_type})
        return {"status_code": r.status_code, "body": _safe_body(r)}

    def get_power_state(self) -> Optional[str]:
        url = f"{self.base}/redfish/v1/Systems/{self.system_id}"
        try:
            with self._client() as c:
                r = c.get(url)
            return r.json().get("PowerState")
        except Exception:
            return None

    # ── 一键部署：挂介质 → 切引导 → 重启 ────────────────────────────────────

    def deploy_iso(self, image_url: str) -> Dict[str, Any]:
        """完整 PXE Host 部署流程，任一步失败即中止并返回详情。"""
        steps = []

        try:
            steps.append({"step": "eject_media", **self.eject_media()})
        except Exception as exc:
            steps.append({"step": "eject_media", "error": str(exc)})

        try:
            res = self.insert_media(image_url)
            steps.append({"step": "insert_media", **res})
            if res["status_code"] >= 400:
                return {"ok": False, "stage": "insert_media", "steps": steps}
        except Exception as exc:
            steps.append({"step": "insert_media", "error": str(exc)})
            return {"ok": False, "stage": "insert_media", "steps": steps}

        try:
            res = self.set_boot_once_cd()
            steps.append({"step": "set_boot_once_cd", **res})
            if res["status_code"] >= 400:
                return {"ok": False, "stage": "set_boot_once_cd", "steps": steps}
        except Exception as exc:
            steps.append({"step": "set_boot_once_cd", "error": str(exc)})
            return {"ok": False, "stage": "set_boot_once_cd", "steps": steps}

        try:
            res = self.reset("ForceRestart")
            steps.append({"step": "reset", **res})
            if res["status_code"] >= 400:
                return {"ok": False, "stage": "reset", "steps": steps}
        except Exception as exc:
            steps.append({"step": "reset", "error": str(exc)})
            return {"ok": False, "stage": "reset", "steps": steps}

        return {"ok": True, "stage": "completed", "steps": steps}


def _safe_body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        text = resp.text or ""
        return text[:500] if text else None
