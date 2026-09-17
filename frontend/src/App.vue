<template>
  <div class="app-container">
    <!-- 侧边栏导航 -->
    <aside class="sidebar">
      <div class="logo">
        <h2>集群管理</h2>
        <span class="version">v1.0</span>
      </div>
      <el-menu
        :default-active="currentRoute"
        router
        class="sidebar-menu"
      >
        <el-menu-item index="/">
          <el-icon><Odometer /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/pxe">
          <el-icon><Download /></el-icon>
          <span>PXE部署</span>
        </el-menu-item>
        <el-menu-item index="/nodes">
          <el-icon><Server /></el-icon>
          <span>节点管理</span>
        </el-menu-item>
        <el-menu-item index="/network">
          <el-icon><Share /></el-icon>
          <span>组网图</span>
        </el-menu-item>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon>
          <span>告警中心</span>
        </el-menu-item>
        <!-- 巡检管理: 暂未实现, 先不展示, 后续想清楚交互再恢复
        <el-menu-item index="/patrol">
          <el-icon><Search /></el-icon>
          <span>巡检管理</span>
        </el-menu-item>
        -->
        <el-menu-item index="/diagnose">
          <el-icon><FirstAidKit /></el-icon>
          <span>故障诊断</span>
        </el-menu-item>
      </el-menu>

      <!-- 三平面状态指示 -->
      <div class="plane-status">
        <h4>三平面状态</h4>
        <div class="plane-item">
          <span class="plane-name">管理面 (GE)</span>
          <el-tag :type="planeStatus.management" size="small">{{ planeLabels.management }}</el-tag>
        </div>
        <div class="plane-item">
          <span class="plane-name">控制面 (10GE)</span>
          <el-tag :type="planeStatus.control" size="small">{{ planeLabels.control }}</el-tag>
        </div>
        <div class="plane-item">
          <span class="plane-name">数据面 (100GE)</span>
          <el-tag :type="planeStatus.data" size="small">{{ planeLabels.data }}</el-tag>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="main-content">
      <header class="header">
        <h1>{{ pageTitle }}</h1>
        <div class="header-actions">
          <el-button type="primary" @click="refreshData" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </header>
      <div class="content">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const loading = ref(false)

const currentRoute = computed(() => route.path)
const pageTitle = computed(() => route.meta.title || '集群管理系统')

const planeStatus = ref({
  management: 'success',
  control: 'success',
  data: 'success'
})

const planeLabels = ref({
  management: '正常',
  control: '正常',
  data: '正常'
})

const refreshData = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/network/status')
    const data = response.data

    planeStatus.value.management = data.management.nodes_online > 0 ? 'success' : 'danger'
    planeStatus.value.control = data.control.nodes_online > 0 ? 'success' : 'warning'
    planeStatus.value.data = (data.data_front.nodes_online > 0 || data.data_back.nodes_online > 0) ? 'success' : 'danger'

    planeLabels.value.management = `${data.management.nodes_online}/${data.management.nodes_total}`
    planeLabels.value.control = `${data.control.nodes_online}/${data.control.nodes_total}`
    planeLabels.value.data = `${data.data_front.nodes_online + data.data_back.nodes_online}`
  } catch (e) {
    console.error('获取网络状态失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  refreshData()
})
</script>

<style scoped>
.app-container {
  display: flex;
  height: 100vh;
  background: #1a1a2e;
}

.sidebar {
  width: 240px;
  background: #16213e;
  border-right: 1px solid #0f3460;
  display: flex;
  flex-direction: column;
}

.logo {
  padding: 20px;
  text-align: center;
  border-bottom: 1px solid #0f3460;
}

.logo h2 {
  color: #e94560;
  margin: 0;
}

.logo .version {
  color: #666;
  font-size: 12px;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  background: transparent;
}

.sidebar-menu .el-menu-item {
  color: #a0a0a0;
}

.sidebar-menu .el-menu-item:hover {
  background: #0f3460;
}

.sidebar-menu .el-menu-item.is-active {
  color: #e94560;
  background: #0f3460;
}

.plane-status {
  padding: 15px;
  border-top: 1px solid #0f3460;
}

.plane-status h4 {
  color: #a0a0a0;
  margin: 0 0 10px 0;
  font-size: 12px;
}

.plane-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 8px 0;
}

.plane-name {
  color: #fff;
  font-size: 12px;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.header {
  padding: 20px 30px;
  background: #16213e;
  border-bottom: 1px solid #0f3460;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header h1 {
  color: #fff;
  margin: 0;
  font-size: 24px;
}

.content {
  flex: 1;
  padding: 20px 30px;
  overflow-y: auto;
}

/* 全局样式 */
:deep(.el-card) {
  background: #16213e;
  border: 1px solid #0f3460;
  color: #fff;
}

:deep(.el-card__header) {
  background: #0f3460;
  color: #fff;
  border-bottom: 1px solid #0f3460;
}

:deep(.el-table) {
  background: transparent;
  color: #fff;
}

:deep(.el-table th) {
  background: #0f3460;
  color: #fff;
}

:deep(.el-table tr) {
  background: transparent;
}

:deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: rgba(15, 52, 96, 0.3);
}

:deep(.el-dialog) {
  background: #16213e;
  color: #fff;
}

:deep(.el-dialog__header) {
  background: #0f3460;
  padding: 14px 20px;
}

:deep(.el-dialog__title) {
  color: #fff !important;
  font-weight: 600;
}

:deep(.el-dialog__headerbtn .el-dialog__close) {
  color: #fff;
}
:deep(.el-dialog__headerbtn:hover .el-dialog__close) {
  color: #e94560;
}

:deep(.el-form-item__label) {
  color: #a0a0a0;
}
</style>

<!-- 全局非 scoped 样式: 给被 teleport 到 body 之外的 Element Plus dialog 用 -->
<style>
.el-overlay .el-dialog {
  background: #16213e;
  color: #fff;
}
.el-overlay .el-dialog__header {
  background: #0f3460;
  margin-right: 0;
  padding: 14px 20px;
}
.el-overlay .el-dialog__title {
  color: #fff !important;
  font-weight: 600;
}
.el-overlay .el-dialog__body {
  color: #fff;
}
.el-overlay .el-dialog__headerbtn .el-dialog__close {
  color: #fff;
}
.el-overlay .el-dialog__headerbtn:hover .el-dialog__close {
  color: #e94560;
}
.el-overlay .el-form-item__label {
  color: #a0a0a0;
}
</style>