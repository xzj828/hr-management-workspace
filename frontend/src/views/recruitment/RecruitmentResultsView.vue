<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'
import ResumeIntelligencePanel from '@/components/ResumeIntelligencePanel.vue'
import ScreeningDecisionDrawer from '@/components/ScreeningDecisionDrawer.vue'
import CommunicationConfirmDrawer from '@/components/CommunicationConfirmDrawer.vue'
import WorkflowRunPanel from '@/components/WorkflowRunPanel.vue'
import RecruitmentResultsNavigation from '@/components/RecruitmentResultsNavigation.vue'
import { formatFileSize, stageColumns } from '@/recruitment'
import { createRequestId } from '@/recruitmentJobs'
import { communicationPayload } from '@/recruitmentCommunications'
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
const purgeTarget = ref(null)
const purgeSaving = ref(false)
const purgeError = ref('')
const clearTarget = ref('')
const clearSaving = ref(false)
const clearError = ref('')
const decisionDrawerMode = ref('')
const decisionBusy = ref(false)
const decisionSaved = ref(false)
const decisionError = ref('')
const notificationError = ref('')
const decisionBatchId = ref('')
const decisionRequest = reactive({ id: '', signature: '' })
const notificationRequest = reactive({ id: '', signature: '', approvalId: '' })
const greetingRequest = reactive({ id: '', signature: '', approvalId: '' })
const greetingDrawerOpen = ref(false)
const greetingBusy = ref(false)
const greetingError = ref('')
const greetingCandidates = ref([])
const greetingExcludedCount = ref(0)
const greetingAccountId = ref('')
const greetingAccountName = ref('')
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
    greeting: row?.greeting || {
      eligible: false,
      status: 'not_requested',
      reason_code: 'stable_identity_missing',
      reason_label: '缺少平台稳定身份',
    },
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
  queued: '已排队', running: '拉取中', analyzing: 'AI 分析中', waiting_human: '等待人工', paused: '已暂停',
  succeeded: '已完成', failed: '失败', cancelled: '已取消', draft: '草稿',
  open: '待处理', resolved: '已处理', archived: '已归档',
}

