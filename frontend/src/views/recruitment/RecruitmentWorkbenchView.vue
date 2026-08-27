<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import CandidateFilterPanel from '@/components/CandidateFilterPanel.vue'
import { defaultCandidateFilters, normalizeCandidateFilters } from '@/recruitmentCandidateFilters'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const auth = useAuthStore()
const context = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()

const WIZARD_DRAFT_VERSION = 1
const WORKBENCH_RESET_VERSION = 1
const WIZARD_STEPS = ['context', 'standard', 'plan', 'review']
const MAX_JOB_DOCUMENT_SIZE = 25 * 1024 * 1024
const JOB_DOCUMENT_SUFFIX = /\.(doc|docx|xlsx)$/i
const JOB_DOCUMENT_CATEGORY = 'persona'

const accounts = ref([])
const workflowTemplates = ref([])
const workflowVersions = ref([])
const documents = ref([])
const loading = ref(true)
const documentsLoading = ref(false)
const loadError = ref('')
const documentError = ref('')
const submitError = ref('')
const selectedAccountId = ref('')
const fileInput = ref(null)
const workbenchMain = ref(null)
const stepHeading = ref(null)
const currentStep = ref('context')
const completedSteps = reactive({ context: false, standard: false, plan: false })
const wizardError = ref('')
const routeJobError = ref('')
const storageNotice = ref('')
const wizardReady = ref(false)
const wizardHydrating = ref(false)
const restoredWizardStep = ref('context')
const dragging = ref(false)
const uploadQueue = ref([])
const uploading = ref(false)
const uploadProgress = reactive({ completed: 0, total: 0, failed: 0 })
const schemeKind = ref('passive_resume')
const workflowChoice = ref('standard')
const coreText = ref('')
const bonusText = ref('')
const interval = ref(2)
const source = ref('search')
const keyword = ref('')
const candidateFilters = ref(defaultCandidateFilters())
const targetResumeCount = ref(3)
const maxScanCount = ref(20)
const autoStartRequested = ref(false)
const submitting = ref(false)
const submitStage = ref('')
const currentPlan = ref(null)
const archivedPlan = ref(null)
const planLoading = ref(false)
const planError = ref('')
const planVersionNotice = ref('')
const legacyEditBaseUnknown = ref(false)
const editBase = reactive({
  active: false,
  jobId: '',
  controlVersion: 0,
  revisionId: null,
  revision: null,
})
const summary = reactive({ worker: null, cli_available: false })
const startRequest = reactive({ id: '', signature: '' })
let documentLoadSequence = 0
let planLoadSequence = 0
let planPollTimer = null
let planPollInFlight = false
let componentAlive = true
let skipPreviousJobPersistFor = ''
let activeExecutionSnapshot = null
let activeUploadLock = null
let freshWorkbenchLocked = false

function controllablePlan() {
  return currentPlan.value || archivedPlan.value
}

const selectedJob = computed(() => context.currentJob)
const selectedAccount = computed(() => accounts.value.find((account) => String(account.id) === String(selectedAccountId.value)) || null)
const jobsForAccount = computed(() => {
  if (!selectedAccountId.value) return context.jobs
  return context.jobs.filter((job) => String(job.boss_account) === String(selectedAccountId.value))
})
const selectedJobValue = computed({
  get: () => context.selectedJobId,
  set: (value) => chooseJob(value),
})
const coreItems = computed(() => requirementLines(coreText.value))
const bonusItems = computed(() => requirementLines(bonusText.value))
const activeCountValid = computed(() => {
  const target = Number(targetResumeCount.value)
  const maximum = Number(maxScanCount.value)
  return Number.isInteger(target) && Number.isInteger(maximum) && target >= 1 && target <= 100 && maximum >= target && maximum <= 100
})
const activeQueryValid = computed(() => {
  if (schemeKind.value !== 'active_resume_search') return true
  if (!coreItems.value.length) return false
  return source.value !== 'search' || Boolean(keyword.value.trim())
})
const passiveIntervalValid = computed(() => Number(interval.value) >= 1 && Number(interval.value) <= 1440)
const browserReady = computed(() => selectedAccount.value?.login_status === 'ready')
const runtimeReady = computed(() => summary.worker?.status === 'online' && summary.cli_available)
const enabledWorkflowOptions = computed(() => {
  const options = workflowVersions.value
    .filter((version) => version.status === 'enabled'
      && String(version.boss_account) === String(selectedAccountId.value)
      && !workflowVersionIsPlanManaged(version))
    .map((version) => ({
    id: version.id,
    label: `${workflowTemplates.value.find((item) => item.id === version.template)?.name || `流程 ${version.template}`} · V${version.version}`,
    }))
  const plan = controllablePlan()
  const revisionWorkflow = plan?.current_revision?.workflow_version
  const revisionWorkflowId = typeof revisionWorkflow === 'object' ? revisionWorkflow?.id : revisionWorkflow
  if (revisionUsesCustomWorkflow(plan?.current_revision)
    && revisionWorkflowId
    && !workflowVersionIsPlanManaged(revisionWorkflow)
    && !options.some((item) => String(item.id) === String(revisionWorkflowId))) {
    options.push({ id: revisionWorkflowId, label: '当前任务使用的高级流程' })
  }
  return options
})
const selectedCustomWorkflow = computed(() => {
  if (!String(workflowChoice.value).startsWith('custom:')) return null
  const id = String(workflowChoice.value).slice(7)
  return enabledWorkflowOptions.value.find((item) => String(item.id) === id) || null
})
const contextStepComplete = computed(() => Boolean(
  selectedJob.value
  && selectedAccount.value
  && String(selectedJob.value.boss_account) === String(selectedAccount.value.id),
))
const contextReadiness = computed(() => [
  {
    key: 'login',
    label: browserReady.value ? '已登录' : '等待登录',
    detail: selectedAccount.value?.name || '尚未选择账号',
    ready: browserReady.value,
  },
  {
    key: 'browser',
    label: browserReady.value ? '可正常访问' : '浏览器未就绪',
    detail: browserReady.value ? 'BOSS 直聘' : accountReadinessMessage(selectedAccount.value),
    ready: browserReady.value,
  },
  {
    key: 'binding',
    label: contextStepComplete.value ? '职位已绑定' : '等待绑定',
    detail: contextStepComplete.value ? '本次作业可用' : '请选择匹配的职位与账号',
    ready: contextStepComplete.value,
  },
])
const wizardSteps = computed(() => [
  { key: 'context', number: '01', label: '职位与账号', reachable: true },
  { key: 'standard', number: '02', label: '招聘标准', reachable: completedSteps.context },
  { key: 'plan', number: '03', label: '执行方案', reachable: completedSteps.context && completedSteps.standard },
  {
    key: 'review',
    number: '04',
    label: '执行前检查',
    reachable: completedSteps.context && completedSteps.standard && completedSteps.plan,
  },
])
const currentStepCopy = computed(() => ({
  context: {
    title: '职位与账号',
    description: '确认本次作业使用的在招职位和授权执行账号。',
  },
  standard: {
    title: '招聘标准',
    description: '上传岗位参考资料，并补充用于寻访与评分的文字要求。',
  },
  plan: {
    title: '执行方案',
    description: '选择业务目标、运行流程和本次作业参数。',
  },
  review: {
    title: '执行前检查',
    description: '确认全部运行条件；从执行方案继续时，全部通过后会自动开始执行。',
  },
}[currentStep.value]))

const checks = computed(() => [
  {
    key: 'job',
    label: '执行职位',
    ok: Boolean(selectedJob.value),
    detail: selectedJob.value ? selectedJob.value.title : '请先选择一个已同步的在招职位',
    link: !selectedJob.value ? { path: '/recruitment/admin', query: { section: 'jobs' } } : null,
  },
  {
    key: 'account',
    label: 'BOSS 账号',
    ok: Boolean(selectedAccount.value && selectedJob.value && String(selectedJob.value.boss_account) === String(selectedAccount.value.id)),
    detail: selectedAccount.value ? selectedAccount.value.name : '请选择与职位绑定的执行账号',
    link: !selectedAccount.value ? { path: '/recruitment/admin', query: { section: 'accounts' } } : null,
  },
  {
    key: 'browser',
    label: '隔离浏览器',
    ok: browserReady.value,
    detail: browserReady.value ? '已登录，可接受自动化任务' : accountReadinessMessage(selectedAccount.value),
    link: !browserReady.value ? { path: '/recruitment/admin', query: { section: 'accounts' } } : null,
  },
  {
    key: 'runtime',
    label: '本机自动化服务',
    ok: runtimeReady.value,
    detail: runtimeReady.value ? 'Worker 与 BOSS CLI 均在线' : 'Worker 或 BOSS CLI 未就绪，请先检查系统诊断',
    link: !runtimeReady.value ? { path: '/recruitment/admin', query: { section: 'diagnostics' } } : null,
  },
  {
    key: 'scheme',
    label: '执行方案',
    ok: (schemeKind.value === 'passive_resume' || schemeKind.value === 'active_resume_search')
      && (workflowChoice.value === 'standard' || Boolean(selectedCustomWorkflow.value)),
    detail: workflowChoice.value === 'standard'
      ? (schemeKind.value === 'passive_resume' ? '标准被动咨询与简历获取流程' : '标准主动搜索与简历获取流程')
      : (selectedCustomWorkflow.value ? `高级流程：${selectedCustomWorkflow.value.label}` : '所选高级流程已停用或不属于当前账号'),
  },
  {
    key: 'parameters',
    label: '运行参数',
    ok: schemeKind.value === 'passive_resume'
      ? passiveIntervalValid.value
      : activeCountValid.value && activeQueryValid.value,
    detail: parameterCheckMessage(),
    link: schemeKind.value === 'active_resume_search' && !coreItems.value.length
      ? { name: 'recruitment-workbench', query: { ...route.query, job: String(selectedJob.value?.id || ''), step: 'standard' } }
      : null,
  },
])
const firstBlockingCheck = computed(() => checks.value.find((item) => !item.ok) || null)
const currentPlanState = computed(() => normalizePlanState(controllablePlan()))
const startDisabledReason = computed(() => {
  if (loading.value) return '招聘作业台仍在加载，请稍候。'
  if (planLoading.value) return '正在同步服务端任务状态，请稍候。'
  if (planError.value) return `任务状态同步失败，请等待自动刷新后再试：${planError.value}`
  if (uploading.value) return '文件仍在上传，请等待完成。'
  if (submitting.value) return '任务指令正在处理，请勿重复提交。'
  if (currentStep.value !== 'review') return '请先完成执行方案，再进入执行前检查。'
  if (controllablePlan() && !['stopped', 'failed', 'completed'].includes(currentPlanState.value)) {
    return '当前任务尚未停止，不能开启新版本。'
  }
  if (legacyEditBaseUnknown.value && controllablePlan()) return '旧草稿缺少编辑基线，请先确认以服务端最新版本继续编辑。'
  if (firstBlockingCheck.value) return firstBlockingCheck.value.detail
  return ''
})
const canSubmit = computed(() => !startDisabledReason.value)

function requirementLines(value) {
  return [...new Set(String(value || '')
    .split(/\r?\n/)
    .map((item) => item.trim().slice(0, 200))
    .filter(Boolean))]
    .slice(0, 10)
}

function accountReadinessMessage(account) {
  if (!account) return '尚未选择执行账号'
  const messages = {
    ready: '已登录',
    browser_stopped: '隔离浏览器尚未启动，请先到管理后台启动并登录',
    waiting_login: '隔离浏览器已启动，等待 HR 完成 BOSS 登录',
    waiting_human: '账号正在等待验证码或人工验证',
    error: '账号状态异常，请在管理后台检查',
    unknown: '账号状态尚未检查，请在管理后台刷新状态',
  }
  return messages[account.login_status] || '账号尚未达到可执行状态'
}

function parameterCheckMessage() {
  if (schemeKind.value === 'passive_resume') {
    return passiveIntervalValid.value ? `每 ${interval.value} 分钟同步一次消息` : '同步间隔必须为 1–1440 分钟'
  }
  if (!coreItems.value.length) return '主动寻访至少填写一项核心要求'
  if (source.value === 'search' && !keyword.value.trim()) return '常规搜索需要填写搜索关键词'
  if (!activeCountValid.value) return '目标简历数为 1–100，最大扫描人数须不少于目标数且不超过 100'
  return `目标 ${targetResumeCount.value} 份，最多扫描 ${maxScanCount.value} 人`
}

function requestId() {
  return globalThis.crypto?.randomUUID?.()
    || `00000000-0000-4000-8000-${Date.now().toString().padStart(12, '0').slice(-12)}`
}

function normalizePlanState(plan) {
  const value = String(plan?.effective_state || plan?.actual_state || plan?.current_run?.status || plan?.desired_state || '')
  return {
    queued: 'starting',
    pending: 'starting',
    succeeded: 'completed',
    cancelled: 'stopped',
  }[value] || value || 'stopped'
}

function planRevisionSnapshot(plan) {
  const revision = plan?.current_revision
  if (!revision || typeof revision !== 'object') return { id: null, revision: null }
  return {
    id: revision.id ?? null,
    revision: revision.revision ?? revision.version ?? null,
  }
}

function revisionUsesCustomWorkflow(revision) {
  if (!revision || typeof revision !== 'object') return false
  const mode = String(revision.workflow_mode || '').toLowerCase()
  if (['custom', 'advanced'].includes(mode)) return true
  if (['managed', 'standard'].includes(mode)) return false
  if (typeof revision.is_managed_workflow === 'boolean') return !revision.is_managed_workflow
  return false
}

function workflowVersionIsPlanManaged(value) {
  const versionId = typeof value === 'object' ? value?.id : value
  const inlineVersion = value && typeof value === 'object' ? value : null
  const loadedVersion = workflowVersions.value.find((version) => String(version.id) === String(versionId)) || null
  if (inlineVersion?.is_plan_managed === true || loadedVersion?.is_plan_managed === true) return true
  const templateValue = inlineVersion?.template ?? loadedVersion?.template
  if (templateValue && typeof templateValue === 'object' && templateValue.is_plan_managed === true) return true
  const templateId = typeof templateValue === 'object' ? templateValue?.id : templateValue
  return workflowTemplates.value.some((template) => (
    String(template.id) === String(templateId) && template.is_plan_managed === true
  ))
}

function resetEditBase() {
  editBase.active = false
  editBase.jobId = ''
  editBase.controlVersion = 0
  editBase.revisionId = null
  editBase.revision = null
  legacyEditBaseUnknown.value = false
  planVersionNotice.value = ''
}

function captureEditBase(plan = controllablePlan()) {
  const jobId = selectedJob.value?.id
  if (!jobId) return
  const revision = planRevisionSnapshot(plan)
  editBase.active = true
  editBase.jobId = String(jobId)
  editBase.controlVersion = Number(plan?.control_version ?? 0)
  editBase.revisionId = revision.id
  editBase.revision = revision.revision
  legacyEditBaseUnknown.value = false
  planVersionNotice.value = ''
}

function ensureEditBase() {
  if (!selectedJob.value?.id || wizardHydrating.value || !wizardReady.value) return
  if (legacyEditBaseUnknown.value) return
  if (editBase.active && editBase.jobId === String(selectedJob.value.id)) return
  captureEditBase()
}

function serializedEditBase() {
  if (!editBase.active) return null
  return {
    jobId: editBase.jobId,
    controlVersion: editBase.controlVersion,
    revisionId: editBase.revisionId,
    revision: editBase.revision,
  }
}

function isValidStoredEditBase(value, jobId) {
  if (value === null) return true
  return isRecord(value)
    && String(value.jobId) === String(jobId)
    && Number.isInteger(value.controlVersion)
    && value.controlVersion >= 0
    && (value.revisionId == null || ['string', 'number'].includes(typeof value.revisionId))
    && (value.revision == null || ['string', 'number'].includes(typeof value.revision))
}

function restoreEditBase(stored, jobId) {
  resetEditBase()
  if (!Object.prototype.hasOwnProperty.call(stored, 'editBase')) {
    legacyEditBaseUnknown.value = true
    return
  }
  if (stored.editBase === null) return
  editBase.active = true
  editBase.jobId = String(jobId)
  editBase.controlVersion = Number(stored.editBase.controlVersion)
  editBase.revisionId = stored.editBase.revisionId ?? null
  editBase.revision = stored.editBase.revision ?? null
}

function editBaseDiffersFrom(plan) {
  if (!editBase.active || editBase.jobId !== String(selectedJob.value?.id || '')) return false
  const revision = planRevisionSnapshot(plan)
  return editBase.controlVersion !== Number(plan?.control_version ?? 0)
    || String(editBase.revisionId ?? '') !== String(revision.id ?? '')
    || String(editBase.revision ?? '') !== String(revision.revision ?? '')
}

function updatePlanVersionNotice(plan) {
  if (legacyEditBaseUnknown.value && plan) {
    planVersionNotice.value = '这个旧草稿没有记录编辑基线。请确认以服务端最新版本继续编辑后再提交。'
    return
  }
  if (!editBaseDiffersFrom(plan)) {
    planVersionNotice.value = ''
    return
  }
  const latest = planRevisionSnapshot(plan)
  const baseLabel = editBase.revision ?? editBase.revisionId ?? '初始'
  const latestLabel = latest.revision ?? latest.id ?? '最新'
  planVersionNotice.value = `服务端方案已从 V${baseLabel} 更新为 V${latestLabel}。当前草稿仍基于原版本，提交时会保留冲突保护。`
}

function rebaseEditDraft() {
  captureEditBase(controllablePlan())
  submitError.value = ''
  persistWizardDraft()
}

