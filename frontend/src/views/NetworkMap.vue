<template>
  <div class="network-map">
    <!-- 控制栏 -->
    <div class="controls-bar">
      <div class="plane-buttons">
        <span class="ctrl-label">平面视图：</span>
        <el-radio-group v-model="currentPlane" @change="renderTopology">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="management">管理面 GE</el-radio-button>
          <el-radio-button value="control">控制面 10GE</el-radio-button>
          <el-radio-button value="data_front">数据面前段 DPDK</el-radio-button>
          <el-radio-button value="data_back">数据面后段 RDMA</el-radio-button>
        </el-radio-group>
      </div>
      <div class="legend">
        <div v-for="item in LEGEND_LINKS" :key="item.label" class="legend-item">
          <svg width="28" height="10">
            <line x1="2" y1="5" x2="26" y2="5"
              :stroke="item.color"
              stroke-width="2"
              :stroke-dasharray="item.dash ? '5,3' : null"
              stroke-opacity="0.9"
            />
          </svg>
          <span :style="{ color: item.color }">{{ item.label }}</span>
        </div>
        <div class="legend-sep"></div>
        <div class="legend-item">
          <span class="dot" style="background:#22c55e"></span>
          <span>在线</span>
        </div>
        <div class="legend-item">
          <span class="dot" style="background:#6b7280"></span>
          <span>离线</span>
        </div>
      </div>
      <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
    </div>

    <!-- 拓扑图 -->
    <el-card class="topology-card" v-loading="loading">
      <div ref="topoRef" class="topo-wrap"></div>
    </el-card>

    <!-- 详情面板 -->
    <transition name="panel-slide">
      <el-card v-if="selected" class="detail-panel">
        <template #header>
          <div class="panel-header">
            <span>{{ selected.type === 'node' ? '节点详情' : '链路详情' }}</span>
            <el-button size="small" @click="selected = null">✕</el-button>
          </div>
        </template>

        <!-- 节点详情 -->
        <template v-if="selected.type === 'node'">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="名称">{{ selected.data.name }}</el-descriptions-item>
            <el-descriptions-item label="类型">{{ NODE_TYPE_LABEL[selected.data.type] || selected.data.type }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="STATUS_TAG[selected.data.status] || 'info'" size="small">
                {{ selected.data.status }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <template v-if="selected.data.planes">
            <div class="plane-table">
              <div class="pt-title">三平面网卡状态</div>
              <div
                v-for="(pdata, pname) in selected.data.planes"
                :key="pname"
                class="pt-row"
              >
                <span class="pt-plane" :style="{ color: PLANE_COLORS[pname] }">
                  {{ PLANE_LABEL[pname] || pname }}
                </span>
                <span class="pt-ip">{{ pdata.ip || pdata.bmc_ip || '—' }}</span>
                <el-tag
                  :type="pdata.status === 'online' ? 'success' : 'danger'"
                  size="small"
                >{{ pdata.status || 'offline' }}</el-tag>
                <span v-if="pdata.protocol" class="pt-proto">{{ pdata.protocol }}</span>
              </div>
            </div>
          </template>
          <!-- BMC 快速跳转 -->
          <div v-if="getNodeBmcIp(selected.data)" class="bmc-action">
            <div class="bmc-ip-hint">BMC: {{ getNodeBmcIp(selected.data) }}</div>
            <el-button type="primary" size="small" @click="openBmc(selected.data)">
              打开 BMC 管理界面
            </el-button>
          </div>
        </template>

        <!-- 链路详情 -->
        <template v-else>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="平面">
              <span :style="{ color: PLANE_COLORS[selected.data.plane] }">
                {{ PLANE_LABEL[selected.data.plane] || selected.data.plane }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="协议">{{ selected.data.protocol }}</el-descriptions-item>
            <el-descriptions-item label="带宽">{{ selected.data.bandwidth }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="LINK_STATUS_TAG[selected.data.status] || 'info'" size="small">
                {{ selected.data.status }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="延迟">
              {{ selected.data.latency != null ? selected.data.latency + ' ms' : '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="丢包率">
              {{ selected.data.packet_loss != null ? selected.data.packet_loss + '%' : '—' }}
            </el-descriptions-item>
          </el-descriptions>
        </template>
      </el-card>
    </transition>

    <!-- 三平面统计 -->
    <el-card class="stats-card">
      <template #header><span>三平面网络统计</span></template>
      <div class="stats-grid">
        <div
          v-for="plane in STAT_PLANES"
          :key="plane.key"
          class="stat-item"
          :style="{ borderLeftColor: plane.color }"
        >
          <h5 :style="{ color: plane.color }">{{ plane.label }}</h5>
          <p>在线节点：{{ netStatus[plane.key]?.nodes_online ?? '—' }} / {{ netStatus[plane.key]?.nodes_total ?? '—' }}</p>
          <p class="stat-desc">{{ netStatus[plane.key]?.description }}</p>
          <el-progress
            :percentage="pct(netStatus[plane.key]?.nodes_online, netStatus[plane.key]?.nodes_total)"
            :color="plane.color"
            :stroke-width="6"
          />
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import * as d3 from 'd3'

// ─── 常量 ─────────────────────────────────────────────────────
const PLANE_COLORS = {
  management: '#22c55e',
  control:    '#3b82f6',
  data_front: '#f97316',
  data_back:  '#a855f7',
  data:       '#f97316',
}
const PLANE_LABEL = {
  management: '管理面 GE',
  control:    '控制面 10GE',
  data_front: '数据面前段 DPDK',
  data_back:  '数据面后段 RDMA',
  data:       '数据面',
}
const NODE_TYPE_LABEL = {
  master:       'Master 节点',
  slave:        'Slave 节点',
  subswath:     'SubSwath NFS Server',
  gstorage:     'GStorage NFS Server',
  sensor:       '传感器阵列',
  acquisition:  'Acquisition 采集节点',
  mgmt_station: '管理站 (Windows)',
  pxe_host:     'PXE Host (DHCP/TFTP/HTTP)',
  switch:       '交换机',
}
const STATUS_TAG = {
  online: 'success', normal: 'success',
  offline: 'danger', error: 'danger',
  warning: 'warning', degraded: 'warning',
}
const LINK_STATUS_TAG = { normal: 'success', degraded: 'warning', down: 'danger' }

const LEGEND_LINKS = [
  { label: '管理面 GE',        color: '#22c55e', dash: false },
  { label: '控制面 10GE',      color: '#3b82f6', dash: false },
  { label: '数据面 DPDK',      color: '#f97316', dash: false },
  { label: '数据面 RDMA',      color: '#a855f7', dash: false },
  { label: '链路断开',          color: '#6b7280', dash: true  },
]
const STAT_PLANES = [
  { key: 'management', label: '管理面 (GE)',      color: '#22c55e' },
  { key: 'control',    label: '控制面 (10GE)',    color: '#3b82f6' },
  { key: 'data_front', label: '数据面前段 DPDK',  color: '#f97316' },
  { key: 'data_back',  label: '数据面后段 RDMA',  color: '#a855f7' },
]

// 节点尺寸
const NODE_R = { master: 32, slave: 22, subswath: 22, gstorage: 22, sensor: 24, acquisition: 22, mgmt_station: 26, pxe_host: 26, switch: 0 }
const SW_W = 96, SW_H = 38

// 节点内部图标文字
const NODE_ICON = { master: 'M', slave: 'S', subswath: 'N', gstorage: 'G', sensor: 'D', acquisition: 'A', mgmt_station: '⚙', pxe_host: 'P' }

// ─── 响应式状态 ───────────────────────────────────────────────
const topoRef    = ref(null)
const loading    = ref(false)
const currentPlane = ref('all')
const selected   = ref(null)
const topoData   = ref({ nodes: [], links: [] })
const netStatus  = ref({})

// ─── 数据加载 ─────────────────────────────────────────────────
const loadAll = async () => {
  loading.value = true
  try {
    const [topo, status] = await Promise.all([
      axios.get('/api/network/topology-graph'),
      axios.get('/api/network/status'),
    ])
    topoData.value = { nodes: topo.data.nodes || [], links: topo.data.links || [] }
    netStatus.value = status.data || {}
    await nextTick()
    renderTopology()
  } catch (e) {
    ElMessage.error('加载拓扑数据失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

// ─── 固定层级布局计算（5层）────────────────────────────────
const computePositions = (nodes, W, H) => {
  const pos = {}
  const padX = 64
  const usableW = W - padX * 2

  // 按类型分组
  const masters  = nodes.filter(n => n.type === 'master')
  const slaves   = nodes.filter(n => n.type === 'slave')
  const storages = nodes.filter(n => n.type === 'subswath' || n.type === 'gstorage')
  const sensors  = nodes.filter(n => n.type === 'sensor')
  const mgmtSt   = nodes.find(n => n.id === 'mgmt-station')
  const pxeHost  = nodes.find(n => n.id === 'pxe-host')
  const swMgmt   = nodes.find(n => n.id === 'sw-mgmt')
  const swCtrl   = nodes.find(n => n.id === 'sw-ctrl')
  const swData   = nodes.find(n => n.id === 'sw-data-100g')

  // 5 层 Y 坐标
  const y0 = H * 0.09   // 管理层
  const y1 = H * 0.26   // 控制层（含传感器）
  const y2 = H * 0.47   // 主控层（Master）
  const y3 = H * 0.64   // 数据交换层（100G 交换机）
  const y4 = H * 0.84   // 数据处理层（Slave + SubSwath + GStorage）

  // 第 0 层（管理层）：管理站(Windows) — 管理交换机 — PXE Host
  if (mgmtSt)  pos['mgmt-station'] = { x: padX + usableW * 0.10, y: y0 }
  if (swMgmt)  pos['sw-mgmt']      = { x: padX + usableW * 0.45, y: y0 }
  if (pxeHost) pos['pxe-host']     = { x: padX + usableW * 0.78, y: y0 }

  // 第 1 层
  sensors.forEach((s, i) => {
    pos[s.id] = { x: padX + usableW * (0.05 + i * 0.11), y: y1 }
  })
  if (swCtrl) pos['sw-ctrl'] = { x: padX + usableW * 0.55, y: y1 }

  // 第 2 层：Master 居中展开
  const masterStep = masters.length > 1
    ? Math.min(usableW * 0.85 / (masters.length - 1), usableW * 0.20)
    : 0
  const masterStartX = padX + usableW * 0.5 - masterStep * (masters.length - 1) / 2
  masters.forEach((m, i) => {
    pos[m.id] = { x: masterStartX + i * masterStep, y: y2 }
  })

  // 第 3 层：100G 数据交换机（居中）
  if (swData) pos['sw-data-100g'] = { x: padX + usableW * 0.5, y: y3 }

  // 第 4 层：Slaves + Storages + Acquisitions 均匀分布
  const acqs = nodes.filter(n => n.type === 'acquisition')
  const bottomNodes = [...slaves, ...storages, ...acqs]
  bottomNodes.forEach((n, i) => {
    pos[n.id] = {
      x: padX + (i + 0.5) * (usableW / Math.max(bottomNodes.length, 1)),
      y: y4,
    }
  })

  return pos
}

// ─── 辅助：节点边缘坐标（链路端点不进入节点内部） ────────────
const edgePoint = (nodePos, targetPos, nodeType) => {
  if (nodeType === 'switch') {
    const hw = SW_W / 2 + 3, hh = SW_H / 2 + 3
    const dx = targetPos.x - nodePos.x || 0.001
    const dy = targetPos.y - nodePos.y || 0.001
    const scaleX = hw / Math.abs(dx)
    const scaleY = hh / Math.abs(dy)
    const scale = Math.min(scaleX, scaleY)
    if (scale >= 1) return nodePos
    return { x: nodePos.x + dx * scale, y: nodePos.y + dy * scale }
  }
  const r = (NODE_R[nodeType] || 22) + 3
  const d = Math.hypot(targetPos.x - nodePos.x, targetPos.y - nodePos.y)
  if (d <= r) return nodePos
  return {
    x: nodePos.x + (targetPos.x - nodePos.x) * r / d,
    y: nodePos.y + (targetPos.y - nodePos.y) * r / d,
  }
}

// ─── 辅助：贝塞尔曲线路径 ─────────────────────────────────────
const curvePath = (src, tgt) => {
  const dy = tgt.y - src.y
  return [
    `M ${src.x} ${src.y}`,
    `C ${src.x} ${src.y + dy * 0.45},`,
    `  ${tgt.x} ${tgt.y - dy * 0.45},`,
    `  ${tgt.x} ${tgt.y}`,
  ].join(' ')
}

// ─── 主渲染函数 ───────────────────────────────────────────────
const renderTopology = () => {
  if (!topoRef.value) return
  const W = topoRef.value.clientWidth || 900
  const H = 580

  d3.select(topoRef.value).selectAll('*').remove()

  const { nodes, links } = topoData.value
  if (nodes.length === 0) { renderEmpty(W, H); return }

  // 过滤可见链路
  const visLinks = currentPlane.value === 'all'
    ? links
    : links.filter(l => l.plane === currentPlane.value)

  const positions = computePositions(nodes, W, H)
  const nodeById  = Object.fromEntries(nodes.map(n => [n.id, n]))

  // ── SVG 根元素 ──────────────────────────────────────────────
  const svg = d3.select(topoRef.value)
    .append('svg')
    .attr('width', W)
    .attr('height', H)
    .style('background', '#0f172a')

  // 箭头标记（每种平面颜色 + 离线灰色各一个）
  const defs = svg.append('defs')
  const arrowPlanes = [...Object.keys(PLANE_COLORS), 'down']
  arrowPlanes.forEach(key => {
    const color = key === 'down' ? '#6b7280' : PLANE_COLORS[key]
    defs.append('marker')
      .attr('id', `arr-${key}`)
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 7).attr('refY', 0)
      .attr('markerWidth', 5).attr('markerHeight', 5)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', color)
  })

  // zoom / pan
  const g = svg.append('g')
  svg.call(
    d3.zoom()
      .scaleExtent([0.35, 3])
      .on('zoom', e => g.attr('transform', e.transform))
  )

  // ── 层级分隔虚线 ────────────────────────────────────────────
  const ROWS   = [H * 0.09, H * 0.26, H * 0.47, H * 0.64, H * 0.84]
  const RLABEL = ['管理层', '控制层', '主控层', '数据交换层', '数据处理层']
  const bgG = g.append('g').attr('pointer-events', 'none')
  ROWS.forEach((ry, ri) => {
    bgG.append('line')
      .attr('x1', 8).attr('y1', ry - 28)
      .attr('x2', W - 8).attr('y2', ry - 28)
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '4,4')
    bgG.append('text')
      .attr('x', 10).attr('y', ry - 32)
      .attr('fill', '#334155')
      .attr('font-size', '10px')
      .text(RLABEL[ri])
  })

  // ── 链路 ────────────────────────────────────────────────────
  const linkG = g.append('g')
  visLinks.forEach(link => {
    const srcId = typeof link.source === 'object' ? link.source.id : link.source
    const tgtId = typeof link.target === 'object' ? link.target.id : link.target
    const srcPos  = positions[srcId]
    const tgtPos  = positions[tgtId]
    const srcNode = nodeById[srcId]
    const tgtNode = nodeById[tgtId]
    if (!srcPos || !tgtPos || !srcNode || !tgtNode) return

    // 多端口并行偏移（同节点→同交换机的多条链路横向错开）
    const portCount = link.port_count || 1
    const portIndex = link.port_index ?? 0
    let eSrc = srcPos, eTgt = tgtPos
    if (portCount > 1) {
      const dx = tgtPos.x - srcPos.x
      const dy = tgtPos.y - srcPos.y
      const len = Math.hypot(dx, dy) || 1
      const perpX = -dy / len
      const perpY =  dx / len
      const spacing = 11
      const offset = (portIndex - (portCount - 1) / 2) * spacing
      eSrc = { x: srcPos.x + perpX * offset, y: srcPos.y + perpY * offset }
      eTgt = { x: tgtPos.x + perpX * offset, y: tgtPos.y + perpY * offset }
    }

    const s = edgePoint(eSrc, eTgt, srcNode.type)
    const t = edgePoint(eTgt, eSrc, tgtNode.type)

    const isDown   = link.status === 'down'
    const isDeg    = link.status === 'degraded'
    const color    = isDown ? '#6b7280' : (PLANE_COLORS[link.plane] || '#94a3b8')
    const arrowKey = isDown ? 'down' : link.plane
    const bwWidth  = link.bandwidth === '100GE' ? 2.5 : link.bandwidth === '10GE' ? 2 : 1.5

    linkG.append('path')
      .attr('d', curvePath(s, t))
      .attr('stroke', color)
      .attr('stroke-width', bwWidth)
      .attr('stroke-dasharray', isDown ? '7,5' : isDeg ? '3,3' : null)
      .attr('stroke-opacity', isDown ? 0.4 : 0.75)
      .attr('fill', 'none')
      .attr('marker-end', `url(#arr-${arrowKey})`)
      .style('cursor', 'pointer')
      .on('click', () => { selected.value = { type: 'link', data: link } })

    // 链路标注：多端口显示网卡名，单端口显示带宽
    const midX = (s.x + t.x) / 2
    const midY = (s.y + t.y) / 2
    const label = link.nic || link.bandwidth
    linkG.append('text')
      .attr('x', midX).attr('y', midY - 4)
      .attr('text-anchor', 'middle')
      .attr('fill', color)
      .attr('font-size', portCount > 1 ? '8px' : '9px')
      .attr('pointer-events', 'none')
      .text(label)
  })

  // ── 节点 ────────────────────────────────────────────────────
  const nodeG = g.append('g')
  nodes.forEach(node => {
    const pos = positions[node.id]
    if (!pos) return

    const ng = nodeG.append('g')
      .attr('transform', `translate(${pos.x},${pos.y})`)
      .style('cursor', 'pointer')
      .on('click', () => { selected.value = { type: 'node', data: node } })

    const statusColor = node.status === 'online' ? '#22c55e'
      : node.status === 'warning' || node.status === 'degraded' ? '#eab308'
      : '#6b7280'

    if (node.type === 'switch') {
      const planeColor = PLANE_COLORS[node.switch_plane] || '#94a3b8'

      // 外发光
      ng.append('rect')
        .attr('x', -SW_W / 2 - 4).attr('y', -SW_H / 2 - 4)
        .attr('width', SW_W + 8).attr('height', SW_H + 8)
        .attr('rx', 12)
        .attr('fill', 'none')
        .attr('stroke', planeColor)
        .attr('stroke-width', 1)
        .attr('stroke-opacity', 0.25)

      ng.append('rect')
        .attr('x', -SW_W / 2).attr('y', -SW_H / 2)
        .attr('width', SW_W).attr('height', SW_H)
        .attr('rx', 8)
        .attr('fill', '#1e293b')
        .attr('stroke', planeColor)
        .attr('stroke-width', 2)

      // 交换机名称分两行
      const [line1, line2] = node.name.split(' ')
      ng.append('text')
        .attr('text-anchor', 'middle').attr('dy', -3)
        .attr('fill', planeColor).attr('font-size', '10px').attr('font-weight', 'bold')
        .attr('pointer-events', 'none')
        .text(line1)
      ng.append('text')
        .attr('text-anchor', 'middle').attr('dy', 11)
        .attr('fill', planeColor).attr('font-size', '9px').attr('opacity', 0.8)
        .attr('pointer-events', 'none')
        .text(line2 || '')

    } else {
      const r = NODE_R[node.type] || 22

      // 在线状态光晕
      if (node.status === 'online') {
        ng.append('circle')
          .attr('r', r + 6)
          .attr('fill', 'none')
          .attr('stroke', statusColor)
          .attr('stroke-width', 1)
          .attr('stroke-opacity', 0.25)
      }

      // 主圆
      const nodeFills = {
        master: '#1e3a5f', slave: '#1e293b',
        subswath: '#1a2e20', gstorage: '#2e1e1a',
        sensor: '#2d1b4e', acquisition: '#0e2a2e',
        mgmt_station: '#1a2e1a', pxe_host: '#3a1f1f',
      }
      ng.append('circle')
        .attr('r', r)
        .attr('fill', nodeFills[node.type] || '#1e293b')
        .attr('stroke', statusColor)
        .attr('stroke-width', 2.5)

      // 图标
      ng.append('text')
        .attr('text-anchor', 'middle').attr('dy', 5)
        .attr('fill', '#e2e8f0')
        .attr('font-size', node.type === 'master' ? '16px' : '13px')
        .attr('font-weight', 'bold')
        .attr('pointer-events', 'none')
        .text(NODE_ICON[node.type] || '?')

      // 节点名
      ng.append('text')
        .attr('text-anchor', 'middle').attr('dy', r + 16)
        .attr('fill', '#94a3b8').attr('font-size', '11px')
        .attr('pointer-events', 'none')
        .text(node.name)

      // 三平面状态小圆点（仅服务器节点）
      if (node.planes) {
        const planeKeys = Object.keys(node.planes).filter(p => PLANE_COLORS[p])
        planeKeys.forEach((p, idx) => {
          const angle = (idx / planeKeys.length) * Math.PI * 2 - Math.PI / 2
          const dotR  = r - 7
          const pStat = node.planes[p]?.status
          const dotColor = pStat === 'online' ? PLANE_COLORS[p] : '#475569'
          ng.append('circle')
            .attr('cx', Math.cos(angle) * dotR)
            .attr('cy', Math.sin(angle) * dotR)
            .attr('r', 4.5)
            .attr('fill', dotColor)
            .attr('stroke', '#0f172a')
            .attr('stroke-width', 1.5)
            .attr('pointer-events', 'none')
        })
      }
    }
  })
}

const renderEmpty = (W, H) => {
  const svg = d3.select(topoRef.value)
    .append('svg')
    .attr('width', W).attr('height', H)
    .style('background', '#0f172a')
  svg.append('text')
    .attr('x', W / 2).attr('y', H / 2 - 10)
    .attr('text-anchor', 'middle')
    .attr('fill', '#475569').attr('font-size', '15px')
    .text('暂无节点数据 — 请先在 PXE 部署页面添加节点')
}

const pct = (online, total) => (!total ? 0 : Math.round((online / total) * 100))

const getNodeBmcIp = (node) =>
  node.planes?.management?.bmc_ip || node.bmc_ip || null

const openBmc = (node) => {
  const ip = getNodeBmcIp(node)
  if (!ip) { ElMessage.warning('该节点无 BMC IP 信息'); return }
  window.open(`https://${ip}`, '_blank')
}

onMounted(() => {
  loadAll()
  window.addEventListener('resize', renderTopology)
})
onUnmounted(() => {
  window.removeEventListener('resize', renderTopology)
})
</script>

<style scoped>
.network-map {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ── 控制栏 ── */
.controls-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
  padding: 8px 0;
}
.ctrl-label {
  color: #94a3b8;
  font-size: 13px;
  white-space: nowrap;
}
.legend {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-left: auto;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #94a3b8;
}
.legend-sep {
  width: 1px;
  height: 16px;
  background: #334155;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

/* ── 拓扑容器 ── */
.topology-card :deep(.el-card__body) {
  padding: 0;
}
.topo-wrap {
  width: 100%;
  height: 580px;
  overflow: hidden;
}

/* ── 详情面板 ── */
.detail-panel {
  position: fixed;
  right: 20px;
  top: 80px;
  width: 360px;
  z-index: 200;
  max-height: calc(100vh - 100px);
  overflow-y: auto;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 三平面状态表 */
.plane-table {
  margin-top: 14px;
}
.pt-title {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.pt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid #1e293b;
  font-size: 12px;
}
.pt-row:last-child { border-bottom: none; }
.pt-plane { width: 110px; font-weight: 600; }
.pt-ip    { flex: 1; color: #cbd5e1; font-family: monospace; }
.pt-proto { color: #f97316; font-size: 11px; }

/* 动画 */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.panel-slide-enter-from,
.panel-slide-leave-to {
  transform: translateX(30px);
  opacity: 0;
}

/* ── 统计卡片 ── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.stat-item {
  padding: 14px 16px;
  background: #0f172a;
  border-radius: 8px;
  border-left: 4px solid transparent;
}
.stat-item h5 {
  margin: 0 0 8px;
  font-size: 13px;
}
.stat-item p {
  margin: 4px 0;
  font-size: 12px;
  color: #64748b;
}
.stat-desc { color: #475569 !important; font-size: 11px !important; }

.bmc-action {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid #1e293b;
}
.bmc-ip-hint {
  font-size: 11px;
  color: #64748b;
  font-family: monospace;
  margin-bottom: 8px;
}

@media (max-width: 900px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .detail-panel { width: calc(100vw - 40px); right: 20px; }
}
</style>
