<template>
  <div class="app">
    <!-- 侧栏: 四项。仪表盘并进了一键诊断, PXE 与巡检本来就已隐藏 -->
    <aside class="sidebar">
      <div class="brand">
        <img src="/logo.svg" alt="" class="brand-mark" />
        <div class="brand-text">
          <span class="brand-name">集群运维</span>
          <span class="brand-ver cm-mono">v1.1</span>
        </div>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in NAV"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ 'is-active': isActive(item.path) }"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="spacer"></div>

      <!-- 当前集群的一句话状态, 不用切页就知道手上这台机台什么情况 -->
      <div class="cluster-card">
        <span class="cc-title">当前集群</span>
        <template v-if="current">
          <span class="cc-name cm-mono">{{ current.name }}</span>
          <span class="cc-sub">{{ current.machine_type || '—' }} · {{ current.node_count }} 台在册</span>
          <span class="cc-sub" v-if="current.site">{{ current.site }}</span>
          <span class="cc-diag">{{ lastDiagnosedText }}</span>
        </template>
        <template v-else>
          <span class="cc-sub">还没有集群</span>
          <router-link to="/clusters" class="cc-link">去新建</router-link>
        </template>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <!-- 集群选择器常驻: 全站都只看选中的这一套 -->
        <div class="picker">
          <span class="picker-label">集群</span>
          <el-select
            :model-value="store.currentId"
            placeholder="选择机台"
            size="default"
            style="width: 260px"
            :loading="store.loading"
            no-data-text="还没有集群, 到「集群管理」里新建"
            @change="onSelect"
          >
            <el-option
              v-for="c in store.list"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            >
              <span class="opt-name cm-mono">{{ c.name }}</span>
              <span class="opt-sub">{{ c.product }} · {{ c.machine_type }}</span>
            </el-option>
          </el-select>
          <span v-if="current" class="picker-meta">{{ current.product }}</span>
        </div>

        <div class="spacer"></div>

        <h1 class="page-title">{{ pageTitle }}</h1>
      </header>

      <div class="content">
        <el-alert
          v-if="store.error"
          :title="store.error"
          type="error"
          show-icon
          :closable="false"
          class="load-error"
        />
        <router-view :key="routeKey" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, markRaw } from 'vue'
import { useRoute } from 'vue-router'
import {
  TrendCharts, Share, Grid, Document
} from '@element-plus/icons-vue'
import { clusterStore as store, currentCluster, loadClusters, selectCluster } from '@/stores/cluster'

const route = useRoute()

const NAV = [
  { path: '/', label: '一键诊断', icon: markRaw(TrendCharts) },
  { path: '/network', label: '组网图', icon: markRaw(Share) },
  { path: '/clusters', label: '集群管理', icon: markRaw(Grid) },
  { path: '/logs', label: '告警与日志', icon: markRaw(Document) },
]

const current = currentCluster
const pageTitle = computed(() => route.meta.title || '集群运维')

// 切集群时让子页面整体重建, 免得上一套集群的数据残留在界面上
const routeKey = computed(() => `${route.path}:${store.currentId ?? 'none'}`)

const isActive = (path) => (path === '/' ? route.path === '/' : route.path.startsWith(path))

const lastDiagnosedText = computed(() => {
  const at = current.value?.last_diagnosed_at
  if (!at) return '尚未诊断'
  const d = new Date(at)
  if (Number.isNaN(d.getTime())) return '尚未诊断'
  return `上次诊断 ${d.toLocaleString('zh-CN', { hour12: false })}`
})

const onSelect = (id) => selectCluster(id)

onMounted(() => loadClusters())
</script>

<style scoped>
.app {
  display: flex;
  height: 100vh;
  background: var(--cm-bg);
}

.spacer { flex-grow: 1; }

/* ── 侧栏 ── */
.sidebar {
  width: 208px;
  flex-shrink: 0;
  background: var(--cm-surface);
  border-right: 1px solid var(--cm-border);
  display: flex;
  flex-direction: column;
}

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 18px 18px 16px;
  border-bottom: 1px solid var(--cm-border-light);
}
.brand-mark { width: 30px; height: 30px; display: block; }
.brand-text { display: flex; flex-direction: column; line-height: 1.3; }
.brand-name { font-size: 15px; font-weight: 700; color: var(--cm-text); }
.brand-ver { font-size: 10px; color: var(--cm-text-3); }

.nav { padding: 12px 10px; display: flex; flex-direction: column; gap: 3px; }
.nav-item {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 11px 12px;
  border-radius: 8px;
  color: var(--cm-text-2);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
}
.nav-item:hover { background: var(--cm-surface-2); color: var(--cm-text); }
.nav-item.is-active {
  background: var(--cm-brand-tint);
  color: var(--cm-brand);
  font-weight: 700;
}
.nav-icon { font-size: 17px; }

.cluster-card {
  margin: 10px;
  padding: 13px 14px;
  background: var(--cm-bg);
  border: 1px solid var(--cm-border-light);
  border-radius: 9px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cc-title { font-size: 11px; font-weight: 700; color: var(--cm-text-3); }
.cc-name { font-size: 13px; font-weight: 700; color: var(--cm-text); word-break: break-all; }
.cc-sub { font-size: 11px; color: var(--cm-text-2); line-height: 1.5; }
.cc-diag { font-size: 11px; color: var(--cm-text-3); padding-top: 2px; }
.cc-link { font-size: 12px; color: var(--cm-brand); font-weight: 600; }

/* ── 主区 ── */
.main {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  height: 58px;
  flex-shrink: 0;
  background: var(--cm-surface);
  border-bottom: 1px solid var(--cm-border);
  display: flex;
  align-items: center;
  padding: 0 22px;
  gap: 14px;
}
.picker { display: flex; align-items: center; gap: 10px; min-width: 0; }
.picker-label { font-size: 12px; font-weight: 600; color: var(--cm-text-3); }
.picker-meta {
  font-size: 12px;
  color: var(--cm-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 260px;
}
.opt-name { font-weight: 600; }
.opt-sub { float: right; font-size: 12px; color: var(--cm-text-3); padding-left: 16px; }

.page-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--cm-text-2);
}

.content {
  flex-grow: 1;
  padding: 20px 22px;
  overflow-y: auto;
  min-height: 0;
}
.load-error { margin-bottom: 16px; }
</style>
