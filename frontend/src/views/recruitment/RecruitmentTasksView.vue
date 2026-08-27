<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import RecruitmentResultsNavigation from '@/components/RecruitmentResultsNavigation.vue'

const plans = ref([])
const loading = ref(true)
const loadError = ref('')
const search = ref('')
const stateFilter = ref('all')
const kindFilter = ref('all')
const visibility = ref('current')
const lastSyncedAt = ref(null)
let loadSequence = 0
let pollTimer = null
let componentAlive = true
let pollInFlight = false

const activeStates = new Set(['starting', 'running', 'pausing', 'stopping'])
const terminalStates = new Set(['stopped', 'failed', 'completed'])

function planState(plan, { preserveArchived = true } = {}) {
  if (preserveArchived && plan?.archived_at) return 'archived'
  const value = String(plan?.effective_state || plan?.actual_state || plan?.current_run?.status || plan?.desired_state || '')
  return { queued: 'starting', pending: 'starting', succeeded: 'completed', cancelled: 'stopped' }[value] || value || 'stopped'
}

function stateLabel(plan) {
  return {
    starting: '正在开启', running: '运行中', waiting_human: '等待人工', paused: '已暂停', pausing: '正在暂停',
    stopping: '正在停止', stopped: '已停止', failed: '运行失败', completed: '本轮完成', archived: '已删除',
  }[planState(plan)] || '状态同步中'
}

function stateGroup(plan) {
  const state = planState(plan, { preserveArchived: false })
  if (activeStates.has(state)) return 'active'
  if (state === 'waiting_human') return 'waiting'
  if (state === 'paused') return 'paused'
  if (terminalStates.has(state)) return 'ended'
  return state
}

function kindLabel(plan) {
  return plan?.kind === 'passive_resume' ? '被动咨询与简历获取' : '主动搜索并拉取简历'
}

function revisionLabel(plan) {
  const revision = plan?.current_revision?.revision
  return revision ? `方案 V${revision}` : '暂无方案版本'
}

function runLabel(plan) {
  return plan?.current_run?.id ? `运行 #${String(plan.current_run.id).slice(0, 8)}` : '暂无运行编号'
}

function formatDateTime(value) {
  const parsed = new Date(value)
  if (!value || Number.isNaN(parsed.getTime())) return '刚刚同步'
  return parsed.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function taskTo(plan) {
  return {
    name: 'recruitment-task-detail',
    params: { planId: String(plan.id) },
    query: {
      job: String(plan.job),
      run: plan.current_run?.id ? String(plan.current_run.id) : undefined,
      view: 'tasks',
      status: plan.archived_at ? 'archived' : undefined,
    },
  }
}

const sortedPlans = computed(() => [...plans.value].sort((left, right) => {
  const priority = { waiting: 0, active: 1, paused: 2, ended: 3 }
  const stateDelta = (priority[stateGroup(left)] ?? 4) - (priority[stateGroup(right)] ?? 4)
  return stateDelta || new Date(right.updated_at || 0).getTime() - new Date(left.updated_at || 0).getTime()
}))

const filteredPlans = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase('zh-CN')
  return sortedPlans.value.filter((plan) => {
    if (kindFilter.value !== 'all' && plan.kind !== kindFilter.value) return false
    if (stateFilter.value !== 'all' && stateGroup(plan) !== stateFilter.value) return false
    if (!keyword) return true
    return [plan.job_title, kindLabel(plan), revisionLabel(plan), runLabel(plan)]
      .some((value) => String(value || '').toLocaleLowerCase('zh-CN').includes(keyword))
  })
})

const summary = computed(() => ({
  total: plans.value.length,
  active: plans.value.filter((plan) => stateGroup(plan) === 'active').length,
  waiting: plans.value.filter((plan) => stateGroup(plan) === 'waiting').length,
  ended: plans.value.filter((plan) => stateGroup(plan) === 'ended').length,
}))

async function loadPlans({ silent = false } = {}) {
  if (silent && pollInFlight) return
  const sequence = ++loadSequence
  if (!silent) loading.value = true
  if (silent) pollInFlight = true
  const path = visibility.value === 'archived' ? 'recruitment/automation-plans/?archived=1' : 'recruitment/automation-plans/'
  try {
    const payload = await api(path)
    if (!componentAlive || sequence !== loadSequence) return
    plans.value = listItems(payload)
    loadError.value = ''
    lastSyncedAt.value = new Date()
  } catch (error) {
    if (sequence === loadSequence) loadError.value = error.message || '招聘任务读取失败'
  } finally {
    if (silent) pollInFlight = false
    if (!silent && sequence === loadSequence) loading.value = false
  }
}

