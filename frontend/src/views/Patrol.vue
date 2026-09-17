<template>
  <div class="patrol-view">
    <!-- 巡检统计 -->
    <el-card>
      <template #header>
        <span>巡检统计</span>
      </template>
      <el-row :gutter="20">
        <el-col :span="6">
          <el-statistic title="检测项总数" :value="patrolSummary.total_checked" />
        </el-col>
        <el-col :span="6">
          <el-statistic title="合格项" :value="patrolSummary.total_passed">
            <template #suffix>
              <el-tag type="success" size="small">合格</el-tag>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="不合格项" :value="patrolSummary.total_failed">
            <template #suffix>
              <el-tag type="danger" size="small">不合格</el-tag>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-progress
            :percentage="patrolSummary.pass_rate"
            color="#67c23a"
            style="margin-top: 20px"
          >
            <template #default="{ percentage }">
              合格率 {{ percentage }}%
            </template>
          </el-progress>
        </el-col>
      </el-row>
    </el-card>

    <!-- 巡检项目 -->
    <el-card>
      <template #header>
        <span>巡检项目清单</span>
      </template>

      <el-tabs v-model="activePlane">
        <el-tab-pane label="管理面" name="management">
          <el-table :data="patrolItems.management" stripe size="small">
            <el-table-column prop="name" label="巡检项" />
            <el-table-column prop="description" label="说明" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="控制面" name="control">
          <el-table :data="patrolItems.control" stripe size="small">
            <el-table-column prop="name" label="巡检项" />
            <el-table-column prop="description" label="说明" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="数据面" name="data">
          <el-table :data="patrolItems.data" stripe size="small">
            <el-table-column prop="name" label="巡检项" />
            <el-table-column prop="description" label="说明" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="系统" name="system">
          <el-table :data="patrolItems.system" stripe size="small">
            <el-table-column prop="name" label="巡检项" />
            <el-table-column prop="description" label="说明" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 巡检操作 -->
    <el-card>
      <template #header>
        <span>执行巡检</span>
      </template>

      <div class="patrol-actions">
        <el-button type="primary" @click="runFullPatrol" :loading="patrolling">
          <el-icon><Search /></el-icon>
          全量巡检
        </el-button>
        <el-select v-model="selectedPlane" placeholder="选择平面" style="width: 150px">
          <el-option label="管理面" value="management" />
          <el-option label="控制面" value="control" />
          <el-option label="数据面" value="data" />
          <el-option label="全部平面" value="all" />
        </el-select>
        <el-button @click="runPlanePatrol" :loading="patrolling">
          按平面巡检
        </el-button>
      </div>
    </el-card>

    <!-- 巡检记录 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span>巡检记录</span>
          <el-button size="small" @click="loadRecords">刷新</el-button>
        </div>
      </template>

      <el-table :data="patrolRecords" stripe>
        <el-table-column prop="patrol_type" label="巡检类型" width="150" />
        <el-table-column prop="plane" label="平面" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.plane }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="result" label="结果" width="80">
          <template #default="{ row }">
            <el-tag :type="row.result === 'pass' ? 'success' : 'danger'" size="small">
              {{ row.result === 'pass' ? '合格' : '不合格' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="details" label="详情">
          <template #default="{ row }">
            <span v-if="row.details">{{ JSON.stringify(row.details).substring(0, 100) }}...</span>
          </template>
        </el-table-column>
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
import axios from 'axios'
import { ElMessage } from 'element-plus'

const patrolSummary = ref({ total_checked: 0, total_passed: 0, total_failed: 0, pass_rate: 0 })
const patrolItems = ref({ management: [], control: [], data: [], system: [] })
const patrolRecords = ref([])
const activePlane = ref('management')
const selectedPlane = ref('all')
const patrolling = ref(false)

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString()
}

const loadPatrolSummary = async () => {
  try {
    const response = await axios.get('/api/patrol/summary')
    patrolSummary.value = response.data
  } catch (e) {
    console.error('获取巡检统计失败', e)
  }
}

const loadPatrolItems = async () => {
  try {
    const response = await axios.get('/api/patrol/items')
    patrolItems.value = response.data
  } catch (e) {
    console.error('获取巡检项目失败', e)
  }
}

const loadRecords = async () => {
  try {
    const response = await axios.get('/api/patrol/records')
    patrolRecords.value = response.data
  } catch (e) {
    ElMessage.error('获取巡检记录失败')
  }
}

const runFullPatrol = async () => {
  patrolling.value = true
  try {
    await axios.post('/api/patrol/run')
    ElMessage.success('全量巡检已启动')
    setTimeout(() => {
      loadPatrolSummary()
      loadRecords()
    }, 2000)
  } catch (e) {
    ElMessage.error('启动巡检失败')
  } finally {
    patrolling.value = false
  }
}

const runPlanePatrol = async () => {
  if (!selectedPlane.value) {
    ElMessage.warning('请选择巡检平面')
    return
  }

  patrolling.value = true
  try {
    await axios.post(`/api/patrol/run/plane/${selectedPlane.value}`)
    ElMessage.success(`${selectedPlane.value}平面巡检已启动`)
  } catch (e) {
    ElMessage.error('启动巡检失败')
  } finally {
    patrolling.value = false
  }
}

onMounted(() => {
  loadPatrolSummary()
  loadPatrolItems()
  loadRecords()
})
</script>

<style scoped>
.patrol-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.patrol-actions {
  display: flex;
  gap: 15px;
  align-items: center;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>