<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import CircularTaskProgress from '@/components/CircularTaskProgress.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'

const props = defineProps({
  task: { type: Object, required: true },
})

defineEmits(['close'])

const completedNodeStates = new Set(['succeeded', 'failed', 'skipped', 'cancelled'])

function rawState(task) {
  const value = String(task?.automation_plan_effective_state || task?.status || '')
  return { queued: 'starting', pending: 'starting', succeeded: 'completed', cancelled: 'stopped' }[value] || value || 'stopped'
}

function stateLabel(task) {
  return {
    starting: '正在开启', running: '运行中', waiting_human: '等待人工', paused: '已暂停', pausing: '正在暂停',
    stopping: '正在停止', stopped: '已停止', failed: '运行失败', completed: '本轮完成', archived: '已删除',
  }[rawState(task)] || '状态同步中'
}

function formatRunId(task) {
  return task?.id ? `运行 #${String(task.id).slice(0, 8)}` : '暂无运行编号'
}

function formatDateTime(value) {
  const parsed = new Date(value)
  if (!value || Number.isNaN(parsed.getTime())) return '等待记录'
  return parsed.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).replaceAll('/', '-')
}

function formatTime(value) {
  const parsed = new Date(value)
  if (!value || Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function nestedNumber(source, keys) {
  if (!source || typeof source !== 'object') return null
  for (const key of keys) {
    const value = Number(source[key])
    if (Number.isFinite(value) && value >= 0) return value
  }
  for (const value of Object.values(source)) {
    if (value && typeof value === 'object') {
      const found = nestedNumber(value, keys)
      if (found !== null) return found
    }
  }
  return null
}

const nodes = computed(() => Array.isArray(props.task?.node_runs) ? props.task.node_runs : [])
const countSources = computed(() => [
  props.task?.result,
  ...nodes.value.map((node) => node?.output),
].filter(Boolean).reverse())

function metric(keys) {
  for (const source of countSources.value) {
    const value = nestedNumber(source, keys)
    if (value !== null) return value
  }
  return null
}

const progress = computed(() => {
  if (rawState(props.task) === 'completed') return 100
  if (!nodes.value.length) return 0
  const completed = nodes.value.filter((node) => completedNodeStates.has(node.status)).length
  const active = nodes.value.some((node) => ['running', 'waiting_human'].includes(node.status)) ? 0.72 : 0
  return Math.min(99, Math.round(((completed + active) / nodes.value.length) * 100))
})

const metrics = computed(() => [
  { label: '已检索', value: metric(['searched_count', 'discovered_count', 'candidate_count', 'scanned_count']), icon: 'search' },
  { label: '已分析', value: metric(['analyzed_count', 'scanned_count', 'pulled_resume_count']), icon: 'document' },
  { label: '符合要求', value: metric(['qualified_resume_count', 'matched_count', 'qualified_count']), icon: 'user-check' },
])

const activeNode = computed(() => nodes.value.find((node) => ['running', 'waiting_human'].includes(node.status)))

function stepName(node) {
  const key = `${node?.node_type || ''} ${node?.node_key || ''}`.toLowerCase()
  if (key.includes('search') || key.includes('pull') || key.includes('resume')) return '简历拉取与分析'
  if (key.includes('archive') || key.includes('result')) return '结果归档'
  if (key.includes('init') || key.includes('prepare') || key.includes('start')) return '方案初始化'
  if (key.includes('human') || key.includes('review') || key.includes('approval')) return '等待人工确认'
  return node?.status_label || '任务执行'
}

const currentStep = computed(() => {
  if (rawState(props.task) === 'completed') return '结果归档'
  if (activeNode.value) return stepName(activeNode.value)
  if (rawState(props.task) === 'starting') return '方案初始化'
  return stateLabel(props.task)
})

const currentDescription = computed(() => {
  if (activeNode.value?.node_type?.includes('search') || activeNode.value?.node_key?.includes('search')) {
    return '正在从多渠道拉取候选人简历，并进行结构化解析与匹配分析。'
  }
  if (rawState(props.task) === 'completed') return '本轮任务已经完成，执行结果与审计记录均已归档。'
  if (rawState(props.task) === 'waiting_human') return '自动执行已安全暂停，正在等待 HR 完成人工处理。'
  return '系统正在按冻结的招聘方案执行任务，并持续同步最新运行状态。'
})

const nextStep = computed(() => {
  if (progress.value < 25) return { title: '候选人检索', description: '准备完成后将开始检索并筛选候选人。' }
  if (progress.value < 50) return { title: '简历拉取与分析', description: '检索完成后将拉取简历并进行结构化分析。' }
  if (progress.value < 100) return { title: '结果归档', description: '分析完成后将自动归档结果，供后续查看与复盘。' }
  return { title: '本轮已完成', description: '所有执行结果均已归档，可进入运行记录查看详情。' }
})

const needsHuman = computed(() => rawState(props.task) === 'waiting_human')

const phases = computed(() => {
  const items = [
    { label: '准备完成', threshold: 0 },
    { label: '检索完成', threshold: 25 },
    { label: '分析进行中', threshold: 50 },
    { label: '归档待执行', threshold: 75 },
  ]
  const completedTimes = nodes.value.filter((node) => completedNodeStates.has(node.status)).map((node) => node.completed_at || node.updated_at)
  return items.map((item, index) => {
    const done = progress.value >= (index + 1) * 25 || progress.value === 100
    const current = !done && progress.value >= item.threshold
    let detail = done ? (formatTime(completedTimes[index]) || '已完成') : current ? '进行中' : '待执行'
    if (index === 0 && done) detail = formatTime(props.task?.started_at || props.task?.created_at) || detail
    return { ...item, done, current, detail }
  })
})

const detailRoute = computed(() => ({
  name: 'recruitment-task-detail',
  params: { planId: props.task.automation_plan },
  query: { run: props.task.id },
}))
</script>

<template>
  <RecruitmentDetailDrawer title="任务执行中" variant="task-execution" @close="$emit('close')">
    <div class="execution-layout" data-test="task-execution-report">
      <aside class="execution-sidebar">
        <div class="execution-job">
          <span class="execution-job__icon"><AppIcon name="search" :size="27" :stroke-width="2" /></span>
          <div><h3>{{ task.job_title || `职位 #${task.job}` }}</h3><span>{{ task.automation_plan_kind === 'passive_resume' ? '被动咨询' : '主动寻访' }}</span></div>
        </div>

        <div class="execution-state"><strong>{{ stateLabel(task) }}</strong><i></i><span>{{ formatRunId(task) }}</span></div>

        <div class="execution-progress" role="progressbar" aria-label="整体进度" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="progress">
          <CircularTaskProgress :value="progress" />
          <div><strong>{{ progress }}<small>%</small></strong><span>整体进度</span></div>
        </div>

        <dl class="execution-facts">
          <div><AppIcon name="clock" :size="22" /><dt>开始时间</dt><dd>{{ formatDateTime(task.started_at || task.created_at) }}</dd></div>
          <div><AppIcon name="user" :size="22" /><dt>执行账号</dt><dd>{{ task.account_name || '系统自动执行' }}</dd></div>
        </dl>
      </aside>

      <main class="execution-main">
        <header class="execution-current">
          <h3>当前正在执行：<strong>{{ currentStep }}</strong></h3>
          <p>{{ currentDescription }}</p>
        </header>

        <section class="execution-metrics" aria-label="执行统计">
          <div v-for="item in metrics" :key="item.label">
            <AppIcon :name="item.icon" :size="29" :stroke-width="1.8" />
            <span>{{ item.label }}<strong>{{ item.value ?? '—' }}</strong></span>
          </div>
        </section>

        <div class="execution-separator"></div>

        <section class="execution-next">
          <AppIcon name="arrow-right" :size="29" />
          <div><h4>下一步：{{ nextStep.title }}</h4><p>{{ nextStep.description }}</p></div>
        </section>

        <section :class="['execution-human', { 'needs-human': needsHuman }]">
          <AppIcon :name="needsHuman ? 'alert-circle' : 'check-circle'" :size="25" />
          <strong>{{ needsHuman ? '有事项需要 HR 处理' : '暂无需要 HR 处理的事项' }}</strong>
        </section>
      </main>
    </div>

    <template #footer>
      <ol class="execution-phases" aria-label="任务阶段">
        <li v-for="(phase, index) in phases" :key="phase.label" :class="{ 'is-done': phase.done, 'is-current': phase.current }">
          <div class="execution-phase-line" v-if="index > 0"></div>
          <span class="execution-phase-icon"><AppIcon v-if="phase.done" name="check-circle" :size="26" /><i v-else-if="phase.current"></i></span>
          <strong>{{ phase.label }}</strong>
          <small>{{ phase.detail }}</small>
        </li>
      </ol>
      <RouterLink class="execution-record-link" :to="detailRoute">查看运行记录</RouterLink>
    </template>
  </RecruitmentDetailDrawer>
</template>

<style scoped>
:deep(.recruitment-drawer-backdrop.is-task-execution) { padding: 28px; background: rgba(47, 62, 70, .42); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); }
:deep(.recruitment-drawer.is-task-execution) { width: min(886px, calc(100vw - 56px)); height: min(833px, calc(100dvh - 56px)); max-height: 833px; border: 1px solid #eef1f2; border-radius: 15px; background: #fff; box-shadow: 0 32px 70px rgba(28, 42, 54, .2); }
:deep(.recruitment-drawer.is-task-execution .recruitment-drawer__header) { min-height: 79px; padding: 0 33px; border-bottom: 1px solid #dfe5e7; }
:deep(.recruitment-drawer.is-task-execution .recruitment-drawer__header h2) { color: #17263a; font-size: 24px; font-weight: 850; letter-spacing: -.03em; }
:deep(.recruitment-drawer.is-task-execution .recruitment-drawer__header button) { width: 38px; height: 38px; color: #56667a; border-color: #dbe2e5; }
:deep(.recruitment-drawer.is-task-execution .recruitment-drawer__header button svg) { stroke-width: 1.5; }
:deep(.recruitment-drawer.is-task-execution .recruitment-drawer__body) { min-height: 0; overflow: hidden; padding: 0; }
:deep(.recruitment-drawer.is-task-execution .recruitment-drawer__footer) { display: grid; min-height: 178px; padding: 23px 36px 17px; border-top: 1px solid #dfe5e7; background: #fff; }

.execution-layout { display: grid; height: 100%; min-height: 0; grid-template-columns: 265px minmax(0, 1fr); }
.execution-sidebar { display: flex; min-width: 0; flex-direction: column; padding: 28px 32px 38px 33px; border-right: 1px solid #dfe5e7; }
.execution-job { display: grid; grid-template-columns: 48px minmax(0, 1fr); align-items: center; gap: 15px; }
.execution-job__icon { display: grid; width: 48px; height: 48px; place-items: center; color: #fff; border-radius: 14px; background: #13988d; box-shadow: inset 0 1px 0 rgba(255,255,255,.3); }
.execution-job h3 { overflow: hidden; margin: 0 0 7px; color: #17263a; font-size: 19px; line-height: 1.15; text-overflow: ellipsis; white-space: nowrap; }
.execution-job div > span { display: inline-flex; min-height: 25px; align-items: center; padding: 0 10px; color: #168c83; border: 1px solid #aad6d1; border-radius: 5px; background: #f1fbfa; font-size: 13px; font-weight: 750; }
.execution-state { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 6px 8px; margin-top: 36px; color: #30435a; }
.execution-state strong { font-size: 20px; }
.execution-state i { width: 9px; height: 9px; border-radius: 50%; background: #15978c; }
.execution-state span { grid-column: 1 / -1; font-size: 16px; }
.execution-progress { position: relative; width: 180px; height: 180px; align-self: center; margin: 21px 0 25px; }
.execution-progress > div { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
.execution-progress > div strong { color: #108c82; font-size: 40px; line-height: 1; letter-spacing: -.04em; }
.execution-progress > div strong small { font-size: 23px; }
.execution-progress > div span { margin-top: 8px; color: #405168; font-size: 14px; }
.execution-facts { display: grid; gap: 27px; margin: auto 0 0; }
.execution-facts > div { display: grid; grid-template-columns: 26px minmax(0, 1fr); align-items: start; column-gap: 13px; color: #617187; }
.execution-facts svg { grid-row: 1 / span 2; }
.execution-facts dt { color: #43566c; font-size: 15px; }
.execution-facts dd { margin: 6px 0 0; color: #52647a; font-size: 14px; line-height: 1.45; }

.execution-main { display: flex; min-width: 0; flex-direction: column; padding: 39px 44px 31px 32px; }
.execution-current h3 { margin: 0; color: #17263a; font-size: 18px; font-weight: 800; }
.execution-current h3 strong { color: #128f85; }
.execution-current p { margin: 24px 0 0; color: #465970; font-size: 14px; line-height: 1.7; }
.execution-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 37px; padding: 24px 18px; border: 1px solid #dce7e7; border-radius: 15px; background: #f8fbfb; }
.execution-metrics > div { display: grid; grid-template-columns: 31px minmax(0, 1fr); align-items: start; gap: 13px; min-width: 0; padding: 0 17px; color: #118f85; }
.execution-metrics > div + div { border-left: 1px solid #dbe4e5; }
.execution-metrics span { display: grid; gap: 10px; color: #53637a; font-size: 15px; }
.execution-metrics strong { color: #0f8f85; font-size: 31px; line-height: 1; }
.execution-separator { height: 1px; margin: 37px 0 23px; background: #dfe5e7; }
.execution-next { display: grid; grid-template-columns: 34px minmax(0, 1fr); align-items: start; gap: 15px; padding: 14px 17px 17px; color: #5a6c81; border-radius: 14px; background: #f7f9f9; }
.execution-next > svg { margin-top: 1px; padding: 4px; border: 1.5px solid currentColor; border-radius: 50%; }
.execution-next h4 { margin: 0; color: #26384d; font-size: 16px; }
.execution-next p { margin: 5px 0 0; color: #53657b; font-size: 13px; line-height: 1.55; }
.execution-human { display: flex; align-items: center; gap: 18px; min-height: 94px; margin-top: 38px; padding: 0 29px; color: #138f85; border: 1px solid #cfe0df; border-radius: 13px; background: #f8fbfb; }
.execution-human strong { font-size: 17px; }
.execution-human.needs-human { color: #a16207; border-color: #efd8a8; background: #fffaf0; }

.execution-phases { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 0; padding: 0; list-style: none; }
.execution-phases li { position: relative; display: grid; place-items: center; gap: 6px; color: #647489; text-align: center; }
.execution-phase-line { position: absolute; top: 13px; right: calc(50% + 16px); left: calc(-50% + 16px); height: 2px; background: #d8dfe2; }
.execution-phase-icon { position: relative; z-index: 1; display: grid; width: 28px; height: 28px; place-items: center; color: #718096; border: 2px solid currentColor; border-radius: 50%; background: #fff; }
.execution-phase-icon > svg { width: 28px; height: 28px; margin: -2px; color: #15978c; background: #fff; }
.execution-phase-icon i { width: 10px; height: 10px; border-radius: 50%; background: #fff; }
.execution-phases strong { font-size: 13px; font-weight: 650; }
.execution-phases small { font-size: 12px; }
.execution-phases .is-done, .execution-phases .is-current { color: #168f85; }
.execution-phases .is-done .execution-phase-icon { color: #15978c; }
.execution-phases .is-current .execution-phase-icon { color: #13988d; border-width: 7px; }
.execution-record-link { align-self: end; justify-self: center; display: inline-flex; min-width: 160px; min-height: 44px; align-items: center; justify-content: center; padding: 0 27px; color: #158d84; border: 1px solid #9bcec9; border-radius: 9px; background: #fff; font-size: 15px; font-weight: 750; text-decoration: none; transition: 160ms ease; }
.execution-record-link:hover { color: #fff; border-color: #128f85; background: #128f85; }

@media (max-width: 780px) {
  :deep(.recruitment-drawer-backdrop.is-task-execution) { padding: 12px; }
  :deep(.recruitment-drawer.is-task-execution) { width: calc(100vw - 24px); height: calc(100dvh - 24px); max-height: none; }
  :deep(.recruitment-drawer.is-task-execution .recruitment-drawer__body) { overflow-y: auto; }
  :deep(.recruitment-drawer.is-task-execution .recruitment-drawer__footer) { min-height: 194px; padding: 20px 16px 14px; }
  .execution-layout { height: auto; grid-template-columns: 1fr; }
  .execution-sidebar { display: grid; grid-template-columns: 1fr auto; gap: 20px; padding: 24px 20px; border-right: 0; border-bottom: 1px solid #dfe5e7; }
  .execution-state { margin: 0; justify-self: end; }
  .execution-progress { grid-column: 1 / -1; width: 160px; height: 160px; margin: 0 auto; }
  .execution-facts { grid-column: 1 / -1; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; }
  .execution-main { padding: 28px 20px; }
  .execution-human { margin-top: 24px; }
}

@media (max-width: 520px) {
  .execution-sidebar { grid-template-columns: 1fr; }
  .execution-state { justify-self: start; margin-top: 4px; }
  .execution-facts { grid-template-columns: 1fr; }
  .execution-metrics { grid-template-columns: 1fr; padding: 9px 18px; }
  .execution-metrics > div { padding: 14px 0; }
  .execution-metrics > div + div { border-top: 1px solid #dbe4e5; border-left: 0; }
  .execution-phases strong { font-size: 11px; }
  .execution-phases small { font-size: 10px; }
}

:deep(.recruitment-drawer.is-task-execution) {
  --execution-font-min: .9167rem;
  font-size: var(--execution-font-min);
  font-weight: 400;
}

:deep(.recruitment-drawer.is-task-execution) :is(p, span, small, button, a, dt, dd, li) {
  font-weight: 400 !important;
}

:deep(.recruitment-drawer.is-task-execution) :is(h2, h3, h4, strong, b) {
  font-weight: 400 !important;
}

.execution-phases strong,
.execution-phases small,
.execution-job div > span,
.execution-progress > div > span,
.execution-facts dd,
.execution-current p,
.execution-next p,
.execution-human strong {
  font-size: var(--execution-font-min) !important;
}
</style>
