<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const auth = useAuthStore()
const context = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()

const WIZARD_DRAFT_VERSION = 1
const WIZARD_STEPS = ['context', 'standard', 'plan']
const MAX_JOB_DOCUMENT_SIZE = 25 * 1024 * 1024
const JOB_DOCUMENT_SUFFIX = /\.(doc|docx|xlsx)$/i

const accounts = ref([])
const policies = ref([])
const workflowTemplates = ref([])
const workflowVersions = ref([])
const documents = ref([])
const loading = ref(true)
const documentsLoading = ref(false)
const loadError = ref('')
const documentError = ref('')
const submitError = ref('')
const selectedAccountId = ref('')
const documentCategory = ref('persona')
const fileInput = ref(null)
const stepHeading = ref(null)
const currentStep = ref('context')
const completedSteps = reactive({ context: false, standard: false })
const wizardError = ref('')
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
const targetResumeCount = ref(3)
const maxScanCount = ref(20)
const submitting = ref(false)
const submitStage = ref('')
const receipt = ref(null)
const operationState = ref(null)
const summary = reactive({ worker: null, cli_available: false })
let documentLoadSequence = 0

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
const enabledWorkflowOptions = computed(() => workflowVersions.value
  .filter((version) => version.status === 'enabled' && String(version.boss_account) === String(selectedAccountId.value))
  .map((version) => ({
    id: version.id,
    label: `${workflowTemplates.value.find((item) => item.id === version.template)?.name || `流程 ${version.template}`} · V${version.version}`,
  })))
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
const wizardSteps = computed(() => [
  { key: 'context', number: '01', label: '职位与账号', reachable: true },
  { key: 'standard', number: '02', label: '画像与要求', reachable: completedSteps.context },
  { key: 'plan', number: '03', label: '方案与执行', reachable: completedSteps.context && completedSteps.standard },
])

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
const canSubmit = computed(() => (
  !loading.value
  && !uploading.value
  && !submitting.value
  && !receipt.value
  && currentStep.value === 'plan'
  && checks.value.every((item) => item.ok)
))
const resultsLink = computed(() => receipt.value ? {
  path: '/recruitment/results',
  query: { job: String(receipt.value.jobId), run: String(receipt.value.run.id), view: 'tasks' },
} : null)

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

function statusLabel(status) {
  return {
    pending: '等待执行',
    running: '执行中',
    waiting_human: '等待人工处理',
    paused: '已暂停',
    succeeded: '已完成',
    failed: '执行失败',
    cancelled: '已取消',
  }[status] || status || '已创建'
}

function requestId() {
  return globalThis.crypto?.randomUUID?.()
    || `00000000-0000-4000-8000-${Date.now().toString().padStart(12, '0').slice(-12)}`
}

function operationStorageKey(jobId = selectedJob.value?.id) {
  if (!jobId) return ''
  return `ximing-hr:recruitment-operation:${auth.user?.id || 'unknown'}:${jobId}`
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
    targetResumeCount: Number(targetResumeCount.value),
    maxScanCount: Number(maxScanCount.value),
  }
}

function operationFingerprint() {
  return JSON.stringify({
    job: selectedJob.value?.id || null,
    account: selectedAccountId.value || null,
    ...operationDraft(),
  })
}

function persistOperation(state = operationState.value) {
  const key = operationStorageKey(state?.jobId)
  if (!key || !state) return
  sessionStorage.setItem(key, JSON.stringify(state))
}

function wizardStorageKey(jobId = selectedJob.value?.id) {
  if (!jobId) return ''
  return `ximing-hr:recruitment-workbench-draft:v${WIZARD_DRAFT_VERSION}:${auth.user?.id || 'unknown'}:${jobId}`
}

function resetWizardFields() {
  documentCategory.value = 'persona'
  schemeKind.value = 'passive_resume'
  workflowChoice.value = 'standard'
  coreText.value = ''
  bonusText.value = ''
  interval.value = 2
  source.value = 'search'
  keyword.value = ''
  targetResumeCount.value = 3
  maxScanCount.value = 20
  completedSteps.context = false
  completedSteps.standard = false
  restoredWizardStep.value = 'context'
  currentStep.value = 'context'
  wizardError.value = ''
  dragging.value = false
  uploadQueue.value = []
}

