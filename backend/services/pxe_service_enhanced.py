"""
优化后的 PXE 配置服务 - 增强版
包含文件生成、验证和错误处理
"""

import os
import shutil
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
import re
import subprocess


# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PXEServiceEnhanced:
    """优化后的PXE部署配置服务"""

    def __init__(
        self,
        tftp_dir: str = "/tftpboot",
        dhcp_conf: str = "/etc/dhcp/dhcpd.conf",
        ks_dir: str = "/tftpboot/ks",
        pxe_cfg_dir: str = "/tftpboot/pxelinux.cfg",
        http_server: str = "192.168.1.10",
        http_port: int = 8000,
        log_dir: str = "/var/log/pxe"
    ):
        self.tftp_dir = tftp_dir
        self.dhcp_conf = dhcp_conf
        self.ks_dir = ks_dir
        self.pxe_cfg_dir = pxe_cfg_dir
        self.http_server = http_server
        self.http_port = http_port
        self.log_dir = log_dir

        # 创建必要目录
        Path(self.ks_dir).mkdir(parents=True, exist_ok=True)
        Path(self.pxe_cfg_dir).mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)

    def _log(self, level: int, msg: str):
        """记录日志到文件和控制台"""
        logger.log(level, msg)
        log_file = f"{self.log_dir}/pxe-{datetime.now().strftime('%Y%m%d')}.log"
        with open(log_file, 'a') as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] [{logging.getLevelName(level)}] {msg}\n")

    def _validate_ip(self, ip: str) -> bool:
        """验证IP地址格式"""
        pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if not re.match(pattern, ip):
            return False
        parts = ip.split('.')
        return all(0 <= int(p) <= 255 for p in parts)

    def _validate_mac(self, mac: str) -> bool:
        """验证MAC地址格式"""
        pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$'
        return bool(re.match(pattern, mac))

    def _validate_hostname(self, hostname: str) -> bool:
        """验证主机名格式"""
        pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$'
        return bool(re.match(pattern, hostname)) and len(hostname) <= 63

    def _render_template(
        self,
        template: str,
        variables: Dict[str, str]
    ) -> Tuple[str, List[str]]:
        """
        渲染Kickstart模板
        返回: (rendered_content, missing_variables)
        """
        rendered = template
        missing = []

        # 查找所有{{VARIABLE}}形式的变量
        pattern = r'\{\{(\w+)\}\}'
        variables_found = set(re.findall(pattern, template))

        # 替换变量
        for var_name in variables_found:
            if var_name in variables:
                value = variables[var_name]
                # 转义特殊字符
                value = str(value).replace('\\', '\\\\').replace('"', '\\"')
                rendered = rendered.replace(f'{{{{{var_name}}}}}', value)
            else:
                missing.append(var_name)

        return rendered, missing

    def generate_kickstart(
        self,
        node_type: str,
        hostname: str,
        mgmt_ip: str,
        ctrl_ip: str,
        data_ip: str,
        mgmt_gateway: str = "192.168.1.1",
        ctrl_gateway: str = "10.0.0.1",
        data_gateway: str = "192.168.100.1",
        mgmt_netmask: str = "255.255.255.0",
        ctrl_netmask: str = "255.255.255.0",
        data_netmask: str = "255.255.255.0",
        root_password: str = "openEuler@2024",
        dns_servers: str = "8.8.8.8,8.8.4.4"
    ) -> Dict:
        """
        生成Kickstart配置文件

        返回:
        {
            "success": bool,
            "content": str,           # Kickstart内容
            "file_path": str,         # 保存的文件路径
            "url": str,               # HTTP访问URL
            "errors": List[str]       # 验证错误
        }
        """
        errors = []

        # ====== 参数验证 ======
        # 验证节点类型
        if node_type not in ['master', 'slave']:
            errors.append(f"节点类型必须是 'master' 或 'slave', 实际: {node_type}")

        # 验证主机名
        if not self._validate_hostname(hostname):
            errors.append(f"主机名无效: {hostname}")

        # 验证IP地址
        for ip_addr, ip_name in [
            (mgmt_ip, "mgmt_ip"),
            (ctrl_ip, "ctrl_ip"),
            (data_ip, "data_ip"),
            (mgmt_gateway, "mgmt_gateway"),
            (ctrl_gateway, "ctrl_gateway"),
            (data_gateway, "data_gateway")
        ]:
            if not self._validate_ip(ip_addr):
                errors.append(f"IP地址无效 ({ip_name}): {ip_addr}")

        # 检查IP不重复
        ips = [mgmt_ip, ctrl_ip, data_ip]
        if len(ips) != len(set(ips)):
            errors.append("三个IP地址不能相同")

        if errors:
            return {
                "success": False,
                "errors": errors,
                "content": None,
                "file_path": None,
                "url": None
            }

        # ====== 选择模板 ======
        ks_template = self._get_template(node_type)

        # ====== 准备变量 ======
        variables = {
            "HOSTNAME": hostname,
            "MGMT_IP": mgmt_ip,
            "MGMT_NETMASK": mgmt_netmask,
            "MGMT_GATEWAY": mgmt_gateway,
            "CTRL_IP": ctrl_ip,
            "CTRL_NETMASK": ctrl_netmask,
            "CTRL_GATEWAY": ctrl_gateway,
            "DATA_IP": data_ip,
            "DATA_NETMASK": data_netmask,
            "DATA_GATEWAY": data_gateway,
            "ROOT_PASSWORD": root_password,
            "DNS_SERVERS": dns_servers,
            "PXE_SERVER": self.http_server,
            "MASTER_DATA_IP": "192.168.100.101"  # Slave节点需要Master IP
        }

        # ====== 渲染模板 ======
        rendered_ks, missing_vars = self._render_template(ks_template, variables)

        if missing_vars:
            errors.append(f"缺少模板变量: {', '.join(missing_vars)}")
            return {
                "success": False,
                "errors": errors,
                "content": rendered_ks,
                "file_path": None,
                "url": None
            }

        # ====== 验证Kickstart语法 ======
        ks_errors = self._validate_kickstart(rendered_ks)
        if ks_errors:
            errors.extend(ks_errors)
            return {
                "success": False,
                "errors": errors,
                "content": rendered_ks,
                "file_path": None,
                "url": None
            }

        # ====== 保存文件 ======
        try:
            file_path = self._save_kickstart_file(hostname, rendered_ks)
            url = f"http://{self.http_server}:{self.http_port}/ks/{hostname}.ks"

            self._log(
                logging.INFO,
                f"成功生成Kickstart配置: {hostname} ({node_type}) -> {file_path}"
            )

            return {
                "success": True,
                "errors": [],
                "content": rendered_ks,
                "file_path": file_path,
                "url": url
            }
        except Exception as e:
            error_msg = f"保存Kickstart文件失败: {str(e)}"
            self._log(logging.ERROR, error_msg)
            errors.append(error_msg)
            return {
                "success": False,
                "errors": errors,
                "content": rendered_ks,
                "file_path": None,
                "url": None
            }

    def _get_template(self, node_type: str) -> str:
        """获取对应节点类型的Kickstart模板"""
        if node_type == "master":
            return MASTER_KS_TEMPLATE
        else:
            return SLAVE_KS_TEMPLATE

    def _validate_kickstart(self, ks_content: str) -> List[str]:
        """验证Kickstart配置的基本语法"""
        errors = []

        # 检查必需字段
        required_fields = [
            ('lang ', '语言配置'),
            ('keyboard ', '键盘配置'),
            ('network --device=eth0', '管理面网络配置'),
            ('network --device=eth1', '控制面网络配置'),
            ('network --device=eth2', '数据面网络配置'),
            ('%packages', '软件包配置'),
            ('%post', '后置脚本')
        ]

        for field, desc in required_fields:
            if field not in ks_content:
                errors.append(f"缺少 {desc}: 未找到 '{field}'")

        # 检查配置完整性
        if '%packages' in ks_content:
            if '%end' not in ks_content.split('%packages')[1]:
                errors.append("%packages 块缺少 %end 结尾")

        return errors

    def _save_kickstart_file(self, hostname: str, content: str) -> str:
        """保存Kickstart文件到TFTP目录"""
        file_path = f"{self.ks_dir}/{hostname}.ks"

        try:
            with open(file_path, 'w') as f:
                f.write(content)
            os.chmod(file_path, 0o644)
            return file_path
        except Exception as e:
            raise Exception(f"无法写入文件 {file_path}: {str(e)}")

    def create_pxe_boot_entry(self, hostname: str, mac: str, ks_url: str) -> Dict:
        """
        创建PXE引导条目

        在 /tftpboot/pxelinux.cfg/01-<MAC> 中创建配置文件
        """
        # 验证MAC地址
        if not self._validate_mac(mac):
            return {
                "success": False,
                "error": f"无效的MAC地址: {mac}"
            }

        # MAC地址格式转换: 00:1a:2b:3c:4d:5e -> 01-00-1a-2b-3c-4d-5e
        mac_formatted = "01-" + mac.replace(":", "-").lower()

        # PXE启动配置 (支持菜单和超时)
        pxe_config = f"""DEFAULT install
PROMPT 1
TIMEOUT 30

LABEL install
    MENU LABEL Install {hostname} with Kickstart
    KERNEL vmlinuz
    APPEND initrd=initrd.img inst.ks={ks_url} inst.repo=http://{self.http_server}/openEuler/ rd.loglevel=info

LABEL local
    MENU LABEL Boot from local disk
    LOCALBOOT 0

LABEL rescue
    MENU LABEL Rescue mode
    KERNEL vmlinuz
    APPEND initrd=initrd.img rescue
"""

        config_file_path = f"{self.pxe_cfg_dir}/{mac_formatted}"

        try:
            with open(config_file_path, 'w') as f:
                f.write(pxe_config)
            os.chmod(config_file_path, 0o644)

            self._log(
                logging.INFO,
                f"创建PXE启动配置: {hostname} ({mac}) -> {config_file_path}"
            )

            return {
                "success": True,
                "hostname": hostname,
                "mac": mac,
                "config_file": mac_formatted,
                "config_path": config_file_path,
                "config_content": pxe_config
            }
        except Exception as e:
            error_msg = f"创建PXE配置失败: {str(e)}"
            self._log(logging.ERROR, error_msg)
            return {
                "success": False,
                "error": error_msg
            }

    def generate_dhcp_config(self, nodes: List[Dict]) -> str:
        """
        生成DHCP配置

        nodes: [
            {
                "hostname": "master-1",
                "mgmt_mac": "00:1a:2b:3c:4d:5e",
                "mgmt_ip": "192.168.1.101",
                "mgmt_subnet": "192.168.1.0/24",
                "mgmt_gateway": "192.168.1.1"
            },
            ...
        ]
        """
        dhcp_content = """# DHCP配置 - Cluster Manager PXE
# 自动生成的配置
# 生成时间: {timestamp}

option domain-name-servers 8.8.8.8, 8.8.4.4;
default-lease-time 3600;
max-lease-time 7200;

# 管理面 (GE口) - 192.168.1.0/24
subnet 192.168.1.0 netmask 255.255.255.0 {{
    option routers 192.168.1.1;
    option subnet-mask 255.255.255.0;
    option broadcast-address 192.168.1.255;
    range 192.168.1.200 192.168.1.250;

    # PXE启动配置
    next-server 192.168.1.10;
    filename "pxelinux.0";

    option root-path "/nfs/openEuler";

    # 固定IP分配
""".format(timestamp=datetime.now().isoformat())

        # 添加每个节点的固定分配
        for node in nodes:
            if 'mgmt_mac' not in node or 'mgmt_ip' not in node or 'hostname' not in node:
                continue

            dhcp_content += f"""
    host {node['hostname']} {{
        hardware ethernet {node['mgmt_mac']};
        fixed-address {node['mgmt_ip']};
        filename "pxelinux.0";
    }}
"""

        dhcp_content += "}\n"
        return dhcp_content

    def write_dhcp_config(self, nodes: List[Dict]) -> Dict:
        """生成并写入DHCP配置, 重启服务"""
        try:
            config_content = self.generate_dhcp_config(nodes)

            # 备份原配置
            backup_file = f"{self.dhcp_conf}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            if os.path.exists(self.dhcp_conf):
                shutil.copy(self.dhcp_conf, backup_file)
                self._log(logging.INFO, f"DHCP配置已备份: {backup_file}")

            # 写入新配置
            with open(self.dhcp_conf, 'w') as f:
                f.write(config_content)

            # 测试配置语法
            result = subprocess.run(
                ['dhcpd', '-t'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                error_msg = f"DHCP配置语法错误: {result.stderr}"
                self._log(logging.ERROR, error_msg)
                # 恢复备份
                if os.path.exists(backup_file):
                    shutil.copy(backup_file, self.dhcp_conf)
                return {
                    "success": False,
                    "error": error_msg
                }

            # 重启DHCP服务
            restart_result = subprocess.run(
                ['systemctl', 'restart', 'dhcpd'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if restart_result.returncode != 0:
                error_msg = f"重启DHCP服务失败: {restart_result.stderr}"
                self._log(logging.ERROR, error_msg)
                return {
                    "success": False,
                    "error": error_msg
                }

            self._log(logging.INFO, "DHCP配置已更新并服务已重启")

            return {
                "success": True,
                "config_file": self.dhcp_conf,
                "backup_file": backup_file,
                "nodes_configured": len(nodes)
            }
        except Exception as e:
            error_msg = f"写入DHCP配置失败: {str(e)}"
            self._log(logging.ERROR, error_msg)
            return {
                "success": False,
                "error": error_msg
            }

    def reload_services(self) -> Dict:
        """重新加载PXE相关服务"""
        services = ['tftp', 'xinetd', 'dhcpd', 'nfs-server']
        results = {}

        for service in services:
            try:
                result = subprocess.run(
                    ['systemctl', 'restart', service],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    results[service] = "success"
                    self._log(logging.INFO, f"服务已重启: {service}")
                else:
                    results[service] = f"failed: {result.stderr}"
                    self._log(logging.ERROR, f"重启服务失败: {service}")
            except Exception as e:
                results[service] = f"error: {str(e)}"
                self._log(logging.ERROR, f"重启服务异常: {service} - {str(e)}")

        return {
            "success": all(v == "success" for v in results.values()),
            "services": results
        }


# ============ Kickstart模板 ============

MASTER_KS_TEMPLATE = """# Kickstart配置 - Master节点 (DPDK)
# 自动生成的配置
# 主机名: {{HOSTNAME}}

lang en_US.UTF-8
keyboard us
timezone Asia/Shanghai --utc

auth --enableshadow --passalgo=sha512
rootpw --plaintext {{ROOT_PASSWORD}}

url --url=http://{{PXE_SERVER}}/openEuler/

autopart --type=lvm

# 三平面网络配置
network --device=eth0 --bootproto=none --ip={{MGMT_IP}} --netmask={{MGMT_NETMASK}} --gateway={{MGMT_GATEWAY}} --nameserver={{DNS_SERVERS}} --hostname={{HOSTNAME}} --activate
network --device=eth1 --bootproto=none --ip={{CTRL_IP}} --netmask={{CTRL_NETMASK}} --gateway={{CTRL_GATEWAY}} --noipv6 --activate
network --device=eth2 --bootproto=none --ip={{DATA_IP}} --netmask={{DATA_NETMASK}} --noipv6 --activate

%packages
@core
@base
openssh-server
openssh-clients
python3
python3-pip
vim
net-tools
tar
gzip
dpdk
dpdk-tools
libdpdk
vfio-utils
%end

%post --log=/root/ks-post.log
#!/bin/bash
set -x

echo "=== Master节点后置配置 (DPDK) ==="

# 1. VFIO/DPDK内核模块配置
modprobe vfio
modprobe vfio-pci
modprobe vfio_iommu_type1

cat > /etc/modules-load.d/dpdk.conf << 'EOF'
vfio
vfio-pci
vfio_iommu_type1
EOF

# 2. IOMMU配置 (Intel VT-d)
if ! grep -q "intel_iommu=on" /etc/default/grub; then
    sed -i 's/^GRUB_CMDLINE_LINUX="/GRUB_CMDLINE_LINUX="intel_iommu=on iommu=pt /' /etc/default/grub
    grub2-mkconfig -o /boot/grub2/grub.cfg
fi

# 3. 注册到管理平台
curl -X POST http://{{PXE_SERVER}}:8000/api/nodes/register \\
  -H "Content-Type: application/json" \\
  -d '{"hostname":"{{HOSTNAME}}","node_type":"master","mgmt_ip":"{{MGMT_IP}}","ctrl_ip":"{{CTRL_IP}}","data_ip":"{{DATA_IP}}","data_protocol":"DPDK"}'

echo "=== Master节点后置配置完成 ==="
%end

reboot
"""

SLAVE_KS_TEMPLATE = """# Kickstart配置 - Slave节点 (RDMA)
# 自动生成的配置
# 主机名: {{HOSTNAME}}

lang en_US.UTF-8
keyboard us
timezone Asia/Shanghai --utc

auth --enableshadow --passalgo=sha512
rootpw --plaintext {{ROOT_PASSWORD}}

url --url=http://{{PXE_SERVER}}/openEuler/

autopart --type=lvm

# 三平面网络配置
network --device=eth0 --bootproto=none --ip={{MGMT_IP}} --netmask={{MGMT_NETMASK}} --gateway={{MGMT_GATEWAY}} --nameserver={{DNS_SERVERS}} --hostname={{HOSTNAME}} --activate
network --device=eth1 --bootproto=none --ip={{CTRL_IP}} --netmask={{CTRL_NETMASK}} --gateway={{CTRL_GATEWAY}} --noipv6 --activate
network --device=eth2 --bootproto=none --ip={{DATA_IP}} --netmask={{DATA_NETMASK}} --noipv6 --activate

%packages
@core
@base
openssh-server
openssh-clients
python3
python3-pip
vim
net-tools
tar
gzip
rdma-core
ibutils
infiniband-diags
perftest
%end

%post --log=/root/ks-post.log
#!/bin/bash
set -x

echo "=== Slave节点后置配置 (RDMA) ==="

# 1. RDMA内核模块加载
modprobe ib_core
modprobe ib_uverbs
modprobe rdma_cm
modprobe rdma_ucm
modprobe ib_ipoib

cat > /etc/modules-load.d/rdma.conf << 'EOF'
ib_core
ib_uverbs
rdma_cm
rdma_ucm
ib_ipoib
EOF

# 2. RDMA连接配置
mkdir -p /etc/rdma
cat > /etc/rdma/rdma.conf << 'EOF'
MASTER_DATA_IP={{MASTER_DATA_IP}}
LOCAL_DATA_IP={{DATA_IP}}
RDMA_PORT=18515
EOF

# 3. 注册到管理平台
curl -X POST http://{{PXE_SERVER}}:8000/api/nodes/register \\
  -H "Content-Type: application/json" \\
  -d '{"hostname":"{{HOSTNAME}}","node_type":"slave","mgmt_ip":"{{MGMT_IP}}","ctrl_ip":"{{CTRL_IP}}","data_ip":"{{DATA_IP}}","data_protocol":"RDMA"}'

echo "=== Slave节点后置配置完成 ==="
%end

reboot
"""


if __name__ == "__main__":
    # 示例使用
    pxe = PXEServiceEnhanced()

    # 生成Master节点Kickstart
    result = pxe.generate_kickstart(
        node_type="master",
        hostname="master-1",
        mgmt_ip="192.168.1.101",
        ctrl_ip="10.0.0.101",
        data_ip="192.168.100.101"
    )

    print("Master Kickstart生成结果:")
    print(f"  Success: {result['success']}")
    print(f"  File: {result.get('file_path')}")
    print(f"  URL: {result.get('url')}")
    if result.get('errors'):
        print(f"  Errors: {result['errors']}")

    # 生成PXE启动配置
    pxe_result = pxe.create_pxe_boot_entry(
        hostname="master-1",
        mac="00:1a:2b:3c:4d:5e",
        ks_url="http://192.168.1.10:8000/ks/master-1.ks"
    )

    print("\nPXE启动配置生成结果:")
    print(f"  Success: {pxe_result['success']}")
    print(f"  Config File: {pxe_result.get('config_file')}")
