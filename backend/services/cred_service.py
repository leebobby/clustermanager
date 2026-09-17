"""
SSH 凭据持久化 — 保存在 BASE_DIR/ssh_credentials.json
"""

import json
import os
from typing import Optional, Dict
from config import BASE_DIR

CRED_PATH = os.path.join(BASE_DIR, "ssh_credentials.json")
PWD_MASK = "********"


def load_creds() -> Optional[Dict]:
    """读取已保存的凭据；返回 None 表示尚未保存"""
    if not os.path.exists(CRED_PATH):
        return None
    try:
        with open(CRED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_creds(ssh_user: str, ssh_password: str, ssh_port: int = 22) -> None:
    """写入凭据；调用方应在密码非占位符 (********) 时再调用"""
    data = {
        "ssh_user": ssh_user,
        "ssh_password": ssh_password,
        "ssh_port": int(ssh_port or 22),
    }
    with open(CRED_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clear_creds() -> None:
    """清除已保存的凭据"""
    if os.path.exists(CRED_PATH):
        try:
            os.remove(CRED_PATH)
        except Exception:
            pass


def get_public_info() -> Dict:
    """返回给前端预填的非敏感信息(密码字段用 ******** 占位)"""
    creds = load_creds()
    if not creds:
        return {"has_saved": False, "ssh_user": "root", "ssh_port": 22}
    return {
        "has_saved": True,
        "ssh_user": creds.get("ssh_user", "root"),
        "ssh_port": creds.get("ssh_port", 22),
    }


def resolve_password(provided: Optional[str]) -> Optional[str]:
    """
    根据前端传入的密码值解析为真实密码:
      - 空 / None / ******** → 使用已保存的密码
      - 其它字符串           → 视为新密码, 原样返回
    返回 None 表示既未提供也无已保存
    """
    if provided and provided != PWD_MASK:
        return provided
    saved = load_creds()
    if saved and saved.get("ssh_password"):
        return saved["ssh_password"]
    return None
