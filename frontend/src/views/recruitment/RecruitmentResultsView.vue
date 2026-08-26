<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import WorkflowRunPanel from '@/components/WorkflowRunPanel.vue'
import { stageColumns } from '@/recruitment'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const context = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()
const currentJob = computed(() => context.currentJob)

function normalizeView(value) {
  return {
    overview: 'attention', attention: 'attention', tasks: 'tasks', runs: 'tasks',
    candidates: 'candidates', resumes: 'candidates', pipeline: 'pipeline',
  }[String(value || '')] || 'attention'
}

function viewFromQuery(query) {
  if (query.view) return normalizeView(query.view)
  if (query.run) return 'tasks'
  if (query.application || query.candidate || query.filter) return 'candidates'
  return 'attention'
}

const activeView = ref(viewFromQuery(route.query))
const selectedRunId = ref(String(route.query.run || ''))
const statusFilter = ref(String(route.query.status || 'all'))
const expandedRunId = ref('')
const runPanelId = ref(String(route.query.run || ''))
const runActionBusy = ref(false)
const runActionError = ref('')
const attentionActionId = ref('')
const attentionActionError = ref('')
let requestSequence = 0
let runContextSequence = 0

const resources = reactive({
  runs: { items: [], loading: false, loaded: false, error: '' },
  campaigns: { items: [], loading: false, loaded: false, error: '' },
  attentions: { items: [], loading: false, loaded: false, error: '' },
  applications: { items: [], loading: false, loaded: false, error: '' },
  resumes: { items: [], loading: false, loaded: false, error: '' },
  structures: { items: [], loading: false, loaded: false, error: '' },
  assessments: { items: [], loading: false, loaded: false, error: '' },
})

const resourceDefinitions = [
  ['runs', '任务运行', () => 'recruitment/workflow-runs/'],
  ['campaigns', '主动寻访', () => 'recruitment/search-campaigns/'],
  ['attentions', '人工事项', () => 'recruitment/human-attentions/'],
  ['applications', '候选人', (jobId) => `recruitment/applications/?job=${jobId}`],
  ['resumes', '简历', (jobId) => `recruitment/resumes/?job=${jobId}`],
  ['structures', '简历结构化', (jobId) => `recruitment/structured-resumes/?job=${jobId}`],
  ['assessments', '简历评分', (jobId) => `recruitment/resume-assessments/?job=${jobId}`],
]

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'needs_action', label: '需要处理' },
  { value: 'in_progress', label: '执行中' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败 / 已取消' },
]
const visibleStatusOptions = computed(() => statusOptions.some((option) => option.value === statusFilter.value)
  ? statusOptions
  : [...statusOptions, { value: statusFilter.value, label: statusLabels?.[statusFilter.value] || statusFilter.value }])

const statusLabels = {
  queued: '已排队', running: '运行中', waiting_human: '等待人工', paused: '已暂停',
  succeeded: '已完成', failed: '失败', cancelled: '已取消', draft: '草稿',
  open: '待处理', resolved: '已处理', archived: '已归档',
}

const currentJobId = computed(() => currentJob.value ? String(currentJob.value.id) : '')
const jobRuns = computed(() => resources.runs.items.filter((item) => {
  if (String(item.job || '') !== currentJobId.value) return false
  const account = String(route.query.account || '')
  return !account || String(item.boss_account || item.account || '') === account
}))
const runById = computed(() => new Map(jobRuns.value.map((item) => [String(item.id), item])))
const jobCampaigns = computed(() => resources.campaigns.items.filter((item) => {
  if (String(item.job || '') !== currentJobId.value) return false
  const account = String(route.query.account || '')
  return !account || String(item.boss_account || item.account || '') === account
}))
const jobAttentions = computed(() => resources.attentions.items.filter((item) => {
  const account = String(route.query.account || '')
  if (account && String(item.boss_account || item.account || '') !== account) return false
  if (String(item.job || '') === currentJobId.value) return true
  const linkedRun = runById.value.get(String(item.workflow_run || ''))
  return linkedRun && String(linkedRun.job || '') === currentJobId.value
}))

function matchesStatus(status, group) {
  if (group === 'all') return true
  if (group === 'needs_action') return ['waiting_human', 'paused'].includes(status)
  if (group === 'in_progress') return ['queued', 'running'].includes(status)
  if (group === 'succeeded') return status === 'succeeded'
  if (group === 'failed') return ['failed', 'cancelled'].includes(status)
  return status === group
}

const filteredRuns = computed(() => jobRuns.value.filter((item) => {
  if (selectedRunId.value && String(item.id) !== selectedRunId.value) return false
  return matchesStatus(item.status, statusFilter.value)
}))

const filteredCampaigns = computed(() => jobCampaigns.value.filter((item) => {
  if (selectedRunId.value && String(item.workflow_run || '') !== selectedRunId.value) return false
  return matchesStatus(item.status, statusFilter.value)
}))

const filteredAttentions = computed(() => jobAttentions.value.filter((item) => {
  if (selectedRunId.value && String(item.workflow_run || '') !== selectedRunId.value) return false
  if (statusFilter.value === 'all') return true
  if (statusFilter.value === 'needs_action') return item.status === 'open'
  if (statusFilter.value === 'succeeded') return item.status === 'resolved'
  return false
}))

const assessmentByResume = computed(() => {
  const result = new Map()
  for (const assessment of resources.assessments.items) {
    const key = String(assessment.resume)
    const current = result.get(key)
    if (!current || Number(assessment.version || 0) > Number(current.version || 0)) result.set(key, assessment)
  }
  return result
})

const structuredResumeIds = computed(() => new Set(resources.structures.items.map((item) => String(item.resume))))
const resumesByApplication = computed(() => {
  const result = new Map()
  for (const resume of resources.resumes.items) {
    const key = String(resume.application || '')
    if (!result.has(key)) result.set(key, [])
    result.get(key).push(resume)
  }
  return result
})

const allCandidateResults = computed(() => resources.applications.items.map((application) => {
  const resumes = resumesByApplication.value.get(String(application.id)) || []
  const scored = resumes
    .map((resume) => ({ resume, assessment: assessmentByResume.value.get(String(resume.id)) }))
    .filter((item) => item.assessment)
    .sort((a, b) => Number(b.assessment.total_score || 0) - Number(a.assessment.total_score || 0))
  return { application, resumes, bestAssessment: scored[0]?.assessment || null }
}))

function resumeMatchesLegacyFilter(resume, filter) {
  const assessment = assessmentByResume.value.get(String(resume.id))
  if (filter === 'pending_parse') return !structuredResumeIds.value.has(String(resume.id))
  if (filter === 'pending_hr_review') return assessment?.recommendation === 'review'
  if (filter === 'recommended_advance') return assessment?.recommendation === 'advance'
  return true
}

const legacyContext = computed(() => ({
  account: String(route.query.account || ''),
  application: String(route.query.application || ''),
  candidate: String(route.query.candidate || ''),
  filter: String(route.query.filter || ''),
}))

