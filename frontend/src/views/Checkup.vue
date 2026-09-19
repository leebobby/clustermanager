<template>
  <div class="checkup">
    <el-empty v-if="!ready" description="还没选机台类型" />

    <template v-else>
      <!-- 选这次要查什么。全量跑在现场不现实, 所以先勾再跑 -->
      <section class="picker cm-card">
        <header class="pk-head">
          <span class="pk-title">这次查什么</span>
          <span class="pk-sub">勾上的才跑。没勾的不会出现在报告里</span>
          <div class="spacer"></div>
          <el-button link type="primary" size="small" @click="presetQuick">只查连通性</el-button>
          <el-button link type="primary" size="small" @click="presetAll">全选可跑的</el-button>
        </header>

        <div class="pk-body">
          <div class="pk-row">
            <span class="pk-label">检查项</span>
            <div class="pk-chips">
              <button
                v-for="c in options.checks"
                :key="c.key"
                type="button"
                class="chip"
                :class="{ 'is-on': picked.checks.includes(c.key), 'is-dead': !c.ready }"
                :title="c.ready ? '' : '没有脚本认领这项, 勾了也跑不出结果'"
                @click="toggle('checks', c.key)"
              >
                <span class="chip-name">{{ c.label }}</span>
                <span class="chip-count">{{ c.count }}</span>
                <span v-if="!c.ready" class="chip-dead">缺脚本</span>
              </button>
            </div>
          </div>

          <div class="pk-row">
            <span class="pk-label">角色范围</span>
            <div class="pk-chips">
              <button
                v-for="r in options.roles"
                :key="r.key"
                type="button"
                class="chip"
                :class="{ 'is-on': picked.roles.includes(r.key) }"
                @click="toggle('roles', r.key)"
              >
                <span class="chip-name">{{ r.label }}</span>
                <span class="chip-count">{{ r.count }}</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- 大结论 -->
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
              跑了 {{ summary.total }} 项 · {{ ws.machineType }} · {{ ws.nodeCount }} 台
              <template v-if="result.elapsed_seconds != null"> · 耗时 {{ result.elapsed_seconds }} 秒</template>
              <span v-if="summary.note" class="v-unchecked">{{ summary.note }}</span>
            </template>
            <template v-else>
              按当前勾选会跑 <b>{{ plannedCount }}</b> 项。检查项由组网图推导 ——
              每个角色该接哪几个平面就查哪几项, Master 数据面四个口是四项。
            </template>
          </div>
        </div>

        <div class="v-action">
          <el-button
            type="primary" size="large"
            :loading="running" :disabled="!plannedCount"
            @click="run"
          >
            <el-icon v-if="!running" class="btn-icon"><TrendCharts /></el-icon>
            {{ result ? '重新诊断' : '开始诊断' }}
          </el-button>
          <span class="v-time">{{ plannedCount ? `本次 ${plannedCount} 项` : '还没勾任何检查项' }}</span>
        </div>
      </section>

      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="block" />

      <el-alert
        v-if="mismatches.length"
        type="warning" show-icon :closable="false" class="block"
        title="实际台数与模板不一致"
      >
        <div v-for="m in mismatches" :key="m" class="mismatch">{{ m }}</div>
      </el-alert>

      <!-- 平面概览 -->
      <section v-if="result && planeStats.length" class="planes">
        <div v-for="p in planeStats" :key="p.key" class="plane cm-card">
          <div class="p-head">
            <svg width="20" height="8" viewBox="0 0 20 8" aria-hidden="true">
              <line x1="1" y1="4" x2="19" y2="4"
                :stroke="planeColor(p.key)" :stroke-width="PLANE_WIDTH[p.key]"
                :stroke-dasharray="p.key === 'data_back' ? '6,4' : null" stroke-linecap="round" />
            </svg>
            <span class="p-name" :style="{ color: planeColor(p.key) }">{{ p.label }}</span>
          </div>
          <div class="p-count">
            <span class="p-num" :class="{ 'p-num--bad': p.fail }">{{ p.pass }}</span>
            <span class="p-den">/ {{ p.total }} 个口通</span>
          </div>
          <span class="cm-chip" :class="`cm-chip--${p.status}`">{{ p.text }}</span>
        </div>
      </section>

      <!-- 结果 -->
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
              size="small" plain type="primary" class="r-locate"
              @click="locate(item)"
            >在组网图定位</el-button>
          </article>
        </div>

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
import { computed, markRaw, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  TrendCharts, CircleCheck, Warning, CircleClose, QuestionFilled, ArrowDown
} from '@element-plus/icons-vue'
import axios from 'axios'
import { ws, ready } from '@/stores/workspace'
import { planeColors, PLANE_LABEL, PLANE_WIDTH } from '@/styles/tokens'

