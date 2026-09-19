<template>
  <div class="checkup">
    <el-empty v-if="!current" description="还没有集群">
      <router-link to="/clusters"><el-button type="primary">去新建一套集群</el-button></router-link>
    </el-empty>

    <template v-else>
      <!-- 大结论: 一眼看到该不该动手 -->
      <section class="verdict cm-card" :class="`verdict--${summary.verdict}`">
        <div class="v-badge" :class="`v-badge--${summary.verdict}`">
          <el-icon :size="30"><component :is="VERDICT_ICON[summary.verdict]" /></el-icon>
        </div>

        <div class="v-body">
          <div class="v-line">
            <span class="v-headline" :class="`v-headline--${summary.verdict}`">{{ summary.headline }}</span>
            <span v-if="counts.warn && summary.verdict === 'fail'" class="v-warn">{{ counts.warn }} 项警告</span>
            <span v-if="counts.pass" class="v-pass">{{ counts.pass }} 项通过</span>
          </div>
          <div class="v-meta">
            <template v-if="result">
              共 {{ summary.total }} 个检查项 · 覆盖 {{ nodeCount }} 台服务器
              <template v-if="result.elapsed_seconds != null"> · 耗时 {{ result.elapsed_seconds }} 秒</template>
              <span v-if="summary.note" class="v-unchecked">{{ summary.note }}</span>
            </template>
            <template v-else>
              还没跑过。检查项由组网图推导 —— 每个角色该接哪几个平面, 就查哪几项。
            </template>
          </div>
        </div>

        <div class="v-action">
          <el-button type="primary" size="large" :loading="running" @click="run">
            <el-icon v-if="!running" class="btn-icon"><TrendCharts /></el-icon>
            {{ result ? '重新诊断' : '开始诊断' }}
          </el-button>
          <span class="v-time">{{ lastRunText }}</span>
        </div>
      </section>

      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        :closable="false"
        class="block"
      />

      <!-- 模板台数和实际对不上, 这本身就是要查的事 -->
      <el-alert
        v-if="mismatches.length"
        type="warning"
        show-icon
        :closable="false"
        class="block"
        title="实际台数与模板不一致"
      >
        <div v-for="m in mismatches" :key="m" class="mismatch">{{ m }}</div>
      </el-alert>

      <!-- 四平面概览 -->
      <section v-if="result" class="planes">
        <div v-for="p in planeStats" :key="p.key" class="plane cm-card">
          <div class="p-head">
            <svg width="20" height="8" viewBox="0 0 20 8" aria-hidden="true">
              <line x1="1" y1="4" x2="19" y2="4"
                :stroke="planeColor(p.key)"
                :stroke-width="PLANE_WIDTH[p.key]"
                :stroke-dasharray="p.key === 'data_back' ? '6,4' : null"
                stroke-linecap="round" />
            </svg>
            <span class="p-name" :style="{ color: planeColor(p.key) }">{{ p.label }}</span>
          </div>
          <div class="p-count">
            <span class="p-num" :class="{ 'p-num--bad': p.fail }">{{ p.pass }}</span>
            <span class="p-den">/ {{ p.total }} 通</span>
          </div>
          <span class="cm-chip" :class="`cm-chip--${p.status}`">{{ p.text }}</span>
        </div>
      </section>

      <!-- 检查结果: 故障在最上面 -->
      <section v-if="result" class="results cm-card">
        <header class="r-head">
          <span class="r-title">检查结果</span>
          <span class="r-sub">按严重度排, 要动手的永远在最上面</span>
          <div class="spacer"></div>
          <el-button size="small" @click="exportReport">导出报告</el-button>
        </header>

        <div v-if="actionable.length" class="rows">
          <article v-for="item in actionable" :key="item.id" class="row">
            <span class="cm-dot" :class="`cm-dot--${dotOf(item.status)}`"></span>
            <div class="r-body">
              <div class="r-line">
                <span class="r-name">{{ item.title }}</span>
                <span class="r-target cm-mono" :style="{ color: item.plane ? planeColor(item.plane) : 'var(--cm-text-2)' }">
                  {{ item.target }}<template v-if="item.host"> · {{ item.host }}</template>
                </span>
                <span class="r-role">{{ item.role_label }}</span>
              </div>
              <div v-if="item.detail" class="r-detail">{{ item.detail }}</div>
              <div v-if="item.suggestion" class="r-suggest" :class="`r-suggest--${dotOf(item.status)}`">
                建议：{{ item.suggestion }}
              </div>
            </div>
            <el-button
              v-if="item.status === 'fail'"
              size="small"
              plain
              type="primary"
              class="r-locate"
              @click="locate(item)"
            >在组网图定位</el-button>
          </article>
        </div>

        <!-- 没查的项单独一组, 不混在通过里 —— 把没查的算成通过比没有报告更糟 -->
        <button v-if="unchecked.length" type="button" class="fold" @click="showUnchecked = !showUnchecked">
          <span class="cm-dot cm-dot--idle"></span>
          <span class="fold-name">{{ unchecked.length }} 项未检查</span>
          <span class="fold-sub">{{ uncheckedReason }}</span>
          <div class="spacer"></div>
          <el-icon class="fold-arrow" :class="{ 'is-open': showUnchecked }"><ArrowDown /></el-icon>
        </button>
        <div v-if="showUnchecked" class="rows rows--quiet">
          <article v-for="item in unchecked" :key="item.id" class="row">
            <span class="cm-dot cm-dot--idle"></span>
            <div class="r-body">
              <div class="r-line">
                <span class="r-name r-name--quiet">{{ item.title }}</span>
                <span class="r-target cm-mono">{{ item.target }}</span>
              </div>
              <div v-if="item.detail" class="r-detail">{{ item.detail }}</div>
              <div v-if="item.suggestion" class="r-detail">{{ item.suggestion }}</div>
            </div>
          </article>
        </div>

        <button v-if="passed.length" type="button" class="fold" @click="showPassed = !showPassed">
          <span class="cm-dot cm-dot--pass"></span>
          <span class="fold-name">{{ passed.length }} 项通过</span>
          <span class="fold-sub">{{ passedBreakdown }}</span>
          <div class="spacer"></div>
          <el-icon class="fold-arrow" :class="{ 'is-open': showPassed }"><ArrowDown /></el-icon>
        </button>
        <div v-if="showPassed" class="rows rows--quiet">
          <article v-for="item in passed" :key="item.id" class="row">
            <span class="cm-dot cm-dot--pass"></span>
            <div class="r-body">
              <div class="r-line">
                <span class="r-name r-name--quiet">{{ item.title }}</span>
                <span class="r-target cm-mono">{{ item.target }}</span>
                <span class="r-detail">{{ item.detail }}</span>
              </div>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, markRaw, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  TrendCharts, CircleCheck, Warning, CircleClose, QuestionFilled, ArrowDown
} from '@element-plus/icons-vue'
import axios from 'axios'
import { currentCluster, loadClusters } from '@/stores/cluster'
import { planeColors, PLANE_LABEL, PLANE_WIDTH } from '@/styles/tokens'

