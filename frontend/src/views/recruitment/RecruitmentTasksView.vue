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
      <div><h2>招聘任务</h2><p>查看和维护所有岗位的招聘任务</p></div>
      <RouterLink class="tasks-primary-button" :to="{ name: 'recruitment-workbench', query: { new: '1' } }"><AppIcon name="plus" :size="16" />创建新任务</RouterLink>
    </header>

    <section class="tasks-summary" aria-label="招聘任务概览">
      <article><span>{{ visibility === 'archived' ? '已删除任务' : '全部任务' }}</span><strong>{{ summary.total }}</strong></article>
      <article><span>进行中</span><strong>{{ summary.active }}</strong></article>
      <article><span>等待人工</span><strong>{{ summary.waiting }}</strong></article>
      <article><span>已结束</span><strong>{{ summary.ended }}</strong></article>
    </section>

    <section class="tasks-panel">
      <header class="tasks-panel__header">
        <div class="tasks-visibility" aria-label="任务可见范围">
          <button type="button" :class="{ 'is-active': visibility === 'current' }" @click="visibility = 'current'">当前任务</button>
          <button type="button" :class="{ 'is-active': visibility === 'archived' }" data-test="show-archived-tasks" @click="visibility = 'archived'">已删除任务</button>
        </div>
        <small v-if="lastSyncedAt && !loadError">自动更新于 {{ formatDateTime(lastSyncedAt) }}</small>
      </header>

      <div class="tasks-filters">
        <label class="tasks-search"><span>搜索任务</span><span class="tasks-input"><AppIcon name="search" :size="17" /><input v-model="search" type="search" placeholder="岗位、方案或运行编号" data-test="task-search" /></span></label>
        <label><span>运行状态</span><span class="tasks-select"><select v-model="stateFilter" data-test="task-state-filter"><option value="all">全部状态</option><option value="active">进行中</option><option value="waiting">等待人工</option><option value="paused">已暂停</option><option value="ended">已结束</option></select><AppIcon name="chevron-down" :size="16" /></span></label>
        <label><span>任务类型</span><span class="tasks-select"><select v-model="kindFilter" data-test="task-kind-filter"><option value="all">全部类型</option><option value="passive_resume">被动咨询</option><option value="active_resume_search">主动寻访</option></select><AppIcon name="chevron-down" :size="16" /></span></label>
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
          <div><strong>{{ plans.length ? '没有符合筛选条件的任务' : visibility === 'archived' ? '没有已删除任务' : '还没有招聘任务' }}</strong><p v-if="plans.length">换个搜索词或筛选条件试试</p></div>
          <RouterLink v-if="!plans.length && visibility === 'current'" :to="{ name: 'recruitment-workbench', query: { new: '1' } }">创建任务</RouterLink>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.recruitment-tasks { --ink: #0f172a; --slate: #334155; --muted: #64748b; --line: #dfe7e6; --brand: #0f9f8f; --brand-dark: #087f73; --brand-soft: #eaf8f6; --danger: #dc4a4a; --warning: #d97706; --task-body: clamp(14px, .35rem + .55cqi, 18px); --task-detail: clamp(13px, .35rem + .45cqi, 16px); --task-meta: clamp(12px, .38rem + .34cqi, 14px); --task-control-height: clamp(44px, 2.25rem + .8cqi, 52px); --task-radius-control: clamp(10px, .45rem + .25cqi, 13px); --task-radius-panel: clamp(16px, .75rem + .4cqi, 21px); width: 100%; max-width: 100%; gap: clamp(18px, 1rem + .45cqi, 28px); color: var(--ink); font-family: var(--app-font-family); container-type: inline-size; }
.recruitment-tasks *, .recruitment-tasks *::before, .recruitment-tasks *::after { box-sizing: border-box; }
.tasks-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: clamp(20px, 2cqi, 32px); }
.tasks-hero > div { display: grid; gap: 6px; }
.tasks-hero h2 { margin: 0; font-size: clamp(2rem, 1.35rem + 1.1cqi, 2.75rem); letter-spacing: -.035em; }
.tasks-hero p { margin: 0; color: var(--muted); font-size: var(--task-body); }
.tasks-primary-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: var(--task-control-height); padding: 0 clamp(18px, 1rem + .45cqi, 24px); border: 1px solid var(--brand); border-radius: var(--task-radius-control); color: #fff; background: var(--brand); box-shadow: 0 8px 18px rgba(15, 159, 143, .16); font-size: var(--task-detail); font-weight: 800; text-decoration: none; transition: 160ms ease; }
.tasks-primary-button:hover { background: var(--brand-dark); border-color: var(--brand-dark); transform: translateY(-1px); }
.tasks-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; border: 1px solid var(--line); border-radius: var(--task-radius-panel); background: #fff; box-shadow: 0 2px 10px rgba(15, 23, 42, .025); }
.tasks-summary article { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: clamp(82px, 4rem + 1.7cqi, 106px); padding: clamp(18px, 1rem + .55cqi, 28px); border-left: 1px solid var(--line); }
.tasks-summary article:first-child { border-left: 0; }
.tasks-summary span { color: var(--muted); font-size: var(--task-detail); font-weight: 700; }
.tasks-summary strong { color: var(--ink); font-size: clamp(28px, 1.35rem + .75cqi, 38px); line-height: 1; letter-spacing: -.045em; font-variant-numeric: tabular-nums; }
.tasks-panel { overflow: hidden; border: 1px solid var(--line); border-radius: var(--task-radius-panel); background: #fff; box-shadow: 0 4px 18px rgba(15, 23, 42, .035); }
.tasks-panel__header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: clamp(14px, .75rem + .4cqi, 20px) clamp(18px, 1rem + .55cqi, 28px); border-bottom: 1px solid var(--line); }
.tasks-panel__header > small { color: var(--muted); font-size: var(--task-meta); }
.tasks-visibility { display: inline-flex; gap: 5px; padding: 4px; border-radius: 12px; background: #edf3f2; }
.tasks-visibility button { min-height: 38px; padding: 0 15px; border: 1px solid transparent; border-radius: 9px; color: var(--muted); background: transparent; font-size: var(--task-meta); font-weight: 800; cursor: pointer; }
.tasks-visibility button.is-active { color: var(--brand-dark); background: #fff; box-shadow: 0 1px 3px rgba(15, 23, 42, .08); }
.tasks-filters { display: grid; grid-template-columns: minmax(360px, 1fr) minmax(190px, .34fr) minmax(200px, .36fr); gap: clamp(12px, .7rem + .3cqi, 18px); padding: clamp(18px, 1rem + .45cqi, 24px) clamp(18px, 1rem + .55cqi, 28px); border-bottom: 1px solid var(--line); background: #f8fbfa; }
.tasks-filters label { display: grid; gap: 8px; min-width: 0; }
.tasks-filters label > span:first-child { color: var(--muted); font-size: var(--task-meta); font-weight: 800; }
.tasks-input, .tasks-select { position: relative; display: flex; align-items: center; min-width: 0; }
.tasks-input > svg { position: absolute; left: 14px; z-index: 1; color: #80908f; pointer-events: none; }
.tasks-select > svg { position: absolute; right: 14px; z-index: 1; color: #6b7c7a; pointer-events: none; }
.tasks-filters input, .tasks-filters select { width: 100%; min-height: var(--task-control-height); border: 1px solid #ccd9d7; border-radius: var(--task-radius-control); color: var(--slate); background: #fff; font: 650 var(--task-detail)/1.3 inherit; outline: none; transition: border-color 150ms ease, box-shadow 150ms ease, background 150ms ease; }
.tasks-filters input { padding: 0 15px 0 42px; }
.tasks-filters select { appearance: none; padding: 0 42px 0 15px; cursor: pointer; }
.tasks-filters input:hover, .tasks-filters select:hover { border-color: #9fbfba; }
.tasks-filters input:focus, .tasks-filters select:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(15, 159, 143, .12); }
.tasks-table { overflow-x: auto; }
.tasks-table__head, .tasks-row { display: grid; grid-template-columns: minmax(280px, 1.35fr) minmax(230px, 1fr) minmax(140px, .55fr) minmax(160px, .65fr) minmax(150px, auto); align-items: center; gap: clamp(18px, 1.15cqi, 28px); min-width: 1020px; }
.tasks-table__head { min-height: 48px; padding: 0 clamp(18px, 1rem + .55cqi, 28px); color: var(--muted); background: #f7faf9; font-size: var(--task-meta); font-weight: 800; letter-spacing: .035em; }
.tasks-row { min-height: clamp(82px, 4.25rem + 1.2cqi, 102px); padding: 15px clamp(18px, 1rem + .55cqi, 28px); border-top: 1px solid #e7efed; transition: background 150ms ease; }
.tasks-row:hover { background: #fbfefd; }
.tasks-row > div { display: grid; gap: 5px; min-width: 0; color: var(--slate); font-size: var(--task-detail); }
.tasks-row strong { overflow: hidden; color: var(--ink); font-size: var(--task-body); text-overflow: ellipsis; white-space: nowrap; }
.tasks-row small, .tasks-row time { color: var(--muted); font-size: var(--task-meta); }
.tasks-status { display: inline-flex; align-items: center; gap: 7px; width: fit-content; min-height: 32px; padding: 0 11px; border-radius: 999px; color: var(--slate); background: #f1f5f4; font-size: var(--task-meta); font-weight: 800; }
.tasks-status i { width: 7px; height: 7px; border-radius: 50%; background: #94a3b8; }
.tasks-status.is-running, .tasks-status.is-starting, .tasks-status.is-completed { color: var(--brand-dark); background: var(--brand-soft); }
.tasks-status.is-running i, .tasks-status.is-starting i, .tasks-status.is-completed i { background: var(--brand); }
.tasks-status.is-waiting_human, .tasks-status.is-paused, .tasks-status.is-pausing, .tasks-status.is-stopping { color: #9a5b08; background: #fff7e3; }
.tasks-status.is-waiting_human i, .tasks-status.is-paused i, .tasks-status.is-pausing i, .tasks-status.is-stopping i { background: var(--warning); }
.tasks-status.is-failed, .tasks-status.is-archived { color: #b42332; background: #fff0f2; }
.tasks-status.is-failed i, .tasks-status.is-archived i { background: var(--danger); }
.tasks-row__link { display: inline-flex; align-items: center; justify-content: center; justify-self: end; gap: 6px; min-height: 40px; padding: 0 13px; border: 1px solid #b8d8d4; border-radius: 10px; color: var(--brand-dark); background: #fff; font-size: var(--task-meta); font-weight: 800; text-decoration: none; }
.tasks-row__link:hover { border-color: var(--brand); background: var(--brand-soft); }
.tasks-state { display: flex; align-items: center; justify-content: center; gap: 14px; min-height: clamp(230px, 16cqi, 320px); padding: 34px; color: var(--muted); text-align: left; }
.tasks-state > div { display: grid; gap: 4px; }
.tasks-state strong { color: var(--slate); font-size: var(--task-body); }
.tasks-state p { margin: 0; font-size: var(--task-detail); }
.tasks-state a, .tasks-state button, .tasks-sync-warning button { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 0 14px; border: 1px solid #b8ded8; border-radius: 10px; color: var(--brand-dark); background: #fff; font-size: var(--task-meta); font-weight: 800; text-decoration: none; cursor: pointer; }
.tasks-state--loading { display: grid; grid-template-columns: repeat(3, minmax(80px, 180px)); }
.tasks-state--loading span { height: 52px; border-radius: 10px; background: linear-gradient(90deg, #f1f5f4, #fafcfb, #f1f5f4); }
.tasks-state--loading p { grid-column: 1 / -1; text-align: center; }
.tasks-state.is-error { color: #b42332; }
.tasks-sync-warning { margin: 0; padding: 11px 18px; color: #9a5b08; background: #fff9ea; font-size: var(--task-meta); }
.recruitment-tasks a:focus-visible, .recruitment-tasks button:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
@container (max-width: 1080px) {
  .tasks-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tasks-summary article { border-top: 1px solid var(--line); }
  .tasks-summary article:nth-child(-n + 2) { border-top: 0; }
  .tasks-summary article:nth-child(odd) { border-left: 0; }
  .tasks-filters { grid-template-columns: minmax(280px, 1fr) minmax(170px, .45fr) minmax(180px, .5fr); }
  .tasks-table__head { display: none; }
  .tasks-table { overflow: visible; }
  .tasks-row { grid-template-columns: minmax(0, 1fr) auto; gap: 11px 22px; min-width: 0; }
  .tasks-row > :nth-child(2), .tasks-row > time { grid-column: 1; }
  .tasks-status, .tasks-row__link { grid-column: 2; justify-self: end; }
}
@container (max-width: 760px) {
  .tasks-hero { align-items: stretch; flex-direction: column; }
  .tasks-primary-button { align-self: stretch; }
  .tasks-filters { grid-template-columns: 1fr; }
  .tasks-panel__header { align-items: flex-start; flex-direction: column; }
  .tasks-panel__header > small { display: none; }
  .tasks-visibility { width: 100%; }
  .tasks-visibility button { flex: 1; min-height: 42px; }
  .tasks-row { grid-template-columns: 1fr; }
  .tasks-row > :nth-child(n) { grid-column: 1; justify-self: start; }
  .tasks-row__link { width: 100%; min-height: 44px; }
  .tasks-state { align-items: center; flex-direction: column; text-align: center; }
}
@container (max-width: 480px) {
  .tasks-summary article { min-height: 76px; padding: 13px; }
  .tasks-summary span { font-size: 12px; }
  .tasks-summary strong { font-size: 26px; }
}
</style>