const router = useRouter()

const running = ref(false)
const error = ref('')
const result = ref(null)
const showPassed = ref(false)
const showUnchecked = ref(false)
const options = reactive({ checks: [], roles: [], total: 0, matrix: {} })
const picked = reactive({ checks: [], roles: [] })

const VERDICT_ICON = {
  fail: markRaw(CircleClose),
  warn: markRaw(Warning),
  pass: markRaw(CircleCheck),
  skip: markRaw(QuestionFilled),
}

const PLANE_COLOR = planeColors()
const planeColor = (key) => PLANE_COLOR[key] || 'var(--cm-text-2)'

const summary = computed(() => result.value?.summary || {
  verdict: 'skip', headline: '尚未诊断', total: 0, counts: {}, unchecked: 0, note: '',
})
const counts = computed(() => summary.value.counts || {})
const items = computed(() => result.value?.items || [])
const mismatches = computed(() => result.value?.mismatches || [])

const actionable = computed(() => items.value.filter(i => i.status === 'fail' || i.status === 'warn'))
const unchecked = computed(() => items.value.filter(i => i.status === 'skip' || i.status === 'pending'))
const passed = computed(() => items.value.filter(i => i.status === 'pass'))

const dotOf = (status) => ({ fail: 'fail', warn: 'warn', pass: 'pass' }[status] || 'idle')

// 这次会跑多少项 —— 从后端给的 (检查项 x 角色) 精确计数里取, 不做比例估算
const plannedCount = computed(() => {
  let n = 0
  picked.checks.forEach(c => {
    const row = options.matrix[c] || {}
    picked.roles.forEach(r => { n += row[r] || 0 })
  })
  return n
})

const uncheckedReason = computed(() => {
  const noScript = unchecked.value.filter(i => i.kind === 'script' && !i.script_id).length
  const noAddr = unchecked.value.filter(i => i.kind === 'builtin').length
  const parts = []
  if (noScript) parts.push(`${noScript} 项没有脚本认领`)
  if (noAddr) parts.push(`${noAddr} 项探测不成`)
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
    const slot = acc[i.plane] || (acc[i.plane] = {
      key: i.plane, label: PLANE_LABEL[i.plane] || i.plane, pass: 0, warn: 0, fail: 0, total: 0,
    })
    slot.total += 1
    if (i.status === 'pass') slot.pass += 1
    else if (i.status === 'warn') { slot.pass += 1; slot.warn += 1 }
    else if (i.status === 'fail') slot.fail += 1
  })
  const ORDER = ['management', 'control', 'data_front', 'data_back']
  return ORDER.filter(k => acc[k]).map(k => acc[k]).map(p => ({
    ...p,
    status: p.fail ? 'fail' : (p.warn ? 'warn' : (p.total ? 'pass' : 'idle')),
    text: p.fail ? `${p.fail} 个口不通` : (p.warn ? `${p.warn} 个口延迟偏高` : '全部正常'),
  }))
})

const toggle = (kind, key) => {
  const arr = picked[kind]
  const i = arr.indexOf(key)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(key)
}

// 默认只勾连通性 —— 它最快、不需要登机器, 现场十有八九先看这个
const presetQuick = () => {
  picked.checks = options.checks.filter(c => c.ready && c.kind === 'builtin').map(c => c.key)
  picked.roles = options.roles.map(r => r.key)
}
const presetAll = () => {
  picked.checks = options.checks.filter(c => c.ready).map(c => c.key)
  picked.roles = options.roles.map(r => r.key)
}

