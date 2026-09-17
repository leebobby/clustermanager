# 集群管理系统启动指南

## 系统要求
- Python 3.8+
- Node.js 18+
- npm 或 yarn

## 快速启动

### 1. 启动后端

```bash
# 进入backend目录
cd D:\01.code\00.AIstudy\AIstudyForLee\clustermanager\backend

# 安装依赖
pip install -r requirements.txt

# 启动服务（方式1）
python run.py

# 启动服务（方式2）
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

后端启动后会自动：
- 初始化数据库
- 生成演示数据（1 Master + 5 Slave + 1 传感器）

### 2. 启动前端

```bash
# 进入frontend目录
cd D:\01.code\00.AIstudy\AIstudyForLee\clustermanager\frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端访问地址: http://localhost:3000

### 3. 访问API文档

后端启动后访问 Swagger文档: http://localhost:8000/docs

## 功能验证

### 组网图功能
1. 启动后端和前端后，访问 http://localhost:3000
2. 点击左侧菜单 "组网图"
3. 应看到三平面网络拓扑图：
   - 管理站节点（虚拟）
   - 1个Master节点
   - 5个Slave节点
   - 1个传感器节点
4. 可切换不同平面视图查看

### 其他功能
- **仪表盘**: 三平面状态概览
- **PXE部署**: BMC录入、节点部署、终端登录
- **节点管理**: 节点列表、电源控制
- **告警中心**: 告警查看和处理
- **巡检管理**: 执行巡检任务
- **故障诊断**: 日志查询、故障分析

## 常见问题

### Q: 后端启动报错 ModuleNotFoundError
确保在 backend 目录下启动，或使用 `python run.py`

### Q: 前端组网图空白
1. 确认后端已启动并生成演示数据
2. 检查浏览器控制台是否有API错误
3. 刷新页面重新加载

### Q: D3.js加载失败
确保执行了 `npm install` 安装了 d3 依赖
