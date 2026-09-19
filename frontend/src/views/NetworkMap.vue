<template>
  <div class="netmap">
    <header class="bar cm-card">
      <div class="modes">
        <button
          type="button"
          class="mode"
          :class="{ 'is-on': mode === 'template' }"
          @click="mode = 'template'"
        >模板组网</button>
        <button
          type="button"
          class="mode"
          :class="{ 'is-on': mode === 'live' }"
          :disabled="!current"
          @click="mode = 'live'"
        >叠加实况</button>
      </div>

      <span class="hint">
        <template v-if="mode === 'template'">按模板画的规划图, 装机之前就能确认组网对不对</template>
        <template v-else>把这套集群的实测状态盖在同一张图上</template>
      </span>

      <div class="spacer"></div>

      <template v-if="mode === 'template'">
        <el-select v-model="pickedProduct" placeholder="产品" size="small" style="width: 190px" @change="onProductChange">
          <el-option v-for="p in products" :key="p.name" :label="p.name" :value="p.name" />
        </el-select>
        <el-select v-model="pickedMachine" placeholder="机台类型" size="small" style="width: 190px" @change="load">
          <el-option v-for="m in machineTypes" :key="m.name" :label="m.name" :value="m.name" />
        </el-select>
      </template>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <el-alert
      v-if="graph && graph.mismatches && graph.mismatches.length"
      type="warning" show-icon :closable="false" title="实际台数与模板不一致"
    >
      <div v-for="m in graph.mismatches" :key="m" class="mismatch">{{ m }}</div>
    </el-alert>

    <section class="legend cm-card">
      <span class="lg-title">图例</span>
      <div v-for="p in legendPlanes" :key="p.key" class="lg-item">
        <svg width="26" height="8" viewBox="0 0 26 8" aria-hidden="true">
          <line x1="1" y1="4" x2="25" y2="4" :stroke="PLANE_COLOR[p.key]"
            :stroke-width="PLANE_WIDTH[p.key]"
            :stroke-dasharray="p.key === 'data_back' ? '6,4' : null" stroke-linecap="round" />
        </svg>
        <span :style="{ color: PLANE_COLOR[p.key] }">{{ p.label }}</span>
      </div>
      <div class="lg-sep"></div>
      <div v-for="s in LEGEND_STATUS" :key="s.key" class="lg-item">
        <span class="lg-sq" :style="{ background: s.color }"></span>
        <span>{{ s.label }}</span>
      </div>
    </section>

    <section class="canvas cm-card" v-loading="loading">
      <el-empty v-if="!graph" :description="emptyText" />
      <div v-else class="scroller">
        <svg :width="layout.width" :height="layout.height" role="img" :aria-label="ariaLabel">
          <!-- 管理站 -->
          <g v-if="layout.station">
            <rect :x="layout.station.x" :y="layout.station.y" :width="layout.station.w" height="46"
              rx="9" :fill="UI.surface2" :stroke="UI.border" stroke-width="1.5" />
            <text :x="layout.station.x + 16" :y="layout.station.y + 20" font-size="13" font-weight="700"
              :fill="UI.text">{{ graph.station.label }}</text>
            <text :x="layout.station.x + 16" :y="layout.station.y + 36" font-size="11"
              :fill="UI.text2">{{ graph.station.note }}</text>
            <path :d="`M${layout.station.x + 50} ${layout.station.y + 46} V${layout.buses[0].y}`"
              :stroke="PLANE_COLOR.management" stroke-width="1.5" fill="none" />
          </g>

          <!-- 三条平面总线: 横着走, 位置固定 -->
          <g v-for="bus in layout.buses" :key="bus.key">
            <text :x="16" :y="bus.y + 2" font-size="13" font-weight="700" :fill="PLANE_COLOR[bus.key]">{{ bus.label }}</text>
            <text :x="16" :y="bus.y + 19" font-size="10.5" :fill="UI.text3">{{ bus.sub }}</text>
            <line :x1="layout.busX0" :y1="bus.y" :x2="layout.busX1" :y2="bus.y"
              :stroke="PLANE_COLOR[bus.key]" :stroke-width="PLANE_WIDTH[bus.key] + 1"
              :stroke-dasharray="bus.key === 'data_back' ? '14,8' : null" stroke-linecap="round" />
            <template v-if="bus.showSwitch">
              <rect :x="layout.busX1 - 96" :y="bus.y - 32" width="96" height="18" rx="4"
                :fill="tint(bus.key)" />
              <text :x="layout.busX1 - 88" :y="bus.y - 19" font-size="10.5" font-weight="600"
                :fill="PLANE_COLOR[bus.key]" class="cm-mono">{{ bus.switch }}</text>
            </template>
          </g>

          <!-- 角色分组, 挂在总线下面 -->
          <g v-for="g in layout.groups" :key="g.key">
            <path v-for="stub in g.stubs" :key="stub.plane"
              :d="`M${stub.x} ${g.y} V${stub.busY}`"
              :stroke="PLANE_COLOR[stub.plane]" :stroke-width="PLANE_WIDTH[stub.plane]"
              :stroke-dasharray="stub.plane === 'data_back' ? '9,5' : null" fill="none" />
            <circle v-for="stub in g.stubs" :key="`j-${stub.plane}`"
              :cx="stub.x" :cy="stub.busY" r="4" :fill="PLANE_COLOR[stub.plane]" />

            <rect :x="g.x" :y="g.y" :width="g.w" :height="g.h" rx="11"
              :fill="UI.surface" :stroke="UI.border" stroke-width="1.5" />
            <text :x="g.x + 16" :y="g.y + 24" font-size="14" font-weight="700" :fill="UI.text">{{ g.label }}</text>
            <text :x="g.x + 16" :y="g.y + 42" font-size="10.5" :fill="UI.text3">{{ g.sub }}</text>

            <g v-for="chip in g.chips" :key="chip.hostname">
              <title>{{ chip.tooltip }}</title>
              <rect :x="chip.x" :y="chip.y" width="20" height="20" rx="5"
                :fill="chip.color"
                :stroke="chip.focused ? UI.brand : 'none'"
                :stroke-width="chip.focused ? 3 : 0"
                class="chip" @click="select(chip.node)" />
            </g>

            <text v-if="g.note" :x="g.x + 16" :y="g.y + g.h - 14" font-size="10.5" :fill="UI.text2">
              <title>{{ g.noteFull }}</title>{{ g.note }}
            </text>
          </g>
        </svg>
      </div>
    </section>

    <!-- 节点详情 -->
    <el-drawer v-model="drawer" :title="selected?.hostname || '节点'" size="380px">
      <template v-if="selected">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="角色">{{ selected.role_key }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ selected.node_type }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <span class="cm-chip" :class="`cm-chip--${statusClass(selected.status)}`">{{ STATUS_TEXT[selected.status] || selected.status }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="管理面">{{ selected.mgmt_ip || '—' }}</el-descriptions-item>
          <el-descriptions-item label="控制面">{{ selected.ctrl_ip || '—' }}</el-descriptions-item>
          <el-descriptions-item label="数据面">
            {{ selected.data_ip || '—' }}
            <span v-if="selected.data_protocol"> ({{ selected.data_protocol }})</span>
          </el-descriptions-item>
        </el-descriptions>
        <el-button
          v-if="selected.mgmt_ip"
          type="primary" class="bmc-btn" @click="openBmc(selected)"
        >打开 BMC 管理界面</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
/*
 * 组网图 —— 固定版式, 不是力导向。
 *
 * 原来用 D3 力导向: 22 个点自己弹来弹去, 每次打开位置都不一样, 台数一多就糊成
 * 一团, 想指着说"就是这台"都指不准。改成:
 *   三条平面总线横着走, 服务器按角色分组挂在下面, 每组用短竖线接到它该接的总线。
 * 位置每次都一样, 台数再多也只是组里多几个方块。
 *
 * 版式完全由下面的 layout 算出来, 没有布局算法, 所以也不需要 D3。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { currentCluster } from '@/stores/cluster'
import { planeColors, statusColors, uiColors, PLANE_WIDTH } from '@/styles/tokens'

const route = useRoute()
const current = currentCluster

const PLANE_COLOR = planeColors()
const UI = uiColors()
const PLANE_SUB = {
  management: 'BMC / 带外 / PXE',
  control: '集群内部控制流',
  data_front: '前段 DPDK',
  data_back: '后段 RDMA',
}
const STATUS_COLOR = statusColors()
const LEGEND_STATUS = [
  { key: 'online', label: '在线', color: STATUS_COLOR.online },
  { key: 'degraded', label: '异常', color: STATUS_COLOR.degraded },
  { key: 'offline', label: '离线', color: STATUS_COLOR.offline },
  { key: 'planned', label: '规划中', color: STATUS_COLOR.planned },
]
const STATUS_TEXT = { online: '在线', offline: '离线', degraded: '异常', planned: '规划中' }

const mode = ref('template')
const loading = ref(false)
const error = ref('')
const graph = ref(null)
const products = ref([])
const pickedProduct = ref('')
const pickedMachine = ref('')
const drawer = ref(false)
const selected = ref(null)

const focusHost = computed(() => route.query.focus || '')

const machineTypes = computed(
  () => products.value.find(p => p.name === pickedProduct.value)?.machine_types || []
)
const legendPlanes = computed(() => graph.value?.planes || [])
const emptyText = computed(() =>
  mode.value === 'live' ? '这套集群还没有节点' : '先在「集群管理」里配好产品与机台类型'
)
const ariaLabel = computed(() => {
  if (!graph.value) return '组网图'
  const names = (graph.value.groups || []).map(g => `${g.label} ${g.count} 台`).join('、')
  return `组网图: ${names}, 分别接入 ${(graph.value.planes || []).map(p => p.label).join('、')}`
})

const tint = (plane) => ({
  management: '#EDF1F6', control: '#F2ECFC', data_front: '#E4F2F6', data_back: '#FCE9F1',
}[plane] || '#EDF1F6')

const statusClass = (s) => ({ online: 'pass', degraded: 'warn', offline: 'fail' }[s] || 'idle')

// ── 版式 ──────────────────────────────────────────────────────────────────
const LABEL_W = 170      // 左边平面名那一栏
const BUS_GAP = 58
const BUS_TOP = 130
const GROUP_TOP_GAP = 76
const GROUP_GAP = 18
const CHIP = 20
const CHIP_GAP = 4
const CHIP_PITCH = CHIP + CHIP_GAP

// 10.5px 下一个汉字约 10.5px 宽, 留 32px 内边距。SVG 没有自动省略号, 只能自己截。
const clip = (text, width) => {
  if (!text) return ''
  const max = Math.max(4, Math.floor((width - 32) / 10.5))
  return text.length > max ? text.slice(0, max - 1) + '…' : text
}

const layout = computed(() => {
  const g = graph.value
  if (!g) return { width: 0, height: 0, buses: [], groups: [] }

  const seenSwitch = new Set()
  const buses = (g.planes || []).map((p, i) => {
    const showSwitch = !seenSwitch.has(p.switch)
    seenSwitch.add(p.switch)
    return {
      key: p.key,
      label: p.label,
      sub: PLANE_SUB[p.key] || '',
      switch: p.switch,
      showSwitch,          // 前后段共用一台交换机, 名牌只画一次
      y: BUS_TOP + i * BUS_GAP,
    }
  })
  const busY = Object.fromEntries(buses.map(b => [b.key, b.y]))
  const groupY = (buses.length ? buses[buses.length - 1].y : BUS_TOP) + GROUP_TOP_GAP

  // 组宽跟着台数走, 但封顶 —— 一组 12 台也不该占满整屏
  let x = LABEL_W
  const groups = (g.groups || []).map(grp => {
    const perRow = Math.min(Math.max(grp.count, 1), 7)
    const w = Math.max(158, Math.min(260, perRow * CHIP_PITCH + 32))
    const cols = Math.max(1, Math.floor((w - 32) / CHIP_PITCH))
    const rows = Math.ceil(Math.max(grp.count, 1) / cols)
    const h = 58 + rows * CHIP_PITCH + (grp.note ? 22 : 10)

    const chips = (grp.nodes || []).map((n, i) => ({
      hostname: n.hostname,
      node: n,
      x: x + 16 + (i % cols) * CHIP_PITCH,
      y: groupY + 54 + Math.floor(i / cols) * CHIP_PITCH,
      color: STATUS_COLOR[n.status] || STATUS_COLOR.planned,
      focused: focusHost.value && n.hostname === focusHost.value,
      tooltip: `${n.hostname}\n${STATUS_TEXT[n.status] || n.status}\n管理面 ${n.mgmt_ip || '—'}\n控制面 ${n.ctrl_ip || '—'}\n数据面 ${n.data_ip || '—'}`,
    }))

    const stubs = (grp.planes || [])
      .filter(p => busY[p] != null)
      .map((p, i) => ({ plane: p, x: x + 24 + i * 26, busY: busY[p] }))

    const box = {
      key: grp.key, label: grp.label, x, y: groupY, w, h, chips, stubs,
      sub: `${grp.count} 台${grp.planned_count && grp.count !== grp.planned_count ? ` (模板 ${grp.planned_count})` : ''}`,
      note: clip(grp.note, w),
      noteFull: grp.note,
    }
    x += w + GROUP_GAP
    return box
  })

  const maxH = groups.reduce((m, b) => Math.max(m, b.h), 0)
  return {
    buses,
    groups,
    busX0: LABEL_W,
    busX1: Math.max(x - GROUP_GAP, LABEL_W + 400),
    station: { x: LABEL_W, y: 44, w: 210 },
    width: Math.max(x - GROUP_GAP + 20, 900),
    height: groupY + maxH + 30,
  }
})

// ── 取数 ──────────────────────────────────────────────────────────────────
const loadProducts = async () => {
  try {
    const { data } = await axios.get('/api/templates')
    products.value = data.products || []
    if (!pickedProduct.value && products.value.length) {
      pickedProduct.value = products.value[0].name
      pickedMachine.value = products.value[0].machine_types?.[0]?.name || ''
    }
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message
  }
}

const onProductChange = () => {
  pickedMachine.value = machineTypes.value[0]?.name || ''
  load()
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    if (mode.value === 'live') {
      if (!current.value) { graph.value = null; return }
      const { data } = await axios.get(`/api/clusters/${current.value.id}/topology`)
      graph.value = data
    } else {
      if (!pickedProduct.value || !pickedMachine.value) { graph.value = null; return }
      const { data } = await axios.get('/api/templates/topology', {
        params: { product: pickedProduct.value, machine_type: pickedMachine.value },
      })
      graph.value = data
    }
  } catch (e) {
    graph.value = null
    error.value = e?.response?.data?.detail || e.message || '读取组网图失败'
  } finally {
    loading.value = false
  }
}

const select = (node) => {
  selected.value = node
  drawer.value = true
}

const openBmc = (node) => window.open(`https://${node.mgmt_ip}`, '_blank', 'noopener')

watch(mode, load)
watch(() => current.value?.id, () => { if (mode.value === 'live') load() })

onMounted(async () => {
  await loadProducts()
  // 从一键诊断点「在组网图定位」过来的, 直接开实况, 否则看规划图
  if (focusHost.value && current.value) {
    mode.value = 'live'
    pickedProduct.value = current.value.product
    pickedMachine.value = current.value.machine_type
  } else if (current.value) {
    pickedProduct.value = current.value.product || pickedProduct.value
    pickedMachine.value = current.value.machine_type || pickedMachine.value
  }
  load()
})
</script>

<style scoped>
.netmap { display: flex; flex-direction: column; gap: 14px; }
.spacer { flex-grow: 1; }

.bar { display: flex; align-items: center; gap: 12px; padding: 11px 18px; }
.modes { display: flex; background: var(--cm-surface-2); border: 1px solid var(--cm-border); border-radius: 8px; padding: 3px; }
.mode {
  height: 28px; padding: 0 14px;
  background: transparent; color: var(--cm-text-2);
  border: 1px solid transparent; border-radius: 6px;
  font-size: 12px; font-weight: 600; font-family: inherit; cursor: pointer;
}
.mode.is-on { background: var(--cm-surface); color: var(--cm-text); border-color: var(--cm-border); font-weight: 700; }
.mode:disabled { opacity: .5; cursor: not-allowed; }
.hint { font-size: 12px; color: var(--cm-text-2); }
.mismatch { font-size: 13px; line-height: 1.8; }

.legend { display: flex; align-items: center; gap: 22px; padding: 10px 18px; flex-wrap: wrap; }
.lg-title { font-size: 12px; font-weight: 700; color: var(--cm-text-3); }
.lg-item { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--cm-text-2); font-weight: 600; }
.lg-sq { width: 11px; height: 11px; border-radius: 3px; }
.lg-sep { width: 1px; height: 18px; background: var(--cm-border-light); }

.canvas { padding: 14px; min-height: 420px; }
.scroller { overflow-x: auto; }
.chip { cursor: pointer; }
.chip:hover { opacity: .78; }

.bmc-btn { margin-top: 16px; width: 100%; }
</style>
