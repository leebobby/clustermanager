"""
节点数据模型 - 支持三平面网络信息
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class Node(Base):
    """节点表 - 包含三平面网络信息"""
    __tablename__ = 'nodes'

    id = Column(Integer, primary_key=True)
    hostname = Column(String(100), unique=True)
    node_type = Column(String(20))  # master/slave/sensor
    role = Column(String(50))

    # 管理面 (GE口)
    mgmt_ip = Column(String(45))
    mgmt_mac = Column(String(17))
    bmc_ip = Column(String(45))
    bmc_mac = Column(String(17))

    # 控制面 (10GE)
    ctrl_ip = Column(String(45))
    ctrl_mac = Column(String(17))
    ctrl_status = Column(String(20), default='offline')

    # 数据面 (100GE)
    data_ip = Column(String(45))
    data_mac = Column(String(17))
    data_status = Column(String(20), default='offline')
    data_protocol = Column(String(20))  # DPDK/RDMA

    # 整体状态
    status = Column(String(20), default='offline')
    os_version = Column(String(50))
    cpu_cores = Column(Integer)
    memory_gb = Column(Integer)
    disk_gb = Column(Integer)

    # NIC / HBA / SSD 等设备的固件版本快照,由 firstboot 阶段刷固件后回报
    # 形如 [{"pci":"0000:01:00.0","name":"ConnectX-5","from":"22.35.4030","to":"22.36.1010","at":"..."}]
    nic_firmware = Column(JSON)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime)
    last_mgmt_seen = Column(DateTime)
    last_ctrl_seen = Column(DateTime)
    last_data_seen = Column(DateTime)


class NetworkLink(Base):
    """网络链路表 - 记录平面间连接"""
    __tablename__ = 'network_links'

    id = Column(Integer, primary_key=True)
    source_node_id = Column(Integer)
    target_node_id = Column(Integer)
    plane = Column(String(20))  # management/control/data_front/data_back
    protocol = Column(String(20))  # IPMI/TCP/DPDK/RDMA
    bandwidth = Column(String(20))  # GE/10GE/100GE
    status = Column(String(20), default='normal')
    latency_ms = Column(Float)
    packet_loss_rate = Column(Float)
    throughput_mbps = Column(Float)
    last_check = Column(DateTime)


class BMCInfo(Base):
    """BMC信息表"""
    __tablename__ = 'bmc_info'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer)
    bmc_model = Column(String(50))
    bmc_version = Column(String(50))
    power_status = Column(String(20))
    temperature = Column(Integer)
    fan_speed = Column(Integer)
    last_update = Column(DateTime, default=datetime.utcnow)


class Alert(Base):
    """告警表 - 区分平面"""
    __tablename__ = 'alerts'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer)
    link_id = Column(Integer)
    plane = Column(String(20))  # 管理面/控制面/数据面
    alert_type = Column(String(50))
    severity = Column(String(20))  # critical/warning/info
    message = Column(Text)
    status = Column(String(20), default='active')
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)


class PatrolRecord(Base):
    """巡检记录表 - 区分平面"""
    __tablename__ = 'patrol_records'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer)
    patrol_type = Column(String(50))
    plane = Column(String(20))  # 管理面/控制面/数据面/all
    result = Column(String(20))  # pass/fail
    details = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class Log(Base):
    """日志表"""
    __tablename__ = 'logs'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer)
    log_type = Column(String(30))  # syslog/kernel/dpdk/rdma/bmc
    level = Column(String(10))
    message = Column(Text)
    raw_content = Column(Text)
    collected_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class FaultPoint(Base):
    """故障点表"""
    __tablename__ = 'fault_points'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer)
    link_id = Column(Integer)
    plane = Column(String(20))
    fault_type = Column(String(50))
    description = Column(Text)
    severity = Column(String(20))
    related_logs = Column(JSON)
    suggestions = Column(Text)
    status = Column(String(20), default='active')
    created_at = Column(DateTime, default=datetime.utcnow)


class DPDKStats(Base):
    """DPDK统计表 - Master节点"""
    __tablename__ = 'dpdk_stats'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer)
    rx_packets = Column(Integer)
    rx_bytes = Column(Integer)
    rx_dropped = Column(Integer)
    rx_errors = Column(Integer)
    throughput_mbps = Column(Float)
    collection_time = Column(DateTime, default=datetime.utcnow)


class RDMAStats(Base):
    """RDMA统计表 - Slave节点"""
    __tablename__ = 'rdma_stats'

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer)
    tx_packets = Column(Integer)
    tx_bytes = Column(Integer)
    tx_dropped = Column(Integer)
    tx_errors = Column(Integer)
    throughput_mbps = Column(Float)
    collection_time = Column(DateTime, default=datetime.utcnow)


class PXEConfig(Base):
    """PXE配置表"""
    __tablename__ = 'pxe_config'

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    mgmt_subnet = Column(String(50))
    ctrl_subnet = Column(String(50))
    data_subnet = Column(String(50))
    mgmt_gateway = Column(String(45))
    ctrl_gateway = Column(String(45))
    data_gateway = Column(String(45))
    dns_servers = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)


class DiagScript(Base):
    """诊断脚本配置表 - 支持分类管理和SSH远程执行"""
    __tablename__ = 'diag_scripts'

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    description = Column(Text, default='')
    script_tab = Column(String(20), default='hardware')   # business / hardware / log_export
    category = Column(String(50), default='通用诊断')
    script_content = Column(Text)           # SSH命令或脚本内容
    target_node_type = Column(String(20), default='all')  # all/master/slave/sensor
    timeout = Column(Integer, default=30)   # 超时秒数
    enabled = Column(Boolean, default=True)
    # 日志导出场景: stdout = 脚本 stdout 落成一个文件 (默认);
    #              files  = 脚本 stdout 是一行一个的远端绝对路径, 后端 SFTP 全文件下载
    # business/hardware 类型脚本固定 stdout 即可, 不会被读到
    output_mode = Column(String(20), default='stdout')

    # 结果判定规则 (business/hardware 诊断用, 把"跑命令"升级成"判结论"):
    #   exit_code      : 仅看退出码, 0=正常 否则=异常 (默认, 兼容旧行为)
    #   fault_if_match : stdout/stderr 命中 expect_pattern(正则) → 异常, 否则正常
    #                    例: error|fail|panic, 命中即判故障
    #   pass_if_match  : 命中 expect_pattern → 正常, 否则异常
    #                    例: 期望出现 'active (running)', 没出现即异常
    expect_mode = Column(String(20), default='exit_code')
    expect_pattern = Column(Text, default='')
    # 判异常时给运维看的处置建议 (一键体检报告里异常项直接展示)
    suggestion = Column(Text, default='')

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


# 数据库连接（路径兼容 PyInstaller 打包后运行）
from config import DATABASE_PATH
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化数据库"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()