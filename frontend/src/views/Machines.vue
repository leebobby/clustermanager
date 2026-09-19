<template>
  <div class="machines">
    <el-tabs v-model="tab">
      <!-- ── 节点 ────────────────────────────────────────────────── -->
      <el-tab-pane label="节点" name="nodes">
        <div class="pane">
          <header class="bar cm-card">
            <span class="bar-title">{{ ws.machineType || '未选机台类型' }}</span>
            <span class="bar-sub">
              {{ nodes.length }} 台 · 由模板加载。改完模板点「重新加载」对齐, 实测状态会保留
            </span>
            <div class="spacer"></div>
            <el-button size="small" type="primary" plain :disabled="!ready" @click="openNode()">加节点</el-button>
            <el-button size="small" :loading="reloading" :disabled="!ready" @click="reload">重新加载</el-button>
          </header>

          <el-table :data="nodes" class="cm-card" empty-text="还没有节点" max-height="620">
            <el-table-column prop="hostname" label="主机名" min-width="130">
              <template #default="{ row }"><span class="cm-mono bold">{{ row.hostname }}</span></template>
            </el-table-column>
            <el-table-column prop="role_key" label="角色" width="110" />
            <el-table-column label="整机" width="88">
              <template #default="{ row }">
                <span class="cm-chip" :class="`cm-chip--${statusClass(row.status)}`">
                  {{ STATUS_TEXT[row.status] || '未检测' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column
              v-for="p in PLANE_KEYS"
              :key="p"
              :label="PLANE_LABEL[p]"
              min-width="150"
            >
              <template #default="{ row }">
                <div v-if="(row.plane_ips || {})[p]" class="ip-cell">
                  <span
                    v-for="ip in row.plane_ips[p]"
                    :key="ip"
                    class="cm-mono ip"
                    :style="{ color: PLANE_COLOR[p] }"
                  >{{ ip }}</span>
                  <span class="cm-chip cm-chip--tiny" :class="`cm-chip--${statusClass((row.plane_status || {})[p])}`">
                    {{ STATUS_TEXT[(row.plane_status || {})[p]] || '未检测' }}
                  </span>
                </div>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" align="right" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openNode(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="removeNode(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ── 模板 ────────────────────────────────────────────────── -->
      <el-tab-pane label="模板" name="templates">
        <div class="pane">
          <header class="bar cm-card">
            <span class="bar-title">产品与机台类型</span>
            <span class="bar-sub">产品定义角色, 机台类型只定各角色几台。存 JSON 文件, 不入库。</span>
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
                  <el-input v-model="p.name" placeholder="产品名称, 如 A" style="width: 240px" />
                  <el-input v-model="p.description" placeholder="说明" />
                  <el-button type="danger" plain @click="draft.splice(pi, 1)">删除产品</el-button>
                </div>

                <div class="sub">
                  <span class="sub-title">角色</span>
                  <span class="sub-hint">key 是角色标识, 定下就别改 —— 机台类型的台数按它索引。主机名前缀可以随便改。</span>
                  <div class="spacer"></div>
                  <el-button size="small" @click="p.roles.push(emptyRole())">加角色</el-button>
                </div>

                <el-table :data="p.roles" size="small" border>
                  <el-table-column type="expand">
                    <template #default="{ row }">
                      <div class="expand">
                        <div class="exp-block">
                          <span class="exp-title">接哪几个平面</span>
                          <span class="exp-hint">
                            组网图和诊断项都从这里推出来。同一个平面可以加多块网卡 ——
                            Master 数据面就是前段 DPDK 两块 + 后段 RDMA 两块, 一共四个 IP,
                            诊断时四个口各查一次。
                          </span>
                          <div v-for="plane in meta.planes" :key="plane.key" class="plane-block">
                            <div class="plane-head">
                              <el-checkbox
                                :model-value="hasPlane(row, plane.key)"
                                @change="togglePlane(row, plane.key, $event)"
                              >
                                <span :style="{ color: PLANE_COLOR[plane.key], fontWeight: 700 }">{{ plane.label }}</span>
                              </el-checkbox>
                              <template v-if="hasPlane(row, plane.key)">
                                <el-input
                                  v-if="plane.key.startsWith('data')"
                                  :model-value="planeOf(row, plane.key).protocol"
                                  placeholder="协议 DPDK / RDMA"
                                  size="small" style="width: 160px"
                                  @update:model-value="v => (planeOf(row, plane.key).protocol = v)"
                                />
                                <el-button size="small" link type="primary"
                                  @click="planeOf(row, plane.key).prefixes.push('')">加网卡</el-button>
                              </template>
                            </div>
                            <div v-if="hasPlane(row, plane.key)" class="nics">
                              <div
                                v-for="(pref, ni) in planeOf(row, plane.key).prefixes"
                                :key="ni"
                                class="nic"
                              >
                                <span class="nic-no">第 {{ ni + 1 }} 口</span>
                                <el-input
                                  :model-value="pref"
                                  placeholder="网段前缀 如 200.1.1."
                                  size="small" style="width: 200px"
                                  @update:model-value="v => (planeOf(row, plane.key).prefixes[ni] = v)"
                                />
                                <span class="nic-eg cm-mono">
                                  {{ pref ? `${String(pref).replace(/\.$/, '')}.${row.ip_start}` : '—' }}
                                </span>
                                <el-button
                                  link type="danger" size="small"
                                  @click="planeOf(row, plane.key).prefixes.splice(ni, 1)"
                                >删</el-button>
                              </div>
                              <span v-if="!planeOf(row, plane.key).prefixes.length" class="muted">
                                还没加网卡, 这个平面不会生成 IP
                              </span>
                            </div>
                          </div>
                        </div>

                        <div class="exp-block">
                          <span class="exp-title">角色专项检查</span>
                          <span class="exp-hint">
                            打钩的会进一键诊断的可选项。ping / BMC / SSH 由后端直接探; 其余要由
                            诊断脚本认领, 没脚本认领的会标成"缺脚本", 勾了也跑不出结果。
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
                  <el-table-column label="key" width="126">
                    <template #default="{ row }"><el-input v-model="row.key" size="small" placeholder="master" /></template>
                  </el-table-column>
                  <el-table-column label="显示名" width="136">
                    <template #default="{ row }"><el-input v-model="row.label" size="small" placeholder="Master" /></template>
                  </el-table-column>
                  <el-table-column label="节点类型" width="116">
                    <template #default="{ row }"><el-input v-model="row.node_type" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="主机名前缀" width="126">
                    <template #default="{ row }"><el-input v-model="row.hostname_prefix" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="名序号起" width="96">
                    <template #default="{ row }"><el-input-number v-model="row.hostname_start" :min="0" size="small" controls-position="right" style="width: 80px" /></template>
                  </el-table-column>
                  <el-table-column label="IP 起" width="96">
                    <template #default="{ row }"><el-input-number v-model="row.ip_start" :min="0" size="small" controls-position="right" style="width: 80px" /></template>
                  </el-table-column>
                  <el-table-column label="平面 / 网卡数" min-width="180">
                    <template #default="{ row }">
                      <span v-for="pl in row.planes" :key="pl.plane" class="plane-tag"
                        :style="{ color: PLANE_COLOR[pl.plane] }">
                        {{ SHORT_PLANE[pl.plane] }}<template v-if="pl.prefixes.length > 1">&times;{{ pl.prefixes.length }}</template>
                      </span>
                      <span v-if="!row.planes.length" class="muted">未配</span>
                    </template>
                  </el-table-column>
                  <el-table-column width="56" align="right">
                    <template #default="{ $index }">
                      <el-button link type="danger" size="small" @click="p.roles.splice($index, 1)">删</el-button>
                    </template>
                  </el-table-column>
                </el-table>

                <div class="sub">
                  <span class="sub-title">机台类型</span>
                  <span class="sub-hint">同一产品下的区别只有台数。比如 A11 和 A12。</span>
                  <div class="spacer"></div>
                  <el-button size="small" @click="addMachine(p)">加机台类型</el-button>
                </div>

                <el-table :data="p.machine_types" size="small" border>
                  <el-table-column label="名称" width="170">
                    <template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="A11" /></template>
                  </el-table-column>
                  <el-table-column label="说明" min-width="160">
                    <template #default="{ row }"><el-input v-model="row.description" size="small" /></template>
                  </el-table-column>
                  <el-table-column
                    v-for="role in p.roles"
                    :key="role.key"
                    :label="role.label || role.key"
                    width="108"
                  >
                    <template #default="{ row }">
                      <el-input-number
                        :model-value="row.counts[role.key] || 0"
                        :min="0" size="small" controls-position="right" style="width: 90px"
                        @update:model-value="v => (row.counts[role.key] = v || 0)"
                      />
                    </template>
                  </el-table-column>
                  <el-table-column label="合计" width="78">
                    <template #default="{ row }">{{ total(row) }} 台</template>
                  </el-table-column>
                  <el-table-column width="56" align="right">
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

    <el-dialog v-model="nodeOpen" :title="nodeForm.id ? '编辑节点' : '加节点'" width="560px">
      <el-form label-width="96px">
        <el-form-item label="主机名"><el-input v-model="nodeForm.hostname" placeholder="如 slave-13" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="nodeForm.role_key" style="width: 100%" @change="onNodeRole">
            <el-option v-for="r in currentRoles" :key="r.key" :label="`${r.label} (${r.key})`" :value="r.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="节点类型"><el-input v-model="nodeForm.node_type" /></el-form-item>
        <el-form-item label="管理面 IP"><el-input v-model="nodeForm.mgmt_ip" placeholder="BMC 同网段" /></el-form-item>
        <el-form-item label="控制面 IP"><el-input v-model="nodeForm.ctrl_ip" /></el-form-item>
        <el-form-item label="数据面 IP">
          <div class="row">
            <el-input v-model="nodeForm.data_ip" />
            <el-input v-model="nodeForm.data_protocol" placeholder="DPDK / RDMA" style="width: 150px" />
          </div>
        </el-form-item>
        <el-form-item label="系统"><el-input v-model="nodeForm.os_version" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nodeOpen = false">取消</el-button>
        <el-button type="primary" :loading="savingNode" @click="saveNode">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { ws, ready, loadWorkspace, reloadNodes } from '@/stores/workspace'
import { planeColors, PLANE_LABEL } from '@/styles/tokens'

const PLANE_COLOR = planeColors()
const PLANE_KEYS = ['management', 'control', 'data_front', 'data_back']
const SHORT_PLANE = { management: '管', control: '控', data_front: '前', data_back: '后' }
const STATUS_TEXT = { online: '通', offline: '断', degraded: '异常', planned: '规划中', unknown: '未检测' }

const tab = ref('nodes')
const nodes = ref([])
const reloading = ref(false)

const saved = ref([])
const draft = ref([])
const meta = ref({ planes: [], checks: [] })
const activeProduct = ref('0')
const saving = ref(false)
const tplError = ref('')

const nodeOpen = ref(false)
const savingNode = ref(false)
const nodeForm = ref({})

const currentRoles = computed(() => saved.value.find(p => p.name === ws.product)?.roles || [])
const statusClass = (s) => ({ online: 'pass', degraded: 'warn', offline: 'fail' }[s] || 'idle')
const total = (m) => Object.values(m.counts || {}).reduce((a, b) => a + (Number(b) || 0), 0)

const emptyRole = () => ({
  key: '', label: '', node_type: 'slave', hostname_prefix: 'node', role: '',
  hostname_start: 1, ip_start: 1, planes: [], checks: ['ping'],
  os_version: '', cpu_cores: null, memory_gb: null, disk_gb: null, note: '',
})

const hasPlane = (role, key) => (role.planes || []).some(p => p.plane === key)
const planeOf = (role, key) => (role.planes || []).find(p => p.plane === key) || { prefixes: [] }
const togglePlane = (role, key, on) => {
  if (on) role.planes.push({ plane: key, prefixes: [''], protocol: '', bandwidth: '', switch: '' })
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

const loadNodes = async () => {
  if (!ready.value) { nodes.value = []; return }
  try {
    const { data } = await axios.get('/api/workspace/nodes')
    nodes.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  }
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
    await loadWorkspace({ force: true })
    ElMessage.success('模板已保存。到「节点」页点「重新加载」让节点跟着更新')
  } catch (e) {
    tplError.value = e?.response?.data?.detail || e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const reload = async () => {
  reloading.value = true
  try {
    const data = await reloadNodes()
    await loadNodes()
    const bits = []
    if (data.created?.length) bits.push(`新增 ${data.created.length}`)
    if (data.updated?.length) bits.push(`更新 ${data.updated.length}`)
    if (data.removed?.length) bits.push(`移除 ${data.removed.length}`)
    ElMessage.success(bits.length ? `已对齐模板: ${bits.join(' · ')}` : '已经和模板一致, 无需改动')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  } finally {
    reloading.value = false
  }
}

const openNode = (row = null) => {
  nodeForm.value = row
    ? { ...row }
    : { hostname: '', role_key: currentRoles.value[0]?.key || '', node_type: '',
        mgmt_ip: '', ctrl_ip: '', data_ip: '', data_protocol: '', os_version: '' }
  if (!row) onNodeRole()
  nodeOpen.value = true
}

const onNodeRole = () => {
  const role = currentRoles.value.find(r => r.key === nodeForm.value.role_key)
  if (!role) return
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
      product: ws.product,
      machine_type: ws.machineType,
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
    await loadNodes()
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || '保存失败')
  } finally {
    savingNode.value = false
  }
}

const removeNode = async (row) => {
  try {
    await ElMessageBox.confirm(
      `删除节点「${row.hostname}」? 如果它是模板生成的, 下次「重新加载」会再出现。`,
      '确认', { type: 'warning' })
  } catch (e) {
    return
  }
  try {
    await axios.delete(`/api/nodes/${row.id}`)
    await loadNodes()
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  }
}

watch(() => `${ws.product}/${ws.machineType}`, loadNodes)

onMounted(() => {
  loadWorkspace()
  loadNodes()
  loadTemplates()
})
</script>

<style scoped>
.machines { display: flex; flex-direction: column; }
.spacer { flex-grow: 1; }
.muted { color: var(--cm-text-3); font-size: 12px; }
.bold { font-weight: 700; color: var(--cm-text); }

.pane { display: flex; flex-direction: column; gap: 14px; }
.bar { display: flex; align-items: center; gap: 12px; padding: 12px 18px; }
.bar-title { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.bar-sub { font-size: 12px; color: var(--cm-text-2); }

.ip-cell { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; }
.ip { font-size: 12px; font-weight: 600; }

.prod { display: flex; flex-direction: column; gap: 14px; }
.row { display: flex; align-items: center; gap: 10px; }
.sub { display: flex; align-items: baseline; gap: 10px; }
.sub-title { font-size: 13px; font-weight: 700; color: var(--cm-text); }
.sub-hint { font-size: 12px; color: var(--cm-text-2); }

.expand { display: flex; flex-direction: column; gap: 16px; padding: 12px 18px; }
.exp-block { display: flex; flex-direction: column; gap: 8px; }
.exp-title { font-size: 13px; font-weight: 700; color: var(--cm-text); }
.exp-hint { font-size: 12px; color: var(--cm-text-2); line-height: 1.6; }

.plane-block {
  padding: 9px 12px;
  background: var(--cm-bg);
  border: 1px solid var(--cm-border-light);
  border-radius: 8px;
}
.plane-head { display: flex; align-items: center; gap: 14px; }
.nics { display: flex; flex-direction: column; gap: 6px; margin: 8px 0 2px 24px; }
.nic { display: flex; align-items: center; gap: 10px; }
.nic-no { font-size: 12px; color: var(--cm-text-3); width: 52px; }
.nic-eg { font-size: 11px; color: var(--cm-text-3); }
.plane-tag { font-size: 12px; font-weight: 700; margin-right: 8px; }
</style>
