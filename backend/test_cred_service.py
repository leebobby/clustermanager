"""诊断 SSH 默认凭据与页面保存凭据的优先级测试（不依赖 pytest）。"""

import json
import os
import tempfile
from unittest import mock

from services import cred_service


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        config_path = os.path.join(td, "cluster_manager_config.json")
        saved_path = os.path.join(td, "ssh_credentials.json")
        with mock.patch.object(cred_service, "APP_CONFIG_PATH", config_path), \
             mock.patch.object(cred_service, "CRED_PATH", saved_path):
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"diagnose": {
                    "ssh_user": "operator",
                    "ssh_password": "config-secret",
                    "ssh_port": 2222,
                }}, f)

            public = cred_service.get_public_info()
            assert public == {"has_saved": True, "ssh_user": "operator", "ssh_port": 2222}
            assert cred_service.resolve_password("") == "config-secret"
            assert cred_service.resolve_password(cred_service.PWD_MASK) == "config-secret"

            cred_service.save_creds("root", "saved-secret", 22)
            assert cred_service.resolve_password("") == "saved-secret"
            assert cred_service.get_public_info()["ssh_user"] == "root"

            cred_service.clear_creds()
            assert cred_service.resolve_password("") == "config-secret"

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"diagnose": {"ssh_password": ""}}, f)
            assert cred_service.resolve_password("") is None
            assert cred_service.get_public_info()["has_saved"] is False

    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