function operationDraft() {
  return {
    schemeKind: schemeKind.value,
    workflowChoice: workflowChoice.value,
    coreText: coreText.value,
    bonusText: bonusText.value,
    interval: Number(interval.value),
    source: source.value,
    keyword: keyword.value,
    candidateFilters: normalizeCandidateFilters(candidateFilters.value),
    targetResumeCount: Number(targetResumeCount.value),
    maxScanCount: Number(maxScanCount.value),
  }
}

function operationFingerprint({
  jobId = selectedJob.value?.id || null,
  accountId = selectedAccountId.value || null,
  draft = operationDraft(),
} = {}) {
  return JSON.stringify({
    job: jobId,
    account: accountId,
    ...draft,
  })
}

function reportStorageUnavailable() {
  storageNotice.value = '浏览器临时存储不可用，本次仍可继续操作，但刷新页面后草稿和重试进度可能无法恢复。'
}

function readSessionItem(key) {
  try {
    const storage = globalThis.sessionStorage
    if (!storage) throw new Error('sessionStorage unavailable')
    return storage.getItem(key)
  } catch {
    reportStorageUnavailable()
    return null
  }
}

function writeSessionItem(key, value) {
  try {
    const storage = globalThis.sessionStorage
    if (!storage) throw new Error('sessionStorage unavailable')
    storage.setItem(key, JSON.stringify(value))
    return true
  } catch {
    reportStorageUnavailable()
    return false
  }
}

function removeSessionItem(key) {
  try {
    const storage = globalThis.sessionStorage
    if (!storage) throw new Error('sessionStorage unavailable')
    storage.removeItem(key)
    return true
  } catch {
    reportStorageUnavailable()
    return false
  }
}

function wizardStorageKey(jobId = selectedJob.value?.id) {
  if (!jobId) return ''
  return `ximing-hr:recruitment-workbench-draft:v${WIZARD_DRAFT_VERSION}:${auth.user?.id || 'unknown'}:${jobId}`
}

function workbenchResetStorageKey() {
  return `ximing-hr:recruitment-workbench-reset:v${WORKBENCH_RESET_VERSION}:${auth.user?.id || 'unknown'}`
}

function scheduleFreshWorkbench() {
  writeSessionItem(workbenchResetStorageKey(), { pending: true })
}

function consumeFreshWorkbench() {
  const key = workbenchResetStorageKey()
  const pending = Boolean(readSessionItem(key))
  if (pending) removeSessionItem(key)
  return pending
}

function resetWizardFields() {
  autoStartRequested.value = false
  schemeKind.value = 'passive_resume'
  workflowChoice.value = 'standard'
  coreText.value = ''
  bonusText.value = ''
  interval.value = 2
  source.value = 'search'
  keyword.value = ''
  candidateFilters.value = defaultCandidateFilters()
  targetResumeCount.value = 3
  maxScanCount.value = 20
  completedSteps.context = false
  completedSteps.standard = false
  completedSteps.plan = false
  restoredWizardStep.value = 'context'
  currentStep.value = 'context'
  wizardError.value = ''
  dragging.value = false
  uploadQueue.value = []
  resetEditBase()
}

function persistWizardDraft(jobId = selectedJob.value?.id) {
  if (!wizardReady.value || wizardHydrating.value || !jobId) return
  const key = wizardStorageKey(jobId)
  if (!key) return
  writeSessionItem(key, {
    version: WIZARD_DRAFT_VERSION,
    jobId: String(jobId),
    selectedAccountId: String(selectedAccountId.value || ''),
    step: currentStep.value,
    completed: {
      context: completedSteps.context,
      standard: completedSteps.standard,
      plan: completedSteps.plan,
    },
    documentCategory: JOB_DOCUMENT_CATEGORY,
    draft: operationDraft(),
    editBase: serializedEditBase(),
  })
}

