<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/api'
import EChart from '@/components/EChart.vue'
import AppIcon from '@/components/AppIcon.vue'

const data = ref(null)
const loading = ref(true)
const error = ref('')
const filters = reactive({ from: '', to: '', department: '' })

const isSingleMonth = computed(() => data.value?.period?.from === data.value?.period?.to)
const periodLabel = computed(() => {
  const start = data.value?.period?.from
  const end = data.value?.period?.to
  if (!start || !end) return '未选择周期'
  const format = (value) => {
    const [year, month] = value.split('-')
    return `${year} 年 ${Number(month)} 月`
  }
  return start === end ? format(start) : `${format(start)} — ${format(end)}`
})
const sourceDescription = computed(() => {
  const count = data.value?.period?.batch_count || 0
  const latest = data.value?.batch
  if (!latest) return '所选周期暂无已完成的导入批次'
  const source = count === 1 ? `数据来自 ${latest.original_filename}` : `已汇总 ${count} 个导入批次`
  const department = filters.department ? ` · ${filters.department}` : ' · 全部部门'
  return `${source}${department}，最后处理于 ${new Date(latest.completed_at).toLocaleString()}`
})
const availableValues = computed(() => (data.value?.available_periods || []).map((item) => item.value).sort())

const lineOption = computed(() => ({
  animationDuration: 650,
  tooltip: { trigger: 'axis', valueFormatter: (value) => `${value}%` },
  grid: { left: 42, right: 20, top: 32, bottom: 38 },
  xAxis: {
    type: 'category', boundaryGap: false,
    data: (data.value?.daily || []).map((item) => isSingleMonth.value ? item.date.slice(8) : item.date.slice(5).replace('-', '/')),
    axisLine: { lineStyle: { color: '#CBD5E1' } }, axisTick: { show: false }, axisLabel: { color: '#64748B', hideOverlap: true },
  },
  yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', color: '#64748B' }, splitLine: { lineStyle: { color: '#E2E8F0', type: 'dashed' } } },
  series: [{
    name: '出勤率', type: 'line', smooth: 0.35, showSymbol: false,
    data: (data.value?.daily || []).map((item) => item.rate),
    lineStyle: { color: '#0F9F8F', width: 3 }, itemStyle: { color: '#0F9F8F' },
    areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(15,159,143,.24)' }, { offset: 1, color: 'rgba(15,159,143,0)' }] } },
  }],
}))

const departmentOption = computed(() => {
  const rows = [...(data.value?.departments || [])].sort((a, b) => b.attendance_rate - a.attendance_rate).slice(0, 8)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } }, grid: { left: 92, right: 28, top: 18, bottom: 24 },
    xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%', color: '#64748B' }, splitLine: { lineStyle: { color: '#E2E8F0' } } },
    yAxis: { type: 'category', inverse: true, data: rows.map((row) => row.department), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#334155', width: 78, overflow: 'truncate' } },
    series: [{ type: 'bar', data: rows.map((row) => row.attendance_rate), barWidth: 12, itemStyle: { color: '#334155', borderRadius: [0, 8, 8, 0] }, label: { show: true, position: 'right', formatter: '{c}%', color: '#475569' } }],
  }
})

async function load(useFilters = false) {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams()
    if (useFilters && filters.from) params.set('from', filters.from)
    if (useFilters && filters.to) params.set('to', filters.to)
    if (useFilters && filters.department) params.set('department', filters.department)
    const payload = await api(`dashboard/${params.size ? `?${params}` : ''}`)
    data.value = payload
    if (!filters.from) filters.from = payload.period?.from || ''
    if (!filters.to) filters.to = payload.period?.to || ''
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  if (filters.from && filters.to && filters.from > filters.to) {
    error.value = '起始月份不能晚于结束月份'
    return
  }
  load(true)
}

function showLatest() {
  const values = availableValues.value
  if (!values.length) return
  filters.from = values.at(-1)
  filters.to = values.at(-1)
  applyFilters()
}

function showAll() {
  const values = availableValues.value
  if (!values.length) return
  filters.from = values[0]
  filters.to = values.at(-1)
  applyFilters()
}

onMounted(() => load())
</script>

