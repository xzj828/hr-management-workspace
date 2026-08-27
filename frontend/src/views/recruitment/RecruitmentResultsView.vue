<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import ResumeIntelligencePanel from '@/components/ResumeIntelligencePanel.vue'
import ScreeningDecisionDrawer from '@/components/ScreeningDecisionDrawer.vue'
import WorkflowRunPanel from '@/components/WorkflowRunPanel.vue'
import { stageColumns } from '@/recruitment'
import { createRequestId } from '@/recruitmentJobs'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const props = defineProps({
  embedded: { type: Boolean, default: false },
  autoRefreshMs: { type: Number, default: 0 },
})

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
const candidateFilters = reactive({
  stage: 'all',
  ai: 'all',
  resume: 'all',
  hr: 'all',
  notification: 'all',
})
const selectedApplicationIds = ref([])
const candidatePage = ref(1)
const candidatePageSize = ref(10)
const detailStructure = ref(null)
const detailAssessment = ref(null)
const detailAssessments = ref([])
const detailTasks = ref([])
const detailLoading = ref(false)
const detailError = ref('')
const decisionDrawerMode = ref('')
const decisionBusy = ref(false)
const decisionSaved = ref(false)
const decisionError = ref('')
const notificationError = ref('')
const decisionBatchId = ref('')
const decisionRequest = reactive({ id: '', signature: '' })
const notificationRequest = reactive({ id: '', signature: '', approvalId: '' })
const operationNotice = ref(null)
let detailReturnFocus = null
let requestSequence = 0
let runContextSequence = 0
let detailSequence = 0

const resources = reactive({
  runs: { items: [], loading: false, loaded: false, error: '' },
  campaigns: { items: [], loading: false, loaded: false, error: '' },
  attentions: { items: [], loading: false, loaded: false, error: '' },
  screening: { items: [], loading: false, loaded: false, error: '' },
})

const screeningMeta = reactive({ job: null, standard: null })

function normalizeScreeningResult(row) {
  const application = row?.application || {}
  const candidate = row?.candidate || application.candidate || {}
  return {
    rank: Number.isFinite(Number(row?.rank)) && row?.rank !== null ? Number(row.rank) : null,
    application: { ...application, candidate },
    candidate,
    resume: row?.resume || row?.current_resume || null,
    structure: row?.structure || row?.structured_resume || null,
    assessment: row?.assessment || null,
    aiState: row?.ai_state || row?.aiState || (row?.assessment ? 'scored' : row?.resume ? 'unscored' : 'no_resume'),
    hrDecision: row?.hr_decision || row?.hrDecision || null,
    notification: row?.notification || { status: 'not_requested' },
  }
}

function parseScreeningPayload(payload) {
  screeningMeta.job = payload?.job || null
  screeningMeta.standard = payload?.standard || null
  return listItems(payload).map(normalizeScreeningResult)
}

const resourceDefinitions = [
  ['runs', '任务运行', () => 'recruitment/workflow-runs/'],
  ['campaigns', '主动寻访', () => 'recruitment/search-campaigns/'],
  ['attentions', '人工事项', () => 'recruitment/human-attentions/'],
  ['screening', '候选排名', (jobId) => `recruitment/screening-results/?job=${jobId}`, parseScreeningPayload],
]

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'needs_action', label: '需要处理' },
  { value: 'in_progress', label: '执行中' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败 / 已取消' },
  { value: 'archived', label: '已删除任务' },
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
  const wantsArchived = statusFilter.value === 'archived'
  if (Boolean(item.automation_plan_archived_at) !== wantsArchived) return false
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
  if (group === 'archived') return true
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

const screeningResults = computed(() => resources.screening.items)
const screeningApplications = computed(() => screeningResults.value.map((row) => row.application))
const screeningResumeCount = computed(() => screeningResults.value.filter((row) => row.resume).length)

const legacyContext = computed(() => ({
  account: String(route.query.account || ''),
  application: String(route.query.application || ''),
  candidate: String(route.query.candidate || ''),
  filter: String(route.query.filter || ''),
}))

const hasLegacyContext = computed(() => Object.values(legacyContext.value).some(Boolean) && !route.query.resume)

function matchesLegacyCandidateFilter(row, filter) {
  if (filter === 'pending_parse') return Boolean(row.resume && !row.structure)
  if (filter === 'pending_hr_review') return row.assessment?.recommendation === 'review'
  if (filter === 'recommended_advance') return row.assessment?.recommendation === 'advance'
  return true
}

function matchesCandidateFilter(row) {
  if (candidateFilters.stage !== 'all' && row.application?.stage !== candidateFilters.stage) return false
  if (candidateFilters.ai !== 'all') {
    if (candidateFilters.ai === 'unscored') {
      if (row.aiState === 'scored' && row.assessment) return false
    } else if (row.assessment?.recommendation !== candidateFilters.ai) return false
  }
  if (candidateFilters.resume !== 'all') {
    const resumeState = !row.resume ? 'missing' : row.structure ? 'ready' : 'processing'
    if (resumeState !== candidateFilters.resume) return false
  }
  if (candidateFilters.hr !== 'all') {
    if (candidateFilters.hr === 'pending' ? Boolean(row.hrDecision) : row.hrDecision?.decision !== candidateFilters.hr) return false
  }
  if (candidateFilters.notification !== 'all' && (row.notification?.status || 'not_requested') !== candidateFilters.notification) return false
  return true
}

const candidateResults = computed(() => screeningResults.value.flatMap((row) => {
  const focus = legacyContext.value
  if (!route.query.resume && focus.application && String(row.application.id) !== focus.application) return []
  if (focus.candidate && String(row.candidate?.id || '') !== focus.candidate) return []
  if (focus.filter && focus.filter !== 'pending_standard_review' && !matchesLegacyCandidateFilter(row, focus.filter)) return []
  return matchesCandidateFilter(row) ? [row] : []
}))

const candidatePageCount = computed(() => Math.max(1, Math.ceil(candidateResults.value.length / candidatePageSize.value)))
const candidatePaginationItems = computed(() => {
  const total = candidatePageCount.value
  const current = candidatePage.value
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1)
  if (current <= 4) return [1, 2, 3, 4, 5, 'ellipsis-end', total]
  if (current >= total - 3) return [1, 'ellipsis-start', total - 4, total - 3, total - 2, total - 1, total]
  return [1, 'ellipsis-start', current - 1, current, current + 1, 'ellipsis-end', total]
})
const displayedCandidateResults = computed(() => {
  const start = (candidatePage.value - 1) * candidatePageSize.value
  return candidateResults.value.slice(start, start + candidatePageSize.value)
})

const candidateStageOptions = computed(() => [
  { value: 'all', label: '全部阶段' },
  ...stageColumns.map((stage) => ({ value: stage.key, label: stage.label })),
])
const candidateAiOptions = [
  { value: 'all', label: '全部建议' },
  { value: 'advance', label: '建议通过' },
  { value: 'review', label: '建议复核' },
  { value: 'hold', label: '建议未通过' },
  { value: 'unscored', label: '未评分 / 处理中' },
]
const candidateResumeOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'ready', label: '已解析' },
  { value: 'processing', label: '处理中' },
  { value: 'missing', label: '暂无简历' },
]
const candidateHrOptions = [
  { value: 'all', label: '全部结论' },
  { value: 'pass', label: '已通过' },
  { value: 'fail', label: '未通过' },
  { value: 'pending', label: '待确认' },
]
const candidateNotificationOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'not_requested', label: '未通知' },
  { value: 'queued', label: '已排队' },
  { value: 'running', label: '执行中' },
  { value: 'waiting_human', label: '等待人工' },
  { value: 'succeeded', label: '已发送' },
  { value: 'failed', label: '失败' },
]

function clearCandidateFilters() {
  Object.assign(candidateFilters, { stage: 'all', ai: 'all', resume: 'all', hr: 'all', notification: 'all' })
}

watch(
  () => [candidateFilters.stage, candidateFilters.ai, candidateFilters.resume, candidateFilters.hr, candidateFilters.notification, candidatePageSize.value],
  () => { candidatePage.value = 1 },
)

const selectedCandidateRows = computed(() => {
  const selected = new Set(selectedApplicationIds.value.map(String))
  return screeningResults.value.filter((row) => selected.has(String(row.application.id)))
})
const allVisibleSelected = computed(() => displayedCandidateResults.value.length > 0
  && displayedCandidateResults.value.every((row) => selectedApplicationIds.value.includes(String(row.application.id))))
const selectedDetailRow = computed(() => {
  const applicationId = String(route.query.application || '')
  if (!applicationId) return null
  const row = screeningResults.value.find((item) => String(item.application.id) === applicationId)
  if (!row?.resume) return null
  const resumeId = String(route.query.resume || '')
  return !resumeId || String(row.resume.id) === resumeId ? row : null
})

