<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const auth = useAuthStore()
const context = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()

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
  },
])
const firstBlockingCheck = computed(() => checks.value.find((item) => !item.ok) || null)
const canSubmit = computed(() => (
  !loading.value
  && !uploading.value
  && !submitting.value
  && !receipt.value
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
}

function replaceJobQuery(jobId) {
  const query = { ...route.query }
  if (jobId) query.job = String(jobId)
  else delete query.job
  router.replace({ name: route.name, query }).catch(() => {})
}

function chooseJob(jobId, { updateRoute = true } = {}) {
  const normalized = jobId === null || jobId === undefined ? '' : String(jobId)
  const job = context.jobs.find((item) => String(item.id) === normalized)
  if (!job) return
  context.selectJob(job.id, { userId: auth.user?.id || context.loadedUserId })
  selectedAccountId.value = job.boss_account ? String(job.boss_account) : ''
  if (updateRoute) replaceJobQuery(job.id)
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
    restoreOperation(selectedJob.value?.id)
  } catch (error) {
    loadError.value = error.message || '招聘作业台加载失败'
  } finally {
    loading.value = false
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

async function uploadDocuments(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  if (!files.length || !selectedJob.value || uploading.value) return
  uploading.value = true
  documentError.value = ''
  uploadProgress.completed = 0
  uploadProgress.total = files.length
  uploadProgress.failed = 0
  const failedFiles = []
  const jobId = selectedJob.value.id
  try {
    for (const file of files) {
      const body = new FormData()
      body.append('job', String(jobId))
      body.append('category', documentCategory.value)
      body.append('title', file.name.replace(/\.(docx?|xlsx)$/i, ''))
      body.append('file', file)
      try {
        await api('recruitment/job-documents/', { method: 'POST', body })
      } catch (error) {
        uploadProgress.failed += 1
        failedFiles.push(`${file.name}：${error.message}`)
      } finally {
        uploadProgress.completed += 1
      }
    }
    await loadDocuments(jobId)
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
    documentLoadSequence += 1
    documents.value = []
    operationState.value = null
    receipt.value = null
    submitError.value = ''
    if (previousJobId && jobId !== previousJobId) {
      coreText.value = ''
      bonusText.value = ''
    }
    if (jobId) {
      loadDocuments(jobId)
      restoreOperation(jobId)
    }
  },
  { immediate: true },
)

watch(schemeKind, () => {
  submitError.value = ''
})

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
      <section class="panel workbench-context" aria-labelledby="workbench-context-title">
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

      <div class="workbench-layout">
        <main class="workbench-main">
          <section class="panel workbench-section" aria-labelledby="workbench-standard-title">
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

          <section class="panel workbench-section" aria-labelledby="workbench-scheme-title">
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
  --workbench-ink: #0f172a;
  --workbench-muted: #64748b;
  --workbench-line: #e2e8f0;
  --workbench-teal: #0f9f8f;
  --workbench-teal-soft: #ecfdf9;
  --workbench-amber: #d97706;
}

.workbench-hero {
  align-items: center;
}

.workbench-runtime {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 11px;
  border: 1px solid #f1d4aa;
  border-radius: 999px;
  color: #9a5a08;
  background: #fffaf2;
  font-size: 12px;
  font-weight: 700;
}

.workbench-runtime i {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #f59e0b;
}

.workbench-runtime.is-ready {
  border-color: #bce8df;
  color: #087f73;
  background: var(--workbench-teal-soft);
}

.workbench-runtime.is-ready i {
  background: var(--workbench-teal);
}

.workbench-error,
.workbench-inline-error {
  margin: 0;
  color: #b42318;
  background: #fff5f4;
  border: 1px solid #ffd4d0;
  border-radius: 9px;
  padding: 10px 12px;
  font-size: 12px;
}

.workbench-loading {
  min-height: 220px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 9px;
  color: var(--workbench-muted);
}

.workbench-loading > span {
  width: min(520px, 78%);
  height: 14px;
  border-radius: 6px;
  background: linear-gradient(90deg, #eef2f5, #f8fafc, #eef2f5);
}

.workbench-loading > span:nth-child(2) { width: min(440px, 68%); }
.workbench-loading > span:nth-child(3) { width: min(360px, 56%); }

.workbench-context,
.workbench-section,
.workbench-review {
  padding: 22px;
}

.workbench-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 18px;
}

.workbench-section-heading div > span {
  display: block;
  color: var(--workbench-teal);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .14em;
}

.workbench-section-heading h3 {
  margin: 3px 0 0;
  color: var(--workbench-ink);
  font-size: 17px;
}

.workbench-section-heading p {
  margin: 3px 0 0;
  max-width: 520px;
  color: var(--workbench-muted);
  font-size: 12px;
  text-align: right;
}

.workbench-context-grid,
.workbench-requirements,
.workbench-settings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.workbench-context-grid label,
.workbench-requirements label,
.workbench-settings label,
.workbench-upload__actions label {
  display: grid;
  gap: 7px;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
}

.workbench-context-grid select,
.workbench-requirements textarea,
.workbench-settings select,
.workbench-settings input,
.workbench-upload__actions select {
  width: 100%;
  border: 1px solid #d7e0e7;
  border-radius: 9px;
  color: var(--workbench-ink);
  background: #fff;
  padding: 10px 11px;
  font: inherit;
  font-weight: 500;
}

.workbench-context-grid select:focus,
.workbench-requirements textarea:focus,
.workbench-settings select:focus,
.workbench-settings input:focus,
.workbench-upload__actions select:focus {
  outline: 2px solid rgba(15, 159, 143, .18);
  border-color: var(--workbench-teal);
}

.workbench-context-grid small,
.workbench-requirements small,
.workbench-settings small {
  color: var(--workbench-muted);
  font-weight: 500;
  line-height: 1.45;
}

.workbench-empty-actions {
  margin-top: 12px;
}

.workbench-empty-actions a,
.workbench-receipt a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #087f73;
  font-size: 12px;
  font-weight: 800;
  text-decoration: none;
}

