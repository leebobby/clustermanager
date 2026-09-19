<template>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <img src="/logo.svg" alt="" class="brand-mark" />
        <div class="brand-text">
          <span class="brand-name">集群运维</span>
          <span class="brand-ver cm-mono">v1.2</span>
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

      <div class="machine-card">
        <span class="mc-title">当前机台</span>
        <template v-if="ready">
          <span class="mc-name">{{ ws.machineType }}</span>
          <span class="mc-sub">{{ ws.product }}</span>
          <span class="mc-sub">{{ ws.nodeCount }} 台节点</span>
        </template>
        <template v-else>
          <span class="mc-sub">还没选机台类型</span>
        </template>
        <button type="button" class="mc-switch" @click="chooser = true">切换机台类型</button>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <span class="picker-label">机台</span>
        <button type="button" class="picker" @click="chooser = true">
          <template v-if="ready">
            <span class="pk-machine">{{ ws.machineType }}</span>
            <span class="pk-product">{{ ws.product }}</span>
          </template>
          <span v-else class="pk-empty">点这里选一个机台类型</span>
          <el-icon class="pk-arrow"><ArrowDown /></el-icon>
        </button>

        <div class="spacer"></div>
        <h1 class="page-title">{{ pageTitle }}</h1>
      </header>

      <div class="content">
        <el-alert
          v-if="ws.error"
          :title="ws.error"
          type="error"
          show-icon
          :closable="false"
          class="load-error"
        />
        <router-view :key="routeKey" />
      </div>
    </div>

    <!-- 打开工具的第一步: 选机台类型。选完节点就按模板加载好了 -->
    <el-dialog
      v-model="chooser"
      title="选择机台类型"
      width="640px"
      :close-on-click-modal="ready"
      :show-close="ready"
    >
      <p class="ch-hint">
        选好之后, 这台机台的节点会按模板直接加载出来 —— 不用再一台台建。
        <template v-if="ready">换一种机台类型会按新模板重新加载节点列表。</template>
      </p>

      <el-empty v-if="!ws.available.length" description="模板里还没有产品">
        <router-link to="/machines"><el-button type="primary" @click="chooser = false">去建模板</el-button></router-link>
      </el-empty>

      <div v-else class="ch-list">
        <section v-for="p in ws.available" :key="p.product" class="ch-product">
          <div class="ch-phead">
            <span class="ch-pname">{{ p.product }}</span>
            <span v-if="p.description" class="ch-pdesc">{{ p.description }}</span>
          </div>
          <div class="ch-types">
            <button
              v-for="m in p.machine_types"
              :key="m.name"
              type="button"
              class="ch-type"
              :class="{ 'is-on': p.product === ws.product && m.name === ws.machineType }"
              :disabled="switching"
              @click="pick(p.product, m.name)"
            >
              <span class="ct-name">{{ m.name }}</span>
              <span class="ct-total">{{ m.total }} 台</span>
              <span v-if="m.description" class="ct-desc">{{ m.description }}</span>
            </button>
          </div>
          <el-empty v-if="!p.machine_types.length" :image-size="0" description="这个产品下还没有机台类型" />
        </section>
      </div>

      <template #footer>
        <router-link to="/machines">
          <el-button link type="primary" @click="chooser = false">改模板</el-button>
        </router-link>
        <el-button v-if="ready" @click="chooser = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch, markRaw } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { TrendCharts, Share, Grid, Document, ArrowDown } from '@element-plus/icons-vue'
import { ws, ready, loadWorkspace, selectMachine } from '@/stores/workspace'

const route = useRoute()
const chooser = ref(false)
const switching = ref(false)

const NAV = [
  { path: '/', label: '一键诊断', icon: markRaw(TrendCharts) },
  { path: '/network', label: '组网图', icon: markRaw(Share) },
  { path: '/machines', label: '机台与模板', icon: markRaw(Grid) },
  { path: '/logs', label: '告警与日志', icon: markRaw(Document) },
]

const pageTitle = computed(() => route.meta.title || '集群运维')
// 换机台类型时让子页面整体重建, 免得上一套的数据残留在界面上
const routeKey = computed(() => `${route.path}:${ws.product}/${ws.machineType}`)
const isActive = (path) => (path === '/' ? route.path === '/' : route.path.startsWith(path))

const pick = async (product, machineType) => {
  switching.value = true
  try {
    const data = await selectMachine(product, machineType)
    chooser.value = false
    const bits = []
    if (data.created?.length) bits.push(`新增 ${data.created.length} 台`)
    if (data.updated?.length) bits.push(`更新 ${data.updated.length} 台`)
    if (data.removed?.length) bits.push(`移除 ${data.removed.length} 台`)
    ElMessage.success(`已加载 ${machineType}, 共 ${data.node_count} 台节点` +
      (bits.length ? ` (${bits.join(' · ')})` : ''))
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || '切换失败')
  } finally {
    switching.value = false
  }
}

