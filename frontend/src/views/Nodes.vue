<template>
  <div class="nodes-view">
    <!-- 节点列表 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span>节点列表 (三平面网络)</span>
          <div class="header-actions">
            <el-select v-model="filterType" placeholder="节点类型" clearable style="width: 130px">
              <el-option label="Master" value="master" />
              <el-option label="Slave" value="slave" />
              <el-option label="SubSwath" value="subswath" />
              <el-option label="GStorage" value="gstorage" />
              <el-option label="Sensor" value="sensor" />
            </el-select>
            <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 100px">
              <el-option label="在线" value="online" />
              <el-option label="离线" value="offline" />
              <el-option label="告警" value="warning" />
            </el-select>
            <el-button type="primary" @click="loadNodes">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <el-button type="warning" @click="forceSyncFromJson" :loading="syncing">
              从规划重新同步
            </el-button>
            <el-button type="info" @click="openDebug">
              诊断
            </el-button>
            <el-button type="success" @click="openAdd">
              <el-icon><Plus /></el-icon>
              新增节点
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="filteredNodes" stripe>
        <el-table-column prop="hostname" label="主机名" width="130" />
        <el-table-column label="类型 / 角色" width="110">
          <template #default="{ row }">
            <el-tag :type="nodeTypeTag(row.node_type)" size="small">{{ row.node_type }}</el-tag>
            <div v-if="row.role" class="role-text">{{ row.role }}</div>
          </template>
        </el-table-column>
        <el-table-column label="管理面 (GE)" width="180">
          <template #default="{ row }">
            <div class="plane-info">
              <span class="ip">{{ row.mgmt_ip || '-' }}</span>
              <el-tag :type="getStatusType(row.status)" size="small">{{ row.status }}</el-tag>
            </div>
            <div class="sub-info">BMC: {{ row.bmc_ip || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="控制面 (10GE)" width="150">
          <template #default="{ row }">
            <div class="plane-info">
              <span class="ip">{{ row.ctrl_ip || '-' }}</span>
              <el-tag :type="getStatusType(row.ctrl_status)" size="small">
                {{ row.ctrl_status || 'offline' }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="数据面 (100GE)" width="180">
          <template #default="{ row }">
            <div class="plane-info">
              <span class="ip">{{ row.data_ip || '-' }}</span>
              <el-tag :type="getStatusType(row.data_status)" size="small">
                {{ row.data_status || 'offline' }}
              </el-tag>
            </div>
            <div class="sub-info">{{ row.data_protocol || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="os_version" label="系统版本" width="130" />
        <el-table-column label="配置" width="150">
          <template #default="{ row }">
            <span>{{ row.cpu_cores || '-' }}核 / {{ row.memory_gb || '-' }}G / {{ row.disk_gb || '-' }}G</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" @click="checkNetwork(row)">网络检查</el-button>
            <el-button size="small" type="warning" @click="showPowerDialog(row)">电源</el-button>
            <el-button size="small" type="danger" @click="deleteNode(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增 / 编辑节点对话框 -->
    <el-dialog
      v-model="editDialogVisible"
      :title="editMode === 'add' ? '新增节点' : '编辑节点'"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-form :model="editForm" :rules="editRules" ref="editFormRef" label-width="110px" size="default">

        <el-divider content-position="left">基本信息</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="主机名" prop="hostname">
              <el-input v-model="editForm.hostname" placeholder="如 master-01" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="节点类型" prop="node_type">
              <el-select v-model="editForm.node_type" style="width:100%">
                <el-option label="Master" value="master" />
                <el-option label="Slave" value="slave" />
                <el-option label="SubSwath" value="subswath" />
                <el-option label="GStorage" value="gstorage" />
                <el-option label="Sensor" value="sensor" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="角色">
              <el-input v-model="editForm.role" placeholder="可选，如 compute" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">管理面 (GE)</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="管理面 IP">
              <el-input v-model="editForm.mgmt_ip" placeholder="172.16.0.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="管理面 MAC">
              <el-input v-model="editForm.mgmt_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="BMC IP">
              <el-input v-model="editForm.bmc_ip" placeholder="172.16.0.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="BMC MAC">
              <el-input v-model="editForm.bmc_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">控制面 (10GE)</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="控制面 IP">
              <el-input v-model="editForm.ctrl_ip" placeholder="172.16.3.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="控制面 MAC">
              <el-input v-model="editForm.ctrl_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">数据面 (100GE)</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="数据面 IP">
              <el-input v-model="editForm.data_ip" placeholder="200.1.1.x / 100.1.1.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="数据面 MAC">
              <el-input v-model="editForm.data_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="数据协议">
              <el-select v-model="editForm.data_protocol" clearable style="width:100%">
                <el-option label="DPDK" value="DPDK" />
                <el-option label="RDMA" value="RDMA" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">硬件信息</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="系统版本">
              <el-input v-model="editForm.os_version" placeholder="OpenEuler 22.03" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="CPU 核数">
              <el-input-number v-model="editForm.cpu_cores" :min="1" :precision="0" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="内存 (GB)">
              <el-input-number v-model="editForm.memory_gb" :min="1" :precision="0" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="磁盘 (GB)">
              <el-input-number v-model="editForm.disk_gb" :min="1" :precision="0" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>

      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveNode" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 电源控制对话框 -->
    <el-dialog v-model="powerDialogVisible" title="电源控制" width="400px">
      <div class="power-controls">
        <p>节点: {{ selectedNode?.hostname }}</p>
        <p>BMC: {{ selectedNode?.bmc_ip }}</p>
        <div class="power-buttons">
          <el-button type="success" @click="powerControl('on')">开机</el-button>
          <el-button type="danger" @click="powerControl('off')">关机</el-button>
          <el-button type="warning" @click="powerControl('reset')">重启</el-button>
          <el-button @click="powerControl('status')">查询状态</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 网络检查结果对话框 -->
    <el-dialog v-model="networkDialogVisible" title="三平面网络检查" width="500px">
      <div v-if="networkCheckResult" class="network-result">
        <div class="plane-check">
          <h4>管理面 (GE口)</h4>
          <p>IP: {{ networkCheckResult.planes.management.ip }}</p>
          <p>BMC IP: {{ networkCheckResult.planes.management.bmc_ip }}</p>
          <el-tag :type="networkCheckResult.planes.management.reachable ? 'success' : 'danger'">
            {{ networkCheckResult.planes.management.reachable ? '可达' : '不可达' }}
          </el-tag>
          <span v-if="networkCheckResult.planes.management.latency_ms">
            延迟: {{ networkCheckResult.planes.management.latency_ms }}ms
          </span>
        </div>
        <div class="plane-check">
          <h4>控制面 (10GE)</h4>
          <p>IP: {{ networkCheckResult.planes.control.ip }}</p>
          <el-tag :type="networkCheckResult.planes.control.reachable ? 'success' : 'danger'">
            {{ networkCheckResult.planes.control.reachable ? '可达' : '不可达' }}
          </el-tag>
          <span v-if="networkCheckResult.planes.control.latency_ms">
            延迟: {{ networkCheckResult.planes.control.latency_ms }}ms
          </span>
        </div>
        <div class="plane-check">
          <h4>数据面 (100GE)</h4>
          <p>IP: {{ networkCheckResult.planes.data.ip }}</p>
          <p>协议: {{ networkCheckResult.planes.data.protocol }}</p>
          <el-tag :type="networkCheckResult.planes.data.reachable ? 'success' : 'danger'">
            {{ networkCheckResult.planes.data.reachable ? '可达' : '不可达' }}
          </el-tag>
          <span v-if="networkCheckResult.planes.data.throughput_mbps">
            吞吐: {{ networkCheckResult.planes.data.throughput_mbps }}Mbps
          </span>
        </div>
      </div>
    </el-dialog>

    <!-- ══ 诊断面板 ══ -->
    <el-dialog v-model="debugDialogVisible" title="同步诊断" width="900px" top="5vh">
      <div v-if="debugLoading" style="padding:24px;text-align:center;color:#a0a0a0">加载中...</div>
      <div v-else-if="debugData" class="debug-panel">
        <el-alert
          :type="debugData.db.raw_count === debugData.nodes_json.entries ? 'success' : 'warning'"
          :title="`nodes.json: ${debugData.nodes_json.entries} 个节点 | DB(SQL): ${debugData.db.raw_count} | DB(ORM): ${debugData.db.orm_count}`"
          :closable="false"
          show-icon
          style="margin-bottom:14px"
        />
        <div class="debug-paths">
          <div><b>数据库文件</b>：<code>{{ debugData.database_path }}</code></div>
          <div><b>nodes.json</b>：<code>{{ debugData.nodes_json_path }}</code></div>
        </div>

        <el-collapse>
          <el-collapse-item :title="`nodes.json 中的 ${debugData.nodes_json.entries} 个节点`" name="nj">
            <el-table :data="debugData.nodes_json.hostnames" size="small" max-height="220">
              <el-table-column prop="hostname" label="主机名" width="160" />
              <el-table-column prop="role" label="角色" width="120" />
              <el-table-column prop="mac" label="MAC" />
            </el-table>
          </el-collapse-item>

          <el-collapse-item :title="`DB 中的 ${debugData.db.orm_count} 个节点 (ORM 解析后)`" name="db">
            <el-table :data="debugData.db.nodes" size="small" max-height="220">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="hostname" label="主机名" width="140" />
              <el-table-column prop="node_type" label="类型" width="100" />
              <el-table-column prop="status" label="状态" width="80" />
              <el-table-column prop="ctrl_ip" label="ctrl_ip" />
              <el-table-column prop="bmc_ip" label="bmc_ip" />
            </el-table>
            <div v-if="debugData.db.error" class="debug-err">DB 错误: {{ debugData.db.error }}</div>
          </el-collapse-item>

          <el-collapse-item :title="`nodes 表实际列 (${debugData.db.columns.length})`" name="cols">
            <code style="word-break:break-all;color:#8b949e">{{ debugData.db.columns.join(', ') }}</code>
            <div v-if="debugData.db.columns_error" class="debug-err">{{ debugData.db.columns_error }}</div>
          </el-collapse-item>
        </el-collapse>

        <div v-if="debugData.db.raw_count !== debugData.nodes_json.entries" class="debug-hint">
          <strong>判读：</strong>
          <ul>
            <li v-if="debugData.db.raw_count === 0">DB 真的是空的——sync 没有写入任何节点。可能原因：sync 调用根本没跑（旧后端未重启）、或 sync 内每条都抛了异常（看后端控制台 [sync][error] 日志）</li>
            <li v-else-if="debugData.db.raw_count !== debugData.db.orm_count">SQL count 和 ORM count 对不上——response_model 验证可能因某节点字段不合规失败</li>
            <li v-else>DB 有数据但前端没显示——刷新页面或检查 GET /api/nodes 返回</li>
          </ul>
        </div>
      </div>
      <div v-else class="debug-err">加载诊断信息失败</div>
      <template #footer>
        <el-button @click="loadDebug" :loading="debugLoading">重新加载</el-button>
        <el-button @click="debugDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Refresh, Plus } from '@element-plus/icons-vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const nodes = ref([])
const filterType = ref('')
const filterStatus = ref('')
const selectedNode = ref(null)

const powerDialogVisible = ref(false)
const networkDialogVisible = ref(false)
const networkCheckResult = ref(null)

// ── 新增/编辑 ─────────────────────────────────────────────────
const editDialogVisible = ref(false)
const editMode = ref('add')
const editFormRef = ref(null)
const saving = ref(false)

const emptyForm = () => ({
  hostname: '',
  node_type: 'slave',
  role: '',
  mgmt_ip: '',
  mgmt_mac: '',
  bmc_ip: '',
  bmc_mac: '',
  ctrl_ip: '',
  ctrl_mac: '',
  data_ip: '',
  data_mac: '',
  data_protocol: '',
  os_version: '',
  cpu_cores: null,
  memory_gb: null,
  disk_gb: null,
})

const editForm = ref(emptyForm())

const editRules = {
  hostname: [{ required: true, message: '请输入主机名', trigger: 'blur' }],
  node_type: [{ required: true, message: '请选择节点类型', trigger: 'change' }],
}

const openAdd = () => {
  editMode.value = 'add'
  editForm.value = emptyForm()
  editDialogVisible.value = true
}

const openEdit = (node) => {
  editMode.value = 'edit'
  editForm.value = { ...node }
  editDialogVisible.value = true
}

const saveNode = async () => {
  try {
    await editFormRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = { ...editForm.value }
    // 清理空字符串为 null，避免覆盖已有数据
    Object.keys(payload).forEach(k => {
      if (payload[k] === '') payload[k] = null
    })
    if (editMode.value === 'add') {
      await axios.post('/api/nodes', payload)
      ElMessage.success('节点已新增')
    } else {
      await axios.put(`/api/nodes/${editForm.value.id}`, payload)
      ElMessage.success('节点已更新')
    }
    editDialogVisible.value = false
    loadNodes()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

const deleteNode = async (node) => {
  try {
    await ElMessageBox.confirm(
      `确认删除节点 "${node.hostname}"？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await axios.delete(`/api/nodes/${node.id}`)
    ElMessage.success('节点已删除')
    loadNodes()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

// ── 筛选 ──────────────────────────────────────────────────────
const filteredNodes = computed(() => {
  let result = nodes.value
  if (filterType.value) result = result.filter(n => n.node_type === filterType.value)
  if (filterStatus.value) result = result.filter(n => n.status === filterStatus.value)
  return result
})

// ── 样式辅助 ──────────────────────────────────────────────────
const nodeTypeTag = (type) => {
  const map = { master: 'danger', slave: 'info', subswath: 'warning', gstorage: 'success', sensor: '' }
  return map[type] ?? 'info'
}

const getStatusType = (status) => {
  const map = { online: 'success', offline: 'danger', warning: 'warning', deploying: 'info', error: 'danger' }
  return map[status] ?? 'info'
}

// ── 数据加载 ──────────────────────────────────────────────────
const loadNodes = async () => {
  try {
    const response = await axios.get('/api/nodes')
    nodes.value = response.data
  } catch (e) {
    ElMessage.error('获取节点列表失败')
  }
}

// ── 诊断面板 ────────────────────────────────────────────────
const debugDialogVisible = ref(false)
const debugLoading = ref(false)
const debugData = ref(null)
const openDebug = () => {
  debugDialogVisible.value = true
  loadDebug()
}
const loadDebug = async () => {
  debugLoading.value = true
  try {
    const res = await axios.get('/api/pxe/debug-state')
    debugData.value = res.data
  } catch (e) {
    debugData.value = null
    ElMessage.error('加载诊断失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    debugLoading.value = false
  }
}

// 从 pxe_data/nodes.json 强制同步到 DB (作为 IP 规划落库的应急/手动入口)
const syncing = ref(false)
const forceSyncFromJson = async () => {
  syncing.value = true
  try {
    const res = await axios.post('/api/pxe/nodes-json/sync-to-db')
    const d = res.data || {}
    ElMessage.success(
      `同步完成: 新建 ${d.created || 0} / 更新 ${d.updated || 0} / ` +
      `清理残留 ${d.deleted || 0}, 数据库共 ${d.db_total || 0} 个节点`
    )
    if (d.deleted && d.deleted_hostnames?.length) {
      console.warn('[sync] 清理规划残留:', d.deleted_hostnames)
    }
    if (d.skipped && d.skipped.length) {
      console.warn('[sync] 跳过的条目:', d.skipped)
      ElMessage.warning(`有 ${d.skipped.length} 个条目被跳过, 详见控制台`)
    }
    await loadNodes()
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    syncing.value = false
  }
}

// ── 电源控制 ──────────────────────────────────────────────────
const showPowerDialog = (node) => {
  selectedNode.value = node
  powerDialogVisible.value = true
}

const powerControl = async (action) => {
  if (!selectedNode.value) return
  try {
    const response = await axios.post(`/api/ipmi/nodes/${selectedNode.value.id}/power`, { action })
    ElMessage.success(`电源操作成功: ${response.data.power_status}`)
  } catch (e) {
    ElMessage.error('电源操作失败')
  }
}

// ── 网络检查 ──────────────────────────────────────────────────
const checkNetwork = async (node) => {
  selectedNode.value = node
  try {
    const response = await axios.post(`/api/network/check/${node.id}`)
    networkCheckResult.value = response.data
    networkDialogVisible.value = true
  } catch (e) {
    ElMessage.error('网络检查失败')
  }
}

onMounted(() => {
  loadNodes()
})
</script>

<style scoped>
.nodes-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.debug-panel { font-size: 13px; }
.debug-paths { padding: 8px 12px; background: #0d1b2e; border-radius: 4px; margin-bottom: 12px; line-height: 1.8; }
.debug-paths code { color: #79c0ff; font-size: 12px; }
.debug-err { color: #ff7b7b; margin-top: 8px; font-size: 12px; }
.debug-hint { margin-top: 12px; padding: 10px 14px; background: #2a1f0a; border-left: 3px solid #e0a64b; border-radius: 4px; }
.debug-hint ul { margin: 6px 0 0 0; padding-left: 22px; color: #d0d0d0; }
.debug-hint li { margin: 4px 0; }

.header-actions {
  display: flex;
  gap: 10px;
}

.plane-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.plane-info .ip {
  color: #fff;
  font-size: 13px;
}

.sub-info {
  color: #a0a0a0;
  font-size: 12px;
  margin-top: 4px;
}

.role-text {
  color: #a0a0a0;
  font-size: 11px;
  margin-top: 3px;
}

.power-controls {
  text-align: center;
}

.power-controls p {
  color: #fff;
  margin: 10px 0;
}

.power-buttons {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 20px;
}

.network-result {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.plane-check {
  padding: 15px;
  background: #0f3460;
  border-radius: 8px;
}

.plane-check h4 {
  color: #e94560;
  margin: 0 0 10px 0;
}

.plane-check p {
  color: #fff;
  margin: 5px 0;
}

/* ── 暗色表格 ── */
.nodes-view :deep(.el-table) {
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
.nodes-view :deep(.el-table th.el-table__cell) {
  background-color: #0d1b2e !important;
  color: #64748b;
  border-bottom-color: #1e293b;
}
.nodes-view :deep(.el-table td.el-table__cell) {
  background-color: transparent !important;
  border-bottom-color: #1e293b;
  color: #cbd5e1;
}
.nodes-view :deep(.el-table tr) {
  background-color: transparent !important;
}
.nodes-view :deep(.el-table__body tr:hover > td.el-table__cell) {
  background-color: #1e3a5f !important;
}
.nodes-view :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background-color: rgba(255, 255, 255, 0.025) !important;
}
.nodes-view :deep(.el-table__inner-wrapper::before),
.nodes-view :deep(.el-table__border-left-patch) {
  background-color: #1e293b;
}
.nodes-view :deep(.el-table__empty-block) {
  background-color: transparent;
}

/* ── 编辑对话框 el-divider 暗色 ── */
.nodes-view :deep(.el-dialog .el-divider) {
  border-top-color: #1e293b;
}
.nodes-view :deep(.el-dialog .el-divider__text) {
  background-color: #1a2744;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}
</style>