.workbench-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 348px;
  gap: 18px;
  align-items: start;
}

.workbench-main {
  display: grid;
  gap: 18px;
  min-width: 0;
}

.workbench-upload {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px;
  border: 1px dashed #cbd8df;
  border-radius: 12px;
  background: #f8fbfc;
}

.workbench-upload__copy,
.workbench-upload__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.workbench-upload__copy > i {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  color: #087f73;
  background: #e8f8f4;
}

.workbench-upload__copy div {
  display: grid;
  gap: 3px;
}

.workbench-upload__copy strong {
  color: var(--workbench-ink);
  font-size: 13px;
}

.workbench-upload__copy small {
  color: var(--workbench-muted);
  font-size: 11px;
}

.workbench-upload__actions select {
  min-width: 116px;
  padding: 8px 9px;
}

.workbench-upload__actions button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}

.workbench-documents {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0 18px;
}

.workbench-documents > p {
  margin: 0;
  color: var(--workbench-muted);
  font-size: 11px;
}

.workbench-documents a {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 180px;
  padding: 8px 10px;
  border: 1px solid var(--workbench-line);
  border-radius: 9px;
  color: #334155;
  background: #fff;
  text-decoration: none;
}

.workbench-documents a > span {
  display: grid;
  gap: 2px;
}

.workbench-documents a strong { font-size: 11px; }
.workbench-documents a small { color: var(--workbench-muted); font-size: 9px; }

.workbench-requirements label > span em {
  margin-left: 5px;
  color: var(--workbench-muted);
  font-style: normal;
  font-size: 10px;
  font-weight: 500;
}

.workbench-requirements textarea {
  resize: vertical;
  min-height: 116px;
  line-height: 1.65;
}

.workbench-schemes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  border: 0;
}

.workbench-schemes > label {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 15px;
  border: 1px solid var(--workbench-line);
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease;
}

.workbench-schemes > label:hover {
  border-color: #9dcfc7;
}

.workbench-schemes > label.is-selected {
  border-color: var(--workbench-teal);
  background: #f4fffc;
  box-shadow: 0 0 0 2px rgba(15, 159, 143, .09);
}

.workbench-schemes input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.workbench-schemes label > i {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  color: #087f73;
  background: #e8f8f4;
}

.workbench-schemes label > span {
  display: grid;
  gap: 3px;
}

.workbench-schemes small {
  color: var(--workbench-teal);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .08em;
}

.workbench-schemes strong {
  color: var(--workbench-ink);
  font-size: 13px;
}

.workbench-schemes em {
  color: var(--workbench-muted);
  font-size: 10px;
  font-style: normal;
  line-height: 1.45;
}

