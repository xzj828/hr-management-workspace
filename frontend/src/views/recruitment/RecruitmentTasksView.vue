<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
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

async function loadPlans({ silent = false } = {}) {
  if (silent && pollInFlight) return
  const sequence = ++loadSequence
  if (!silent) loading.value = true
  if (silent) pollInFlight = true
  try {
    const payload = await api('recruitment/automation-plans/')
    if (!componentAlive || sequence !== loadSequence) return
    plans.value = listItems(payload)
    loadError.value = ''
  } catch (error) {
    if (sequence === loadSequence) loadError.value = error.message || '招聘任务读取失败'
  } finally {
    if (silent) pollInFlight = false
    if (!silent && sequence === loadSequence) loading.value = false
  }
}

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

    <section class="tasks-panel">
      <div class="tasks-filters">
        <label class="tasks-search"><span>搜索任务</span><span class="tasks-input"><AppIcon name="search" :size="17" /><input v-model="search" type="search" placeholder="岗位、方案或运行编号" data-test="task-search" /></span></label>
        <label><span>运行状态</span><span class="tasks-select"><select v-model="stateFilter" data-test="task-state-filter"><option value="all">全部状态</option><option value="active">进行中</option><option value="waiting">等待人工</option><option value="paused">已暂停</option><option value="ended">已结束</option></select><AppIcon name="chevron-down" :size="16" /></span></label>
        <label><span>任务类型</span><span class="tasks-select"><select v-model="kindFilter" data-test="task-kind-filter"><option value="all">全部类型</option><option value="passive_resume">被动咨询</option><option value="active_resume_search">主动寻访</option></select><AppIcon name="chevron-down" :size="16" /></span></label>
      </div>

      <div v-if="loading" class="tasks-state tasks-state--loading" data-test="tasks-loading" aria-live="polite"><span></span><span></span><span></span><p>正在同步招聘任务…</p></div>
      <div v-else-if="loadError && !plans.length" class="tasks-state is-error" data-test="tasks-error" role="alert"><AppIcon name="alert-circle" :size="24" /><div><strong>招聘任务暂时无法加载</strong><p>{{ loadError }}</p></div><button type="button" @click="loadPlans()">重新加载</button></div>

      <template v-else>
        <p v-if="loadError" class="tasks-sync-warning" role="status">同步失败，当前展示上次成功结果。<button type="button" @click="loadPlans()">重试</button></p>
        <div v-if="filteredPlans.length" class="tasks-card-grid" role="list" aria-label="招聘任务列表">
          <article v-for="plan in filteredPlans" :key="plan.id" :class="['tasks-card', `is-${plan.kind}`]" role="listitem" :data-test="`task-row-${plan.id}`">
            <div class="tasks-card__cover">
              <span class="tasks-card__cover-icon"><AppIcon :name="plan.kind === 'passive_resume' ? 'headset' : 'search'" :size="30" /></span>
              <div><small>招聘方案</small><strong>{{ plan.kind === 'passive_resume' ? '被动咨询' : '主动寻访' }}</strong></div>
              <span :class="['tasks-status', `is-${planState(plan)}`]"><i></i>{{ stateLabel(plan) }}</span>
            </div>
            <div class="tasks-card__body">
              <div class="tasks-card__title"><span>招聘岗位</span><h3>{{ plan.job_title || `职位 #${plan.job}` }}</h3></div>
              <p>{{ kindLabel(plan) }}</p>
              <dl>
                <div><dt>方案版本</dt><dd>{{ revisionLabel(plan) }}</dd></div>
                <div><dt>运行编号</dt><dd>{{ runLabel(plan) }}</dd></div>
              </dl>
            </div>
            <footer class="tasks-card__footer">
              <time><AppIcon name="clock" :size="14" />更新于 {{ formatDateTime(plan.updated_at) }}</time>
              <RouterLink class="tasks-card__link" :to="taskTo(plan)" :data-test="`open-task-${plan.id}`">查看与维护<AppIcon name="chevron-right" :size="13" /></RouterLink>
            </footer>
          </article>
        </div>
        <div v-else class="tasks-state" data-test="tasks-empty">
          <AppIcon name="briefcase" :size="25" />
          <div><strong>{{ plans.length ? '没有符合筛选条件的任务' : '还没有招聘任务' }}</strong><p v-if="plans.length">换个搜索词或筛选条件试试</p></div>
          <RouterLink v-if="!plans.length" :to="{ name: 'recruitment-workbench', query: { new: '1' } }">创建任务</RouterLink>
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
.tasks-panel { overflow: hidden; border: 1px solid var(--line); border-radius: var(--task-radius-panel); background: #fff; box-shadow: 0 4px 18px rgba(15, 23, 42, .035); }
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
.tasks-card-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: clamp(18px, 1.2rem + .45cqi, 28px); padding: clamp(20px, 1.2rem + .55cqi, 30px); background: #f4f8f7; }
.tasks-card { position: relative; display: grid; grid-template-rows: auto 1fr auto; min-width: 0; overflow: hidden; border: 1px solid #dce8e6; border-radius: clamp(16px, .8rem + .35cqi, 21px); background: #fff; box-shadow: 0 10px 28px rgba(15, 23, 42, .075); transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease; }
.tasks-card:hover { border-color: #b6d7d2; box-shadow: 0 18px 38px rgba(15, 23, 42, .11); transform: translateY(-3px); }
.tasks-card__cover { position: relative; display: flex; align-items: center; gap: 13px; min-height: clamp(112px, 7rem + 1.7cqi, 148px); overflow: hidden; padding: clamp(18px, 1rem + .5cqi, 26px); color: #fff; background: linear-gradient(135deg, #0b766e 0%, #12a594 56%, #4bc4ad 100%); }
.tasks-card__cover::before, .tasks-card__cover::after { position: absolute; content: ''; border-radius: 50%; background: rgba(255, 255, 255, .12); }
.tasks-card__cover::before { width: 170px; height: 170px; right: -58px; bottom: -105px; }
.tasks-card__cover::after { width: 96px; height: 96px; right: 66px; top: -60px; }
.tasks-card.is-passive_resume .tasks-card__cover { background: linear-gradient(135deg, #3056a2 0%, #5967c7 56%, #6d9dde 100%); }
.tasks-card__cover-icon { position: relative; z-index: 1; display: grid; flex: none; width: 54px; height: 54px; place-content: center; border: 1px solid rgba(255, 255, 255, .28); border-radius: 16px; background: rgba(255, 255, 255, .15); box-shadow: inset 0 1px 0 rgba(255, 255, 255, .2); }
.tasks-card__cover > div { position: relative; z-index: 1; display: grid; gap: 3px; min-width: 0; }
.tasks-card__cover small { color: rgba(255, 255, 255, .76); font-size: var(--task-meta); font-weight: 700; letter-spacing: .08em; }
.tasks-card__cover strong { font-size: clamp(18px, .8rem + .65cqi, 24px); line-height: 1.2; }
.tasks-status { position: relative; z-index: 1; display: inline-flex; align-items: center; gap: 7px; width: fit-content; min-height: 32px; padding: 0 11px; border-radius: 999px; color: var(--slate); background: rgba(255, 255, 255, .93); box-shadow: 0 3px 10px rgba(15, 23, 42, .12); font-size: var(--task-meta); font-weight: 800; }
.tasks-card__cover > .tasks-status { margin-left: auto; align-self: flex-start; }
.tasks-status i { width: 7px; height: 7px; border-radius: 50%; background: #94a3b8; }
.tasks-status.is-running, .tasks-status.is-starting, .tasks-status.is-completed { color: var(--brand-dark); background: var(--brand-soft); }
.tasks-status.is-running i, .tasks-status.is-starting i, .tasks-status.is-completed i { background: var(--brand); }
.tasks-status.is-waiting_human, .tasks-status.is-paused, .tasks-status.is-pausing, .tasks-status.is-stopping { color: #9a5b08; background: #fff7e3; }
.tasks-status.is-waiting_human i, .tasks-status.is-paused i, .tasks-status.is-pausing i, .tasks-status.is-stopping i { background: var(--warning); }
.tasks-status.is-failed, .tasks-status.is-archived { color: #b42332; background: #fff0f2; }
.tasks-status.is-failed i, .tasks-status.is-archived i { background: var(--danger); }
.tasks-card__body { display: grid; align-content: start; gap: 13px; padding: clamp(20px, 1.1rem + .45cqi, 27px); }
.tasks-card__title { display: grid; gap: 4px; }
.tasks-card__title > span { color: var(--muted); font-size: var(--task-meta); font-weight: 750; }
.tasks-card__title h3 { overflow: hidden; margin: 0; color: var(--ink); font-size: clamp(18px, .85rem + .55cqi, 23px); line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.tasks-card__body > p { margin: 0; color: var(--slate); font-size: var(--task-detail); line-height: 1.6; }
.tasks-card dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 0; }
.tasks-card dl > div { display: grid; gap: 4px; min-width: 0; padding: 11px 12px; border-radius: 11px; background: #f5f9f8; }
.tasks-card dt { color: var(--muted); font-size: var(--task-meta); }
.tasks-card dd { overflow: hidden; margin: 0; color: var(--slate); font-size: var(--task-detail); font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.tasks-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px clamp(20px, 1.1rem + .45cqi, 27px); border-top: 1px solid #e6eeec; }
.tasks-card__footer time { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: var(--muted); font-size: var(--task-meta); }
.tasks-card__link { display: inline-flex; flex: none; align-items: center; justify-content: center; gap: 6px; min-height: 40px; padding: 0 13px; border: 1px solid #b8d8d4; border-radius: 10px; color: var(--brand-dark); background: #fff; font-size: var(--task-meta); font-weight: 800; text-decoration: none; }
.tasks-card__link:hover { border-color: var(--brand); background: var(--brand-soft); }
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
  .tasks-filters { grid-template-columns: minmax(280px, 1fr) minmax(170px, .45fr) minmax(180px, .5fr); }
  .tasks-card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (max-width: 760px) {
  .tasks-hero { align-items: stretch; flex-direction: column; }
  .tasks-primary-button { align-self: stretch; }
  .tasks-filters { grid-template-columns: 1fr; }
  .tasks-card-grid { grid-template-columns: minmax(0, 1fr); padding: 16px; }
  .tasks-card__link { min-height: 44px; }
  .tasks-state { align-items: center; flex-direction: column; text-align: center; }
}
@container (max-width: 480px) {
  .tasks-card__cover { align-items: flex-start; min-height: 124px; }
  .tasks-card__cover > .tasks-status { position: absolute; right: 16px; bottom: 14px; }
  .tasks-card dl { grid-template-columns: minmax(0, 1fr); }
  .tasks-card__footer { align-items: stretch; flex-direction: column; }
  .tasks-card__link { width: 100%; }
}
</style>