const currentJobId = computed(() => currentJob.value ? String(currentJob.value.id) : '')
const jobRuns = computed(() => resources.runs.items.filter((item) => {
  if (String(item.job || '') !== currentJobId.value) return false
  const wantsArchived = statusFilter.value === 'archived'
  if (Boolean(item.archived_at || item.automation_plan_archived_at) !== wantsArchived) return false
  const account = String(route.query.account || '')
  return !account || String(item.boss_account || item.account || '') === account
}))
const runById = computed(() => new Map(jobRuns.value.map((item) => [String(item.id), item])))
const jobCampaigns = computed(() => resources.campaigns.items.filter((item) => {
  if (String(item.job || '') !== currentJobId.value) return false
  const linkedRun = resources.runs.items.find((run) => String(run.id) === String(item.workflow_run || ''))
  const wantsArchived = statusFilter.value === 'archived'
  if (linkedRun && Boolean(linkedRun.archived_at || linkedRun.automation_plan_archived_at) !== wantsArchived) return false
  if (!linkedRun && wantsArchived) return false
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
  if (group === 'in_progress') return ['queued', 'running', 'analyzing'].includes(status)
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
  if (statusFilter.value === 'all') return item.status !== 'archived'
  if (statusFilter.value === 'needs_action') return item.status === 'open'
  if (statusFilter.value === 'succeeded') return item.status === 'resolved'
  if (statusFilter.value === 'archived') return item.status === 'archived'
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
  const recommendation = row.assessment?.system_recommendation || row.assessment?.recommendation
  if (filter === 'pending_hr_review') return recommendation === 'review'
  if (filter === 'recommended_advance') return recommendation === 'advance'
  return true
}

function matchesCandidateFilter(row) {
  if (candidateFilters.stage !== 'all' && row.application?.stage !== candidateFilters.stage) return false
  if (candidateFilters.ai !== 'all') {
    if (candidateFilters.ai === 'unscored') {
      if (row.aiState === 'scored' && row.assessment) return false
    } else if ((row.assessment?.system_recommendation || row.assessment?.recommendation) !== candidateFilters.ai) return false
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
const clearableCandidateRows = computed(() => screeningResults.value.filter((row) => row.application?.id))
const clearableAttentionItems = computed(() => jobAttentions.value.filter((item) => item.status !== 'archived'))
const clearableTaskRuns = computed(() => jobRuns.value.filter((run) => !run.archived_at))
const activeClearTarget = computed(() => ({ attention: 'attentions', tasks: 'tasks', candidates: 'candidates' }[activeView.value] || ''))
const activeClearCount = computed(() => ({
  attentions: clearableAttentionItems.value.length,
  tasks: clearableTaskRuns.value.length,
  candidates: clearableCandidateRows.value.length,
}[activeClearTarget.value] || 0))
const activeClearLabel = computed(() => activeClearTarget.value === 'candidates' ? '一键清除候选人' : '一键清除')
const clearDialog = computed(() => ({
  attentions: {
    title: '一键清除人工事项',
    name: `${currentJob.value?.title || '当前岗位'} · ${clearableAttentionItems.value.length} 项`,
    description: '将这些人工事项从当前列表归档。未完成的流程不会因此被自动批准或继续执行。',
    note: '历史事项和处理证据仍会保留；此操作不会替代“标记已处理”。',
    actionLabel: '确认清除',
  },
  tasks: {
    title: '一键清除任务结果',
    name: `${currentJob.value?.title || '当前岗位'} · ${clearableTaskRuns.value.length} 个任务`,
    description: '将当前岗位中已经结束的任务结果从当前列表归档。',
    note: '正在运行、等待人工或暂停中的任务会安全保留；历史结果和审计证据不会被物理删除。',
    actionLabel: '确认清除',
  },
  candidates: {
    title: '一键清除候选人记录',
    name: `${currentJob.value?.title || '当前岗位'} · ${clearableCandidateRows.value.length} 条记录`,
    description: '将当前岗位的全部候选人记录从候选人与简历列表中归档。',
    note: '候选人主档、其他岗位的应聘、简历原文件、历史评分、流程和审计证据都会保留。',
    actionLabel: '确认清除',
  },
}[clearTarget.value] || null))

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
const greetableCandidateRows = computed(() => selectedCandidateRows.value.filter((row) => row.greeting?.eligible))
const excludedGreetingRows = computed(() => selectedCandidateRows.value.filter((row) => !row.greeting?.eligible))
const activePipelineCount = computed(() => screeningApplications.value.filter((application) => !['hired', 'rejected'].includes(application.stage)).length)
const hiredCount = computed(() => screeningApplications.value.filter((application) => application.stage === 'hired').length)
const hiringCompletion = computed(() => {
  const target = Number(currentJob.value?.headcount || 0)
  return target ? Math.min(100, Math.round(hiredCount.value / target * 100)) : 0
})
const openAttentionCount = computed(() => jobAttentions.value.filter((item) => item.status === 'open').length)
const activeRunCount = computed(() => jobRuns.value.filter((item) => ['queued', 'running', 'analyzing', 'waiting_human', 'paused'].includes(item.status)).length)
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
  if (['running', 'analyzing', 'queued'].includes(status)) return 'active'
  return 'neutral'
}

function runProgress(run) {
  const nodes = run.node_runs || []
  if (!nodes.length) return 0
  const completed = nodes.filter((node) => ['succeeded', 'skipped', 'failed', 'cancelled'].includes(node.status)).length
  return Math.round(completed / nodes.length * 100)
}

function campaignProgress(campaign) {
  const maximum = Math.max(1, Number(campaign.max_scan_count || 0))
  return Math.min(100, Math.round(Number(campaign.scanned_count || 0) / maximum * 100))
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
  const digits = assessment.scoring_policy_version === 'evidence-level-v1' ? 1 : 0
  return `${Number(assessment.total_score || 0).toFixed(digits)} 分`
}

function aiRecommendationLabel(row) {
  if (row.aiState !== 'scored' || !row.assessment) {
    return {
      processing: 'AI 处理中', failed: 'AI 评分失败', no_resume: '暂无简历',
      standard_missing: '待发布岗位标准', unscored: 'AI 尚未评分',
    }[row.aiState] || 'AI 尚未评分'
  }
  const recommendation = row.assessment.system_recommendation || row.assessment.recommendation
  return {
    advance: 'AI 建议进一步沟通', review: 'AI 建议人工复核', hold: 'AI 暂不建议推进',
  }[recommendation] || 'AI 建议人工复核'
}

function aiRecommendationTone(row) {
  if (row.aiState !== 'scored' || !row.assessment) return 'neutral'
  const recommendation = row.assessment.system_recommendation || row.assessment.recommendation
  return { advance: 'success', review: 'warning', hold: 'danger' }[recommendation] || 'warning'
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
    } else if (action === 'retry-report' && detailAssessment.value) {
      await api(`recruitment/resume-assessments/${detailAssessment.value.id}/retry-report/`, { method: 'POST', body: JSON.stringify({ request_id: createRequestId() }) })
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

function openResumePurge(row) {
  if (!row?.resume) return
  purgeTarget.value = row
  purgeError.value = ''
}

async function confirmResumePurge() {
  const target = purgeTarget.value
  if (!target?.resume || purgeSaving.value) return
  purgeSaving.value = true
  purgeError.value = ''
  try {
    const result = await api(`recruitment/resumes/${target.resume.id}/purge/`, { method: 'POST' })
    const releasedBytes = Number(result?.released_bytes ?? target.resume.file_size ?? 0)
    await closeCandidateDetail()
    purgeTarget.value = null
    await loadResults()
    operationNotice.value = {
      tone: 'success',
      message: releasedBytes > 0
        ? `简历原文件已删除，释放 ${formatFileSize(releasedBytes)} 本地空间；历史评分和审计记录已保留。`
        : '简历原文件已清理；历史评分和审计记录已保留。',
    }
  } catch (error) {
    purgeError.value = error.message || '简历删除失败，请稍后重试'
  } finally {
    purgeSaving.value = false
  }
}

function openBulkClear(target) {
  const count = {
    attentions: clearableAttentionItems.value.length,
    tasks: clearableTaskRuns.value.length,
    candidates: clearableCandidateRows.value.length,
  }[target] || 0
  if (!count) return
  clearTarget.value = target
  clearError.value = ''
}

async function confirmBulkClear() {
  if (!clearTarget.value || clearSaving.value) return
  clearSaving.value = true
  clearError.value = ''
  try {
    let result
    if (clearTarget.value === 'attentions') {
      result = await api('recruitment/human-attentions/bulk-archive/', {
        method: 'POST',
        body: JSON.stringify({ attention_ids: clearableAttentionItems.value.map((item) => item.id) }),
      })
      operationNotice.value = {
        tone: result.skipped_count ? 'warning' : 'success',
        message: `已清除 ${result.archived_count || 0} 项人工事项${result.skipped_count ? `，${result.skipped_count} 项因不可访问而保留` : ''}。`,
      }
    } else if (clearTarget.value === 'tasks') {
      result = await api('recruitment/workflow-runs/bulk-archive/', {
        method: 'POST',
        body: JSON.stringify({ run_ids: clearableTaskRuns.value.map((run) => run.id) }),
      })
      operationNotice.value = {
        tone: result.skipped_count ? 'warning' : 'success',
        message: `已清除 ${result.archived_count || 0} 个已结束任务${result.skipped_count ? `，${result.skipped_count} 个运行中或受保护任务已保留` : ''}。`,
      }
    } else {
      result = await api('recruitment/applications/bulk-archive/', {
        method: 'POST',
        body: JSON.stringify({ application_ids: clearableCandidateRows.value.map((row) => row.application.id) }),
      })
      operationNotice.value = {
        tone: result.skipped_count ? 'warning' : 'success',
        message: `已清除 ${result.archived_count || 0} 条候选人记录${result.skipped_count ? `，${result.skipped_count} 条因不可访问而保留` : ''}。`,
      }
      selectedApplicationIds.value = []
    }
    clearTarget.value = ''
    await loadResults()
  } catch (error) {
    clearError.value = error.message || '批量清除失败，请稍后重试'
  } finally {
    clearSaving.value = false
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

function openGreetingDrawer(event) {
  const accountId = screeningMeta.job?.boss_account || currentJob.value?.boss_account
  if (!accountId) {
    operationNotice.value = { tone: 'warning', message: '当前岗位未关联可用的 BOSS 账号，请刷新岗位配置后重试。' }
    return
  }
  if (!greetableCandidateRows.value.length) {
    const reasons = [...new Set(excludedGreetingRows.value.map((row) => row.greeting?.reason_label).filter(Boolean))]
    operationNotice.value = {
      tone: 'warning',
      message: reasons.length
        ? `所选候选人当前无法打招呼：${reasons.join('、')}。`
        : '所选候选人当前无法打招呼，请刷新结果后重试。',
    }
    return
  }
  detailReturnFocus = event?.currentTarget || document.activeElement
  greetingError.value = ''
  greetingBusy.value = false
  greetingCandidates.value = greetableCandidateRows.value.map((row) => ({
    applicationId: row.application.id,
    name: row.candidate?.name || '未命名候选人',
    jobTitle: currentJob.value?.title || '',
  }))
  greetingExcludedCount.value = excludedGreetingRows.value.length
  greetingAccountId.value = String(accountId)
  greetingAccountName.value = currentJob.value?.account_name || ''
  greetingDrawerOpen.value = true
}

async function closeGreetingDrawer(force = false) {
  if (greetingBusy.value && !force) return
  greetingDrawerOpen.value = false
  greetingCandidates.value = []
  greetingExcludedCount.value = 0
  greetingAccountId.value = ''
  greetingAccountName.value = ''
  await nextTick()
  detailReturnFocus?.focus?.()
  detailReturnFocus = null
}

async function submitGreeting(snapshot) {
  if (!greetingCandidates.value.length || greetingBusy.value) return
  const accountId = greetingAccountId.value
  if (!accountId) {
    greetingError.value = '当前岗位未关联可用的 BOSS 账号，请刷新岗位配置后重试。'
    return
  }
  const applicationIds = greetingCandidates.value.map((item) => Number(item.applicationId))
  const signature = JSON.stringify({ accountId: Number(accountId), applicationIds, message: snapshot.message })
  if (greetingRequest.signature !== signature) {
    greetingRequest.id = createRequestId()
    greetingRequest.signature = signature
    greetingRequest.approvalId = ''
  }
  greetingBusy.value = true
  greetingError.value = ''
  try {
    if (!greetingRequest.approvalId) {
      const prepared = await api('recruitment/communication-actions/prepare/', {
        method: 'POST',
        body: JSON.stringify(communicationPayload({
          accountId,
          applicationIds,
          action: 'greet',
          message: snapshot.message,
          requestId: greetingRequest.id,
        })),
      })
      greetingRequest.approvalId = String(prepared.approval_id || prepared.id || '')
    }
    if (!greetingRequest.approvalId) throw new Error('服务端未返回有效的沟通审批记录')
    const approved = await api(`recruitment/automation-approvals/${encodeURIComponent(greetingRequest.approvalId)}/approve/`, { method: 'POST' })
    const steps = Array.isArray(approved?.batch?.steps) ? approved.batch.steps : []
    if (!steps.some((step) => step.status === 'pending')) {
      greetingError.value = '审批已保存，但服务端没有返回可执行的待处理步骤；请刷新候选人状态后人工核查。'
      await loadResults()
      return
    }
    const submitted = new Set(applicationIds.map(String))
    selectedApplicationIds.value = selectedApplicationIds.value.filter((id) => !submitted.has(String(id)))
    operationNotice.value = { tone: 'success', message: `已将 ${applicationIds.length} 位候选人的统一打招呼任务加入顺序执行队列。` }
    await closeGreetingDrawer(true)
    await loadResults()
  } catch (error) {
    greetingError.value = error.message || '批量打招呼提交失败，请核对候选人状态后重试。'
  } finally {
    greetingBusy.value = false
  }
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
    purgeTarget.value = null
    purgeSaving.value = false
    purgeError.value = ''
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
  <div :class="['page-stack', 'results-center', { 'is-embedded': embedded, 'results-center--business-results-typography': !embedded }]">
    <RecruitmentResultsNavigation v-if="!embedded" />
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
      <div v-if="context.jobs.length" class="results-select results-select--required"><select data-test="empty-job-filter" aria-label="选择在招职位" @change="chooseJob"><option value="">选择职位</option><option v-for="job in context.jobs" :key="job.id" :value="job.id">{{ job.title }}</option></select><AppIcon name="chevron-down" :size="16" /></div>
      <RouterLink v-else class="primary-button" to="/recruitment/workbench">返回招聘作业台</RouterLink>
    </section>

    <template v-else>
      <div class="results-overview">
        <section v-if="!embedded" class="results-context" aria-label="当前结果范围">
          <label class="results-context__job"><span>当前岗位</span><span class="results-select"><select :value="currentJobId" data-test="job-filter" @change="chooseJob"><option v-for="job in context.jobs" :key="job.id" :value="String(job.id)">{{ job.title }} · {{ job.account_name || '未绑定账号' }}</option></select><AppIcon name="chevron-down" :size="16" /></span><small>招聘目标 {{ currentJob.headcount || '未设置' }} 人</small></label>
          <label><span>任务运行</span><span class="results-select"><select v-model="selectedRunId" data-test="run-filter"><option value="">该岗位全部运行</option><option v-for="run in jobRuns" :key="run.id" :value="String(run.id)">{{ run.template_name || '自动化任务' }} · {{ statusLabel(run.status) }} · {{ formatDateTime(run.created_at) }}</option></select><AppIcon name="chevron-down" :size="16" /></span></label>
          <label><span>结果状态</span><span class="results-select"><select v-model="statusFilter" data-test="status-filter"><option v-for="option in visibleStatusOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><AppIcon name="chevron-down" :size="16" /></span></label>
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
          <div class="results-tabbar">
            <nav class="results-tabs" role="tablist" aria-label="结果中心视图">
              <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="activeView === tab.key" :class="{ active: activeView === tab.key }" :data-test="`results-tab-${tab.key}`" @click="activeView = tab.key">{{ tab.label }} <span>{{ tab.count }}</span></button>
            </nav>
            <button v-if="activeClearTarget" class="results-list-clear" type="button" :data-test="`clear-${activeClearTarget}`" :disabled="!activeClearCount" @click="openBulkClear(activeClearTarget)">{{ activeClearLabel }}</button>
          </div>

        <section v-if="activeView === 'attention'" class="results-panel results-panel--attention" data-test="attention-view">
          <p v-if="resources.attentions.error" class="results-inline-error">人工事项加载失败：{{ resources.attentions.error }}</p>
          <p v-if="attentionActionError" class="results-inline-error" data-test="attention-action-error">{{ attentionActionError }}</p>
          <div class="attention-list">
            <div class="attention-list__head" aria-hidden="true">
              <span>待处理事项</span><span>类别</span><span>关联账号 / 候选人</span><span>上下文摘要</span><span>创建时间</span><span>状态</span><span>处理</span>
            </div>
            <article v-for="item in filteredAttentions" :key="item.id" :class="`is-${statusTone(item.status)}`">
              <strong>{{ item.title }}</strong>
              <span class="attention-type">{{ item.attention_type_label || '人工事项' }}</span>
              <span class="attention-object">{{ item.candidate_name || item.account_name || '当前岗位' }}</span>
              <p>{{ detailText(item.detail) }}</p>
              <time>{{ formatDateTime(item.created_at) }}</time>
              <span :class="['candidate-status', `is-${statusTone(item.status)}`]">{{ item.status_label || statusLabel(item.status) }}</span>
              <div class="attention-actions">
                <RouterLink :to="{ name: 'recruitment-candidates', query: { job: currentJobId, application: item.application || undefined } }">查看相关信息 <AppIcon name="chevron-right" :size="14" /></RouterLink>
                <button v-if="item.status === 'open'" class="attention-actions__primary" type="button" :disabled="Boolean(attentionActionId)" :data-test="`resolve-attention-${item.id}`" @click="resolveAttention(item)">{{ attentionActionId === String(item.id) ? '正在处理…' : '标记已处理' }}</button>
              </div>
            </article>
            <div v-if="!filteredAttentions.length && resources.attentions.loading" class="results-table-empty">正在加载人工事项…</div>
            <div v-else-if="!filteredAttentions.length" class="results-table-empty"><strong>当前范围没有需要人工处理的事项</strong><span>可切换状态查看已处理记录。</span></div>
            <footer class="results-table-footer">共 {{ filteredAttentions.length }} 项</footer>
          </div>
        </section>

        <section v-else-if="activeView === 'tasks'" class="results-task-view" data-test="tasks-view">
          <div class="results-task-grid">
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
                <span>{{ (run.node_runs || []).filter((node) => ['succeeded', 'skipped', 'failed', 'cancelled'].includes(node.status)).length }}/{{ (run.node_runs || []).length }}</span>
                <span>{{ run.target_candidate_count ?? run.target_count ?? '—' }}</span>
                <div class="results-table-progress"><div class="results-progress"><i :style="{ width: `${runProgress(run)}%` }"></i></div><small>{{ runProgress(run) }}%</small></div>
                <time>{{ formatDateTime(run.started_at || run.created_at || run.updated_at) }}</time>
                <span class="run-list__actions"><RouterLink v-if="run.automation_plan" :to="{ name: 'recruitment-task-detail', params: { planId: run.automation_plan }, query: { job: currentJobId, run: run.id, view: 'tasks', status: run.automation_plan_archived_at ? 'archived' : undefined } }">查看任务</RouterLink><button type="button" :data-test="`manage-run-${run.id}`" @click="openRunPanel(run)">{{ run.status === 'waiting_human' ? '处理待办' : '查看进展' }}</button></span>
                <p v-if="run.error_message" class="run-error">{{ run.error_message }}</p>
              </article>
              </template>
              <div v-else-if="resources.runs.loading" class="results-table-empty">正在恢复任务运行…</div>
              <div v-else class="results-table-empty"><strong>当前筛选下没有任务运行</strong><span>返回作业台发起任务后，运行记录会出现在这里。</span></div>
              <footer class="results-table-footer">共 {{ filteredRuns.length }} 项</footer>
            </div>
          </article>

          <article class="results-subpanel">
            <header><h3>主动寻访结果</h3><span>{{ filteredCampaigns.filter((campaign) => ['queued', 'running', 'analyzing', 'waiting_human', 'paused'].includes(campaign.status)).length }} 个运行中，{{ filteredCampaigns.filter((campaign) => campaign.status === 'succeeded').length }} 个已完成</span></header>
            <p v-if="resources.campaigns.error" class="results-inline-error">主动寻访加载失败：{{ resources.campaigns.error }}</p>
            <div class="campaign-list results-data-table">
              <div class="results-data-table__head results-data-table__head--campaign"><span>运行名称</span><span>状态</span><span>AI 合格 / 目标</span><span>AI 分析进度</span><span>开始时间</span><span>操作</span></div>
              <template v-if="filteredCampaigns.length">
                <article v-for="campaign in filteredCampaigns" :key="campaign.id" class="results-data-table__row results-data-table__row--campaign">
                  <div class="results-table-name"><strong>{{ campaign.name }}</strong><small>{{ campaign.source === 'recommend' ? '推荐人才' : campaign.source === 'deep_search' ? '深度搜索' : '关键词搜索' }}</small></div>
                  <span :class="['candidate-status', `is-${statusTone(campaign.status)}`]">{{ statusLabel(campaign.status) }}</span>
                  <span>{{ campaign.qualified_resume_count || 0 }}/{{ campaign.target_resume_count }}</span>
                  <div class="results-table-progress"><div class="results-progress"><i :style="{ width: `${campaignProgress(campaign)}%` }"></i></div><small>{{ campaign.scanned_count || 0 }}/{{ campaign.max_scan_count }} · 已拉取 {{ campaign.pulled_resume_count || 0 }}</small></div>
                  <time>{{ formatDateTime(campaign.started_at || campaign.created_at || campaign.updated_at) }}</time>
                  <RouterLink :to="{ name: 'recruitment-workbench', query: { job: currentJobId, campaign: campaign.id } }">查看运行并处理</RouterLink>
                  <p v-if="campaign.error_message || campaign.stop_reason" :class="{ 'run-error': campaign.error_message }">{{ campaign.error_message || `停止原因：${campaign.stop_reason_label || campaign.stop_reason}` }}</p>
                </article>
              </template>
              <div v-else-if="resources.campaigns.loading" class="results-table-empty">正在加载主动寻访结果…</div>
              <div v-else class="results-table-empty"><strong>当前筛选下没有主动寻访</strong><span>被动消息方案仍可只产生任务运行和人工事项。</span></div>
              <footer class="results-table-footer">共 {{ filteredCampaigns.length }} 项</footer>
            </div>
          </article>
          </div>
        </section>

        <section v-else-if="activeView === 'candidates'" class="results-panel results-panel--candidates" data-test="candidates-view">
          <p v-if="resources.screening.error" class="results-inline-error">候选排名加载失败：{{ resources.screening.error }}</p>

          <div class="candidate-filter-bar" aria-label="候选人筛选">
            <label><span>招聘阶段</span><span class="results-select"><select v-model="candidateFilters.stage" data-test="candidate-filter-stage"><option v-for="option in candidateStageOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><AppIcon name="chevron-down" :size="15" /></span></label>
            <label><span>AI 初筛建议</span><span class="results-select"><select v-model="candidateFilters.ai" data-test="candidate-filter-ai"><option v-for="option in candidateAiOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><AppIcon name="chevron-down" :size="15" /></span></label>
            <label><span>简历状态</span><span class="results-select"><select v-model="candidateFilters.resume" data-test="candidate-filter-resume"><option v-for="option in candidateResumeOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><AppIcon name="chevron-down" :size="15" /></span></label>
            <label><span>HR 结论</span><span class="results-select"><select v-model="candidateFilters.hr" data-test="candidate-filter-hr"><option v-for="option in candidateHrOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><AppIcon name="chevron-down" :size="15" /></span></label>
            <label><span>通知状态</span><span class="results-select"><select v-model="candidateFilters.notification" data-test="candidate-filter-notification"><option v-for="option in candidateNotificationOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><AppIcon name="chevron-down" :size="15" /></span></label>
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

          <div v-if="candidateResults.length" class="candidate-ranking-region">
            <div class="candidate-ranking-scroll">
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
                  <th scope="col" class="candidate-action-heading">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in displayedCandidateResults" :key="row.application.id" :data-application-id="row.application.id" :class="{ 'is-selected': isApplicationSelected(row.application.id) }">
                  <td class="candidate-select-cell"><label><span class="sr-only">选择候选人 {{ row.candidate?.name || '未命名候选人' }}</span><input type="checkbox" :checked="isApplicationSelected(row.application.id)" :aria-label="`选择候选人 ${row.candidate?.name || '未命名候选人'}`" @change="toggleApplication(row.application.id, $event.target.checked)" /></label></td>
                  <td data-label="排名"><strong :class="['candidate-rank', row.rank && row.rank <= 3 ? `is-top-${row.rank}` : '']"><AppIcon v-if="row.rank && row.rank <= 3" name="crown" :size="18" />{{ row.rank ?? '—' }}</strong></td>
                  <td data-label="候选人"><button v-if="row.resume" class="candidate-name-button" type="button" :aria-label="`查看 ${row.candidate?.name || '候选人'} 的简历与分析报告`" @click="openCandidateDetail(row, $event)"><strong>{{ row.candidate?.name || '未命名候选人' }}</strong></button><div v-else class="candidate-name-static"><strong>{{ row.candidate?.name || '未命名候选人' }}</strong></div></td>
                  <td data-label="招聘阶段"><span class="candidate-status is-neutral">{{ row.application.stage_label || statusLabel(row.application.stage) }}</span></td>
                  <td data-label="AI 初筛建议"><span :class="['candidate-status', `is-${aiRecommendationTone(row)}`]">{{ aiRecommendationLabel(row) }}</span></td>
                  <td data-label="得分"><div class="candidate-score" :class="{ 'has-score': row.assessment }" :title="row.assessment ? `置信度 ${Math.round(Number(row.assessment.confidence || 0) * 100)}%` : '尚未评分，不作为 0 分'"><strong>{{ scoreText(row.assessment) }}</strong><small class="sr-only">{{ row.assessment ? `置信度 ${Math.round(Number(row.assessment.confidence || 0) * 100)}%` : '不作为 0 分' }}</small></div></td>
                  <td data-label="简历状态"><div class="candidate-resume"><strong>{{ row.resume?.original_name || '暂无简历' }}</strong></div></td>
                  <td data-label="HR 结论"><span :class="['candidate-status', row.hrDecision?.decision === 'pass' ? 'is-success' : row.hrDecision?.decision === 'fail' ? 'is-danger' : 'is-neutral']" :title="row.hrDecision?.reason || ''">{{ hrDecisionLabel(row.hrDecision) }}</span></td>
                  <td data-label="通知状态"><div class="candidate-notification"><span :class="['candidate-status', `is-${notificationTone(row.notification)}`]">{{ notificationLabel(row.notification) }}</span><small v-if="row.notification?.error_message">{{ row.notification.error_message }}</small></div></td>
                  <td class="candidate-action-cell"><div v-if="row.resume"><button type="button" :data-test="`view-candidate-${row.application.id}`" @click="openCandidateDetail(row, $event)">查看详情</button><button class="candidate-action-danger" type="button" :data-test="`purge-resume-${row.application.id}`" @click="openResumePurge(row)">删除简历</button></div><span v-else class="candidate-action-empty" aria-hidden="true">—</span></td>
                </tr>
              </tbody>
              </table>
            </div>
            <footer class="candidate-table-footer">
              <span>共 {{ candidateResults.length }} 项</span>
              <div><button type="button" :disabled="candidatePage === 1" aria-label="上一页" @click="candidatePage -= 1">‹</button><template v-for="item in candidatePaginationItems" :key="item"><span v-if="String(item).startsWith('ellipsis')">…</span><button v-else type="button" :class="{ active: candidatePage === item }" @click="candidatePage = item">{{ item }}</button></template><button type="button" :disabled="candidatePage === candidatePageCount" aria-label="下一页" @click="candidatePage += 1">›</button></div>
              <label class="results-select candidate-page-size"><span class="sr-only">每页显示数量</span><select v-model.number="candidatePageSize"><option :value="10">10 条/页</option><option :value="20">20 条/页</option><option :value="50">50 条/页</option></select><AppIcon name="chevron-down" :size="15" /></label>
            </footer>
          </div>
          <div v-else-if="resources.screening.loading" class="results-local-loading">正在加载候选排名…</div>
          <div v-else-if="resources.screening.error" class="results-empty"><AppIcon name="alert-circle" :size="25" /><strong>候选排名暂时无法加载</strong><span>其他任务结果仍可查看；重试不会使用旧岗位数据覆盖当前页面。</span><button class="secondary-button" type="button" @click="loadResults()">重试候选排名</button></div>
          <div v-else-if="screeningResults.length" class="results-empty"><AppIcon name="filter" :size="25" /><strong>当前筛选下没有候选人</strong><span>可清除筛选查看完整排名；筛选不会清除已选择的人。</span><button class="secondary-button" type="button" @click="clearCandidateFilters">查看全部</button></div>
          <div v-else class="results-empty"><AppIcon name="users" :size="25" /><strong>该岗位还没有候选人结果</strong><span>返回作业台执行寻访，或在候选人页面导入已确认的人选。</span><RouterLink class="primary-button" to="/recruitment/workbench">返回招聘作业台</RouterLink></div>

          <div v-if="selectedCandidateRows.length" class="candidate-batch-bar" role="region" aria-label="候选人批量操作" data-test="candidate-batch-bar">
            <div><strong>已选择 {{ selectedCandidateRows.length }} 人</strong><button type="button" @click="selectedApplicationIds = []">清空选择</button></div>
            <span>其中 {{ greetableCandidateRows.length }} 人可打招呼；AI 建议不会限制 HR 的人工判断。</span>
            <div><button class="primary-button" type="button" data-test="bulk-greet" @click="openGreetingDrawer($event)">批量打招呼</button><button class="secondary-button" type="button" data-test="bulk-pass" @click="openDecisionDrawer('pass', $event)">确认通过</button><button class="secondary-button" type="button" data-test="bulk-fail" @click="openDecisionDrawer('fail', $event)">确认未通过</button></div>
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
        v-if="selectedDetailRow && !purgeTarget"
        :resume="selectedDetailRow.resume"
        :structure="detailStructure"
        :assessment="detailAssessment"
        :assessments="detailAssessments"
        :tasks="detailTasks"
        :loading="detailLoading"
        :context-error="detailError"
        @close="closeCandidateDetail"
        @retry-structure="runResumeAction(selectedDetailRow, 'retry-structure')"
        @retry-report="runResumeAction(selectedDetailRow, 'retry-report')"
        @score="runResumeAction(selectedDetailRow, 'score')"
        @rescore="runResumeAction(selectedDetailRow, 'rescore')"
        @purge="openResumePurge(selectedDetailRow)"
      />
      <ArchiveConfirmModal
        v-if="purgeTarget"
        title="删除已保存简历"
        :name="`${purgeTarget.resume.candidate_name} · ${purgeTarget.resume.original_name}`"
        :description="`将从当前排名移除这份简历，并物理删除本地原文件（${formatFileSize(purgeTarget.resume.file_size || 0)}）。此操作不可恢复。`"
        note="历史结构化结果、评分、HR 结论和审计记录仍会保留。"
        action-label="确认删除"
        :saving="purgeSaving"
        :error="purgeError"
        :business-results-typography="!embedded"
        @close="purgeTarget = null"
        @confirm="confirmResumePurge"
      />
      <ArchiveConfirmModal
        v-if="clearDialog"
        :title="clearDialog.title"
        :name="clearDialog.name"
        :description="clearDialog.description"
        :note="clearDialog.note"
        :action-label="clearDialog.actionLabel"
        :saving="clearSaving"
        :error="clearError"
        :business-results-typography="!embedded"
        @close="clearTarget = ''"
        @confirm="confirmBulkClear"
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
      <CommunicationConfirmDrawer
        v-if="greetingDrawerOpen"
        :candidates="greetingCandidates"
        :account-name="greetingAccountName"
        :saving="greetingBusy"
        :excluded-count="greetingExcludedCount"
        :error="greetingError"
        fixed-action="greet"
        @close="closeGreetingDrawer()"
        @confirm="submitGreeting"
      />
    </template>
  </div>
</template>

<style scoped>
.results-center {
  --results-font-family: var(--app-font-family);
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
  --results-control-height: clamp(2.875rem, 1.85rem + .95cqi, 3.25rem);
  --results-compact-control-height: clamp(2.75rem, 1.8rem + .85cqi, 3rem);
  --results-touch-target: clamp(2.75rem, 1.5rem + 1.35cqi, 3.5rem);
  --results-row-min-height: clamp(4.5rem, 2.75rem + 1.9cqi, 5.5rem);
  --results-font-meta: .875rem;
  --results-font-detail: .9375rem;
  --results-font-control: .9375rem;
  --results-font-body: .9375rem;
  --results-font-title: 1.125rem;
  --results-font-metric: clamp(1.625rem, 1rem + .8cqi, 2.25rem);
  --results-font-campaign-metric: clamp(1.25rem, .55rem + .75cqi, 1.875rem);
  --results-weight-regular: 400;
  --results-weight-medium: 400;
  --results-weight-bold: 600;
  --results-weight-heavy: 600;
  --results-leading-tight: 1.45;
  --results-leading-body: 1.65;
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
  --results-candidate-name-min: 15rem;
  --results-candidate-stage-min: 9rem;
  --results-candidate-resume-min: 12rem;
  --results-candidate-score-min: 11rem;
  --results-action-column: 1.5rem;
  --results-stage-label-width: 5.625rem;
  --results-stage-count-width: 1.875rem;
  --results-stage-card-min: 8.125rem;
  --results-progress-height: clamp(.5625rem, .35rem + .35cqi, .875rem);
  --results-stage-progress-height: clamp(.6875rem, .4rem + .4cqi, 1rem);
  --results-attention-columns: minmax(220px, 1.15fr) minmax(90px, .45fr) minmax(130px, .7fr) minmax(240px, 1.25fr) 106px 86px minmax(230px, 1fr);
  --results-status-marker-width: 4px;
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

.results-center--business-results-typography {
  --results-font-min: .9167rem;
  --results-font-meta: var(--results-font-min);
  --results-weight-bold: 400;
  --results-weight-heavy: 400;
  font-size: var(--results-font-min);
  font-weight: var(--results-weight-regular);
}

.results-center *,
.results-center *::before,
.results-center *::after {
  box-sizing: border-box;
}

.results-center button,
.results-center input,
.results-center select,
.results-center textarea {
  font-family: var(--results-font-family);
}

.results-center--business-results-typography :deep(:is(p, span, small, label, th, td, button, a, input, select, textarea, time, dt, dd, li, em)) {
  font-weight: var(--results-weight-regular) !important;
}

.results-center--business-results-typography :deep(:is(h1, h2, h3, h4, h5, h6, strong, b)) {
  font-weight: var(--results-weight-regular) !important;
}

.results-center--business-results-typography :deep(.workflow-run-panel :is(span, small, p, button, strong)),
.results-center--business-results-typography :deep(.screening-decision-drawer :is(p, span, small, label, textarea, button, dt, dd, strong, em)),
.results-center--business-results-typography :deep(.resume-evidence-card :is(p, span:not(.candidate-summary__avatar), small, button, strong)),
.results-center--business-results-typography :deep(.analysis-report h3),
.results-center--business-results-typography :deep(.keyword-section h3),
.results-center--business-results-typography :deep(.communication-intro :is(strong, p)),
.results-center--business-results-typography :deep(.communication-meta),
.results-center--business-results-typography :deep(.communication-field),
.results-center--business-results-typography :deep(.communication-warning),
.results-center--business-results-typography :deep(.communication-recipients :is(span, strong, small)),
.results-center--business-results-typography :deep(.drawer-confirm-footer button) {
  font-size: var(--results-font-min) !important;
}

.results-center strong {
  font-weight: var(--results-weight-bold);
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

.results-select {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 0;
}

.results-select > svg {
  position: absolute;
  right: var(--results-space-3);
  z-index: 1;
  color: var(--results-color-muted);
  pointer-events: none;
}

.results-select select {
  appearance: none;
  cursor: pointer;
}

.results-select--required {
  min-width: var(--results-filter-status-min);
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

.results-context label > span:first-child {
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
  transition: border-color var(--results-transition), box-shadow var(--results-transition), background var(--results-transition);
}

.results-context select:hover,
.results-required select:hover {
  border-color: #a9c6c2;
  background: var(--results-color-surface);
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

.results-tabbar {
  display: flex;
  align-items: stretch;
  min-width: 0;
  border-bottom: var(--results-border-width) solid var(--results-color-line);
}

.results-tabs {
  display: flex;
  flex: 1 1 auto;
  min-width: 0;
  padding-left: var(--results-space-4);
}

.results-tabs button {
  position: relative;
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: var(--results-space-2);
  min-width: clamp(150px, 12cqi, 190px);
  min-height: var(--results-control-height);
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

.results-tabbar > .results-list-clear {
  align-self: center;
  margin: 0 var(--results-space-4) 0 var(--results-space-3);
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
  padding: 10px var(--results-space-4);
}

.results-list-clear {
  flex: none;
  min-height: 34px;
  padding: 0 12px;
  color: var(--results-color-danger-text);
  background: var(--results-color-surface);
  border: var(--results-border-width) solid rgba(190, 58, 69, .32);
  border-radius: var(--results-radius-control);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-bold);
}

.results-list-clear:hover:not(:disabled) {
  background: var(--results-color-danger-soft);
  border-color: rgba(190, 58, 69, .55);
}

.results-list-clear:disabled {
  cursor: not-allowed;
  opacity: var(--results-disabled-opacity);
}

.attention-list__head {
  color: var(--results-color-muted);
  background: var(--results-color-surface-soft);
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
}

.attention-list__head > span:nth-last-child(2) {
  text-align: center;
}

.attention-list__head > span:last-child {
  padding-right: 8px;
  text-align: right;
}

.attention-list > article {
  min-height: 60px;
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
  display: grid;
  grid-template-columns: minmax(118px, 1fr) minmax(100px, auto);
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
  width: 100%;
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
  justify-content: center;
  gap: var(--results-space-1);
  min-height: 36px;
  padding: 0 10px;
  border: var(--results-border-width) solid #b8d8d4;
  border-radius: 9px;
  background: var(--results-color-surface);
  white-space: nowrap;
  width: 100%;
}

.attention-actions button {
  min-height: 36px;
  padding: 0 11px;
  color: #fff;
  background: var(--results-color-brand);
  border: var(--results-border-width) solid var(--results-color-brand);
  border-radius: 9px;
  white-space: nowrap;
  width: 100%;
}

.attention-list a:hover,
.attention-list a:hover {
  background: var(--results-color-brand-soft);
}

.attention-actions button:hover:not(:disabled) {
  background: var(--results-color-brand-dark);
  border-color: var(--results-color-brand-dark);
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

.results-task-view {
  min-width: 0;
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
  display: grid;
  grid-template-columns: repeat(5, minmax(190px, 1fr)) auto;
  align-items: end;
  gap: 12px;
  padding: 16px var(--results-space-5) 18px;
  border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  background: var(--results-color-surface);
}

.candidate-filter-bar label {
  display: grid;
  gap: 7px;
  min-width: 0;
  max-width: none;
  color: var(--results-color-copy);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-medium);
}

.candidate-filter-bar label > span:first-child {
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
}

.candidate-filter-bar select {
  width: 100%;
  min-width: 0;
  height: var(--results-compact-control-height);
  padding: 0 34px 0 12px;
  appearance: none;
  border: var(--results-border-width) solid var(--results-color-line);
  border-radius: var(--results-radius-control);
  color: var(--results-color-copy);
  background: var(--results-color-surface-soft);
  font: inherit;
  transition: border-color var(--results-transition), box-shadow var(--results-transition), background var(--results-transition);
}

.candidate-filter-bar select:hover {
  border-color: #a9c6c2;
  background: var(--results-color-surface);
}

.candidate-filter-bar button {
  min-height: var(--results-compact-control-height);
  padding: 0 18px;
  border: 1px solid var(--results-color-line);
  border-radius: var(--results-radius-control);
  color: var(--results-color-brand-dark);
  background: var(--results-color-surface);
  font-size: var(--results-font-detail);
  font-weight: var(--results-weight-medium);
  transition: border-color var(--results-transition), background var(--results-transition), color var(--results-transition);
}

.candidate-filter-bar button:hover {
  border-color: var(--results-color-brand-line);
  background: var(--results-color-brand-soft);
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

.candidate-ranking-region {
  min-width: 0;
}

.candidate-ranking-scroll {
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: #a9bbb8 #edf3f2;
}

.candidate-table-footer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  min-width: 0;
  min-height: 56px;
  padding: 9px var(--results-space-5);
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
  min-width: 34px;
  height: 34px;
  padding: 0 9px;
  color: var(--results-color-copy);
  background: transparent;
  border: 0;
  border-radius: 8px;
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
  height: 38px;
  padding: 0 34px 0 12px;
  border: var(--results-border-width) solid var(--results-color-line);
  border-radius: var(--results-radius-control);
  color: var(--results-color-copy);
  background: var(--results-color-surface);
  font-size: var(--results-font-meta);
}

.candidate-ranking-table {
  width: 100%;
  min-width: 1200px;
  table-layout: fixed;
  border-collapse: collapse;
  color: var(--results-color-copy);
  font-size: var(--results-font-detail);
}

.candidate-ranking-table th {
  padding: 12px 16px;
  border-bottom: var(--results-border-width) solid var(--results-color-line);
  color: var(--results-color-muted);
  background: var(--results-color-surface-soft);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-heavy);
  letter-spacing: .015em;
  line-height: var(--results-leading-tight);
  text-align: left;
  white-space: nowrap;
}

.candidate-ranking-table td {
  min-height: 52px;
  padding: 11px 16px;
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
  font-size: var(--results-font-body);
  font-variant-numeric: tabular-nums;
}

.candidate-name-button {
  display: grid;
  gap: 0;
  width: 100%;
  max-width: none;
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  text-align: left;
}

.candidate-name-static {
  display: grid;
  gap: 0;
  width: 100%;
}

.candidate-name-button:not(:disabled):hover strong,
.candidate-name-button:not(:disabled):focus-visible strong {
  color: var(--results-color-brand-dark);
  text-decoration: underline;
}

.candidate-name-button strong,
.candidate-name-static strong,
.candidate-resume strong,
.candidate-score strong {
  overflow: hidden;
  color: var(--results-color-ink);
  font-size: var(--results-font-body);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-name-button small,
.candidate-name-static small,
.candidate-resume small,
.candidate-score small,
.candidate-notification small {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
  line-height: var(--results-leading-body);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-score.has-score strong {
  color: var(--results-color-brand-dark);
  font-size: var(--results-font-body);
  font-variant-numeric: tabular-nums;
}

.candidate-status {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-regular);
  line-height: 1.35;
  white-space: nowrap;
}

.candidate-status.is-success { color: var(--results-color-brand-dark); background: var(--results-color-brand-soft); }
.candidate-status.is-warning { color: var(--results-color-warning-text); background: var(--results-color-warning-soft); }
.candidate-status.is-danger { color: var(--results-color-danger-text); background: var(--results-color-danger-soft); }
.candidate-status.is-active { color: var(--results-color-active); background: var(--results-color-active-soft); }
.candidate-status.is-neutral { color: var(--results-color-muted); background: var(--results-color-surface-muted); }

.candidate-notification {
  max-width: none;
}

.candidate-notification small {
  color: var(--results-color-danger-text);
  white-space: normal;
}

.candidate-action-cell {
  text-align: center;
}

.candidate-action-heading {
  text-align: center !important;
}

.candidate-action-cell > div {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 164px;
  margin: 0 auto;
}

.candidate-action-cell button {
  width: 100%;
  min-height: 36px;
  padding: 0 8px;
  border: var(--results-border-width) solid var(--results-color-brand-line);
  border-radius: var(--results-radius-control);
  color: var(--results-color-brand-dark);
  background: var(--results-color-brand-soft);
  font-size: var(--results-font-meta);
  font-weight: var(--results-weight-bold);
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
  font-size: var(--results-font-detail);
}

.candidate-batch-bar > div:first-child button {
  padding: 3px;
  border: 0;
  color: var(--results-color-brand-dark);
  background: transparent;
  font-size: var(--results-font-meta);
}

.candidate-batch-bar > span {
  color: var(--results-color-muted);
  font-size: var(--results-font-meta);
}

.candidate-batch-bar .primary-button,
.candidate-batch-bar .secondary-button {
  min-height: 42px;
}

.candidate-action-cell .candidate-action-danger { color: var(--results-color-danger-text); border-color: rgba(190, 58, 69, .28); background: #fff; }
.candidate-action-cell .candidate-action-danger:hover { color: #a72f3b; border-color: rgba(190, 58, 69, .52); background: #fff3f4; }

.candidate-rank {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.candidate-rank.is-top-1 { color: #b7791f; }
.candidate-rank.is-top-2 { color: #718096; }
.candidate-rank.is-top-3 { color: #b46f3c; }

.candidate-ranking-table th:nth-child(1) { width: 50px; }
.candidate-ranking-table th:nth-child(2) { width: 60px; }
.candidate-ranking-table th:nth-child(3) { width: 135px; }
.candidate-ranking-table th:nth-child(4) { width: 110px; }
.candidate-ranking-table th:nth-child(5) { width: 140px; }
.candidate-ranking-table th:nth-child(6) { width: 90px; }
.candidate-ranking-table th:nth-child(7) { width: 160px; }
.candidate-ranking-table th:nth-child(8) { width: 110px; }
.candidate-ranking-table th:nth-child(9) { width: 120px; }
.candidate-ranking-table th:nth-child(10) { width: 190px; }

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

.candidate-action-cell button:hover {
  border-color: var(--results-color-brand);
  background: #dff4f0;
}

.candidate-action-empty {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  max-width: 164px;
  color: var(--results-color-faint);
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

.results-data-table__row > .run-error {
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
@container results-center (max-width: 1180px) {
  .attention-list {
    gap: 14px;
    padding: 16px;
    background: var(--results-color-surface-soft);
  }

  .attention-list__head {
    display: none;
  }

  .attention-list > article {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px 18px;
    min-height: 0;
    padding: 18px;
    border: var(--results-border-width) solid var(--results-color-line-soft);
    border-radius: var(--results-radius-panel);
    background: var(--results-color-surface);
    box-shadow: 0 8px 22px rgba(15, 23, 42, .055);
  }

  .attention-list > article:last-child {
    border-bottom: var(--results-border-width) solid var(--results-color-line-soft);
  }

  .attention-list article > strong { grid-row: 1; grid-column: 1; }
  .attention-list article > .candidate-status { grid-row: 1; grid-column: 2; }
  .attention-type { grid-row: 2; grid-column: 1; }
  .attention-object { grid-row: 3; grid-column: 1; }
  .attention-list article > p { grid-row: 4; grid-column: 1 / -1; }
  .attention-list article > time { grid-row: 5; grid-column: 1; align-self: center; }
  .attention-actions { display: flex; grid-row: 5; grid-column: 2; width: auto; }

  .attention-list a,
  .attention-actions button {
    width: auto;
  }

  .candidate-filter-bar {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .candidate-ranking-scroll {
    overflow: visible;
    background: var(--results-color-surface-soft);
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
    gap: 14px;
    padding: 16px;
  }

  .candidate-ranking-table tbody tr {
    display: grid;
    grid-template-columns: 36px repeat(2, minmax(0, 1fr));
    gap: 0 22px;
    padding: 14px 16px;
    border: 1px solid var(--results-color-line-soft);
    border-radius: var(--results-radius-control);
    background: var(--results-color-surface);
  }

  .candidate-ranking-table td {
    display: grid;
    grid-template-columns: 108px minmax(0, 1fr);
    align-items: start;
    gap: 12px;
    min-width: 0;
    padding: 9px 0;
    border: 0;
  }

  .candidate-ranking-table td::before {
    content: attr(data-label);
    color: var(--results-color-muted);
    font-size: var(--results-font-meta);
    font-weight: var(--results-weight-regular);
  }

  .candidate-ranking-table .candidate-select-cell {
    display: block;
    grid-row: 1 / span 5;
    grid-column: 1;
    width: auto;
    padding-top: 10px;
  }

  .candidate-ranking-table .candidate-select-cell::before,
  .candidate-ranking-table .candidate-action-cell::before {
    display: none;
  }

  .candidate-name-button,
  .candidate-name-static,
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
    grid-column: 2 / -1;
    padding-top: 10px !important;
    text-align: left;
  }

  .candidate-action-cell > div {
    display: inline-flex;
    width: auto;
    max-width: none;
    margin: 0;
  }

  .candidate-action-empty {
    display: none;
  }

  .candidate-action-cell:has(.candidate-action-empty) {
    display: none !important;
  }
}

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

@container results-center (max-width: 820px) {
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

  .results-kpis small {
    display: none;
  }

  .results-tabbar {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .results-tabs {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow-x: visible;
    padding: 0;
  }

  .results-tabbar > .results-list-clear {
    width: calc(100% - (2 * var(--results-space-3)));
    min-height: var(--results-touch-target);
    margin: var(--results-space-2) var(--results-space-3);
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

  .attention-list article > time { grid-row: 5; }
  .attention-actions { grid-row: 6; flex-wrap: wrap; }

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

  .candidate-filter-bar {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .candidate-filter-bar label {
    max-width: none;
  }

  .candidate-filter-bar button {
    grid-column: 1 / -1;
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
    font-size: var(--results-font-meta);
    font-weight: var(--results-weight-regular);
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
  .candidate-name-static,
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

@container results-center (max-width: 520px) {
  .candidate-filter-bar {
    grid-template-columns: minmax(0, 1fr);
  }

  .candidate-filter-bar button {
    grid-column: 1;
  }

  .candidate-table-footer {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .candidate-table-footer > div {
    grid-row: 2;
    grid-column: 1 / -1;
    justify-content: center;
  }

  .candidate-table-footer > label {
    grid-column: 2;
  }

  .candidate-ranking-table td {
    grid-template-columns: 88px minmax(0, 1fr);
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
