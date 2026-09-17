<template>
  <div class="dashboard">
    <!-- 三平面状态概览 -->
    <el-row :gutter="20" class="status-row">
      <el-col :span="6">
        <el-card class="status-card management">
          <div class="status-content">
            <h3>管理面 (GE)</h3>
            <div class="status-value">
              <span class="online">{{ stats.management?.nodes_online || 0 }}</span>
              <span class="total">/{{ stats.management?.nodes_total || 0 }}</span>
            </div>
            <p class="status-desc">{{ stats.management?.description }}</p>
            <el-tag :type="stats.management?.nodes_online > 0 ? 'success' : 'danger'">
              {{ stats.management?.nodes_online > 0 ? '正常' : '异常' }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="status-card control">
          <div class="status-content">
            <h3>控制面 (10GE)</h3>
            <div class="status-value">
              <span class="online">{{ stats.control?.nodes_online || 0 }}</span>
              <span class="total">/{{ stats.control?.nodes_total || 0 }}</span>
            </div>
            <p class="status-desc">{{ stats.control?.description }}</p>
            <el-tag :type="stats.control?.nodes_online > 0 ? 'success' : 'warning'">
              {{ stats.control?.nodes_online > 0 ? '正常' : '部分异常' }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="status-card data-front">
          <div class="status-content">
            <h3>数据面前段 (DPDK)</h3>
            <div class="status-value">
              <span class="online">{{ stats.data_front?.nodes_online || 0 }}</span>
              <span class="total">/{{ stats.data_front?.nodes_total || 0 }}</span>
            </div>
            <p class="status-desc">{{ stats.data_front?.description }}</p>
            <el-tag :type="stats.data_front?.nodes_online > 0 ? 'success' : 'danger'">
              {{ stats.data_front?.nodes_online > 0 ? '正常' : '异常' }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="status-card data-back">
          <div class="status-content">
            <h3>数据面后段 (RDMA)</h3>
            <div class="status-value">
              <span class="online">{{ stats.data_back?.nodes_online || 0 }}</span>
              <span class="total">/{{ stats.data_back?.nodes_total || 0 }}</span>
            </div>
            <p class="status-desc">{{ stats.data_back?.description }}</p>
            <el-tag :type="stats.data_back?.nodes_online > 0 ? 'success' : 'danger'">
              {{ stats.data_back?.nodes_online > 0 ? '正常' : '异常' }}
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 节点统计 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="8">
        <el-card>
          <template #header>
            <span>节点分布</span>
          </template>
          <div class="node-distribution">
            <div class="dist-item">
              <span class="label">Master节点</span>
              <span class="value">{{ nodeStats.masters || 0 }}</span>
            </div>
            <div class="dist-item">
              <span class="label">Slave节点</span>
              <span class="value">{{ nodeStats.slaves || 0 }}</span>
            </div>
            <div class="dist-item">
              <span class="label">在线节点</span>
              <span class="value online">{{ nodeStats.online || 0 }}</span>
            </div>
            <div class="dist-item">
              <span class="label">离线节点</span>
              <span class="value offline">{{ nodeStats.offline || 0 }}</span>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card>
          <template #header>
            <span>告警统计</span>
          </template>
          <div class="alert-stats">
            <div class="alert-item critical">
              <span class="label">严重告警</span>
              <span class="value">{{ alertStats.critical || 0 }}</span>
            </div>
            <div class="alert-item warning">
              <span class="label">警告</span>
              <span class="value">{{ alertStats.warning || 0 }}</span>
            </div>
            <div class="alert-item info">
              <span class="label">提示</span>
              <span class="value">{{ alertStats.info || 0 }}</span>
            </div>
            <el-button type="primary" link @click="goToAlerts">
              查看所有告警
            </el-button>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card>
          <template #header>
            <span>巡检统计</span>
          </template>
          <div class="patrol-stats">
            <el-progress
              :percentage="patrolStats.pass_rate || 0"
              color="#67c23a"
              :format="(percentage) => `合格率 ${percentage}%`"
            />
            <div class="patrol-detail">
              <span>检测项: {{ patrolStats.total_checked || 0 }}</span>
              <span>合格: {{ patrolStats.total_passed || 0 }}</span>
              <span>不合格: {{ patrolStats.total_failed || 0 }}</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷操作 -->
    <el-card>
      <template #header>
        <span>快捷操作</span>
      </template>
      <div class="quick-actions">
        <el-button type="primary" @click="goToPXE">
          <el-icon><Download /></el-icon>
          PXE部署
        </el-button>
        <el-button type="success" @click="runPatrol">
          <el-icon><Search /></el-icon>
          执行巡检
        </el-button>
        <el-button type="warning" @click="analyzeFaults">
          <el-icon><FirstAidKit /></el-icon>
          故障分析
        </el-button>
        <el-button @click="goToNetwork">
          <el-icon><Share /></el-icon>
          查看组网图
        </el-button>
      </div>
    </el-card>

    <!-- 最近告警 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span>最近告警</span>
          <el-button size="small" @click="loadRecentAlerts">刷新</el-button>
        </div>
      </template>
      <el-table :data="recentAlerts" stripe size="small">
        <el-table-column prop="plane" label="平面" width="100" />
        <el-table-column prop="severity" label="严重性" width="80">
          <template #default="{ row }">
            <el-tag :type="getSeverityType(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="alert_type" label="类型" width="120" />
        <el-table-column prop="message" label="消息" />
        <el-table-column prop="created_at" label="时间" width="150">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const router = useRouter()

const stats = ref({})
const nodeStats = ref({})
const alertStats = ref({})
const patrolStats = ref({})
const recentAlerts = ref([])

const getSeverityType = (severity) => {
  const types = { 'critical': 'danger', 'warning': 'warning', 'info': 'info' }
  return types[severity] || 'info'
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString()
}

const loadStats = async () => {
  try {
    const response = await axios.get('/api/network/status')
    stats.value = response.data
  } catch (e) {
    console.error('获取状态失败', e)
  }
}

const loadNodeStats = async () => {
  try {
    const response = await axios.get('/api/nodes')
    const nodes = response.data
    nodeStats.value = {
      masters: nodes.filter(n => n.node_type === 'master').length,
      slaves: nodes.filter(n => n.node_type === 'slave').length,
      online: nodes.filter(n => n.status === 'online').length,
      offline: nodes.filter(n => n.status !== 'online').length
    }
  } catch (e) {
    console.error('获取节点统计失败', e)
  }
}

const loadAlertStats = async () => {
  try {
    const response = await axios.get('/api/alerts/stats')
    alertStats.value = response.data
  } catch (e) {
    console.error('获取告警统计失败', e)
  }
}

const loadPatrolStats = async () => {
  try {
    const response = await axios.get('/api/patrol/summary')
    patrolStats.value = response.data
  } catch (e) {
    console.error('获取巡检统计失败', e)
  }
}

const loadRecentAlerts = async () => {
  try {
    const response = await axios.get('/api/alerts/active')
    recentAlerts.value = response.data.slice(0, 10)
  } catch (e) {
    console.error('获取告警失败', e)
  }
}

const goToAlerts = () => router.push('/alerts')
const goToPXE = () => router.push('/pxe')
const goToNetwork = () => router.push('/network')

const runPatrol = async () => {
  try {
    await axios.post('/api/patrol/run')
    ElMessage.success('巡检任务已启动')
  } catch (e) {
    ElMessage.error('启动巡检失败')
  }
}

const analyzeFaults = async () => {
  try {
    await axios.post('/api/diagnose/analyze')
    ElMessage.success('故障分析已启动')
    router.push('/diagnose')
  } catch (e) {
    ElMessage.error('故障分析失败')
  }
}

const loadAllData = async () => {
  await Promise.all([
    loadStats(),
    loadNodeStats(),
    loadAlertStats(),
    loadPatrolStats(),
    loadRecentAlerts()
  ])
}

onMounted(() => {
  loadAllData()
})
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.status-row {
  margin-bottom: 0;
}

.status-card {
  height: 180px;
}

.status-card.management {
  border-left: 4px solid #67c23a;
}

.status-card.control {
  border-left: 4px solid #409eff;
}

.status-card.data-front {
  border-left: 4px solid #e94560;
}

.status-card.data-back {
  border-left: 4px solid #f56c6c;
}

.status-content {
  text-align: center;
}

.status-content h3 {
  color: #fff;
  margin: 0;
  font-size: 16px;
}

.status-value {
  margin-top: 20px;
}

.status-value .online {
  font-size: 36px;
  color: #67c23a;
  font-weight: bold;
}

.status-value .total {
  font-size: 24px;
  color: #a0a0a0;
}

.status-desc {
  color: #a0a0a0;
  font-size: 12px;
  margin: 10px 0;
}

.node-distribution, .alert-stats, .patrol-stats {
  padding: 10px;
}

.dist-item, .alert-item {
  display: flex;
  justify-content: space-between;
  padding: 10px;
  background: #0f3460;
  border-radius: 4px;
  margin: 5px 0;
}

.dist-item .label, .alert-item .label {
  color: #a0a0a0;
}

.dist-item .value, .alert-item .value {
  color: #fff;
  font-weight: bold;
}

.value.online {
  color: #67c23a;
}

.value.offline {
  color: #f56c6c;
}

.alert-item.critical .value {
  color: #f56c6c;
}

.alert-item.warning .value {
  color: #e6a23c;
}

.patrol-detail {
  display: flex;
  justify-content: space-around;
  margin-top: 15px;
  color: #a0a0a0;
}

.quick-actions {
  display: flex;
  gap: 15px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>