watch(visibility, () => {
  stateFilter.value = 'all'
  plans.value = []
  loadError.value = ''
  lastSyncedAt.value = null
  loadPlans()
})

onMounted(() => {
  loadPlans()
  pollTimer = globalThis.setInterval(() => loadPlans({ silent: true }), 5000)
})

onUnmounted(() => {
  componentAlive = false
  loadSequence += 1
  if (pollTimer) globalThis.clearInterval(pollTimer)
})
</script>

<template>
  <div class="page-stack recruitment-tasks">
    <RecruitmentResultsNavigation />

    <header class="tasks-hero">
      <div><span>RESULT CENTER</span><h2>招聘任务</h2><p>跨岗位查看所有招聘作业；进入任务后可维护运行并直接查看业务结果。</p></div>
      <RouterLink class="tasks-primary-button" :to="{ name: 'recruitment-workbench', query: { new: '1' } }"><AppIcon name="plus" :size="14" />创建新任务</RouterLink>
    </header>

    <section class="tasks-summary" aria-label="招聘任务概览">
      <article><span>全部任务</span><strong>{{ summary.total }}</strong><small>{{ visibility === 'archived' ? '已删除记录' : '当前任务' }}</small></article>
      <article><span>进行中</span><strong>{{ summary.active }}</strong><small>正在开启或执行</small></article>
      <article><span>等待人工</span><strong>{{ summary.waiting }}</strong><small>需要 HR 处理</small></article>
      <article><span>已结束</span><strong>{{ summary.ended }}</strong><small>停止、完成或失败</small></article>
    </section>

    <section class="tasks-panel">
      <header class="tasks-panel__header">
        <div class="tasks-visibility" aria-label="任务可见范围">
          <button type="button" :class="{ 'is-active': visibility === 'current' }" @click="visibility = 'current'">当前任务</button>
          <button type="button" :class="{ 'is-active': visibility === 'archived' }" data-test="show-archived-tasks" @click="visibility = 'archived'">已删除任务</button>
        </div>
        <small v-if="lastSyncedAt && !loadError">最近同步 {{ formatDateTime(lastSyncedAt) }}</small>
      </header>

      <div class="tasks-filters">
        <label><span>搜索任务</span><input v-model="search" type="search" placeholder="搜索岗位、方案或运行编号" data-test="task-search" /></label>
        <label><span>运行状态</span><select v-model="stateFilter" data-test="task-state-filter"><option value="all">全部状态</option><option value="active">进行中</option><option value="waiting">等待人工</option><option value="paused">已暂停</option><option value="ended">已结束</option></select></label>
        <label><span>任务类型</span><select v-model="kindFilter" data-test="task-kind-filter"><option value="all">全部类型</option><option value="passive_resume">被动咨询</option><option value="active_resume_search">主动寻访</option></select></label>
      </div>

      <div v-if="loading" class="tasks-state tasks-state--loading" data-test="tasks-loading" aria-live="polite"><span></span><span></span><span></span><p>正在同步招聘任务…</p></div>
      <div v-else-if="loadError && !plans.length" class="tasks-state is-error" data-test="tasks-error" role="alert"><AppIcon name="alert-circle" :size="24" /><div><strong>招聘任务暂时无法加载</strong><p>{{ loadError }}</p></div><button type="button" @click="loadPlans()">重新加载</button></div>

      <template v-else>
        <p v-if="loadError" class="tasks-sync-warning" role="status">同步失败，当前展示上次成功结果。<button type="button" @click="loadPlans()">重试</button></p>
        <div v-if="filteredPlans.length" class="tasks-table" role="list" aria-label="招聘任务列表">
          <div class="tasks-table__head" aria-hidden="true"><span>招聘任务</span><span>类型与版本</span><span>当前状态</span><span>最近更新</span><span>操作</span></div>
          <article v-for="plan in filteredPlans" :key="plan.id" class="tasks-row" role="listitem" :data-test="`task-row-${plan.id}`">
            <div><strong>{{ plan.job_title || `职位 #${plan.job}` }}</strong><small>{{ runLabel(plan) }}</small></div>
            <div><span>{{ kindLabel(plan) }}</span><small>{{ revisionLabel(plan) }}</small></div>
            <span :class="['tasks-status', `is-${planState(plan)}`]"><i></i>{{ stateLabel(plan) }}</span>
            <time>{{ formatDateTime(plan.updated_at) }}</time>
            <RouterLink class="tasks-row__link" :to="taskTo(plan)" :data-test="`open-task-${plan.id}`">查看与维护<AppIcon name="chevron-right" :size="12" /></RouterLink>
          </article>
        </div>
        <div v-else class="tasks-state" data-test="tasks-empty">
          <AppIcon name="briefcase" :size="25" />
          <div><strong>{{ plans.length ? '没有符合筛选条件的任务' : visibility === 'archived' ? '没有已删除任务' : '还没有招聘任务' }}</strong><p>{{ plans.length ? '调整搜索词或筛选条件后再试。' : visibility === 'archived' ? '删除的终态任务会保留在这里。' : '从招聘作业台配置并执行后，任务会出现在这里。' }}</p></div>
          <RouterLink v-if="!plans.length && visibility === 'current'" :to="{ name: 'recruitment-workbench', query: { new: '1' } }">创建第一个任务</RouterLink>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.recruitment-tasks { --ink: #0f172a; --slate: #334155; --muted: #64748b; --line: #e2e8f0; --brand: #0f9f8f; --brand-dark: #087f73; --brand-soft: #eaf8f6; width: 100%; max-width: 100%; gap: 20px; color: var(--ink); container-type: inline-size; }
.recruitment-tasks *, .recruitment-tasks *::before, .recruitment-tasks *::after { box-sizing: border-box; }
.tasks-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; }
.tasks-hero > div { display: grid; gap: 5px; }
.tasks-hero span { color: var(--brand-dark); font-size: 10px; font-weight: 900; letter-spacing: .16em; }
.tasks-hero h2 { margin: 0; font-size: clamp(1.75rem, 1.2rem + 1.2cqi, 2.5rem); letter-spacing: -.035em; }
.tasks-hero p { margin: 0; color: var(--muted); font-size: 13px; }
.tasks-primary-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 40px; padding: 0 15px; border-radius: 10px; color: #fff; background: var(--brand); font-size: 12px; font-weight: 800; text-decoration: none; }
.tasks-primary-button:hover { background: var(--brand-dark); }
.tasks-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.tasks-summary article { display: grid; grid-template-columns: 1fr auto; gap: 6px 14px; padding: 17px 18px; border: 1px solid var(--line); border-radius: 15px; background: #fff; box-shadow: 0 1px 2px rgba(15, 23, 42, .025); }
.tasks-summary span, .tasks-summary small { color: var(--muted); font-size: 11px; font-weight: 700; }
.tasks-summary strong { grid-row: span 2; font-size: 26px; letter-spacing: -.04em; }
.tasks-summary small { font-weight: 500; }
.tasks-panel { overflow: hidden; border: 1px solid var(--line); border-radius: 18px; background: #fff; box-shadow: 0 2px 8px rgba(15, 23, 42, .025); }
.tasks-panel__header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 18px; border-bottom: 1px solid var(--line); }
.tasks-panel__header > small { color: var(--muted); font-size: 10px; }
.tasks-visibility { display: inline-flex; gap: 4px; padding: 3px; border-radius: 10px; background: #f1f5f4; }
.tasks-visibility button { min-height: 31px; padding: 0 12px; border: 0; border-radius: 8px; color: var(--muted); background: transparent; font-size: 11px; font-weight: 800; cursor: pointer; }
.tasks-visibility button.is-active { color: var(--brand-dark); background: #fff; box-shadow: 0 1px 3px rgba(15, 23, 42, .08); }
.tasks-filters { display: grid; grid-template-columns: minmax(240px, 1fr) minmax(150px, .3fr) minmax(170px, .3fr); gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--line); background: #fbfdfc; }
.tasks-filters label { display: grid; gap: 6px; }
.tasks-filters label > span { color: var(--muted); font-size: 10px; font-weight: 800; }
.tasks-filters input, .tasks-filters select { width: 100%; min-height: 38px; padding: 0 11px; border: 1px solid #d9e3e1; border-radius: 9px; color: var(--slate); background: #fff; font: 600 12px/1.3 inherit; outline: none; }
.tasks-filters input:focus, .tasks-filters select:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(15, 159, 143, .12); }
.tasks-table__head, .tasks-row { display: grid; grid-template-columns: minmax(200px, 1.1fr) minmax(180px, .9fr) minmax(110px, .5fr) minmax(130px, .55fr) minmax(120px, auto); align-items: center; gap: 18px; }
.tasks-table__head { min-height: 38px; padding: 0 18px; color: var(--muted); background: #f8faf9; font-size: 10px; font-weight: 800; letter-spacing: .06em; }
.tasks-row { min-height: 72px; padding: 13px 18px; border-top: 1px solid #edf2f1; transition: background 150ms ease; }
.tasks-row:hover { background: #fbfefd; }
.tasks-row > div { display: grid; gap: 4px; min-width: 0; color: var(--slate); font-size: 11px; }
.tasks-row strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.tasks-row small, .tasks-row time { color: var(--muted); font-size: 10px; }
.tasks-status { display: inline-flex; align-items: center; gap: 6px; width: fit-content; min-height: 25px; padding: 0 9px; border-radius: 999px; color: var(--slate); background: #f1f5f4; font-size: 10px; font-weight: 800; }
.tasks-status i { width: 6px; height: 6px; border-radius: 50%; background: #94a3b8; }
.tasks-status.is-running, .tasks-status.is-starting, .tasks-status.is-completed { color: var(--brand-dark); background: var(--brand-soft); }
.tasks-status.is-running i, .tasks-status.is-starting i, .tasks-status.is-completed i { background: var(--brand); }
.tasks-status.is-waiting_human, .tasks-status.is-paused, .tasks-status.is-pausing, .tasks-status.is-stopping { color: #9a5b08; background: #fff7e3; }
.tasks-status.is-waiting_human i, .tasks-status.is-paused i, .tasks-status.is-pausing i, .tasks-status.is-stopping i { background: #d97706; }
.tasks-status.is-failed, .tasks-status.is-archived { color: #b42332; background: #fff0f2; }
.tasks-status.is-failed i, .tasks-status.is-archived i { background: #dc4a4a; }
.tasks-row__link { display: inline-flex; align-items: center; justify-content: flex-end; gap: 4px; color: var(--brand-dark); font-size: 11px; font-weight: 800; text-decoration: none; }
.tasks-state { display: flex; align-items: center; justify-content: center; gap: 12px; min-height: 210px; padding: 30px; color: var(--muted); text-align: left; }
.tasks-state > div { display: grid; gap: 4px; }
.tasks-state strong { color: var(--slate); font-size: 13px; }
.tasks-state p { margin: 0; font-size: 11px; }
.tasks-state a, .tasks-state button, .tasks-sync-warning button { min-height: 34px; padding: 0 12px; border: 1px solid #b8ded8; border-radius: 9px; color: var(--brand-dark); background: #fff; font-size: 11px; font-weight: 800; text-decoration: none; cursor: pointer; }
.tasks-state--loading { display: grid; grid-template-columns: repeat(3, minmax(80px, 180px)); }
.tasks-state--loading span { height: 42px; border-radius: 8px; background: linear-gradient(90deg, #f1f5f4, #fafcfb, #f1f5f4); }
.tasks-state--loading p { grid-column: 1 / -1; text-align: center; }
.tasks-state.is-error { color: #b42332; }
.tasks-sync-warning { margin: 0; padding: 9px 18px; color: #9a5b08; background: #fff9ea; font-size: 11px; }
.recruitment-tasks a:focus-visible, .recruitment-tasks button:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
@container (max-width: 960px) {
  .tasks-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tasks-table__head { display: none; }
  .tasks-row { grid-template-columns: minmax(0, 1fr) auto; gap: 10px 18px; }
  .tasks-row > :nth-child(2), .tasks-row > time { grid-column: 1; }
  .tasks-status, .tasks-row__link { grid-column: 2; justify-self: end; }
}
@container (max-width: 620px) {
  .tasks-hero { align-items: stretch; flex-direction: column; }
  .tasks-primary-button { align-self: stretch; }
  .tasks-filters { grid-template-columns: 1fr; }
  .tasks-panel__header { align-items: flex-start; flex-direction: column; }
  .tasks-row { grid-template-columns: 1fr; }
  .tasks-row > :nth-child(n) { grid-column: 1; justify-self: start; }
}
</style>
