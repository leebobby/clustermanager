<template>
  <div class="netmap">
    <header class="bar cm-card">
      <div class="modes">
        <button type="button" class="mode" :class="{ 'is-on': !live }" @click="setLive(false)">模板组网</button>
        <button type="button" class="mode" :class="{ 'is-on': live }" @click="setLive(true)">叠加实况</button>
      </div>
      <span class="hint">
        <template v-if="!live">按模板画的规划图, 装机之前就能确认组网对不对</template>
        <template v-else>线的颜色 = 通断。灰色是还没测过 —— 连通性检测还没开放, 先看模板组网</template>
      </span>
      <div class="spacer"></div>
      <span class="who cm-mono">{{ ws.product }} / {{ ws.machineType }}</span>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-alert
      v-if="graph && graph.problems && graph.problems.length"
      type="warning" show-icon :closable="false" title="这张图画不全, 原因在模板里"
    >
      <div v-for="m in graph.problems" :key="m" class="mismatch">{{ m }}</div>
      <router-link to="/machines" class="fix-link">去「机台与模板」改</router-link>
    </el-alert>
    <el-alert
      v-if="graph && graph.mismatches && graph.mismatches.length"
      type="warning" show-icon :closable="false" title="实际台数与模板不一致"
    >
      <div v-for="m in graph.mismatches" :key="m" class="mismatch">{{ m }}</div>
    </el-alert>

    <section class="legend cm-card">
      <!-- 实况模式下线色表示通断, 模板模式下表示平面 —— 图例跟着换 -->
      <template v-if="live">
        <span class="lg-title">连线</span>
        <div v-for="s in LINK_LEGEND" :key="s.key" class="lg-item">
          <svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true">
            <line x1="1" y1="4" x2="27" y2="4" :stroke="s.color" stroke-width="3.4"
              :stroke-dasharray="s.dash" stroke-linecap="round" />
          </svg>
          <span :style="{ color: s.color }">{{ s.label }}</span>
        </div>
        <div class="lg-sep"></div>
        <span class="lg-title">节点</span>
        <div v-for="s in NODE_LEGEND" :key="s.key" class="lg-item">
          <span class="lg-sq" :style="{ background: s.color }"></span>
          <span>{{ s.label }}</span>
        </div>
      </template>
      <template v-else>
        <span class="lg-title">平面</span>
        <div v-for="p in legendPlanes" :key="p.key" class="lg-item">
          <svg width="28" height="8" viewBox="0 0 28 8" aria-hidden="true">
            <line x1="1" y1="4" x2="27" y2="4" :stroke="PLANE_COLOR[p.key]"
              :stroke-width="PLANE_WIDTH[p.key]"
              :stroke-dasharray="p.key === 'data_back' ? '6,4' : null" stroke-linecap="round" />
          </svg>
          <span :style="{ color: PLANE_COLOR[p.key] }">{{ p.label }}</span>
        </div>
      </template>
    </section>

    <section class="canvas cm-card" v-loading="loading">
      <!-- 一条平面都没有 = 模板里的角色没配平面, 这时候画布上什么也画不出来。
           以前这里会照着空的 buses 去画管理站引线, 直接渲染失败成一片白板 -->
      <el-empty v-if="!graph || !layout.buses.length" :description="emptyText">
        <router-link v-if="ready" to="/machines">
          <el-button type="primary">去「机台与模板」配平面和网段</el-button>
        </router-link>
      </el-empty>
      <div v-else class="scroller">
        <svg :width="layout.width" :height="layout.height" role="img" :aria-label="ariaLabel">
          <g v-if="layout.station && layout.buses.length">
            <rect :x="layout.station.x" :y="layout.station.y" :width="layout.station.w" height="46"
              rx="9" :fill="UI.surface2" :stroke="UI.border" stroke-width="1.5" />
            <text :x="layout.station.x + 16" :y="layout.station.y + 20" font-size="13" font-weight="700"
              :fill="UI.text">{{ graph.station.label }}</text>
            <text :x="layout.station.x + 16" :y="layout.station.y + 36" font-size="11"
              :fill="UI.text2">{{ graph.station.note }}</text>
            <path :d="`M${layout.station.x + 50} ${layout.station.y + 46} V${layout.buses[0].y}`"
              :stroke="PLANE_COLOR.management" stroke-width="1.5" fill="none" />
          </g>

          <!-- 平面总线: 一直用平面色, 它标的是"这是哪条平面", 不是通断 -->
          <g v-for="bus in layout.buses" :key="bus.key">
            <text :x="16" :y="bus.y + 2" font-size="13" font-weight="700" :fill="PLANE_COLOR[bus.key]">{{ bus.label }}</text>
            <text :x="16" :y="bus.y + 19" font-size="10.5" :fill="UI.text3">{{ bus.sub }}</text>
            <line :x1="layout.busX0" :y1="bus.y" :x2="layout.busX1" :y2="bus.y"
              :stroke="PLANE_COLOR[bus.key]" :stroke-width="PLANE_WIDTH[bus.key] + 1"
              :stroke-dasharray="bus.key === 'data_back' ? '14,8' : null" stroke-linecap="round" />
            <template v-if="bus.showSwitch">
              <rect :x="layout.busX1 - 96" :y="bus.y - 32" width="96" height="18" rx="4" :fill="tint(bus.key)" />
              <text :x="layout.busX1 - 88" :y="bus.y - 19" font-size="10.5" font-weight="600"
                :fill="PLANE_COLOR[bus.key]" class="cm-mono">{{ bus.switch }}</text>
            </template>
          </g>

          <g v-for="g in layout.groups" :key="g.key">
            <!-- 竖线: 实况下用通断色, 断的加粗, 一眼能看出来 -->
            <g v-for="stub in g.stubs" :key="stub.plane">
              <path :d="`M${stub.x} ${g.y} V${stub.busY}`"
                :stroke="stub.color" :stroke-width="stub.width"
                :stroke-dasharray="stub.dash" fill="none" />
              <circle :cx="stub.x" :cy="stub.busY" r="4.5" :fill="stub.color" />
              <!-- 断掉的画一个叉, 黑白打印或截图缩小后也分得出来 -->
              <g v-if="stub.broken">
                <circle :cx="stub.x" :cy="stub.markY" r="8" :fill="UI.surface" :stroke="stub.color" stroke-width="2" />
                <path :d="`M${stub.x - 3.4} ${stub.markY - 3.4} L${stub.x + 3.4} ${stub.markY + 3.4}
                          M${stub.x + 3.4} ${stub.markY - 3.4} L${stub.x - 3.4} ${stub.markY + 3.4}`"
                  :stroke="stub.color" stroke-width="2" stroke-linecap="round" fill="none" />
              </g>
              <text v-if="stub.tally" :x="stub.x + 12" :y="stub.busY + 9"
                font-size="10" font-weight="700" :fill="stub.color" class="cm-mono">{{ stub.tally }}</text>
            </g>

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

    <el-drawer v-model="drawer" :title="selected?.hostname || '节点'" size="400px">
      <template v-if="selected">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="角色">{{ selected.role_key }}</el-descriptions-item>
          <el-descriptions-item label="整机状态">
            <span class="cm-chip" :class="`cm-chip--${statusClass(selected.status)}`">
              {{ STATUS_TEXT[selected.status] || selected.status }}
            </span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="pl-title">各平面</div>
        <div v-for="pl in nodePlanes(selected)" :key="pl.plane" class="pl-row">
          <span class="pl-name" :style="{ color: PLANE_COLOR[pl.plane] }">{{ PLANE_LABEL[pl.plane] }}</span>
          <div class="pl-ips">
            <span v-for="ip in pl.ips" :key="ip" class="cm-mono pl-ip">{{ ip }}</span>
          </div>
          <span class="cm-chip" :class="`cm-chip--${statusClass(pl.status)}`">
            {{ STATUS_TEXT[pl.status] || '未检' }}
          </span>
        </div>

        <el-button v-if="selected.mgmt_ip" type="primary" class="bmc-btn" @click="openBmc(selected)">
          打开 BMC 管理界面
        </el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
/*
 * 组网图 —— 固定版式, 不是力导向。
 *
 * 三条平面总线横着走, 服务器按角色分组挂在下面。位置每次都一样, 台数再多也只是
 * 组里多几个方块。版式完全由 layout 算出来, 没有布局算法, 所以不需要 D3。
 *
 * 通断怎么表达(这一版的重点):
 *   总线   一直是平面色 —— 它回答"这是哪条平面"
 *   竖线   模板模式下是平面色; 实况模式下改成通断色, 断的加粗并在中间打一个叉
 *   方块   节点整机状态
 * 颜色之外还叠了线宽和叉号, 截图缩小或黑白打印也分得出来。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { ws, ready } from '@/stores/workspace'
import { planeColors, statusColors, uiColors, PLANE_WIDTH, PLANE_LABEL } from '@/styles/tokens'

const route = useRoute()

const PLANE_COLOR = planeColors()
const STATUS_COLOR = statusColors()
const UI = uiColors()

const LINK_STATE_COLOR = {
  up: STATUS_COLOR.online,
  partial: STATUS_COLOR.degraded,
  down: STATUS_COLOR.offline,
  unknown: '#B4BECB',
}
const LINK_LEGEND = [
  { key: 'up', label: '通', color: LINK_STATE_COLOR.up, dash: null },
  { key: 'partial', label: '部分通', color: LINK_STATE_COLOR.partial, dash: null },
  { key: 'down', label: '断', color: LINK_STATE_COLOR.down, dash: null },
  { key: 'unknown', label: '未检测', color: LINK_STATE_COLOR.unknown, dash: '5,4' },
]
const NODE_LEGEND = [
  { key: 'online', label: '在线', color: STATUS_COLOR.online },
  { key: 'offline', label: '离线', color: STATUS_COLOR.offline },
  { key: 'unknown', label: '未检测', color: '#CBD3DD' },
]
const NODE_COLOR = {
  online: STATUS_COLOR.online,
  degraded: STATUS_COLOR.degraded,
  offline: STATUS_COLOR.offline,
  planned: '#CBD3DD',
  unknown: '#CBD3DD',
}
const STATUS_TEXT = {
  online: '通', offline: '断', degraded: '异常', planned: '规划中', unknown: '未检测',
}
const PLANE_SUB = {
  management: 'BMC / 带外 / PXE',
  control: '集群内部控制流',
  data_front: '前段 DPDK',
  data_back: '后段 RDMA',
}

// 默认看模板组网 —— 实况的通断要靠连通性检测填, 那一块还没开放, 一进来全是灰的没意义
const live = ref(false)
const loading = ref(false)
const error = ref('')
const graph = ref(null)
const drawer = ref(false)
const selected = ref(null)

const focusHost = computed(() => route.query.focus || '')
const legendPlanes = computed(() => graph.value?.planes || [])
const emptyText = computed(() => {
  if (!ready.value) return '先选一个机台类型'
  const g = graph.value
  if (!g) return '这个机台类型下还没有节点'
  if (!(g.planes || []).length) {
    return '模板里的角色还没配平面和网段, 组网图画不出来 —— 节点的 IP 也是由平面网段生成的'
  }
  return '这个机台类型下还没有节点'
})
const ariaLabel = computed(() => {
  if (!graph.value) return '组网图'
  const names = (graph.value.groups || []).map(g => `${g.label} ${g.count} 台`).join('、')
  return `组网图: ${names}`
})

const tint = (plane) => ({
  management: '#EDF1F6', control: '#F2ECFC', data_front: '#E4F2F6', data_back: '#FCE9F1',
}[plane] || '#EDF1F6')

const statusClass = (s) => ({ online: 'pass', degraded: 'warn', offline: 'fail' }[s] || 'idle')

const nodePlanes = (node) => {
  const ips = node.plane_ips || {}
  const st = node.plane_status || {}
  return Object.keys(PLANE_LABEL)
    .filter(p => (ips[p] || []).length)
    .map(p => ({ plane: p, ips: ips[p], status: st[p] || 'unknown' }))
}

// ── 版式 ──────────────────────────────────────────────────────────────────
const LABEL_W = 170
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
      key: p.key, label: p.label, sub: PLANE_SUB[p.key] || '',
      switch: p.switch, showSwitch, y: BUS_TOP + i * BUS_GAP,
    }
  })
  const busY = Object.fromEntries(buses.map(b => [b.key, b.y]))
  const groupY = (buses.length ? buses[buses.length - 1].y : BUS_TOP) + GROUP_TOP_GAP

  const linkOf = {}
  ;(g.links || []).forEach(l => { linkOf[`${l.source}|${l.plane}`] = l })

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
      color: NODE_COLOR[n.status] || NODE_COLOR.unknown,
      focused: focusHost.value && n.hostname === focusHost.value,
      tooltip: [
        n.hostname,
        STATUS_TEXT[n.status] || n.status,
        ...Object.entries(n.plane_ips || {}).map(
          ([p, ips]) => `${PLANE_LABEL[p] || p}: ${ips.join(', ')}`
        ),
      ].join('\n'),
    }))

    const stubs = (grp.planes || [])
      .filter(p => busY[p] != null)
      .map((p, i) => {
        const link = linkOf[`${grp.key}|${p}`] || {}
        const state = live.value ? (grp.plane_state?.[p] || 'unknown') : null
        const color = live.value ? (LINK_STATE_COLOR[state] || LINK_STATE_COLOR.unknown)
                                 : PLANE_COLOR[p]
        const broken = live.value && (state === 'down' || state === 'partial')
        const stubX = x + 24 + i * 26
        return {
          plane: p,
          x: stubX,
          busY: busY[p],
          // 叉号紧挨着它标的那条链路, 不要跑到别的平面总线上去
          markY: busY[p] + 22,
          color,
          // 断掉的加粗, 未检测的画虚线 —— 不靠颜色一个通道
          width: broken ? PLANE_WIDTH[p] + 1.6
               : (live.value && state === 'unknown' ? PLANE_WIDTH[p] : PLANE_WIDTH[p]),
          dash: live.value
            ? (state === 'unknown' ? '5,4' : null)
            : (p === 'data_back' ? '9,5' : null),
          broken,
          tally: live.value && link.count && state !== 'unknown'
            ? `${link.up}/${link.count}${link.nics > 1 ? ` ×${link.nics}口` : ''}` : '',
        }
      })

    const box = {
      key: grp.key, label: grp.label, x, y: groupY, w, h, chips, stubs,
      sub: `${grp.count} 台${grp.planned_count && grp.count !== grp.planned_count
        ? ` (模板 ${grp.planned_count})` : ''}`,
      note: clip(grp.note, w),
      noteFull: grp.note,
    }
    x += w + GROUP_GAP
    return box
  })

  const maxH = groups.reduce((m, b) => Math.max(m, b.h), 0)
  return {
    buses, groups,
    busX0: LABEL_W,
    busX1: Math.max(x - GROUP_GAP, LABEL_W + 400),
    station: { x: LABEL_W, y: 44, w: 210 },
    width: Math.max(x - GROUP_GAP + 20, 900),
    height: groupY + maxH + 30,
  }
})

// ── 取数 ──────────────────────────────────────────────────────────────────
const load = async () => {
  if (!ready.value) { graph.value = null; return }
  loading.value = true
  error.value = ''
  try {
    const { data } = await axios.get('/api/workspace/topology', { params: { live: live.value } })
    graph.value = data
  } catch (e) {
    graph.value = null
    error.value = e?.response?.data?.detail || e.message || '读取组网图失败'
  } finally {
    loading.value = false
  }
}

const setLive = (v) => { live.value = v; load() }
const select = (node) => { selected.value = node; drawer.value = true }
const openBmc = (node) => window.open(`https://${node.mgmt_ip}`, '_blank', 'noopener')