function persistWizardDraft(jobId = selectedJob.value?.id) {
  if (!wizardReady.value || wizardHydrating.value || !jobId) return
  const key = wizardStorageKey(jobId)
  if (!key) return
  sessionStorage.setItem(key, JSON.stringify({
    version: WIZARD_DRAFT_VERSION,
    jobId: String(jobId),
    selectedAccountId: String(selectedAccountId.value || ''),
    step: currentStep.value,
    completed: {
      context: completedSteps.context,
      standard: completedSteps.standard,
    },
    documentCategory: documentCategory.value,
    draft: operationDraft(),
  }))
}

function restoreWizardDraft(jobId = selectedJob.value?.id) {
  const key = wizardStorageKey(jobId)
  if (!key) return false
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) || 'null')
    if (
      !stored
      || stored.version !== WIZARD_DRAFT_VERSION
      || String(stored.jobId) !== String(jobId)
    ) return false
    applyOperationDraft(stored.draft)
    documentCategory.value = ['persona', 'requirement', 'other'].includes(stored.documentCategory)
      ? stored.documentCategory
      : 'persona'
    completedSteps.context = stored.completed?.context === true
    completedSteps.standard = stored.completed?.standard === true
    restoredWizardStep.value = WIZARD_STEPS.includes(stored.step) ? stored.step : 'context'
    return true
  } catch {
    sessionStorage.removeItem(key)
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
  return normalized
}

async function focusCurrentStep() {
  await nextTick()
  stepHeading.value?.focus?.()
}

function resolveWizardStep({ replaceInvalid = true } = {}) {
  if (!wizardReady.value) return
  const requested = WIZARD_STEPS.includes(String(route.query.step || ''))
    ? String(route.query.step)
    : restoredWizardStep.value
  const guarded = guardedWizardStep(requested)
  currentStep.value = guarded
  const jobId = selectedJob.value?.id
  const queryStep = String(route.query.step || '')
  const queryJob = String(route.query.job || '')
  if (replaceInvalid && (queryStep !== guarded || (jobId && queryJob !== String(jobId)))) {
    const query = { ...route.query, step: guarded }
    if (jobId) query.job = String(jobId)
    router.replace({ name: route.name, query }).catch(() => {})
  }
  persistWizardDraft()
  focusCurrentStep()
}