const activeRun = computed(() => jobRuns.value.find((run) => String(run.id) === runPanelId.value) || null)

const stageProgress = computed(() => {
  const total = screeningApplications.value.length
  const groups = [
    { key: 'new', label: '新候选人', stages: ['new'] },
    { key: 'communicated', label: '已沟通', stages: ['to_screen', 'communicating'] },
    { key: 'awaiting_interview', label: '待面试', stages: ['interviewing'] },
    { key: 'interviewed', label: '已面试', stages: ['to_offer'] },
    { key: 'hired', label: '已录用', stages: ['hired'] },
    { key: 'closed', label: '已关闭', stages: ['rejected'] },
  ]
  return groups.map((stage, index) => {
    const count = screeningApplications.value.filter((application) => stage.stages.includes(application.stage)).length
    return {
      ...stage,
      count,
      index,
      percentage: total ? Math.round(count / total * 100) : 0,
    }
  })
})
const activePipelineCount = computed(() => screeningApplications.value.filter((application) => !['hired', 'rejected'].includes(application.stage)).length)
const hiredCount = computed(() => screeningApplications.value.filter((application) => application.stage === 'hired').length)
const hiringCompletion = computed(() => {
  const target = Number(currentJob.value?.headcount || 0)
  return target ? Math.min(100, Math.round(hiredCount.value / target * 100)) : 0
})
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
  { key: 'candidates', label: '候选人与简历', count: screeningResults.value.length },
  { key: 'pipeline', label: '招聘进度', count: screeningResults.value.length },
])

const notificationSummary = computed(() => {
  const counts = { pending: 0, queued: 0, running: 0, waiting_human: 0, succeeded: 0, failed: 0, cancelled: 0, uncertain: 0 }
  for (const row of screeningResults.value) {
    const status = row.notification?.status || 'not_requested'
    if (isNotificationUncertain(row.notification)) counts.uncertain += 1
    else if (Object.hasOwn(counts, status)) counts[status] += 1
  }
  return counts
})
const hasNotificationActivity = computed(() => Object.values(notificationSummary.value).some(Boolean))

function resetResources() {
  for (const resource of Object.values(resources)) {
    resource.items = []
    resource.loading = false
    resource.loaded = false
    resource.error = ''
  }
  screeningMeta.job = null
  screeningMeta.standard = null
}