onMounted(async () => {
  await loadWorkspace()
  // 没选过就弹出来 —— 这是打开工具的第一步, 不该让人自己去找
  if (!ws.chosen) chooser.value = true
})

// 模板页把产品全删光之类, 让选择框再出来
watch(() => ws.available.length, (n) => { if (!n) chooser.value = false })
</script>

<style scoped>
.app { display: flex; height: 100vh; background: var(--cm-bg); }
.spacer { flex-grow: 1; }

.sidebar {
  width: 208px;
  flex-shrink: 0;
  background: var(--cm-surface);
  border-right: 1px solid var(--cm-border);
  display: flex;
  flex-direction: column;
}

.brand {
  display: flex; align-items: center; gap: 11px;
  padding: 18px 18px 16px;
  border-bottom: 1px solid var(--cm-border-light);
}
.brand-mark { width: 30px; height: 30px; display: block; }
.brand-text { display: flex; flex-direction: column; line-height: 1.3; }
.brand-name { font-size: 15px; font-weight: 700; color: var(--cm-text); }
.brand-ver { font-size: 10px; color: var(--cm-text-3); }

.nav { padding: 12px 10px; display: flex; flex-direction: column; gap: 3px; }
.nav-item {
  display: flex; align-items: center; gap: 11px;
  padding: 11px 12px; border-radius: 8px;
  color: var(--cm-text-2); text-decoration: none;
  font-size: 14px; font-weight: 500;
}
.nav-item:hover { background: var(--cm-surface-2); color: var(--cm-text); }
.nav-item.is-active { background: var(--cm-brand-tint); color: var(--cm-brand); font-weight: 700; }
.nav-icon { font-size: 17px; }

.machine-card {
  margin: 10px; padding: 13px 14px;
  background: var(--cm-bg);
  border: 1px solid var(--cm-border-light);
  border-radius: 9px;
  display: flex; flex-direction: column; gap: 6px;
}
.mc-title { font-size: 11px; font-weight: 700; color: var(--cm-text-3); }
.mc-name { font-size: 14px; font-weight: 700; color: var(--cm-text); line-height: 1.4; }
.mc-sub { font-size: 11px; color: var(--cm-text-2); line-height: 1.5; }
.mc-switch {
  margin-top: 4px; padding: 0;
  background: none; border: none;
  color: var(--cm-brand); font-size: 12px; font-weight: 600;
  font-family: inherit; text-align: left; cursor: pointer;
}

.main { flex-grow: 1; display: flex; flex-direction: column; min-width: 0; }

.topbar {
  height: 58px; flex-shrink: 0;
  background: var(--cm-surface);
  border-bottom: 1px solid var(--cm-border);
  display: flex; align-items: center; padding: 0 22px; gap: 12px;
}
.picker-label { font-size: 12px; font-weight: 600; color: var(--cm-text-3); }
.picker {
  display: flex; align-items: center; gap: 10px;
  height: 34px; padding: 0 12px;
  background: var(--cm-brand-tint);
  border: 1px solid var(--cm-brand-line);
  border-radius: 7px;
  font-family: inherit; cursor: pointer;
}
.picker:hover { background: #DFE9FF; }
.pk-machine { font-size: 13px; font-weight: 700; color: var(--cm-brand); }
.pk-product { font-size: 12px; color: var(--cm-text-2); }
.pk-empty { font-size: 13px; font-weight: 600; color: var(--cm-brand); }
.pk-arrow { color: var(--cm-brand); font-size: 12px; }

.page-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--cm-text-2); }

.content { flex-grow: 1; padding: 20px 22px; overflow-y: auto; min-height: 0; }
.load-error { margin-bottom: 16px; }

/* 选择框 */
.ch-hint { margin: 0 0 16px; font-size: 13px; color: var(--cm-text-2); line-height: 1.7; }
.ch-list { display: flex; flex-direction: column; gap: 18px; max-height: 52vh; overflow-y: auto; }
.ch-phead { display: flex; align-items: baseline; gap: 10px; margin-bottom: 9px; }
.ch-pname { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.ch-pdesc { font-size: 12px; color: var(--cm-text-3); }
.ch-types { display: grid; grid-template-columns: repeat(auto-fill, minmax(178px, 1fr)); gap: 10px; }
.ch-type {
  display: flex; flex-direction: column; gap: 4px;
  padding: 12px 14px;
  background: var(--cm-surface);
  border: 1px solid var(--cm-border);
  border-radius: 9px;
  font-family: inherit; text-align: left; cursor: pointer;
}
.ch-type:hover { border-color: var(--cm-brand-line); background: var(--cm-brand-tint); }
.ch-type.is-on { border-color: var(--cm-brand); background: var(--cm-brand-tint); border-width: 2px; }
.ch-type:disabled { opacity: .6; cursor: wait; }
.ct-name { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.ct-total { font-size: 12px; font-weight: 600; color: var(--cm-brand); }
.ct-desc { font-size: 11px; color: var(--cm-text-2); line-height: 1.5; }
</style>