function isRecord(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function isValidWizardDraft(stored, jobId) {
  if (!isRecord(stored) || stored.version !== WIZARD_DRAFT_VERSION || String(stored.jobId) !== String(jobId)) return false
  if (typeof stored.selectedAccountId !== 'string') return false
  if (!WIZARD_STEPS.includes(stored.step)) return false
  if (!isRecord(stored.completed)
    || typeof stored.completed.context !== 'boolean'
    || typeof stored.completed.standard !== 'boolean'
    || (Object.prototype.hasOwnProperty.call(stored.completed, 'plan')
      && typeof stored.completed.plan !== 'boolean')) return false
  if (Object.prototype.hasOwnProperty.call(stored, 'editBase') && !isValidStoredEditBase(stored.editBase, jobId)) return false
  const draft = stored.draft
  return isRecord(draft)
    && ['passive_resume', 'active_resume_search'].includes(draft.schemeKind)
    && typeof draft.workflowChoice === 'string'
    && Boolean(draft.workflowChoice)
    && typeof draft.coreText === 'string'
    && typeof draft.bonusText === 'string'
    && Number.isFinite(draft.interval)
    && ['search', 'recommend', 'deep_search'].includes(draft.source)
    && typeof draft.keyword === 'string'
    && (!Object.prototype.hasOwnProperty.call(draft, 'candidateFilters')
      || (draft.candidateFilters && typeof draft.candidateFilters === 'object' && !Array.isArray(draft.candidateFilters)))
    && Number.isFinite(draft.targetResumeCount)
    && Number.isFinite(draft.maxScanCount)
}

function restoreWizardDraft(jobId = selectedJob.value?.id) {
  const key = wizardStorageKey(jobId)
  if (!key) return false
  try {
    const serialized = readSessionItem(key)
    if (!serialized) return false
    const stored = JSON.parse(serialized)
    if (!isValidWizardDraft(stored, jobId)) {
      removeSessionItem(key)
      return false
    }
    applyOperationDraft(stored.draft)
    restoreEditBase(stored, jobId)
    completedSteps.context = stored.completed?.context === true
    completedSteps.standard = stored.completed?.standard === true
    completedSteps.plan = stored.completed?.plan === true
    restoredWizardStep.value = stored.step
    return true
  } catch {
    removeSessionItem(key)
    return false
  }
}

function guardedWizardStep(requested) {
  const normalized = WIZARD_STEPS.includes(requested) ? requested : 'context'
  if (normalized === 'standard' && !completedSteps.context) return 'context'
  if (normalized === 'plan') {
    if (!completedSteps.context) return 'context'
    if (!completedSteps.standard) return 'standard'
  }
  if (normalized === 'review') {
    if (!completedSteps.context) return 'context'
    if (!completedSteps.standard) return 'standard'
    if (!completedSteps.plan) return 'plan'
  }
  return normalized
}

async function focusCurrentStep({ resetScroll = false } = {}) {
  await nextTick()
  if (resetScroll && workbenchMain.value) workbenchMain.value.scrollTop = 0
  stepHeading.value?.focus?.()
}

function resolveWizardStep({ replaceInvalid = true } = {}) {
  if (!wizardReady.value) return
  if (restoreBusyRouteIfNeeded()) return
  const queryStep = Array.isArray(route.query.step)
    ? String(route.query.step[0] || '')
    : String(route.query.step || '')
  const hasExplicitStep = Boolean(queryStep)
  const invalidStep = hasExplicitStep && !WIZARD_STEPS.includes(queryStep)
  const requested = invalidStep
    ? 'context'
    : (hasExplicitStep ? queryStep : restoredWizardStep.value)
  const guarded = guardedWizardStep(requested)
  if (invalidStep) {
    wizardError.value = '步骤参数无效，已安全返回第一步。'
  } else if (hasExplicitStep && guarded !== requested) {
    wizardError.value = requested === 'review'
      ? '请先完成职位、招聘标准和执行方案，再进入执行前检查。'
      : (requested === 'plan'
          ? '请先完成前置步骤，再进入执行方案。'
          : '请先完成职位与账号确认，再进入招聘标准。')
  }
  currentStep.value = guarded
  const jobId = selectedJob.value?.id
  const queryJob = Array.isArray(route.query.job)
    ? String(route.query.job[0] || '')
    : String(route.query.job || '')
  const shouldAttachSelectedJob = Boolean(jobId && !queryJob && !routeJobError.value)
  if (replaceInvalid && (queryStep !== guarded || shouldAttachSelectedJob || routeJobError.value)) {
    const query = { ...route.query, step: guarded }
    if (routeJobError.value) delete query.job
    else if (shouldAttachSelectedJob) query.job = String(jobId)
    router.replace({ name: route.name, query }).catch(() => {})
  }
  persistWizardDraft()
  focusCurrentStep()
}

function navigateWizardStep(step, { replace = false } = {}) {
  const guarded = guardedWizardStep(step)
  if (guarded !== 'review') autoStartRequested.value = false
  currentStep.value = guarded
  restoredWizardStep.value = guarded
  wizardError.value = ''
  persistWizardDraft()
  const query = { ...route.query, step: guarded }
  delete query.new
  delete query.editPlan
  if (selectedJob.value?.id) query.job = String(selectedJob.value.id)
  const navigation = replace ? router.replace : router.push
  navigation.call(router, { name: route.name, query }).catch(() => {})
  focusCurrentStep()
}

function completeContextStep() {
  wizardError.value = ''
  if (!contextStepComplete.value) {
    wizardError.value = '请选择属于同一授权范围的在招职位和 BOSS 账号'
    return
  }
  completedSteps.context = true
  persistWizardDraft()
  navigateWizardStep('standard')
}

function completeStandardStep() {
  wizardError.value = ''
  if (uploading.value) {
    wizardError.value = '文件仍在上传，请等待全部文件处理完成'
    return
  }
  completedSteps.standard = true
  persistWizardDraft()
  navigateWizardStep('plan')
}

function completePlanStep() {
  wizardError.value = ''
  completedSteps.plan = true
  autoStartRequested.value = true
  persistWizardDraft()
  navigateWizardStep('review')
}

function previousStep() {
  const index = WIZARD_STEPS.indexOf(currentStep.value)
  if (index > 0) navigateWizardStep(WIZARD_STEPS[index - 1])
}

function markStandardDirty() {
  if (!wizardReady.value || wizardHydrating.value) return
  ensureEditBase()
  completedSteps.standard = false
  completedSteps.plan = false
  persistWizardDraft()
}

function markPlanDirty() {
  if (!wizardReady.value || wizardHydrating.value || currentStep.value !== 'plan') return
  ensureEditBase()
  completedSteps.plan = false
  persistWizardDraft()
}

function applyOperationDraft(draft) {
  if (!draft) return
  schemeKind.value = draft.schemeKind || 'passive_resume'
  workflowChoice.value = draft.workflowChoice || 'standard'
  coreText.value = draft.coreText || ''
  bonusText.value = draft.bonusText || ''
  interval.value = Number(draft.interval || 2)
  source.value = draft.source || 'search'
  keyword.value = draft.keyword || ''
  candidateFilters.value = normalizeCandidateFilters(draft.candidateFilters)
  targetResumeCount.value = Number(draft.targetResumeCount || 3)
  maxScanCount.value = Number(draft.maxScanCount || 20)
}

function replaceJobQuery(jobId, { step } = {}) {
  const query = { ...route.query }
  delete query.new
  delete query.editPlan
  if (jobId) query.job = String(jobId)
  else delete query.job
  if (step) query.step = step
  router.replace({ name: route.name, query }).catch(() => {})
}

function chooseJob(jobId, { updateRoute = true } = {}) {
  const normalized = jobId === null || jobId === undefined ? '' : String(jobId)
  const job = context.jobs.find((item) => String(item.id) === normalized)
  if (!job) return
  freshWorkbenchLocked = false
  routeJobError.value = ''
  const changed = String(selectedJob.value?.id || '') !== String(job.id)
  context.selectJob(job.id, { userId: auth.user?.id || context.loadedUserId })
  selectedAccountId.value = job.boss_account ? String(job.boss_account) : ''
  if (updateRoute) replaceJobQuery(job.id, { step: changed ? 'context' : currentStep.value })
}

function chooseAccount() {
  submitError.value = ''
  const currentBelongsToAccount = selectedJob.value
    && String(selectedJob.value.boss_account) === String(selectedAccountId.value)
  if (currentBelongsToAccount) return
  const firstJob = jobsForAccount.value[0]
  if (firstJob) {
    chooseJob(firstJob.id)
    return
  }
  context.invalidateSelection({
    userId: auth.user?.id || context.loadedUserId,
    reason: '所选账号暂无已同步的在招职位',
  })
  replaceJobQuery('')
}

function routeQueryValue(value) {
  const candidate = Array.isArray(value) ? value[0] : value
  return candidate === null || candidate === undefined ? '' : String(candidate)
}

function busyNavigationLock() {
  if (activeExecutionSnapshot) {
    return { jobId: String(activeExecutionSnapshot.job.id), step: 'review' }
  }
  return activeUploadLock
}

function restoreBusyRouteIfNeeded() {
  const lock = busyNavigationLock()
  if (!lock) return false
  const queryJobId = routeQueryValue(route.query.job)
  const queryStep = routeQueryValue(route.query.step)
  if (queryJobId === lock.jobId && queryStep === lock.step) return false
  wizardError.value = '任务处理中，暂不能切换职位或步骤；已恢复到本次任务页面。'
  router.replace({
    name: route.name,
    query: { ...route.query, job: lock.jobId, step: lock.step },
  }).catch(() => {})
  return true
}

function invalidateRouteJob(jobId) {
  const message = `职位 ${jobId} 已失效、不再开放或无权访问，请重新选择。`
  const wasHydrating = wizardHydrating.value
  const previousJobId = selectedJob.value?.id ? String(selectedJob.value.id) : ''
  if (previousJobId) {
    persistWizardDraft(previousJobId)
    skipPreviousJobPersistFor = previousJobId
  }
  wizardHydrating.value = true
  routeJobError.value = message
  resetWizardFields()
  selectedAccountId.value = ''
  planLoadSequence += 1
  currentPlan.value = null
  archivedPlan.value = null
  planError.value = ''
  submitError.value = ''
  try {
    context.invalidateSelection({
      userId: auth.user?.id || context.loadedUserId,
      reason: message,
    })
  } catch {
    context.selectedJobId = ''
    context.invalidationReason = message
  }
  if (previousJobId) {
    nextTick(() => {
      if (skipPreviousJobPersistFor === previousJobId) skipPreviousJobPersistFor = ''
    })
  }
  wizardHydrating.value = wasHydrating
  const query = { ...route.query, step: 'context' }
  delete query.job
  router.replace({ name: route.name, query }).catch(() => {})
  if (wizardReady.value) focusCurrentStep()
  return false
}

function alignInitialSelection() {
  const queryJobId = routeQueryValue(route.query.job)
  if (queryJobId && context.jobs.some((job) => String(job.id) === queryJobId)) {
    chooseJob(queryJobId, { updateRoute: false })
    return true
  }
  if (queryJobId) {
    return invalidateRouteJob(queryJobId)
  }
  routeJobError.value = ''
  if (selectedJob.value) {
    selectedAccountId.value = selectedJob.value.boss_account ? String(selectedJob.value.boss_account) : ''
    replaceJobQuery(selectedJob.value.id)
    return true
  }
  const defaultJob = context.jobs.find((job) => accounts.value.some((account) => (
    String(account.id) === String(job.boss_account) && account.login_status === 'ready'
  ))) || context.jobs[0]
  if (defaultJob) chooseJob(defaultJob.id)
  else if (accounts.value[0]) selectedAccountId.value = String(accounts.value[0].id)
  return Boolean(defaultJob)
}

function syncJobFromRoute(value) {
  if (freshWorkbenchLocked) return
  if (!wizardReady.value) return
  if (restoreBusyRouteIfNeeded()) return
  const jobId = routeQueryValue(value)
  if (!jobId) {
    resolveWizardStep()
    return
  }
  const job = context.jobs.find((item) => String(item.id) === jobId)
  if (!job) {
    invalidateRouteJob(jobId)
    return
  }
  routeJobError.value = ''
  if (String(selectedJob.value?.id || '') !== jobId) {
    chooseJob(jobId, { updateRoute: false })
    return
  }
  resolveWizardStep()
}

function planFromPayload(payload) {
  if (payload && typeof payload === 'object' && !Array.isArray(payload) && payload.id) return payload
  return listItems(payload)[0] || null
}

function planJobId(plan) {
  return typeof plan?.job === 'object' ? plan.job?.id : plan?.job
}

function operationDraftFromRevision(plan) {
  const revision = plan?.current_revision
  if (!revision || typeof revision !== 'object') return null
  const config = revision.config || revision.config_snapshot || {}
  const revisionWorkflow = revision.workflow_version
  const revisionWorkflowId = typeof revisionWorkflow === 'object' ? revisionWorkflow?.id : revisionWorkflow
  return {
    schemeKind: plan.kind || 'passive_resume',
    workflowChoice: revisionUsesCustomWorkflow(revision)
      && revisionWorkflowId
      && !workflowVersionIsPlanManaged(revisionWorkflow)
      ? `custom:${revisionWorkflowId}`
      : 'standard',
    coreText: Array.isArray(config.core) ? config.core.join('\n') : '',
    bonusText: Array.isArray(config.bonus) ? config.bonus.join('\n') : '',
    interval: Number(config.interval_minutes ?? 2),
    source: config.source || 'search',
    keyword: config.keyword || '',
    candidateFilters: normalizeCandidateFilters(config.candidate_filters),
    targetResumeCount: Number(config.target_resume_count ?? 3),
    maxScanCount: Number(config.max_scan_count ?? 20),
  }
}

function applyServerPlan(plan, jobId, { hydrateDraft = false } = {}) {
  if (!componentAlive || String(selectedJob.value?.id || '') !== String(jobId || '')) return false
  const serverPlan = plan || archivedPlan.value
  if (serverPlan && planJobId(serverPlan) != null && String(planJobId(serverPlan)) !== String(jobId)) return false
  currentPlan.value = plan
  planError.value = ''
  if (legacyEditBaseUnknown.value && !serverPlan) captureEditBase(null)
  if (serverPlan && hydrateDraft) {
    const revisionDraft = operationDraftFromRevision(serverPlan)
    if (revisionDraft) applyOperationDraft(revisionDraft)
    completedSteps.context = true
    completedSteps.standard = true
    completedSteps.plan = true
    restoredWizardStep.value = 'review'
  }
  updatePlanVersionNotice(serverPlan)
  return true
}

async function refreshCurrentPlan({ jobId = selectedJob.value?.id, silent = false, poll = false, hydrateDraft = false } = {}) {
  if (!jobId || !componentAlive) return null
  if (poll && planPollInFlight) return null
  const sequence = ++planLoadSequence
  if (poll) planPollInFlight = true
  if (!silent) planLoading.value = true
  try {
    const payload = await api(`recruitment/automation-plans/?job=${encodeURIComponent(jobId)}`)
    const plan = planFromPayload(payload)
    let removedPlan = null
    if (!plan) {
      const archivedPayload = await api(`recruitment/automation-plans/?job=${encodeURIComponent(jobId)}&archived=1`)
      removedPlan = planFromPayload(archivedPayload)
    }
    if (sequence === planLoadSequence) {
      archivedPlan.value = removedPlan
      applyServerPlan(plan, jobId, { hydrateDraft })
    }
    return plan || removedPlan
  } catch (error) {
    if (sequence === planLoadSequence && String(selectedJob.value?.id || '') === String(jobId)) {
      planError.value = error.message || '任务状态读取失败'
    }
    return null
  } finally {
    if (poll) planPollInFlight = false
    if (!silent && sequence === planLoadSequence) planLoading.value = false
  }
}

function enterPlanEdit() {
  captureEditBase(controllablePlan())
  completedSteps.context = true
  completedSteps.standard = false
  completedSteps.plan = false
  submitError.value = ''
  persistWizardDraft()
  navigateWizardStep('standard')
}

async function loadWorkbench() {
  loading.value = true
  loadError.value = ''
  wizardHydrating.value = true
  let createFresh = false
  try {
    if (!context.loaded) {
      await context.loadJobs({ userId: auth.user?.id })
    }
    const [accountResult, summaryResult, templateResult, versionResult] = await Promise.allSettled([
      api('recruitment/boss-accounts/'),
      api('recruitment/automation/summary/'),
      api('recruitment/workflows/'),
      api('recruitment/workflow-versions/'),
    ])
    if (accountResult.status === 'rejected') throw accountResult.reason
    accounts.value = listItems(accountResult.value).filter((account) => account.active && !account.archived_at)
    workflowTemplates.value = templateResult.status === 'fulfilled' ? listItems(templateResult.value) : []
    workflowVersions.value = versionResult.status === 'fulfilled' ? listItems(versionResult.value) : []
    if (summaryResult.status === 'fulfilled') Object.assign(summary, summaryResult.value)
    else loadError.value = `自动化服务状态读取失败：${summaryResult.reason?.message || '请稍后重试'}`
    const editPlanId = routeQueryValue(route.query.editPlan)
    createFresh = !editPlanId && (routeQueryValue(route.query.new) === '1' || freshWorkbenchOnMount)
    freshWorkbenchLocked = createFresh
    if (createFresh) {
      context.invalidateSelection({ userId: auth.user?.id || context.loadedUserId, reason: '' })
      selectedAccountId.value = ''
      resetWizardFields()
      const query = { ...route.query, new: '1', step: 'context' }
      delete query.job
      delete query.editPlan
      await router.replace({ name: route.name, query }).catch(() => {})
    }
    const hasValidSelection = createFresh ? false : alignInitialSelection()
    if (hasValidSelection) {
      restoreWizardDraft(selectedJob.value?.id)
      const plan = await refreshCurrentPlan({ jobId: selectedJob.value?.id, hydrateDraft: Boolean(editPlanId) })
      if (plan && editPlanId && String(plan.id) === editPlanId) enterPlanEdit()
    }
  } catch (error) {
    loadError.value = error.message || '招聘作业台加载失败'
  } finally {
    wizardHydrating.value = false
    loading.value = false
    wizardReady.value = true
    if (createFresh) {
      context.invalidateSelection({ userId: auth.user?.id || context.loadedUserId, reason: '' })
      const query = { ...route.query, new: '1', step: 'context' }
      delete query.job
      delete query.editPlan
      await router.replace({ name: route.name, query }).catch(() => {})
    }
    resolveWizardStep()
  }
}

async function loadDocuments(jobId) {
  if (!jobId) {
    documents.value = []
    return
  }
  const sequence = ++documentLoadSequence
  documentsLoading.value = true
  documentError.value = ''
  try {
    const payload = await api(`recruitment/job-documents/?job=${jobId}`)
    if (sequence === documentLoadSequence) documents.value = listItems(payload)
  } catch (error) {
    if (sequence === documentLoadSequence) documentError.value = error.message || '岗位依据读取失败'
  } finally {
    if (sequence === documentLoadSequence) documentsLoading.value = false
  }
}

function validateDocumentFile(file) {
  if (!JOB_DOCUMENT_SUFFIX.test(file.name || '')) return '仅支持 DOC、DOCX 或 XLSX'
  if (!Number(file.size)) return '文件不能为空'
  if (file.size > MAX_JOB_DOCUMENT_SIZE) return '单个文件不能超过 25MB'
  return ''
}

function selectDocuments(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  handleDocumentFiles(files)
}

function dropDocuments(event) {
  dragging.value = false
  handleDocumentFiles([...(event.dataTransfer?.files || [])])
}

async function handleDocumentFiles(files) {
  if (!files.length || !selectedJob.value || uploading.value) return
  markStandardDirty()
  documentError.value = ''
  const batchId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  const queue = files.map((file, index) => {
    const validationError = validateDocumentFile(file)
    return {
      id: `${batchId}-${index}`,
      file: validationError ? null : file,
      name: file.name || `未命名文件 ${index + 1}`,
      size: Number(file.size || 0),
      status: validationError ? 'failed' : 'pending',
      error: validationError,
    }
  })
  uploadQueue.value = queue
  uploadProgress.completed = queue.filter((item) => item.status === 'failed').length
  uploadProgress.total = queue.length
  uploadProgress.failed = uploadProgress.completed
  const validItems = queue.filter((item) => item.status === 'pending')
  if (!validItems.length) {
    documentError.value = '所选文件均未通过上传校验'
    return
  }

  const jobId = selectedJob.value.id
  activeUploadLock = { jobId: String(jobId), step: 'standard' }
  uploading.value = true
  const failedFiles = queue
    .filter((item) => item.status === 'failed')
    .map((item) => `${item.name}：${item.error}`)
  let succeeded = 0
  try {
    for (const item of validItems) {
      item.status = 'uploading'
      const body = new FormData()
      body.append('job', String(jobId))
      body.append('category', JOB_DOCUMENT_CATEGORY)
      body.append('title', item.name.replace(/\.(doc|docx|xlsx)$/i, ''))
      body.append('file', item.file)
      try {
        await api('recruitment/job-documents/', { method: 'POST', body })
        item.status = 'succeeded'
        item.file = null
        succeeded += 1
      } catch (error) {
        item.status = 'failed'
        item.error = error.message || '上传失败'
        item.file = null
        uploadProgress.failed += 1
        failedFiles.push(`${item.name}：${item.error}`)
      } finally {
        uploadProgress.completed += 1
      }
    }
    if (succeeded) await loadDocuments(jobId)
    if (failedFiles.length) documentError.value = `部分文件未上传：${failedFiles.join('；')}`
  } finally {
    uploading.value = false
    activeUploadLock = null
  }
}

function createExecutionSnapshot() {
  const draft = Object.freeze({ ...operationDraft() })
  const requirements = Object.freeze({
    core: Object.freeze([...coreItems.value]),
    bonus: Object.freeze([...bonusItems.value]),
  })
  const job = Object.freeze({
    id: selectedJob.value.id,
    title: selectedJob.value.title,
  })
  const account = Object.freeze({
    id: Number(selectedAccountId.value),
    name: selectedAccount.value.name,
  })
  const workflow = Object.freeze({
    choice: draft.workflowChoice,
    customId: selectedCustomWorkflow.value?.id || null,
  })
  const config = Object.freeze(draft.schemeKind === 'passive_resume'
    ? {
        interval_minutes: Number(draft.interval),
        reply_message: '您好，这边是招聘岗位，方便发送一份简历进一步沟通吗？',
        core: requirements.core,
        bonus: requirements.bonus,
      }
    : {
        source: draft.source,
        keyword: draft.keyword.trim(),
        candidate_filters: normalizeCandidateFilters(draft.candidateFilters),
        target_resume_count: Number(draft.targetResumeCount),
        max_scan_count: Number(draft.maxScanCount),
        core: requirements.core,
        bonus: requirements.bonus,
      })
  const fingerprint = operationFingerprint({ jobId: job.id, accountId: account.id, draft })
  return Object.freeze({
    job,
    account,
    scheme: draft.schemeKind,
    draft,
    requirements,
    workflow,
    config,
    fingerprint,
  })
}

async function startExecution() {
  if (submitting.value) return
  if (!canSubmit.value) {
    submitError.value = firstBlockingCheck.value?.detail || '请先完成执行前检查'
    return
  }
  submitting.value = true
  planLoadSequence += 1
  submitError.value = ''
  let snapshot = null
  try {
    snapshot = createExecutionSnapshot()
    activeExecutionSnapshot = snapshot
    ensureEditBase()
    const command = {
      job: Number(snapshot.job.id),
      kind: snapshot.scheme,
      config: snapshot.config,
      expected_control_version: editBase.active && editBase.jobId === String(snapshot.job.id)
        ? editBase.controlVersion
        : Number(controllablePlan()?.control_version ?? 0),
    }
    if (snapshot.workflow.customId) command.workflow_version = Number(snapshot.workflow.customId)
    const signature = JSON.stringify(command)
    if (startRequest.signature !== signature) {
      startRequest.id = requestId()
      startRequest.signature = signature
    }
    submitStage.value = '正在原子开启招聘任务…'
    const plan = await api('recruitment/automation-plans/start/', {
      method: 'POST',
      body: JSON.stringify({
        request_id: startRequest.id,
        ...command,
      }),
    })
    planLoadSequence += 1
    resetEditBase()
    applyServerPlan(plan, snapshot.job.id)
    startRequest.id = ''
    startRequest.signature = ''
    submitStage.value = ''
    wizardReady.value = false
    removeSessionItem(wizardStorageKey(snapshot.job.id))
    scheduleFreshWorkbench()
    try {
      await router.replace({
        name: 'recruitment-task-detail',
        params: { planId: String(plan.id) },
        query: {
          job: String(snapshot.job.id),
          run: plan.current_run?.id ? String(plan.current_run.id) : undefined,
          view: 'tasks',
        },
      })
    } catch {
      submitError.value = '任务已经创建，但结果中心任务页未能打开；请从顶部“结果中心”的任务运行中进入。'
    }
  } catch (error) {
    if (error.status === 409 && snapshot) {
      await refreshCurrentPlan({ jobId: snapshot.job.id, silent: true })
      submitError.value = `服务端拒绝启动：${error.message || '任务状态刚刚发生变化'}。已为你刷新任务状态；请确认最新版本后重试。`
    } else {
      submitError.value = `${submitStage.value ? `${submitStage.value.replace(/正在|…/g, '')}失败：` : ''}${error.message || '无法创建招聘作业'}`
    }
  } finally {
    submitting.value = false
    if (activeExecutionSnapshot === snapshot) activeExecutionSnapshot = null
    submitStage.value = ''
  }
}

function attemptRequestedAutoStart() {
  if (!autoStartRequested.value) return
  if (currentStep.value !== 'review') {
    autoStartRequested.value = false
    return
  }
  if (loading.value || planLoading.value || submitting.value) return
  if (planError.value || firstBlockingCheck.value || !canSubmit.value) {
    autoStartRequested.value = false
    return
  }
  autoStartRequested.value = false
  startExecution()
}

const freshWorkbenchOnMount = consumeFreshWorkbench()
freshWorkbenchLocked = freshWorkbenchOnMount || routeQueryValue(route.query.new) === '1'

watch(currentStep, (step, previousStep) => {
  if (step !== previousStep) focusCurrentStep({ resetScroll: true })
}, { flush: 'sync' })

watch(
  [currentStep, loading, planLoading, currentPlan, firstBlockingCheck, canSubmit],
  () => attemptRequestedAutoStart(),
  { flush: 'post' },
)

watch(
  () => selectedJob.value?.id,
  (jobId, previousJobId) => {
    if (previousJobId && String(previousJobId) !== String(jobId)) {
      if (skipPreviousJobPersistFor === String(previousJobId)) skipPreviousJobPersistFor = ''
      else persistWizardDraft(previousJobId)
    }
    wizardHydrating.value = true
    documentLoadSequence += 1
    planLoadSequence += 1
    documents.value = []
    currentPlan.value = null
    archivedPlan.value = null
    planError.value = ''
    startRequest.id = ''
    startRequest.signature = ''
    submitError.value = ''
    resetWizardFields()
    if (jobId) {
      const job = context.jobs.find((item) => String(item.id) === String(jobId))
      routeJobError.value = ''
      selectedAccountId.value = job?.boss_account ? String(job.boss_account) : ''
      loadDocuments(jobId)
      restoreWizardDraft(jobId)
      if (wizardReady.value) refreshCurrentPlan({ jobId, hydrateDraft: false })
    }
    wizardHydrating.value = false
    if (previousJobId && String(previousJobId) !== String(jobId)) {
      currentStep.value = 'context'
      restoredWizardStep.value = 'context'
      replaceJobQuery(jobId, { step: 'context' })
    } else if (wizardReady.value) resolveWizardStep()
  },
  { immediate: true },
)

watch(schemeKind, () => {
  submitError.value = ''
})

watch(
  () => route.query.job,
  (value) => syncJobFromRoute(value),
)

watch(
  () => route.query.step,
  () => resolveWizardStep(),
)

watch([coreText, bonusText], () => {
  if (currentStep.value === 'standard') markStandardDirty()
}, { flush: 'sync' })

watch(
  [schemeKind, workflowChoice, interval, source, keyword, candidateFilters, targetResumeCount, maxScanCount, selectedAccountId],
  () => {
    if (currentStep.value === 'standard' || currentStep.value === 'plan') ensureEditBase()
    markPlanDirty()
    persistWizardDraft()
  },
)

watch(
  () => [completedSteps.context, completedSteps.standard, completedSteps.plan, currentStep.value],
  () => persistWizardDraft(),
)

watch(enabledWorkflowOptions, (options) => {
  if (workflowChoice.value !== 'standard' && !options.some((item) => `custom:${item.id}` === workflowChoice.value)) {
    workflowChoice.value = 'standard'
  }
})

onMounted(async () => {
  await loadWorkbench()
  if (!componentAlive) return
  planPollTimer = globalThis.setInterval(() => {
    refreshCurrentPlan({ silent: true, poll: true })
  }, 5000)
})

onUnmounted(() => {
  componentAlive = false
  planLoadSequence += 1
  documentLoadSequence += 1
  if (planPollTimer) globalThis.clearInterval(planPollTimer)
  planPollTimer = null
})
</script>

<template>
  <div class="page-stack recruitment-workbench">
    <section v-if="loading" class="workbench-card workbench-card--loading" aria-live="polite">
      <aside class="workbench-sidebar" aria-hidden="true">
        <header class="workbench-sidebar__intro">
          <strong>招聘准备</strong>
          <p>依次完成四个步骤，建立一次清晰可控的招聘作业。</p>
        </header>
      </aside>
      <div class="workbench-workspace">
        <header class="workbench-task-header">
          <div>
            <h2>正在准备招聘作业</h2>
          </div>
          <p>正在读取职位、账号与运行条件。</p>
        </header>
        <div class="workbench-loading">
          <span></span><span></span><span></span>
          <p>正在读取职位、账号与运行条件…</p>
        </div>
      </div>
    </section>

    <section v-else class="workbench-card" data-test="workbench-card">
      <aside class="workbench-sidebar">
        <header class="workbench-sidebar__intro">
          <strong>招聘准备</strong>
        </header>
        <nav class="workbench-wizard" aria-label="招聘作业步骤">
          <button
            v-for="step in wizardSteps"
            :key="step.key"
            :class="['workbench-wizard__step', { 'is-current': currentStep === step.key, 'is-complete': completedSteps[step.key] }]"
            :data-test="`wizard-step-${step.key}`"
            type="button"
            :disabled="!step.reachable || uploading || submitting"
            :aria-current="currentStep === step.key ? 'step' : undefined"
            @click="navigateWizardStep(step.key)"
          >
            <span>
              <AppIcon v-if="completedSteps[step.key] && currentStep !== step.key" name="check-circle" :size="20" />
              <template v-else>{{ step.number }}</template>
            </span>
            <strong>{{ step.label }}</strong>
            <small v-if="currentStep === step.key">进行中</small>
            <small v-else-if="completedSteps[step.key]">已完成</small>
          </button>
        </nav>
      </aside>

      <div class="workbench-workspace">
        <header class="workbench-task-header">
          <div class="workbench-task-header__title">
            <h2 id="workbench-current-title" ref="stepHeading" tabindex="-1">{{ currentStepCopy.title }}</h2>
          </div>
          <p class="sr-only">{{ currentStepCopy.description }}</p>
        </header>

        <div class="workbench-notices">
          <p v-if="loadError" class="workbench-error" role="alert">{{ loadError }}</p>
          <p v-if="routeJobError" class="workbench-error" role="alert">{{ routeJobError }}</p>
          <p v-if="wizardError" class="workbench-error" role="alert">{{ wizardError }}</p>
          <p v-if="storageNotice" class="workbench-storage-notice" role="status">
            <AppIcon name="alert-circle" :size="16" /> {{ storageNotice }}
          </p>
        </div>

        <main ref="workbenchMain" class="workbench-main">
          <section
            v-if="currentStep === 'context'"
            class="workbench-section workbench-section--context"
            data-test="workbench-step-context"
            aria-labelledby="workbench-current-title"
          >
            <div class="workbench-context-grid">
              <label>
                <span>在招职位</span>
                <select v-model="selectedJobValue" data-test="workbench-job" :disabled="uploading || submitting || !context.jobs.length">
                  <option value="">请选择在招职位</option>
                  <option v-for="job in context.jobs" :key="job.id" :value="String(job.id)">
                    {{ job.title }}{{ job.department ? ` · ${job.department}` : '' }}
                  </option>
                </select>
                <small v-if="!context.jobs.length">暂无职位，请先到管理后台同步 BOSS 已发布职位。</small>
              </label>
              <label>
                <span>执行账号</span>
                <select v-model="selectedAccountId" data-test="workbench-account" :disabled="uploading || submitting || !accounts.length" @change="chooseAccount">
                  <option value="">请选择 BOSS 账号</option>
                  <option v-for="account in accounts" :key="account.id" :value="String(account.id)">
                    {{ account.name }} · {{ account.login_status_label || accountReadinessMessage(account) }}
                  </option>
                </select>
                <small v-if="!accounts.length">暂无可用账号，请先在管理后台添加并登录。</small>
              </label>
            </div>
            <div v-if="selectedAccount || selectedJob" class="workbench-context-readiness" aria-label="账号就绪状态">
              <strong>账号就绪状态</strong>
              <ul>
                <li v-for="item in contextReadiness" :key="item.key" :class="{ 'is-ready': item.ready }">
                  <AppIcon :name="item.ready ? 'check-circle' : 'alert-circle'" :size="22" />
                  <span><b>{{ item.label }}</b><small>{{ item.detail }}</small></span>
                </li>
              </ul>
            </div>
            <div v-if="!context.jobs.length || !accounts.length" class="workbench-empty-actions">
              <router-link :to="{ path: '/recruitment/admin', query: { section: !accounts.length ? 'accounts' : 'jobs' } }">
                前往管理后台处理 <AppIcon name="arrow-right" :size="14" />
              </router-link>
            </div>
            <footer class="workbench-step-actions workbench-step-actions--forward">
              <button
                class="primary-button workbench-next"
                data-test="complete-context-step"
                type="button"
                :disabled="!contextStepComplete || uploading || submitting"
                @click="completeContextStep"
              >
                下一步：招聘标准 <AppIcon name="arrow-right" :size="16" />
              </button>
            </footer>
          </section>

          <section
            v-else-if="currentStep === 'standard'"
            class="workbench-section"
            data-test="workbench-step-standard"
            aria-labelledby="workbench-current-title"
          >
            <div class="workbench-upload-kind">
              <div>
                <strong>岗位参考资料</strong>
                <small class="sr-only">资料会归档到“{{ selectedJob?.title }}”，用于生成岗位标准和简历评分依据。</small>
              </div>
            </div>

            <label
              :class="['workbench-drop-zone', { 'is-dragging': dragging, 'is-uploading': uploading }]"
              data-test="workbench-drop-zone"
              role="button"
              tabindex="0"
              :aria-disabled="!selectedJob || uploading || submitting"
              @dragenter.prevent="dragging = true"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="dropDocuments"
              @keydown.enter.prevent="fileInput?.click()"
              @keydown.space.prevent="fileInput?.click()"
            >
              <span class="workbench-drop-zone__icon"><AppIcon name="upload" :size="24" /></span>
              <strong data-test="workbench-upload">
                {{ uploading ? `正在上传 ${uploadProgress.completed}/${uploadProgress.total}` : '拖入文件，或点击选择' }}
              </strong>
              <small>支持 DOC、DOCX、XLSX，可一次选择多个；单文件最大 25MB</small>
              <input
                ref="fileInput"
                data-test="workbench-file-input"
                type="file"
                accept=".doc,.docx,.xlsx"
                multiple
                hidden
                :disabled="!selectedJob || uploading || submitting"
                @change="selectDocuments"
              />
            </label>

            <ul v-if="uploadQueue.length" class="workbench-upload-queue" aria-live="polite" aria-label="文件上传状态">
              <li v-for="item in uploadQueue" :key="item.id" :class="`is-${item.status}`" :data-test="`upload-file-${item.status}`">
                <i><AppIcon :name="item.status === 'succeeded' ? 'check-circle' : (item.status === 'failed' ? 'alert-circle' : 'document')" :size="17" /></i>
                <span>
                  <strong>{{ item.name }}</strong>
                  <small v-if="item.status === 'pending'">等待上传</small>
                  <small v-else-if="item.status === 'uploading'">正在上传…</small>
                  <small v-else-if="item.status === 'succeeded'">已上传</small>
                  <small v-else>{{ item.error }}</small>
                </span>
              </li>
            </ul>

            <p v-if="documentError" class="workbench-inline-error" role="alert">{{ documentError }}</p>
            <div class="workbench-documents" aria-live="polite">
              <p v-if="documentsLoading">正在读取岗位依据…</p>
              <template v-else-if="documents.length">
                <a
                  v-for="document in documents"
                  :key="document.id"
                  :href="`/api/recruitment/job-document-versions/${document.current_version.id}/file/`"
                >
                  <AppIcon name="document" :size="16" />
                  <span><strong>{{ document.title }}</strong><small>{{ document.category_label }} · V{{ document.current_version.version }}</small></span>
                </a>
              </template>
              <p v-else class="sr-only">尚未上传岗位参考资料；不影响本次自动化，生成评分标准前可继续补充。</p>
            </div>

            <div class="workbench-requirements">
              <label>
                <span><b>核心要求 <em>主动寻访必填</em></b><small>{{ coreItems.length }} 项</small></span>
                <textarea v-model="coreText" data-test="core-requirements" rows="5" maxlength="2000" :placeholder="'例如：\n3 年以上 Python 开发经验\n熟悉 Django 与关系型数据库'"></textarea>
                <small class="sr-only">已识别 {{ coreItems.length }}/10 项；每项最多 200 字。</small>
              </label>
              <label>
                <span><b>加分项 <em>选填</em></b><small>{{ bonusItems.length }} 项</small></span>
                <textarea v-model="bonusText" data-test="bonus-requirements" rows="5" maxlength="2000" :placeholder="'例如：\n有 AI 应用落地经验\n做过复杂后台系统'"></textarea>
                <small class="sr-only">已识别 {{ bonusItems.length }}/10 项。</small>
              </label>
            </div>

            <footer class="workbench-step-actions workbench-step-actions--split">
              <button class="secondary-button workbench-previous" data-test="previous-step" type="button" :disabled="uploading || submitting" @click="previousStep">
                上一步
              </button>
              <button
                class="primary-button workbench-next"
                data-test="complete-standard-step"
                type="button"
                :disabled="uploading || submitting"
                @click="completeStandardStep"
              >
                下一步：执行方案 <AppIcon name="arrow-right" :size="16" />
              </button>
            </footer>
          </section>

          <section
            v-else-if="currentStep === 'plan'"
            class="workbench-section workbench-section--plan"
            data-test="workbench-step-plan"
            aria-labelledby="workbench-current-title"
          >
            <fieldset class="workbench-schemes">
              <legend class="sr-only">选择执行方案</legend>
              <label :class="{ 'is-selected': schemeKind === 'passive_resume' }">
                <input v-model="schemeKind" data-test="scheme-passive" type="radio" value="passive_resume" />
                <span><strong>被动咨询</strong><em>接收候选人主动咨询</em></span>
              </label>
              <label :class="{ 'is-selected': schemeKind === 'active_resume_search' }">
                <input v-model="schemeKind" data-test="scheme-active" type="radio" value="active_resume_search" />
                <span><strong>主动寻访</strong><em>主动搜索并联系候选人</em></span>
              </label>
            </fieldset>

            <div class="workbench-workflow-choice">
              <label>
                <span>运行流程</span>
                <select v-model="workflowChoice" data-test="workflow-choice" :disabled="submitting">
                  <option value="standard">标准流程（按本页设置生成）</option>
                  <option v-for="option in enabledWorkflowOptions" :key="option.id" :value="`custom:${option.id}`">
                    {{ option.label }}
                  </option>
                </select>
                <small class="sr-only">{{ enabledWorkflowOptions.length ? '也可直接运行管理后台已启用、且属于当前账号的高级流程。' : '当前账号暂无已启用的高级流程，使用标准流程即可。' }}</small>
              </label>
              <router-link :to="{ path: '/recruitment/admin', query: { section: 'workflows', account: selectedAccountId } }">管理高级流程</router-link>
            </div>

            <div v-if="schemeKind === 'passive_resume'" class="workbench-settings workbench-settings--passive">
              <label>
                <span>消息同步间隔</span>
                <select v-model.number="interval" data-test="passive-interval">
                  <option :value="1">每 1 分钟</option>
                  <option :value="2">每 2 分钟</option>
                  <option :value="5">每 5 分钟</option>
                  <option :value="15">每 15 分钟</option>
                  <option :value="60">每小时</option>
                  <option :value="1440">每天</option>
                </select>
                <small>完整会话会在隔离浏览器中同步；验证码、风控和观望意图会暂停或转人工。</small>
              </label>
            </div>

            <div v-else class="workbench-settings">
              <label>
                <span>搜索来源</span>
                <select v-model="source" data-test="active-source">
                  <option value="search">常规搜索</option>
                  <option value="recommend">推荐牛人</option>
                  <option value="deep_search">深度搜索</option>
                </select>
              </label>
              <label>
                <span>搜索关键词</span>
                <input v-model.trim="keyword" data-test="active-keyword" maxlength="120" placeholder="例如：Python 后端" />
                <small>{{ source === 'search' ? '常规搜索必填' : '可选，用于缩小候选范围' }}</small>
              </label>
              <CandidateFilterPanel v-model="candidateFilters" :disabled="submitting" />
              <label>
                <span>目标简历数</span>
                <input v-model.number="targetResumeCount" data-test="target-resume-count" type="number" min="1" max="100" />
                <small>达到目标后自动停止继续拉取。</small>
              </label>
              <label>
                <span>最大扫描人数</span>
                <input v-model.number="maxScanCount" data-test="max-scan-count" type="number" :min="targetResumeCount || 1" max="100" />
                <small>必须不少于目标简历数，最多 100 人。</small>
              </label>
            </div>

            <footer class="workbench-step-actions workbench-step-actions--split">
              <button class="secondary-button workbench-previous" data-test="previous-step" type="button" :disabled="submitting" @click="previousStep">
                上一步
              </button>
              <button
                class="primary-button workbench-next"
                data-test="complete-plan-step"
                type="button"
                :disabled="submitting"
                @click="completePlanStep"
              >
                检查并开始执行 <AppIcon name="arrow-right" :size="16" />
              </button>
            </footer>
          </section>

          <section
            v-else
            class="workbench-section workbench-review"
            data-test="workbench-step-review"
            aria-labelledby="workbench-current-title"
          >
              <div class="workbench-summary" aria-label="本次作业摘要">
                <div>
                  <AppIcon name="briefcase" :size="26" />
                  <span><strong>{{ selectedJob?.title || '尚未选择职位' }}</strong><small>在招职位</small></span>
                </div>
                <div>
                  <AppIcon name="user" :size="26" />
                  <span><strong>{{ selectedAccount?.name || '尚未选择账号' }}</strong><small>执行账号</small></span>
                </div>
                <div>
                  <AppIcon name="search" :size="26" />
                  <span><strong>{{ schemeKind === 'passive_resume' ? '被动咨询' : `主动寻访 ${targetResumeCount} 份` }}</strong><small>{{ schemeKind === 'passive_resume' ? '消息同步' : '目标简历数' }}</small></span>
                </div>
              </div>

              <ol class="workbench-checks">
                <li v-for="item in checks" :id="`precheck-${item.key}`" :key="item.key" :class="{ 'is-ready': item.ok }" :data-test="`precheck-${item.key}`">
                  <i><AppIcon :name="item.ok ? 'check-circle' : 'alert-circle'" :size="17" /></i>
                  <span><strong>{{ item.label }}</strong><small>{{ item.detail }}</small></span>
                  <router-link v-if="item.link" :to="item.link">处理</router-link>
                </li>
              </ol>

              <p v-if="submitError" class="workbench-inline-error" role="alert">{{ submitError }}</p>
              <div v-if="planVersionNotice" class="workbench-version-notice" data-test="plan-version-notice" role="status">
                <p>{{ planVersionNotice }}</p>
                <button data-test="rebase-edit-draft" type="button" :disabled="submitting" @click="rebaseEditDraft">
                  以最新版本继续编辑
                </button>
              </div>
              <p v-if="planLoading" class="workbench-submit-hint" data-test="plan-loading" aria-live="polite">
                {{ autoStartRequested ? '正在执行前检查，全部通过后将自动开始执行…' : '正在同步任务状态…' }}
              </p>
              <p v-else-if="planError && !currentPlan" class="workbench-inline-error" role="alert">{{ planError }}</p>
              <small v-if="!planLoading" class="workbench-submit-hint">
                {{ firstBlockingCheck ? `请先处理：${firstBlockingCheck.label}` : (startDisabledReason || '点击后将以一个原子命令创建方案版本并开启任务。') }}
              </small>

              <p class="workbench-safety"><AppIcon name="shield" :size="15" /> 外发、身份复核、额度与人工确认继续由服务端安全门控制。</p>
              <footer class="workbench-step-actions workbench-review-actions">
                <button class="secondary-button workbench-previous" data-test="previous-step" type="button" :disabled="submitting" @click="previousStep">
                  上一步
                </button>
                <button
                  v-if="!planLoading"
                  class="primary-button workbench-start"
                  data-test="start-execution"
                  type="button"
                  :disabled="!canSubmit"
                  :aria-describedby="firstBlockingCheck ? `precheck-${firstBlockingCheck.key}` : undefined"
                  @click="startExecution"
                >
                  {{ submitting ? submitStage : '开始执行' }}
                </button>
              </footer>
          </section>
        </main>
      </div>
    </section>
  </div>
</template>

<style scoped>
.recruitment-workbench {
  --wb-color-stage: #00bfc1;
  --wb-color-canvas: #f3f6f8;
  --wb-color-surface: #ffffff;
  --wb-color-sidebar: #e8f8f8;
  --wb-color-sidebar-active: #ffffff;
  --wb-color-section-soft: #f2fbfb;
  --wb-color-ink: #0f172a;
  --wb-color-secondary: #334155;
  --wb-color-muted: #64748b;
  --wb-color-line: #e2e8f0;
  --wb-color-line-strong: #b8c8d8;
  --wb-color-primary: #00aeb1;
  --wb-color-primary-dark: #007f82;
  --wb-color-primary-soft: #ddf7f7;
  --wb-color-primary-soft-hover: #edfafa;
  --wb-color-success-border: #ccebe6;
  --wb-color-success-soft: #f7fcfb;
  --wb-color-warning: #d97706;
  --wb-color-warning-border: #f1d7a8;
  --wb-color-warning-control-border: #d5a14a;
  --wb-color-warning-ink: #8a5208;
  --wb-color-warning-control-ink: #714207;
  --wb-color-warning-soft: #fffbeb;
  --wb-color-danger: #dc4a4a;
  --wb-color-danger-border: #f2caca;
  --wb-color-danger-soft: #fffafa;
  --wb-color-transparent: transparent;
  --wb-font-family: var(--app-font-family);
  --wb-font-size-meta: 12px;
  --wb-font-size-small: 12px;
  --wb-font-size-control: 14px;
  --wb-font-size-body: 14px;
  --wb-font-size-section: 26px;
  --wb-font-size-title: 18px;
  --wb-font-weight-medium: 500;
  --wb-font-weight-semibold: 600;
  --wb-font-weight-bold: 700;
  --wb-font-weight-heavy: 800;
  --wb-line-height-compact: 1.45;
  --wb-line-height-body: 1.6;
  --wb-letter-spacing-kicker: .14em;
  --wb-letter-spacing-title: -.02em;
  --wb-letter-spacing-heading: -.025em;
  --wb-heading-line-height: 1.24;
  --wb-space-1: 4px;
  --wb-space-2: 8px;
  --wb-space-3: 12px;
  --wb-space-4: 16px;
  --wb-space-5: 22px;
  --wb-space-6: 28px;
  --wb-space-7: 34px;
  --wb-stage-pad-top: 28px;
  --wb-stage-pad-inline: 34px;
  --wb-stage-pad-bottom: 42px;
  --wb-stage-margin-top: -28px;
  --wb-stage-margin-inline: -34px;
  --wb-stage-margin-bottom: -42px;
  --wb-stage-gap: 16px;
  --wb-content-max-width: 960px;
  --wb-card-max-width: 960px;
  --wb-card-min-height: 560px;
  --wb-card-height: 560px;
  --wb-sidebar-width: 210px;
  --wb-workspace-padding-block: 28px;
  --wb-workspace-padding-inline: 30px;
  --wb-form-max-width: 620px;
  --wb-topbar-height: 64px;
  --wb-radius-control: 9px;
  --wb-radius-panel: 15px;
  --wb-radius-card: 32px;
  --wb-radius-status: 6px;
  --wb-radius-icon: 14px;
  --wb-radius-pill: 999px;
  --wb-border-width: 1px;
  --wb-focus-width: 2px;
  --wb-control-min-height: 52px;
  --wb-status-dot-size: 8px;
  --wb-step-number-size: 40px;
  --wb-step-min-height: 64px;
  --wb-mobile-step-number-size: 34px;
  --wb-mobile-step-min-height: 58px;
  --wb-radio-size: 18px;
  --wb-scheme-label-end-padding: 48px;
  --wb-upload-icon-size: 34px;
  --wb-drop-icon-size: 48px;
  --wb-check-icon-column: 20px;
  --wb-aside-min-width: 304px;
  --wb-aside-max-width: 320px;
  --wb-sticky-offset: 82px;
  --wb-loading-min-height: 220px;
  --wb-loading-line-height: 14px;
  --wb-copy-max-width: 520px;
  --wb-passive-max-width: 420px;
  --wb-context-field-max-width: 400px;
  --wb-textarea-min-height: 118px;
  --wb-drop-zone-min-height: 164px;
  --wb-context-min-height: 100%;
  --wb-scheme-min-height: 116px;
  --wb-start-min-height: 52px;
  --wb-review-title-size: 26px;
  --wb-review-copy-max-width: 220px;
  --wb-mobile-section-title-size: 26px;
  --wb-drop-zone-mobile-min-height: 160px;
  --wb-document-min-width: 180px;
  --wb-shadow-panel: 0 20px 60px rgba(4, 75, 78, .20);
  --wb-transition: 180ms ease;
  --wb-disabled-opacity: .62;
  --wb-soft-disabled-opacity: .72;
  display: grid;
  justify-items: center;
  align-content: start;
  gap: var(--wb-stage-gap);
  width: 100%;
  min-width: 0;
  max-width: none;
  min-height: calc(100vh - var(--wb-topbar-height));
  margin: 0;
  padding: var(--wb-stage-pad-top) var(--wb-stage-pad-inline) var(--wb-stage-pad-bottom);
  overflow-x: clip;
  background: var(--wb-color-stage);
  container-name: workbench-page;
  container-type: inline-size;
  font-family: var(--wb-font-family);
}

.recruitment-workbench,
.recruitment-workbench * {
  box-sizing: border-box;
}

.recruitment-workbench > * {
  width: 100%;
  max-width: var(--wb-content-max-width);
  min-width: 0;
}

.workbench-hero {
  align-items: center;
}

.workbench-hero .eyebrow {
  display: none;
}

.workbench-hero h2 {
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-title);
  font-weight: var(--wb-font-weight-bold);
}