const hasLegacyContext = computed(() => Object.values(legacyContext.value).some(Boolean))
const candidateResults = computed(() => allCandidateResults.value.flatMap((row) => {
  const focus = legacyContext.value
  if (focus.application && String(row.application.id) !== focus.application) return []
  if (focus.candidate && String(row.application.candidate?.id || '') !== focus.candidate) return []
  if (!focus.filter || focus.filter === 'pending_standard_review') return [row]
  const matchingResumes = row.resumes.filter((resume) => resumeMatchesLegacyFilter(resume, focus.filter))
  if (!matchingResumes.length) return []
  const matchingAssessments = matchingResumes
    .map((resume) => assessmentByResume.value.get(String(resume.id)))
    .filter(Boolean)
    .sort((a, b) => Number(b.total_score || 0) - Number(a.total_score || 0))
  return [{ ...row, resumes: matchingResumes, bestAssessment: matchingAssessments[0] || null }]
}))

const activeRun = computed(() => jobRuns.value.find((run) => String(run.id) === runPanelId.value) || null)

const stageProgress = computed(() => stageColumns.map((stage) => ({
  ...stage,
  count: resources.applications.items.filter((application) => application.stage === stage.key).length,
})))
const maxStageCount = computed(() => Math.max(1, ...stageProgress.value.map((stage) => stage.count)))
const openAttentionCount = computed(() => jobAttentions.value.filter((item) => item.status === 'open').length)
const activeRunCount = computed(() => jobRuns.value.filter((item) => ['queued', 'running', 'waiting_human', 'paused'].includes(item.status)).length)
const pulledResumeCount = computed(() => jobCampaigns.value.reduce((total, item) => total + Number(item.pulled_resume_count || 0), 0))
const isRefreshing = computed(() => Object.values(resources).some((resource) => resource.loading))
const hasLoadedResource = computed(() => Object.values(resources).some((resource) => resource.loaded))
const hasAnyData = computed(() => Object.values(resources).some((resource) => resource.items.length))
const initialLoading = computed(() => !hasLoadedResource.value && isRefreshing.value)
const resourceErrors = computed(() => resourceDefinitions
  .filter(([key]) => resources[key].error)
  .map(([key, label]) => ({ key, label, message: resources[key].error })))
const allFailed = computed(() => !hasAnyData.value && Object.values(resources).every((resource) => resource.loaded && resource.error))

const tabs = computed(() => [
  { key: 'attention', label: '需要人工', count: openAttentionCount.value },
  { key: 'tasks', label: '任务结果', count: jobRuns.value.length + jobCampaigns.value.length },
  { key: 'candidates', label: '候选人与简历', count: resources.applications.items.length },
  { key: 'pipeline', label: '招聘进度', count: resources.applications.items.length },
])

function resetResources() {
  for (const resource of Object.values(resources)) {
    resource.items = []
    resource.loading = false
    resource.loaded = false
    resource.error = ''
  }
}

async function loadResults({ reset = false } = {}) {
  const jobId = currentJobId.value
  if (!jobId) return
  const sequence = ++requestSequence
  if (reset) resetResources()

  await Promise.all(resourceDefinitions.map(async ([key, , makePath]) => {
    const resource = resources[key]
    resource.loading = true
    resource.error = ''
    try {
      const items = listItems(await api(makePath(jobId)))
      if (sequence !== requestSequence || currentJobId.value !== jobId) return
      resource.items = items
    } catch (error) {
      if (sequence !== requestSequence || currentJobId.value !== jobId) return
      resource.error = error.message || '数据加载失败'
    } finally {
      if (sequence === requestSequence && currentJobId.value === jobId) {
        resource.loading = false
        resource.loaded = true
      }
    }
  }))

  if (sequence === requestSequence && !resources.runs.error && selectedRunId.value
    && !jobRuns.value.some((run) => String(run.id) === selectedRunId.value)) {
    try {
      const linkedRun = await api(`recruitment/workflow-runs/${encodeURIComponent(selectedRunId.value)}/`)
      if (sequence === requestSequence && String(linkedRun.job || '') === jobId) resources.runs.items.push(linkedRun)
      else if (sequence === requestSequence) selectedRunId.value = ''
    } catch {
      if (sequence === requestSequence) selectedRunId.value = ''
    }
  }
}

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

function statusLabel(status) {
  return statusLabels[status] || status || '未知'
}

function statusTone(status) {
  if (['succeeded', 'resolved'].includes(status)) return 'success'
  if (['failed', 'cancelled'].includes(status)) return 'danger'
  if (['waiting_human', 'paused', 'open'].includes(status)) return 'warning'
  if (['running', 'queued'].includes(status)) return 'active'
  return 'neutral'
}

function runProgress(run) {
  const nodes = run.node_runs || []
  if (!nodes.length) return 0
  const completed = nodes.filter((node) => ['succeeded', 'skipped', 'failed', 'cancelled'].includes(node.status)).length
  return Math.round(completed / nodes.length * 100)
}

function campaignProgress(campaign) {
  const target = Math.max(1, Number(campaign.target_resume_count || 0))
  return Math.min(100, Math.round(Number(campaign.pulled_resume_count || 0) / target * 100))
}

function detailText(detail) {
  if (typeof detail === 'string') return detail
  if (!detail || typeof detail !== 'object') return '请由 HR 查看并处理'
  for (const key of ['message', 'reason', 'question', 'summary', 'last_message']) {
    if (typeof detail[key] === 'string' && detail[key].trim()) return detail[key]
  }
  return '系统已保留上下文，请进入候选人页面处理'
}

function scoreText(assessment) {
  if (!assessment) return '尚未评分'
  return `${Number(assessment.total_score || 0).toFixed(0)} 分 · ${assessment.recommendation_label || assessment.recommendation || '待复核'}`
}

function toggleRunDetail(runId) {
  const normalized = String(runId)
  expandedRunId.value = expandedRunId.value === normalized ? '' : normalized
}

function openRunPanel(run) {
  runActionError.value = ''
  runPanelId.value = String(run.id)
  selectedRunId.value = String(run.id)
}

function closeRunPanel() {
  runPanelId.value = ''
  selectedRunId.value = ''
}

function replaceRun(updated) {
  const index = resources.runs.items.findIndex((run) => String(run.id) === String(updated.id))
  if (index >= 0) resources.runs.items.splice(index, 1, updated)
}