const router = useRouter()
const current = currentCluster

const running = ref(false)
const error = ref('')
const result = ref(null)
const showPassed = ref(false)
const showUnchecked = ref(false)

const VERDICT_ICON = {
  fail: markRaw(CircleClose),
  warn: markRaw(Warning),
  pass: markRaw(CircleCheck),
  skip: markRaw(QuestionFilled),
}

// 解析一次就缓存住。每行都去 getComputedStyle 的话, 149 个检查项每次重渲染
// 就是 149 次样式计算。颜色仍然只在 theme.css 里定义一处。
const PLANE_COLOR = planeColors()
const planeColor = (key) => PLANE_COLOR[key] || 'var(--cm-text-2)'

const summary = computed(() => result.value?.summary || {
  verdict: 'skip', headline: '尚未诊断', total: 0, counts: {}, unchecked: 0, note: '',
})
const counts = computed(() => summary.value.counts || {})
const items = computed(() => result.value?.items || [])
const mismatches = computed(() => result.value?.mismatches || [])
const nodeCount = computed(() => current.value?.node_count ?? 0)

// fail / warn 是要动手的; skip / pending 是没查的; pass 折叠起来
const actionable = computed(() => items.value.filter(i => i.status === 'fail' || i.status === 'warn'))
const unchecked = computed(() => items.value.filter(i => i.status === 'skip' || i.status === 'pending'))
const passed = computed(() => items.value.filter(i => i.status === 'pass'))