.workbench-hero p {
  color: var(--wb-color-secondary);
  font-size: var(--wb-font-size-body);
}

.workbench-runtime {
  display: inline-flex;
  align-items: center;
  gap: var(--wb-space-2);
  padding: 0;
  border: 0;
  color: var(--wb-color-warning);
  background: var(--wb-color-transparent);
  font-size: var(--wb-font-size-control);
  font-weight: var(--wb-font-weight-bold);
}

.workbench-runtime i {
  width: var(--wb-status-dot-size);
  height: var(--wb-status-dot-size);
  flex: 0 0 var(--wb-status-dot-size);
  border-radius: var(--wb-radius-pill);
  background: var(--wb-color-warning);
}

.workbench-runtime.is-ready {
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-transparent);
}

.workbench-runtime.is-ready i {
  background: var(--wb-color-primary);
}

.workbench-error,
.workbench-inline-error {
  margin: 0;
  padding: var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-danger);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-danger);
  background: var(--wb-color-surface);
  font-size: var(--wb-font-size-control);
  line-height: var(--wb-line-height-compact);
}

.workbench-storage-notice {
  display: flex;
  align-items: flex-start;
  gap: var(--wb-space-2);
  margin: 0;
  padding: var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-warning-border);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-warning-ink);
  background: var(--wb-color-warning-soft);
  font-size: var(--wb-font-size-control);
  line-height: var(--wb-line-height-compact);
}