<template>
  <div class="page-stack">
    <section class="period-filter panel">
      <div class="period-filter__intro"><span class="panel-kicker">DASHBOARD RANGE</span><strong>选择看板统计范围</strong><small>可查看单月，也可跨月汇总</small></div>
      <label class="field-label">起始月份<input v-model="filters.from" type="month" /></label>
      <span class="period-filter__dash">—</span>
      <label class="field-label">结束月份<input v-model="filters.to" type="month" /></label>
      <label class="field-label period-filter__department">部门<select v-model="filters.department"><option value="">全部部门</option><option v-for="department in data?.available_departments || []" :key="department" :value="department">{{ department }}</option></select></label>
      <button class="primary-button" :disabled="loading" @click="applyFilters">{{ loading ? '加载中…' : '更新看板' }}</button>
      <div class="period-filter__quick"><button class="text-button" @click="showLatest">最近月份</button><button class="text-button" @click="showAll">全部记录</button></div>
    </section>

    <div v-if="loading" class="skeleton-block"></div>
    <div v-else-if="error" class="empty-state"><strong>看板加载失败</strong><p>{{ error }}</p><button class="secondary-button" @click="applyFilters">重试</button></div>
    <template v-else-if="data?.batches?.length">
      <div class="page-hero">
        <div><span class="period-pill">{{ periodLabel }}</span><h2>{{ filters.department ? `${filters.department}考勤概览` : '考勤概览' }}</h2><p>{{ sourceDescription }}</p></div>
        <router-link class="primary-button" :to="{ name: 'imports' }">导入新打卡表</router-link>
      </div>

      <section class="kpi-grid">
        <article class="kpi-card kpi-card--ink"><span>纳入核算人数</span><strong>{{ data.kpis.employees }}</strong><small>{{ filters.department || '全部部门' }}去重人数</small><i>人</i></article>
        <article class="kpi-card"><span>期间出勤率</span><strong>{{ data.kpis.attendance_rate }}%</strong><small>实际出勤 ÷ 应出勤</small><i class="trend-up"><AppIcon name="arrow-right" :size="16" /></i></article>
        <article class="kpi-card"><span>需要复核</span><strong>{{ data.kpis.review_count }}</strong><small>所选范围内去重人数</small><i class="warning-dot"><AppIcon name="alert-circle" :size="15" /></i></article>
        <article class="kpi-card"><span>跨日待审核</span><strong>{{ data.kpis.pending_cross_day }}</strong><small>所选范围内凌晨单条打卡</small><i class="amber-dot"><AppIcon name="clock" :size="15" /></i></article>
      </section>

      <section class="dashboard-grid">
        <article class="panel panel--wide">
          <header class="panel__header"><div><span class="panel-kicker">DAILY TREND</span><h3>每日出勤率走势</h3></div><span class="legend-dot"><i></i>出勤率</span></header>
          <EChart class="chart-large" :option="lineOption" />
        </article>
        <article class="panel">
          <header class="panel__header"><div><span class="panel-kicker">DEPARTMENT</span><h3>{{ filters.department ? '所选部门出勤概况' : '部门出勤对比' }}</h3></div></header>
          <EChart class="chart-large" :option="departmentOption" />
        </article>
      </section>

      <section class="dashboard-grid dashboard-grid--lower">
        <article class="panel">
          <header class="panel__header"><div><span class="panel-kicker">DATA QUALITY</span><h3>所选周期整体导入质量</h3></div><span>{{ data.period.batch_count }} 个批次</span></header>
          <div class="quality-list">
            <div><span>总记录</span><strong>{{ data.summary.total_rows }}</strong></div>
            <div><span>成功匹配</span><strong class="text-success">{{ data.summary.matched_rows }}</strong></div>
            <div><span>未匹配</span><strong class="text-warning">{{ data.summary.unmatched_rows }}</strong></div>
            <div><span>跨日疑似</span><strong>{{ data.summary.suspicion_count }}</strong></div>
          </div>
        </article>
        <article class="panel panel--wide">
          <header class="panel__header"><div><span class="panel-kicker">REVIEW QUEUE</span><h3>待办提醒</h3></div><router-link class="button-with-icon" :to="{ name: 'suspicions' }"><span>查看全部</span><AppIcon name="arrow-right" :size="15" /></router-link></header>
          <div class="todo-strip">
            <div class="todo-card todo-card--amber"><span>01</span><div><strong>{{ data.kpis.pending_cross_day }} 条跨日记录</strong><p>需要判断归入前一天还是保留当天</p></div></div>
            <div class="todo-card"><span>02</span><div><strong>{{ data.kpis.review_count }} 人待核对</strong><p>实际出勤与默认应出勤存在差异</p></div></div>
            <div class="todo-card"><span>03</span><div><strong>{{ data.summary.unmatched_rows }} 条未匹配</strong><p>这是所选周期整体数据，建议补充工号或人员别名</p></div></div>
          </div>
        </article>
      </section>
    </template>
    <div v-else-if="data?.available_periods?.length" class="empty-state empty-state--hero">
      <div class="empty-state__icon"><AppIcon name="clock" :size="29" /></div><strong>所选范围暂无考勤数据</strong><p>请调整起止月份，或点击“全部记录”查看已有批次。</p><button class="primary-button" @click="showAll">查看全部记录</button>
    </div>
    <div v-else class="empty-state empty-state--hero">
      <div class="empty-state__icon"><AppIcon name="upload" :size="29" /></div><strong>先导入第一份打卡表</strong><p>系统会自动匹配人员、识别跨日打卡并生成核算结果。</p><router-link class="primary-button" :to="{ name: 'imports' }">前往导入</router-link>
    </div>
  </div>
</template>
