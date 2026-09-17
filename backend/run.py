#!/usr/bin/env python
"""
集群管理系统启动脚本
"""

import sys
import os

# 确保backend目录在Python路径中
backend_dir = os.path.dirname(os.path.abspath(__file__))
# 同时添加backend的父目录（项目根目录），这样可以从根目录导入backend包
project_root = os.path.dirname(backend_dir)

sys.path.insert(0, project_root)
sys.path.insert(0, backend_dir)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[backend_dir]
    )