async function loadResults({ reset = false } = {}) {
  const jobId = currentJobId.value
  if (!jobId) return
  const sequence = ++requestSequence
  if (reset) resetResources()

  await Promise.all(resourceDefinitions.map(async ([key, , makePath, parsePayload]) => {
    const resource = resources[key]
    resource.loading = true
    resource.error = ''
    try {
      const payload = await api(makePath(jobId))
      if (sequence !== requestSequence || currentJobId.value !== jobId) return
      const items = parsePayload ? parsePayload(payload) : listItems(payload)
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

  if (sequence === requestSequence) {
    const available = new Set(screeningResults.value.map((row) => String(row.application.id)))
    selectedApplicationIds.value = selectedApplicationIds.value.filter((id) => available.has(String(id)))
  }

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
  return `${Number(assessment.total_score || 0).toFixed(0)} 分`
}

function aiRecommendationLabel(row) {
  if (row.aiState !== 'scored' || !row.assessment) {
    return {
      processing: 'AI 处理中', failed: 'AI 评分失败', no_resume: '暂无简历',
      standard_missing: '待发布岗位标准', unscored: 'AI 尚未评分',
    }[row.aiState] || 'AI 尚未评分'
  }
  return {
    advance: 'AI 建议通过', review: 'AI 建议人工复核', hold: 'AI 建议未通过',
  }[row.assessment.recommendation] || 'AI 建议人工复核'
}

function aiRecommendationTone(row) {
  if (row.aiState !== 'scored' || !row.assessment) return 'neutral'
  return { advance: 'success', review: 'warning', hold: 'danger' }[row.assessment.recommendation] || 'warning'
}

function resumeStatusLabel(row) {
  if (!row.resume) return '等待候选人提供'
  if (row.aiState === 'processing') return '正在解析 / 评分'
  if (row.aiState === 'failed') return '智能处理失败'
  if (!row.structure) return '等待结构化'
  if (!row.assessment) return screeningMeta.standard ? '等待评分' : '等待岗位标准'
  return '原件与报告已就绪'
}

function hrDecisionLabel(decision) {
  if (!decision) return 'HR 待确认'
  return decision.decision === 'pass' ? 'HR 已确认通过' : 'HR 已确认未通过'
}

function notificationLabel(notification) {
  if (isNotificationUncertain(notification)) return '发送结果待人工确认'
  return {
    not_requested: '未创建通知', draft: '等待审批', pending: '已加入队列', queued: '已排队', running: '执行中',
    waiting_human: '等待人工介入', succeeded: '通知已发送', failed: '通知失败', cancelled: '通知已取消',
  }[notification?.status || 'not_requested'] || '通知状态未知'
}

function isNotificationUncertain(notification) {
  return String(notification?.error_code || '').toLowerCase().includes('uncertain')
}

function notificationTone(notification) {
  if (isNotificationUncertain(notification)) return 'warning'
  return {
    succeeded: 'success', failed: 'danger', cancelled: 'neutral', waiting_human: 'warning',
    pending: 'active', queued: 'active', running: 'active', draft: 'warning',
  }[notification?.status] || 'neutral'
}

function isApplicationSelected(applicationId) {
  return selectedApplicationIds.value.includes(String(applicationId))
}

function toggleApplication(applicationId, checked) {
  const id = String(applicationId)
  const next = new Set(selectedApplicationIds.value)
  if (checked) next.add(id)
  else next.delete(id)
  selectedApplicationIds.value = [...next]
}

function toggleVisibleCandidates(checked) {
  const next = new Set(selectedApplicationIds.value)
  for (const row of displayedCandidateResults.value) {
    const id = String(row.application.id)
    if (checked) next.add(id)
    else next.delete(id)
  }
  selectedApplicationIds.value = [...next]
}

function openCandidateDetail(row, event) {
  if (!row.resume) return
  detailReturnFocus = event?.currentTarget || document.activeElement
  detailError.value = ''
  router.push({
    name: route.name,
    query: {
      ...route.query,
      view: 'candidates',
      application: String(row.application.id),
      resume: String(row.resume.id),
    },
  }).catch(() => {})
}

async function closeCandidateDetail() {
  const query = { ...route.query }
  delete query.application
  delete query.resume
  await router.replace({ name: route.name, query }).catch(() => {})
  await nextTick()
  detailReturnFocus?.focus?.()
  detailReturnFocus = null
}

async function loadDetailIntelligence(row) {
  const sequence = ++detailSequence
  detailStructure.value = row?.structure || null
  detailAssessment.value = row?.assessment || null
  detailAssessments.value = row?.assessment ? [row.assessment] : []
  detailTasks.value = []
  detailLoading.value = Boolean(row?.resume)
  detailError.value = ''
  if (!row?.resume || !currentJobId.value) {
    detailLoading.value = false
    return
  }
  const resumeId = String(row.resume.id)
  const [structureResult, assessmentResult, taskResult] = await Promise.allSettled([
    api(`recruitment/structured-resumes/?resume=${encodeURIComponent(resumeId)}`),
    api(`recruitment/resume-assessments/?resume=${encodeURIComponent(resumeId)}`),
    api(`recruitment/ai-tasks/?resume=${encodeURIComponent(resumeId)}`),
  ])
  if (sequence !== detailSequence || selectedDetailRow.value !== row) return

  if (structureResult.status === 'fulfilled') {
    const structures = listItems(structureResult.value)
      .filter((item) => String(item.resume) === resumeId)
      .sort((a, b) => Number(b.version || 0) - Number(a.version || 0) || Number(b.id || 0) - Number(a.id || 0))
    detailStructure.value = structures.find((item) => String(item.id) === String(row.structure?.id || '')) || structures[0] || null
  }
  if (assessmentResult.status === 'fulfilled') {
    const assessments = listItems(assessmentResult.value)
      .filter((item) => !item.resume || String(item.resume) === resumeId)
      .sort((a, b) => Number(b.version || 0) - Number(a.version || 0) || String(b.created_at || '').localeCompare(String(a.created_at || '')))
    detailAssessments.value = assessments
    const summaryAssessmentId = String(row.assessment?.id || '')
    const currentStandardId = String(screeningMeta.standard?.id || '')
    const currentStructureId = String(detailStructure.value?.id || row.structure?.id || '')
    detailAssessment.value = assessments.find((item) => String(item.id) === summaryAssessmentId)
      || assessments.find((item) => (!currentStandardId || String(item.standard) === currentStandardId)
        && (!currentStructureId || String(item.structured_resume) === currentStructureId))
      || null
  }
  if (taskResult.status === 'fulfilled') {
    detailTasks.value = listItems(taskResult.value).filter((item) => !item.resume || String(item.resume) === resumeId)
  }
  const failedLabels = [
    [structureResult, '结构化信息'], [assessmentResult, '完整分析报告'], [taskResult, '处理记录'],
  ].filter(([result]) => result.status === 'rejected').map(([, label]) => label)
  if (failedLabels.length) detailError.value = `${failedLabels.join('、')}暂未加载；排名摘要和原始简历仍可查看。`
  detailLoading.value = false
}

async function runResumeAction(row, action) {
  if (!row?.resume) return
  detailError.value = ''
  try {
    if (action === 'retry-structure') {
      await api(`recruitment/resumes/${row.resume.id}/retry-structure/`, { method: 'POST', body: JSON.stringify({ request_id: createRequestId() }) })
    } else if (action === 'rescore' && row.assessment) {
      await api(`recruitment/resume-assessments/${row.assessment.id}/rescore/`, { method: 'POST', body: JSON.stringify({ request_id: createRequestId() }) })
    } else {
      await api('recruitment/resume-assessments/score/', {
        method: 'POST',
        body: JSON.stringify({ request_id: createRequestId(), job: Number(currentJobId.value), resume_ids: [row.resume.id] }),
      })
    }
    operationNotice.value = { tone: 'success', message: '处理任务已加入队列，稍后刷新即可查看最新结果。' }
    await loadResults()
  } catch (error) {
    detailError.value = error.message || '简历处理任务创建失败'
  }
}

function selectedCandidateSnapshots() {
  return selectedCandidateRows.value.map((row) => ({
    applicationId: row.application.id,
    name: row.candidate?.name || '未命名候选人',
    title: row.candidate?.current_title || '',
    stage: row.application.stage,
    stageLabel: row.application.stage_label || statusLabel(row.application.stage),
    notificationStatus: row.notification?.status || 'not_requested',
    notificationErrorCode: row.notification?.error_code || '',
  }))
}

function openDecisionDrawer(mode, event) {
  if (!selectedCandidateRows.value.length) return
  detailReturnFocus = event?.currentTarget || document.activeElement
  decisionDrawerMode.value = mode
  decisionBusy.value = false
  decisionSaved.value = false
  decisionError.value = ''
  notificationError.value = ''
  decisionBatchId.value = ''
  decisionRequest.id = ''
  decisionRequest.signature = ''
  notificationRequest.id = ''
  notificationRequest.signature = ''
  notificationRequest.approvalId = ''
}

async function closeDecisionDrawer(force = false) {
  if (decisionBusy.value && !force) return
  decisionDrawerMode.value = ''
  await nextTick()
  detailReturnFocus?.focus?.()
  detailReturnFocus = null
}

function applyDecisionResult(result) {
  const byApplication = new Map((result?.decisions || []).map((item) => [String(item.application), item]))
  for (const row of screeningResults.value) {
    const decision = byApplication.get(String(row.application.id))
    if (decision) row.hrDecision = { ...decision, batch_id: result.decision_batch_id }
  }
}

async function submitScreeningDecision({ notify, reason, message }) {
  if (!decisionDrawerMode.value || !selectedCandidateRows.value.length || decisionBusy.value) return
  decisionBusy.value = true
  decisionError.value = ''
  notificationError.value = ''
  const applicationIds = selectedCandidateRows.value.map((row) => Number(row.application.id))
  const decisionSignature = JSON.stringify({ job: Number(currentJobId.value), applicationIds, decision: decisionDrawerMode.value, reason })
  try {
    if (!decisionSaved.value || !decisionBatchId.value) {
      if (decisionRequest.signature !== decisionSignature) {
        decisionRequest.id = createRequestId()
        decisionRequest.signature = decisionSignature
      }
      const result = await api('recruitment/screening-decisions/bulk/', {
        method: 'POST',
        body: JSON.stringify({
          request_id: decisionRequest.id,
          job: Number(currentJobId.value),
          application_ids: applicationIds,
          decision: decisionDrawerMode.value,
          reason,
        }),
      })
      decisionBatchId.value = String(result.decision_batch_id || result.id || '')
      decisionSaved.value = true
      applyDecisionResult(result)
    }

    if (!notify || decisionDrawerMode.value !== 'fail') {
      operationNotice.value = { tone: 'success', message: `已保存 ${applicationIds.length} 位候选人的 HR ${decisionDrawerMode.value === 'pass' ? '通过' : '未通过'}结论；招聘阶段未自动改变。` }
      selectedApplicationIds.value = selectedApplicationIds.value.filter((id) => !applicationIds.map(String).includes(String(id)))
      await closeDecisionDrawer(true)
      return
    }

    const notificationSignature = JSON.stringify({ decisionBatchId: decisionBatchId.value, message })
    if (notificationRequest.signature !== notificationSignature) {
      notificationRequest.id = createRequestId()
      notificationRequest.signature = notificationSignature
      notificationRequest.approvalId = ''
    }
    if (!notificationRequest.approvalId) {
      const prepared = await api('recruitment/rejection-notices/prepare/', {
        method: 'POST',
        body: JSON.stringify({ request_id: notificationRequest.id, decision_batch_id: decisionBatchId.value, message }),
      })
      notificationRequest.approvalId = String(prepared.approval_id || prepared.id || '')
    }
    await api(`recruitment/automation-approvals/${encodeURIComponent(notificationRequest.approvalId)}/approve/`, { method: 'POST' })
    for (const row of selectedCandidateRows.value) row.notification = { ...row.notification, status: 'pending' }
    operationNotice.value = { tone: 'success', message: `已保存 ${applicationIds.length} 位候选人的 HR 未通过结论，并加入安全通知队列；这不代表消息已经发送。` }
    selectedApplicationIds.value = selectedApplicationIds.value.filter((id) => !applicationIds.map(String).includes(String(id)))
    await closeDecisionDrawer(true)
  } catch (error) {
    if (decisionSaved.value) notificationError.value = error.message || '通知审批或队列创建失败'
    else decisionError.value = error.message || 'HR 结论保存失败'
  } finally {
    decisionBusy.value = false
  }
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
  for (const key of ['account', 'application', 'candidate', 'filter', 'resume']) delete query[key]
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
  for (const key of ['run', 'account', 'application', 'candidate', 'filter', 'resume']) delete query[key]
  selectedApplicationIds.value = []
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
    route.query.account, route.query.application, route.query.candidate, route.query.filter, route.query.resume,
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
watch(selectedDetailRow, (row) => loadDetailIntelligence(row))

watch(
  () => currentJobId.value,
  async (jobId) => {
    requestSequence += 1
    detailSequence += 1
    statusFilter.value = 'all'
    clearCandidateFilters()
    selectedApplicationIds.value = []
    decisionDrawerMode.value = ''
    operationNotice.value = null
    detailReturnFocus = null
    detailStructure.value = null
    detailAssessment.value = null
    detailAssessments.value = []
    detailTasks.value = []
    detailLoading.value = false
    if (!jobId) {
      selectedRunId.value = ''
      resetResources()
      return
    }
    await loadResults({ reset: true })
  },
  { immediate: true },
)

let resultsPollTimer = null
onMounted(() => {
  if (props.autoRefreshMs > 0) {
    resultsPollTimer = globalThis.setInterval(() => {
      if (!isRefreshing.value) loadResults()
    }, props.autoRefreshMs)
  }
})

onUnmounted(() => {
  if (resultsPollTimer) globalThis.clearInterval(resultsPollTimer)
  resultsPollTimer = null
})
</script>

<template>
  <div :class="['page-stack', 'results-center', { 'is-embedded': embedded }]">
    <header v-if="!embedded" class="page-hero page-hero--compact results-hero">
      <div>
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
        <section v-if="!embedded" class="results-context" aria-label="当前结果范围">
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
          <article><span>候选人</span><strong>{{ resources.screening.error ? '—' : screeningResults.length }}</strong><small>{{ resources.screening.error ? '排名数据暂未加载' : `${screeningResumeCount} 人已有当前简历` }}</small></article>
        </section>

        <div v-if="resourceErrors.length && !allFailed" class="results-data-warning" role="status" data-test="partial-error">
          <AppIcon name="alert-circle" :size="16" />
          <span><strong>{{ resourceErrors.length }} 项数据暂未加载：</strong>{{ resourceErrors.map((item) => item.label).join('、') }}。已加载的结果仍可查看。</span>
          <button type="button" :disabled="isRefreshing" @click="loadResults()">重试</button>
        </div>
        <div v-if="operationNotice" :class="['results-operation-notice', `is-${operationNotice.tone}`]" role="status" data-test="operation-notice">
          <AppIcon :name="operationNotice.tone === 'success' ? 'check-circle' : 'alert-circle'" :size="16" />
          <span>{{ operationNotice.message }}</span>
          <button type="button" aria-label="关闭提示" @click="operationNotice = null">×</button>
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

        <section v-if="activeView === 'attention'" class="results-panel results-panel--attention" data-test="attention-view">
          <p v-if="resources.attentions.error" class="results-inline-error">人工事项加载失败：{{ resources.attentions.error }}</p>
          <p v-if="attentionActionError" class="results-inline-error" data-test="attention-action-error">{{ attentionActionError }}</p>
          <div class="attention-list">
            <div class="attention-list__head" aria-hidden="true">
              <span>待处理事项</span><span>类别</span><span>关联账号 / 候选人</span><span>上下文摘要</span><span>创建时间</span><span>状态</span><span>操作</span>
            </div>
            <article v-for="item in filteredAttentions" :key="item.id" :class="`is-${statusTone(item.status)}`">
              <strong>{{ item.title }}</strong>
              <span class="attention-type">{{ item.attention_type_label || '人工事项' }}</span>
              <span class="attention-object">{{ item.candidate_name || item.account_name || '当前岗位' }}</span>
              <p>{{ detailText(item.detail) }}</p>
              <time>{{ formatDateTime(item.created_at) }}</time>
              <span :class="['candidate-status', `is-${statusTone(item.status)}`]">{{ item.status_label || statusLabel(item.status) }}</span>
              <div class="attention-actions">
                <RouterLink :to="{ name: 'recruitment-candidates', query: { job: currentJobId, application: item.application || undefined } }">查看上下文 <AppIcon name="chevron-right" :size="11" /></RouterLink>
                <button v-if="item.status === 'open'" type="button" :disabled="Boolean(attentionActionId)" :data-test="`resolve-attention-${item.id}`" @click="resolveAttention(item)">{{ attentionActionId === String(item.id) ? '处理中…' : '标记已处理' }}</button>
              </div>
            </article>
            <div v-if="!filteredAttentions.length && resources.attentions.loading" class="results-table-empty">正在加载人工事项…</div>
            <div v-else-if="!filteredAttentions.length" class="results-table-empty"><strong>当前范围没有需要人工处理的事项</strong><span>可切换状态查看已处理记录。</span></div>
            <footer class="results-table-footer">共 {{ filteredAttentions.length }} 项</footer>
          </div>
        </section>

        <section v-else-if="activeView === 'tasks'" class="results-task-grid" data-test="tasks-view">
          <article class="results-subpanel">
            <header><h3>自动化运行</h3><span>{{ filteredRuns.filter((run) => ['queued', 'running', 'waiting_human', 'paused'].includes(run.status)).length }} 个运行中</span></header>
            <p v-if="resources.runs.error" class="results-inline-error">任务运行加载失败：{{ resources.runs.error }}</p>
            <p v-if="runActionError" class="results-inline-error" data-test="run-action-error">{{ runActionError }}</p>
            <div class="run-list results-data-table">
              <div class="results-data-table__head"><span>运行名称</span><span>状态</span><span>步骤</span><span>目标候选数</span><span>进度</span><span>开始时间</span><span>操作</span></div>
              <template v-if="filteredRuns.length">
              <article v-for="run in filteredRuns" :key="run.id" class="results-data-table__row">
                <div class="results-table-name"><strong>{{ run.template_name || '自动化任务' }}</strong><small>#{{ String(run.id).slice(0, 8) }}</small></div>
                <span :class="['candidate-status', `is-${statusTone(run.status)}`]">{{ statusLabel(run.status) }}</span>
                <span>{{ (run.node_runs || []).filter((node) => node.status === 'succeeded').length }}/{{ (run.node_runs || []).length }}</span>
                <span>{{ run.target_candidate_count ?? run.target_count ?? '—' }}</span>
                <div class="results-table-progress"><div class="results-progress"><i :style="{ width: `${runProgress(run)}%` }"></i></div><small>{{ runProgress(run) }}%</small></div>
                <time>{{ formatDateTime(run.started_at || run.created_at || run.updated_at) }}</time>
                <span class="run-list__actions"><RouterLink v-if="run.automation_plan" :to="{ name: 'recruitment-task-detail', params: { planId: run.automation_plan }, query: { job: currentJobId, run: run.id, view: 'tasks', status: run.automation_plan_archived_at ? 'archived' : undefined } }">查看任务</RouterLink><button type="button" :aria-expanded="expandedRunId === String(run.id)" @click="toggleRunDetail(run.id)">查看运行详情</button><button type="button" :data-test="`manage-run-${run.id}`" @click="openRunPanel(run)">处理运行</button></span>
                <p v-if="run.error_message" class="run-error">{{ run.error_message }}</p>
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
              </template>
              <div v-else-if="resources.runs.loading" class="results-table-empty">正在恢复任务运行…</div>
              <div v-else class="results-table-empty"><strong>当前筛选下没有任务运行</strong><span>返回作业台发起任务后，运行记录会出现在这里。</span></div>
              <footer class="results-table-footer">共 {{ filteredRuns.length }} 项</footer>
            </div>
          </article>

          <article class="results-subpanel">
            <header><h3>主动寻访结果</h3><span>{{ filteredCampaigns.filter((campaign) => ['queued', 'running', 'waiting_human', 'paused'].includes(campaign.status)).length }} 个运行中，{{ filteredCampaigns.filter((campaign) => campaign.status === 'succeeded').length }} 个已完成</span></header>
            <p v-if="resources.campaigns.error" class="results-inline-error">主动寻访加载失败：{{ resources.campaigns.error }}</p>
            <div class="campaign-list results-data-table">
              <div class="results-data-table__head results-data-table__head--campaign"><span>运行名称</span><span>状态</span><span>已获取 / 目标</span><span>回复率</span><span>开始时间</span><span>操作</span></div>
              <template v-if="filteredCampaigns.length">
                <article v-for="campaign in filteredCampaigns" :key="campaign.id" class="results-data-table__row results-data-table__row--campaign">
                  <div class="results-table-name"><strong>{{ campaign.name }}</strong><small>{{ campaign.source === 'recommend' ? '推荐人才' : campaign.source === 'deep_search' ? '深度搜索' : '关键词搜索' }}</small></div>
                  <span :class="['candidate-status', `is-${statusTone(campaign.status)}`]">{{ statusLabel(campaign.status) }}</span>
                  <span>{{ campaign.pulled_resume_count }}/{{ campaign.target_resume_count }}</span>
                  <div class="results-table-progress"><div class="results-progress"><i :style="{ width: `${campaignProgress(campaign)}%` }"></i></div><small>{{ campaignProgress(campaign) }}%</small></div>
                  <time>{{ formatDateTime(campaign.started_at || campaign.created_at || campaign.updated_at) }}</time>
                  <RouterLink :to="{ name: 'recruitment-workbench', query: { job: currentJobId, campaign: campaign.id } }">查看运行并处理</RouterLink>
                  <p v-if="campaign.error_message || campaign.stop_reason" :class="{ 'run-error': campaign.error_message }">{{ campaign.error_message || `停止原因：${campaign.stop_reason}` }}</p>
                </article>
              </template>
              <div v-else-if="resources.campaigns.loading" class="results-table-empty">正在加载主动寻访结果…</div>
              <div v-else class="results-table-empty"><strong>当前筛选下没有主动寻访</strong><span>被动消息方案仍可只产生任务运行和人工事项。</span></div>
              <footer class="results-table-footer">共 {{ filteredCampaigns.length }} 项</footer>
            </div>
          </article>
        </section>

        <section v-else-if="activeView === 'candidates'" class="results-panel results-panel--candidates" data-test="candidates-view">
          <p v-if="resources.screening.error" class="results-inline-error">候选排名加载失败：{{ resources.screening.error }}</p>

          <div class="candidate-filter-bar" aria-label="候选人筛选">
            <label><span>招聘阶段</span><select v-model="candidateFilters.stage" data-test="candidate-filter-stage"><option v-for="option in candidateStageOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label><span>AI 初筛建议</span><select v-model="candidateFilters.ai" data-test="candidate-filter-ai"><option v-for="option in candidateAiOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label><span>简历状态</span><select v-model="candidateFilters.resume" data-test="candidate-filter-resume"><option v-for="option in candidateResumeOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label><span>HR 结论</span><select v-model="candidateFilters.hr" data-test="candidate-filter-hr"><option v-for="option in candidateHrOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <label><span>通知状态</span><select v-model="candidateFilters.notification" data-test="candidate-filter-notification"><option v-for="option in candidateNotificationOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
            <button type="button" data-test="candidate-filter-clear" @click="clearCandidateFilters">清除筛选</button>
          </div>

          <section v-if="hasNotificationActivity" class="notification-summary" aria-label="未通过通知执行汇总" data-test="notification-summary">
            <strong>通知执行汇总</strong>
            <span v-if="notificationSummary.pending">已加入队列 {{ notificationSummary.pending }}</span>
            <span v-if="notificationSummary.queued">已排队 {{ notificationSummary.queued }}</span>
            <span v-if="notificationSummary.running">执行中 {{ notificationSummary.running }}</span>
            <span v-if="notificationSummary.waiting_human">等待人工 {{ notificationSummary.waiting_human }}</span>
            <span v-if="notificationSummary.succeeded">已发送 {{ notificationSummary.succeeded }}</span>
            <span v-if="notificationSummary.failed">失败 {{ notificationSummary.failed }}</span>
            <span v-if="notificationSummary.cancelled">已取消 {{ notificationSummary.cancelled }}</span>
            <span v-if="notificationSummary.uncertain">结果待确认 {{ notificationSummary.uncertain }}</span>
            <small>“已加入队列”不代表已发送；请以每位候选人的最终状态为准。</small>
          </section>

          <div v-if="candidateResults.length" class="candidate-ranking-scroll">
            <table class="candidate-ranking-table">
              <caption class="sr-only">{{ currentJob.title }}候选排名，AI 建议、HR 结论、招聘阶段与通知状态分列展示</caption>
              <thead>
                <tr>
                  <th scope="col" class="candidate-select-cell"><label><span class="sr-only">选择当前页的全部候选人</span><input type="checkbox" :checked="allVisibleSelected" :aria-label="`选择当前页的 ${displayedCandidateResults.length} 位候选人`" data-test="select-visible-candidates" @change="toggleVisibleCandidates($event.target.checked)" /></label></th>
                  <th scope="col" aria-sort="descending">排名</th>
                  <th scope="col">候选人</th>
                  <th scope="col">招聘阶段</th>
                  <th scope="col">AI 初筛建议</th>
                  <th scope="col">得分</th>
                  <th scope="col">简历状态</th>
                  <th scope="col">HR 结论</th>
                  <th scope="col">通知状态</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in displayedCandidateResults" :key="row.application.id" :data-application-id="row.application.id" :class="{ 'is-selected': isApplicationSelected(row.application.id) }">
                  <td class="candidate-select-cell"><label><span class="sr-only">选择候选人 {{ row.candidate?.name || '未命名候选人' }}</span><input type="checkbox" :checked="isApplicationSelected(row.application.id)" :aria-label="`选择候选人 ${row.candidate?.name || '未命名候选人'}`" @change="toggleApplication(row.application.id, $event.target.checked)" /></label></td>
                  <td data-label="排名"><strong :class="['candidate-rank', row.rank && row.rank <= 3 ? `is-top-${row.rank}` : '']"><AppIcon v-if="row.rank && row.rank <= 3" name="crown" :size="13" />{{ row.rank ?? '—' }}</strong></td>
                  <td data-label="候选人"><button class="candidate-name-button" type="button" :disabled="!row.resume" :aria-label="row.resume ? `查看 ${row.candidate?.name || '候选人'} 的简历与分析报告` : `${row.candidate?.name || '候选人'} 暂无简历`" @click="openCandidateDetail(row, $event)"><strong>{{ row.candidate?.name || '未命名候选人' }}</strong><small>{{ row.candidate?.current_title || '当前岗位未填写' }} · {{ row.candidate?.current_city || '城市未填写' }}</small></button></td>
                  <td data-label="招聘阶段"><span class="candidate-status is-neutral">{{ row.application.stage_label || statusLabel(row.application.stage) }}</span></td>
                  <td data-label="AI 初筛建议"><span :class="['candidate-status', `is-${aiRecommendationTone(row)}`]">{{ aiRecommendationLabel(row) }}</span></td>
                  <td data-label="得分"><div class="candidate-score" :class="{ 'has-score': row.assessment }" :title="row.assessment ? `置信度 ${Math.round(Number(row.assessment.confidence || 0) * 100)}%` : '尚未评分，不作为 0 分'"><strong>{{ scoreText(row.assessment) }}</strong><small class="sr-only">{{ row.assessment ? `置信度 ${Math.round(Number(row.assessment.confidence || 0) * 100)}%` : '不作为 0 分' }}</small></div></td>
                  <td data-label="简历状态"><div class="candidate-resume"><strong>{{ row.resume?.original_name || '暂无当前简历' }}</strong><small>{{ resumeStatusLabel(row) }}</small></div></td>
                  <td data-label="HR 结论"><span :class="['candidate-status', row.hrDecision?.decision === 'pass' ? 'is-success' : row.hrDecision?.decision === 'fail' ? 'is-danger' : 'is-neutral']" :title="row.hrDecision?.reason || ''">{{ hrDecisionLabel(row.hrDecision) }}</span></td>
                  <td data-label="通知状态"><div class="candidate-notification"><span :class="['candidate-status', `is-${notificationTone(row.notification)}`]">{{ notificationLabel(row.notification) }}</span><small v-if="row.notification?.error_message">{{ row.notification.error_message }}</small></div></td>
                  <td class="candidate-action-cell"><button type="button" :disabled="!row.resume" :data-test="`view-candidate-${row.application.id}`" @click="openCandidateDetail(row, $event)">{{ row.resume ? '查看简历与报告' : '暂无简历' }}</button></td>
                </tr>
              </tbody>
            </table>
            <footer class="candidate-table-footer">
              <span>共 {{ candidateResults.length }} 项</span>
              <div><button type="button" :disabled="candidatePage === 1" aria-label="上一页" @click="candidatePage -= 1">‹</button><template v-for="item in candidatePaginationItems" :key="item"><span v-if="String(item).startsWith('ellipsis')">…</span><button v-else type="button" :class="{ active: candidatePage === item }" @click="candidatePage = item">{{ item }}</button></template><button type="button" :disabled="candidatePage === candidatePageCount" aria-label="下一页" @click="candidatePage += 1">›</button></div>
              <label><span class="sr-only">每页显示数量</span><select v-model.number="candidatePageSize"><option :value="10">10 条/页</option><option :value="20">20 条/页</option><option :value="50">50 条/页</option></select></label>
            </footer>
          </div>
          <div v-else-if="resources.screening.loading" class="results-local-loading">正在加载候选排名…</div>
          <div v-else-if="resources.screening.error" class="results-empty"><AppIcon name="alert-circle" :size="25" /><strong>候选排名暂时无法加载</strong><span>其他任务结果仍可查看；重试不会使用旧岗位数据覆盖当前页面。</span><button class="secondary-button" type="button" @click="loadResults()">重试候选排名</button></div>
          <div v-else-if="screeningResults.length" class="results-empty"><AppIcon name="filter" :size="25" /><strong>当前筛选下没有候选人</strong><span>可清除筛选查看完整排名；筛选不会清除已选择的人。</span><button class="secondary-button" type="button" @click="clearCandidateFilters">查看全部</button></div>
          <div v-else class="results-empty"><AppIcon name="users" :size="25" /><strong>该岗位还没有候选人结果</strong><span>返回作业台执行寻访，或在候选人页面导入已确认的人选。</span><RouterLink class="primary-button" to="/recruitment/workbench">返回招聘作业台</RouterLink></div>

          <div v-if="selectedCandidateRows.length" class="candidate-batch-bar" role="region" aria-label="候选人批量操作" data-test="candidate-batch-bar">
            <div><strong>已选择 {{ selectedCandidateRows.length }} 人</strong><button type="button" @click="selectedApplicationIds = []">清空选择</button></div>
            <span>AI 建议不会限制 HR 的人工判断。</span>
            <div><button class="secondary-button" type="button" data-test="bulk-pass" @click="openDecisionDrawer('pass', $event)">确认通过</button><button class="primary-button" type="button" data-test="bulk-fail" @click="openDecisionDrawer('fail', $event)">确认未通过</button></div>
          </div>
        </section>

        <section v-else class="results-panel results-panel--pipeline" data-test="pipeline-view">
          <p v-if="resources.screening.error" class="results-inline-error">招聘进度加载失败：{{ resources.screening.error }}</p>
          <template v-if="screeningResults.length">
            <h3 class="pipeline-section-title">招聘阶段分布</h3>
            <div class="stage-progress-list" aria-label="候选人阶段分布">
              <article v-for="stage in stageProgress" :key="stage.key" :class="`stage-tone-${stage.index % 5}`">
                <span>{{ stage.label }}</span>
                <strong>{{ stage.count }}</strong>
                <div><i :style="{ width: `${stage.percentage}%` }"></i></div>
                <small>{{ stage.percentage }}%</small>
              </article>
            </div>
            <h3 class="pipeline-section-title pipeline-section-title--summary">招聘目标概览</h3>
            <div class="pipeline-summary" aria-label="招聘目标概览">
              <article><span>岗位招聘目标</span><strong>{{ currentJob.headcount || '—' }}<small v-if="currentJob.headcount"> 人</small></strong></article>
              <article><span>已录用</span><strong>{{ hiredCount }}<small> 人</small></strong></article>
              <article><span>在招中</span><strong>{{ activePipelineCount }}<small> 人</small></strong></article>
              <article class="pipeline-summary__completion"><span>完成进度</span><strong>{{ currentJob.headcount ? `${hiringCompletion}%` : '未设置' }}</strong><div><i :style="{ width: `${hiringCompletion}%` }"></i></div></article>
              <RouterLink class="pipeline-entry" :to="{ name: 'recruitment-pipeline', query: { job: currentJobId } }">进入招聘流程</RouterLink>
            </div>
          </template>
          <div v-else-if="resources.screening.loading" class="results-local-loading">正在加载招聘进度…</div>
          <div v-else-if="resources.screening.error" class="results-empty"><AppIcon name="alert-circle" :size="25" /><strong>招聘进度暂时无法加载</strong><span>候选排名恢复后，阶段统计会同步更新。</span></div>
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
      <ResumeIntelligencePanel
        v-if="selectedDetailRow"
        :resume="selectedDetailRow.resume"
        :structure="detailStructure"
        :assessment="detailAssessment"
        :assessments="detailAssessments"
        :tasks="detailTasks"
        :loading="detailLoading"
        :context-error="detailError"
        @close="closeCandidateDetail"
        @retry-structure="runResumeAction(selectedDetailRow, 'retry-structure')"
        @score="runResumeAction(selectedDetailRow, 'score')"
        @rescore="runResumeAction(selectedDetailRow, 'rescore')"
      />
      <ScreeningDecisionDrawer
        v-if="decisionDrawerMode"
        :mode="decisionDrawerMode"
        :candidates="selectedCandidateSnapshots()"
        :job-title="currentJob.title"
        :account-name="currentJob.account_name || ''"
        :saving="decisionBusy"
        :decision-saved="decisionSaved"
        :decision-error="decisionError"
        :notification-error="notificationError"
        @close="closeDecisionDrawer()"
        @confirm="submitScreeningDecision"
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
  --results-color-surface-soft: #f8faf9;
  --results-color-surface-muted: #f1f5f9;
  --results-color-brand: #0f9f8f;
  --results-color-brand-dark: #087f73;
  --results-color-brand-soft: #eaf8f6;
  --results-color-brand-control: var(--results-color-surface);
  --results-color-brand-line: #9bd3cc;
  --results-color-warning: #d97706;
  --results-color-warning-text: #9a5b08;
  --results-color-warning-soft: #fff7e3;
  --results-color-warning-line: #f1dfb1;
  --results-color-danger: #dc4a4a;
  --results-color-danger-text: #b42332;
  --results-color-danger-soft: #fff0f2;
  --results-color-active: #155e75;
  --results-color-active-soft: #ecf8fc;
  --results-color-info: #6f91b5;
  --results-color-info-soft: #edf4fb;
  --results-color-sage: #739b7a;
  --results-color-sage-soft: #edf5ed;
  --results-color-stage-muted: #94a3b8;
  --results-space-1: clamp(.25rem, .2rem + .09cqi, .375rem);
  --results-space-2: clamp(.5rem, .25rem + .3cqi, .75rem);
  --results-space-3: clamp(.75rem, .4rem + .42cqi, 1rem);
  --results-space-4: clamp(1rem, .55rem + .55cqi, 1.375rem);
  --results-space-5: clamp(1.375rem, .75rem + .75cqi, 1.875rem);
  --results-space-6: clamp(1.75rem, 1rem + .9cqi, 2.375rem);
  --results-space-7: clamp(2.125rem, 1.25rem + 1.05cqi, 2.875rem);
  --results-radius-control: clamp(.5625rem, .48rem + .06cqi, .75rem);
  --results-radius-panel: clamp(.9375rem, .78rem + .12cqi, 1.25rem);
  --results-radius-status: 999px;
  --results-border-width: 1px;
  --results-active-border-width: 2px;
  --results-control-height: clamp(2.375rem, 1.25rem + 1.35cqi, 3.25rem);
  --results-compact-control-height: clamp(2.125rem, 1.25rem + 1.15cqi, 3rem);
  --results-touch-target: clamp(2.75rem, 1.5rem + 1.35cqi, 3.5rem);
  --results-row-min-height: clamp(4rem, 2.25rem + 2.1cqi, 5.25rem);
  --results-font-meta: clamp(.625rem, .12rem + .52cqi, .9375rem);
  --results-font-detail: clamp(.6875rem, .15rem + .62cqi, 1.0625rem);
  --results-font-control: clamp(.75rem, .15rem + .65cqi, 1.125rem);
  --results-font-body: clamp(.8125rem, .2rem + .65cqi, 1.125rem);
  --results-font-title: clamp(.9375rem, .25rem + .75cqi, 1.375rem);
  --results-font-metric: clamp(1.625rem, 1rem + .8cqi, 2.25rem);
  --results-font-campaign-metric: clamp(1.25rem, .55rem + .75cqi, 1.875rem);
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
  --results-filter-job-min: 14.375rem;
  --results-filter-run-min: 13.125rem;
  --results-filter-status-min: 10.625rem;
  --results-empty-copy-max: 26.25rem;
  --results-avatar-size: clamp(2rem, 1rem + 1.15cqi, 2.75rem);
  --results-candidate-name-min: 9.375rem;
  --results-candidate-stage-min: 5.625rem;
  --results-candidate-resume-min: 6.875rem;
  --results-candidate-score-min: 9.6875rem;
  --results-action-column: 1.5rem;
  --results-stage-label-width: 5.625rem;
  --results-stage-count-width: 1.875rem;
  --results-stage-card-min: 8.125rem;
  --results-progress-height: clamp(.5625rem, .35rem + .35cqi, .875rem);
  --results-stage-progress-height: clamp(.6875rem, .4rem + .4cqi, 1rem);
  --results-attention-columns: minmax(150px, 1.1fr) 90px minmax(130px, .9fr) minmax(210px, 1.45fr) 105px 72px 164px;
  --results-status-marker-width: 4px;
  --results-node-marker-size: 6px;
  --results-skeleton-height: 76px;
  --results-skeleton-background: var(--results-color-surface-muted);
  --results-skeleton-opacity: .6;
  --results-skeleton-duration: 1.2s;
  gap: clamp(1.375rem, 1.1rem + .22vw, 1.75rem);
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

.results-hero h2 {
  font-size: clamp(1.6875rem, .8rem + 1cqi, 2.5rem);
}

.results-hero p {
  font-size: var(--results-font-body);
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
  gap: var(--results-space-3);
  padding: var(--results-space-3) var(--results-space-4);
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
  display: none;
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
  padding: var(--results-space-3) var(--results-space-4);
  border-left: var(--results-border-width) solid var(--results-color-line-soft);
}

.results-kpis article:first-child {
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
  padding: 0 var(--results-space-4);
  border-bottom: var(--results-border-width) solid var(--results-color-line);
}

.results-tabs button {
  position: relative;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: var(--results-space-2);
  min-width: 145px;
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
  padding: var(--results-space-4);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
}

.results-panel > header h3,
.results-subpanel > header h3 {
  margin: 0 0 var(--results-space-1);
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

.attention-list__head,
.attention-list > article {
  display: grid;
  grid-template-columns: var(--results-attention-columns);
  gap: var(--results-space-3);
  align-items: center;
  min-width: 0;
  padding: var(--results-space-3) var(--results-space-4);
}

.attention-list__head {
  color: var(--results-color-muted);
  background: var(--results-color-surface-soft);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
}

.attention-list > article {
  min-height: var(--results-row-min-height);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
}

.attention-list > article:last-child,
.run-list > article:last-child,
.campaign-list > article:last-child,
.candidate-result-list > article:last-child {
  border-bottom: 0;
}

.attention-type,
.attention-object,
.attention-list time {
  overflow: hidden;
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attention-list article > strong {
  overflow: hidden;
  color: var(--results-color-ink);
  font-size: var(--results-font-control);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attention-list article > p {
  display: -webkit-box;
  overflow: hidden;
  margin: 0;
  color: var(--results-color-copy);
  font-size: var(--results-font-detail);
  line-height: var(--results-leading-body);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.attention-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--results-space-2);
  min-width: 0;
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
  white-space: nowrap;
}

.attention-actions button {
  min-height: 24px;
  padding: 0;
  color: var(--results-color-brand-dark);
  background: transparent;
  border: 0;
  white-space: nowrap;
}

.attention-actions button:disabled,
.results-center button:disabled {
  opacity: var(--results-disabled-opacity);
}

.results-empty {
  display: grid;
  justify-items: center;
  gap: var(--results-space-2);
  padding: var(--results-space-6) var(--results-space-5);
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
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--results-space-5);
  padding: var(--results-space-3) var(--results-space-5) var(--results-space-7);
}

.stage-progress-list article {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: var(--results-space-1) var(--results-space-2);
  min-width: 0;
}

.stage-progress-list span {
  grid-column: 1 / -1;
  color: var(--results-color-copy);
  font-size: var(--results-font-control);
  font-weight: var(--results-weight-bold);
}

.stage-progress-list div {
  grid-column: 1 / -1;
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
  font-size: var(--results-font-campaign-metric);
  text-align: left;
}

.stage-progress-list small {
  grid-column: 2;
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
  text-align: right;
}

.stage-progress-list .stage-tone-1 i { background: var(--results-color-info); }
.stage-progress-list .stage-tone-2 i { background: var(--results-color-sage); }
.stage-progress-list .stage-tone-3 i { background: var(--results-color-warning); }
.stage-progress-list .stage-tone-4 i { background: var(--results-color-stage-muted); }
.stage-progress-list .stage-tone-5 i { background: #cbd5df; }

.pipeline-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, .72fr)) minmax(220px, 1.35fr) minmax(170px, 1fr);
  align-items: center;
  gap: var(--results-space-5);
  padding: var(--results-space-1) var(--results-space-5) var(--results-space-5);
}

.pipeline-summary article {
  display: grid;
  align-content: center;
  gap: var(--results-space-1);
  min-width: 0;
}

.pipeline-summary span {
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
}

.pipeline-summary strong {
  color: var(--results-color-ink);
  font-size: var(--results-font-campaign-metric);
  font-variant-numeric: tabular-nums;
}

.pipeline-summary strong small {
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-medium);
}

.pipeline-summary__completion {
  grid-template-columns: minmax(0, 1fr) auto;
}

.pipeline-summary__completion > div {
  grid-column: 1 / -1;
  height: var(--results-progress-height);
  overflow: hidden;
  background: var(--results-color-line-soft);
  border-radius: var(--results-radius-status);
}

.pipeline-summary__completion > div i {
  display: block;
  height: 100%;
  background: var(--results-color-brand);
  border-radius: inherit;
}

.pipeline-section-title {
  margin: 0;
  padding: 18px var(--results-space-5) 0;
  color: var(--results-color-ink);
  font-size: var(--results-font-control);
}

.pipeline-section-title--summary {
  padding-top: 17px;
  border-top: var(--results-border-width) solid var(--results-color-line-soft);
}

.pipeline-entry {
  justify-self: end;
  min-width: 142px;
  padding: 10px 18px;
  color: #fff;
  background: var(--results-color-brand);
  border-radius: 5px;
  font-size: var(--results-font-control);
  font-weight: var(--results-weight-heavy);
  text-align: center;
  text-decoration: none;
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

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.results-operation-notice {
  display: flex;
  align-items: center;
  gap: var(--results-space-3);
  padding: 12px var(--results-space-5);
  border-top: var(--results-border-width) solid var(--results-color-line-soft);
  color: var(--results-color-copy);
  background: var(--results-color-surface);
  font-size: var(--results-font-detail);
}

.results-operation-notice.is-success {
  color: var(--results-color-brand-dark);
  background: var(--results-color-brand-soft);
}

.results-operation-notice > span {
  flex: 1;
}

.results-operation-notice button {
  width: 32px;
  height: 32px;
  border: 0;
  background: transparent;
  color: currentColor;
  font-size: 20px;
}

.candidate-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  overflow-x: auto;
  padding: 13px var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  scrollbar-width: thin;
}

.candidate-filter-bar label {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  color: var(--results-color-copy);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-medium);
  white-space: nowrap;
}

.candidate-filter-bar select {
  min-width: 80px;
  height: 31px;
  padding: 0 26px 0 9px;
  border: var(--results-border-width) solid var(--results-color-line);
  border-radius: 5px;
  color: var(--results-color-copy);
  background: var(--results-color-surface-soft);
  font: inherit;
}

.candidate-filter-bar button {
  flex: 0 0 auto;
  min-height: 31px;
  padding: 0 13px;
  border: 1px solid var(--results-color-line);
  border-radius: 5px;
  color: var(--results-color-brand-dark);
  background: var(--results-color-surface);
  font-size: var(--results-font-detail);
}

.notification-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 11px var(--results-space-5);
  border-bottom: var(--results-border-width) solid var(--results-color-warning-line);
  color: var(--results-color-warning-text);
  background: var(--results-color-warning-soft);
  font-size: var(--results-font-detail);
}

.notification-summary strong {
  color: var(--results-color-warning-text);
}

.notification-summary span {
  padding: 3px 7px;
  border-radius: 8px;
  background: rgba(255, 255, 255, .75);
}

.notification-summary small {
  flex: 1 1 260px;
  color: var(--results-color-warning-text);
  text-align: right;
}

.candidate-ranking-scroll {
  overflow-x: auto;
}

.candidate-table-footer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  min-width: 760px;
  min-height: 48px;
  padding: 8px var(--results-space-5);
  color: var(--results-color-muted);
  background: var(--results-color-surface);
  border-top: var(--results-border-width) solid var(--results-color-line-soft);
  font-size: var(--results-font-meta);
}

