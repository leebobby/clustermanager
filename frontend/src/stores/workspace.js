/*
 * 当前机台 —— 全站共享的一个选择。
 *
 * 本工具一次只对着一台机台: 打开时选一个机台类型, 节点就按模板加载好了。
 * 没有"集群"这一层, 也不需要机台编号 —— 组网图、一键诊断看的都是这一套。
 *
 * 选择存在后端(workspace.json), 不放 localStorage: 节点表是跟着这个选择走的,
 * 两边各存一份迟早对不上。
 *
 * 全站就这一处共享状态, 一个 reactive 对象够了, 没引入 Pinia。
 */

import { reactive, computed } from 'vue'
import axios from 'axios'

export const ws = reactive({
  product: '',
  machineType: '',
  nodeCount: 0,
  chosen: false,        // 还没选过 → 首次打开要弹选择框
  available: [],        // [{product, machine_types: [{name, total}]}]
  loading: false,
  loaded: false,
  error: '',
})

export const ready = computed(() => Boolean(ws.product && ws.machineType))

export const machineTypesOf = (productName) =>
  ws.available.find(p => p.product === productName)?.machine_types || []

export const currentTotal = computed(() => {
  const m = machineTypesOf(ws.product).find(x => x.name === ws.machineType)
  return m?.total ?? 0
})

function apply(data) {
  ws.product = data.product || ''
  ws.machineType = data.machine_type || ''
  ws.nodeCount = data.node_count ?? 0
  if (data.available) ws.available = data.available
  if (data.chosen !== undefined) ws.chosen = data.chosen
}

export async function loadWorkspace({ force = false } = {}) {
  if (ws.loading) return
  if (ws.loaded && !force) return
  ws.loading = true
  ws.error = ''
  try {
    const { data } = await axios.get('/api/workspace')
    apply(data)
    ws.loaded = true
  } catch (e) {
    ws.error = e?.response?.data?.detail || e.message || '读取当前机台失败'
  } finally {
    ws.loading = false
  }
}

/** 选机台类型 —— 后端会顺手把节点按模板加载好, 不用再点第二下 */
export async function selectMachine(product, machineType) {
  ws.loading = true
  ws.error = ''
  try {
    const { data } = await axios.put('/api/workspace', {
      product, machine_type: machineType,
    })
    apply(data)
    ws.chosen = true
    return data
  } finally {
    ws.loading = false
  }
}

/** 改完模板重新对齐节点。实测状态按主机名保留, 不会白测一遍 */
export async function reloadNodes() {
  const { data } = await axios.post('/api/workspace/reload')
  apply(data)
  return data
}
