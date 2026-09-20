"""
读上传上来的 JSON。

导入模板和导入 nodes.json 共用 —— 现场那些文件都是手改过的, 编码和 BOM 什么
情况都有, 两处按同一套规矩认, 免得一个能读另一个读不了。
"""

import json
from typing import Any


def load_bytes(blob: bytes) -> Any:
    """现场的文件不一定是 UTF-8 —— Windows 上记事本另存为很可能是 GBK"""
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return json.loads(blob.decode(encoding))
        except UnicodeDecodeError:
            continue
        except json.JSONDecodeError as e:
            raise ValueError(f"这不是一份合法的 JSON: 第 {e.lineno} 行 {e.msg}") from e
    raise ValueError("文件编码认不出来, 存成 UTF-8 再试一次")