.candidate-table-footer > div {
  display: flex;
  align-items: center;
  gap: 4px;
}

.candidate-table-footer > div > span {
  min-width: 22px;
  color: var(--results-color-muted);
  text-align: center;
}

.candidate-table-footer button {
  min-width: 28px;
  height: 28px;
  padding: 0 7px;
  color: var(--results-color-copy);
  background: transparent;
  border: 0;
  border-radius: 5px;
  font-size: var(--results-font-detail);
}

.candidate-table-footer button.active {
  color: #fff;
  background: var(--results-color-brand);
  font-weight: var(--results-weight-heavy);
}

.candidate-table-footer button:disabled {
  color: var(--results-color-faint);
}

.candidate-table-footer > label {
  justify-self: end;
}

.candidate-table-footer select {
  height: 30px;
  padding: 0 25px 0 9px;
  border: var(--results-border-width) solid var(--results-color-line);
  border-radius: 5px;
  color: var(--results-color-copy);
  background: var(--results-color-surface);
  font-size: var(--results-font-meta);
}

.candidate-ranking-table {
  width: 100%;
  min-width: 0;
  table-layout: fixed;
  border-collapse: collapse;
  color: var(--results-color-copy);
  font-size: var(--results-font-detail);
}

.candidate-ranking-table th {
  padding: 11px 10px;
  border-bottom: var(--results-border-width) solid var(--results-color-line);
  color: var(--results-color-muted);
  background: var(--results-color-surface-soft);
  font-size: 10px;
  font-weight: var(--results-weight-heavy);
  letter-spacing: .04em;
  text-align: left;
  white-space: nowrap;
}