.workbench-settings {
  margin-top: 16px;
  padding: 16px;
  border-radius: 12px;
  background: #f8fafc;
}

.workbench-settings--passive {
  grid-template-columns: minmax(240px, 420px);
}

.workbench-workflow-choice {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid var(--workbench-line);
  border-radius: 12px;
  background: #fbfcfd;
}

.workbench-workflow-choice label { display: grid; flex: 1; gap: 6px; color: #334155; font-size: 12px; font-weight: 700; }
.workbench-workflow-choice select { width: 100%; padding: 10px 11px; border: 1px solid #d7e0e7; border-radius: 9px; color: var(--workbench-ink); background: #fff; }
.workbench-workflow-choice small { color: var(--workbench-muted); font-weight: 500; }
.workbench-workflow-choice a { flex: 0 0 auto; padding-bottom: 7px; color: #087f73; font-size: 11px; font-weight: 800; text-decoration: none; }

.workbench-review {
  position: sticky;
  top: 82px;
}

.workbench-review .workbench-section-heading {
  margin-bottom: 12px;
}

.workbench-checks {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.workbench-checks li {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
  padding: 10px 0;
  border-bottom: 1px solid #edf1f4;
}

.workbench-checks li > i {
  color: var(--workbench-amber);
}

.workbench-checks li.is-ready > i {
  color: var(--workbench-teal);
}

.workbench-checks li > span {
  display: grid;
  gap: 3px;
}

.workbench-checks strong {
  color: var(--workbench-ink);
  font-size: 11px;
}

.workbench-checks small {
  color: var(--workbench-muted);
  font-size: 10px;
  line-height: 1.45;
}

.workbench-checks a {
  color: #087f73;
  font-size: 10px;
  font-weight: 800;
  text-decoration: none;
}

.workbench-summary {
  display: grid;
  gap: 4px;
  margin: 15px 0 12px;
  padding: 12px;
  border-radius: 10px;
  background: #f6f8fa;
}

.workbench-summary span,
.workbench-summary small {
  color: var(--workbench-muted);
  font-size: 10px;
}

.workbench-summary strong {
  color: var(--workbench-ink);
  font-size: 13px;
}

.workbench-start {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 42px;
  margin-top: 10px;
}

.workbench-submit-hint {
  display: block;
  margin-top: 8px;
  color: var(--workbench-muted);
  font-size: 10px;
  line-height: 1.45;
  text-align: center;
}

.workbench-receipt {
  display: flex;
  gap: 9px;
  margin-top: 14px;
  padding: 12px;
  border: 1px solid #bce8df;
  border-radius: 11px;
  color: #087f73;
  background: var(--workbench-teal-soft);
}

.workbench-receipt > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.workbench-receipt span,
.workbench-receipt small {
  font-size: 10px;
}

.workbench-receipt strong {
  overflow-wrap: anywhere;
  color: var(--workbench-ink);
  font-size: 11px;
}

.workbench-receipt a {
  margin-top: 4px;
}

.workbench-new-task {
  width: fit-content;
  margin-top: 5px;
  padding: 0;
  border: 0;
  color: #6b7280;
  background: transparent;
  font-size: 10px;
  font-weight: 700;
  text-decoration: underline;
}

.workbench-safety {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 14px 0 0;
  color: var(--workbench-muted);
  font-size: 9px;
  line-height: 1.5;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 1199px) {
  .workbench-layout {
    grid-template-columns: 1fr;
  }

  .workbench-review {
    position: static;
    order: -1;
  }

  .workbench-checks {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    column-gap: 18px;
  }
}

@media (max-width: 767px) {
  .workbench-hero,
  .workbench-section-heading,
  .workbench-upload {
    align-items: flex-start;
    flex-direction: column;
  }

  .workbench-section-heading p {
    text-align: left;
  }

  .workbench-context,
  .workbench-section,
  .workbench-review {
    padding: 16px;
  }

  .workbench-context-grid,
  .workbench-requirements,
  .workbench-settings,
  .workbench-schemes,
  .workbench-checks {
    grid-template-columns: 1fr;
  }

  .workbench-workflow-choice { align-items: stretch; flex-direction: column; }
  .workbench-workflow-choice a { padding-bottom: 0; }

  .workbench-upload__actions {
    width: 100%;
    align-items: stretch;
    flex-direction: column;
  }

  .workbench-upload__actions button {
    justify-content: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  .workbench-schemes > label {
    transition: none;
  }
}
</style>