.workbench-storage-notice > svg {
  flex: 0 0 auto;
}

.workbench-loading {
  min-height: var(--wb-loading-min-height);
  display: grid;
  place-items: center;
  align-content: center;
  gap: var(--wb-space-2);
  color: var(--wb-color-muted);
  box-shadow: none;
}

.workbench-loading > span {
  width: min(var(--wb-copy-max-width), 78%);
  height: var(--wb-loading-line-height);
  border-radius: var(--wb-radius-status);
  background: var(--wb-color-canvas);
}

.workbench-loading > span:nth-child(2) {
  width: min(var(--wb-passive-max-width), 68%);
}

.workbench-loading > span:nth-child(3) {
  width: min(var(--wb-document-min-width), 56%);
}

.workbench-wizard {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--wb-space-2);
  min-width: 0;
  overflow: visible;
  border: 0;
  background: var(--wb-color-transparent);
  box-shadow: none;
}

.workbench-wizard__step {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  column-gap: var(--wb-space-3);
  align-items: center;
  min-width: 0;
  padding: var(--wb-space-2) var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-transparent);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-muted);
  background: var(--wb-color-transparent);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--wb-transition), background-color var(--wb-transition);
}

.workbench-wizard__step::after {
  position: absolute;
  right: var(--wb-space-3);
  bottom: 0;
  left: var(--wb-space-3);
  height: var(--wb-focus-width);
  border-radius: var(--wb-radius-pill);
  background: var(--wb-color-transparent);
  content: '';
}

.workbench-wizard__step > span {
  grid-row: 1 / span 2;
  display: grid;
  place-items: center;
  width: var(--wb-step-number-size);
  height: var(--wb-step-number-size);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-pill);
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  font-weight: var(--wb-font-weight-heavy);
}

.workbench-wizard__step strong {
  overflow: hidden;
  color: var(--wb-color-secondary);
  font-size: var(--wb-font-size-body);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-wizard__step small {
  overflow: hidden;
  margin-top: var(--wb-space-1);
  font-size: var(--wb-font-size-meta);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-wizard__step:hover:not(:disabled) {
  background: var(--wb-color-primary-soft-hover);
}

.workbench-wizard__step:focus-visible {
  z-index: 1;
  outline: var(--wb-focus-width) solid var(--wb-color-primary);
  outline-offset: var(--wb-border-width);
}

.workbench-wizard__step.is-current {
  color: var(--wb-color-primary-dark);
  border-color: var(--wb-color-primary);
  background: var(--wb-color-surface);
}

.workbench-wizard__step.is-current::after {
  background: var(--wb-color-primary);
}

.workbench-wizard__step.is-current > span {
  border-color: var(--wb-color-primary);
  color: var(--wb-color-surface);
  background: var(--wb-color-primary);
}

.workbench-wizard__step.is-complete > span {
  border-color: var(--wb-color-success-border);
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-primary-soft);
}

.workbench-wizard__step.is-current strong,
.workbench-wizard__step.is-complete strong {
  color: var(--wb-color-ink);
}

.workbench-wizard__step:disabled {
  cursor: not-allowed;
  opacity: var(--wb-disabled-opacity);
}

.workbench-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(var(--wb-aside-min-width), var(--wb-aside-max-width));
  gap: var(--wb-space-5);
  align-items: start;
  min-width: 0;
}

.workbench-layout--single {
  grid-template-columns: minmax(0, 1fr);
}

.workbench-layout--context {
  justify-self: center;
  max-width: var(--wb-context-panel-max-width);
}

.workbench-main {
  display: block;
  min-width: 0;
  padding: 0;
  overflow: hidden;
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-panel);
  background: var(--wb-color-surface);
  box-shadow: none;
}

.workbench-section {
  min-width: 0;
  padding: var(--wb-space-4) var(--wb-space-5);
}

.workbench-section + .workbench-section {
  border-top: var(--wb-border-width) solid var(--wb-color-line);
}

.workbench-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--wb-space-4);
  margin-bottom: var(--wb-space-3);
}

.workbench-section-heading div > span {
  display: block;
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-meta);
  font-weight: var(--wb-font-weight-heavy);
  letter-spacing: var(--wb-letter-spacing-kicker);
}

.workbench-section-heading h3 {
  display: inline-block;
  margin: var(--wb-space-1) 0 0;
  padding: 0 var(--wb-space-1);
  border-radius: var(--wb-radius-status);
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-section);
  font-weight: var(--wb-font-weight-bold);
  line-height: var(--wb-line-height-compact);
}

.workbench-section-heading h3:focus {
  outline: none;
}

.workbench-section-heading p {
  max-width: var(--wb-copy-max-width);
  margin: var(--wb-space-1) 0 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-control);
  line-height: var(--wb-line-height-body);
  text-align: right;
}

.workbench-context-grid,
.workbench-requirements,
.workbench-settings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--wb-space-4);
  min-width: 0;
}

.workbench-context-grid {
  grid-template-columns: repeat(2, minmax(0, var(--wb-context-field-max-width)));
  justify-content: space-between;
}

.workbench-context-grid label,
.workbench-requirements label,
.workbench-settings label {
  display: grid;
  gap: var(--wb-space-2);
  min-width: 0;
  color: var(--wb-color-secondary);
  font-size: var(--wb-font-size-control);
  font-weight: var(--wb-font-weight-bold);
}

.workbench-context-grid select,
.workbench-requirements textarea,
.workbench-settings select,
.workbench-settings input,
.workbench-workflow-choice select {
  width: 100%;
  min-width: 0;
  padding: var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-ink);
  background: var(--wb-color-surface);
  font: inherit;
  font-size: var(--wb-font-size-body);
  font-weight: var(--wb-font-weight-medium);
}

.workbench-context-grid select:focus,
.workbench-requirements textarea:focus,
.workbench-settings select:focus,
.workbench-settings input:focus,
.workbench-workflow-choice select:focus {
  outline: var(--wb-focus-width) solid var(--wb-color-primary);
  border-color: var(--wb-color-primary);
}

.workbench-context-grid small,
.workbench-requirements small,
.workbench-settings small,
.workbench-workflow-choice small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  font-weight: var(--wb-font-weight-medium);
  line-height: var(--wb-line-height-compact);
}

.workbench-step-actions {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--wb-space-4);
  align-items: center;
  margin-top: var(--wb-space-5);
  padding-top: var(--wb-space-3);
  border-top: var(--wb-border-width) solid var(--wb-color-line);
}

.workbench-step-actions--forward {
  grid-template-columns: minmax(0, 1fr) auto;
}

.workbench-step-actions--split {
  grid-template-columns: auto minmax(0, 1fr);
}

.workbench-step-actions--split .workbench-next {
  justify-self: end;
}

.workbench-step-actions--previous-only {
  grid-template-columns: auto minmax(0, 1fr);
}

.workbench-step-actions > span {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-control);
  line-height: var(--wb-line-height-compact);
}

.workbench-step-actions--previous-only > span {
  text-align: right;
}

.workbench-step-actions .secondary-button {
  min-height: var(--wb-control-min-height);
  border-color: var(--wb-color-line);
  color: var(--wb-color-secondary);
  background: var(--wb-color-surface);
  box-shadow: none;
}

.workbench-step-actions .workbench-next {
  display: inline-flex;
  align-items: center;
  gap: var(--wb-space-2);
  border-color: var(--wb-color-ink);
  color: var(--wb-color-surface);
  background: var(--wb-color-ink);
}

.workbench-step-actions .workbench-next:hover:not(:disabled) {
  border-color: var(--wb-color-secondary);
  color: var(--wb-color-surface);
  background: var(--wb-color-secondary);
}

.workbench-upload-kind {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--wb-space-5);
  min-width: 0;
  margin-bottom: var(--wb-space-3);
}

.workbench-upload-kind > div,
.workbench-upload-kind > label {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-upload-kind > div strong,
.workbench-upload-kind > label span {
  color: var(--wb-color-secondary);
  font-size: var(--wb-font-size-control);
  font-weight: var(--wb-font-weight-bold);
}

.workbench-upload-kind > div small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-upload-kind select {
  min-width: 148px;
  padding: var(--wb-space-2) var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-ink);
  background: var(--wb-color-surface);
  font: inherit;
  font-size: var(--wb-font-size-body);
}

.workbench-upload-kind select:focus {
  outline: var(--wb-focus-width) solid var(--wb-color-primary);
  border-color: var(--wb-color-primary);
}

.workbench-drop-zone {
  display: grid;
  place-items: center;
  align-content: center;
  gap: var(--wb-space-2);
  min-height: var(--wb-drop-zone-min-height);
  padding: var(--wb-space-5);
  border: var(--wb-border-width) dashed var(--wb-color-line-strong);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-secondary);
  background: var(--wb-color-canvas);
  text-align: center;
  cursor: pointer;
  transition: border-color var(--wb-transition), background-color var(--wb-transition);
}

.workbench-drop-zone:hover,
.workbench-drop-zone.is-dragging {
  border-color: var(--wb-color-primary);
  background: var(--wb-color-primary-soft-hover);
}

.workbench-drop-zone.is-uploading {
  cursor: progress;
}

.workbench-drop-zone[aria-disabled='true'] {
  cursor: not-allowed;
  opacity: var(--wb-soft-disabled-opacity);
}

.workbench-drop-zone:focus-visible,
.workbench-drop-zone:focus-within {
  outline: var(--wb-focus-width) solid var(--wb-color-primary);
  outline-offset: var(--wb-space-1);
}

.workbench-drop-zone__icon {
  display: grid;
  place-items: center;
  width: var(--wb-drop-icon-size);
  height: var(--wb-drop-icon-size);
  margin-bottom: var(--wb-space-1);
  border-radius: var(--wb-radius-icon);
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-primary-soft);
}

.workbench-drop-zone > strong {
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-body);
  font-weight: var(--wb-font-weight-bold);
}

.workbench-drop-zone > small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-upload-queue {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--wb-space-2);
  min-width: 0;
  margin: var(--wb-space-3) 0 0;
  padding: 0;
  list-style: none;
}

.workbench-upload-queue li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--wb-space-2);
  align-items: start;
  min-width: 0;
  padding: var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-muted);
  background: var(--wb-color-surface);
}

.workbench-upload-queue li > span {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-upload-queue strong,
.workbench-upload-queue small {
  overflow-wrap: anywhere;
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-upload-queue strong {
  color: var(--wb-color-secondary);
}

.workbench-upload-queue .is-succeeded {
  border-color: var(--wb-color-success-border);
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-success-soft);
}

.workbench-upload-queue .is-failed {
  border-color: var(--wb-color-danger-border);
  color: var(--wb-color-danger);
  background: var(--wb-color-danger-soft);
}

.workbench-empty-actions {
  margin-top: var(--wb-space-3);
}

.workbench-empty-actions a,
.workbench-receipt a {
  display: inline-flex;
  align-items: center;
  gap: var(--wb-space-1);
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-control);
  font-weight: var(--wb-font-weight-bold);
  text-decoration: none;
}

.workbench-documents {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wb-space-2);
  min-width: 0;
  margin: var(--wb-space-3) 0 var(--wb-space-4);
}

.workbench-documents > p {
  margin: 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-documents a {
  display: flex;
  align-items: center;
  gap: var(--wb-space-2);
  min-width: min(var(--wb-document-min-width), 100%);
  padding: var(--wb-space-1) var(--wb-space-2);
  border-left: var(--wb-focus-width) solid var(--wb-color-line);
  color: var(--wb-color-secondary);
  background: var(--wb-color-transparent);
  text-decoration: none;
}

.workbench-documents a > span {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-documents a strong {
  overflow-wrap: anywhere;
  font-size: var(--wb-font-size-small);
}

.workbench-documents a small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-meta);
}

.workbench-requirements label > span em {
  margin-left: var(--wb-space-1);
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  font-style: normal;
  font-weight: var(--wb-font-weight-medium);
}

.workbench-requirements textarea {
  min-height: var(--wb-textarea-min-height);
  resize: vertical;
  line-height: var(--wb-line-height-body);
}

.workbench-schemes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--wb-space-3);
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.workbench-schemes > label {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--wb-space-3);
  min-width: 0;
  padding: var(--wb-space-4) var(--wb-scheme-label-end-padding) var(--wb-space-4) var(--wb-space-4);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-control);
  background: var(--wb-color-surface);
  cursor: pointer;
  transition: border-color var(--wb-transition), background-color var(--wb-transition);
}

.workbench-schemes > label:hover {
  border-color: var(--wb-color-primary);
  background: var(--wb-color-primary-soft-hover);
}

.workbench-schemes > label:focus-within {
  outline: var(--wb-focus-width) solid var(--wb-color-primary);
}

.workbench-schemes > label.is-selected {
  border-color: var(--wb-color-primary);
  background: var(--wb-color-primary-soft);
  box-shadow: none;
}

.workbench-schemes input {
  position: absolute;
  top: var(--wb-space-4);
  right: var(--wb-space-4);
  width: var(--wb-radio-size);
  height: var(--wb-radio-size);
  margin: 0;
  opacity: 1;
  accent-color: var(--wb-color-primary);
  cursor: pointer;
  pointer-events: auto;
}

.workbench-schemes input:focus {
  outline: none;
  box-shadow: none;
}

.workbench-schemes label > i {
  display: grid;
  place-items: center;
  width: var(--wb-upload-icon-size);
  height: var(--wb-upload-icon-size);
  flex: 0 0 var(--wb-upload-icon-size);
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-transparent);
}

.workbench-schemes label > span {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-schemes small {
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-meta);
  font-weight: var(--wb-font-weight-heavy);
  letter-spacing: var(--wb-letter-spacing-kicker);
}

.workbench-schemes strong {
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-body);
}

.workbench-schemes em {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  font-style: normal;
  line-height: var(--wb-line-height-compact);
}

