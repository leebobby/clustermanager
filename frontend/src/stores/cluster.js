/*
 * 当前集群 —— 全站共享的一个选择。
 *
 * 现场只关心眼前这台机台, 所以组网图、一键诊断、节点清单都只看这一套集群。
 * 选择记在 localStorage 里: 现场用的是同一台笔记本对着同一台机台干活, 每次
 * 打开都要重选一遍很烦。
 *
 * 没有引入 Pinia —— 全站就这一处共享状态, 一个 reactive 对象够了。
 */

import { reactive, computed } from 'vue'
import axios from 'axios'

const STORAGE_KEY = 'cm.currentClusterId'

function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? Number(raw) : null
  } catch (e) {
    return null   // 隐私模式 / 禁用站点数据时读不到, 不影响使用
  }
}

function writeStored(id) {
  try {
    if (id == null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(id))
  } catch (e) {
    /* 存不了就算了 */
  }
}

export const clusterStore = reactive({
  list: [],
  currentId: readStored(),
  loading: false,
  loaded: false,
  error: '',
})

export const currentCluster = computed(
  () => clusterStore.list.find(c => c.id === clusterStore.currentId) || null
)

export async function loadClusters({ force = false } = {}) {
  if (clusterStore.loading) return
  if (clusterStore.loaded && !force) return
  clusterStore.loading = true
  clusterStore.error = ''
  try {
    const { data } = await axios.get('/api/clusters')
    clusterStore.list = Array.isArray(data) ? data : []
    clusterStore.loaded = true

    // 记着的那套被删了, 或者还没选过 —— 落到第一套, 免得页面一直空着
    const stillThere = clusterStore.list.some(c => c.id === clusterStore.currentId)
    if (!stillThere) {
      selectCluster(clusterStore.list.length ? clusterStore.list[0].id : null)
    }
  } catch (e) {
    clusterStore.error = e?.response?.data?.detail || e.message || '读取集群列表失败'
  } finally {
    clusterStore.loading = false
  }
}

export function selectCluster(id) {
  clusterStore.currentId = id
  writeStored(id)
}
