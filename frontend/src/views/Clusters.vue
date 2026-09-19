<template>
  <div class="clusters">
    <el-tabs v-model="tab" class="tabs">
      <!-- ── 集群 ────────────────────────────────────────────────── -->
      <el-tab-pane label="集群" name="clusters">
        <div class="pane">
          <header class="bar cm-card">
            <span class="bar-title">现场机台</span>
            <span class="bar-sub">一台机台 = 一套集群。组网图、诊断、节点都按集群收口。</span>
            <div class="spacer"></div>
            <el-button type="primary" @click="openCreate">新建集群</el-button>
            <el-button :loading="store.loading" @click="refresh">刷新</el-button>
          </header>

          <el-table :data="store.list" class="cm-card" empty-text="还没有集群, 点右上「新建集群」">
            <el-table-column label="机台编号" min-width="150">
              <template #default="{ row }">
                <div class="c-name">
                  <span class="cm-mono name-text">{{ row.name }}</span>
                  <span v-if="row.id === store.currentId" class="cm-chip cm-chip--brand">当前</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="product" label="产品" min-width="150" />
            <el-table-column prop="machine_type" label="机台类型" min-width="140" />
            <el-table-column prop="site" label="厂区 / 产线" min-width="110" />
            <el-table-column label="节点" width="90">
              <template #default="{ row }">{{ row.node_count }} 台</template>
            </el-table-column>
            <el-table-column label="上次诊断" min-width="160">
              <template #default="{ row }">
                <span class="muted">{{ fmtTime(row.last_diagnosed_at) || '尚未诊断' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" align="right">
              <template #default="{ row }">
                <el-button v-if="row.id !== store.currentId" link type="primary" size="small"
                  @click="select(row.id)">设为当前</el-button>
                <el-button link type="primary" size="small" @click="viewNodes(row)">节点</el-button>
                <el-button link type="danger" size="small" @click="confirmDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <section v-if="nodeCluster" class="cm-card nodes">
            <header class="bar bar--inner">
              <span class="bar-title">{{ nodeCluster.name }} 的节点</span>
              <span class="bar-sub">{{ nodes.length }} 台 · 正常情况下由模板生成, 这里可以手工补漏</span>
              <div class="spacer"></div>
              <el-button size="small" type="primary" plain @click="openNode()">加节点</el-button>
              <el-button size="small" @click="nodeCluster = null">收起</el-button>
            </header>
            <el-table :data="nodes" size="small" max-height="380">
              <el-table-column prop="hostname" label="主机名" min-width="130">
                <template #default="{ row }"><span class="cm-mono">{{ row.hostname }}</span></template>
              </el-table-column>
              <el-table-column prop="role_key" label="角色" width="110" />
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <span class="cm-chip" :class="`cm-chip--${statusClass(row.status)}`">{{ STATUS_TEXT[row.status] || row.status }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="mgmt_ip" label="管理面" min-width="120" />
              <el-table-column prop="ctrl_ip" label="控制面" min-width="120" />
              <el-table-column label="数据面" min-width="150">
                <template #default="{ row }">
                  {{ row.data_ip || '—' }}
                  <span v-if="row.data_protocol" class="muted"> {{ row.data_protocol }}</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="110" align="right">
                <template #default="{ row }">
                  <el-button link type="primary" size="small" @click="openNode(row)">编辑</el-button>
                  <el-button link type="danger" size="small" @click="deleteNode(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </div>
      </el-tab-pane>

      <!-- ── 模板 ────────────────────────────────────────────────── -->
      <el-tab-pane label="模板" name="templates">
        <div class="pane">
          <header class="bar cm-card">
            <span class="bar-title">产品与机台类型</span>
            <span class="bar-sub">产品定义角色, 机台类型只定台数。存 JSON 文件, 不入库。</span>
            <div class="spacer"></div>
            <el-button @click="addProduct">新增产品</el-button>
            <el-button type="primary" :loading="saving" @click="saveTemplates">保存模板</el-button>
          </header>

          <el-alert v-if="tplError" :title="tplError" type="error" show-icon :closable="false" />

          <el-tabs v-if="draft.length" v-model="activeProduct" type="border-card" class="cm-card">
            <el-tab-pane
              v-for="(p, pi) in draft"
              :key="pi"
              :name="String(pi)"
              :label="p.name || '(未命名)'"
            >
              <div class="prod">
                <div class="row">
                  <el-input v-model="p.name" placeholder="产品名称" style="width: 260px" />
                  <el-input v-model="p.description" placeholder="说明" />
                  <el-button type="danger" plain @click="draft.splice(pi, 1)">删除产品</el-button>
                </div>

                <!-- 角色 -->
                <div class="sub">
                  <span class="sub-title">角色</span>
                  <span class="sub-hint">
                    key 是角色标识, 定下就别改 —— 机台类型的台数按它索引。主机名前缀可以随便改。
                  </span>
                  <div class="spacer"></div>
                  <el-button size="small" @click="p.roles.push(emptyRole())">加角色</el-button>
                </div>

                <el-table :data="p.roles" size="small" border>
                  <el-table-column type="expand">
                    <template #default="{ row }">
                      <div class="expand">
                        <div class="exp-block">
                          <span class="exp-title">接哪几个平面</span>
                          <span class="exp-hint">组网图和诊断项都从这里推出来</span>
                          <div v-for="plane in meta.planes" :key="plane.key" class="plane-row">
                            <el-checkbox
                              :model-value="hasPlane(row, plane.key)"
                              @change="togglePlane(row, plane.key, $event)"
                            >
                              <span :style="{ color: `var(--cm-plane-${plane.key})`, fontWeight: 700 }">{{ plane.label }}</span>
                            </el-checkbox>
                            <template v-if="hasPlane(row, plane.key)">
                              <el-input
                                :model-value="planeOf(row, plane.key).prefix"
                                placeholder="网段前缀 如 172.16.3."
                                size="small" style="width: 190px"
                                @update:model-value="v => planeOf(row, plane.key).prefix = v"
                              />
                              <el-input
                                v-if="plane.key.startsWith('data')"
                                :model-value="planeOf(row, plane.key).protocol"
                                placeholder="协议 DPDK / RDMA"
                                size="small" style="width: 150px"
                                @update:model-value="v => planeOf(row, plane.key).protocol = v"
                              />
                            </template>
                          </div>
                        </div>

                        <div class="exp-block">
                          <span class="exp-title">角色专项检查</span>
                          <span class="exp-hint">
                            打钩的会进一键诊断。ping / BMC / SSH 由后端直接探; 其余要由诊断脚本认领,
                            没脚本认领的会如实标成"未检查", 不会算成通过。
                          </span>
                          <el-checkbox-group v-model="row.checks">
                            <el-checkbox v-for="c in meta.checks" :key="c.key" :value="c.key">
                              {{ c.label }}
                              <span class="muted">({{ c.kind === 'builtin' ? '内建' : '需脚本' }})</span>
                            </el-checkbox>
                          </el-checkbox-group>
                        </div>

                        <div class="exp-block">
                          <span class="exp-title">硬件规格与备注</span>
                          <div class="row">
                            <el-input v-model="row.os_version" placeholder="系统版本" style="width: 220px" />
                            <el-input-number v-model="row.cpu_cores" :min="0" placeholder="核" controls-position="right" style="width: 120px" />
                            <el-input-number v-model="row.memory_gb" :min="0" placeholder="内存 GB" controls-position="right" style="width: 130px" />
                            <el-input-number v-model="row.disk_gb" :min="0" placeholder="磁盘 GB" controls-position="right" style="width: 140px" />
                          </div>
                          <el-input v-model="row.note" placeholder="备注, 会显示在组网图的角色框里" />
                        </div>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="key" width="130">
                    <template #default="{ row }"><el-input v-model="row.key" size="small" placeholder="master" /></template>
                  </el-table-column>
                  <el-table-column label="显示名" width="140">
                    <template #default="{ row }"><el-input v-model="row.label" size="small" placeholder="Master" /></template>
                  </el-table-column>
                  <el-table-column label="节点类型" width="120">
                    <template #default="{ row }"><el-input v-model="row.node_type" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="主机名前缀" width="130">
                    <template #default="{ row }"><el-input v-model="row.hostname_prefix" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="名序号起" width="100">
                    <template #default="{ row }"><el-input-number v-model="row.hostname_start" :min="0" size="small" controls-position="right" style="width: 84px" /></template>
                  </el-table-column>
                  <el-table-column label="IP 起" width="100">
                    <template #default="{ row }"><el-input-number v-model="row.ip_start" :min="0" size="small" controls-position="right" style="width: 84px" /></template>
                  </el-table-column>
                  <el-table-column label="平面" min-width="140">
                    <template #default="{ row }">
                      <span v-for="pl in row.planes" :key="pl.plane" class="plane-tag"
                        :style="{ color: `var(--cm-plane-${pl.plane})` }">{{ shortPlane(pl.plane) }}</span>
                      <span v-if="!row.planes.length" class="muted">未配</span>
                    </template>
                  </el-table-column>
                  <el-table-column width="60" align="right">
                    <template #default="{ $index }">
                      <el-button link type="danger" size="small" @click="p.roles.splice($index, 1)">删</el-button>
                    </template>
                  </el-table-column>
                </el-table>

                <!-- 机台类型 -->
                <div class="sub">
                  <span class="sub-title">机台类型</span>
                  <span class="sub-hint">同一产品下的区别只有台数</span>
                  <div class="spacer"></div>
                  <el-button size="small" @click="addMachine(p)">加机台类型</el-button>
                </div>

                <el-table :data="p.machine_types" size="small" border>
                  <el-table-column label="名称" width="180">
                    <template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="说明" min-width="180">
                    <template #default="{ row }"><el-input v-model="row.description" size="small" /></template>
                  </el-table-column>
                  <el-table-column
                    v-for="role in p.roles"
                    :key="role.key"
                    :label="role.label || role.key"
                    width="110"
                  >
                    <template #default="{ row }">
                      <el-input-number
                        :model-value="row.counts[role.key] || 0"
                        :min="0" size="small" controls-position="right" style="width: 92px"
                        @update:model-value="v => (row.counts[role.key] = v || 0)"
                      />
                    </template>
                  </el-table-column>
                  <el-table-column label="合计" width="80">
                    <template #default="{ row }">{{ total(row) }} 台</template>
                  </el-table-column>
                  <el-table-column width="60" align="right">
                    <template #default="{ $index }">
                      <el-button link type="danger" size="small" @click="p.machine_types.splice($index, 1)">删</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-tab-pane>
          </el-tabs>

          <el-empty v-else description="还没有产品, 点右上「新增产品」" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建集群 -->
    <el-dialog v-model="createOpen" title="新建集群" width="520px">
      <el-form label-width="96px">
        <el-form-item label="产品">
          <el-select v-model="form.product" style="width: 100%" @change="onFormProduct">
            <el-option v-for="p in saved" :key="p.name" :label="p.name" :value="p.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="机台类型">
          <el-select v-model="form.machine_type" style="width: 100%">
            <el-option
              v-for="m in formMachines"
              :key="m.name"
              :label="`${m.name} — ${totalOf(m)} 台`"
              :value="m.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="机台编号">
          <el-input v-model="form.name" placeholder="如 M-2024-017" />
        </el-form-item>
        <el-form-item label="厂区 / 产线">
          <el-input v-model="form.site" placeholder="选填" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
        <el-form-item label="">
          <el-checkbox v-model="form.create_nodes">同时按模板把节点排出来</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="create">建立</el-button>
      </template>
    </el-dialog>

    <!-- 单台节点: 模板生成之外的补漏口子 -->
    <el-dialog v-model="nodeOpen" :title="nodeForm.id ? '编辑节点' : '加节点'" width="560px">
      <el-form label-width="96px">
        <el-form-item label="主机名">
          <el-input v-model="nodeForm.hostname" placeholder="如 slave-13" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="nodeForm.role_key" style="width: 100%" @change="onNodeRole">
            <el-option
              v-for="r in clusterRoles"
              :key="r.key"
              :label="`${r.label} (${r.key})`"
              :value="r.key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="节点类型">
          <el-input v-model="nodeForm.node_type" />
        </el-form-item>
        <el-form-item label="管理面 IP">
          <el-input v-model="nodeForm.mgmt_ip" placeholder="BMC 同网段" />
        </el-form-item>
        <el-form-item label="控制面 IP">
          <el-input v-model="nodeForm.ctrl_ip" />
        </el-form-item>
        <el-form-item label="数据面 IP">
          <div class="row">
            <el-input v-model="nodeForm.data_ip" />
            <el-input v-model="nodeForm.data_protocol" placeholder="DPDK / RDMA" style="width: 150px" />
          </div>
        </el-form-item>
        <el-form-item label="系统">
          <el-input v-model="nodeForm.os_version" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nodeOpen = false">取消</el-button>
        <el-button type="primary" :loading="savingNode" @click="saveNode">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { clusterStore as store, loadClusters, selectCluster } from '@/stores/cluster'

const STATUS_TEXT = { online: '在线', offline: '离线', degraded: '异常', planned: '规划中' }
const SHORT_PLANE = { management: '管', control: '控', data_front: '前', data_back: '后' }

const tab = ref('clusters')
const saved = ref([])          // 已保存的模板
const draft = ref([])          // 编辑草稿, 保存成功前不影响 saved
const meta = ref({ planes: [], checks: [] })
const activeProduct = ref('0')
const saving = ref(false)
const tplError = ref('')

const nodeCluster = ref(null)
const nodes = ref([])

const createOpen = ref(false)
const creating = ref(false)
const form = ref({ product: '', machine_type: '', name: '', site: '', note: '', create_nodes: true })

const formMachines = computed(
  () => saved.value.find(p => p.name === form.value.product)?.machine_types || []
)

const statusClass = (s) => ({ online: 'pass', degraded: 'warn', offline: 'fail' }[s] || 'idle')
const shortPlane = (p) => SHORT_PLANE[p] || p
const total = (m) => Object.values(m.counts || {}).reduce((a, b) => a + (Number(b) || 0), 0)
const totalOf = total

const fmtTime = (v) => {
  if (!v) return ''
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('zh-CN', { hour12: false })
}

const emptyRole = () => ({
  key: '', label: '', node_type: 'slave', hostname_prefix: 'node', role: '',
  hostname_start: 1, ip_start: 1, planes: [], checks: ['ping'],
  os_version: '', cpu_cores: null, memory_gb: null, disk_gb: null, note: '',
})

const hasPlane = (role, key) => (role.planes || []).some(p => p.plane === key)
const planeOf = (role, key) => (role.planes || []).find(p => p.plane === key) || {}
const togglePlane = (role, key, on) => {
  if (on) role.planes.push({ plane: key, prefix: '', protocol: '', bandwidth: '', switch: '' })
  else role.planes = role.planes.filter(p => p.plane !== key)
}

const addProduct = () => {
  draft.value.push({ name: '', description: '', roles: [emptyRole()], machine_types: [] })
  activeProduct.value = String(draft.value.length - 1)
}
const addMachine = (p) => {
  const counts = {}
  p.roles.forEach(r => { counts[r.key || r.hostname_prefix] = 0 })
  p.machine_types.push({ name: '', description: '', counts })
}

const loadTemplates = async () => {
  try {
    const [{ data }, { data: m }] = await Promise.all([
      axios.get('/api/templates'),
      axios.get('/api/templates/meta'),
    ])
    saved.value = data.products || []
    meta.value = m
    draft.value = JSON.parse(JSON.stringify(saved.value))
  } catch (e) {
    tplError.value = e?.response?.data?.detail || e.message || '读取模板失败'
  }
}

const saveTemplates = async () => {
  tplError.value = ''
  // 前端先挡一道明显的错, 省得跑一趟后端才知道 key 重了
  for (const p of draft.value) {
    if (!p.name.trim()) { tplError.value = '有产品没填名称'; return }
    const keys = p.roles.map(r => (r.key || '').trim())
    if (keys.some(k => !k)) { tplError.value = `产品「${p.name}」里有角色没填 key`; return }
    const dup = keys.filter((k, i) => keys.indexOf(k) !== i)
    if (dup.length) { tplError.value = `产品「${p.name}」里 key 重复: ${[...new Set(dup)].join(', ')}`; return }
  }
  saving.value = true
  try {
    const { data } = await axios.put('/api/templates', { products: draft.value })
    saved.value = data.products || []
    draft.value = JSON.parse(JSON.stringify(saved.value))
    ElMessage.success('模板已保存')
  } catch (e) {
    tplError.value = e?.response?.data?.detail || e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const refresh = () => loadClusters({ force: true })
const select = (id) => { selectCluster(id); ElMessage.success('已切换当前集群') }

const viewNodes = async (row) => {
  nodeCluster.value = row
  try {
    const { data } = await axios.get(`/api/clusters/${row.id}/nodes`)
    nodes.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  }
}

const openCreate = () => {
  if (!saved.value.length) {
    ElMessage.warning('先到「模板」页配好产品与机台类型')
    tab.value = 'templates'
    return
  }
  form.value = {
    product: saved.value[0].name,
    machine_type: saved.value[0].machine_types?.[0]?.name || '',
    name: '', site: '', note: '', create_nodes: true,
  }
  createOpen.value = true
}

const onFormProduct = () => {
  form.value.machine_type = formMachines.value[0]?.name || ''
}

const create = async () => {
  if (!form.value.name.trim()) { ElMessage.warning('填一个机台编号'); return }
  creating.value = true
  try {
    const { data } = await axios.post('/api/clusters', form.value)
    createOpen.value = false
    await loadClusters({ force: true })
    selectCluster(data.id)
    const conflicts = data.conflicts?.length ? `, ${data.conflicts.join('; ')}` : ''
    ElMessage.success(`已建立 ${data.name}, 排了 ${data.created} 台节点${conflicts}`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || '建立失败')
  } finally {
    creating.value = false
  }
}

// ── 单台节点 ───────────────────────────────────────────────────────────────
const nodeOpen = ref(false)
const savingNode = ref(false)
const nodeForm = ref({})

// 加节点时角色下拉取的是这套集群所属产品的角色, 不是全部产品的
const clusterRoles = computed(
  () => saved.value.find(p => p.name === nodeCluster.value?.product)?.roles || []
)

const openNode = (row = null) => {
  nodeForm.value = row
    ? { ...row }
    : { hostname: '', role_key: clusterRoles.value[0]?.key || '', node_type: '',
        mgmt_ip: '', ctrl_ip: '', data_ip: '', data_protocol: '', os_version: '' }
  if (!row) onNodeRole()
  nodeOpen.value = true
}

const onNodeRole = () => {
  const role = clusterRoles.value.find(r => r.key === nodeForm.value.role_key)
  if (!role) return
  // 带出该角色的默认值, 省得一个个填; 填错了还能改
  if (!nodeForm.value.node_type) nodeForm.value.node_type = role.node_type
  if (!nodeForm.value.os_version) nodeForm.value.os_version = role.os_version || ''
  const data = (role.planes || []).find(p => p.plane.startsWith('data'))
  if (data && !nodeForm.value.data_protocol) nodeForm.value.data_protocol = data.protocol || ''
}

const saveNode = async () => {
  if (!nodeForm.value.hostname?.trim()) { ElMessage.warning('填一个主机名'); return }
  savingNode.value = true
  try {
    const payload = {
      hostname: nodeForm.value.hostname.trim(),
      node_type: nodeForm.value.node_type || nodeForm.value.role_key || 'slave',
      role_key: nodeForm.value.role_key || null,
      cluster_id: nodeCluster.value.id,
      product: nodeCluster.value.product,
      machine_type: nodeCluster.value.machine_type,
      // 管理面与 BMC 同网段, 沿用模板展开时的约定
      mgmt_ip: nodeForm.value.mgmt_ip || null,
      bmc_ip: nodeForm.value.mgmt_ip || null,
      ctrl_ip: nodeForm.value.ctrl_ip || null,
      data_ip: nodeForm.value.data_ip || null,
      data_protocol: nodeForm.value.data_protocol || null,
      os_version: nodeForm.value.os_version || null,
    }
    if (nodeForm.value.id) await axios.put(`/api/nodes/${nodeForm.value.id}`, payload)
    else await axios.post('/api/nodes', payload)
    nodeOpen.value = false
    await viewNodes(nodeCluster.value)
    await loadClusters({ force: true })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || '保存失败')
  } finally {
    savingNode.value = false
  }
}

const deleteNode = async (row) => {
  try {
    await ElMessageBox.confirm(`删除节点「${row.hostname}」?`, '确认', { type: 'warning' })
  } catch (e) {
    return
  }
  try {
    await axios.delete(`/api/nodes/${row.id}`)
    await viewNodes(nodeCluster.value)
    await loadClusters({ force: true })
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  }
}

const confirmDelete = async (row) => {
  // 默认不删节点 —— 顺手清掉几十台机器的记录是不可逆的, 要删得明着选
  try {
    await ElMessageBox.confirm(
      `删除集群「${row.name}」。它名下 ${row.node_count} 台节点默认保留(变成无归属), 要一并删除请勾选。`,
      '确认删除',
      {
        type: 'warning',
        confirmButtonText: '删除集群',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
        showInput: false,
      }
    )
  } catch (e) {
    return
  }
  let withNodes = false
  try {
    await ElMessageBox.confirm(`同时删除这 ${row.node_count} 台节点吗?`, '节点怎么处理', {
      type: 'warning',
      confirmButtonText: '一并删除节点',
      cancelButtonText: '保留节点',
      distinguishCancelAndClose: true,
    })
    withNodes = true
  } catch (action) {
    if (action === 'close') return   // 点了叉就是取消整件事
    withNodes = false
  }
  try {
    const { data } = await axios.delete(`/api/clusters/${row.id}`, { params: { with_nodes: withNodes } })
    await loadClusters({ force: true })
    if (nodeCluster.value?.id === row.id) nodeCluster.value = null
    ElMessage.success(
      withNodes ? `已删除 ${data.deleted} 及其 ${data.nodes_deleted} 台节点`
                : `已删除 ${data.deleted}, ${data.nodes_detached} 台节点保留为无归属`
    )
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  }
}

onMounted(() => {
  loadClusters()
  loadTemplates()
})
</script>

<style scoped>
.clusters { display: flex; flex-direction: column; }
.spacer { flex-grow: 1; }
.muted { color: var(--cm-text-3); font-size: 12px; }

.pane { display: flex; flex-direction: column; gap: 14px; }
.bar { display: flex; align-items: center; gap: 12px; padding: 12px 18px; }
.bar--inner { border-bottom: 1px solid var(--cm-border-light); padding: 12px 18px; }
.bar-title { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.bar-sub { font-size: 12px; color: var(--cm-text-2); }

.c-name { display: flex; align-items: center; gap: 9px; }
.name-text { font-weight: 700; color: var(--cm-text); }

.nodes { overflow: hidden; }

.prod { display: flex; flex-direction: column; gap: 14px; }
.row { display: flex; align-items: center; gap: 10px; }
.sub { display: flex; align-items: baseline; gap: 10px; }
.sub-title { font-size: 13px; font-weight: 700; color: var(--cm-text); }
.sub-hint { font-size: 12px; color: var(--cm-text-2); }

.expand { display: flex; flex-direction: column; gap: 16px; padding: 12px 18px; }
.exp-block { display: flex; flex-direction: column; gap: 8px; }
.exp-title { font-size: 13px; font-weight: 700; color: var(--cm-text); }
.exp-hint { font-size: 12px; color: var(--cm-text-2); line-height: 1.6; }
.plane-row { display: flex; align-items: center; gap: 12px; }
.plane-tag { font-size: 12px; font-weight: 700; margin-right: 6px; }
</style>
