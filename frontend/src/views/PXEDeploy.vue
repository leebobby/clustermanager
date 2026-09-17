<template>
  <div class="pxe-deploy">
    <el-tabs v-model="activeTab" type="border-card" class="dark-tabs">

      <!-- ══════════════════════════════════════════════════════════
           Tab 1: IP 规划
           ══════════════════════════════════════════════════════════ -->
      <el-tab-pane label="IP 规划" name="planning">
        <el-card shadow="never">
          <template #header>
            <span>v2 六子网 IP 规划</span>
          </template>

          <!-- 子网说明 -->
          <el-alert type="info" :closable="false" style="margin-bottom:16px">
            <template #title>
              管理面 BMC: <b>172.16.0.0/24</b> &nbsp;|&nbsp;
              控制面 10GE: <b>172.16.3.0/24</b> &nbsp;|&nbsp;
              DPDK-1: <b>200.1.1.0/24</b> &nbsp;|&nbsp;
              DPDK-2: <b>200.1.2.0/24</b> &nbsp;|&nbsp;
              RDMA-1: <b>100.1.1.0/24</b> &nbsp;|&nbsp;
              RDMA-2: <b>100.1.2.0/24</b>
            </template>
          </el-alert>

          <!-- 节点数量 -->
          <el-form :model="planForm" inline label-width="120px">
            <el-form-item label="Master 数量">
              <el-input-number v-model="planForm.master_count" :min="0" :max="10" />
            </el-form-item>
            <el-form-item label="Slave 数量">
              <el-input-number v-model="planForm.slave_count" :min="0" :max="50" />
            </el-form-item>
            <el-form-item label="SubSwath 数量">
              <el-input-number v-model="planForm.subswath_count" :min="0" :max="8" />
            </el-form-item>
            <el-form-item label="GStorage 数量">
              <el-input-number v-model="planForm.gstorage_count" :min="0" :max="4" />
            </el-form-item>
            <el-form-item label="Acquisition 数量">
              <el-input-number v-model="planForm.acquisition_count" :min="0" :max="20" />
            </el-form-item>
            <el-form-item>
              <el-button
                type="success"
                size="default"
                @click="applyPlanToNodesJson"
                :loading="applyingPlan || planning"
              >
                应用规划 (保存到 nodes.json + 节点管理)
              </el-button>
              <el-button @click="generatePlan" :loading="planning" plain>
                仅预览
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 规划结果 -->
        <template v-if="ipPlanResult">
          <el-alert
            v-if="planSaved"
            type="success"
            :title="`已保存到 nodes.json,共 ${ipPlanResult.total_nodes} 个节点(含 PXE Host)。节点管理已同步,未部署节点显示为离线。`"
            :closable="false"
            style="margin:12px 0"
          />
          <el-alert
            v-else
            type="warning"
            :title="`预览: 共 ${ipPlanResult.total_nodes} 个节点(含 PXE Host)。当前未保存,点击上方【应用规划】写入 nodes.json。`"
            :closable="false"
            style="margin:12px 0"
          />

          <!-- PXE Host -->
          <el-card shadow="never" style="margin-bottom:12px">
            <template #header><span class="role-tag role-host">PXE Host ×1</span></template>
            <el-table :data="ipPlanResult.plan.pxe_host" size="small" stripe>
              <el-table-column prop="hostname"  label="主机名"    width="140" />
              <el-table-column prop="bmc_ip"    label="BMC IP"   width="140" />
              <el-table-column prop="ctrl_ip"   label="控制面 IP" width="140" />
              <el-table-column prop="note"      label="说明" />
            </el-table>
          </el-card>

          <!-- Master -->
          <el-card v-if="ipPlanResult.plan.masters.length" shadow="never" style="margin-bottom:12px">
            <template #header>
              <span class="role-tag role-master">Master ×{{ ipPlanResult.plan.masters.length }}</span>
            </template>
            <el-table :data="ipPlanResult.plan.masters" size="small" stripe>
              <el-table-column prop="hostname"  label="主机名"     width="130" />
              <el-table-column prop="bmc_ip"    label="BMC IP"    width="130" />
              <el-table-column prop="ctrl_ip"   label="控制面"     width="130" />
              <el-table-column prop="dpdk1_ip"  label="DPDK-1"    width="120" />
              <el-table-column prop="dpdk2_ip"  label="DPDK-2"    width="120" />
              <el-table-column prop="rdma1_ip"  label="RDMA-1"    width="120" />
              <el-table-column prop="rdma2_ip"  label="RDMA-2"    width="120" />
              <el-table-column prop="hugepages_1g" label="大页(×1G)" width="80" />
            </el-table>
          </el-card>

          <!-- Slave -->
          <el-card v-if="ipPlanResult.plan.slaves.length" shadow="never" style="margin-bottom:12px">
            <template #header>
              <span class="role-tag role-slave">Slave ×{{ ipPlanResult.plan.slaves.length }}</span>
            </template>
            <el-table :data="ipPlanResult.plan.slaves" size="small" stripe>
              <el-table-column prop="hostname" label="主机名"   width="130" />
              <el-table-column prop="bmc_ip"   label="BMC IP"  width="140" />
              <el-table-column prop="ctrl_ip"  label="控制面"  width="140" />
              <el-table-column prop="rdma1_ip" label="RDMA-1"  width="140" />
              <el-table-column prop="nics"     label="网口分配" />
            </el-table>
          </el-card>

          <!-- SubSwath -->
          <el-card v-if="ipPlanResult.plan.subswaths.length" shadow="never" style="margin-bottom:12px">
            <template #header>
              <span class="role-tag role-subswath">SubSwath ×{{ ipPlanResult.plan.subswaths.length }}</span>
            </template>
            <el-table :data="ipPlanResult.plan.subswaths" size="small" stripe>
              <el-table-column prop="hostname"    label="主机名"   width="130" />
              <el-table-column prop="bmc_ip"      label="BMC IP"  width="140" />
              <el-table-column prop="ctrl_ip"     label="控制面"  width="140" />
              <el-table-column prop="rdma1_ip"    label="RDMA-1"  width="140" />
              <el-table-column prop="rdma2_ip"    label="RDMA-2"  width="140" />
              <el-table-column prop="data_disks"  label="数据盘"  width="140" />
              <el-table-column prop="data_raid"   label="RAID 方案" />
            </el-table>
          </el-card>

          <!-- GStorage -->
          <el-card v-if="ipPlanResult.plan.gstorages.length" shadow="never" style="margin-bottom:12px">
            <template #header>
              <span class="role-tag role-gstorage">GStorage ×{{ ipPlanResult.plan.gstorages.length }}</span>
            </template>
            <el-table :data="ipPlanResult.plan.gstorages" size="small" stripe>
              <el-table-column prop="hostname"   label="主机名"   width="130" />
              <el-table-column prop="bmc_ip"     label="BMC IP"  width="140" />
              <el-table-column prop="ctrl_ip"    label="控制面"  width="140" />
              <el-table-column prop="rdma2_ip"   label="RDMA-2"  width="140" />
              <el-table-column prop="data_disks" label="数据盘"  width="140" />
              <el-table-column prop="data_raid"  label="RAID 方案" />
            </el-table>
          </el-card>

          <!-- Acquisition -->
          <el-card v-if="ipPlanResult.plan.acquisitions.length" shadow="never" style="margin-bottom:12px">
            <template #header>
              <span class="role-tag role-acquisition">Acquisition ×{{ ipPlanResult.plan.acquisitions.length }}</span>
            </template>
            <el-table :data="ipPlanResult.plan.acquisitions" size="small" stripe>
              <el-table-column prop="hostname"  label="主机名"    width="150" />
              <el-table-column prop="bmc_ip"    label="BMC IP"   width="140" />
              <el-table-column prop="ctrl_ip"   label="控制面"    width="140" />
              <el-table-column prop="dpdk1_ip"  label="DPDK-1"   width="140" />
              <el-table-column prop="rdma1_ip"  label="RDMA-1"   width="140" />
              <el-table-column prop="nics"      label="网口分配" />
            </el-table>
          </el-card>
        </template>
      </el-tab-pane>

      <!-- ══════════════════════════════════════════════════════════
           Tab 2: 节点配置 (nodes.json)
           ══════════════════════════════════════════════════════════ -->
      <el-tab-pane label="节点配置" name="nodes">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>nodes.json — 节点 MAC 与配置映射（{{ nodeList.length }} 个节点）</span>
              <div>
                <el-button size="small" @click="loadNodeList">
                  <el-icon><Refresh /></el-icon> 刷新
                </el-button>
                <el-button size="small" type="warning" @click="resetToTemplate">
                  重置为模板 MAC
                </el-button>
              </div>
            </div>
          </template>

          <el-alert type="warning" :closable="false" style="margin-bottom:12px">
            <template #title>
              表中 MAC 为占位符，请点击编辑替换为实际硬件 MAC（通过 <code>ip link show</code> 获取）
            </template>
          </el-alert>

          <el-table :data="nodeList" size="small" stripe row-key="mac">
            <el-table-column prop="hostname" label="主机名" width="130" fixed />
            <el-table-column label="角色" width="100">
              <template #default="{ row }">
                <el-tag :type="roleTagType(row.role)" size="small">{{ row.role }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="MAC 地址" width="180">
              <template #default="{ row }">
                <span class="mac-text">{{ row.mac }}</span>
                <el-button
                  link
                  size="small"
                  style="margin-left:4px"
                  @click="openNodeEdit(row)"
                >编辑</el-button>
              </template>
            </el-table-column>
            <el-table-column prop="bmc_ip"   label="BMC IP"  width="130" />
            <el-table-column prop="ctrl_ip"  label="控制面 IP" width="130" />
            <el-table-column label="RDMA IP" width="200">
              <template #default="{ row }">
                <span>{{ row.rdma_ips }}</span>
              </template>
            </el-table-column>
            <el-table-column label="DPDK IP" width="220">
              <template #default="{ row }">
                <span v-if="row.dpdk_ips">{{ row.dpdk_ips }}</span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="数据盘 / RAID" min-width="160">
              <template #default="{ row }">
                <span v-if="row.data_disks">
                  {{ row.data_disks }}
                  <el-tag v-if="row.data_raid_level" type="warning" size="small" style="margin-left:4px">
                    {{ row.data_raid_level.toUpperCase() }}
                  </el-tag>
                </span>
                <span v-else class="text-muted">无数据盘</span>
              </template>
            </el-table-column>
            <el-table-column label="大页" width="70">
              <template #default="{ row }">
                <span v-if="row.hugepages_1g && row.hugepages_1g !== '0'">
                  {{ row.hugepages_1g }}G
                </span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 节点配置编辑对话框 -->
        <el-dialog v-model="nodeEditVisible" title="编辑节点配置" width="660px" :close-on-click-modal="false">
          <el-descriptions :column="2" border size="small" style="margin-bottom:14px">
            <el-descriptions-item label="主机名">{{ nodeEditRow.hostname }}</el-descriptions-item>
            <el-descriptions-item label="角色">
              <el-tag :type="roleTagType(nodeEditRow.role)" size="small">{{ nodeEditRow.role }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <!-- 角色对应网卡规划提示 -->
          <el-alert type="info" :closable="false" style="margin-bottom:12px">
            <template #title>
              <span v-if="nodeEditRow.role === 'master'">
                Master — DPDK×2（eno2/eno3，200.1.1/200.1.2）+ RDMA×2（eno4/eno5，100.1.1/100.1.2）
              </span>
              <span v-else-if="nodeEditRow.role === 'acquisition'">
                Acquisition — DPDK×1（eno2，200.1.1）+ RDMA×1（eno3，100.1.1）
              </span>
              <span v-else-if="nodeEditRow.role === 'slave'">
                Slave — RDMA×1（eno2，100.1.1）
              </span>
              <span v-else-if="nodeEditRow.role === 'subswath'">
                SubSwath — RDMA×2（eno2/eno3，100.1.1/100.1.2）
              </span>
              <span v-else-if="nodeEditRow.role === 'gstorage'">
                GStorage — RDMA×1（eno2，100.1.2）
              </span>
              <span v-else>{{ nodeEditRow.role }} — 按实际网卡配置填写</span>
            </template>
          </el-alert>

          <el-form label-width="110px" size="small">
            <el-divider content-position="left">MAC 地址</el-divider>
            <el-form-item label="当前 MAC">
              <el-input :value="nodeEditRow.mac" disabled style="width:230px;font-family:monospace" />
            </el-form-item>
            <el-form-item label="新 MAC">
              <el-input v-model="nodeEditForm.newMac" placeholder="00:11:22:33:44:55" style="width:230px" />
            </el-form-item>

            <el-divider content-position="left">控制面</el-divider>
            <el-form-item label="控制面网卡名">
              <el-input v-model="nodeEditForm.ctrl_nic" placeholder="如 eno1 / enp129s0f0" style="width:200px" />
            </el-form-item>

            <!-- DPDK：master + acquisition 均有 DPDK -->
            <template v-if="['master', 'acquisition'].includes(nodeEditRow.role)">
              <el-divider content-position="left">DPDK 网卡（100GE 数据面前段）</el-divider>
              <div
                v-for="(pair, idx) in nodeEditForm.dpdkPairs"
                :key="'dpdk'+idx"
                class="nic-row"
              >
                <span class="nic-idx">{{ idx + 1 }}</span>
                <el-input v-model="pair.nic" placeholder="网卡名 如 enp129s0f0" style="width:175px" />
                <el-input v-model="pair.ip" placeholder="IP/掩码 如 200.1.1.11/24" style="width:195px" />
                <el-button size="small" :disabled="nodeEditForm.dpdkPairs.length <= 1"
                  @click="nodeEditForm.dpdkPairs.splice(idx, 1)">
                  <el-icon><Minus /></el-icon>
                </el-button>
              </div>
              <div class="nic-add-row">
                <el-button size="small" @click="nodeEditForm.dpdkPairs.push({ nic: '', ip: '' })">
                  <el-icon><Plus /></el-icon> 添加 DPDK 网卡
                </el-button>
              </div>
            </template>

            <!-- RDMA：除 pxe_host 以外所有角色均可能有 RDMA -->
            <template v-if="!['pxe_host'].includes(nodeEditRow.role)">
              <el-divider content-position="left">RDMA 网卡（100GE 数据面后段）</el-divider>
              <div
                v-for="(pair, idx) in nodeEditForm.rdmaPairs"
                :key="'rdma'+idx"
                class="nic-row"
              >
                <span class="nic-idx">{{ idx + 1 }}</span>
                <el-input v-model="pair.nic" placeholder="网卡名 如 enp130s0f0" style="width:175px" />
                <el-input v-model="pair.ip" placeholder="IP/掩码 如 100.1.1.11/24" style="width:195px" />
                <el-button size="small" :disabled="nodeEditForm.rdmaPairs.length <= 1"
                  @click="nodeEditForm.rdmaPairs.splice(idx, 1)">
                  <el-icon><Minus /></el-icon>
                </el-button>
              </div>
              <div class="nic-add-row">
                <el-button size="small" @click="nodeEditForm.rdmaPairs.push({ nic: '', ip: '' })">
                  <el-icon><Plus /></el-icon> 添加 RDMA 网卡
                </el-button>
              </div>
            </template>
          </el-form>

          <template #footer>
            <el-button @click="nodeEditVisible = false">取消</el-button>
            <el-button type="primary" @click="saveNodeEdit" :loading="savingNode">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ══════════════════════════════════════════════════════════
           Tab 3: 配置文件生成
           ══════════════════════════════════════════════════════════ -->
      <el-tab-pane label="配置生成" name="configs">
        <el-row :gutter="16">
          <!-- DHCP 配置 -->
          <el-col :span="12">
            <el-card shadow="never" style="margin-bottom:16px">
              <template #header>
                <div class="card-header">
                  <span>dhcpd.conf（控制面 172.16.3.0/24）</span>
                  <div>
                    <el-button size="small" @click="fetchDhcpConfig" :loading="loadingDhcp">生成</el-button>
                    <el-button size="small" @click="copyText(dhcpConfig)" :disabled="!dhcpConfig">复制</el-button>
                  </div>
                </div>
              </template>
              <el-alert type="info" :closable="false" style="margin-bottom:8px">
                <template #title>
                  保存至 <code>/etc/dhcp/dhcpd.conf</code>，
                  并在 <code>/etc/sysconfig/dhcpd</code> 中设置
                  <code>DHCPDARGS=eno3</code>（100GE 物理接口）
                </template>
              </el-alert>
              <el-input
                v-model="dhcpConfig"
                type="textarea"
                :rows="18"
                class="code-textarea"
                placeholder="点击「生成」按钮获取配置..."
              />
            </el-card>
          </el-col>

          <!-- GRUB 配置 -->
          <el-col :span="12">
            <el-card shadow="never" style="margin-bottom:16px">
              <template #header>
                <div class="card-header">
                  <span>grub.cfg（aarch64 UEFI 引导）</span>
                  <div>
                    <el-button size="small" @click="fetchGrubConfig" :loading="loadingGrub">生成</el-button>
                    <el-button size="small" @click="copyText(grubConfig)" :disabled="!grubConfig">复制</el-button>
                  </div>
                </div>
              </template>
              <el-alert type="info" :closable="false" style="margin-bottom:8px">
                <template #title>
                  保存至 <code>/var/lib/tftpboot/grub.cfg</code>
                </template>
              </el-alert>
              <el-input
                v-model="grubConfig"
                type="textarea"
                :rows="18"
                class="code-textarea"
                placeholder="点击「生成」按钮获取配置..."
              />
            </el-card>
          </el-col>

          <!-- RAID1 初始化脚本 -->
          <el-col :span="12">
            <el-card shadow="never" style="margin-bottom:16px">
              <template #header>
                <div class="card-header">
                  <span>setup-raid1.sh（iBMC Redfish 批量建 RAID1）</span>
                  <div>
                    <el-button size="small" @click="fetchRaid1Script" :loading="loadingRaid1">生成</el-button>
                    <el-button size="small" @click="copyText(raid1Script)" :disabled="!raid1Script">复制</el-button>
                  </div>
                </div>
              </template>
              <el-alert type="warning" :closable="false" style="margin-bottom:8px">
                <template #title>
                  部署前在 PXE Host 执行，为所有节点创建 2×960G RAID1 系统盘
                </template>
              </el-alert>
              <el-input
                v-model="raid1Script"
                type="textarea"
                :rows="14"
                class="code-textarea"
                placeholder="点击「生成」按钮获取脚本..."
              />
            </el-card>
          </el-col>

          <!-- PXE 引导脚本 -->
          <el-col :span="12">
            <el-card shadow="never">
              <template #header>
                <div class="card-header">
                  <span>set-pxe-boot.sh（ipmitool 批量设置 PXE 启动）</span>
                  <div>
                    <el-button size="small" @click="fetchPxeBootScript" :loading="loadingPxeBoot">生成</el-button>
                    <el-button size="small" @click="copyText(pxeBootScript)" :disabled="!pxeBootScript">复制</el-button>
                  </div>
                </div>
              </template>
              <el-alert type="info" :closable="false" style="margin-bottom:8px">
                <template #title>
                  每批部署前执行，设置目标节点下次从 PXE 启动
                </template>
              </el-alert>
              <el-input
                v-model="pxeBootScript"
                type="textarea"
                :rows="14"
                class="code-textarea"
                placeholder="点击「生成」按钮获取脚本..."
              />
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- ══════════════════════════════════════════════════════════
           Tab 4: 分批部署
           ══════════════════════════════════════════════════════════ -->
      <el-tab-pane label="分批部署" name="deploy">
        <!-- ── PXE Host 首次装机引导（一次性 Bootstrap，默认折叠）── -->
        <el-card shadow="never" class="bootstrap-card" style="margin-bottom:14px">
          <div class="bootstrap-header" @click="bootstrapExpanded = !bootstrapExpanded">
            <el-icon class="caret" :class="{ rotated: bootstrapExpanded }"><CaretRight /></el-icon>
            <span class="bootstrap-title">PXE Host 首次装机引导</span>
            <el-tag size="small" effect="plain" type="info">Bootstrap · 一次性</el-tag>
            <span class="bootstrap-status" :style="{ color: bootstrapStateColor }">
              · {{ bootstrapStateLabel }}
            </span>
            <span style="flex:1"></span>
            <el-button size="small" link @click.stop="openPxeHostEdit">
              <el-icon><Edit /></el-icon> 配置
            </el-button>
          </div>

          <div v-if="bootstrapExpanded" class="bootstrap-body">
            <el-alert type="info" :closable="false" style="margin-bottom:12px">
              <template #title>
                仅在 PXE Host 首次部署时使用 — 通过 BMC Redfish 把本地 ISO 挂为虚拟光驱触发一次性 CD 引导。
                PXE Host 装好后稳定运行，不需要重复执行此操作。
              </template>
            </el-alert>
            <el-row :gutter="16">
              <el-col :span="14">
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="主机名">{{ pxeHostCfg.hostname || '—' }}</el-descriptions-item>
                  <el-descriptions-item label="BMC IP">
                    <span class="ip-text">{{ pxeHostCfg.bmc_ip || '—' }}</span>
                  </el-descriptions-item>
                  <el-descriptions-item label="控制面 IP">
                    <span class="ip-text">{{ pxeHostCfg.ctrl_ip || '—' }}</span>
                  </el-descriptions-item>
                  <el-descriptions-item label="ISO HTTP 地址">
                    <span class="ip-text">
                      {{ pxeHostCfg.iso_http_host }}:{{ pxeHostCfg.iso_http_port }}
                    </span>
                  </el-descriptions-item>
                  <el-descriptions-item label="ISO 文件" :span="2">
                    <el-tag v-if="pxeHostCfg.iso_filename" type="warning" size="small">
                      {{ pxeHostCfg.iso_filename }}
                    </el-tag>
                    <span v-else class="text-muted">未选择</span>
                  </el-descriptions-item>
                  <el-descriptions-item label="Redfish 路径" :span="2">
                    <code class="redfish-path">
                      Managers/{{ pxeHostCfg.redfish_manager_id }} /
                      VirtualMedia/{{ pxeHostCfg.redfish_virtual_media_id }} /
                      Systems/{{ pxeHostCfg.redfish_system_id }}
                    </code>
                  </el-descriptions-item>
                </el-descriptions>
              </el-col>
              <el-col :span="10">
                <div class="wave-check">
                  <b>装机流程（Redfish 三步）：</b>
                  <code>1. InsertMedia → 挂载 ISO</code>
                  <code>2. PATCH Boot=Cd / Once</code>
                  <code>3. ComputerSystem.Reset</code>
                </div>
                <div class="wave-meta" style="margin-top:6px">
                  <el-icon><Clock /></el-icon> 预计 ~15 min（仅首次）
                </div>
                <el-button
                  type="warning"
                  style="margin-top:12px;width:100%"
                  @click="installPxeHost"
                  :loading="installingPxeHost"
                  :disabled="!pxeHostCfg.iso_filename || !pxeHostCfg.bmc_ip
                             || bootstrapState === 'online' || bootstrapState === 'installing'"
                >
                  {{ bootstrapState === 'online' ? 'PXE Host 已就绪'
                     : bootstrapState === 'installing' ? '装机进行中…'
                     : '开始首次装机' }}
                </el-button>
                <el-button
                  v-if="bootstrapState === 'online' || bootstrapState === 'error'"
                  size="small" link type="danger"
                  style="margin-top:6px;width:100%"
                  @click="installPxeHost(true)"
                >
                  ⚠ 强制重新装机（覆盖现有系统）
                </el-button>
              </el-col>
            </el-row>
          </div>
        </el-card>

        <el-alert type="warning" :closable="false" style="margin-bottom:16px">
          <template #title>
            <b>分批部署顺序：第一批 → 等待 NFS 就绪 → 第二批 → 等待大页就绪 → 第三批</b>
          </template>
          <div style="margin-top:6px;font-size:13px;color:#b0b0b0">
            前提：PXE Host 已装机就绪。Slave firstboot 会轮询 NFS Server，Server 就绪前不会挂载；
            Master firstboot 会自动 reboot 一次（大页/驱动生效）。
          </div>
        </el-alert>

        <el-row :gutter="16">
          <!-- 第一批: SubSwath + GStorage（有节点才显示） -->
          <el-col :span="8" v-if="waveNodes(1).length > 0">
            <el-card shadow="never" class="wave-card">
              <template #header>
                <div class="wave-header">
                  <el-tag type="warning" size="large">第一批</el-tag>
                  <span>NFS Server（SubSwath + GStorage）</span>
                </div>
              </template>
              <div class="wave-nodes">
                <div v-for="node in waveNodes(1)" :key="node.mac" class="wave-node-item">
                  <el-tag :type="roleTagType(node.role)" size="small">{{ node.role }}</el-tag>
                  <span class="node-name">{{ node.hostname }}</span>
                  <span class="node-bmc">{{ node.bmc_ip }}</span>
                </div>
              </div>
              <div class="wave-meta">
                <el-icon><Clock /></el-icon> 预计 ~20 min（含 NVMe RAID10 初始化）
              </div>
              <el-divider />
              <div class="wave-check">
                <b>就绪验证：</b>
                <code>showmount -e 100.1.1.170</code><br>
                <code>showmount -e 100.1.1.171</code><br>
                <code>showmount -e 100.1.2.172</code>
              </div>
              <el-button type="warning" style="margin-top:12px;width:100%"
                @click="triggerWaveDeploy(1)" :loading="deployingWave === 1">
                触发第一批部署
              </el-button>
            </el-card>
          </el-col>

          <!-- 第二批: Master（有节点才显示） -->
          <el-col :span="8" v-if="waveNodes(2).length > 0">
            <el-card shadow="never" class="wave-card">
              <template #header>
                <div class="wave-header">
                  <el-tag type="success" size="large">第二批</el-tag>
                  <span>Master（DPDK + RDMA 计算控制）</span>
                </div>
              </template>
              <div class="wave-nodes">
                <div v-for="node in waveNodes(2)" :key="node.mac" class="wave-node-item">
                  <el-tag type="success" size="small">master</el-tag>
                  <span class="node-name">{{ node.hostname }}</span>
                  <span class="node-bmc">{{ node.bmc_ip }}</span>
                </div>
              </div>
              <div class="wave-meta">
                <el-icon><Clock /></el-icon> 预计 ~25 min（含大页 reboot）
              </div>
              <el-divider />
              <div class="wave-check">
                <b>就绪验证：</b>
                <code>grep HugePages_Total /proc/meminfo</code>
                <div style="color:#6c6c6c;font-size:12px">期望 100 个 1G 大页</div>
              </div>
              <el-button type="success" style="margin-top:12px;width:100%"
                @click="triggerWaveDeploy(2)" :loading="deployingWave === 2">
                触发第二批部署
              </el-button>
            </el-card>
          </el-col>

          <!-- 第三批: Slave + Acquisition（有节点才显示） -->
          <el-col :span="8" v-if="waveNodes(3).length > 0">
            <el-card shadow="never" class="wave-card">
              <template #header>
                <div class="wave-header">
                  <el-tag type="primary" size="large">第三批</el-tag>
                  <span>Slave / Acquisition（RDMA + NFS 客户端）</span>
                </div>
              </template>
              <div class="wave-nodes">
                <div v-for="node in waveNodes(3)" :key="node.mac" class="wave-node-item">
                  <el-tag :type="roleTagType(node.role)" size="small">{{ node.role }}</el-tag>
                  <span class="node-name">{{ node.hostname }}</span>
                  <span class="node-bmc">{{ node.bmc_ip }}</span>
                </div>
              </div>
              <div class="wave-meta">
                <el-icon><Clock /></el-icon> 预计 ~20 min（含 NFS 挂载等待）
              </div>
              <el-divider />
              <div class="wave-check">
                <b>就绪验证（Slave）：</b>
                <code>df -h | grep -E "swath|global"</code>
                <b style="display:block;margin-top:6px">就绪验证（Acquisition）：</b>
                <code>ip addr show eno2 | grep 200.1.1</code>
              </div>
              <el-button type="primary" style="margin-top:12px;width:100%"
                @click="triggerWaveDeploy(3)" :loading="deployingWave === 3">
                触发第三批部署
              </el-button>
            </el-card>
          </el-col>

          <!-- 全部为 0 时的空提示 -->
          <el-col :span="24" v-if="waveNodes(1).length + waveNodes(2).length + waveNodes(3).length === 0">
            <el-empty description="nodes.json 中暂无节点，请先在「节点配置」中检查或执行「应用到 nodes.json」" :image-size="60" />
          </el-col>
        </el-row>

        <!-- 自定义脚本 -->
        <el-card shadow="never" style="margin-top:16px">
          <template #header><span>自定义脚本（部署后批量配置）</span></template>
          <el-alert type="info" :closable="false" style="margin-bottom:14px">
            <template #title>通过 SSH 在已部署节点上执行自定义 Shell 脚本，适用于软件安装、参数调整等部署后任务</template>
          </el-alert>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form label-width="80px" size="small">
                <el-form-item label="目标节点">
                  <el-select v-model="scriptTargets" multiple collapse-tags collapse-tags-tooltip
                    placeholder="选择目标节点..." style="width:100%">
                    <el-option
                      v-for="node in nodeList"
                      :key="node.mac"
                      :label="`${node.hostname} (${node.ctrl_ip})`"
                      :value="node.mac"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="SSH 用户">
                  <el-input v-model="scriptSshUser" placeholder="root" style="width:130px" />
                </el-form-item>
                <el-form-item label="SSH 密码">
                  <el-input v-model="scriptSshPassword" type="password" show-password
                    placeholder="留空使用密钥" style="width:160px" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" @click="runCustomScript" :loading="runningScript"
                    :disabled="!scriptTargets.length">
                    执行脚本
                  </el-button>
                </el-form-item>
              </el-form>
            </el-col>
            <el-col :span="16">
              <div style="font-size:12px;color:#64748b;margin-bottom:6px">脚本内容（Shell）：</div>
              <el-input
                v-model="customScript"
                type="textarea"
                :rows="10"
                class="code-textarea"
                placeholder="#!/bin/bash&#10;# 在此输入自定义 Shell 脚本..."
              />
            </el-col>
          </el-row>
          <template v-if="scriptResult.length">
            <el-divider />
            <div style="font-size:12px;color:#64748b;margin-bottom:8px">执行结果：</div>
            <el-table :data="scriptResult" size="small" stripe>
              <el-table-column prop="hostname" label="节点" width="130" />
              <el-table-column prop="status" label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                    {{ row.status === 'success' ? '成功' : '失败' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="output" label="输出">
                <template #default="{ row }">
                  <pre class="script-output">{{ row.output || '(无输出)' }}</pre>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </el-card>

        <!-- node-env API 说明 -->
        <el-card shadow="never" style="margin-top:16px">
          <template #header><span>firstboot node-env API</span></template>
          <el-alert type="info" :closable="false">
            <template #title>节点 firstboot 阶段调用以下接口获取配置（detect.sh）</template>
          </el-alert>
          <pre class="code-block">curl -sf http://172.16.3.10:8000/api/pxe/node-env?mac=&lt;10GE_MAC&gt; \
     -o /etc/node-role/env</pre>
          <el-form inline style="margin-top:12px">
            <el-form-item label="查询 MAC">
              <el-input v-model="queryMac" placeholder="aa:bb:cc:11:00:01" style="width:200px" clearable />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="queryNodeEnv" :loading="queryingEnv">查询环境变量</el-button>
            </el-form-item>
          </el-form>
          <el-input
            v-if="nodeEnvResult"
            v-model="nodeEnvResult"
            type="textarea"
            :rows="12"
            class="code-textarea"
          />
        </el-card>
      </el-tab-pane>

      <!-- ══════════════════════════════════════════════════════════
           Tab 5: 状态监控
           ══════════════════════════════════════════════════════════ -->
      <el-tab-pane label="状态监控" name="status">
        <!-- BMC 节点发现 -->
        <el-card shadow="never" style="margin-bottom:16px">
          <template #header>
            <div class="card-header">
              <span>节点发现（BMC 扫描）</span>
              <el-button type="primary" size="small" @click="discoverDialogVisible = true">
                <el-icon><Search /></el-icon> 扫描 BMC
              </el-button>
            </div>
          </template>
          <el-table :data="discoveredNodes" stripe size="small">
            <el-table-column prop="bmc_ip"    label="BMC IP"   width="140" />
            <el-table-column prop="bmc_mac"   label="BMC MAC"  width="160" />
            <el-table-column prop="hostname"  label="主机名"   width="140" />
            <el-table-column prop="status"    label="状态"     width="100">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180">
              <template #default="{ row }">
                <el-button size="small" type="primary" @click="showDeployDialog(row)">部署</el-button>
                <el-button size="small" @click="checkBMCInfo(row)">BMC 信息</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <!-- 部署任务状态 -->
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>部署任务状态</span>
              <el-button size="small" @click="refreshDeployStatus">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
            </div>
          </template>
          <el-empty v-if="deployTasks.length === 0" description="暂无进行中的部署任务" :image-size="60" />
          <el-table v-else :data="deployTasks" stripe size="small">
            <el-table-column prop="hostname" label="主机名"   width="130" />
            <el-table-column prop="bmc_ip"   label="BMC IP"  width="130">
              <template #default="{ row }">
                <span class="ip-text">{{ row.bmc_ip || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="ctrl_ip"  label="控制面 IP" width="130">
              <template #default="{ row }">
                <span class="ip-text">{{ row.ctrl_ip || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="data_ip"  label="数据面 IP" width="130">
              <template #default="{ row }">
                <span class="ip-text">{{ row.data_ip || '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="status"   label="状态"   width="110">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="stage"    label="阶段进展" min-width="240">
              <template #default="{ row }">
                <el-progress :percentage="row.progress" :status="row.status === 'completed' ? 'success' : ''" />
                <span class="stage-text">{{ row.stage }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="固件仓库" name="firmware">
        <el-card shadow="never" style="margin-bottom:14px">
          <template #header>
            <div class="card-header">
              <span>固件文件</span>
              <div>
                <el-button size="small" @click="loadFirmwareList">
                  <el-icon><Refresh /></el-icon> 刷新
                </el-button>
                <el-button size="small" type="primary" @click="firmwareUploadVisible = true">
                  <el-icon><Plus /></el-icon> 上传固件
                </el-button>
              </div>
            </div>
          </template>
          <el-alert type="info" :closable="false" style="margin-bottom:12px">
            <template #title>
              节点 firstboot 阶段从 <code>http://&lt;pxe-host&gt;/firmware/&lt;rel_path&gt;</code> 拉取固件;
              并通过 <code>POST /api/pxe/report</code> 回报版本变更
            </template>
          </el-alert>
          <div v-if="firmwareDir" class="form-hint" style="margin-bottom:8px">
            扫描目录: <code>{{ firmwareDir }}</code>
          </div>
          <el-table :data="firmwareList" stripe size="small">
            <el-table-column label="厂商"   prop="vendor"   width="120" />
            <el-table-column label="型号"   prop="model"    width="180" />
            <el-table-column label="版本"   prop="version"  width="140" />
            <el-table-column label="文件名" prop="filename" />
            <el-table-column label="大小(MB)" prop="size_mb" width="100" />
            <el-table-column label="SHA256" width="180">
              <template #default="{ row }">
                <span style="font-family:monospace;font-size:12px">{{ row.sha256 ? row.sha256.slice(0,16) + '…' : '—' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="匹配规则" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.referenced_by_manifest" type="success" size="small">已引用</el-tag>
                <el-tag v-else type="info" size="small">未引用</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="useFirmwareInRule(row)">作为规则</el-button>
                <el-button size="small" type="danger"  link @click="deleteFirmware(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>固件匹配规则 (manifest.json)</span>
              <div>
                <el-button size="small" @click="loadFirmwareManifest">
                  <el-icon><Refresh /></el-icon> 重载
                </el-button>
                <el-button size="small" @click="addManifestRule">
                  <el-icon><Plus /></el-icon> 新增规则
                </el-button>
                <el-button size="small" type="primary" @click="saveFirmwareManifest" :loading="savingManifest">保存</el-button>
              </div>
            </div>
          </template>
          <el-alert type="warning" :closable="false" style="margin-bottom:12px">
            <template #title>
              节点 firstboot 用 lspci 拿到的 vendor:device ID 匹配下表, 每张设备只执行 target_fw 不一致时的烧写
            </template>
          </el-alert>
          <el-table :data="manifestRules" stripe size="small" border>
            <el-table-column label="启用" width="60">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" />
              </template>
            </el-table-column>
            <el-table-column label="vendor_id" width="100">
              <template #default="{ row }">
                <el-input v-model="row.match_vendor_id" size="small" placeholder="15b3" />
              </template>
            </el-table-column>
            <el-table-column label="device_id" width="100">
              <template #default="{ row }">
                <el-input v-model="row.match_device_id" size="small" placeholder="1019" />
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="140">
              <template #default="{ row }">
                <el-input v-model="row.name" size="small" placeholder="Mellanox ConnectX-5" />
              </template>
            </el-table-column>
            <el-table-column label="目标版本" width="120">
              <template #default="{ row }">
                <el-input v-model="row.target_fw" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="image (rel_path)" min-width="220">
              <template #default="{ row }">
                <el-select v-model="row.image" filterable size="small" placeholder="选择固件文件">
                  <el-option v-for="f in firmwareList" :key="f.rel_path"
                    :label="f.rel_path" :value="f.rel_path" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="工具" width="100">
              <template #default="{ row }">
                <el-input v-model="row.tool" size="small" placeholder="mstflint" />
              </template>
            </el-table-column>
            <el-table-column label="烧写命令" min-width="260">
              <template #default="{ row }">
                <el-input v-model="row.flash_cmd" size="small"
                  placeholder="mstflint -d {pci} -i {image} -y burn" />
              </template>
            </el-table-column>
            <el-table-column label="查询命令" min-width="260">
              <template #default="{ row }">
                <el-input v-model="row.query_cmd" size="small"
                  placeholder="mstflint -d {pci} q | awk '/FW Version:/{print $3}'" />
              </template>
            </el-table-column>
            <el-table-column label="post_action" width="130">
              <template #default="{ row }">
                <el-select v-model="row.post_action" size="small">
                  <el-option label="冷启动" value="cold_reboot" />
                  <el-option label="热启动" value="warm_reboot" />
                  <el-option label="无"     value="none" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="70" fixed="right">
              <template #default="{ $index }">
                <el-button size="small" type="danger" link @click="removeManifestRule($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!manifestRules.length" class="form-hint" style="text-align:center;padding:20px">
            暂无规则。请先上传固件文件, 再点【新增规则】配置匹配条件。
          </div>
          <div class="form-hint" style="margin-top:10px">
            节点拉取入口: <code>GET /firmware/manifest.json</code>
          </div>
        </el-card>
      </el-tab-pane>

    </el-tabs>

    <!-- ── 固件上传对话框 ─────────────────────────────────────────────── -->
    <el-dialog v-model="firmwareUploadVisible" title="上传固件" width="520px">
      <el-form :model="firmwareUploadForm" label-width="100px" size="small">
        <el-form-item label="厂商" required>
          <el-input v-model="firmwareUploadForm.vendor" placeholder="如 mellanox / huawei / intel" />
        </el-form-item>
        <el-form-item label="型号" required>
          <el-input v-model="firmwareUploadForm.model" placeholder="如 ConnectX-5 / hinic_4x25GE" />
        </el-form-item>
        <el-form-item label="版本" required>
          <el-input v-model="firmwareUploadForm.version" placeholder="如 22.36.1010" />
        </el-form-item>
        <el-form-item label="固件文件" required>
          <input ref="firmwareFileInput" type="file" />
        </el-form-item>
        <el-alert type="info" :closable="false">
          <template #title>
            保存为 <code>firmware/{vendor}/{model}/{version}/{原文件名}</code>;
            上传完自动计算 SHA256
          </template>
        </el-alert>
      </el-form>
      <template #footer>
        <el-button @click="firmwareUploadVisible = false">取消</el-button>
        <el-button type="primary" @click="uploadFirmware" :loading="uploadingFirmware">上传</el-button>
      </template>
    </el-dialog>

    <!-- ── BMC 发现对话框 ─────────────────────────────────────────────── -->
    <el-dialog v-model="discoverDialogVisible" title="BMC 节点发现" width="460px">
      <el-form :model="discoverForm" label-width="100px">
        <el-form-item label="子网范围">
          <el-input v-model="discoverForm.subnet" placeholder="例如: 172.16.0.0/24" />
        </el-form-item>
        <el-form-item label="超时时间(s)">
          <el-input-number v-model="discoverForm.timeout" :min="1" :max="60" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="discoverDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="startDiscover" :loading="discovering">开始扫描</el-button>
      </template>
    </el-dialog>

    <!-- ── PXE Host 配置对话框 ────────────────────────────────────────── -->
    <el-dialog v-model="pxeHostEditVisible" title="PXE Host 自部署配置" width="640px" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" style="margin-bottom:14px">
        <template #title>
          管理站（Windows）通过 BMC Redfish 把本地 ISO 挂为虚拟光驱，触发 PXE Host
          一次性 CD 引导完成自动装机
        </template>
      </el-alert>
      <el-form :model="pxeHostForm" label-width="120px" size="small">
        <el-divider content-position="left">基本</el-divider>
        <el-form-item label="主机名">
          <el-input v-model="pxeHostForm.hostname" style="width:230px" />
        </el-form-item>
        <el-form-item label="控制面 IP">
          <el-input v-model="pxeHostForm.ctrl_ip" placeholder="172.16.3.10" style="width:230px" />
        </el-form-item>

        <el-divider content-position="left">BMC / Redfish</el-divider>
        <el-form-item label="BMC IP">
          <el-input v-model="pxeHostForm.bmc_ip" placeholder="172.16.0.10" style="width:230px" />
        </el-form-item>
        <el-form-item label="BMC 用户">
          <el-input v-model="pxeHostForm.bmc_user" style="width:200px" />
        </el-form-item>
        <el-form-item label="BMC 密码">
          <el-input v-model="pxeHostForm.bmc_password" type="password" show-password
            placeholder="留空保持原值" style="width:230px" />
        </el-form-item>
        <el-form-item label="Manager ID">
          <el-input v-model="pxeHostForm.redfish_manager_id" style="width:120px" />
          <span class="form-hint">华为 iBMC 通常为 1，Dell 为 iDRAC.Embedded.1</span>
        </el-form-item>
        <el-form-item label="System ID">
          <el-input v-model="pxeHostForm.redfish_system_id" style="width:120px" />
        </el-form-item>
        <el-form-item label="VirtualMedia ID">
          <el-input v-model="pxeHostForm.redfish_virtual_media_id" style="width:120px" />
          <span class="form-hint">华为 CD，Dell CD1，部分厂商为 1/2</span>
        </el-form-item>

        <el-divider content-position="left">ISO 镜像</el-divider>
        <el-form-item label="HTTP 主机">
          <el-input v-model="pxeHostForm.iso_http_host" placeholder="管理站 BMC 可达 IP"
            style="width:200px" />
          <span class="form-hint">Windows 管理站对 BMC 的可达 IP（GE 网卡）</span>
        </el-form-item>
        <el-form-item label="HTTP 端口">
          <el-input-number v-model="pxeHostForm.iso_http_port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="ISO 文件">
          <el-select v-model="pxeHostForm.iso_filename" placeholder="选择 ISO" style="width:280px">
            <el-option v-for="iso in isoList" :key="iso.filename"
              :label="`${iso.filename} (${iso.size_mb} MB)`" :value="iso.filename" />
          </el-select>
          <el-button size="small" style="margin-left:8px" @click="loadIsoList">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <div v-if="isoDir" class="form-hint" style="margin-top:4px">
            扫描目录: <code>{{ isoDir }}</code>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pxeHostEditVisible = false">取消</el-button>
        <el-button type="primary" @click="savePxeHostConfig" :loading="savingPxeHost">保存</el-button>
      </template>
    </el-dialog>

    <!-- ── 单节点部署对话框 ───────────────────────────────────────────── -->
    <el-dialog v-model="deployDialogVisible" title="节点部署配置" width="560px">
      <el-form :model="deployForm" label-width="120px">
        <el-form-item label="主机名">
          <el-input v-model="deployForm.hostname" placeholder="例如: master-01" />
        </el-form-item>
        <el-form-item label="节点类型">
          <el-radio-group v-model="deployForm.node_type">
            <el-radio label="master">Master</el-radio>
            <el-radio label="slave">Slave</el-radio>
            <el-radio label="subswath">SubSwath</el-radio>
            <el-radio label="gstorage">GStorage</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-divider>三平面网络</el-divider>
        <el-form-item label="BMC IP (GE)">
          <el-input v-model="deployForm.mgmt_ip" placeholder="172.16.0.11" />
        </el-form-item>
        <el-form-item label="控制面 (10GE)">
          <el-input v-model="deployForm.ctrl_ip" placeholder="172.16.3.11" />
        </el-form-item>
        <el-form-item label="数据面 (100GE)">
          <el-input v-model="deployForm.data_ip" placeholder="100.1.1.11" />
        </el-form-item>
        <el-alert
          v-if="deployForm.node_type === 'master'"
          type="info" :closable="false"
          title="Master: DPDK 接收 + RDMA 计算控制，需 100G×4 和大页内存"
        />
        <el-alert
          v-if="deployForm.node_type === 'subswath'"
          type="warning" :closable="false"
          title="SubSwath: NFS Server，firstboot 将创建 4×NVMe 软件 RAID10"
        />
      </el-form>
      <template #footer>
        <el-button @click="deployDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="startDeploy" :loading="deploying">开始部署</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Search, Clock, Plus, Minus, Edit, CaretRight } from '@element-plus/icons-vue'

// ── 全局状态 ──────────────────────────────────────────────────────────────────
const activeTab = ref('planning')

// ── Tab1: IP 规划 ─────────────────────────────────────────────────────────────
const planForm = ref({ master_count: 6, slave_count: 12, subswath_count: 2, gstorage_count: 1, acquisition_count: 0 })
const ipPlanResult = ref(null)
const planning = ref(false)
const applyingPlan = ref(false)
const planSaved = ref(false)        // true = ipPlanResult 对应的内容已写入 nodes.json

// 用户改任意 count → 当前预览/已存状态都失效, 需要重新预览或重新应用
watch(planForm, () => { planSaved.value = false }, { deep: true })

async function generatePlan() {
  planning.value = true
  try {
    const res = await axios.post('/api/pxe/network-plan', planForm.value)
    ipPlanResult.value = res.data
    planSaved.value = false         // 仅预览, 未保存
    ElMessage.info(`已生成预览, 共 ${res.data.total_nodes} 个节点。点击【应用规划】写入 nodes.json。`)
  } catch (e) {
    ElMessage.error('规划生成失败: ' + e.message)
  } finally {
    planning.value = false
  }
}

async function applyPlanToNodesJson() {
  const summary = `Master×${planForm.value.master_count} / Slave×${planForm.value.slave_count} / SubSwath×${planForm.value.subswath_count} / GStorage×${planForm.value.gstorage_count} / Acquisition×${planForm.value.acquisition_count}`
  try {
    await ElMessageBox.confirm(
      `将按当前规划保存到 nodes.json: ${summary}\n\n规则:\n` +
      `- 同名节点保留已填写的真实 MAC, IP 字段按本次规划重算\n` +
      `- 新增节点追加 (默认占位 MAC)\n` +
      `- 旧规划中存在但本次不在的节点将被删除 (新规划为唯一来源)\n` +
      `- 节点管理同步:\n` +
      `    · 名称符合规划模板 (master-01 / slave-12 等) 但不在本次规划 → 一并删除\n` +
      `    · 单数字 demo 节点 (master-1) 和自定义主机名 → 不受影响`,
      '确认应用规划',
      { type: 'warning', confirmButtonText: '确认应用', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  applyingPlan.value = true
  try {
    // Step1: regenerate 写入 nodes.json
    const { data } = await axios.post('/api/pxe/nodes-json/regenerate', planForm.value)
    console.log('[apply] regenerate response:', data)

    // Step2: 显式再 sync 一次，确保节点管理页数据与 nodes.json 保持一致
    const syncRes = await axios.post('/api/pxe/nodes-json/sync-to-db')
    const syncData = syncRes.data || {}
    console.log('[apply] sync-to-db response:', syncData)
    const dbCreated = syncData.created ?? 0
    const dbUpdated = syncData.updated ?? 0
    const dbDeleted = syncData.deleted ?? 0
    const dbTotal   = syncData.db_total ?? 0
    const skipped   = syncData.skipped || []
    if (skipped.length) console.warn('[apply] 跳过条目:', skipped)
    if (dbDeleted) console.warn('[apply] 清理规划残留:', syncData.deleted_hostnames)

    // 刷新预览
    try {
      const planRes = await axios.post('/api/pxe/network-plan', planForm.value)
      ipPlanResult.value = planRes.data
    } catch { /* ignore */ }
    planSaved.value = true

    const added   = data.added?.length   ?? 0
    const updated = data.updated?.length ?? 0
    const removed = data.removed?.length ?? 0
    ElMessage.success(
      `nodes.json: 新增 ${added} / 更新 ${updated} / 删除 ${removed}。` +
      `节点管理: 新建 ${dbCreated} / 更新 ${dbUpdated} / 清理残留 ${dbDeleted}, ` +
      `当前 DB 共 ${dbTotal} 个节点。`
    )
    if (skipped.length) {
      ElMessage.warning(`有 ${skipped.length} 条记录被跳过未同步, 详见浏览器控制台 [apply] 跳过条目`)
    }
    await loadNodeList()
    activeTab.value = 'nodes'
  } catch (e) {
    console.error('[apply] 失败:', e.response?.data || e)
    ElMessage.error('应用失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    applyingPlan.value = false
  }
}

// ── Tab2: 节点配置 ────────────────────────────────────────────────────────────
const nodeList = ref([])
const nodeEditVisible = ref(false)
const nodeEditRow = ref({})
const nodeEditForm = ref({ newMac: '', ctrl_nic: '', dpdkPairs: [], rdmaPairs: [] })
const savingNode = ref(false)

async function loadNodeList() {
  try {
    const res = await axios.get('/api/pxe/nodes-json/node-list')
    nodeList.value = res.data
  } catch (e) {
    ElMessage.error('加载节点列表失败')
  }
}

function parsePairs(nics, ips) {
  const nicArr = (nics || '').split(' ').filter(Boolean)
  const ipArr  = (ips  || '').split(' ').filter(Boolean)
  const len = Math.max(nicArr.length, ipArr.length, 1)
  return Array.from({ length: len }, (_, i) => ({ nic: nicArr[i] || '', ip: ipArr[i] || '' }))
}

function openNodeEdit(row) {
  nodeEditRow.value = row
  nodeEditForm.value = {
    newMac:    row.mac,
    ctrl_nic:  row.ctrl_nic || 'eno1',
    dpdkPairs: parsePairs(row.dpdk_nics, row.dpdk_ips),
    rdmaPairs: parsePairs(row.rdma_nics, row.rdma_ips),
  }
  nodeEditVisible.value = true
}

async function saveNodeEdit() {
  savingNode.value = true
  try {
    const row  = nodeEditRow.value
    const form = nodeEditForm.value

    if (form.newMac !== row.mac) {
      await axios.patch('/api/pxe/nodes-json/update-mac', null, {
        params: { old_mac: row.mac, new_mac: form.newMac }
      })
    }

    const effectiveMac = form.newMac
    await axios.patch('/api/pxe/nodes-json/update-node', {
      mac:       effectiveMac,
      ctrl_nic:  form.ctrl_nic  || null,
      dpdk_nics: form.dpdkPairs.map(p => p.nic).filter(Boolean).join(' ') || null,
      dpdk_ips:  form.dpdkPairs.map(p => p.ip ).filter(Boolean).join(' ') || null,
      rdma_nics: form.rdmaPairs.map(p => p.nic).filter(Boolean).join(' ') || null,
      rdma_ips:  form.rdmaPairs.map(p => p.ip ).filter(Boolean).join(' ') || null,
    })

    ElMessage.success('节点配置已更新')
    nodeEditVisible.value = false
    await loadNodeList()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingNode.value = false
  }
}

async function resetToTemplate() {
  try {
    await ElMessageBox.confirm('将重置所有 MAC 为占位符模板值，确认？', '确认重置', { type: 'warning' })
  } catch { return }
  try {
    const res = await axios.get('/api/pxe/nodes-json')
    await axios.post('/api/pxe/nodes-json', res.data)
    ElMessage.success('已重置为模板 MAC')
    await loadNodeList()
  } catch (e) {
    ElMessage.error('重置失败: ' + e.message)
  }
}

// ── Tab3: 配置文件生成 ────────────────────────────────────────────────────────
const dhcpConfig    = ref('')
const grubConfig    = ref('')
const raid1Script   = ref('')
const pxeBootScript = ref('')
const loadingDhcp    = ref(false)
const loadingGrub    = ref(false)
const loadingRaid1   = ref(false)
const loadingPxeBoot = ref(false)

async function fetchDhcpConfig() {
  loadingDhcp.value = true
  try {
    const res = await axios.get('/api/pxe/dhcp-config')
    dhcpConfig.value = res.data
  } catch (e) { ElMessage.error('生成失败') } finally { loadingDhcp.value = false }
}

async function fetchGrubConfig() {
  loadingGrub.value = true
  try {
    const res = await axios.get('/api/pxe/grub-config')
    grubConfig.value = res.data
  } catch (e) { ElMessage.error('生成失败') } finally { loadingGrub.value = false }
}

async function fetchRaid1Script() {
  loadingRaid1.value = true
  try {
    const res = await axios.get('/api/pxe/setup-raid1-script')
    raid1Script.value = res.data
  } catch (e) { ElMessage.error('生成失败') } finally { loadingRaid1.value = false }
}

async function fetchPxeBootScript() {
  loadingPxeBoot.value = true
  try {
    const res = await axios.get('/api/pxe/pxe-boot-script')
    pxeBootScript.value = res.data
  } catch (e) { ElMessage.error('生成失败') } finally { loadingPxeBoot.value = false }
}

function copyText(text) {
  if (!text) return
  navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制到剪贴板'))
}

// ── Tab4: 分批部署 ────────────────────────────────────────────────────────────
const deployingWave = ref(0)
const queryMac = ref('')
const queryingEnv = ref(false)
const nodeEnvResult = ref('')

const WAVE_ROLES = {
  1: ['subswath', 'gstorage'],
  2: ['master'],
  3: ['slave'],
}

function waveNodes(wave) {
  return nodeList.value.filter(n => WAVE_ROLES[wave]?.includes(n.role))
}

// PXE Host 首次装机（Bootstrap，一次性）
const pxeHostCfg = ref({
  hostname: '', bmc_ip: '', ctrl_ip: '',
  iso_http_host: '', iso_http_port: 8000,
  iso_filename: '',
  redfish_manager_id: '1', redfish_system_id: '1', redfish_virtual_media_id: 'CD',
})
const pxeHostEditVisible = ref(false)
const pxeHostForm = ref({})
const savingPxeHost = ref(false)
const installingPxeHost = ref(false)
const isoList = ref([])
const isoDir = ref('')
const bootstrapExpanded = ref(false)
const bootstrapState = ref('not_configured')   // not_configured / not_installed / installing / online / error

const BOOTSTRAP_STATE_LABELS = {
  not_configured: '未配置',
  not_installed:  '已配置，待装机',
  installing:     '装机进行中',
  online:         '已就绪',
  error:          '上次装机失败',
}
const BOOTSTRAP_STATE_COLORS = {
  not_configured: '#94a3b8',
  not_installed:  '#fbbf24',
  installing:     '#3b82f6',
  online:         '#22c55e',
  error:          '#f87171',
}
const bootstrapStateLabel = computed(() => BOOTSTRAP_STATE_LABELS[bootstrapState.value] || bootstrapState.value)
const bootstrapStateColor = computed(() => BOOTSTRAP_STATE_COLORS[bootstrapState.value] || '#94a3b8')

async function loadPxeHostConfig() {
  try {
    const res = await axios.get('/api/pxe/pxe-host/config')
    pxeHostCfg.value = res.data
  } catch {}
}

async function loadBootstrapState() {
  try {
    const res = await axios.get('/api/pxe/pxe-host/status')
    bootstrapState.value = res.data.state
    // 首次状态非 online 时默认展开，节省一步点击
    if (!bootstrapExpanded.value && bootstrapState.value !== 'online') {
      bootstrapExpanded.value = bootstrapState.value === 'not_configured'
                              || bootstrapState.value === 'not_installed'
                              || bootstrapState.value === 'error'
    }
  } catch {}
}

async function installPxeHost(force = false) {
  if (!pxeHostCfg.value.bmc_ip || !pxeHostCfg.value.iso_filename) {
    ElMessage.warning('请先在「配置」中填写 BMC IP 和选择 ISO')
    return
  }
  const warnText = force
    ? `⚠ 即将通过 BMC 强制重装 PXE Host (${pxeHostCfg.value.bmc_ip})，将覆盖现有系统！`
    + `\n这是一次性 Bootstrap 操作，正常运行的 PXE Host 不应频繁触发。\n确认继续？`
    : `将通过 Redfish 给 PXE Host (${pxeHostCfg.value.bmc_ip}) 挂载 ISO `
    + `《${pxeHostCfg.value.iso_filename}》并强制重启进入安装。\n这是一次性首次装机操作，确认继续？`
  try {
    await ElMessageBox.confirm(warnText, force ? '确认强制重装 PXE Host' : '确认首次装机 PXE Host',
      { type: force ? 'error' : 'warning' })
  } catch { return }

  installingPxeHost.value = true
  try {
    const res = await axios.post('/api/pxe/pxe-host/install')
    const rf = res.data.redfish || {}
    if (rf.ok) {
      ElMessage.success('PXE Host 首次装机已触发：BMC 已挂载 ISO 并重启')
    } else {
      ElMessage.error(`Redfish 调用在阶段 [${rf.stage}] 失败，请检查 BMC 凭据 / VirtualMedia ID`)
    }
    await loadBootstrapState()
    activeTab.value = 'status'
    await refreshDeployStatus()
  } catch (e) {
    ElMessage.error('触发失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    installingPxeHost.value = false
  }
}

async function loadIsoList() {
  try {
    const res = await axios.get('/api/pxe/pxe-host/iso-list')
    isoList.value = res.data.files || []
    isoDir.value = res.data.iso_dir || ''
  } catch (e) {
    ElMessage.error('加载 ISO 列表失败: ' + e.message)
  }
}

async function openPxeHostEdit() {
  await Promise.all([loadPxeHostConfig(), loadIsoList()])
  pxeHostForm.value = {
    ...pxeHostCfg.value,
    bmc_password: '',   // 留空表示不修改
  }
  pxeHostEditVisible.value = true
}

async function savePxeHostConfig() {
  savingPxeHost.value = true
  try {
    const payload = { ...pxeHostForm.value }
    if (!payload.bmc_password) delete payload.bmc_password
    await axios.put('/api/pxe/pxe-host/config', payload)
    ElMessage.success('PXE Host 配置已保存')
    pxeHostEditVisible.value = false
    await loadPxeHostConfig()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingPxeHost.value = false
  }
}

async function triggerWaveDeploy(wave) {
  const nodes = waveNodes(wave)
  if (nodes.length === 0) {
    ElMessage.warning('nodes.json 中没有对应角色的节点，请先在「节点配置」标签中检查')
    return
  }
  const roleStr = WAVE_ROLES[wave].join(' + ')
  try {
    await ElMessageBox.confirm(
      `将触发第 ${wave} 批（${roleStr}）共 ${nodes.length} 个节点的 PXE 引导并将其置为部署中状态，确认继续？`,
      `确认触发第 ${wave} 批部署`,
      { type: 'warning' }
    )
  } catch { return }

  deployingWave.value = wave
  try {
    const res = await axios.post(`/api/pxe/wave-deploy/${wave}`)
    ElMessage.success(`第 ${wave} 批（${res.data.triggered} 个节点）部署已触发`)
    activeTab.value = 'status'
    await refreshDeployStatus()
  } catch (e) {
    ElMessage.error('触发失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    deployingWave.value = 0
  }
}

async function queryNodeEnv() {
  if (!queryMac.value) { ElMessage.warning('请输入 MAC 地址') ; return }
  queryingEnv.value = true
  try {
    const res = await axios.get('/api/pxe/node-env', { params: { mac: queryMac.value } })
    nodeEnvResult.value = res.data
  } catch (e) {
    nodeEnvResult.value = ''
    ElMessage.error(e.response?.data?.detail || '未找到该 MAC 的配置')
  } finally {
    queryingEnv.value = false
  }
}

// ── Tab4: 自定义脚本 ──────────────────────────────────────────────────────────
const scriptTargets     = ref([])
const customScript      = ref('')
const scriptSshUser     = ref('root')
const scriptSshPassword = ref('')
const runningScript     = ref(false)
const scriptResult      = ref([])

async function runCustomScript() {
  if (!scriptTargets.value.length) { ElMessage.warning('请选择目标节点'); return }
  if (!customScript.value.trim()) { ElMessage.warning('请输入脚本内容'); return }
  runningScript.value = true
  scriptResult.value = []
  try {
    const res = await axios.post('/api/pxe/run-script', {
      macs:         scriptTargets.value,
      script:       customScript.value,
      ssh_user:     scriptSshUser.value || 'root',
      ssh_password: scriptSshPassword.value || null,
    })
    scriptResult.value = res.data
    const ok = res.data.filter(r => r.status === 'success').length
    ElMessage.success(`脚本执行完成：${ok}/${res.data.length} 个节点成功`)
  } catch (e) {
    ElMessage.error('执行失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    runningScript.value = false
  }
}

// ── Tab5: 状态监控 ────────────────────────────────────────────────────────────
const discoveredNodes      = ref([])
const deployTasks          = ref([])
const discoverDialogVisible = ref(false)
const deployDialogVisible   = ref(false)
const discovering           = ref(false)
const deploying             = ref(false)

const discoverForm = ref({ subnet: '172.16.0.0/24', timeout: 5 })
const deployForm = ref({
  node_id: 0, hostname: '', node_type: 'slave',
  mgmt_ip: '', ctrl_ip: '', data_ip: '',
})

async function startDiscover() {
  discovering.value = true
  try {
    const res = await axios.post('/api/ipmi/discover', discoverForm.value)
    ElMessage.success(`发现 ${res.data.discovered_count || 0} 个 BMC 节点`)
    discoveredNodes.value = res.data.nodes || []
    discoverDialogVisible.value = false
  } catch (e) {
    ElMessage.error('BMC 扫描失败: ' + e.message)
  } finally {
    discovering.value = false
  }
}

function showDeployDialog(row) {
  deployForm.value = {
    node_id: row.id || 0,
    hostname: row.hostname || '',
    node_type: 'slave',
    mgmt_ip: row.bmc_ip || row.mgmt_ip || '',
    ctrl_ip: '',
    data_ip: '',
  }
  deployDialogVisible.value = true
}

async function startDeploy() {
  deploying.value = true
  try {
    await axios.post(`/api/pxe/nodes/${deployForm.value.node_id}/deploy`, deployForm.value)
    ElMessage.success('部署任务已启动')
    deployDialogVisible.value = false
    await refreshDeployStatus()
  } catch (e) {
    ElMessage.error('部署启动失败: ' + e.message)
  } finally {
    deploying.value = false
  }
}

async function refreshDeployStatus() {
  try {
    const res = await axios.get('/api/pxe/status')
    deployTasks.value = res.data
  } catch {}
}

async function checkBMCInfo(row) {
  try {
    const res = await axios.get(`/api/ipmi/nodes/${row.id}/info`)
    ElMessage.info(`BMC 温度: ${res.data.temperature}°C，风扇: ${res.data.fan_speed} RPM`)
  } catch {
    ElMessage.error('获取 BMC 信息失败')
  }
}

// ── Tab6: 固件仓库 ────────────────────────────────────────────────────────────
const firmwareList = ref([])
const firmwareDir  = ref('')
const manifestRules = ref([])
const savingManifest = ref(false)
const firmwareUploadVisible = ref(false)
const uploadingFirmware = ref(false)
const firmwareFileInput = ref(null)
const firmwareUploadForm = ref({ vendor: '', model: '', version: '' })

async function loadFirmwareList() {
  try {
    const { data } = await axios.get('/api/firmware/list')
    firmwareList.value = data.items || []
    firmwareDir.value  = data.firmware_dir || ''
  } catch (e) {
    ElMessage.error('加载固件列表失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadFirmwareManifest() {
  try {
    const { data } = await axios.get('/api/firmware/manifest')
    manifestRules.value = (data.rules || []).map(r => ({
      enabled: r.enabled !== false,
      match_vendor_id: r.match?.vendor_id || '',
      match_device_id: r.match?.device_id || '',
      name: r.name || '',
      target_fw: r.target_fw || '',
      image: r.image || '',
      tool: r.tool || 'mstflint',
      flash_cmd: r.flash_cmd || '',
      query_cmd: r.query_cmd || '',
      post_action: r.post_action || 'cold_reboot',
    }))
  } catch (e) {
    ElMessage.error('加载 manifest 失败: ' + (e.response?.data?.detail || e.message))
  }
}

function addManifestRule() {
  manifestRules.value.push({
    enabled: true,
    match_vendor_id: '',
    match_device_id: '',
    name: '',
    target_fw: '',
    image: '',
    tool: 'mstflint',
    flash_cmd: 'mstflint -d {pci} -i {image} -y burn',
    query_cmd: "mstflint -d {pci} q | awk '/FW Version:/{print $3}'",
    post_action: 'cold_reboot',
  })
}

function removeManifestRule(idx) {
  manifestRules.value.splice(idx, 1)
}

function useFirmwareInRule(row) {
  // 给一条新规则预填 image + 名称模板, 用户再补 vendor/device id
  manifestRules.value.push({
    enabled: true,
    match_vendor_id: '',
    match_device_id: '',
    name: `${row.vendor} ${row.model}`,
    target_fw: row.version,
    image: row.rel_path,
    tool: 'mstflint',
    flash_cmd: 'mstflint -d {pci} -i {image} -y burn',
    query_cmd: "mstflint -d {pci} q | awk '/FW Version:/{print $3}'",
    post_action: 'cold_reboot',
  })
  ElMessage.success(`已添加规则草稿, 请补充 vendor_id / device_id`)
}

async function saveFirmwareManifest() {
  // 简单校验: vendor_id / device_id 都是 4 位 16 进制
  for (const r of manifestRules.value) {
    if (!/^[0-9a-fA-F]{4}$/.test(r.match_vendor_id) || !/^[0-9a-fA-F]{4}$/.test(r.match_device_id)) {
      ElMessage.error(`规则 "${r.name || '(未命名)'}" 的 vendor_id/device_id 必须是 4 位 16 进制`)
      return
    }
    if (!r.image) {
      ElMessage.error(`规则 "${r.name || '(未命名)'}" 未选择固件文件`)
      return
    }
  }
  savingManifest.value = true
  try {
    const { data } = await axios.put('/api/firmware/manifest', { rules: manifestRules.value })
    ElMessage.success(`已保存 ${data.rule_count} 条规则`)
    await loadFirmwareList()   // 刷新引用标记
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingManifest.value = false
  }
}

async function uploadFirmware() {
  const f = firmwareFileInput.value?.files?.[0]
  const { vendor, model, version } = firmwareUploadForm.value
  if (!vendor || !model || !version) {
    ElMessage.warning('请填写厂商 / 型号 / 版本')
    return
  }
  if (!f) {
    ElMessage.warning('请选择固件文件')
    return
  }
  const fd = new FormData()
  fd.append('vendor', vendor)
  fd.append('model', model)
  fd.append('version', version)
  fd.append('file', f)
  uploadingFirmware.value = true
  try {
    const { data } = await axios.post('/api/firmware/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success(`上传成功: ${data.rel_path}`)
    firmwareUploadVisible.value = false
    firmwareUploadForm.value = { vendor: '', model: '', version: '' }
    if (firmwareFileInput.value) firmwareFileInput.value.value = ''
    await loadFirmwareList()
  } catch (e) {
    ElMessage.error('上传失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    uploadingFirmware.value = false
  }
}

async function deleteFirmware(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除固件文件: ${row.rel_path}?\n如有规则引用此文件, 保存 manifest 时会报错。`,
      '删除固件', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }
  try {
    await axios.delete('/api/firmware/file', { params: { rel_path: row.rel_path } })
    ElMessage.success('已删除')
    await loadFirmwareList()
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

watch(activeTab, async (tab) => {
  if (tab === 'firmware' && !firmwareList.value.length) {
    await Promise.all([loadFirmwareList(), loadFirmwareManifest()])
  }
})

// ── 工具函数 ──────────────────────────────────────────────────────────────────
function roleTagType(role) {
  return { master: 'success', slave: 'primary', subswath: 'warning', gstorage: 'danger', acquisition: '', pxe_host: 'info' }[role] ?? 'info'
}

function statusTagType(status) {
  return { online: 'success', completed: 'success', deploying: 'warning', installing: 'warning', error: 'danger', offline: 'danger' }[status] || 'info'
}

// ── 初始化 ────────────────────────────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([
    loadNodeList(),
    refreshDeployStatus(),
    loadPxeHostConfig(),
    loadBootstrapState(),
  ])
})
</script>

<style scoped>
.pxe-deploy { display: flex; flex-direction: column; gap: 0; }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

/* 角色标签 */
.role-tag {
  font-weight: 600;
  font-size: 14px;
}
.role-host    { color: #909399; }
.role-master  { color: #67c23a; }
.role-slave   { color: #409eff; }
.role-subswath { color: #e6a23c; }
.role-gstorage { color: #f56c6c; }

/* 节点列表 */
.mac-text { font-family: monospace; font-size: 12px; color: #a0a0a0; }
.text-muted { color: #555; font-size: 12px; }

/* 代码区域 */
.code-textarea :deep(textarea) {
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  background: #1e1e1e;
  color: #d4d4d4;
}
.code-block {
  background: #1e1e1e;
  color: #9cdcfe;
  padding: 12px 16px;
  border-radius: 4px;
  font-size: 13px;
  font-family: 'Consolas', 'Courier New', monospace;
  overflow-x: auto;
  margin: 8px 0 0;
}

/* 分批部署 */
.wave-card { height: 100%; }
.wave-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}
.wave-nodes {
  max-height: 220px;
  overflow-y: auto;
  margin-bottom: 8px;
}
.wave-node-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 13px;
}
.node-name { flex: 1; font-weight: 500; }
.node-bmc  { color: #777; font-size: 12px; font-family: monospace; }
.wave-meta { color: #888; font-size: 12px; display: flex; align-items: center; gap: 4px; }
.wave-check {
  background: #1a1a1a;
  border-radius: 4px;
  padding: 8px 10px;
  font-size: 12px;
  color: #aaa;
}
.wave-check code {
  display: block;
  color: #9cdcfe;
  font-family: monospace;
  margin-top: 3px;
}

.stage-text { margin-left: 8px; font-size: 12px; color: #aaa; }
.ip-text    { font-family: monospace; font-size: 12px; color: #93c5fd; }

.bootstrap-card {
  border-left: 2px solid #475569;
  background: rgba(15, 23, 42, 0.4);
}
.bootstrap-card :deep(.el-card__body) { padding: 0; }
.bootstrap-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.bootstrap-header:hover { background: rgba(255,255,255,0.03); }
.bootstrap-header .caret {
  transition: transform 0.2s;
  color: #64748b;
  font-size: 14px;
}
.bootstrap-header .caret.rotated { transform: rotate(90deg); }
.bootstrap-title {
  font-size: 14px;
  font-weight: 600;
  color: #cbd5e1;
}
.bootstrap-status {
  font-size: 12px;
  font-weight: 500;
}
.bootstrap-body {
  padding: 8px 16px 16px;
  border-top: 1px solid #1e293b;
}
.redfish-path {
  background: #0d1b2e;
  color: #9cdcfe;
  font-family: 'Consolas', monospace;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 11px;
}
.form-hint {
  color: #64748b;
  font-size: 11px;
  margin-left: 10px;
}

/* ── 暗色 Tab ── */
.dark-tabs.el-tabs--border-card {
  border: 1px solid #1e293b;
  background: transparent;
}
.dark-tabs :deep(.el-tabs__header) {
  background: #0f172a;
  border-bottom: 1px solid #1e293b;
}
.dark-tabs :deep(.el-tabs__item) {
  color: #64748b;
  border-right: 1px solid #1e293b !important;
  transition: color 0.2s, background 0.2s;
}
.dark-tabs :deep(.el-tabs__item:hover) {
  color: #93c5fd;
}
.dark-tabs :deep(.el-tabs__item.is-active) {
  color: #3b82f6;
  background: #1e293b;
  border-bottom-color: #1e293b !important;
}
.dark-tabs :deep(.el-tabs__content) {
  background: transparent;
  padding: 16px 0 0;
}

/* ── 全局暗色表格（覆盖 Element Plus 默认白色） ── */
.pxe-deploy :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: #0d1b2e;
  --el-table-row-hover-bg-color: #1e3a5f;
  --el-table-current-row-bg-color: #1e3a5f;
  --el-table-border-color: #1e293b;
  --el-table-text-color: #cbd5e1;
  --el-table-header-text-color: #64748b;
  --el-fill-color-light: rgba(255, 255, 255, 0.025);
  background-color: transparent;
}
.pxe-deploy :deep(.el-table th.el-table__cell) {
  background-color: #0d1b2e !important;
  color: #64748b;
  border-bottom-color: #1e293b;
}
.pxe-deploy :deep(.el-table td.el-table__cell) {
  background-color: transparent !important;
  border-bottom-color: #1e293b;
  color: #cbd5e1;
}
.pxe-deploy :deep(.el-table tr) {
  background-color: transparent !important;
}
.pxe-deploy :deep(.el-table__body tr:hover > td.el-table__cell) {
  background-color: #1e3a5f !important;
}
.pxe-deploy :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background-color: rgba(255, 255, 255, 0.025) !important;
}
.pxe-deploy :deep(.el-table__inner-wrapper::before),
.pxe-deploy :deep(.el-table__border-left-patch) {
  background-color: #1e293b;
}
.pxe-deploy :deep(.el-table__empty-block) {
  background-color: transparent;
}

/* ── NIC 编辑行 ── */
.nic-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding-left: 110px;
}
.nic-idx {
  color: #64748b;
  font-size: 12px;
  width: 16px;
  text-align: right;
}
.nic-add-row {
  padding-left: 110px;
  margin-bottom: 6px;
}

/* ── 对话框内 el-divider 暗色 ── */
.pxe-deploy :deep(.el-dialog .el-divider) {
  border-top-color: #1e293b;
}
.pxe-deploy :deep(.el-dialog .el-divider__text) {
  background-color: #1a2744;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

/* ── el-descriptions 暗色（全局卡片内） ── */
.pxe-deploy :deep(.el-descriptions__label) {
  background-color: #0d1b2e !important;
  color: #64748b !important;
}
.pxe-deploy :deep(.el-descriptions__content) {
  background-color: #0a1628 !important;
  color: #cbd5e1 !important;
}
.pxe-deploy :deep(.el-descriptions__cell) {
  border-color: #1e293b !important;
}
/* bootstrap-body 内的 el-descriptions 使用更深的底色与卡片匹配 */
.pxe-deploy :deep(.bootstrap-body .el-descriptions__label),
.pxe-deploy :deep(.bootstrap-body .el-descriptions__content) {
  background-color: #060e1c !important;
}
.pxe-deploy :deep(.bootstrap-body .el-descriptions .el-descriptions__body) {
  background-color: transparent !important;
}

/* ── acquisition 角色标签色 ── */
.role-acquisition { color: #22d3ee; }

/* ── 脚本输出 ── */
.script-output {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 11px;
  font-family: 'Consolas', monospace;
  color: #94a3b8;
  margin: 0;
  max-height: 80px;
  overflow-y: auto;
}
</style>