async function runControl(action, payload = {}) {
  if (!activeRun.value || runActionBusy.value) return
  runActionBusy.value = true
  runActionError.value = ''
  try {
    const updated = await api(`recruitment/workflow-runs/${activeRun.value.id}/${action}/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    replaceRun(updated)
  } catch (error) {
    runActionError.value = error.message || '运行操作失败'
  } finally {
    runActionBusy.value = false
  }
}

function decideRunNode({ nodeId, approved }) {
  return runControl('decision', {
    node_id: nodeId,
    approved,
    note: approved ? 'HR 在结果中心确认通过' : 'HR 在结果中心选择跳过',
  })
}

function retryRunNode(nodeId) {
  return runControl('retry', { node_id: nodeId })
}

async function resolveAttention(item) {
  if (attentionActionId.value) return
  attentionActionId.value = String(item.id)
  attentionActionError.value = ''
  try {
    const updated = await api(`recruitment/human-attentions/${item.id}/resolve/`, {
      method: 'POST',
      body: JSON.stringify({ note: 'HR 已在结果中心处理' }),
    })
    const index = resources.attentions.items.findIndex((entry) => String(entry.id) === String(item.id))
    if (index >= 0) resources.attentions.items.splice(index, 1, { ...item, ...updated, status: updated.status || 'resolved' })
  } catch (error) {
    attentionActionError.value = error.message || '人工事项处理失败'
  } finally {
    attentionActionId.value = ''
  }
}

function legacyFilterLabel(filter) {
  return {
    pending_parse: '待解析简历',
    pending_standard_review: '待确认标准',
    pending_hr_review: '待人工复核',
    recommended_advance: '建议进一步沟通',
  }[filter] || filter
}

function clearLegacyContext() {
  const query = { ...route.query }
  for (const key of ['account', 'application', 'candidate', 'filter']) delete query[key]
  router.replace({ name: route.name, query }).catch(() => {})
}

async function restoreRunJobContext(runId) {
  const sequence = ++runContextSequence
  try {
    const linkedRun = await api(`recruitment/workflow-runs/${encodeURIComponent(runId)}/`)
    if (sequence !== runContextSequence || String(route.query.run || '') !== String(runId)) return
    const jobId = String(linkedRun.job || '')
    if (!jobId || !context.jobs.some((job) => String(job.id) === jobId)) return
    if (!context.selectJob(jobId, { userId: context.loadedUserId })) return
    resources.runs.items = [linkedRun]
    router.replace({ name: route.name, query: { ...route.query, job: jobId } }).catch(() => {})
  } catch {
    // The normal empty/error state remains visible when a stale run link no longer resolves.
  }
}

function chooseJob(event) {
  const jobId = String(event.target.value || '')
  if (!jobId || jobId === currentJobId.value) return
  if (!context.selectJob(jobId, { userId: context.loadedUserId })) return
  const query = { ...route.query, job: jobId }
  for (const key of ['run', 'account', 'application', 'candidate', 'filter']) delete query[key]
  router.replace({ name: route.name, query }).catch(() => {})
}

function replaceResultQuery(key, value) {
  const normalized = value ? String(value) : ''
  if (String(route.query[key] || '') === normalized) return
  const query = { ...route.query }
  if (normalized) query[key] = normalized
  else delete query[key]
  router.replace({ name: route.name, query }).catch(() => {})
}

watch(
  () => [
    route.query.job, route.query.run, route.query.view, route.query.status,
    route.query.account, route.query.application, route.query.candidate, route.query.filter,
    context.jobs.map((job) => job.id).join(','),
  ],
  ([routeJob, routeRun, routeView, routeStatus]) => {
    const normalizedJob = String(routeJob || '')
    if (normalizedJob && normalizedJob !== currentJobId.value
      && context.jobs.some((job) => String(job.id) === normalizedJob)) {
      context.selectJob(normalizedJob, { userId: context.loadedUserId })
    }
    if (!normalizedJob && routeRun) restoreRunJobContext(String(routeRun))
    selectedRunId.value = String(routeRun || '')
    runPanelId.value = String(routeRun || '')
    statusFilter.value = String(routeStatus || 'all')
    activeView.value = viewFromQuery(route.query)
  },
  { immediate: true },
)

watch(activeView, (value) => replaceResultQuery('view', value))
watch(selectedRunId, (value) => replaceResultQuery('run', value))
watch(statusFilter, (value) => replaceResultQuery('status', value === 'all' ? '' : value))

watch(
  () => currentJobId.value,
  async (jobId) => {
    requestSequence += 1
    statusFilter.value = 'all'
    if (!jobId) {
      selectedRunId.value = ''
      resetResources()
      return
    }
    await loadResults({ reset: true })
  },
  { immediate: true },
)
</script>

<template>
  <div class="page-stack results-center">
    <header class="page-hero page-hero--compact results-hero">
      <div>
        <span class="eyebrow">Recruitment Results</span>
        <h2>结果中心</h2>
        <p v-if="currentJob">{{ currentJob.title }} · 自动化结果、人工事项和候选人进度集中处理</p>
        <p v-else>选择职位后查看任务运行与业务结果</p>
      </div>
      <button v-if="currentJob" class="secondary-button results-refresh" type="button" :disabled="isRefreshing" data-test="refresh-results" @click="loadResults()">
        <AppIcon name="refresh" :size="14" />{{ isRefreshing ? '正在刷新' : '刷新结果' }}
      </button>
    </header>

    <section v-if="!currentJob" class="panel results-required" data-test="results-job-required">
      <AppIcon name="briefcase" :size="25" />
      <div><strong>请先选择在招职位</strong><p>结果中心按职位隔离展示，不会把不同岗位的候选人和任务混在一起。</p></div>
      <select v-if="context.jobs.length" data-test="empty-job-filter" aria-label="选择在招职位" @change="chooseJob"><option value="">选择职位</option><option v-for="job in context.jobs" :key="job.id" :value="job.id">{{ job.title }}</option></select>
      <RouterLink v-else class="primary-button" to="/recruitment/workbench">返回招聘作业台</RouterLink>
    </section>

    <template v-else>
      <div class="results-overview">
        <section class="results-context" aria-label="当前结果范围">
          <label class="results-context__job"><span>当前岗位</span><select :value="currentJobId" data-test="job-filter" @change="chooseJob"><option v-for="job in context.jobs" :key="job.id" :value="String(job.id)">{{ job.title }} · {{ job.account_name || '未绑定账号' }}</option></select><small>招聘目标 {{ currentJob.headcount || '未设置' }} 人</small></label>
          <label><span>任务运行</span><select v-model="selectedRunId" data-test="run-filter"><option value="">该岗位全部运行</option><option v-for="run in jobRuns" :key="run.id" :value="String(run.id)">{{ run.template_name || '自动化任务' }} · {{ statusLabel(run.status) }} · {{ formatDateTime(run.created_at) }}</option></select></label>
          <label><span>结果状态</span><select v-model="statusFilter" data-test="status-filter"><option v-for="option in visibleStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
        </section>

        <section v-if="hasLegacyContext" class="results-context-note" data-test="legacy-context">
          <AppIcon name="filter" :size="14" />
          <span>
            已恢复历史链接上下文
            <template v-if="legacyContext.application"> · 应聘 #{{ legacyContext.application }}</template>
            <template v-if="legacyContext.candidate"> · 候选人 #{{ legacyContext.candidate }}</template>
            <template v-if="legacyContext.filter"> · {{ legacyFilterLabel(legacyContext.filter) }}</template>
            <template v-if="legacyContext.account"> · BOSS 账号 #{{ legacyContext.account }}</template>
          </span>
          <button type="button" data-test="clear-legacy-context" @click="clearLegacyContext">清除定向</button>
        </section>

        <section class="results-kpis" aria-label="结果概览">
          <article><span>待人工处理</span><strong>{{ openAttentionCount }}</strong><small>优先处理候选人咨询与风控</small></article>
          <article><span>活跃任务</span><strong>{{ activeRunCount }}</strong><small>执行中、等待人工或暂停</small></article>
          <article><span>已拉取简历</span><strong>{{ pulledResumeCount }}</strong><small>来自当前岗位主动寻访</small></article>
          <article><span>候选人</span><strong>{{ resources.applications.items.length }}</strong><small>{{ resources.resumes.items.length }} 份简历已归档</small></article>
        </section>

        <div v-if="resourceErrors.length && !allFailed" class="results-data-warning" role="status" data-test="partial-error">
          <AppIcon name="alert-circle" :size="16" />
          <span><strong>{{ resourceErrors.length }} 项数据暂未加载：</strong>{{ resourceErrors.map((item) => item.label).join('、') }}。已加载的结果仍可查看。</span>
          <button type="button" :disabled="isRefreshing" @click="loadResults()">重试</button>
        </div>
      </div>

      <section v-if="initialLoading" class="panel results-loading" aria-live="polite" data-test="results-loading">
        <span></span><span></span><span></span><p>正在从服务端恢复该岗位的任务与结果…</p>
      </section>

      <section v-else-if="allFailed" class="panel results-fatal-error" data-test="results-error">
        <AppIcon name="alert-circle" :size="25" />
        <div><strong>结果数据暂时无法加载</strong><p>{{ resourceErrors[0]?.message || '请稍后重试' }}。页面不会用旧岗位的数据覆盖当前岗位。</p></div>
        <button class="secondary-button" type="button" @click="loadResults()">重新加载</button>
      </section>

      <template v-else>
        <div class="results-workspace">
          <nav class="results-tabs" role="tablist" aria-label="结果中心视图">
            <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="activeView === tab.key" :class="{ active: activeView === tab.key }" :data-test="`results-tab-${tab.key}`" @click="activeView = tab.key">{{ tab.label }} <span>{{ tab.count }}</span></button>
          </nav>

        <section v-if="activeView === 'attention'" class="results-panel" data-test="attention-view">
          <header><div><span class="panel-kicker">HUMAN ATTENTION</span><h3>需要人工</h3><p>系统只提醒，不会替 HR 对候选人意图或风控结果做决定。</p></div><span>{{ filteredAttentions.length }} 项</span></header>
          <p v-if="resources.attentions.error" class="results-inline-error">人工事项加载失败：{{ resources.attentions.error }}</p>
          <p v-if="attentionActionError" class="results-inline-error" data-test="attention-action-error">{{ attentionActionError }}</p>
          <div v-if="filteredAttentions.length" class="attention-list">
            <article v-for="item in filteredAttentions" :key="item.id" :class="`is-${statusTone(item.status)}`">
              <i></i><div><span>{{ item.attention_type_label || '人工事项' }} · {{ item.candidate_name || item.account_name || '当前岗位' }}</span><strong>{{ item.title }}</strong><p>{{ detailText(item.detail) }}</p><small>{{ formatDateTime(item.created_at) }} · {{ item.status_label || statusLabel(item.status) }}</small></div>
              <div class="attention-actions">
                <RouterLink :to="{ name: 'recruitment-candidates', query: { job: currentJobId, application: item.application || undefined } }">查看上下文 <AppIcon name="chevron-right" :size="11" /></RouterLink>
                <button v-if="item.status === 'open'" type="button" :disabled="Boolean(attentionActionId)" :data-test="`resolve-attention-${item.id}`" @click="resolveAttention(item)">{{ attentionActionId === String(item.id) ? '处理中…' : '标记已处理' }}</button>
              </div>
            </article>
          </div>
          <div v-else-if="resources.attentions.loading" class="results-local-loading">正在加载人工事项…</div>
          <div v-else class="results-empty"><AppIcon name="check-circle" :size="24" /><strong>当前范围没有需要人工处理的事项</strong><span>可切换状态查看已处理记录，或前往任务结果查看自动化进度。</span></div>
        </section>

        <section v-else-if="activeView === 'tasks'" class="results-task-grid" data-test="tasks-view">
          <article class="results-subpanel">
            <header><div><span class="panel-kicker">WORKFLOW RUNS</span><h3>自动化运行</h3><p>刷新后从服务端恢复，不依赖本页内存。</p></div><span>{{ filteredRuns.length }} 次</span></header>
            <p v-if="resources.runs.error" class="results-inline-error">任务运行加载失败：{{ resources.runs.error }}</p>
            <p v-if="runActionError" class="results-inline-error" data-test="run-action-error">{{ runActionError }}</p>
            <div v-if="filteredRuns.length" class="run-list">
              <article v-for="run in filteredRuns" :key="run.id">
                <div class="run-list__top"><div><strong>{{ run.template_name || '自动化任务' }}</strong><small>#{{ String(run.id).slice(0, 8) }} · {{ run.mode === 'formal' ? '正式运行' : '试运行' }}</small></div><span :class="`is-${statusTone(run.status)}`">{{ statusLabel(run.status) }}</span></div>
                <div class="results-progress"><i :style="{ width: `${runProgress(run)}%` }"></i></div>
                <p v-if="run.error_message" class="run-error">{{ run.error_message }}</p>
                <footer>
                  <small>{{ formatDateTime(run.updated_at) }} · {{ (run.node_runs || []).length }} 个步骤</small>
                  <span class="run-list__actions">
                    <button type="button" :aria-expanded="expandedRunId === String(run.id)" @click="toggleRunDetail(run.id)">{{ expandedRunId === String(run.id) ? '收起运行详情' : '查看运行详情' }}</button>
                    <button type="button" :data-test="`manage-run-${run.id}`" @click="openRunPanel(run)">处理运行</button>
                  </span>
                </footer>
                <section v-if="expandedRunId === String(run.id)" class="run-detail" :aria-label="`${run.template_name || '自动化任务'}运行详情`">
                  <div>
                    <span>节点进度</span>
                    <ol v-if="run.node_runs?.length">
                      <li v-for="node in run.node_runs" :key="node.id">
                        <i :class="`is-${statusTone(node.status)}`"></i>
                        <strong>{{ node.node_key || node.node_type || '流程节点' }}</strong>
                        <small>{{ node.status_label || statusLabel(node.status) }}<template v-if="node.error_message"> · {{ node.error_message }}</template></small>
                      </li>
                    </ol>
                    <p v-else>该运行暂未生成节点记录。</p>
                  </div>
                  <div>
                    <span>事件时间线</span>
                    <ol v-if="run.events?.length">
                      <li v-for="event in run.events.slice().reverse()" :key="event.id">
                        <time>{{ formatDateTime(event.created_at) }}</time>
                        <small>{{ event.message }}</small>
                      </li>
                    </ol>
                    <p v-else>该运行暂未记录更多事件。</p>
                  </div>
                </section>
              </article>
            </div>
            <div v-else-if="resources.runs.loading" class="results-local-loading">正在恢复任务运行…</div>
            <div v-else class="results-empty results-empty--compact"><AppIcon name="workflow" :size="22" /><strong>当前筛选下没有任务运行</strong><span>返回作业台发起任务后，运行记录会出现在这里。</span></div>
          </article>

          <article class="results-subpanel">
            <header><div><span class="panel-kicker">SEARCH OUTCOMES</span><h3>主动寻访结果</h3><p>按目标简历数追踪扫描和拉取进度。</p></div><span>{{ filteredCampaigns.length }} 个方案</span></header>
            <p v-if="resources.campaigns.error" class="results-inline-error">主动寻访加载失败：{{ resources.campaigns.error }}</p>
            <div v-if="filteredCampaigns.length" class="campaign-list">
              <article v-for="campaign in filteredCampaigns" :key="campaign.id">
                <header><div><strong>{{ campaign.name }}</strong><small>{{ campaign.source === 'recommend' ? '推荐人才' : campaign.source === 'deep_search' ? '深度搜索' : '关键词搜索' }}</small></div><span :class="`is-${statusTone(campaign.status)}`">{{ statusLabel(campaign.status) }}</span></header>
                <div class="campaign-numbers"><span><b>{{ campaign.pulled_resume_count }}</b>/{{ campaign.target_resume_count }} 份简历</span><small>已扫描 {{ campaign.scanned_count }}/{{ campaign.max_scan_count }} 人</small></div>
                <div class="results-progress"><i :style="{ width: `${campaignProgress(campaign)}%` }"></i></div>
                <p v-if="campaign.error_message || campaign.stop_reason" :class="{ 'run-error': campaign.error_message }">{{ campaign.error_message || `停止原因：${campaign.stop_reason}` }}</p>
              </article>
            </div>
            <div v-else-if="resources.campaigns.loading" class="results-local-loading">正在加载主动寻访结果…</div>
            <div v-else class="results-empty results-empty--compact"><AppIcon name="search" :size="22" /><strong>当前筛选下没有主动寻访</strong><span>被动消息方案仍可只产生任务运行和人工事项。</span></div>
          </article>
        </section>

        <section v-else-if="activeView === 'candidates'" class="results-panel" data-test="candidates-view">
          <header><div><span class="panel-kicker">CANDIDATES & RESUMES</span><h3>候选人与简历</h3><p>评分只提供初筛依据，不会自动推进或淘汰候选人。</p></div><div class="results-header-links"><RouterLink :to="{ name: 'recruitment-candidates', query: { job: currentJobId, application: legacyContext.application || undefined, candidate: legacyContext.candidate || undefined } }">候选人详情</RouterLink><RouterLink :to="{ name: 'recruitment-resumes', query: { job: currentJobId, candidate: legacyContext.candidate || undefined, filter: legacyContext.filter || undefined } }">简历详情</RouterLink></div></header>
          <p v-if="resources.applications.error || resources.resumes.error || resources.structures.error || resources.assessments.error" class="results-inline-error">部分候选人或简历智能数据未加载，请参考页面上方的数据提示。</p>
          <div v-if="candidateResults.length" class="candidate-result-list">
            <article v-for="row in candidateResults" :key="row.application.id" :data-application-id="row.application.id">
              <div class="candidate-avatar">{{ row.application.candidate?.name?.slice(0, 1) || '?' }}</div>
              <div><strong>{{ row.application.candidate?.name || '未命名候选人' }}</strong><small>{{ row.application.candidate?.current_title || '当前岗位未填写' }} · {{ row.application.candidate?.current_city || '城市未填写' }}</small></div>
              <span class="candidate-stage">{{ row.application.stage_label || statusLabel(row.application.stage) }}</span>
              <div class="candidate-resume"><strong>{{ row.resumes.length }} 份简历</strong><small>{{ row.resumes.some((resume) => structuredResumeIds.has(String(resume.id))) ? '已完成结构化' : row.resumes.length ? '等待结构化' : '等待候选人提供' }}</small></div>
              <div class="candidate-score" :class="{ 'has-score': row.bestAssessment }"><strong>{{ scoreText(row.bestAssessment) }}</strong><small v-if="row.bestAssessment">可信度 {{ Math.round(Number(row.bestAssessment.confidence || 0) * 100) }}%</small></div>
              <RouterLink :to="{ name: 'recruitment-resumes', query: { job: currentJobId, candidate: row.application.candidate?.id, filter: legacyContext.filter || undefined } }" aria-label="查看候选人简历"><AppIcon name="chevron-right" :size="13" /></RouterLink>
            </article>
          </div>
          <div v-else-if="resources.applications.loading" class="results-local-loading">正在加载候选人与简历…</div>
          <div v-else class="results-empty"><AppIcon name="users" :size="25" /><strong>该岗位还没有候选人结果</strong><span>返回作业台执行寻访，或在候选人页面导入已确认的人选。</span><RouterLink class="primary-button" to="/recruitment/workbench">返回招聘作业台</RouterLink></div>
        </section>

        <section v-else class="results-panel" data-test="pipeline-view">
          <header><div><span class="panel-kicker">HIRING PROGRESS</span><h3>招聘进度</h3><p>{{ resources.applications.items.length }} 位候选人 · 招聘目标 {{ currentJob.headcount || '未设置' }} 人</p></div><RouterLink :to="{ name: 'recruitment-pipeline', query: { job: currentJobId } }">进入招聘流程</RouterLink></header>
          <p v-if="resources.applications.error" class="results-inline-error">招聘进度加载失败：{{ resources.applications.error }}</p>
          <div v-if="resources.applications.items.length" class="stage-progress-list">
            <article v-for="stage in stageProgress" :key="stage.key"><span>{{ stage.label }}</span><div><i :style="{ width: `${stage.count / maxStageCount * 100}%` }"></i></div><strong>{{ stage.count }}</strong></article>
          </div>
          <div v-else-if="resources.applications.loading" class="results-local-loading">正在加载招聘进度…</div>
          <div v-else class="results-empty"><AppIcon name="workflow" :size="25" /><strong>还没有可展示的招聘进度</strong><span>候选人进入当前岗位后，系统会按阶段汇总在这里。</span></div>
        </section>
        </div>
      </template>
      <WorkflowRunPanel
        v-if="activeRun"
        :run="activeRun"
        :busy="runActionBusy"
        @close="closeRunPanel"
        @pause="runControl('pause')"
        @resume="runControl('resume')"
        @cancel="runControl('cancel')"
        @decision="decideRunNode"
        @retry="retryRunNode"
      />
    </template>
  </div>
</template>

<style scoped>
.results-center {
  --results-font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --results-color-ink: #0f172a;
  --results-color-slate: #334155;
  --results-color-copy: var(--results-color-slate);
  --results-color-muted: #64748b;
  --results-color-faint: var(--results-color-muted);
  --results-color-line: #e2e8f0;
  --results-color-line-soft: var(--results-color-line);
  --results-color-surface: #ffffff;
  --results-color-canvas: #f3f6f8;
  --results-color-surface-soft: var(--results-color-canvas);
  --results-color-surface-muted: var(--results-color-canvas);
  --results-color-brand: #0f9f8f;
  --results-color-brand-dark: #087f73;
  --results-color-brand-soft: var(--results-color-canvas);
  --results-color-brand-control: var(--results-color-surface);
  --results-color-brand-line: var(--results-color-line);
  --results-color-warning: #d97706;
  --results-color-warning-text: var(--results-color-warning);
  --results-color-warning-soft: var(--results-color-canvas);
  --results-color-warning-line: var(--results-color-warning);
  --results-color-danger: #dc4a4a;
  --results-color-danger-text: var(--results-color-danger);
  --results-color-danger-soft: var(--results-color-canvas);
  --results-color-active: var(--results-color-brand-dark);
  --results-color-active-soft: var(--results-color-canvas);
  --results-space-1: 4px;
  --results-space-2: 8px;
  --results-space-3: 12px;
  --results-space-4: 16px;
  --results-space-5: 22px;
  --results-space-6: 28px;
  --results-space-7: 34px;
  --results-radius-control: 9px;
  --results-radius-panel: 15px;
  --results-radius-status: 999px;
  --results-border-width: 1px;
  --results-active-border-width: 2px;
  --results-control-height: 38px;
  --results-font-meta: 10px;
  --results-font-detail: 11px;
  --results-font-control: 12px;
  --results-font-body: 13px;
  --results-font-title: 15px;
  --results-font-metric: 29px;
  --results-font-campaign-metric: 20px;
  --results-weight-regular: 400;
  --results-weight-medium: 600;
  --results-weight-bold: 700;
  --results-weight-heavy: 800;
  --results-leading-tight: 1.3;
  --results-leading-body: 1.6;
  --results-tracking-kicker: .12em;
  --results-tracking-metric: -.025em;
  --results-shadow-panel: 0 1px 2px rgba(15, 23, 42, .025);
  --results-transition: 180ms ease;
  --results-disabled-opacity: .55;
  --results-filter-job-min: 230px;
  --results-filter-run-min: 210px;
  --results-filter-status-min: 170px;
  --results-empty-copy-max: 420px;
  --results-avatar-size: 32px;
  --results-candidate-name-min: 150px;
  --results-candidate-stage-min: 90px;
  --results-candidate-resume-min: 110px;
  --results-candidate-score-min: 155px;
  --results-action-column: 24px;
  --results-stage-label-width: 90px;
  --results-stage-count-width: 30px;
  --results-progress-height: 5px;
  --results-stage-progress-height: 8px;
  --results-status-marker-width: 4px;
  --results-node-marker-size: 6px;
  --results-skeleton-height: 76px;
  --results-skeleton-background: var(--results-color-surface-muted);
  --results-skeleton-opacity: .6;
  --results-skeleton-duration: 1.2s;
  gap: var(--results-space-5);
  container-name: results-center;
  container-type: inline-size;
  width: 100%;
  min-width: 0;
  max-width: 100%;
  color: var(--results-color-ink);
  font-family: var(--results-font-family);
}

.results-center *,
.results-center *::before,
.results-center *::after {
  box-sizing: border-box;
}

.results-hero {
  align-items: center;
}

.results-refresh {
  display: inline-flex;
  align-items: center;
  gap: var(--results-space-2);
  color: var(--results-color-slate);
  background: var(--results-color-surface);
  border-color: var(--results-color-line);
  font-size: var(--results-font-control);
}

.results-required {
  display: flex;
  align-items: center;
  gap: var(--results-space-4);
  padding: var(--results-space-6);
}

.results-required > svg {
  flex: none;
  color: var(--results-color-brand);
}

.results-required > div {
  flex: 1;
  min-width: 0;
}

.results-required strong {
  font-size: var(--results-font-title);
}

.results-required p {
  margin: var(--results-space-1) 0 0;
  color: var(--results-color-muted);
  font-size: var(--results-font-control);
  line-height: var(--results-leading-body);
}

.results-required .primary-button,
.results-fatal-error .secondary-button,
.results-empty .primary-button {
  font-size: var(--results-font-control);
}

.results-required select {
  min-width: var(--results-filter-status-min);
  max-width: 100%;
  height: var(--results-control-height);
  padding: 0 var(--results-space-7) 0 var(--results-space-3);
  color: var(--results-color-slate);
  background: var(--results-color-surface);
  border: var(--results-border-width) solid var(--results-color-line);
  border-radius: var(--results-radius-control);
  font: var(--results-weight-medium) var(--results-font-control)/var(--results-leading-tight) var(--results-font-family);
}

.results-overview,
.results-workspace {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  background: var(--results-color-surface);
  border: var(--results-border-width) solid var(--results-color-line);
  border-radius: var(--results-radius-panel);
  box-shadow: var(--results-shadow-panel);
}

.results-context {
  display: grid;
  grid-template-columns: minmax(var(--results-filter-job-min), 1.2fr) minmax(var(--results-filter-run-min), 1fr) minmax(var(--results-filter-status-min), .65fr);
  gap: var(--results-space-4);
  padding: var(--results-space-4) var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
}

.results-context__job,
.results-context label {
  display: grid;
  gap: var(--results-space-1);
  min-width: 0;
}

.results-context span {
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
  letter-spacing: var(--results-tracking-kicker);
  text-transform: uppercase;
}

.results-context small {
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
}

.results-context select {
  width: 100%;
  min-width: 0;
  height: var(--results-control-height);
  padding: 0 var(--results-space-7) 0 var(--results-space-3);
  color: var(--results-color-slate);
  background: var(--results-color-surface-soft);
  border: var(--results-border-width) solid var(--results-color-line);
  border-radius: var(--results-radius-control);
  font: var(--results-weight-medium) var(--results-font-control)/var(--results-leading-tight) var(--results-font-family);
}

.results-context select:focus-visible,
.results-tabs button:focus-visible,
.results-center button:focus-visible,
.results-center a:focus-visible {
  outline: var(--results-active-border-width) solid var(--results-color-brand);
  outline-offset: var(--results-active-border-width);
}

.results-context-note {
  display: flex;
  align-items: center;
  gap: var(--results-space-2);
  padding: var(--results-space-2) var(--results-space-5);
  color: var(--results-color-copy);
  background: var(--results-color-surface-soft);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.results-context-note > svg {
  flex: none;
  color: var(--results-color-brand);
}

.results-context-note span,
.results-data-warning span {
  flex: 1;
  min-width: 0;
}

.results-context-note button,
.results-data-warning button {
  flex: none;
  padding: var(--results-space-1) 0;
  color: var(--results-color-brand-dark);
  background: transparent;
  border: 0;
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-heavy);
}

.results-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.results-kpis article {
  display: grid;
  align-content: start;
  gap: var(--results-space-1);
  min-width: 0;
  padding: var(--results-space-4) var(--results-space-5);
  border-left: var(--results-border-width) solid var(--results-color-line-soft);
}

.results-kpis article:first-child {
  background: var(--results-color-brand-soft);
  border-left: 0;
}

.results-kpis span {
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-medium);
}

.results-kpis strong {
  color: var(--results-color-ink);
  font-family: var(--results-font-family);
  font-size: var(--results-font-metric);
  font-weight: var(--results-weight-bold);
  line-height: var(--results-leading-tight);
  letter-spacing: var(--results-tracking-metric);
}

.results-kpis small {
  overflow: hidden;
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
  line-height: var(--results-leading-body);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.results-data-warning {
  display: flex;
  align-items: center;
  gap: var(--results-space-2);
  padding: var(--results-space-2) var(--results-space-5);
  color: var(--results-color-warning-text);
  background: var(--results-color-warning-soft);
  border-top: var(--results-border-width) solid var(--results-color-warning-line);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.results-loading {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--results-space-3);
  padding: var(--results-space-5);
}

.results-loading span {
  height: var(--results-skeleton-height);
  background: var(--results-skeleton-background);
  border-radius: var(--results-radius-control);
  animation: results-pulse var(--results-skeleton-duration) ease-in-out infinite;
}

.results-loading p {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  text-align: center;
}

.results-fatal-error {
  display: flex;
  align-items: center;
  gap: var(--results-space-4);
  padding: var(--results-space-6);
}

.results-fatal-error > svg {
  flex: none;
  color: var(--results-color-danger);
}

.results-fatal-error > div {
  flex: 1;
  min-width: 0;
}

.results-fatal-error strong {
  font-size: var(--results-font-title);
}

.results-fatal-error p {
  margin: var(--results-space-1) 0 0;
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.results-tabs {
  display: flex;
  min-width: 0;
  padding: 0 var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-line);
}

.results-tabs button {
  position: relative;
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: var(--results-space-2);
  min-width: 0;
  padding: var(--results-space-3) var(--results-space-4);
  color: var(--results-color-muted);
  background: transparent;
  border: 0;
  font-size: var(--results-font-control);
  font-weight: var(--results-weight-bold);
  transition: color var(--results-transition), background-color var(--results-transition);
}

.results-tabs button::after {
  position: absolute;
  right: 0;
  bottom: calc(-1 * var(--results-border-width));
  left: 0;
  height: var(--results-active-border-width);
  background: transparent;
  content: "";
}

.results-tabs button:hover {
  color: var(--results-color-slate);
  background: var(--results-color-surface-soft);
}

.results-tabs button.active {
  color: var(--results-color-brand-dark);
}

.results-tabs button.active::after {
  background: var(--results-color-brand);
}

.results-tabs span {
  display: inline-grid;
  place-items: center;
  min-width: var(--results-space-5);
  min-height: var(--results-space-5);
  padding: 0 var(--results-space-2);
  color: var(--results-color-muted);
  background: var(--results-color-surface-muted);
  border-radius: var(--results-radius-status);
  font-size: var(--results-font-meta);
}

.results-tabs button.active span {
  color: var(--results-color-brand-dark);
  background: var(--results-color-brand-soft);
}

.results-panel,
.results-subpanel,
.results-task-grid {
  min-width: 0;
}

.results-panel,
.results-subpanel {
  overflow: hidden;
}

.results-panel > header,
.results-subpanel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--results-space-4);
  padding: var(--results-space-4) var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
}

.results-panel > header h3,
.results-subpanel > header h3 {
  margin: var(--results-space-1) 0;
  color: var(--results-color-ink);
  font-size: var(--results-font-title);
}

.results-panel > header p,
.results-subpanel > header p {
  margin: 0;
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.results-panel > header > span,
.results-subpanel > header > span {
  flex: none;
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
}

.results-panel > header > a,
.results-header-links a {
  color: var(--results-color-brand-dark);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-heavy);
  text-decoration: none;
}

.results-header-links {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--results-space-3);
}

.results-inline-error {
  margin: var(--results-space-3) var(--results-space-5) 0;
  padding: var(--results-space-2) var(--results-space-3);
  color: var(--results-color-danger-text);
  background: var(--results-color-danger-soft);
  border-radius: var(--results-radius-control);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.attention-list,
.run-list,
.campaign-list,
.candidate-result-list {
  display: grid;
}

.attention-list > article {
  display: grid;
  grid-template-columns: var(--results-status-marker-width) minmax(0, 1fr) auto;
  gap: var(--results-space-3);
  align-items: center;
  min-width: 0;
  padding: var(--results-space-4) var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
}

.attention-list > article:last-child,
.run-list > article:last-child,
.campaign-list > article:last-child,
.candidate-result-list > article:last-child {
  border-bottom: 0;
}

.attention-list i {
  align-self: stretch;
  background: var(--results-color-faint);
  border-radius: var(--results-radius-status);
}

.attention-list .is-warning i {
  background: var(--results-color-warning);
}

.attention-list .is-danger i {
  background: var(--results-color-danger);
}

.attention-list .is-success i {
  background: var(--results-color-brand);
}

.attention-list article > div {
  display: grid;
  gap: var(--results-space-1);
  min-width: 0;
}

.attention-list span,
.attention-list small {
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
}

.attention-list strong {
  color: var(--results-color-ink);
  font-size: var(--results-font-body);
}

.attention-list p {
  margin: 0;
  color: var(--results-color-copy);
  font-size: var(--results-font-control);
  line-height: var(--results-leading-body);
}

.attention-actions {
  display: grid;
  justify-items: end;
  gap: var(--results-space-2);
}

.attention-list a,
.attention-actions button,
.run-list footer button {
  color: var(--results-color-brand-dark);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-heavy);
  text-decoration: none;
}

.attention-list a {
  display: inline-flex;
  align-items: center;
  gap: var(--results-space-1);
}

.attention-actions button {
  padding: var(--results-space-2) var(--results-space-3);
  background: var(--results-color-brand-control);
  border: var(--results-border-width) solid var(--results-color-brand-line);
  border-radius: var(--results-radius-control);
}

.attention-actions button:disabled,
.results-center button:disabled {
  opacity: var(--results-disabled-opacity);
}

.results-empty {
  display: grid;
  justify-items: center;
  gap: var(--results-space-2);
  padding: var(--results-space-7) var(--results-space-5);
  color: var(--results-color-faint);
  text-align: center;
}

.results-empty strong {
  color: var(--results-color-slate);
  font-size: var(--results-font-body);
}

.results-empty span {
  max-width: var(--results-empty-copy-max);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.results-empty .primary-button {
  margin-top: var(--results-space-2);
  color: var(--results-color-surface);
  text-decoration: none;
}

.results-empty--compact {
  padding: var(--results-space-6) var(--results-space-4);
}

.results-local-loading {
  padding: var(--results-space-7);
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  text-align: center;
}

.results-task-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.results-subpanel + .results-subpanel {
  border-left: var(--results-border-width) solid var(--results-color-line-soft);
}

.run-list > article,
.campaign-list > article {
  display: grid;
  gap: var(--results-space-3);
  min-width: 0;
  padding: var(--results-space-4) var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
}

.run-list__top,
.campaign-list article > header,
.run-list footer,
.campaign-numbers {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--results-space-3);
  min-width: 0;
}

.run-list__top > div,
.campaign-list header > div {
  display: grid;
  gap: var(--results-space-1);
  min-width: 0;
}

.run-list strong,
.campaign-list strong {
  color: var(--results-color-ink);
  font-size: var(--results-font-control);
}

.run-list small,
.campaign-list small {
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
  line-height: var(--results-leading-body);
}

.run-list__top > span,
.campaign-list header > span,
.candidate-stage {
  flex: none;
  padding: var(--results-space-1) var(--results-space-2);
  border-radius: var(--results-radius-status);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
}

.run-list__top > span.is-success,
.campaign-list header > span.is-success {
  color: var(--results-color-brand-dark);
  background: var(--results-color-brand-soft);
}

.run-list__top > span.is-danger,
.campaign-list header > span.is-danger {
  color: var(--results-color-danger-text);
  background: var(--results-color-danger-soft);
}

.run-list__top > span.is-warning,
.campaign-list header > span.is-warning {
  color: var(--results-color-warning-text);
  background: var(--results-color-warning-soft);
}

.run-list__top > span.is-active,
.campaign-list header > span.is-active {
  color: var(--results-color-active);
  background: var(--results-color-active-soft);
}

.run-list__top > span.is-neutral,
.campaign-list header > span.is-neutral {
  color: var(--results-color-muted);
  background: var(--results-color-surface-muted);
}

.results-progress {
  height: var(--results-progress-height);
  overflow: hidden;
  background: var(--results-color-line);
  border-radius: var(--results-radius-status);
}

.results-progress i {
  display: block;
  height: 100%;
  background: var(--results-color-brand);
  border-radius: inherit;
}

.run-list__actions {
  display: flex;
  align-items: center;
  gap: var(--results-space-3);
}

.run-list footer button {
  padding: var(--results-space-1) 0;
  background: transparent;
  border: 0;
}

.run-error {
  margin: 0;
  padding: var(--results-space-2);
  color: var(--results-color-danger-text);
  background: var(--results-color-danger-soft);
  border-radius: var(--results-radius-control);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.campaign-numbers {
  align-items: flex-end;
}

.campaign-numbers b {
  color: var(--results-color-brand-dark);
  font-size: var(--results-font-campaign-metric);
}

.campaign-list p:not(.run-error) {
  margin: 0;
  color: var(--results-color-warning-text);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
}

.candidate-result-list > article {
  display: grid;
  grid-template-columns: var(--results-avatar-size) minmax(var(--results-candidate-name-min), 1.15fr) minmax(var(--results-candidate-stage-min), .55fr) minmax(var(--results-candidate-resume-min), .7fr) minmax(var(--results-candidate-score-min), .9fr) var(--results-action-column);
  align-items: center;
  gap: var(--results-space-3);
  min-width: 0;
  padding: var(--results-space-3) var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
}

.candidate-avatar {
  display: grid;
  place-items: center;
  width: var(--results-avatar-size);
  height: var(--results-avatar-size);
  color: var(--results-color-brand-dark);
  background: var(--results-color-brand-soft);
  border-radius: var(--results-radius-control);
  font-size: var(--results-font-control);
  font-weight: var(--results-weight-heavy);
}

.candidate-result-list article > div:not(.candidate-avatar) {
  display: grid;
  gap: var(--results-space-1);
  min-width: 0;
}

.candidate-result-list strong {
  overflow: hidden;
  color: var(--results-color-ink);
  font-size: var(--results-font-control);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-result-list small {
  overflow: hidden;
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-stage {
  justify-self: start;
  color: var(--results-color-copy);
  background: var(--results-color-surface-muted);
}

.candidate-score.has-score strong {
  color: var(--results-color-brand-dark);
}

.candidate-result-list a {
  display: inline-grid;
  place-items: center;
  color: var(--results-color-muted);
}

.stage-progress-list {
  display: grid;
  gap: var(--results-space-3);
  padding: var(--results-space-5);
}

.stage-progress-list article {
  display: grid;
  grid-template-columns: var(--results-stage-label-width) minmax(0, 1fr) var(--results-stage-count-width);
  align-items: center;
  gap: var(--results-space-3);
}

.stage-progress-list span {
  color: var(--results-color-copy);
  font-size: var(--results-font-control);
}

.stage-progress-list div {
  height: var(--results-stage-progress-height);
  overflow: hidden;
  background: var(--results-color-line-soft);
  border-radius: var(--results-radius-status);
}

.stage-progress-list i {
  display: block;
  height: 100%;
  min-width: var(--results-active-border-width);
  background: var(--results-color-brand);
  border-radius: inherit;
}

.stage-progress-list strong {
  color: var(--results-color-ink);
  font-size: var(--results-font-control);
  text-align: right;
}

.run-detail {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--results-space-3);
  padding: var(--results-space-3) 0 0;
  border-top: var(--results-border-width) solid var(--results-color-line-soft);
}

.run-detail > div {
  display: grid;
  align-content: start;
  gap: var(--results-space-2);
  min-width: 0;
}

.run-detail > div > span {
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
  letter-spacing: var(--results-tracking-kicker);
  text-transform: uppercase;
}

.run-detail ol {
  display: grid;
  gap: var(--results-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.run-detail li {
  display: grid;
  grid-template-columns: var(--results-node-marker-size) minmax(0, .6fr) minmax(0, 1fr);
  align-items: center;
  gap: var(--results-space-2);
  min-width: 0;
}

.run-detail li > i {
  width: var(--results-node-marker-size);
  height: var(--results-node-marker-size);
  background: var(--results-color-faint);
  border-radius: var(--results-radius-status);
}

.run-detail li > i.is-success {
  background: var(--results-color-brand);
}

.run-detail li > i.is-danger {
  background: var(--results-color-danger);
}

.run-detail li > i.is-warning {
  background: var(--results-color-warning);
}

.run-detail strong,
.run-detail small,
.run-detail p,
.run-detail time {
  min-width: 0;
  margin: 0;
  font-size: var(--results-font-meta);
  line-height: var(--results-leading-body);
}

.run-detail strong {
  overflow: hidden;
  color: var(--results-color-slate);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-detail small,
.run-detail p,
.run-detail time {
  color: var(--results-color-muted);
  overflow-wrap: anywhere;
}

@keyframes results-pulse {
  50% { opacity: var(--results-skeleton-opacity); }
}

/* Container conditions intentionally use literals because custom properties are invalid in query expressions. */
@container results-center (max-width: 1320px) {
  .results-context {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }

  .results-context__job {
    grid-column: 1 / -1;
  }

  .results-tabs {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding: 0;
  }

  .results-tabs button:nth-child(odd) {
    border-right: var(--results-border-width) solid var(--results-color-line-soft);
  }

  .results-tabs button:nth-child(-n + 2) {
    border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  }
}

@container results-center (max-width: 1050px) {

  .results-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .results-kpis article:nth-child(odd) {
    border-left: 0;
  }

  .results-kpis article:nth-child(n + 3) {
    border-top: var(--results-border-width) solid var(--results-color-line-soft);
  }

  .results-task-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .results-subpanel + .results-subpanel {
    border-top: var(--results-border-width) solid var(--results-color-line-soft);
    border-left: 0;
  }

  .candidate-result-list > article {
    grid-template-columns: var(--results-avatar-size) minmax(0, 1fr) auto;
  }

  .candidate-result-list .candidate-resume,
  .candidate-result-list .candidate-score {
    grid-column: 2 / -1;
  }

  .candidate-result-list > article > a {
    grid-row: 1;
    grid-column: 3;
  }
}

@container results-center (max-width: 720px) {
  .results-hero,
  .results-required,
  .results-fatal-error,
  .results-data-warning,
  .results-panel > header,
  .results-subpanel > header {
    align-items: flex-start;
  }

  .results-required,
  .results-fatal-error {
    flex-wrap: wrap;
  }

  .results-required select,
  .results-required .primary-button {
    width: 100%;
  }

  .results-context {
    grid-template-columns: minmax(0, 1fr);
    padding: var(--results-space-4);
  }

  .results-context__job {
    grid-column: auto;
  }

  .results-context-note,
  .results-data-warning {
    padding-right: var(--results-space-4);
    padding-left: var(--results-space-4);
  }

  .results-kpis article {
    padding: var(--results-space-3) var(--results-space-4);
  }

  .results-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow-x: visible;
  }

  .results-tabs button {
    min-width: 0;
    padding-right: var(--results-space-3);
    padding-left: var(--results-space-3);
  }

  .results-panel > header,
  .results-subpanel > header {
    flex-direction: column;
    padding-right: var(--results-space-4);
    padding-left: var(--results-space-4);
  }

  .results-header-links {
    justify-content: flex-start;
  }

  .attention-list > article {
    grid-template-columns: var(--results-status-marker-width) minmax(0, 1fr);
    padding-right: var(--results-space-4);
    padding-left: var(--results-space-4);
  }

  .attention-actions {
    grid-column: 2;
    grid-template-columns: repeat(2, minmax(0, auto));
    justify-content: start;
    justify-items: start;
  }

  .run-list > article,
  .campaign-list > article,
  .candidate-result-list > article {
    padding-right: var(--results-space-4);
    padding-left: var(--results-space-4);
  }

  .run-list footer,
  .campaign-numbers {
    align-items: flex-start;
    flex-direction: column;
  }

  .candidate-stage {
    grid-row: 2;
    grid-column: 2;
  }

  .candidate-result-list .candidate-resume,
  .candidate-result-list .candidate-score {
    grid-column: 2 / -1;
  }

  .run-detail {
    grid-template-columns: minmax(0, 1fr);
  }

  .stage-progress-list {
    padding: var(--results-space-4);
  }

  .stage-progress-list article {
    grid-template-columns: minmax(var(--results-stage-count-width), auto) minmax(0, 1fr) var(--results-stage-count-width);
  }
}

@media (prefers-reduced-motion: reduce) {
  .results-loading span {
    animation: none;
  }

  .results-tabs button {
    transition: none;
  }
}
</style>