watch(() => `${ws.product}/${ws.machineType}`, load)
onMounted(() => {
  // 从一键诊断点「在组网图定位」过来的, 直接看实况
  if (focusHost.value) live.value = true
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
.hint { font-size: 12px; color: var(--cm-text-2); }
.who { font-size: 12px; color: var(--cm-text-3); }
.fix-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--cm-brand);
}

.mismatch { font-size: 13px; line-height: 1.8; }

.legend { display: flex; align-items: center; gap: 20px; padding: 10px 18px; flex-wrap: wrap; }
.lg-title { font-size: 12px; font-weight: 700; color: var(--cm-text-3); }
.lg-item { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--cm-text-2); font-weight: 600; }
.lg-sq { width: 11px; height: 11px; border-radius: 3px; }
.lg-sep { width: 1px; height: 18px; background: var(--cm-border-light); }

.canvas { padding: 14px; min-height: 420px; }
.scroller { overflow-x: auto; }
.chip { cursor: pointer; }
.chip:hover { opacity: .78; }

.pl-title { margin: 18px 0 10px; font-size: 13px; font-weight: 700; color: var(--cm-text); }
.pl-row {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 0; border-bottom: 1px solid var(--cm-border-light);
}
.pl-name { width: 108px; flex-shrink: 0; font-size: 12px; font-weight: 700; }
.pl-ips { flex-grow: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pl-ip { font-size: 12px; color: var(--cm-text-2); }
.bmc-btn { margin-top: 18px; width: 100%; }
</style>