.workbench-settings {
  margin-top: var(--wb-space-4);
  padding: var(--wb-space-4) 0 0;
  border-top: var(--wb-border-width) solid var(--wb-color-line);
  background: var(--wb-color-transparent);
}

.workbench-settings--passive {
  grid-template-columns: minmax(0, var(--wb-passive-max-width));
}

.workbench-workflow-choice {
  display: flex;
  align-items: flex-end;
  gap: var(--wb-space-4);
  min-width: 0;
  margin-top: var(--wb-space-4);
  padding-top: var(--wb-space-4);
  border-top: var(--wb-border-width) solid var(--wb-color-line);
  background: var(--wb-color-transparent);
}

.workbench-workflow-choice label {
  display: grid;
  flex: 1;
  gap: var(--wb-space-2);
  min-width: 0;
  color: var(--wb-color-secondary);
  font-size: var(--wb-font-size-control);
  font-weight: var(--wb-font-weight-bold);
}

.workbench-workflow-choice a {
  flex: 0 0 auto;
  padding-bottom: var(--wb-space-2);
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  font-weight: var(--wb-font-weight-semibold);
  text-decoration: underline;
  text-underline-offset: var(--wb-space-1);
}

.workbench-workflow-choice a:hover {
  color: var(--wb-color-primary-dark);
}

.workbench-review {
  position: sticky;
  top: var(--wb-sticky-offset);
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: var(--wb-space-4);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-panel);
  background: var(--wb-color-surface);
  box-shadow: none;
}

.workbench-review .workbench-section-heading {
  order: 0;
  margin-bottom: var(--wb-space-2);
}

.workbench-review .workbench-section-heading div > span {
  display: none;
}

.workbench-review .workbench-section-heading h3 {
  margin: 0;
  font-size: var(--wb-font-size-section);
}

.workbench-summary {
  order: 1;
  display: grid;
  gap: var(--wb-space-1);
  margin: 0;
  padding: var(--wb-space-3) 0 var(--wb-space-4);
  border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  background: var(--wb-color-transparent);
}

.workbench-summary span,
.workbench-summary small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-summary strong {
  overflow-wrap: anywhere;
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-body);
}

.workbench-checks {
  order: 2;
  display: grid;
  gap: 0;
  min-width: 0;
  margin: 0;
  padding: var(--wb-space-2) 0;
  list-style: none;
}

.workbench-checks li {
  display: grid;
  grid-template-columns: var(--wb-check-icon-column) minmax(0, 1fr) auto;
  gap: var(--wb-space-2);
  align-items: start;
  min-width: 0;
  padding: var(--wb-space-2) 0;
  border-bottom: var(--wb-border-width) solid var(--wb-color-line);
}

.workbench-checks li:last-child {
  border-bottom: 0;
}

.workbench-checks li > i {
  color: var(--wb-color-warning);
}

.workbench-checks li.is-ready > i {
  color: var(--wb-color-primary);
}

.workbench-checks li > span {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-checks strong {
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-small);
}

.workbench-checks small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-checks li.is-ready small {
  display: none;
}

.workbench-checks li.is-ready strong {
  color: var(--wb-color-secondary);
  font-weight: var(--wb-font-weight-semibold);
}

.workbench-checks a {
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-small);
  font-weight: var(--wb-font-weight-bold);
  text-decoration: underline;
  text-underline-offset: var(--wb-space-1);
}

.workbench-review > .workbench-inline-error {
  order: 3;
  margin-bottom: var(--wb-space-2);
}

.workbench-version-notice {
  order: 3;
  display: grid;
  gap: var(--wb-space-2);
  margin-bottom: var(--wb-space-2);
  padding: var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-warning-border);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-warning-ink);
  background: var(--wb-color-warning-soft);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-version-notice p {
  margin: 0;
}

.workbench-version-notice button {
  justify-self: start;
  min-height: 32px;
  padding: 0 var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-warning-control-border);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-warning-control-ink);
  background: var(--wb-color-surface);
  font: inherit;
  font-weight: var(--wb-font-weight-semibold);
}

.workbench-start {
  order: 4;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--wb-space-2);
  width: 100%;
  min-height: var(--wb-control-min-height);
  margin-top: var(--wb-space-1);
  border-color: var(--wb-color-ink);
  color: var(--wb-color-surface);
  background: var(--wb-color-ink);
  box-shadow: none;
  transform: none;
}

.recruitment-workbench .workbench-start:hover:not(:disabled) {
  border-color: var(--wb-color-secondary);
  background: var(--wb-color-secondary);
  transform: none;
}

.workbench-start:disabled {
  border-color: var(--wb-color-line);
  color: var(--wb-color-muted);
  background: var(--wb-color-canvas);
  cursor: not-allowed;
  opacity: 1;
}

.workbench-submit-hint {
  order: 5;
  display: block;
  margin-top: var(--wb-space-2);
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
  text-align: left;
}

.workbench-receipt {
  order: 6;
  display: flex;
  gap: var(--wb-space-2);
  margin-top: var(--wb-space-3);
  padding: var(--wb-space-3);
  border: var(--wb-border-width) solid var(--wb-color-primary);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-surface);
}

.workbench-receipt > div {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-receipt span,
.workbench-receipt small {
  font-size: var(--wb-font-size-small);
}

.workbench-receipt strong {
  overflow-wrap: anywhere;
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-small);
}

.workbench-receipt a {
  margin-top: var(--wb-space-1);
}

.workbench-new-task {
  width: fit-content;
  margin-top: var(--wb-space-1);
  padding: 0;
  border: 0;
  color: var(--wb-color-muted);
  background: var(--wb-color-transparent);
  font-size: var(--wb-font-size-small);
  font-weight: var(--wb-font-weight-semibold);
  text-decoration: underline;
  text-underline-offset: var(--wb-space-1);
}

.workbench-safety {
  order: 7;
  display: flex;
  align-items: flex-start;
  gap: var(--wb-space-2);
  margin: var(--wb-space-3) 0 0;
  padding-top: var(--wb-space-3);
  border-top: var(--wb-border-width) solid var(--wb-color-line);
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.sr-only {
  position: absolute;
  width: var(--wb-border-width);
  height: var(--wb-border-width);
  padding: 0;
  margin: calc(var(--wb-border-width) * -1);
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@container workbench-page (max-width: 840px) {
  .workbench-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-review {
    position: static;
    order: 0;
    width: 100%;
    max-width: 100%;
  }

  .workbench-checks {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: var(--wb-space-5);
  }

  .workbench-checks li {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-checks li:nth-last-child(-n + 2) {
    border-bottom: 0;
  }
}

@container workbench-page (max-width: 620px) {
  .workbench-checks {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-checks li {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-checks li:last-child {
    border-bottom: 0;
  }
}

@media (max-width: 1050px) {
  .workbench-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-review {
    position: static;
    order: 0;
    width: 100%;
    max-width: 100%;
  }

  .workbench-checks {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: var(--wb-space-5);
  }

  .workbench-checks li {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-checks li:nth-last-child(-n + 2) {
    border-bottom: 0;
  }
}

@media (max-width: 900px) {
  .recruitment-workbench {
    --wb-stage-pad-top: 22px;
    --wb-stage-pad-inline: 20px;
    --wb-stage-pad-bottom: 34px;
    --wb-stage-margin-top: -22px;
    --wb-stage-margin-inline: -20px;
    --wb-stage-margin-bottom: -34px;
  }
}

@media (max-width: 680px) {
  .recruitment-workbench {
    --wb-stage-pad-top: 18px;
    --wb-stage-pad-inline: 13px;
    --wb-stage-pad-bottom: 28px;
    --wb-stage-margin-top: -18px;
    --wb-stage-margin-inline: -13px;
    --wb-stage-margin-bottom: -28px;
  }
}

@media (max-width: 720px) {
  .workbench-hero,
  .workbench-section-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .workbench-runtime {
    align-self: flex-start;
  }

  .workbench-section-heading p {
    text-align: left;
  }

  .workbench-section,
  .workbench-review {
    padding: var(--wb-space-4);
  }

  .workbench-context-grid,
  .workbench-requirements,
  .workbench-settings,
  .workbench-schemes,
  .workbench-checks,
  .workbench-upload-queue,
  .workbench-step-actions,
  .workbench-step-actions--forward,
  .workbench-step-actions--split,
  .workbench-step-actions--previous-only {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-step-actions > span,
  .workbench-step-actions--previous-only > span {
    text-align: left;
  }

  .workbench-step-actions button {
    justify-content: center;
    width: 100%;
  }

  .workbench-upload-kind {
    align-items: stretch;
    flex-direction: column;
  }

  .workbench-upload-kind select {
    width: 100%;
  }

  .workbench-drop-zone {
    min-height: var(--wb-drop-zone-mobile-min-height);
    padding: var(--wb-space-5);
  }

  .workbench-checks li {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-checks li:last-child {
    border-bottom: 0;
  }

  .workbench-workflow-choice {
    align-items: stretch;
    flex-direction: column;
  }

  .workbench-workflow-choice a {
    align-self: flex-start;
    padding-bottom: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workbench-schemes > label {
    transition: none;
  }
}

/* 参考图分栏主卡：最新 sprint contract 的页面级覆盖。 */
.recruitment-workbench {
  place-items: center;
  align-content: center;
  gap: 0;
}

.recruitment-workbench > .workbench-card {
  width: min(100%, var(--wb-card-max-width));
  max-width: var(--wb-card-max-width);
}

.workbench-card {
  display: grid;
  grid-template-columns: var(--wb-sidebar-width) minmax(0, 1fr);
  min-width: 0;
  min-height: var(--wb-card-min-height);
  overflow: hidden;
  border: 0;
  border-radius: var(--wb-radius-card);
  background: var(--wb-color-surface);
  box-shadow: var(--wb-shadow-panel);
}

.workbench-sidebar {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: var(--wb-space-7) var(--wb-space-6);
  background: var(--wb-color-sidebar);
}

.workbench-sidebar__intro {
  display: grid;
  gap: var(--wb-space-2);
}

.workbench-sidebar__intro > span {
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-meta);
  font-weight: var(--wb-font-weight-heavy);
  letter-spacing: var(--wb-letter-spacing-kicker);
}

.workbench-sidebar__intro > strong {
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-title);
  font-weight: var(--wb-font-weight-bold);
  letter-spacing: var(--wb-letter-spacing-title);
}

.workbench-sidebar__intro > p {
  margin: 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-body);
}

.workbench-wizard {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--wb-space-2);
  margin-top: var(--wb-space-7);
}

.workbench-wizard__step {
  grid-template-columns: var(--wb-step-number-size) minmax(0, 1fr);
  column-gap: var(--wb-space-3);
  min-height: var(--wb-step-min-height);
  padding: var(--wb-space-3);
  border-color: var(--wb-color-transparent);
  border-radius: var(--wb-radius-control);
  background: var(--wb-color-transparent);
}

.workbench-wizard__step::after {
  display: none;
}

.workbench-wizard__step > span {
  width: var(--wb-step-number-size);
  height: var(--wb-step-number-size);
  border-color: var(--wb-color-line-strong);
  color: var(--wb-color-muted);
  background: var(--wb-color-transparent);
  font-size: var(--wb-font-size-small);
}

.workbench-wizard__step strong {
  color: var(--wb-color-secondary);
  font-size: var(--wb-font-size-body);
  white-space: normal;
}

.workbench-wizard__step small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  white-space: normal;
}

.workbench-wizard__step:hover:not(:disabled) {
  background: var(--wb-color-primary-soft-hover);
}

.workbench-wizard__step.is-current {
  border-color: var(--wb-color-transparent);
  background: var(--wb-color-sidebar-active);
}

.workbench-wizard__step.is-current > span {
  border-color: var(--wb-color-primary);
  color: var(--wb-color-surface);
  background: var(--wb-color-primary);
}

.workbench-wizard__step.is-complete > span {
  border-color: var(--wb-color-primary);
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-primary-soft);
}

.workbench-wizard__step:focus-visible {
  outline-color: var(--wb-color-primary);
  outline-offset: var(--wb-space-1);
}

.workbench-workspace {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: var(--wb-workspace-padding-block) var(--wb-workspace-padding-inline);
  background: var(--wb-color-surface);
}

.workbench-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--wb-space-4);
  padding-bottom: var(--wb-space-5);
  border-bottom: var(--wb-border-width) solid var(--wb-color-line);
}

.workbench-hero > div {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-hero .eyebrow {
  display: block;
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-meta);
  font-weight: var(--wb-font-weight-heavy);
  letter-spacing: var(--wb-letter-spacing-kicker);
}

.workbench-hero h2 {
  margin: 0;
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-title);
  font-weight: var(--wb-font-weight-bold);
  letter-spacing: var(--wb-letter-spacing-title);
}

.workbench-hero p {
  max-width: var(--wb-copy-max-width);
  margin: 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-body);
}

.workbench-runtime {
  flex: 0 0 auto;
  min-height: var(--wb-space-6);
  color: var(--wb-color-warning);
  font-size: var(--wb-font-size-small);
}

.workbench-runtime.is-ready {
  color: var(--wb-color-primary-dark);
}

.workbench-notices {
  display: grid;
  gap: var(--wb-space-2);
  width: min(100%, var(--wb-form-max-width));
  margin-top: var(--wb-space-4);
}

.workbench-notices:empty {
  display: none;
}

.workbench-error,
.workbench-inline-error,
.workbench-storage-notice {
  font-size: var(--wb-font-size-small);
}

.workbench-loading {
  display: grid;
  place-items: start stretch;
  align-content: center;
  flex: 1;
  min-height: 0;
  padding: var(--wb-space-6) 0;
  border: 0;
  background: var(--wb-color-transparent);
  box-shadow: none;
}

.workbench-loading > span {
  background: var(--wb-color-canvas);
}

.workbench-main {
  display: block;
  width: min(100%, var(--wb-form-max-width));
  min-width: 0;
  margin-top: var(--wb-space-6);
  padding: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: var(--wb-color-transparent);
  box-shadow: none;
}

.workbench-section {
  width: 100%;
  min-width: 0;
  padding: 0;
}

.workbench-section--context {
  display: flex;
  flex-direction: column;
  min-height: var(--wb-context-min-height);
}

.workbench-section-heading {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  justify-content: flex-start;
  gap: var(--wb-space-2);
  margin-bottom: var(--wb-space-6);
}

.workbench-section-heading div > span,
.workbench-review__heading div > span {
  display: block;
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-meta);
  font-weight: var(--wb-font-weight-heavy);
  letter-spacing: var(--wb-letter-spacing-kicker);
}

.workbench-section-heading h3 {
  display: block;
  margin: var(--wb-space-1) 0 0;
  padding: 0;
  border-radius: 0;
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-section);
  font-weight: var(--wb-font-weight-bold);
  line-height: var(--wb-heading-line-height);
  letter-spacing: var(--wb-letter-spacing-heading);
}

.workbench-section-heading p {
  max-width: var(--wb-copy-max-width);
  margin: 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-body);
  line-height: var(--wb-line-height-body);
  text-align: left;
}

.workbench-context-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--wb-space-5);
  width: min(100%, var(--wb-form-max-width));
}

.workbench-context-grid label,
.workbench-requirements label,
.workbench-settings label,
.workbench-workflow-choice label {
  gap: var(--wb-space-2);
  font-size: var(--wb-font-size-body);
}

.workbench-context-grid select,
.workbench-requirements textarea,
.workbench-settings select,
.workbench-settings input,
.workbench-workflow-choice select {
  min-height: var(--wb-control-min-height);
  padding: var(--wb-space-3) var(--wb-space-4);
  border-color: var(--wb-color-line);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-ink);
  background: var(--wb-color-surface);
  font-size: var(--wb-font-size-body);
}

.workbench-context-grid small,
.workbench-requirements small,
.workbench-settings small,
.workbench-workflow-choice small {
  font-size: var(--wb-font-size-small);
}

.workbench-empty-actions {
  margin-top: var(--wb-space-4);
}

.workbench-empty-actions a,
.workbench-receipt a {
  font-size: var(--wb-font-size-small);
}

.workbench-step-actions {
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--wb-space-4);
  margin-top: var(--wb-space-6);
  padding-top: var(--wb-space-4);
}

.workbench-section--context .workbench-step-actions {
  margin-top: auto;
}

.workbench-step-actions--forward {
  grid-template-columns: minmax(0, 1fr) auto;
}

.workbench-step-actions--split {
  grid-template-columns: auto minmax(0, 1fr);
}

.workbench-step-actions--split .workbench-next {
  justify-self: end;
}

.workbench-step-actions--previous-only {
  grid-template-columns: auto minmax(0, 1fr);
}

.workbench-step-actions > span {
  font-size: var(--wb-font-size-small);
}

.workbench-step-actions .secondary-button,
.recruitment-workbench .workbench-step-actions .workbench-next {
  min-height: var(--wb-control-min-height);
  padding-inline: var(--wb-space-5);
  border-radius: var(--wb-radius-control);
  font-size: var(--wb-font-size-body);
}

.recruitment-workbench .workbench-step-actions .workbench-next {
  border-color: var(--wb-color-primary);
  color: var(--wb-color-surface);
  background: var(--wb-color-primary);
  box-shadow: none;
}

.recruitment-workbench .workbench-step-actions .workbench-next:hover:not(:disabled) {
  border-color: var(--wb-color-primary-dark);
  color: var(--wb-color-surface);
  background: var(--wb-color-primary-dark);
  transform: none;
}

.workbench-upload-kind {
  display: block;
  width: min(100%, var(--wb-form-max-width));
  margin-bottom: var(--wb-space-3);
}

.workbench-upload-kind > div {
  gap: var(--wb-space-2);
}