.candidate-ranking-table td {
  padding: 7px 8px;
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  vertical-align: middle;
}

.candidate-ranking-table tbody tr {
  transition: background-color 150ms ease;
}

.candidate-ranking-table tbody tr:hover,
.candidate-ranking-table tbody tr.is-selected {
  background: var(--results-color-brand-soft);
}

.candidate-select-cell {
  width: 42px;
  text-align: center !important;
}

.candidate-select-cell input {
  width: 17px;
  height: 17px;
  accent-color: var(--results-color-brand);
}

.candidate-rank {
  color: var(--results-color-ink);
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.candidate-name-button {
  display: grid;
  gap: 3px;
  max-width: 190px;
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  text-align: left;
}

.candidate-name-button:not(:disabled):hover strong,
.candidate-name-button:not(:disabled):focus-visible strong {
  color: var(--results-color-brand-dark);
  text-decoration: underline;
}

.candidate-name-button strong,
.candidate-resume strong,
.candidate-score strong {
  overflow: hidden;
  color: var(--results-color-ink);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-name-button small,
.candidate-resume small,
.candidate-score small,
.candidate-notification small {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--results-color-muted);
  font-size: 10px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-score.has-score strong {
  color: var(--results-color-brand-dark);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.candidate-status {
  display: inline-flex;
  align-items: center;
  min-height: 25px;
  padding: 3px 8px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.35;
  white-space: nowrap;
}

.candidate-status.is-success { color: var(--results-color-brand-dark); background: var(--results-color-brand-soft); }
.candidate-status.is-warning { color: var(--results-color-warning-text); background: var(--results-color-warning-soft); }
.candidate-status.is-danger { color: var(--results-color-danger-text); background: var(--results-color-danger-soft); }
.candidate-status.is-active { color: var(--results-color-active); background: var(--results-color-active-soft); }
.candidate-status.is-neutral { color: var(--results-color-muted); background: var(--results-color-surface-muted); }

.candidate-notification {
  max-width: 150px;
}

.candidate-notification small {
  color: var(--results-color-danger-text);
  white-space: normal;
}

.candidate-action-cell {
  text-align: right;
}

.candidate-action-cell button {
  min-height: 34px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: var(--results-color-brand-dark);
  background: transparent;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}

.candidate-action-cell button:disabled,
.candidate-name-button:disabled {
  cursor: not-allowed;
  color: var(--results-color-muted);
  opacity: .65;
}

.candidate-batch-bar {
  position: sticky;
  bottom: 0;
  z-index: 4;
  display: grid;
  grid-template-columns: minmax(150px, auto) minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  padding: 13px var(--results-space-5) calc(13px + env(safe-area-inset-bottom));
  border-top: var(--results-border-width) solid var(--results-color-brand-line);
  background: var(--results-color-surface);
  box-shadow: var(--results-shadow-panel);
}

.candidate-batch-bar > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.candidate-batch-bar strong {
  color: var(--results-color-ink);
  font-size: 12px;
}

.candidate-batch-bar > div:first-child button {
  padding: 3px;
  border: 0;
  color: var(--results-color-brand-dark);
  background: transparent;
  font-size: 10px;
}

.candidate-batch-bar > span {
  color: var(--results-color-muted);
  font-size: 10px;
}

.candidate-batch-bar .primary-button,
.candidate-batch-bar .secondary-button {
  min-height: 42px;
}

.candidate-rank {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.candidate-rank.is-top-1 { color: #b7791f; }
.candidate-rank.is-top-2 { color: #718096; }
.candidate-rank.is-top-3 { color: #b46f3c; }

.candidate-ranking-table th:nth-child(1) { width: 38px; }
.candidate-ranking-table th:nth-child(2) { width: 46px; }
.candidate-ranking-table th:nth-child(3) { width: 120px; }
.candidate-ranking-table th:nth-child(4) { width: 90px; }
.candidate-ranking-table th:nth-child(5) { width: 105px; }
.candidate-ranking-table th:nth-child(6) { width: 94px; }
.candidate-ranking-table th:nth-child(7) { width: 120px; }
.candidate-ranking-table th:nth-child(8) { width: 92px; }
.candidate-ranking-table th:nth-child(9) { width: 98px; }
.candidate-ranking-table th:nth-child(10) { width: 105px; }

.results-subpanel > header {
  min-height: 54px;
  padding: 14px 18px;
}

.results-subpanel > header h3 {
  margin: 0;
  color: var(--results-color-brand-dark);
  font-size: var(--results-font-control);
}

.results-data-table {
  display: grid;
  min-width: 0;
}

.results-data-table__head,
.results-data-table__row {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, .72fr) minmax(0, .48fr) minmax(0, .76fr) minmax(0, .9fr) minmax(0, .9fr) minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 11px 16px;
}

.results-data-table__head--campaign,
.results-data-table__row--campaign {
  grid-template-columns: minmax(0, 1.45fr) minmax(0, .7fr) minmax(0, .9fr) minmax(0, .9fr) minmax(0, 1fr) minmax(0, 1.1fr);
}

.results-data-table__head {
  color: var(--results-color-muted);
  background: var(--results-color-surface-soft);
  border-top: var(--results-border-width) solid var(--results-color-line-soft);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
}

.results-data-table__row {
  min-height: 62px;
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  color: var(--results-color-copy);
  font-size: var(--results-font-detail);
}

.results-data-table__row > * {
  min-width: 0;
}

.results-table-name {
  display: grid;
  gap: 3px;
}

.results-table-name strong,
.results-table-name small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.results-table-name strong {
  color: var(--results-color-ink);
  font-size: var(--results-font-detail);
}

.results-table-name small,
.results-data-table time,
.results-table-progress small {
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
}

.results-table-progress {
  display: grid;
  grid-template-columns: minmax(38px, 1fr) auto;
  align-items: center;
  gap: 6px;
}

.results-data-table__row .run-list__actions {
  display: grid;
  justify-items: start;
  gap: 2px;
}

.results-data-table__row .run-list__actions button,
.results-data-table__row > a {
  padding: 1px 0;
  color: var(--results-color-brand-dark);
  background: transparent;
  border: 0;
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
  text-decoration: none;
}

.results-data-table__row > .run-error,
.results-data-table__row > .run-detail {
  grid-column: 1 / -1;
}

.results-table-empty {
  display: grid;
  grid-column: 1 / -1;
  justify-items: center;
  gap: 5px;
  min-height: 105px;
  align-content: center;
  padding: 18px;
  color: var(--results-color-muted);
  font-size: var(--results-font-detail);
  text-align: center;
}

.results-table-empty strong {
  color: var(--results-color-slate);
}

.results-table-footer {
  min-height: 36px;
  padding: 10px 16px;
  color: var(--results-color-muted);
  background: var(--results-color-surface);
  border-top: var(--results-border-width) solid var(--results-color-line-soft);
  font-size: var(--results-font-meta);
}

/* Container conditions intentionally use literals because custom properties are invalid in query expressions. */
@container results-center (max-width: 1050px) {
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

  .candidate-batch-bar {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .candidate-batch-bar > span {
    display: none;
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

  .results-context select,
  .candidate-filter-bar button,
  .attention-actions button {
    min-height: var(--results-touch-target);
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

  .results-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .results-kpis article:nth-child(odd) {
    border-left: 0;
  }

  .results-kpis article:nth-child(n + 3) {
    border-top: var(--results-border-width) solid var(--results-color-line-soft);
  }

  .results-tabs {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow-x: visible;
    padding: 0;
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

  .attention-list__head {
    display: none;
  }

  .results-task-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .results-subpanel + .results-subpanel {
    border-top: var(--results-border-width) solid var(--results-color-line-soft);
    border-left: 0;
  }

  .attention-list > article {
    grid-template-columns: minmax(0, 1fr) auto;
    padding-right: var(--results-space-4);
    padding-left: var(--results-space-4);
  }

  .attention-list article > strong {
    grid-row: 1;
    grid-column: 1;
  }

  .attention-list article > .candidate-status {
    grid-row: 1;
    grid-column: 2;
  }

  .attention-object,
  .attention-list article > p,
  .attention-list article > time,
  .attention-actions {
    grid-column: 1 / -1;
    justify-content: start;
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

  .candidate-filter-bar,
  .notification-summary,
  .results-operation-notice {
    padding-right: var(--results-space-4);
    padding-left: var(--results-space-4);
  }

  .notification-summary small {
    flex-basis: 100%;
    text-align: left;
  }

  .candidate-ranking-scroll {
    overflow: visible;
  }

  .candidate-ranking-table {
    display: block;
    min-width: 0;
  }

  .candidate-ranking-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
  }

  .candidate-ranking-table tbody {
    display: grid;
  }

  .candidate-ranking-table tbody tr {
    display: grid;
    grid-template-columns: 36px minmax(0, 1fr);
    padding: 14px var(--results-space-4);
    border-bottom: 1px solid var(--results-color-line-soft);
  }

  .candidate-ranking-table td {
    display: grid;
    grid-column: 2;
    grid-template-columns: 108px minmax(0, 1fr);
    align-items: start;
    gap: 10px;
    padding: 7px 0;
    border: 0;
  }

  .candidate-ranking-table td::before {
    content: attr(data-label);
    color: var(--results-color-muted);
    font-size: 10px;
    font-weight: 700;
  }

  .candidate-ranking-table .candidate-select-cell {
    display: block;
    grid-row: 1 / span 10;
    grid-column: 1;
    width: auto;
    padding-top: 9px;
  }

  .candidate-ranking-table .candidate-select-cell::before,
  .candidate-ranking-table .candidate-action-cell::before {
    display: none;
  }

  .candidate-name-button,
  .candidate-notification {
    max-width: none;
  }

  .candidate-name-button small,
  .candidate-resume small,
  .candidate-score small {
    white-space: normal;
  }

  .candidate-action-cell {
    display: block !important;
    padding-top: 10px !important;
    text-align: left;
  }

  .candidate-action-cell button {
    min-height: 44px;
  }

  .candidate-batch-bar {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
    padding-right: var(--results-space-4);
    padding-left: var(--results-space-4);
  }

  .candidate-batch-bar > div:last-child {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .candidate-batch-bar > div:last-child button {
    width: 100%;
  }

  .run-detail {
    grid-template-columns: minmax(0, 1fr);
  }

  .stage-progress-list {
    grid-template-columns: minmax(0, 1fr);
    padding: var(--results-space-4);
  }

  .pipeline-summary {
    grid-template-columns: minmax(0, 1fr);
  }

  .pipeline-summary article,
  .pipeline-summary article:first-child {
    border-top: var(--results-border-width) solid var(--results-color-line-soft);
    border-left: 0;
  }

  .pipeline-summary__completion {
    grid-column: auto;
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