const dotOf = (status) => ({ fail: 'fail', warn: 'warn', pass: 'pass' }[status] || 'idle')

const uncheckedReason = computed(() => {
  const noScript = unchecked.value.filter(i => i.kind === 'script' && !i.script_id).length
  const noAddr = unchecked.value.filter(i => i.kind === 'builtin').length
  const parts = []
  if (noScript) parts.push(`${noScript} 项没有脚本认领`)
  if (noAddr) parts.push(`${noAddr} 项模板里没配地址`)
  return parts.join(' · ')
})

const passedBreakdown = computed(() => {
  const by = {}
  passed.value.forEach(i => { by[i.category] = (by[i.category] || 0) + 1 })
  return Object.entries(by).map(([k, v]) => `${k} ${v}`).join(' · ')
})

const planeStats = computed(() => {
  const acc = {}
  items.value.filter(i => i.check === 'ping' && i.plane).forEach(i => {
    const slot = acc[i.plane] || (acc[i.plane] = { key: i.plane, label: PLANE_LABEL[i.plane] || i.plane, pass: 0, warn: 0, fail: 0, total: 0 })
    slot.total += 1
    if (i.status === 'pass') slot.pass += 1
    else if (i.status === 'warn') { slot.pass += 1; slot.warn += 1 }
    else if (i.status === 'fail') slot.fail += 1
  })
  return Object.values(acc).map(p => ({
    ...p,
    status: p.fail ? 'fail' : (p.warn ? 'warn' : (p.total ? 'pass' : 'idle')),
    text: p.fail ? `${p.fail} 台不通` : (p.warn ? `${p.warn} 台延迟偏高` : '全部正常'),
  }))
})

const lastRunText = computed(() => {
  const at = result.value?.diagnosed_at || current.value?.last_diagnosed_at
  if (!at) return '尚未诊断'
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? '尚未诊断' : `上次 ${d.toLocaleString('zh-CN', { hour12: false })}`
})

const run = async () => {
  if (!current.value) return
  running.value = true
  error.value = ''
  try {
    const { data } = await axios.post(`/api/clusters/${current.value.id}/diagnose`)
    result.value = data
    // 侧栏那张卡要跟着更新"上次诊断"和节点数
    loadClusters({ force: true })
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message || '诊断失败'
  } finally {
    running.value = false
  }
}

const locate = (item) => {
  router.push({ path: '/network', query: { focus: item.target } })
}