.workbench-upload-kind > div strong {
  font-size: var(--wb-font-size-body);
}

.workbench-upload-kind > div small {
  font-size: var(--wb-font-size-small);
}

.workbench-drop-zone {
  width: min(100%, var(--wb-form-max-width));
  min-height: var(--wb-drop-zone-min-height);
  padding: var(--wb-space-5);
  border-color: var(--wb-color-line-strong);
  border-radius: var(--wb-radius-control);
  background: var(--wb-color-section-soft);
}

.workbench-drop-zone > strong {
  font-size: var(--wb-font-size-body);
}

.workbench-drop-zone > small {
  font-size: var(--wb-font-size-small);
}

.workbench-upload-queue,
.workbench-documents,
.workbench-requirements {
  width: min(100%, var(--wb-form-max-width));
}

.workbench-upload-queue {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.workbench-documents {
  margin-block: var(--wb-space-3) var(--wb-space-5);
}

.workbench-documents > p,
.workbench-documents a strong,
.workbench-documents a small {
  font-size: var(--wb-font-size-small);
}

.workbench-requirements {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--wb-space-4);
}

.workbench-requirements textarea {
  min-height: var(--wb-textarea-min-height);
}

.workbench-schemes {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--wb-space-3);
}

.workbench-schemes > label {
  min-height: var(--wb-scheme-min-height);
  padding: var(--wb-space-4) var(--wb-scheme-label-end-padding) var(--wb-space-4) var(--wb-space-4);
  border-radius: var(--wb-radius-control);
}

.workbench-schemes strong {
  font-size: var(--wb-font-size-body);
}

.workbench-schemes em {
  font-size: var(--wb-font-size-small);
}

.workbench-settings,
.workbench-workflow-choice {
  margin-top: var(--wb-space-5);
  padding-top: var(--wb-space-5);
}

.workbench-settings {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--wb-space-4);
}

.workbench-settings--passive {
  grid-template-columns: minmax(0, var(--wb-passive-max-width));
}

.workbench-workflow-choice a {
  font-size: var(--wb-font-size-small);
}

.workbench-review {
  position: static;
  display: block;
  width: 100%;
  max-width: none;
  margin-top: var(--wb-space-6);
  padding: var(--wb-space-5);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-panel);
  background: var(--wb-color-section-soft);
  box-shadow: none;
}

.workbench-review__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--wb-space-4);
  margin-bottom: var(--wb-space-4);
}

.workbench-review__heading h3 {
  margin: var(--wb-space-1) 0 0;
  color: var(--wb-color-ink);
  font-size: var(--wb-review-title-size);
  line-height: var(--wb-line-height-compact);
}

.workbench-review__heading p {
  max-width: var(--wb-review-copy-max-width);
  margin: 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
  text-align: right;
}

.workbench-summary {
  display: grid;
  gap: var(--wb-space-1);
  margin: 0;
  padding: var(--wb-space-3) var(--wb-space-4);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-control);
  background: var(--wb-color-surface);
}

.workbench-summary span,
.workbench-summary small,
.workbench-summary strong {
  font-size: var(--wb-font-size-small);
}

.workbench-summary strong {
  font-size: var(--wb-font-size-body);
}

.workbench-checks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 var(--wb-space-4);
  margin: var(--wb-space-3) 0 0;
  padding: 0;
}

.workbench-checks li,
.workbench-checks li:nth-last-child(-n + 2) {
  padding: var(--wb-space-3) 0;
  border-bottom: var(--wb-border-width) solid var(--wb-color-line);
}

.workbench-checks strong,
.workbench-checks small,
.workbench-checks a {
  font-size: var(--wb-font-size-small);
}

.workbench-review > .workbench-inline-error,
.workbench-version-notice {
  margin-top: var(--wb-space-3);
  margin-bottom: 0;
}

.workbench-version-notice {
  font-size: var(--wb-font-size-small);
}

.workbench-start {
  display: inline-flex;
  width: 100%;
  min-height: var(--wb-start-min-height);
  margin-top: var(--wb-space-4);
  border-color: var(--wb-color-primary);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-surface);
  background: var(--wb-color-primary);
  font-size: var(--wb-font-size-body);
  box-shadow: none;
}

.recruitment-workbench .workbench-start:hover:not(:disabled) {
  border-color: var(--wb-color-primary-dark);
  background: var(--wb-color-primary-dark);
}

.workbench-start:disabled {
  border-color: var(--wb-color-line);
  color: var(--wb-color-muted);
  background: var(--wb-color-canvas);
}

.workbench-submit-hint,
.workbench-safety {
  font-size: var(--wb-font-size-small);
}

.workbench-safety {
  margin-top: var(--wb-space-4);
}