function navigateWizardStep(step, { replace = false } = {}) {
  const guarded = guardedWizardStep(step)
  currentStep.value = guarded
  restoredWizardStep.value = guarded
  wizardError.value = ''
  persistWizardDraft()
  const query = { ...route.query, step: guarded }
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

function previousStep() {
  const index = WIZARD_STEPS.indexOf(currentStep.value)
  if (index > 0) navigateWizardStep(WIZARD_STEPS[index - 1])
}

function markStandardDirty() {
  if (!wizardReady.value || wizardHydrating.value) return
  completedSteps.standard = false
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
  targetResumeCount.value = Number(draft.targetResumeCount || 3)
  maxScanCount.value = Number(draft.maxScanCount || 20)
}

function restoreOperation(jobId = selectedJob.value?.id) {
  operationState.value = null
  receipt.value = null
  const key = operationStorageKey(jobId)
  if (!key) return
  try {
    const stored = JSON.parse(sessionStorage.getItem(key) || 'null')
    if (!stored || String(stored.jobId) !== String(jobId)) return
    operationState.value = stored
    applyOperationDraft(stored.draft)
    receipt.value = stored.receipt || null
  } catch {
    sessionStorage.removeItem(key)
  }
}

function beginNewTask() {
  const key = operationStorageKey()
  if (key) sessionStorage.removeItem(key)
  operationState.value = null
  receipt.value = null
  submitError.value = ''
  submitStage.value = ''
  persistWizardDraft()
}

function replaceJobQuery(jobId, { step } = {}) {
  const query = { ...route.query }
  if (jobId) query.job = String(jobId)
  else delete query.job
  if (step) query.step = step
  router.replace({ name: route.name, query }).catch(() => {})
}

function chooseJob(jobId, { updateRoute = true } = {}) {
  const normalized = jobId === null || jobId === undefined ? '' : String(jobId)
  const job = context.jobs.find((item) => String(item.id) === normalized)
  if (!job) return
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

function alignInitialSelection() {
  const queryJobId = route.query.job ? String(route.query.job) : ''
  if (queryJobId && context.jobs.some((job) => String(job.id) === queryJobId)) {
    chooseJob(queryJobId, { updateRoute: false })
    return
  }
  if (selectedJob.value) {
    selectedAccountId.value = selectedJob.value.boss_account ? String(selectedJob.value.boss_account) : ''
    replaceJobQuery(selectedJob.value.id)
    return
  }
  const defaultJob = context.jobs.find((job) => accounts.value.some((account) => (
    String(account.id) === String(job.boss_account) && account.login_status === 'ready'
  ))) || context.jobs[0]
  if (defaultJob) chooseJob(defaultJob.id)
  else if (accounts.value[0]) selectedAccountId.value = String(accounts.value[0].id)
}

async function loadWorkbench() {
  loading.value = true
  loadError.value = ''
  wizardHydrating.value = true
  try {
    if (!context.loaded) {
      await context.loadJobs({ userId: auth.user?.id })
    }
    const [accountResult, policyResult, summaryResult, templateResult, versionResult] = await Promise.allSettled([
      api('recruitment/boss-accounts/'),
      api('recruitment/message-sync-policies/'),
      api('recruitment/automation/summary/'),
      api('recruitment/workflows/'),
      api('recruitment/workflow-versions/'),
    ])
    if (accountResult.status === 'rejected') throw accountResult.reason
    accounts.value = listItems(accountResult.value).filter((account) => account.active && !account.archived_at)
    policies.value = policyResult.status === 'fulfilled' ? listItems(policyResult.value) : []
    workflowTemplates.value = templateResult.status === 'fulfilled' ? listItems(templateResult.value) : []
    workflowVersions.value = versionResult.status === 'fulfilled' ? listItems(versionResult.value) : []
    if (summaryResult.status === 'fulfilled') Object.assign(summary, summaryResult.value)
    else loadError.value = `自动化服务状态读取失败：${summaryResult.reason?.message || '请稍后重试'}`
    alignInitialSelection()
    restoreWizardDraft(selectedJob.value?.id)
    restoreOperation(selectedJob.value?.id)
    if (receipt.value) {
      completedSteps.context = true
      completedSteps.standard = true
      restoredWizardStep.value = 'plan'
    }
  } catch (error) {
    loadError.value = error.message || '招聘作业台加载失败'
  } finally {
    wizardHydrating.value = false
    loading.value = false
    wizardReady.value = true
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

  uploading.value = true
  const failedFiles = queue
    .filter((item) => item.status === 'failed')
    .map((item) => `${item.name}：${item.error}`)
  let succeeded = 0
  const jobId = selectedJob.value.id
  try {
    for (const item of validItems) {
      item.status = 'uploading'
      const body = new FormData()
      body.append('job', String(jobId))
      body.append('category', documentCategory.value)
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
  }
}

async function savePassivePolicy() {
  const existing = policies.value.find((item) => String(item.boss_account) === String(selectedAccountId.value))
  const body = JSON.stringify({
    boss_account: Number(selectedAccountId.value),
    enabled: true,
    interval_minutes: Number(interval.value),
  })
  const policy = await api(
    existing ? `recruitment/message-sync-policies/${existing.id}/` : 'recruitment/message-sync-policies/',
    { method: existing ? 'PATCH' : 'POST', body },
  )
  if (existing) policies.value = policies.value.map((item) => item.id === existing.id ? policy : item)
  else policies.value.push(policy)
}

async function startExecution() {
  if (submitting.value) return
  if (!canSubmit.value) {
    submitError.value = firstBlockingCheck.value?.detail || '请先完成执行前检查'
    return
  }
  submitting.value = true
  submitError.value = ''
  try {
    const fingerprint = operationFingerprint()
    if (!operationState.value || operationState.value.fingerprint !== fingerprint || operationState.value.receipt) {
      operationState.value = {
        jobId: selectedJob.value.id,
        fingerprint,
        requestId: requestId(),
        draft: operationDraft(),
        versionId: null,
        enabledId: null,
        receipt: null,
      }
      persistOperation()
    }
    if (schemeKind.value === 'passive_resume') {
      submitStage.value = '正在保存消息同步设置…'
      await savePassivePolicy()
    }
    const requirements = { core: coreItems.value, bonus: bonusItems.value }
    const config = schemeKind.value === 'passive_resume'
      ? {
          reply_message: '您好，这边是招聘岗位，方便发送一份简历进一步沟通吗？',
          ...requirements,
        }
      : {
          source: source.value,
          keyword: keyword.value.trim(),
          target_resume_count: Number(targetResumeCount.value),
          max_scan_count: Number(maxScanCount.value),
          ...requirements,
        }

    let enabledId = operationState.value.enabledId
    if (workflowChoice.value === 'standard') {
      let versionId = operationState.value.versionId
      if (!versionId) {
        submitStage.value = '正在创建可追溯流程版本…'
        const created = await api('recruitment/workflows/standard/', {
          method: 'POST',
          body: JSON.stringify({
            kind: schemeKind.value,
            boss_account: Number(selectedAccountId.value),
            config,
          }),
        })
        versionId = created.version.id
        operationState.value.versionId = versionId
        persistOperation()
      }
      if (!enabledId) {
        submitStage.value = '正在校验并启用流程…'
        const enabled = await api(`recruitment/workflow-versions/${versionId}/enable/`, { method: 'POST' })
        enabledId = enabled.id
        operationState.value.enabledId = enabledId
        persistOperation()
      }
    } else {
      enabledId = selectedCustomWorkflow.value.id
      operationState.value.versionId = enabledId
      operationState.value.enabledId = enabledId
      persistOperation()
    }

    submitStage.value = '正在创建正式运行…'
    const run = await api(`recruitment/workflow-versions/${enabledId}/run/`, {
      method: 'POST',
      body: JSON.stringify({
        mode: 'formal',
        request_id: operationState.value.requestId,
        job: Number(selectedJob.value.id),
        input: {
          scheme: schemeKind.value,
          source: schemeKind.value === 'active_resume_search' ? source.value : 'messages',
          keyword: keyword.value.trim(),
          ...requirements,
        },
        confirm: true,
      }),
    })
    const completedReceipt = {
      run,
      jobId: selectedJob.value.id,
      jobTitle: selectedJob.value.title,
      accountName: selectedAccount.value.name,
      scheme: schemeKind.value,
    }
    receipt.value = completedReceipt
    operationState.value.receipt = completedReceipt
    persistOperation()
    submitStage.value = ''
  } catch (error) {
    submitError.value = `${submitStage.value ? `${submitStage.value.replace(/正在|…/g, '')}失败：` : ''}${error.message || '无法创建招聘作业'}`
  } finally {
    submitting.value = false
    submitStage.value = ''
  }
}

watch(
  () => selectedJob.value?.id,
  (jobId, previousJobId) => {
    if (previousJobId && String(previousJobId) !== String(jobId)) persistWizardDraft(previousJobId)
    wizardHydrating.value = true
    documentLoadSequence += 1
    documents.value = []
    operationState.value = null
    receipt.value = null
    submitError.value = ''
    resetWizardFields()
    if (jobId) {
      const job = context.jobs.find((item) => String(item.id) === String(jobId))
      selectedAccountId.value = job?.boss_account ? String(job.boss_account) : ''
      loadDocuments(jobId)
      restoreWizardDraft(jobId)
      restoreOperation(jobId)
      if (receipt.value) {
        completedSteps.context = true
        completedSteps.standard = true
        restoredWizardStep.value = 'plan'
      }
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
  () => route.query.step,
  () => resolveWizardStep(),
)

watch([coreText, bonusText], () => {
  if (currentStep.value === 'standard') markStandardDirty()
}, { flush: 'sync' })

watch(
  [schemeKind, workflowChoice, interval, source, keyword, targetResumeCount, maxScanCount, documentCategory, selectedAccountId],
  () => persistWizardDraft(),
)

watch(
  () => [completedSteps.context, completedSteps.standard, currentStep.value],
  () => persistWizardDraft(),
)

watch(enabledWorkflowOptions, (options) => {
  if (workflowChoice.value !== 'standard' && !options.some((item) => `custom:${item.id}` === workflowChoice.value)) {
    workflowChoice.value = 'standard'
  }
})

onMounted(loadWorkbench)
</script>

<template>
  <div class="page-stack recruitment-workbench">
    <header class="page-hero page-hero--compact workbench-hero">
      <div>
        <span class="eyebrow">Recruitment Workbench</span>
        <h2>招聘作业台</h2>
        <p>在一个页面准备岗位依据、招聘要求和执行方案，确认无阻塞后发起自动化。</p>
      </div>
      <span :class="['workbench-runtime', { 'is-ready': runtimeReady }]">
        <i></i>{{ runtimeReady ? '自动化服务已就绪' : '自动化服务待检查' }}
      </span>
    </header>

    <p v-if="loadError" class="workbench-error" role="alert">{{ loadError }}</p>

    <section v-if="loading" class="panel workbench-loading" aria-live="polite">
      <span></span><span></span><span></span>
      <p>正在读取职位、账号与运行条件…</p>
    </section>

    <template v-else>
      <div class="workbench-layout">
        <main class="panel workbench-main">
          <section class="workbench-section workbench-section--context" aria-labelledby="workbench-context-title">
            <header class="workbench-section-heading">
              <div><span>STEP 01</span><h3 id="workbench-context-title">选择本次作业</h3></div>
              <p>职位与 BOSS 账号必须属于同一授权范围。</p>
            </header>
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
                <small v-else>{{ selectedJob?.jd ? '已归档职位描述，可继续补充画像与要求。' : '职位已同步，可补充岗位依据。' }}</small>
              </label>
              <label>
                <span>执行账号</span>
                <select v-model="selectedAccountId" data-test="workbench-account" :disabled="uploading || submitting || !accounts.length" @change="chooseAccount">
                  <option value="">请选择 BOSS 账号</option>
                  <option v-for="account in accounts" :key="account.id" :value="String(account.id)">
                    {{ account.name }} · {{ account.login_status_label || accountReadinessMessage(account) }}
                  </option>
                </select>
                <small v-if="selectedAccount">账号环境：{{ selectedAccount.browser_type === 'edge' ? 'Edge' : 'Chrome' }} · CDP {{ selectedAccount.cdp_port }}</small>
                <small v-else>没有可用账号时，请先在管理后台添加并登录。</small>
              </label>
            </div>
            <div v-if="!context.jobs.length || !accounts.length" class="workbench-empty-actions">
              <router-link :to="{ path: '/recruitment/admin', query: { section: !accounts.length ? 'accounts' : 'jobs' } }">
                前往管理后台处理 <AppIcon name="arrow-right" :size="14" />
              </router-link>
            </div>
          </section>

          <section class="workbench-section" aria-labelledby="workbench-standard-title">
            <header class="workbench-section-heading">
              <div><span>STEP 02</span><h3 id="workbench-standard-title">招聘标准</h3></div>
              <p>画像与需求文件将归档到当前职位；文字要求同时用于主动寻访。</p>
            </header>

            <div class="workbench-upload">
              <div class="workbench-upload__copy">
                <i><AppIcon name="document" :size="21" /></i>
                <div><strong>岗位依据文件</strong><small>支持一次选择多个 DOC、DOCX 或 XLSX，系统按文件逐个归档。</small></div>
              </div>
              <div class="workbench-upload__actions">
                <label>
                  <span class="sr-only">文档用途</span>
                  <select v-model="documentCategory" data-test="document-category" :disabled="uploading || submitting">
                    <option value="persona">候选人画像</option>
                    <option value="requirement">招聘需求</option>
                    <option value="other">其他标准</option>
                  </select>
                </label>
                <input
                  ref="fileInput"
                  data-test="workbench-file-input"
                  type="file"
                  accept=".doc,.docx,.xlsx"
                  multiple
                  hidden
                  @change="uploadDocuments"
                />
                <button class="secondary-button" data-test="workbench-upload" type="button" :disabled="!selectedJob || uploading || submitting" @click="fileInput?.click()">
                  <AppIcon name="upload" :size="16" />
                  {{ uploading ? `上传中 ${uploadProgress.completed}/${uploadProgress.total}` : '添加依据文件' }}
                </button>
              </div>
            </div>

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
              <p v-else>尚未上传岗位依据；不影响本次自动化，后续生成评分标准时需要补充。</p>
            </div>

            <div class="workbench-requirements">
              <label>
                <span>核心要求 <em>主动寻访必填，每行一项</em></span>
                <textarea v-model="coreText" data-test="core-requirements" rows="5" maxlength="2000" placeholder="例如：\n3 年以上 Python 开发经验\n熟悉 Django 与关系型数据库"></textarea>
                <small>已识别 {{ coreItems.length }}/10 项；每项最多 200 字。</small>
              </label>
              <label>
                <span>加分项 <em>选填，每行一项</em></span>
                <textarea v-model="bonusText" data-test="bonus-requirements" rows="5" maxlength="2000" placeholder="例如：\n有 AI 应用落地经验\n做过复杂后台系统"></textarea>
                <small>已识别 {{ bonusItems.length }}/10 项。</small>
              </label>
            </div>
          </section>

          <section class="workbench-section" aria-labelledby="workbench-scheme-title">
            <header class="workbench-section-heading">
              <div><span>STEP 03</span><h3 id="workbench-scheme-title">执行方案</h3></div>
              <p>选择一个业务目标，再设置本次运行参数。</p>
            </header>

            <fieldset class="workbench-schemes">
              <legend class="sr-only">选择执行方案</legend>
              <label :class="{ 'is-selected': schemeKind === 'passive_resume' }">
                <input v-model="schemeKind" data-test="scheme-passive" type="radio" value="passive_resume" />
                <i><AppIcon name="workflow" :size="20" /></i>
                <span><small>被动咨询</small><strong>同步消息并获取简历</strong><em>询问了解岗位时只提醒 HR，不直接索要简历。</em></span>
              </label>
              <label :class="{ 'is-selected': schemeKind === 'active_resume_search' }">
                <input v-model="schemeKind" data-test="scheme-active" type="radio" value="active_resume_search" />
                <i><AppIcon name="search" :size="20" /></i>
                <span><small>主动寻访</small><strong>搜索并拉取在线简历</strong><em>按目标数和扫描上限执行，完成后提醒 HR 介入。</em></span>
              </label>
            </fieldset>

            <div class="workbench-workflow-choice">
              <label>
                <span>运行流程</span>
                <select v-model="workflowChoice" data-test="workflow-choice" :disabled="submitting || Boolean(receipt)">
                  <option value="standard">标准流程（按本页设置生成）</option>
                  <option v-for="option in enabledWorkflowOptions" :key="option.id" :value="`custom:${option.id}`">
                    {{ option.label }}
                  </option>
                </select>
                <small>{{ enabledWorkflowOptions.length ? '也可直接运行管理后台已启用、且属于当前账号的高级流程。' : '当前账号暂无已启用的高级流程，使用标准流程即可。' }}</small>
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
          </section>
        </main>

        <aside class="panel workbench-review" aria-labelledby="workbench-review-title">
          <header class="workbench-section-heading">
            <div><span>FINAL CHECK</span><h3 id="workbench-review-title">执行前检查</h3></div>
          </header>
          <ol class="workbench-checks">
            <li v-for="item in checks" :id="`precheck-${item.key}`" :key="item.key" :class="{ 'is-ready': item.ok }" :data-test="`precheck-${item.key}`">
              <i><AppIcon :name="item.ok ? 'check-circle' : 'alert-circle'" :size="17" /></i>
              <span><strong>{{ item.label }}</strong><small>{{ item.detail }}</small></span>
              <router-link v-if="item.link" :to="item.link">处理</router-link>
            </li>
          </ol>

          <div class="workbench-summary">
            <span>本次作业</span>
            <strong>{{ selectedJob?.title || '尚未选择职位' }}</strong>
            <small>{{ selectedAccount?.name || '尚未选择账号' }} · {{ schemeKind === 'passive_resume' ? '被动咨询' : `主动寻访 ${targetResumeCount} 份` }}</small>
          </div>

          <p v-if="submitError" class="workbench-inline-error" role="alert">{{ submitError }}</p>
          <button
            class="primary-button workbench-start"
            data-test="start-execution"
            type="button"
            :disabled="!canSubmit"
            :aria-describedby="firstBlockingCheck ? `precheck-${firstBlockingCheck.key}` : undefined"
            @click="startExecution"
          >
            <AppIcon name="arrow-right" :size="17" />
            {{ submitting ? submitStage : (receipt ? '本次作业已提交' : '开始执行') }}
          </button>
          <small class="workbench-submit-hint">
            {{ receipt ? '本次运行已锁定，避免重复提交；如需重新执行，请先新建任务。' : (firstBlockingCheck ? `请先处理：${firstBlockingCheck.label}` : '点击后将创建、校验并运行一份可追溯流程版本。') }}
          </small>

          <section v-if="receipt" class="workbench-receipt" data-test="execution-receipt" aria-live="polite">
            <i><AppIcon name="check-circle" :size="22" /></i>
            <div>
              <span>招聘作业已创建</span>
              <strong>运行编号 {{ receipt.run.id }}</strong>
              <small>{{ receipt.jobTitle }} · {{ receipt.accountName }} · {{ statusLabel(receipt.run.status) }}</small>
              <router-link data-test="view-results" :to="resultsLink">
                查看结果 <AppIcon name="arrow-right" :size="14" />
              </router-link>
              <button class="workbench-new-task" data-test="new-task" type="button" @click="beginNewTask">新建任务</button>
            </div>
          </section>

          <p class="workbench-safety"><AppIcon name="shield" :size="15" /> 外发、身份复核、额度与人工确认继续由服务端安全门控制。</p>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.recruitment-workbench {
  --wb-color-canvas: #f3f6f8;
  --wb-color-surface: #ffffff;
  --wb-color-ink: #0f172a;
  --wb-color-secondary: #334155;
  --wb-color-muted: #64748b;
  --wb-color-line: #e2e8f0;
  --wb-color-primary: #0f9f8f;
  --wb-color-primary-dark: #087f73;
  --wb-color-warning: #d97706;
  --wb-color-danger: #dc4a4a;
  --wb-font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --wb-font-size-meta: 10px;
  --wb-font-size-small: 11px;
  --wb-font-size-control: 12px;
  --wb-font-size-body: 13px;
  --wb-font-size-section: 17px;
  --wb-font-weight-medium: 500;
  --wb-font-weight-semibold: 600;
  --wb-font-weight-bold: 700;
  --wb-font-weight-heavy: 800;
  --wb-line-height-compact: 1.45;
  --wb-line-height-body: 1.6;
  --wb-letter-spacing-kicker: .14em;
  --wb-space-1: 4px;
  --wb-space-2: 8px;
  --wb-space-3: 12px;
  --wb-space-4: 16px;
  --wb-space-5: 22px;
  --wb-space-6: 28px;
  --wb-radius-control: 9px;
  --wb-radius-panel: 15px;
  --wb-radius-status: 6px;
  --wb-radius-pill: 999px;
  --wb-border-width: 1px;
  --wb-focus-width: 2px;
  --wb-control-min-height: 42px;
  --wb-status-dot-size: 8px;
  --wb-upload-icon-size: 34px;
  --wb-check-icon-column: 20px;
  --wb-aside-min-width: 304px;
  --wb-aside-max-width: 320px;
  --wb-sticky-offset: 82px;
  --wb-loading-min-height: 220px;
  --wb-loading-line-height: 14px;
  --wb-copy-max-width: 520px;
  --wb-passive-max-width: 420px;
  --wb-textarea-min-height: 116px;
  --wb-document-min-width: 180px;
  --wb-upload-select-min-width: 116px;
  --wb-shadow-panel: 0 1px 2px rgba(15, 23, 42, .025);
  --wb-transition: 180ms ease;
  min-width: 0;
  max-width: 100%;
  container-name: workbench-page;
  container-type: inline-size;
  font-family: var(--wb-font-family);
}

.recruitment-workbench,
.recruitment-workbench * {
  box-sizing: border-box;
}

.workbench-hero {
  align-items: center;
}

.workbench-runtime {
  display: inline-flex;
  align-items: center;
  gap: var(--wb-space-2);
  padding: 0;
  border: 0;
  color: var(--wb-color-warning);
  background: transparent;
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
  background: transparent;
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

.workbench-loading {
  min-height: var(--wb-loading-min-height);
  display: grid;
  place-items: center;
  align-content: center;
  gap: var(--wb-space-2);
  color: var(--wb-color-muted);
  box-shadow: var(--wb-shadow-panel);
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

.workbench-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(var(--wb-aside-min-width), var(--wb-aside-max-width));
  gap: var(--wb-space-5);
  align-items: start;
  min-width: 0;
}

.workbench-main {
  display: block;
  min-width: 0;
  padding: 0;
  overflow: hidden;
  border-radius: var(--wb-radius-panel);
  background: var(--wb-color-surface);
  box-shadow: var(--wb-shadow-panel);
}

.workbench-section {
  min-width: 0;
  padding: var(--wb-space-5);
}

.workbench-section + .workbench-section {
  border-top: var(--wb-border-width) solid var(--wb-color-line);
}

.workbench-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--wb-space-4);
  margin-bottom: var(--wb-space-4);
}

.workbench-section-heading div > span {
  display: block;
  color: var(--wb-color-primary-dark);
  font-size: var(--wb-font-size-meta);
  font-weight: var(--wb-font-weight-heavy);
  letter-spacing: var(--wb-letter-spacing-kicker);
}

.workbench-section-heading h3 {
  margin: var(--wb-space-1) 0 0;
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-section);
  font-weight: var(--wb-font-weight-bold);
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

.workbench-context-grid label,
.workbench-requirements label,
.workbench-settings label,
.workbench-upload__actions label {
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
.workbench-upload__actions select,
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
.workbench-upload__actions select:focus,
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

.workbench-upload {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wb-space-4);
  min-width: 0;
  padding: var(--wb-space-3) 0;
  border-top: var(--wb-border-width) solid var(--wb-color-line);
  border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  background: var(--wb-color-surface);
}

.workbench-upload__copy,
.workbench-upload__actions {
  display: flex;
  align-items: center;
  gap: var(--wb-space-3);
  min-width: 0;
}

.workbench-upload__copy > i {
  display: grid;
  place-items: center;
  width: var(--wb-upload-icon-size);
  height: var(--wb-upload-icon-size);
  flex: 0 0 var(--wb-upload-icon-size);
  border-radius: var(--wb-radius-control);
  color: var(--wb-color-primary-dark);
  background: var(--wb-color-canvas);
}

.workbench-upload__copy div {
  display: grid;
  gap: var(--wb-space-1);
  min-width: 0;
}

.workbench-upload__copy strong {
  color: var(--wb-color-ink);
  font-size: var(--wb-font-size-body);
}

.workbench-upload__copy small {
  color: var(--wb-color-muted);
  font-size: var(--wb-font-size-small);
  line-height: var(--wb-line-height-compact);
}

.workbench-upload__actions select {
  min-width: var(--wb-upload-select-min-width);
  padding: var(--wb-space-2);
}

.workbench-upload__actions button {
  display: inline-flex;
  align-items: center;
  gap: var(--wb-space-2);
  white-space: nowrap;
}

.workbench-upload__actions .secondary-button {
  border-color: var(--wb-color-line);
  color: var(--wb-color-secondary);
  background: var(--wb-color-surface);
  box-shadow: none;
  font-size: var(--wb-font-size-control);
  font-weight: var(--wb-font-weight-semibold);
}

.workbench-upload__actions .secondary-button:hover:not(:disabled) {
  border-color: var(--wb-color-muted);
  color: var(--wb-color-ink);
  background: var(--wb-color-canvas);
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
  background: transparent;
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
  font-size: var(--wb-font-size-meta);
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
  padding: var(--wb-space-4);
  border: var(--wb-border-width) solid var(--wb-color-line);
  border-radius: var(--wb-radius-control);
  background: var(--wb-color-surface);
  cursor: pointer;
  transition: border-color var(--wb-transition), background-color var(--wb-transition);
}

.workbench-schemes > label:hover {
  border-color: var(--wb-color-primary);
}

.workbench-schemes > label:focus-within {
  outline: var(--wb-focus-width) solid var(--wb-color-primary);
}

.workbench-schemes > label.is-selected {
  border-color: var(--wb-color-primary);
  background: var(--wb-color-surface);
  box-shadow: none;
}

.workbench-schemes input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.workbench-schemes label > i {
  display: grid;
  place-items: center;
  width: var(--wb-upload-icon-size);
  height: var(--wb-upload-icon-size);
  flex: 0 0 var(--wb-upload-icon-size);
  color: var(--wb-color-primary-dark);
  background: transparent;
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
  background: transparent;
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
  background: transparent;
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
  border-radius: var(--wb-radius-panel);
  background: var(--wb-color-surface);
  box-shadow: var(--wb-shadow-panel);
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
  background: transparent;
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
  font-size: var(--wb-font-size-meta);
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
  font-size: var(--wb-font-size-meta);
  font-weight: var(--wb-font-weight-bold);
  text-decoration: underline;
  text-underline-offset: var(--wb-space-1);
}

.workbench-review > .workbench-inline-error {
  order: 3;
  margin-bottom: var(--wb-space-2);
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
  font-size: var(--wb-font-size-meta);
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
  font-size: var(--wb-font-size-meta);
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
  background: transparent;
  font-size: var(--wb-font-size-meta);
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
  font-size: var(--wb-font-size-meta);
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

@media (max-width: 1700px) {
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
    grid-template-columns: repeat(3, minmax(0, 1fr));
    column-gap: var(--wb-space-5);
  }

  .workbench-checks li:nth-last-child(-n + 3) {
    border-bottom: 0;
  }
}

@container workbench-page (max-width: 1320px) {
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
    grid-template-columns: repeat(3, minmax(0, 1fr));
    column-gap: var(--wb-space-5);
  }

  .workbench-checks li {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-checks li:nth-last-child(-n + 3) {
    border-bottom: 0;
  }
}

@container workbench-page (max-width: 900px) {
  .workbench-checks {
    grid-template-columns: repeat(2, minmax(0, 1fr));
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
  .workbench-checks {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workbench-checks li {
    border-bottom: var(--wb-border-width) solid var(--wb-color-line);
  }

  .workbench-checks li:nth-last-child(-n + 2) {
    border-bottom: 0;
  }
}

@media (max-width: 720px) {
  .workbench-hero,
  .workbench-section-heading,
  .workbench-upload {
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
  .workbench-checks {
    grid-template-columns: minmax(0, 1fr);
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

  .workbench-upload__copy,
  .workbench-upload__actions {
    width: 100%;
  }

  .workbench-upload__actions {
    align-items: stretch;
    flex-direction: column;
  }

  .workbench-upload__actions button {
    justify-content: center;
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workbench-schemes > label {
    transition: none;
  }
}
</style>