const exportReport = () => {
  if (!result.value) return
  const c = result.value.cluster || {}
  const lines = [
    `集群体检报告`,
    `集群      ${c.name || ''}`,
    `产品      ${c.product || ''}`,
    `机台类型  ${c.machine_type || ''}`,
    `时间      ${new Date(result.value.diagnosed_at).toLocaleString('zh-CN', { hour12: false })}`,
    `结论      ${summary.value.headline}${summary.value.note ? ' · ' + summary.value.note : ''}`,
    '',
  ]
  const STATUS = { fail: '故障', warn: '警告', pass: '通过', skip: '未检查', pending: '待执行' }
  items.value.forEach(i => {
    lines.push(`[${STATUS[i.status] || i.status}] ${i.target}  ${i.title}${i.host ? '  ' + i.host : ''}`)
    if (i.detail) lines.push(`        ${i.detail}`)
    if (i.suggestion) lines.push(`        建议: ${i.suggestion}`)
  })
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `体检报告-${c.name || 'cluster'}-${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('报告已导出')
}

// 换集群就把上一套的结果清掉, 别让人看着旧结果以为是新的
watch(() => current.value?.id, () => {
  result.value = null
  error.value = ''
})
</script>

<style scoped>
.checkup { display: flex; flex-direction: column; gap: 16px; }
.spacer { flex-grow: 1; }
.block { margin: 0; }

/* ── 大结论 ── */
.verdict { padding: 20px 24px; display: flex; align-items: center; gap: 22px; }
.verdict--fail { border-color: var(--cm-crit-line); }

.v-badge {
  width: 62px; height: 62px; flex-shrink: 0;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 2px solid;
}
.v-badge--fail { background: var(--cm-crit-bg); border-color: var(--cm-crit-line); color: var(--cm-crit); }
.v-badge--warn { background: var(--cm-warn-bg); border-color: var(--cm-warn-line); color: var(--cm-warn); }
.v-badge--pass { background: var(--cm-ok-bg);   border-color: var(--cm-ok-line);   color: var(--cm-ok); }
.v-badge--skip { background: var(--cm-idle-bg); border-color: var(--cm-idle-line); color: var(--cm-idle); }

.v-body { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.v-line { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.v-headline { font-size: 27px; font-weight: 700; letter-spacing: -0.4px; }
.v-headline--fail { color: var(--cm-crit); }
.v-headline--warn { color: var(--cm-warn); }
.v-headline--pass { color: var(--cm-ok); }
.v-headline--skip { color: var(--cm-idle); }
.v-warn { font-size: 18px; font-weight: 600; color: var(--cm-warn); }
.v-pass { font-size: 15px; color: var(--cm-text-2); }
.v-meta { font-size: 13px; color: var(--cm-text-2); line-height: 1.6; }
.v-unchecked { color: var(--cm-warn); font-weight: 600; margin-left: 8px; }

.v-action { display: flex; flex-direction: column; align-items: flex-end; gap: 8px; margin-left: auto; }
.btn-icon { margin-right: 6px; }
.v-time { font-size: 11px; color: var(--cm-text-3); }

.mismatch { font-size: 13px; line-height: 1.8; }

/* ── 四平面 ── */
.planes { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; }
.plane { padding: 15px 17px; display: flex; flex-direction: column; gap: 9px; }
.p-head { display: flex; align-items: center; gap: 8px; }
.p-name { font-size: 13px; font-weight: 700; }
.p-count { display: flex; align-items: baseline; gap: 5px; }
.p-num { font-size: 30px; font-weight: 700; color: var(--cm-text); letter-spacing: -1px; }
.p-num--bad { color: var(--cm-crit); }
.p-den { font-size: 14px; color: var(--cm-text-3); }
.plane .cm-chip { align-self: flex-start; }

/* ── 结果列表 ── */
.results { display: flex; flex-direction: column; overflow: hidden; }
.r-head {
  height: 46px; flex-shrink: 0;
  background: var(--cm-surface-2);
  border-bottom: 1px solid var(--cm-border);
  display: flex; align-items: center; gap: 9px; padding: 0 20px;
}
.r-title { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.r-sub { font-size: 12px; color: var(--cm-text-2); }

.rows { display: flex; flex-direction: column; }
.rows--quiet { background: var(--cm-bg); }
.row {
  display: flex; align-items: flex-start; gap: 14px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--cm-border-light);
}
.row .cm-dot { margin-top: 5px; }
.r-body { flex-grow: 1; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.r-line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.r-name { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.r-name--quiet { font-weight: 500; color: var(--cm-text-2); }
.r-target { font-size: 12px; font-weight: 600; }
.r-role { font-size: 11px; color: var(--cm-text-3); }
.r-detail { font-size: 12px; color: var(--cm-text-2); line-height: 1.6; }
.r-suggest { font-size: 12px; line-height: 1.6; }
.r-suggest--fail { color: var(--cm-crit); }
.r-suggest--warn { color: var(--cm-warn); }
.r-locate { flex-shrink: 0; }

.fold {
  display: flex; align-items: center; gap: 11px;
  width: 100%; box-sizing: border-box;
  padding: 14px 20px;
  background: var(--cm-surface);
  border: none; border-top: 1px solid var(--cm-border-light);
  font-family: inherit; text-align: left; cursor: pointer;
}
.fold:hover { background: var(--cm-surface-2); }
.fold-name { font-size: 13px; font-weight: 600; color: var(--cm-text); }
.fold-sub { font-size: 12px; color: var(--cm-text-2); }
.fold-arrow { color: var(--cm-text-3); transition: transform .15s; }
.fold-arrow.is-open { transform: rotate(180deg); }
</style>