@media (max-width: 720px) {
  .recruitment-workbench {
    align-content: start;
  }

  .workbench-card {
    grid-template-columns: minmax(0, 1fr);
    min-height: 0;
    border-radius: var(--wb-space-6);
  }

  .workbench-sidebar {
    padding: var(--wb-space-5);
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-sidebar__intro {
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    column-gap: var(--wb-space-3);
  }

  .workbench-sidebar__intro > span {
    grid-column: 1 / -1;
  }

  .workbench-sidebar__intro > p {
    text-align: right;
  }

  .workbench-wizard {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--wb-space-2);
    margin-top: var(--wb-space-4);
  }

  .workbench-wizard__step {
    grid-template-columns: var(--wb-mobile-step-number-size) minmax(0, 1fr);
    column-gap: var(--wb-space-2);
    min-height: var(--wb-mobile-step-min-height);
    padding: var(--wb-space-2);
  }

  .workbench-wizard__step > span {
    width: var(--wb-mobile-step-number-size);
    height: var(--wb-mobile-step-number-size);
  }

  .workbench-wizard__step strong,
  .workbench-wizard__step small {
    font-size: var(--wb-font-size-small);
  }

  .workbench-workspace {
    padding: var(--wb-space-5);
  }

  .workbench-hero {
    align-items: flex-start;
    flex-direction: column;
    padding-bottom: var(--wb-space-4);
  }

  .workbench-main {
    margin-top: var(--wb-space-5);
  }

  .workbench-section--context {
    min-height: 0;
  }

  .workbench-section-heading {
    margin-bottom: var(--wb-space-5);
  }

  .workbench-section-heading h3 {
    font-size: var(--wb-mobile-section-title-size);
  }

  .workbench-requirements,
  .workbench-settings,
  .workbench-schemes,
  .workbench-upload-queue,
  .workbench-step-actions,
  .workbench-step-actions--forward,
  .workbench-step-actions--split,
  .workbench-step-actions--previous-only,
  .workbench-checks {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-step-actions {
    gap: var(--wb-space-3);
  }

  .workbench-step-actions > span,
  .workbench-step-actions--previous-only > span {
    text-align: left;
  }

  .workbench-step-actions button {
    width: 100%;
  }

  .workbench-step-actions--split .workbench-next {
    justify-self: stretch;
  }

  .workbench-workflow-choice,
  .workbench-review__heading {
    align-items: stretch;
    flex-direction: column;
  }

  .workbench-review__heading p {
    max-width: none;
    text-align: left;
  }

  .workbench-review {
    padding: var(--wb-space-4);
  }

  .workbench-checks li,
  .workbench-checks li:nth-last-child(-n + 2) {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-checks li:last-child {
    border-bottom: 0;
  }
}

@media (max-width: 520px) {
  .workbench-sidebar__intro > p,
  .workbench-wizard__step small {
    display: none;
  }

  .workbench-sidebar__intro {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-wizard__step {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
    text-align: center;
  }

  .workbench-wizard__step > span {
    grid-row: auto;
  }

  .workbench-wizard__step strong {
    text-align: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workbench-wizard__step,
  .workbench-drop-zone,
  .workbench-schemes > label {
    transition: none;
  }
}

/* Reference Round 2: stable four-step card and a single task title. */
.recruitment-workbench > .workbench-card {
  height: var(--wb-card-height);
  min-height: var(--wb-card-height);
  max-height: var(--wb-card-height);
}

.workbench-sidebar {
  min-height: 0;
  padding: var(--wb-space-6) var(--wb-space-5);
  overflow: hidden;
}

.workbench-sidebar__intro {
  gap: var(--wb-space-2);
}

.workbench-sidebar__intro > strong {
  font-size: var(--wb-font-size-title);
}

.workbench-wizard {
  gap: var(--wb-space-1);
  margin-top: var(--wb-space-5);
}

.workbench-wizard__step {
  min-height: var(--wb-step-min-height);
  padding: var(--wb-space-2) var(--wb-space-3);
}

.workbench-wizard__step.is-current.is-complete > span {
  border-color: var(--wb-color-primary);
  color: var(--wb-color-surface);
  background: var(--wb-color-primary);
}

.workbench-wizard__step:not(.is-current):not(.is-complete) > span {
  grid-row: 1;
}

.workbench-wizard__step:not(.is-current):not(.is-complete) strong {
  align-self: center;
}

.workbench-workspace {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.workbench-task-header {
  display: grid;
  gap: var(--wb-space-1);
  width: min(100%, var(--wb-form-max-width));
  flex: 0 0 auto;
  padding-bottom: var(--wb-space-4);
  border-bottom: var(--wb-border-width) solid var(--wb-color-line);
}

.workbench-task-header__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wb-space-4);
  min-width: 0;
}

.workbench-task-header h2 {
  margin: 0;
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-section);
  font-weight: var(--wb-font-weight-bold);
  line-height: var(--wb-heading-line-height);
  letter-spacing: var(--wb-letter-spacing-heading);
}

.workbench-task-header h2:focus {
  outline: none;
}

.workbench-task-header p {
  margin: 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-body);
  line-height: var(--wb-line-height-compact);
}

.workbench-task-header .workbench-runtime {
  flex: 0 0 auto;
  min-height: 0;
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  font-weight: var(--wb-font-weight-medium);
  letter-spacing: 0;
}

.workbench-task-header .workbench-runtime.is-ready {
  color: var(--wb-color-muted);
}

.workbench-notices {
  flex: 0 0 auto;
  margin-top: var(--wb-space-3);
}

.workbench-main {
  width: 100%;
  max-width: none;
  min-height: 0;
  flex: 1 1 auto;
  margin-top: var(--wb-space-5);
  padding-right: var(--wb-space-2);
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.workbench-section {
  width: min(100%, var(--wb-form-max-width));
}

.workbench-section--context {
  height: 100%;
  min-height: 100%;
}

.workbench-section--context .workbench-step-actions--forward {
  grid-template-columns: minmax(0, 1fr);
}

.workbench-section--context .workbench-next {
  justify-content: center;
  width: 100%;
}

.workbench-step-actions .secondary-button,
.recruitment-workbench .workbench-step-actions .workbench-next {
  font-size: var(--wb-font-size-body);
}

.workbench-drop-zone:focus-visible,
.workbench-drop-zone:focus-within {
  padding: calc(var(--wb-space-5) - var(--wb-border-width));
  border-width: var(--wb-focus-width);
  border-style: solid;
  border-color: var(--wb-color-primary);
  outline: none;
  box-shadow: none;
}

.workbench-review {
  position: static;
  display: block;
  width: min(100%, var(--wb-form-max-width));
  max-width: var(--wb-form-max-width);
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: var(--wb-color-transparent);
  box-shadow: none;
}

.workbench-review .workbench-summary {
  padding: var(--wb-space-3) var(--wb-space-4);
  border-color: var(--wb-color-line);
  background: var(--wb-color-section-soft);
}

.workbench-review .workbench-checks {
  margin-top: var(--wb-space-3);
}

.workbench-review-actions {
  grid-template-columns: auto minmax(0, 1fr);
}

.workbench-review-actions > span {
  text-align: right;
}

@media (max-width: 900px) {
  .recruitment-workbench {
    place-items: start center;
    align-content: start;
  }

  .recruitment-workbench > .workbench-card {
    grid-template-columns: minmax(0, 1fr);
    height: auto;
    min-height: 0;
    max-height: none;
  }

  .workbench-sidebar {
    padding: var(--wb-space-5) var(--wb-space-6);
    overflow: visible;
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-sidebar__intro {
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    column-gap: var(--wb-space-4);
  }

  .workbench-sidebar__intro > p {
    text-align: right;
  }

  .workbench-wizard {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--wb-space-2);
    margin-top: var(--wb-space-4);
  }

  .workbench-wizard__step {
    grid-template-columns: var(--wb-mobile-step-number-size) minmax(0, 1fr);
    column-gap: var(--wb-space-2);
    min-height: var(--wb-mobile-step-min-height);
    padding: var(--wb-space-2);
  }

  .workbench-wizard__step > span {
    width: var(--wb-mobile-step-number-size);
    height: var(--wb-mobile-step-number-size);
  }

  .workbench-workspace {
    height: auto;
    min-height: 0;
    overflow: visible;
  }

  .workbench-main {
    overflow: visible;
    scrollbar-gutter: auto;
  }

  .workbench-section--context {
    height: auto;
    min-height: 0;
  }
}

@media (max-width: 720px) {
  .workbench-sidebar {
    padding: var(--wb-space-5);
  }

  .workbench-wizard {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workbench-wizard__step {
    align-content: center;
    width: 100%;
    height: var(--wb-mobile-step-min-height);
    min-height: var(--wb-mobile-step-min-height);
    max-height: var(--wb-mobile-step-min-height);
    overflow: hidden;
  }

  .workbench-task-header__title {
    align-items: flex-start;
    flex-direction: column;
    gap: var(--wb-space-2);
  }

  .workbench-task-header h2 {
    font-size: var(--wb-font-size-section);
  }

  .workbench-section,
  .workbench-review {
    width: 100%;
    max-width: none;
  }

  .workbench-review .workbench-summary {
    padding: var(--wb-space-2) var(--wb-space-3);
  }

  .workbench-review .workbench-checks {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 var(--wb-space-3);
    margin-top: var(--wb-space-2);
  }

  .workbench-review .workbench-checks li {
    padding: var(--wb-space-2) 0;
  }

  .workbench-review .workbench-checks li:nth-last-child(-n + 2) {
    border-bottom: 0;
  }

  .workbench-review-actions {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-review-actions > span {
    text-align: left;
  }
}

@media (max-width: 520px) {
  .workbench-review .workbench-checks {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-review .workbench-checks li:nth-last-child(-n + 2) {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-review .workbench-checks li:last-child {
    border-bottom: 0;
  }
}
</style>

<style scoped>
/* Selected Product Design direction: Unified Task Canvas */
.recruitment-workbench {
  --wb-color-stage: #01a7af;
  --wb-color-surface: #fefefe;
  --wb-color-sidebar: #ecf7f7;
  --wb-color-sidebar-active: #ffffff;
  --wb-color-section-soft: #f5fbfb;
  --wb-color-ink: #10213a;
  --wb-color-secondary: #26364c;
  --wb-color-muted: #68788e;
  --wb-color-line: #dce4ec;
  --wb-color-line-strong: #b8cfda;
  --wb-color-primary: #01a7af;
  --wb-color-primary-dark: #078f98;
  --wb-color-primary-soft: #e3f7f7;
  --wb-color-primary-soft-hover: #f3fbfb;
  --wb-color-success: #20a653;
  --wb-color-success-border: #87d4aa;
  --wb-color-warning: #c17917;
  --wb-content-max-width: 1020px;
  --wb-card-max-width: 1020px;
  --wb-card-min-height: 680px;
  --wb-card-height: 680px;
  --wb-sidebar-width: 250px;
  --wb-workspace-padding-block: 30px;
  --wb-workspace-padding-inline: 34px;
  --wb-form-max-width: none;
  --wb-radius-card: 22px;
  --wb-radius-panel: 10px;
  --wb-radius-control: 8px;
  --wb-control-min-height: 46px;
  --wb-step-number-size: 40px;
  --wb-step-min-height: 72px;
  --wb-drop-zone-min-height: 132px;
  --wb-textarea-min-height: 112px;
  --wb-shadow-panel: 0 12px 30px rgba(6, 70, 78, .12);
  min-height: calc(100vh - 64px);
  padding: 28px 32px 40px;
  background: var(--wb-color-stage);
}

.recruitment-workbench > * {
  width: min(100%, var(--wb-card-max-width));
  max-width: var(--wb-card-max-width);
}

.workbench-card {
  grid-template-columns: var(--wb-sidebar-width) minmax(0, 1fr);
  height: var(--wb-card-height);
  min-height: var(--wb-card-min-height);
  border-radius: var(--wb-radius-card);
  background: var(--wb-color-surface);
  box-shadow: var(--wb-shadow-panel);
}

.workbench-sidebar {
  padding: 30px 20px;
  background: var(--wb-color-sidebar);
}

.workbench-sidebar__intro {
  display: block;
  padding: 0 8px;
}

.workbench-sidebar__intro > strong {
  color: var(--wb-color-ink);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -.025em;
}

.workbench-sidebar__intro > p {
  display: none;
}

.workbench-wizard {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  margin-top: 24px;
}

.workbench-wizard__step {
  grid-template-columns: 40px minmax(0, 1fr);
  min-height: 72px;
  padding: 10px 11px;
  border: 0;
  border-radius: 10px;
}

.workbench-wizard__step > span {
  display: grid;
  grid-row: 1 / span 2;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid #b9cddd;
  border-radius: 999px;
  color: #63758b;
  background: transparent;
  font-size: 12px;
  font-weight: 600;
}

.workbench-wizard__step strong {
  align-self: end;
  color: #405168;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.3;
}

.workbench-wizard__step small {
  align-self: start;
  margin-top: 2px;
  color: #75859a;
  font-size: 12px;
  line-height: 1.25;
}

.workbench-wizard__step.is-current {
  color: var(--wb-color-primary-dark);
  background: #fff;
}

.workbench-wizard__step.is-current > span {
  border-color: var(--wb-color-primary);
  color: #fff;
  background: var(--wb-color-primary);
}

.workbench-wizard__step.is-current strong,
.workbench-wizard__step.is-complete strong {
  color: var(--wb-color-ink);
}

.workbench-wizard__step.is-complete:not(.is-current) > span {
  border-color: var(--wb-color-success-border);
  color: var(--wb-color-success);
  background: #f7fffa;
}

.workbench-wizard__step:disabled {
  opacity: .76;
}

.workbench-workspace {
  min-height: 0;
  padding: 36px 56px 0 34px;
  overflow: hidden;
  background: var(--wb-color-surface);
}

.workbench-task-header {
  flex: 0 0 auto;
  min-height: 34px;
  margin: 0;
  padding: 0;
  border: 0;
}

.workbench-task-header__title {
  display: block;
}

.workbench-task-header h2 {
  margin: 0;
  color: var(--wb-color-ink);
  font-size: 24px;
  font-weight: 800;
  line-height: 1.25;
  letter-spacing: -.035em;
}

.workbench-task-header > p {
  display: none;
}

.workbench-notices {
  width: 100%;
  margin-top: 12px;
}

.workbench-main {
  width: 100%;
  max-width: none;
  min-height: 0;
  flex: 1;
  margin-top: 18px;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: #91a2b1 transparent;
}

.workbench-section {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-height: 100%;
  padding: 0;
}

.workbench-context-grid,
.workbench-requirements,
.workbench-settings {
  width: 100%;
  max-width: none;
}

.workbench-context-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  padding-top: 20px;
}

.workbench-context-grid label,
.workbench-requirements label,
.workbench-settings label,
.workbench-workflow-choice label {
  gap: 8px;
  color: var(--wb-color-secondary);
  font-size: 14px;
  font-weight: 700;
}

.workbench-context-grid select,
.workbench-requirements textarea,
.workbench-settings select,
.workbench-settings input,
.workbench-workflow-choice select {
  min-height: var(--wb-control-min-height);
  padding: 10px 13px;
  border: 1px solid #ced9e5;
  border-radius: 7px;
  color: var(--wb-color-ink);
  background: #fff;
  font-size: 14px;
  font-weight: 500;
  box-shadow: 0 1px 1px rgba(15, 33, 58, .02);
}

.workbench-context-grid select:focus,
.workbench-requirements textarea:focus,
.workbench-settings select:focus,
.workbench-settings input:focus,
.workbench-workflow-choice select:focus {
  border-color: var(--wb-color-primary);
  outline: 2px solid rgba(1, 167, 175, .16);
}

.workbench-context-readiness {
  margin-top: 48px;
  padding-top: 22px;
  border-top: 1px solid var(--wb-color-line);
}

.workbench-context-readiness > strong {
  display: block;
  margin-bottom: 20px;
  color: var(--wb-color-ink);
  font-size: 14px;
  font-weight: 800;
}

.workbench-context-readiness ul {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
  padding: 0;
  list-style: none;
}

.workbench-context-readiness li {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr);
  align-items: start;
  gap: 11px;
  min-width: 0;
  padding-right: 20px;
  color: var(--wb-color-muted);
}

.workbench-context-readiness li + li {
  padding-left: 24px;
  border-left: 1px solid var(--wb-color-line);
}

.workbench-context-readiness li > .app-icon {
  margin-top: 1px;
  color: var(--wb-color-warning);
}

.workbench-context-readiness li.is-ready > .app-icon {
  color: var(--wb-color-success);
}

.workbench-context-readiness li span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.workbench-context-readiness li b {
  color: var(--wb-color-secondary);
  font-size: 14px;
  line-height: 1.3;
}

.workbench-context-readiness li small {
  overflow: hidden;
  color: var(--wb-color-muted);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-upload-kind {
  width: 100%;
  margin: 0 0 12px;
}

.workbench-upload-kind > div strong {
  color: var(--wb-color-ink);
  font-size: 14px;
  font-weight: 800;
}

.workbench-drop-zone {
  width: 100%;
  min-height: var(--wb-drop-zone-min-height);
  padding: 18px;
  border: 1px dashed #9ec6d3;
  border-radius: 8px;
  background: #f7fcfc;
}

.workbench-drop-zone__icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  color: var(--wb-color-primary);
  background: #e2f7f7;
}

.workbench-drop-zone__icon .app-icon {
  width: 22px;
  height: 22px;
}

.workbench-drop-zone > strong {
  color: var(--wb-color-ink);
  font-size: 14px;
  font-weight: 800;
}

.workbench-drop-zone > small {
  color: var(--wb-color-muted);
  font-size: 12px;
}

.workbench-upload-queue,
.workbench-documents {
  display: grid;
  gap: 7px;
  width: 100%;
  margin: 8px 0 0;
  padding: 0;
}

.workbench-upload-queue li,
.workbench-documents a {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  min-height: 40px;
  padding: 7px 11px;
  border: 1px solid var(--wb-color-line);
  border-radius: 7px;
  color: var(--wb-color-secondary);
  background: #fff;
}

.workbench-documents a > .app-icon {
  color: #177fc2;
}

.workbench-documents a > span,
.workbench-upload-queue li > span {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workbench-documents a strong,
.workbench-upload-queue li strong {
  color: var(--wb-color-secondary);
  font-size: 12px;
  font-weight: 600;
}

.workbench-documents a small,
.workbench-upload-queue li small {
  color: var(--wb-color-muted);
  font-size: 11px;
}

.workbench-requirements {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  margin-top: 14px;
}

.workbench-requirements label > span {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workbench-requirements label > span b {
  color: var(--wb-color-ink);
  font-size: 14px;
  font-weight: 800;
}

.workbench-requirements label > span em {
  margin-left: 5px;
  color: var(--wb-color-muted);
  font-size: 12px;
  font-style: normal;
  font-weight: 500;
}

.workbench-requirements label > span small {
  color: var(--wb-color-muted);
  font-size: 12px;
  font-weight: 500;
}

.workbench-requirements textarea {
  min-height: 112px;
  padding: 12px;
  resize: vertical;
  line-height: 1.55;
}

.workbench-schemes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  width: 100%;
  margin: 0;
}

.workbench-schemes > label {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: center;
  min-height: 74px;
  padding: 13px 16px;
  border: 1px solid #d2dde7;
  border-radius: 8px;
  background: #fff;
}

.workbench-schemes > label.is-selected {
  border-color: var(--wb-color-primary);
  background: #f2fbfb;
  box-shadow: inset 0 0 0 1px var(--wb-color-primary);
}

.workbench-schemes input {
  position: static;
  width: 18px;
  height: 18px;
  margin: 0;
  opacity: 1;
  accent-color: var(--wb-color-primary);
}

.workbench-schemes label > span {
  display: grid;
  gap: 2px;
}

.workbench-schemes strong {
  color: var(--wb-color-ink);
  font-size: 14px;
  font-weight: 800;
}

.workbench-schemes em {
  color: var(--wb-color-muted);
  font-size: 12px;
  font-style: normal;
  font-weight: 500;
  line-height: 1.35;
}

.workbench-workflow-choice {
  display: block;
  width: 100%;
  margin-top: 14px;
}

.workbench-workflow-choice label {
  width: 100%;
}

.workbench-workflow-choice a {
  display: none;
}

.workbench-settings {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 24px;
  width: 100%;
  margin-top: 14px;
}

.workbench-settings--passive {
  grid-template-columns: minmax(0, 1fr);
  max-width: none;
}

.workbench-settings small {
  line-height: 1.3;
}

.workbench-review {
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
}

.workbench-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: 100%;
  margin: 0 0 12px;
  padding: 0;
  border: 1px solid var(--wb-color-line);
  border-radius: 8px;
  background: #fff;
}

.workbench-summary > div {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 13px 15px;
}

.workbench-summary > div + div {
  border-left: 1px solid var(--wb-color-line);
}

.workbench-summary .app-icon {
  color: var(--wb-color-primary);
}

.workbench-summary > div > span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.workbench-summary strong {
  overflow: hidden;
  color: var(--wb-color-ink);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench-summary small {
  color: var(--wb-color-muted);
  font-size: 11px;
}

.workbench-checks {
  display: grid;
  width: 100%;
  margin: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--wb-color-line);
  border-radius: 8px;
  background: #fff;
  list-style: none;
}

.workbench-checks li,
.workbench-checks li:nth-last-child(-n + 2) {
  display: grid;
  grid-template-columns: 22px 150px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--wb-color-line);
  background: #fff;
}

.workbench-checks li:last-child {
  border-bottom: 0;
}

.workbench-checks li > i {
  color: var(--wb-color-warning);
}

.workbench-checks li.is-ready > i {
  color: var(--wb-color-success);
}

.workbench-checks li > span {
  display: contents;
}

.workbench-checks strong {
  color: var(--wb-color-secondary);
  font-size: 13px;
  font-weight: 700;
}

.workbench-checks small,
.workbench-checks li.is-ready small {
  color: var(--wb-color-secondary);
  font-size: 12px;
  line-height: 1.35;
}

.workbench-checks a {
  color: var(--wb-color-primary-dark);
  font-size: 12px;
  font-weight: 700;
}

.workbench-submit-hint {
  margin: 8px 0 0;
  color: var(--wb-color-muted);
  font-size: 11px;
  text-align: left;
}

.workbench-safety {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  margin: 12px 0 0;
  padding: 11px 13px;
  border: 1px solid #cfe4ea;
  border-radius: 8px;
  color: var(--wb-color-secondary);
  background: #fbfefe;
  font-size: 12px;
  line-height: 1.4;
}

.workbench-safety .app-icon {
  flex: 0 0 auto;
  color: var(--wb-color-primary);
}

.workbench-step-actions {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  min-height: 76px;
  margin: auto -34px 0;
  padding: 16px 34px;
  border-top: 1px solid var(--wb-color-line);
}

.workbench-step-actions--forward {
  grid-template-columns: minmax(0, 1fr) auto;
}

.workbench-step-actions--split,
.workbench-review-actions {
  grid-template-columns: auto minmax(0, 1fr) auto;
}

.workbench-step-actions--split .workbench-next,
.workbench-review-actions .workbench-start {
  grid-column: 3;
  justify-self: end;
}

.workbench-step-actions .secondary-button,
.recruitment-workbench .workbench-step-actions .workbench-next,
.workbench-review-actions .workbench-start {
  min-width: 132px;
  min-height: 46px;
  padding: 10px 22px;
  border-radius: 7px;
  font-size: 15px;
  font-weight: 700;
}

.workbench-step-actions .secondary-button {
  border: 1px solid #cbd7e3;
  color: var(--wb-color-secondary);
  background: #fff;
}

.recruitment-workbench .workbench-step-actions .workbench-next,
.workbench-review-actions .workbench-start {
  border: 1px solid var(--wb-color-primary);
  color: #fff;
  background: var(--wb-color-primary);
  box-shadow: none;
}

.workbench-review-actions {
  width: auto;
  margin-top: auto;
}

.workbench-review-actions .workbench-start {
  position: static;
  width: auto;
  margin: 0;
  transform: none;
}

.workbench-review-actions .workbench-start:hover:not(:disabled) {
  transform: none;
}

@media (max-width: 900px) {
  .recruitment-workbench {
    padding: 20px;
  }

  .workbench-card {
    grid-template-columns: minmax(0, 1fr);
    height: auto;
    min-height: 720px;
  }

  .workbench-sidebar {
    padding: 20px 24px 14px;
  }

  .workbench-sidebar__intro {
    padding: 0;
  }

  .workbench-wizard {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 6px;
    margin-top: 14px;
  }

  .workbench-wizard__step {
    grid-template-columns: 34px minmax(0, 1fr);
    min-height: 60px;
    padding: 7px;
  }

  .workbench-wizard__step > span {
    width: 34px;
    height: 34px;
  }

  .workbench-workspace {
    min-height: 560px;
    padding: 24px 26px 0;
  }

  .workbench-step-actions {
    margin-right: -26px;
    margin-left: -26px;
    padding-right: 26px;
    padding-left: 26px;
  }
}

@media (max-width: 720px) {
  .recruitment-workbench {
    padding: 12px;
  }

  .workbench-card {
    border-radius: 16px;
  }

  .workbench-sidebar {
    padding: 18px;
  }

  .workbench-sidebar__intro > strong {
    font-size: 16px;
  }

  .workbench-wizard {
    overflow-x: auto;
  }

  .workbench-wizard__step {
    min-width: 132px;
  }

  .workbench-workspace {
    min-height: 600px;
    padding: 22px 18px 0;
  }

  .workbench-task-header h2 {
    font-size: 22px;
  }

  .workbench-context-grid,
  .workbench-requirements,
  .workbench-settings,
  .workbench-schemes,
  .workbench-context-readiness ul,
  .workbench-summary {
    grid-template-columns: minmax(0, 1fr);
  }

  .workbench-context-readiness li + li,
  .workbench-summary > div + div {
    margin-top: 10px;
    padding-top: 10px;
    padding-left: 0;
    border-top: 1px solid var(--wb-color-line);
    border-left: 0;
  }

  .workbench-checks li,
  .workbench-checks li:nth-last-child(-n + 2) {
    grid-template-columns: 20px minmax(0, 1fr) auto;
  }

  .workbench-checks li > span {
    display: grid;
    grid-column: 2;
    gap: 2px;
  }

  .workbench-step-actions {
    margin-right: -18px;
    margin-left: -18px;
    padding: 14px 18px;
  }

  .workbench-step-actions .secondary-button,
  .recruitment-workbench .workbench-step-actions .workbench-next,
  .workbench-review-actions .workbench-start {
    min-width: 0;
  }
}

@media (max-width: 520px) {
  .workbench-wizard__step strong,
  .workbench-wizard__step small {
    font-size: 11px;
  }

  .workbench-step-actions--split,
  .workbench-review-actions {
    grid-template-columns: 1fr 1fr;
  }

  .workbench-step-actions--split .workbench-next,
  .workbench-review-actions .workbench-start {
    grid-column: 2;
    width: 100%;
  }

  .workbench-step-actions .secondary-button {
    width: 100%;
  }
}

@media (min-width: 901px) {
  .workbench-main {
    overflow-x: hidden;
  }

  .workbench-step-actions {
    min-height: 66px;
    margin-right: 0;
    margin-left: 0;
    padding: 12px 0 0;
  }

  .workbench-section--context .workbench-next {
    grid-column: 2;
    justify-self: end;
    width: auto;
  }

  .workbench-schemes > label {
    min-height: 62px;
    padding-block: 9px;
  }

  .workbench-workflow-choice {
    margin-top: 10px;
  }

  .workbench-workflow-choice select,
  .workbench-settings select,
  .workbench-settings input {
    min-height: 42px;
    padding-block: 8px;
  }

  .workbench-settings {
    gap: 8px 24px;
    margin-top: 10px;
  }

  .workbench-settings small {
    font-size: 10px;
  }
}

.workbench-main {
  margin-top: 10px;
}

.workbench-workspace {
  padding-top: 28px;
}

.workbench-step-actions {
  min-height: 104px;
}

.workbench-context-readiness li.is-ready > svg.app-icon {
  color: var(--wb-color-success) !important;
}

.workbench-review .workbench-summary {
  order: 1;
  padding: 0;
  border: 1px solid var(--wb-color-line);
  background: #fff;
}

.workbench-review .workbench-summary .app-icon {
  color: var(--wb-color-primary) !important;
}

.workbench-review .workbench-checks {
  order: 2;
  grid-template-columns: minmax(0, 1fr) !important;
  margin-top: 0;
  padding: 0;
}

.workbench-review .workbench-checks li,
.workbench-review .workbench-checks li:nth-last-child(-n + 2) {
  grid-template-columns: 22px 150px minmax(0, 1fr) auto;
}

.workbench-review .workbench-checks li.is-ready small {
  display: block;
}

.workbench-review-actions {
  order: 8;
  margin-top: auto;
}

@media (min-width: 901px) {
  .workbench-section--plan .workbench-schemes > label {
    min-height: 62px;
    padding-block: 9px;
  }

  .workbench-section--plan .workbench-workflow-choice,
  .workbench-section--plan .workbench-settings {
    margin-top: 10px;
  }

  .workbench-section--plan .workbench-settings {
    gap: 10px 24px;
  }

  .workbench-section--plan .workbench-step-actions {
    min-height: 94px;
  }

  .workbench-task-header h2 {
    font-size: 26px;
  }

  .workbench-context-grid {
    gap: 28px;
    padding-top: 28px;
  }

  .workbench-context-grid label,
  .workbench-requirements label,
  .workbench-settings label,
  .workbench-workflow-choice label {
    font-size: 15px;
  }

  .workbench-context-grid select {
    min-height: 54px;
    padding-inline: 16px;
    font-size: 15px;
  }

  .workbench-context-readiness {
    margin-top: 52px;
    padding-top: 28px;
  }

  .workbench-context-readiness > strong,
  .workbench-context-readiness li b {
    font-size: 15px;
  }

  .workbench-drop-zone {
    min-height: 144px;
  }

  .workbench-requirements textarea {
    min-height: 120px;
    font-size: 15px;
  }

  .workbench-schemes > label {
    min-height: 70px;
    padding-block: 12px;
  }

  .workbench-workflow-choice select,
  .workbench-settings select,
  .workbench-settings input {
    min-height: 46px;
  }

  .workbench-summary > div {
    min-height: 72px;
    padding-block: 14px;
  }

  .workbench-checks li,
  .workbench-checks li:nth-last-child(-n + 2) {
    min-height: 50px;
  }

  .workbench-safety {
    min-height: 46px;
  }
}
</style>