const loadOptions = async () => {
  error.value = ''
  try {
    const { data } = await axios.get('/api/workspace/diagnose/options')
    options.checks = data.checks || []
    options.roles = data.roles || []
    options.total = data.total || 0
    options.matrix = data.matrix || {}
    presetQuick()
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message || '读取检查项失败'
  }
}

const run = async () => {
  running.value = true
  error.value = ''
  try {
    const { data } = await axios.post('/api/workspace/diagnose', {
      checks: picked.checks,
      roles: picked.roles,
    })
    result.value = data
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message || '诊断失败'
  } finally {
    running.value = false
  }
}

const locate = (item) => router.push({ path: '/network', query: { focus: item.target } })

const exportReport = () => {
  if (!result.value) return
  const lines = [
    '机台体检报告',
    `产品      ${result.value.product || ''}`,
    `机台类型  ${result.value.machine_type || ''}`,
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
  a.download = `体检报告-${result.value.machine_type || 'machine'}-${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('报告已导出')
}

// 换机台类型就把上一台的结果清掉, 别让人看着旧结果以为是新的
watch(() => `${ws.product}/${ws.machineType}`, () => {
  result.value = null
  if (ready.value) loadOptions()
})

onMounted(() => { if (ready.value) loadOptions() })
</script>

<style scoped>
.checkup { display: flex; flex-direction: column; gap: 16px; }
.spacer { flex-grow: 1; }
.block { margin: 0; }

/* 选检查项 */
.picker { display: flex; flex-direction: column; }
.pk-head {
  display: flex; align-items: center; gap: 9px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--cm-border-light);
}
.pk-title { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.pk-sub { font-size: 12px; color: var(--cm-text-2); }
.pk-body { padding: 14px 18px; display: flex; flex-direction: column; gap: 12px; }
.pk-row { display: flex; align-items: flex-start; gap: 14px; }
.pk-label {
  width: 60px; flex-shrink: 0;
  font-size: 12px; font-weight: 700; color: var(--cm-text-3);
  line-height: 28px;
}
.pk-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  height: 28px; padding: 0 11px;
  background: var(--cm-surface);
  border: 1px solid var(--cm-border);
  border-radius: 999px;
  font-family: inherit; cursor: pointer;
}
.chip:hover { border-color: var(--cm-brand-line); }
.chip.is-on { background: var(--cm-brand-tint); border-color: var(--cm-brand); }
.chip.is-dead { opacity: .62; }
.chip-name { font-size: 12px; font-weight: 600; color: var(--cm-text); }
.chip.is-on .chip-name { color: var(--cm-brand); }
.chip-count { font-size: 11px; color: var(--cm-text-3); font-variant-numeric: tabular-nums; }
.chip-dead { font-size: 10px; color: var(--cm-warn); font-weight: 600; }

/* 大结论 */
.verdict { padding: 20px 24px; display: flex; align-items: center; gap: 22px; }
.verdict--fail { border-color: var(--cm-crit-line); }
.v-badge {
  width: 62px; height: 62px; flex-shrink: 0; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; border: 2px solid;
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

.planes { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; }
.plane { padding: 15px 17px; display: flex; flex-direction: column; gap: 9px; }
.p-head { display: flex; align-items: center; gap: 8px; }
.p-name { font-size: 13px; font-weight: 700; }
.p-count { display: flex; align-items: baseline; gap: 5px; }
.p-num { font-size: 30px; font-weight: 700; color: var(--cm-text); letter-spacing: -1px; }
.p-num--bad { color: var(--cm-crit); }
.p-den { font-size: 14px; color: var(--cm-text-3); }
.plane .cm-chip { align-self: flex-start; }

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
  padding: 14px 20px; border-bottom: 1px solid var(--cm-border-light);
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
  width: 100%; box-sizing: border-box; padding: 14px 20px;
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
