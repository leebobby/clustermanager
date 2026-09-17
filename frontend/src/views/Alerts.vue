<template>
  <div class="alerts-view">
    <!-- 告警统计 -->
    <el-card>
      <template #header>
        <span>告警统计 (三平面)</span>
      </template>
      <el-row :gutter="20">
        <el-col :span="3">
          <div class="stat-box critical">
            <span class="value">{{ alertStats.critical }}</span>
            <span class="label">严重</span>
          </div>
        </el-col>
        <el-col :span="3">
          <div class="stat-box warning">
            <span class="value">{{ alertStats.warning }}</span>
            <span class="label">警告</span>
          </div>
        </el-col>
        <el-col :span="3">
          <div class="stat-box info">
            <span class="value">{{ alertStats.info }}</span>
            <span class="label">提示</span>
          </div>
        </el-col>
        <el-col :span="3">
          <div class="stat-box active">
            <span class="value">{{ alertStats.active }}</span>
            <span class="label">活跃</span>
          </div>
        </el-col>
        <el-col :span="3">
          <div class="stat-box resolved">
            <span class="value">{{ alertStats.resolved }}</span>
            <span class="label">已解决</span>
          </div>
        </el-col>
      </el-row>

      <!-- 按平面统计 -->
      <div class="plane-stats">
        <span class="plane-item">
          管理面: <el-tag :type="alertStats.by_plane?.管理面 > 0 ? 'danger' : 'success'">{{ alertStats.by_plane?.管理面 || 0 }}</el-tag>
        </span>
        <span class="plane-item">
          控制面: <el-tag :type="alertStats.by_plane?.控制面 > 0 ? 'warning' : 'success'">{{ alertStats.by_plane?.控制面 || 0 }}</el-tag>
        </span>
        <span class="plane-item">
          数据面: <el-tag :type="alertStats.by_plane?.数据面 > 0 ? 'danger' : 'success'">{{ alertStats.by_plane?.数据面 || 0 }}</el-tag>
        </span>
      </div>
    </el-card>

    <!-- 告警列表 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span>告警列表</span>
          <div class="filters">
            <el-select v-model="filterSeverity" placeholder="严重性" clearable style="width: 100px">
              <el-option label="严重" value="critical" />
              <el-option label="警告" value="warning" />
              <el-option label="提示" value="info" />
            </el-select>
            <el-select v-model="filterPlane" placeholder="平面" clearable style="width: 100px">
              <el-option label="管理面" value="管理面" />
              <el-option label="控制面" value="控制面" />
              <el-option label="数据面" value="数据面" />
            </el-select>
            <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 100px">
              <el-option label="活跃" value="active" />
              <el-option label="已确认" value="acknowledged" />
              <el-option label="已解决" value="resolved" />
            </el-select>
            <el-button type="primary" @click="loadAlerts">查询</el-button>
            <el-button @click="checkRules">检查规则</el-button>
          </div>
        </div>
      </template>

      <el-table :data="alerts" stripe>
        <el-table-column prop="plane" label="平面" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ row.plane }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="severity" label="严重性" width="80">
          <template #default="{ row }">
            <el-tag :type="getSeverityType(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="alert_type" label="类型" width="120" />
        <el-table-column prop="message" label="消息" />
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="150">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="acknowledgeAlert(row)" v-if="row.status === 'active'">
              确认
            </el-button>
            <el-button size="small" type="success" @click="resolveAlert(row)" v-if="row.status !== 'resolved'">
              解决
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const alertStats = ref({ total: 0, critical: 0, warning: 0, info: 0, active: 0, resolved: 0, by_plane: {} })
const alerts = ref([])
const filterSeverity = ref('')
const filterPlane = ref('')
const filterStatus = ref('')

const getSeverityType = (severity) => {
  const types = { 'critical': 'danger', 'warning': 'warning', 'info': 'info' }
  return types[severity] || 'info'
}

const getStatusType = (status) => {
  const types = { 'active': 'danger', 'acknowledged': 'warning', 'resolved': 'success' }
  return types[status] || 'info'
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString()
}

const loadAlertStats = async () => {
  try {
    const response = await axios.get('/api/alerts/stats')
    alertStats.value = response.data
  } catch (e) {
    console.error('获取告警统计失败', e)
  }
}

const loadAlerts = async () => {
  try {
    const params = {}
    if (filterSeverity.value) params.severity = filterSeverity.value
    if (filterPlane.value) params.plane = filterPlane.value
    if (filterStatus.value) params.status = filterStatus.value

    const response = await axios.get('/api/alerts', { params })
    alerts.value = response.data
  } catch (e) {
    ElMessage.error('获取告警失败')
  }
}

const acknowledgeAlert = async (alert) => {
  try {
    await axios.put(`/api/alerts/${alert.id}/acknowledge`)
    ElMessage.success('告警已确认')
    loadAlerts()
    loadAlertStats()
  } catch (e) {
    ElMessage.error('确认失败')
  }
}

const resolveAlert = async (alert) => {
  try {
    await axios.put(`/api/alerts/${alert.id}/resolve`)
    ElMessage.success('告警已解决')
    loadAlerts()
    loadAlertStats()
  } catch (e) {
    ElMessage.error('解决失败')
  }
}

const checkRules = async () => {
  try {
    const response = await axios.post('/api/alerts/check-rules')
    ElMessage.success(`检查完成，触发 ${response.data.triggered_count} 条告警`)
    loadAlerts()
    loadAlertStats()
  } catch (e) {
    ElMessage.error('规则检查失败')
  }
}

onMounted(() => {
  loadAlertStats()
  loadAlerts()
})
</script>

<style scoped>
.alerts-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.stat-box {
  text-align: center;
  padding: 15px;
  background: #0f3460;
  border-radius: 8px;
}

.stat-box .value {
  font-size: 28px;
  font-weight: bold;
}

.stat-box .label {
  color: #a0a0a0;
  font-size: 12px;
}

.stat-box.critical .value { color: #f56c6c; }
.stat-box.warning .value { color: #e6a23c; }
.stat-box.info .value { color: #909399; }
.stat-box.active .value { color: #409eff; }
.stat-box.resolved .value { color: #67c23a; }

.plane-stats {
  margin-top: 20px;
  display: flex;
  gap: 20px;
}

.plane-item {
  color: #fff;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.filters {
  display: flex;
  gap: 10px;
}
</style>