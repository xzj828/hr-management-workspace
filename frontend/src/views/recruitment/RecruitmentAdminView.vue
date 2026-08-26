<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'
import ModalPanel from '@/components/ModalPanel.vue'
import ModelProfileDrawer from '@/components/ModelProfileDrawer.vue'
import TaskProgressBar from '@/components/TaskProgressBar.vue'
import WorkflowCanvas from '@/components/WorkflowCanvas.vue'
import {
  accountDisplayStatus,
  actionLabels,
  loginStatusLabel,
  taskStatusLabels,
} from '@/recruitmentAutomation'
import { createRequestId, positionSyncSummary, terminalTaskStatuses } from '@/recruitmentJobs'
import { useAuthStore } from '@/stores/auth'
import { useModelCredentialStore } from '@/stores/modelCredential'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const auth = useAuthStore()
const credentials = useModelCredentialStore()
const recruitmentContext = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()

const tabs = [
  { id: 'accounts', label: 'BOSS 账号与浏览器', shortLabel: '账号与浏览器' },
  { id: 'jobs', label: '职位同步', shortLabel: '职位同步' },
  { id: 'workflows', label: '流程方案', shortLabel: '流程方案' },
  { id: 'models', label: '模型管理', shortLabel: '模型管理' },
  { id: 'diagnostics', label: '系统诊断', shortLabel: '系统诊断' },
]

function normalizeSection(value) {
  const section = String(value || '')
  if (section === 'automation') return 'diagnostics'
  return tabs.some((tab) => tab.id === section) ? section : 'accounts'
}

const activeTab = ref(normalizeSection(route.query.section))
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const notice = ref(null)
const accountsLoadFailed = ref(false)
const accountsLoadedOnce = ref(false)
const summary = reactive({ worker: null, cli_available: false, task_counts: {}, has_active_task: false })
const accounts = ref([])
const jobs = ref([])
const tasks = ref([])
const workflows = ref([])
const workflowVersions = ref([])
const archivedAccounts = ref([])
const archivedJobs = ref([])
const archivedTasks = ref([])
const archivedWorkflows = ref([])
const archivedWorkflowVersions = ref([])
const archiveView = reactive({ accounts: false, jobs: false, workflows: false, diagnostics: false })
const archiveLoading = reactive({ accounts: false, jobs: false, workflows: false, diagnostics: false })
const archiveError = reactive({ accounts: '', jobs: '', workflows: '', diagnostics: '' })
const lifecycleTarget = ref(null)
const lifecycleSaving = ref(false)
const actionBusy = reactive({})
const accountModalOpen = ref(false)
const accountSaving = ref(false)
const accountForm = reactive({ name: '', browser_type: 'edge' })
const selectedAccountId = ref('')
const syncTask = ref(null)
const syncMessage = ref('')
const workflowEditorOpen = ref(false)
const workflowEditorSnapshot = ref(null)
const workflowEditorKey = ref(0)
const workflowSaving = ref(false)
const modelDrawerOpen = ref(false)
const editingModel = ref(null)
const modelActionMessage = ref('')
const selectedTask = ref(null)
const accountFeedback = reactive({})
let syncPollTimer = null
let runtimePollTimer = null
let runtimeRequestSequence = 0
let latestAppliedRuntimeSequence = 0
let runtimePollingStopped = false

const workerOnline = computed(() => summary.worker?.status === 'online')
const modelMutationBusy = computed(() => Boolean(credentials.saving || credentials.switchingId || credentials.testingId || credentials.deletingId))
const accountRuntimeBlocked = computed(() => !workerOnline.value || !summary.cli_available)
const accountRuntimeBlocker = computed(() => {
  if (!workerOnline.value && !summary.cli_available) return '本机自动化服务与 BOSS CLI 未就绪。请运行项目根目录的“启动考勤系统.cmd”，再返回本页。'
  if (!workerOnline.value) return '本机自动化服务未运行，无法打开隔离浏览器。请运行项目根目录的“启动考勤系统.cmd”，再返回本页。'
  return 'BOSS CLI 未就绪，无法打开隔离浏览器。请重新启动完整系统；如果仍未恢复，请到“系统诊断”查看详情。'
})
const activeTaskStatuses = new Set(['pending', 'leased', 'running'])
const activeTasksByAccount = computed(() => Object.fromEntries(
  tasks.value
    .filter((task) => activeTaskStatuses.has(task.status))
    .map((task) => [task.boss_account, task]),
))
const selectedAccount = computed(() => accounts.value.find((account) => String(account.id) === String(selectedAccountId.value)) || null)
const selectedAccountReady = computed(() => selectedAccount.value?.login_status === 'ready')
const selectedAccountSyncReady = computed(() => selectedAccountReady.value && !accountRuntimeBlocked.value)
const selectedAccountJobs = computed(() => jobs.value.filter((job) => String(job.boss_account) === String(selectedAccountId.value)))
const displayedAccounts = computed(() => archiveView.accounts ? archivedAccounts.value : accounts.value)
const displayedJobs = computed(() => archiveView.jobs ? archivedJobs.value : selectedAccountJobs.value)
const currentWorkflowRows = computed(() => workflows.value.flatMap((template) => {
  const versions = workflowVersions.value
    .filter((version) => String(version.template) === String(template.id))
    .sort((left, right) => Number(right.version) - Number(left.version))
  return versions.length
    ? versions.map((version) => ({ template, version }))
    : [{ template, version: null }]
}))
const archivedWorkflowRows = computed(() => archivedWorkflows.value.map((template) => {
  const versions = archivedWorkflowVersions.value.filter((version) => String(version.template) === String(template.id))
  const latest = [...versions].sort((left, right) => Number(right.version) - Number(left.version))[0]
  return { template, version: latest || null }
}))
const displayedTasks = computed(() => archiveView.diagnostics ? archivedTasks.value : tasks.value)
const lifecycleDialog = computed(() => {
  const target = lifecycleTarget.value
  if (!target) return null
  const item = target.item
  if (target.kind === 'account') return {
    title: '归档 BOSS 账号', name: item.name,
    description: '账号将停用并从当前列表移除；隔离浏览器目录和历史任务保留，可在“已归档”中恢复。',
    actionLabel: '确认归档账号', note: '如该账号仍有排队或执行中的任务，系统会阻止归档并保留当前状态。',
  }
  if (target.kind === 'job') return {
    title: '关闭并归档职位', name: item.title,
    description: '职位只会在本工作台转为已关闭并移出当前列表；候选人、简历、流程运行和历史记录继续保留。',
    actionLabel: '确认关闭并归档', note: '该操作不会关闭或删除 BOSS 线上发布的职位。',
  }
  if (target.kind === 'workflow') return {
    title: '归档流程方案', name: workflowName(item),
    description: '流程将停止启用并从作业台选项中移除；所有历史版本、运行和审计记录保留。',
    actionLabel: '确认归档', note: '恢复流程模板后不会自动重新启用旧版本。',
  }
  if (target.kind === 'draft') return {
    title: '永久删除流程草稿', name: `${workflowName(item)} · 版本 ${item.version}`,
    description: '该草稿尚未启用，删除后不可恢复；其他版本不受影响。',
    actionLabel: '永久删除草稿', note: '已有运行记录的草稿会被系统阻止删除。',
  }
  if (target.kind === 'model') return {
    title: '永久删除模型配置', name: item.name,
    description: `将删除该模型的 API 地址和加密保存的 Key，操作不可恢复。${item.is_active ? '删除当前模型后，新建 AI 任务将等待配置，直到你切换或新增模型。' : ''}`,
    actionLabel: '永久删除配置', note: '历史结果及已经绑定模型快照的任务不会删除。',
  }
  return {
    title: '归档自动化任务', name: `${actionLabels[item.action] || item.action} · ${taskStatusLabels[item.status] || item.status}`,
    description: '任务将从最近记录移入已归档；事件、执行证据和审计记录继续保留。',
    actionLabel: '确认归档记录', note: '归档不会重新执行、取消或改变任务结果。',
  }
})
const diagnostics = computed(() => [
  {
    label: '本机 Worker',
    state: workerOnline.value ? 'ok' : 'blocked',
    value: workerOnline.value ? (summary.worker?.hostname || '在线') : '未连接',
    detail: workerOnline.value ? `最近心跳 ${formatDate(summary.worker?.last_seen_at)}` : '启动 RPA Worker 后，排队任务才会被执行。',
  },
  {
    label: 'BOSS CLI',
    state: summary.cli_available ? 'ok' : 'blocked',
    value: summary.cli_available ? (summary.worker?.version || '已就绪') : '未检测到',
    detail: summary.cli_available ? '可执行受控的账号与职位动作。' : '请检查 Worker 的 BOSS CLI 安装与版本。',
  },
  {
    label: '可用账号',
    state: accounts.value.some((account) => account.login_status === 'ready') ? 'ok' : 'attention',
    value: `${accounts.value.filter((account) => account.login_status === 'ready').length} / ${accounts.value.length}`,
    detail: accounts.value.length ? '只有登录成功的账号可以启动招聘业务流程。' : '尚未添加 BOSS 账号。',
  },
  {
    label: '活跃任务',
    state: Object.keys(activeTasksByAccount.value).length ? 'attention' : 'ok',
    value: String(Object.keys(activeTasksByAccount.value).length),
    detail: summary.has_active_task ? '任务执行期间请勿重复提交同一账号动作。' : '当前没有排队或执行中的 RPA 任务。',
  },
])

function assignDefaultAccount() {
  const queryAccountId = route.query.account ? String(route.query.account) : ''
  const queryJobId = route.query.job ? String(route.query.job) : ''
  const jobAccountId = queryJobId
    ? jobs.value.find((job) => String(job.id) === queryJobId)?.boss_account
    : null
  const requestedId = queryAccountId || (jobAccountId ? String(jobAccountId) : '')
  if (requestedId && accounts.value.some((account) => String(account.id) === requestedId)) {
    selectedAccountId.value = requestedId
    return
  }
  if (!accounts.value.some((account) => String(account.id) === String(selectedAccountId.value))) {
    selectedAccountId.value = accounts.value[0] ? String(accounts.value[0].id) : ''
  }
}

async function loadAdmin({ silent = false } = {}) {
  if (!auth.canManage) {
    loading.value = false
    refreshing.value = false
    return
  }
  if (silent) refreshing.value = true
  else loading.value = true
  error.value = ''
  const runtimeSequence = ++runtimeRequestSequence
  const requests = [
    ['summary', api('recruitment/automation/summary/')],
    ['accounts', api('recruitment/boss-accounts/')],
    ['jobs', api('recruitment/jobs/')],
    ['tasks', api('recruitment/rpa-tasks/')],
    ['workflows', api('recruitment/workflows/')],
    ['versions', api('recruitment/workflow-versions/')],
    ['models', credentials.loadProfiles()],
  ]
  const settled = await Promise.allSettled(requests.map(([, request]) => request))
  const failures = []
  const canApplyRuntime = !runtimePollingStopped && runtimeSequence >= latestAppliedRuntimeSequence
  if (canApplyRuntime) latestAppliedRuntimeSequence = runtimeSequence
  settled.forEach((result, index) => {
    const key = requests[index][0]
    if (result.status === 'rejected') {
      failures.push(result.reason?.message || `${key} 加载失败`)
      if (key === 'accounts' && !accountsLoadedOnce.value) accountsLoadFailed.value = true
      return
    }
    if (key === 'summary' && canApplyRuntime) Object.assign(summary, result.value)
    if (key === 'accounts' && canApplyRuntime) {
      applyAccounts(listItems(result.value))
      accountsLoadedOnce.value = true
      accountsLoadFailed.value = false
    }
    if (key === 'jobs') jobs.value = listItems(result.value)
    if (key === 'tasks' && canApplyRuntime) tasks.value = listItems(result.value)
    if (key === 'workflows') workflows.value = listItems(result.value)
    if (key === 'versions') workflowVersions.value = listItems(result.value)
  })
  assignDefaultAccount()
  if (failures.length) error.value = [...new Set(failures)].join('；')
  loading.value = false
  refreshing.value = false
}

function setNotice(type, message) {
  notice.value = { type, message }
}

function accountStatus(account) {
  return accountDisplayStatus(account)
}

function accountStatusLabel(account) {
  return loginStatusLabel(accountStatus(account))
}

function accountPrimaryLabel(account) {
  if (activeTasksByAccount.value[account.id]) return taskStatusLabels[activeTasksByAccount.value[account.id].status] || '任务处理中'
  return ({
    waiting_login: '聚焦登录窗口',
    waiting_human: '打开验证窗口',
    risk_control: '打开验证窗口',
    token_invalid: '重新打开登录窗口',
    ready: '重新打开登录环境',
  })[accountStatus(account)] || '打开登录窗口'
}

function accountGuidance(account) {
  return ({
    browser_stopped: '隔离浏览器尚未打开。打开后请在新窗口中完成 BOSS 登录。',
    unknown: '账号状态尚未确认，打开登录窗口后系统会自动检查。',
    waiting_login: '隔离浏览器已打开，请在窗口中完成 BOSS 扫码登录；系统会自动确认状态。',
    waiting_human: '请在隔离浏览器中完成验证码或人工验证；完成后系统会自动确认状态。',
    risk_control: 'BOSS 要求安全验证，请打开验证窗口并按页面提示人工完成。',
    token_invalid: '登录二维码已失效，请重新打开登录窗口获取新二维码。',
    error: '隔离环境状态检查失败，请重试打开；技术原因可在系统诊断中查看。',
    ready: '账号已就绪，可同步职位并运行已启用方案。',
  })[accountStatus(account)] || '打开隔离浏览器并完成人工登录后，系统会自动确认状态。'
}

function setAccountFeedback(accountId, type, message) {
  accountFeedback[accountId] = { type, message }
}

function applyAccounts(nextAccounts) {
  const previous = new Map(accounts.value.map((account) => [String(account.id), account]))
  accounts.value = nextAccounts
  nextAccounts.forEach((account) => {
    if (!accountFeedback[account.id]) return
    const oldStatus = previous.get(String(account.id))?.login_status
    if (oldStatus === account.login_status) return
    if (account.login_status === 'ready') {
      setAccountFeedback(account.id, 'success', '登录状态已自动确认，账号现在可以使用。')
    } else if (['waiting_login', 'waiting_human'].includes(account.login_status) || account.verification_status) {
      setAccountFeedback(account.id, 'attention', accountGuidance(account))
    }
  })
}

function mergeTask(task, account) {
  const normalized = {
    ...task,
    boss_account: task.boss_account ?? account.id,
    account_name: task.account_name || account.name,
  }
  const index = tasks.value.findIndex((item) => String(item.id) === String(normalized.id))
  if (index >= 0) tasks.value[index] = normalized
  else tasks.value = [normalized, ...tasks.value]
}

async function refreshAccountRuntime() {
  const requestSequence = ++runtimeRequestSequence
  const [accountPayload, taskPayload, summaryPayload] = await Promise.all([
    api('recruitment/boss-accounts/'),
    api('recruitment/rpa-tasks/'),
    api('recruitment/automation/summary/'),
  ])
  if (requestSequence < latestAppliedRuntimeSequence || runtimePollingStopped) return false
  latestAppliedRuntimeSequence = requestSequence
  applyAccounts(listItems(accountPayload))
  accountsLoadedOnce.value = true
  accountsLoadFailed.value = false
  tasks.value = listItems(taskPayload)
  Object.assign(summary, summaryPayload)
  assignDefaultAccount()
  return true
}

function scheduleRuntimePoll() {
  if (runtimePollingStopped) return
  if (runtimePollTimer) window.clearTimeout(runtimePollTimer)
  runtimePollTimer = window.setTimeout(pollAccountRuntime, 5000)
}

async function pollAccountRuntime() {
  if (runtimePollingStopped || !auth.canManage) return
  try {
    await refreshAccountRuntime()
  } catch {
    // Preserve the last successful account state; the next recursive poll retries.
  } finally {
    scheduleRuntimePoll()
  }
}

function stopRuntimePolling() {
  runtimePollingStopped = true
  runtimeRequestSequence += 1
  if (runtimePollTimer) window.clearTimeout(runtimePollTimer)
  runtimePollTimer = null
}

async function createAccount() {
  accountSaving.value = true
  error.value = ''
  try {
    const created = await api('recruitment/boss-accounts/', {
      method: 'POST',
      body: JSON.stringify({
        name: accountForm.name.trim(),
        browser_type: accountForm.browser_type,
        daily_contact_limit: 50,
        active: true,
      }),
    })
    accountModalOpen.value = false
    accountForm.name = ''
    selectedAccountId.value = String(created.id)
    try {
      await refreshAccountRuntime()
      setAccountFeedback(created.id, 'success', '账号已创建。隔离浏览器启动后，请在新窗口完成 BOSS 登录。')
    } catch (refreshError) {
      applyAccounts([...accounts.value.filter((account) => account.id !== created.id), created])
      setAccountFeedback(created.id, 'attention', `账号已创建，但状态刷新暂时失败：${refreshError.message}。系统会自动重试。`)
    }
  } catch (err) {
    error.value = err.message
  } finally {
    accountSaving.value = false
  }
}

async function queueBrowserLogin(account) {
  const busyKey = `${account.id}:login`
  if (accountRuntimeBlocked.value || actionBusy[busyKey] || activeTasksByAccount.value[account.id]) return
  actionBusy[busyKey] = true
  error.value = ''
  try {
    const createdTask = await api('recruitment/rpa-tasks/', {
      method: 'POST',
      body: JSON.stringify({
        boss_account: account.id,
        action: 'check_status',
        request_payload: { open_login: true },
      }),
    })
    mergeTask(createdTask, account)
    setAccountFeedback(account.id, 'success', '正在打开隔离浏览器。窗口出现后请完成人工登录，系统会自动确认状态。')
    try {
      await refreshAccountRuntime()
    } catch (refreshError) {
      setAccountFeedback(account.id, 'attention', `启动任务已提交，但状态刷新暂时失败：${refreshError.message}。系统会自动重试，请勿重复提交。`)
    }
  } catch (err) {
    setAccountFeedback(account.id, 'error', `隔离浏览器打开失败：${err.message}`)
  } finally {
    actionBusy[busyKey] = false
  }
}

async function checkAccountStatus(account) {
  const busyKey = `${account.id}:status`
  if (actionBusy[busyKey]) return
  actionBusy[busyKey] = true
  error.value = ''
  try {
    const updated = await api(`recruitment/boss-accounts/${account.id}/check-status/`, { method: 'POST' })
    const index = accounts.value.findIndex((item) => item.id === account.id)
    if (index >= 0) accounts.value[index] = updated
    if (updated.login_status === 'browser_stopped') {
      setAccountFeedback(account.id, 'attention', '检测到隔离浏览器未启动。请点击“打开登录窗口”。')
    } else if (updated.login_status === 'ready') {
      setAccountFeedback(account.id, 'success', '账号登录状态正常，可以同步职位或运行招聘方案。')
    } else {
      setAccountFeedback(account.id, 'attention', updated.status_detail || accountGuidance(updated))
    }
  } catch (err) {
    setAccountFeedback(account.id, 'error', `状态检查失败：${err.message}`)
  } finally {
    actionBusy[busyKey] = false
  }
}

function goToAccountReadiness() {
  activeTab.value = 'accounts'
  setNotice('attention', selectedAccount.value
    ? `请先为“${selectedAccount.value.name}”启动隔离浏览器并完成登录。`
    : '请先添加 BOSS 账号并完成隔离浏览器登录。')
}

function stopSyncPolling() {
  if (syncPollTimer) window.clearTimeout(syncPollTimer)
  syncPollTimer = null
}

async function loadJobs() {
  jobs.value = listItems(await api('recruitment/jobs/'))
}

async function pollSyncTask(taskId) {
  try {
    const task = await api(`recruitment/rpa-tasks/${taskId}/`)
    syncTask.value = task
    if (task.status === 'succeeded') {
      syncMessage.value = positionSyncSummary(task.result) || '职位同步完成'
      await Promise.all([
        loadJobs(),
        recruitmentContext.loadJobs({ userId: auth.user?.id, force: true }),
      ])
      return
    }
    if (task.status === 'waiting_human') {
      syncMessage.value = '同步已暂停：请在该账号的隔离浏览器中完成验证，然后回到账号页检查状态。'
      return
    }
    if (task.status === 'failed' || task.status === 'cancelled') {
      error.value = task.error_message || (task.status === 'cancelled' ? '同步任务已取消' : '职位同步失败')
      return
    }
    syncPollTimer = window.setTimeout(() => pollSyncTask(taskId), 900)
  } catch (err) {
    error.value = err.message
  }
}

async function syncPositions() {
  if (!selectedAccount.value || !selectedAccountSyncReady.value || (syncTask.value && !terminalTaskStatuses.has(syncTask.value.status))) return
  stopSyncPolling()
  error.value = ''
  syncMessage.value = ''
  syncTask.value = { status: 'pending' }
  try {
    const created = await api('recruitment/jobs/sync/', {
      method: 'POST',
      body: JSON.stringify({
        boss_account: selectedAccount.value.id,
        request_id: createRequestId(),
      }),
    })
    syncTask.value = created
    setNotice('success', workerOnline.value
      ? '职位同步任务已提交，可留在本页查看进度。'
      : '职位同步任务已排队；本机 Worker 连接后会开始执行。')
    await pollSyncTask(created.task_id)
  } catch (err) {
    syncTask.value = { status: 'failed' }
    error.value = err.message
  }
}

function workflowName(version) {
  if (version?.workflow_name) return version.workflow_name
  return workflows.value.find((item) => item.id === version.template)?.name || `流程 ${version.template}`
}

function workflowStatusLabel(status) {
  return { draft: '草稿', enabled: '已启用', disabled: '已停用' }[status] || status
}

function openNewWorkflow() {
  workflowEditorSnapshot.value = null
  workflowEditorKey.value += 1
  workflowEditorOpen.value = true
}

async function editWorkflow(version) {
  workflowEditorSnapshot.value = {
    templateId: version.template,
    name: workflowName(version),
    accountId: version.boss_account,
    nodes: version.nodes,
    edges: version.edges,
  }
  workflowEditorKey.value += 1
  workflowEditorOpen.value = true
  await nextTick()
}

async function reloadWorkflows() {
  const [templatePayload, versionPayload] = await Promise.all([
    api('recruitment/workflows/'),
    api('recruitment/workflow-versions/'),
  ])
  workflows.value = listItems(templatePayload)
  workflowVersions.value = listItems(versionPayload)
}

async function saveWorkflow(snapshot) {
  workflowSaving.value = true
  error.value = ''
  try {
    let templateId = snapshot.templateId
    if (!templateId) {
      const template = await api('recruitment/workflows/', {
        method: 'POST',
        body: JSON.stringify({ name: snapshot.name, description: '由招聘管理后台创建' }),
      })
      templateId = template.id
    }
    await api('recruitment/workflow-versions/', {
      method: 'POST',
      body: JSON.stringify({
        template: templateId,
        boss_account: snapshot.accountId,
        nodes: snapshot.nodes,
        edges: snapshot.edges,
      }),
    })
    await reloadWorkflows()
    workflowEditorSnapshot.value = { ...snapshot, templateId }
    workflowEditorKey.value += 1
    setNotice('success', '流程草稿已保存为新的不可变版本。校验并启用后，业务 HR 才能在作业台使用。')
  } catch (err) {
    error.value = err.message
  } finally {
    workflowSaving.value = false
  }
}

async function enableWorkflow(version) {
  const busyKey = `workflow:${version.id}`
  if (actionBusy[busyKey]) return
  actionBusy[busyKey] = true
  error.value = ''
  try {
    await api(`recruitment/workflow-versions/${version.id}/enable/`, { method: 'POST' })
    await reloadWorkflows()
    setNotice('success', `“${workflowName(version)}”版本 ${version.version} 已校验并启用。`)
  } catch (err) {
    error.value = err.message
  } finally {
    actionBusy[busyKey] = false
  }
}

function openModelDrawer(profile = null) {
  editingModel.value = profile
  modelDrawerOpen.value = true
  modelActionMessage.value = ''
}

async function closeModelDrawer() {
  modelDrawerOpen.value = false
  editingModel.value = null
  try {
    await credentials.loadProfiles()
  } catch (err) {
    error.value = err.message
  }
}

async function modelSaved(profile) {
  modelDrawerOpen.value = false
  editingModel.value = null
  modelActionMessage.value = `已保存并切换到“${profile.name}”。`
}

async function activateModel(profile) {
  if (profile.is_active || credentials.switchingId) return
  modelActionMessage.value = ''
  try {
    const selected = await credentials.activateProfile(profile.id)
    modelActionMessage.value = `已切换到“${selected.name}”。`
  } catch (err) {
    error.value = err.message
  }
}

async function testModel(profile) {
  modelActionMessage.value = ''
  try {
    const result = await credentials.testProfile(profile.id)
    modelActionMessage.value = `“${profile.name}”连接成功${result.latency_ms != null ? `，延迟 ${result.latency_ms} ms` : ''}。`
  } catch (err) {
    error.value = err.message
  }
}

async function loadArchived(section) {
  archiveLoading[section] = true
  archiveError[section] = ''
  try {
    if (section === 'accounts') {
      archivedAccounts.value = listItems(await api('recruitment/boss-accounts/?archived=1'))
    } else if (section === 'jobs') {
      archivedJobs.value = listItems(await api('recruitment/jobs/?archived=1'))
    } else if (section === 'workflows') {
      const [templatePayload, versionPayload] = await Promise.all([
        api('recruitment/workflows/?archived=1'),
        api('recruitment/workflow-versions/?archived=1'),
      ])
      archivedWorkflows.value = listItems(templatePayload)
      archivedWorkflowVersions.value = listItems(versionPayload)
    } else if (section === 'diagnostics') {
      archivedTasks.value = listItems(await api('recruitment/rpa-tasks/?archived=1'))
    }
  } catch (err) {
    archiveError[section] = err.message || '归档记录加载失败'
  } finally {
    archiveLoading[section] = false
  }
}

async function setArchiveView(section, value) {
  archiveView[section] = value
  if (!value) archiveError[section] = ''
  if (value) await loadArchived(section)
}

function requestLifecycle(kind, item) {
  lifecycleTarget.value = { kind, item }
}

async function confirmLifecycle() {
  const target = lifecycleTarget.value
  if (!target || lifecycleSaving.value) return
  lifecycleSaving.value = true
  error.value = ''
  try {
    const { kind, item } = target
    if (kind === 'account') {
      await api(`recruitment/boss-accounts/${item.id}/archive/`, { method: 'POST' })
      accounts.value = accounts.value.filter((entry) => String(entry.id) !== String(item.id))
      setNotice('success', `“${item.name}”已归档；隔离目录和历史任务已保留。`)
    } else if (kind === 'job') {
      await api(`recruitment/jobs/${item.id}/archive/`, { method: 'POST' })
      jobs.value = jobs.value.filter((entry) => String(entry.id) !== String(item.id))
      setNotice('success', `“${item.title}”已在工作台关闭并归档；BOSS 线上职位未更改。`)
    } else if (kind === 'workflow') {
      const name = workflowName(item)
      await api(`recruitment/workflows/${item.template}/archive/`, { method: 'POST' })
      workflows.value = workflows.value.filter((entry) => String(entry.id) !== String(item.template))
      workflowVersions.value = workflowVersions.value.filter((entry) => String(entry.template) !== String(item.template))
      setNotice('success', `“${name}”已归档，历史版本与运行记录已保留。`)
    } else if (kind === 'draft') {
      const name = workflowName(item)
      await api(`recruitment/workflow-versions/${item.id}/`, { method: 'DELETE' })
      workflowVersions.value = workflowVersions.value.filter((entry) => String(entry.id) !== String(item.id))
      setNotice('success', `“${name}”版本 ${item.version} 草稿已永久删除。`)
    } else if (kind === 'model') {
      await credentials.deleteProfile(item.id)
      modelActionMessage.value = `“${item.name}”已永久删除，加密保存的 API Key 已擦除。`
    } else {
      await api(`recruitment/rpa-tasks/${item.id}/archive/`, { method: 'POST' })
      tasks.value = tasks.value.filter((entry) => String(entry.id) !== String(item.id))
      if (String(selectedTask.value?.id) === String(item.id)) selectedTask.value = null
      setNotice('success', '自动化任务已归档，事件和执行证据已保留。')
    }
    lifecycleTarget.value = null
    assignDefaultAccount()
  } catch (err) {
    error.value = err.message
  } finally {
    lifecycleSaving.value = false
  }
}

async function restoreLifecycle(kind, item) {
  const busyKey = `restore:${kind}:${item.id}`
  if (actionBusy[busyKey]) return
  actionBusy[busyKey] = true
  error.value = ''
  try {
    if (kind === 'account') {
      const restored = await api(`recruitment/boss-accounts/${item.id}/restore/?archived=1`, { method: 'POST' })
      archivedAccounts.value = archivedAccounts.value.filter((entry) => String(entry.id) !== String(item.id))
      accounts.value = [...accounts.value, restored]
      setNotice('success', `“${item.name}”已恢复；需要重新检查登录状态后才能执行自动化。`)
    } else if (kind === 'job') {
      const restored = await api(`recruitment/jobs/${item.id}/restore/?archived=1`, { method: 'POST' })
      archivedJobs.value = archivedJobs.value.filter((entry) => String(entry.id) !== String(item.id))
      jobs.value = [restored, ...jobs.value]
      setNotice('success', `“${item.title}”已恢复到工作台，状态仍为已关闭。`)
    } else if (kind === 'workflow') {
      const restored = await api(`recruitment/workflows/${item.id}/restore/?archived=1`, { method: 'POST' })
      archivedWorkflows.value = archivedWorkflows.value.filter((entry) => String(entry.id) !== String(item.id))
      archivedWorkflowVersions.value = archivedWorkflowVersions.value.filter((entry) => String(entry.template) !== String(item.id))
      workflows.value = [...workflows.value.filter((entry) => String(entry.id) !== String(item.id)), restored]
      setNotice('success', `“${item.name}”已恢复；如需使用，请重新选择版本并启用。`)
      try {
        await reloadWorkflows()
      } catch (refreshError) {
        setNotice('attention', `“${item.name}”已恢复，但列表刷新暂时失败：${refreshError.message}。请勿重复操作。`)
      }
    } else {
      const restored = await api(`recruitment/rpa-tasks/${item.id}/restore/?archived=1`, { method: 'POST' })
      archivedTasks.value = archivedTasks.value.filter((entry) => String(entry.id) !== String(item.id))
      tasks.value = [restored, ...tasks.value]
      setNotice('success', '自动化任务记录已恢复；任务不会重新执行。')
    }
    assignDefaultAccount()
  } catch (err) {
    error.value = err.message
  } finally {
    actionBusy[busyKey] = false
  }
}

function formatDate(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

watch(
  () => route.query.section,
  (section) => {
    const normalized = normalizeSection(section)
    if (normalized !== activeTab.value) activeTab.value = normalized
  },
)

watch(
  () => [route.query.account, route.query.job],
  () => assignDefaultAccount(),
)

watch(activeTab, (section) => {
  if (String(route.query.section || '') === section) return
  router.replace({ name: route.name, query: { ...route.query, section } }).catch(() => {})
})

onMounted(async () => {
  await loadAdmin()
  scheduleRuntimePoll()
})
onUnmounted(() => {
  stopSyncPolling()
  stopRuntimePolling()
})
</script>

<template>
  <div class="page-stack recruitment-admin">
    <header class="admin-hero">
      <div>
        <span class="eyebrow">Recruitment Administration</span>
        <div class="admin-hero__title-row">
          <h2>管理后台</h2>
          <button v-if="auth.canManage" class="admin-button admin-button--quiet" type="button" :disabled="refreshing" @click="loadAdmin({ silent: true })">
            <AppIcon name="refresh" :size="16" />{{ refreshing ? '刷新中…' : '刷新状态' }}
          </button>
        </div>
        <p>低频设置与技术状态集中在这里；业务 HR 的准备和执行留在招聘作业台。</p>
      </div>
    </header>

    <nav v-if="auth.canManage" class="admin-tabs" aria-label="管理后台子导航">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        :class="{ active: activeTab === tab.id }"
        :aria-current="activeTab === tab.id ? 'page' : undefined"
        :data-test="`admin-tab-${tab.id}`"
        @click="activeTab = tab.id"
      >
        <span>{{ tab.shortLabel }}</span>
      </button>
    </nav>

    <section v-if="!auth.canManage" class="admin-permission" data-test="admin-permission" role="status">
      <AppIcon name="shield" :size="24" />
      <div><strong>当前角色没有管理权限</strong><p>管理后台仅向 HR 与管理员开放。你仍可在招聘作业台和结果中心查看已授权业务数据。</p></div>
    </section>

    <div v-if="auth.canManage && notice" :class="['admin-notice', `is-${notice.type}`]" role="status">
      <AppIcon :name="notice.type === 'success' ? 'check-circle' : 'alert-circle'" :size="18" />
      <span>{{ notice.message }}</span>
      <button type="button" aria-label="关闭提示" @click="notice = null">×</button>
    </div>
    <div v-if="auth.canManage && error" class="admin-error" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="loadAdmin()">重试</button>
    </div>

    <section v-if="auth.canManage && loading" class="admin-loading" aria-label="正在加载管理后台">
      <i v-for="index in 4" :key="index"></i>
    </section>

    <template v-else-if="auth.canManage">
      <section v-if="activeTab === 'accounts'" class="admin-section">
        <header class="admin-section__header">
          <div>
            <span class="admin-kicker">ISOLATED BROWSERS</span>
            <h3>BOSS 账号与隔离浏览器</h3>
            <p>每个账号使用独立浏览器目录。浏览器未启动时，先提交启动任务，再在新窗口完成登录。</p>
          </div>
          <div class="admin-header-actions">
            <div class="admin-segmented" aria-label="账号记录范围">
              <button type="button" :class="{ active: !archiveView.accounts }" :aria-pressed="!archiveView.accounts" @click="setArchiveView('accounts', false)">当前</button>
              <button type="button" :class="{ active: archiveView.accounts }" :aria-pressed="archiveView.accounts" data-test="archived-accounts" @click="setArchiveView('accounts', true)">已归档</button>
            </div>
            <button v-if="!archiveView.accounts" class="admin-button admin-button--primary" data-test="add-boss-account" type="button" @click="accountModalOpen = true">
              <AppIcon name="plus" :size="16" />添加账号
            </button>
          </div>
        </header>

        <div v-if="accountRuntimeBlocked && !archiveView.accounts" class="account-runtime-blocker" data-test="account-runtime-blocker" role="alert">
          <AppIcon name="alert-circle" :size="19" />
          <div><strong>隔离浏览器暂不可用</strong><p>{{ accountRuntimeBlocker }}</p></div>
          <button class="admin-button admin-button--quiet" type="button" @click="activeTab = 'diagnostics'">查看系统诊断</button>
        </div>

        <div v-if="accountsLoadFailed && !archiveView.accounts" class="admin-empty" data-test="accounts-load-error">
          <AppIcon name="alert-circle" :size="24" />
          <strong>账号列表加载失败</strong>
          <p>暂时无法确认已有账号，请重试；系统不会把加载失败误认为“尚未添加账号”。</p>
          <button class="admin-button admin-button--quiet" type="button" @click="loadAdmin()">重新加载</button>
        </div>
        <div v-else-if="archiveView.accounts && archiveLoading.accounts" class="admin-empty"><strong>正在读取归档账号…</strong></div>
        <div v-else-if="archiveView.accounts && archiveError.accounts" class="admin-empty" role="alert"><strong>归档账号加载失败</strong><p>{{ archiveError.accounts }}</p><button class="admin-button admin-button--quiet" type="button" @click="loadArchived('accounts')">重新加载归档账号</button></div>
        <div v-else-if="displayedAccounts.length" class="account-grid">
          <article v-for="account in displayedAccounts" :key="account.id" class="account-card">
            <header>
              <strong>{{ account.name }}</strong>
              <span :class="['account-status', archiveView.accounts ? 'is-offline' : `is-${accountStatus(account)}`]">{{ archiveView.accounts ? '已归档' : accountStatusLabel(account) }}</span>
            </header>
            <div class="account-last-check"><span>最近检查</span><strong>{{ formatDate(account.last_checked_at) }}</strong></div>
            <p :class="accountStatus(account) === 'ready' ? 'account-ready' : 'account-blocker'">{{ archiveView.accounts ? '账号已停用；隔离目录和历史任务仍保留。' : accountGuidance(account) }}</p>
            <p
              v-if="accountFeedback[account.id]"
              :class="['account-feedback', `is-${accountFeedback[account.id].type}`]"
              :data-test="`account-feedback-${account.id}`"
              aria-live="polite"
            >{{ accountFeedback[account.id].message }}</p>
            <footer v-if="archiveView.accounts">
              <button class="admin-button admin-button--quiet" type="button" :data-test="`restore-account-${account.id}`" :disabled="actionBusy[`restore:account:${account.id}`]" @click="restoreLifecycle('account', account)">{{ actionBusy[`restore:account:${account.id}`] ? '恢复中…' : '恢复账号' }}</button>
            </footer>
            <footer v-else>
              <button
                class="admin-button admin-button--primary"
                type="button"
                :disabled="accountRuntimeBlocked || Boolean(activeTasksByAccount[account.id]) || actionBusy[`${account.id}:login`]"
                :title="accountRuntimeBlocked ? accountRuntimeBlocker : undefined"
                :data-test="`start-browser-${account.id}`"
                @click="queueBrowserLogin(account)"
              >{{ accountPrimaryLabel(account) }}</button>
              <button
                class="admin-button admin-button--quiet"
                type="button"
                :disabled="actionBusy[`${account.id}:status`]"
                :data-test="`check-account-${account.id}`"
                @click="checkAccountStatus(account)"
              >{{ actionBusy[`${account.id}:status`] ? '检查中…' : '检查状态' }}</button>
              <button class="admin-link admin-link--danger" type="button" :aria-label="`归档账号 ${account.name}`" @click="requestLifecycle('account', account)">归档</button>
            </footer>
            <details class="account-technical">
              <summary>技术详情</summary>
              <dl>
                <div><dt>浏览器</dt><dd>{{ account.browser_type === 'edge' ? 'Microsoft Edge' : 'Google Chrome' }}</dd></div>
                <div><dt>CDP 端口</dt><dd>{{ account.cdp_port }}</dd></div>
                <div class="account-technical__path"><dt>隔离目录</dt><dd>{{ account.browser_profile }}</dd></div>
              </dl>
            </details>
          </article>
        </div>
        <div v-else class="admin-empty">
          <AppIcon name="user" :size="24" />
          <strong>{{ archiveView.accounts ? '暂无已归档账号' : '尚未添加 BOSS 账号' }}</strong>
          <p>{{ archiveView.accounts ? '归档账号会出现在这里，并可恢复到当前列表。' : '添加后系统会分配隔离浏览器目录和端口，并创建一次可追踪的启动任务。' }}</p>
          <button v-if="archiveView.accounts" class="admin-button admin-button--quiet" type="button" @click="setArchiveView('accounts', false)">返回当前账号</button>
          <button v-else class="admin-button admin-button--primary" data-test="add-boss-account" type="button" @click="accountModalOpen = true">添加第一个账号</button>
        </div>
      </section>

      <section v-else-if="activeTab === 'jobs'" class="admin-section">
        <header class="admin-section__header">
          <div>
            <span class="admin-kicker">POSITION SYNC</span>
            <h3>从 BOSS 同步职位</h3>
            <p>这里只负责把已发布职位同步到系统，不在此处创建、编辑或关闭 BOSS 线上职位。</p>
          </div>
          <div class="admin-segmented" aria-label="职位记录范围">
            <button type="button" :class="{ active: !archiveView.jobs }" :aria-pressed="!archiveView.jobs" @click="setArchiveView('jobs', false)">当前</button>
            <button type="button" :class="{ active: archiveView.jobs }" :aria-pressed="archiveView.jobs" data-test="archived-jobs" @click="setArchiveView('jobs', true)">已归档</button>
          </div>
        </header>

        <div v-if="accounts.length && !archiveView.jobs" class="sync-console">
          <label>
            <span>同步账号</span>
            <select v-model="selectedAccountId" data-test="admin-sync-account">
              <option v-for="account in accounts" :key="account.id" :value="String(account.id)">
                {{ account.name }} · {{ accountStatusLabel(account) }}
              </option>
            </select>
          </label>
          <div class="sync-readiness">
            <span :class="selectedAccountSyncReady ? 'is-ready' : 'is-blocked'"></span>
            <div>
              <strong>{{ selectedAccountSyncReady ? '账号可同步' : '同步条件未满足' }}</strong>
              <small>{{ selectedAccountSyncReady ? '将创建一个有审计记录的职位同步任务。' : (accountRuntimeBlocked ? accountRuntimeBlocker : '需要先启动隔离浏览器并完成登录。') }}</small>
            </div>
          </div>
          <button
            v-if="selectedAccountReady"
            class="admin-button admin-button--primary"
            data-test="admin-sync-positions"
            type="button"
            :disabled="accountRuntimeBlocked || (syncTask && !terminalTaskStatuses.has(syncTask.status))"
            @click="syncPositions"
          >{{ syncTask && !terminalTaskStatuses.has(syncTask.status) ? '同步中…' : '一键同步职位' }}</button>
          <button v-else class="admin-button admin-button--quiet" type="button" @click="goToAccountReadiness">去启动并登录</button>
        </div>
        <div v-else-if="!archiveView.jobs" class="admin-empty">
          <AppIcon name="workflow" :size="24" />
          <strong>没有可用于同步的账号</strong>
          <p>先添加 BOSS 账号并在隔离浏览器中完成登录。</p>
          <button class="admin-button admin-button--primary" type="button" @click="activeTab = 'accounts'; accountModalOpen = true">添加账号</button>
        </div>

        <div v-if="syncTask && !archiveView.jobs" class="sync-progress" aria-live="polite">
          <TaskProgressBar :status="syncTask.status" />
          <p v-if="syncMessage">{{ syncMessage }}</p>
        </div>

        <div v-if="archiveView.jobs && archiveLoading.jobs" class="admin-empty"><strong>正在读取归档职位…</strong></div>
        <div v-else-if="archiveView.jobs && archiveError.jobs" class="admin-empty" role="alert"><strong>归档职位加载失败</strong><p>{{ archiveError.jobs }}</p><button class="admin-button admin-button--quiet" type="button" @click="loadArchived('jobs')">重新加载归档职位</button></div>
        <div v-else-if="accounts.length || archiveView.jobs" class="admin-table-shell">
          <header>
            <div><strong>{{ archiveView.jobs ? '已归档职位' : '已同步职位' }}</strong><small>{{ archiveView.jobs ? '仅影响工作台记录' : (selectedAccount?.name || '当前账号') }}</small></div>
            <span>{{ displayedJobs.length }} 个</span>
          </header>
          <div v-if="displayedJobs.length" class="admin-table-scroll">
            <table>
              <thead><tr><th>职位</th><th>部门</th><th>招聘人数</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="job in displayedJobs" :key="job.id">
                  <td><strong>{{ job.title }}</strong></td>
                  <td>{{ job.department || '—' }}</td>
                  <td>{{ job.headcount || '—' }}</td>
                  <td><span class="table-status">{{ { open: '招聘中', paused: '已暂停', closed: '已关闭' }[job.status] || job.status }}</span></td>
                  <td>{{ formatDate(job.updated_at) }}</td>
                  <td>
                    <button v-if="archiveView.jobs" class="admin-link" type="button" :disabled="actionBusy[`restore:job:${job.id}`]" @click="restoreLifecycle('job', job)">{{ actionBusy[`restore:job:${job.id}`] ? '恢复中…' : '恢复' }}</button>
                    <button v-else class="admin-link admin-link--danger" type="button" :aria-label="`关闭并归档职位 ${job.title}`" @click="requestLifecycle('job', job)">关闭并归档</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="admin-empty admin-empty--compact">
            <strong>{{ archiveView.jobs ? '暂无已归档职位' : '当前账号还没有同步职位' }}</strong>
            <p>{{ archiveView.jobs ? '关闭并归档的工作台职位会出现在这里。' : (selectedAccountReady ? '点击“一键同步职位”从 BOSS 获取已发布职位。' : '账号登录成功后才能同步职位。') }}</p>
            <button v-if="archiveView.jobs" class="admin-button admin-button--quiet" type="button" @click="setArchiveView('jobs', false)">返回当前职位</button>
          </div>
        </div>
      </section>

      <section v-else-if="activeTab === 'workflows'" class="admin-section">
        <header class="admin-section__header">
          <div>
            <span class="admin-kicker">WORKFLOW GOVERNANCE</span>
            <h3>流程方案</h3>
            <p>业务 HR 在作业台选择已启用方案；只有需要改变节点与安全门时才进入高级编排。</p>
          </div>
          <div class="admin-header-actions">
            <div class="admin-segmented" aria-label="流程记录范围">
              <button type="button" :class="{ active: !archiveView.workflows }" :aria-pressed="!archiveView.workflows" @click="setArchiveView('workflows', false)">当前</button>
              <button type="button" :class="{ active: archiveView.workflows }" :aria-pressed="archiveView.workflows" data-test="archived-workflows" @click="setArchiveView('workflows', true)">已归档</button>
            </div>
            <button v-if="!archiveView.workflows" class="admin-button admin-button--primary" type="button" @click="openNewWorkflow">新建高级流程</button>
          </div>
        </header>

        <div v-if="archiveView.workflows && archiveLoading.workflows" class="admin-empty"><strong>正在读取归档流程…</strong></div>
        <div v-else-if="archiveView.workflows && archiveError.workflows" class="admin-empty" role="alert"><strong>归档流程加载失败</strong><p>{{ archiveError.workflows }}</p><button class="admin-button admin-button--quiet" type="button" @click="loadArchived('workflows')">重新加载归档流程</button></div>
        <div v-else-if="archiveView.workflows && archivedWorkflowRows.length" class="workflow-list">
          <article v-for="row in archivedWorkflowRows" :key="row.template.id">
            <div class="workflow-list__identity">
              <i><AppIcon name="workflow" :size="18" /></i>
              <div><strong>{{ row.template.name }}</strong><span>{{ row.version ? `最近版本 ${row.version.version}` : '暂无版本' }} · 已归档</span></div>
            </div>
            <span class="workflow-status is-disabled">已归档</span>
            <div class="workflow-list__actions">
              <button class="admin-button admin-button--quiet" type="button" :disabled="actionBusy[`restore:workflow:${row.template.id}`]" @click="restoreLifecycle('workflow', row.template)">{{ actionBusy[`restore:workflow:${row.template.id}`] ? '恢复中…' : '恢复流程' }}</button>
            </div>
          </article>
        </div>
        <div v-else-if="!archiveView.workflows && currentWorkflowRows.length" class="workflow-list">
          <article v-for="row in currentWorkflowRows" :key="`${row.template.id}:${row.version?.id || 'empty'}`">
            <div class="workflow-list__identity">
              <i><AppIcon name="workflow" :size="18" /></i>
              <div><strong>{{ row.template.name }}</strong><span>{{ row.version ? `版本 ${row.version.version} · ${row.version.nodes?.length || 0} 个节点` : '尚无可用版本' }}</span></div>
            </div>
            <span :class="['workflow-status', `is-${row.version?.status || 'disabled'}`]">{{ row.version ? workflowStatusLabel(row.version.status) : '待配置' }}</span>
            <div class="workflow-list__actions">
              <button v-if="row.version" class="admin-button admin-button--quiet" type="button" :data-test="`edit-admin-workflow-${row.version.id}`" @click="editWorkflow(row.version)">基于此版本编排</button>
              <button v-if="row.version?.status === 'draft'" class="admin-button admin-button--primary" type="button" :disabled="actionBusy[`workflow:${row.version.id}`]" @click="enableWorkflow(row.version)">{{ actionBusy[`workflow:${row.version.id}`] ? '校验中…' : '校验并启用' }}</button>
              <button v-if="row.version?.status === 'draft'" class="admin-link admin-link--danger" type="button" @click="requestLifecycle('draft', row.version)">删除草稿</button>
              <button class="admin-link admin-link--danger" type="button" @click="requestLifecycle('workflow', row.version || { template: row.template.id, workflow_name: row.template.name })">归档方案</button>
            </div>
          </article>
        </div>
        <div v-else class="admin-empty">
          <AppIcon name="workflow" :size="24" />
          <strong>{{ archiveView.workflows ? '暂无已归档流程' : '尚未定义流程方案' }}</strong>
          <p>{{ archiveView.workflows ? '归档流程会出现在这里，并可恢复到当前列表。' : '可以先在招聘作业台使用标准方案；需要自定义节点时再创建高级流程。' }}</p>
          <button v-if="archiveView.workflows" class="admin-button admin-button--quiet" type="button" @click="setArchiveView('workflows', false)">返回当前流程</button>
          <button v-else class="admin-button admin-button--primary" type="button" @click="openNewWorkflow">打开高级编排</button>
        </div>

        <div v-if="workflowEditorOpen && !archiveView.workflows" class="workflow-editor-shell">
          <header>
            <div><strong>高级流程编排</strong><small>保存会生成新的不可变草稿版本，不会覆盖历史版本。</small></div>
            <button class="admin-button admin-button--quiet" type="button" @click="workflowEditorOpen = false">收起画布</button>
          </header>
          <WorkflowCanvas
            :key="workflowEditorKey"
            :accounts="accounts"
            :saving="workflowSaving"
            :snapshot="workflowEditorSnapshot"
            @save="saveWorkflow"
          />
        </div>
      </section>

      <section v-else-if="activeTab === 'models'" class="admin-section">
        <header class="admin-section__header">
          <div>
            <span class="admin-kicker">MODEL CONNECTION</span>
            <h3>模型管理</h3>
            <p>管理当前登录账号的个人模型连接；切换只影响之后创建的 AI 任务。</p>
          </div>
          <button class="admin-button admin-button--primary" data-test="open-model-config" type="button" :disabled="modelMutationBusy" @click="openModelDrawer()"><AppIcon name="plus" :size="16" />新增自定义模型</button>
        </header>
        <p v-if="modelActionMessage" class="model-action-message" aria-live="polite">{{ modelActionMessage }}</p>
        <div v-if="credentials.loading" class="model-list-loading" aria-live="polite"><i></i><i></i><i></i></div>
        <div v-else-if="credentials.profiles.length" class="model-profile-list">
          <article v-for="profile in credentials.profiles" :key="profile.id" :class="{ 'is-active': profile.is_active }">
            <div class="model-card__icon"><AppIcon :name="profile.is_active ? 'check-circle' : 'sparkles'" :size="22" /></div>
            <div class="model-card__body">
              <span>{{ profile.is_active ? '当前使用' : '已保存模型' }}</span>
              <strong>{{ profile.name }}</strong>
              <p>{{ profile.model }} · {{ profile.api_url }}</p>
              <small>{{ profile.has_api_key ? `API Key 已加密保存 ····${profile.key_last4}` : '尚未保存 API Key' }}</small>
            </div>
            <div class="model-card__actions">
              <button v-if="!profile.is_active" class="admin-button admin-button--primary" type="button" :disabled="modelMutationBusy" @click="activateModel(profile)">{{ String(credentials.switchingId) === String(profile.id) ? '切换中…' : '切换到此模型' }}</button>
              <span v-else class="model-active-chip">当前使用</span>
              <button class="admin-button admin-button--quiet" type="button" :disabled="modelMutationBusy" @click="testModel(profile)">{{ String(credentials.testingId) === String(profile.id) ? '连接中…' : '测试连接' }}</button>
              <button class="admin-link" type="button" :disabled="modelMutationBusy" @click="openModelDrawer(profile)">编辑</button>
              <button class="admin-link admin-link--danger" type="button" :disabled="modelMutationBusy" :aria-label="`永久删除模型 ${profile.name}`" @click="requestLifecycle('model', profile)">{{ String(credentials.deletingId) === String(profile.id) ? '删除中…' : '删除' }}</button>
            </div>
          </article>
        </div>
        <div v-else class="admin-empty">
          <AppIcon name="sparkles" :size="24" />
          <strong>尚未配置模型</strong>
          <p>添加一个 OpenAI 兼容模型后，就能在顶栏快速切换。</p>
          <button class="admin-button admin-button--primary" type="button" @click="openModelDrawer()">新增自定义模型</button>
        </div>
        <div class="model-boundary">
          <strong>数据边界</strong>
          <p>模型档案属于当前登录账号。岗位与简历原文件留在本机；模型仅接收本地提取后的文字块，密钥不会写入前端存储。</p>
        </div>
      </section>

      <section v-else class="admin-section">
        <header class="admin-section__header">
          <div>
            <span class="admin-kicker">SYSTEM HEALTH</span>
            <h3>系统诊断</h3>
            <p>先看阻塞项，再下钻最近任务日志；业务页面不再展示 Worker、端口和技术事件。</p>
          </div>
          <div class="admin-segmented" aria-label="任务记录范围">
            <button type="button" :class="{ active: !archiveView.diagnostics }" :aria-pressed="!archiveView.diagnostics" @click="setArchiveView('diagnostics', false)">最近任务</button>
            <button type="button" :class="{ active: archiveView.diagnostics }" :aria-pressed="archiveView.diagnostics" data-test="archived-tasks" @click="setArchiveView('diagnostics', true)">已归档</button>
          </div>
        </header>
        <div v-if="!archiveView.diagnostics" class="diagnostic-grid">
          <article v-for="item in diagnostics" :key="item.label" :class="`is-${item.state}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <p>{{ item.detail }}</p>
          </article>
        </div>

        <div class="admin-table-shell">
          <header>
            <div><strong>{{ archiveView.diagnostics ? '已归档自动化任务' : '最近自动化任务' }}</strong><small>状态、错误和事件均来自服务端审计记录</small></div>
            <span>{{ displayedTasks.length }} 条</span>
          </header>
          <div v-if="archiveView.diagnostics && archiveLoading.diagnostics" class="admin-empty admin-empty--compact"><strong>正在读取归档任务…</strong></div>
          <div v-else-if="archiveView.diagnostics && archiveError.diagnostics" class="admin-empty admin-empty--compact" role="alert"><strong>归档任务加载失败</strong><p>{{ archiveError.diagnostics }}</p><button class="admin-button admin-button--quiet" type="button" @click="loadArchived('diagnostics')">重新加载归档任务</button></div>
          <div v-else-if="displayedTasks.length" class="admin-table-scroll">
            <table>
              <thead><tr><th>账号</th><th>动作</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
              <tbody>
                <tr v-for="task in displayedTasks" :key="task.id">
                  <td><strong>{{ task.account_name }}</strong></td>
                  <td>{{ actionLabels[task.action] || task.action }}</td>
                  <td><span :class="['table-status', `is-${task.status}`]">{{ taskStatusLabels[task.status] || task.status }}</span></td>
                  <td>{{ formatDate(task.created_at) }}</td>
                  <td>
                    <button class="admin-link" type="button" @click="selectedTask = task">查看记录</button>
                    <button v-if="archiveView.diagnostics" class="admin-link" type="button" :disabled="actionBusy[`restore:task:${task.id}`]" @click="restoreLifecycle('task', task)">{{ actionBusy[`restore:task:${task.id}`] ? '恢复中…' : '恢复' }}</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="admin-empty admin-empty--compact"><strong>{{ archiveView.diagnostics ? '暂无已归档任务' : '暂无自动化任务' }}</strong><p>{{ archiveView.diagnostics ? '归档后的任务记录会出现在这里。' : '账号启动、职位同步和流程执行后会在这里留下记录。' }}</p><button v-if="archiveView.diagnostics" class="admin-button admin-button--quiet" type="button" @click="setArchiveView('diagnostics', false)">返回最近任务</button></div>
        </div>
      </section>
    </template>

    <ModalPanel v-if="auth.canManage && accountModalOpen" title="添加 BOSS 账号" @close="accountModalOpen = false">
      <form id="admin-account-form" class="admin-form" @submit.prevent="createAccount">
        <label>账号名称<input v-model.trim="accountForm.name" required maxlength="100" placeholder="例如：北京招聘主账号" /></label>
        <label>隔离浏览器<select v-model="accountForm.browser_type"><option value="edge">Microsoft Edge</option><option value="chrome">Google Chrome</option></select></label>
        <p>系统会自动分配独立目录和调试端口，不会使用你的日常浏览器资料。</p>
      </form>
      <template #footer>
        <button class="secondary-button" type="button" @click="accountModalOpen = false">取消</button>
        <button class="primary-button" type="submit" form="admin-account-form" :disabled="accountSaving">{{ accountSaving ? '保存中…' : '保存账号' }}</button>
      </template>
    </ModalPanel>

    <ModalPanel v-if="auth.canManage && selectedTask" title="自动化任务记录" @close="selectedTask = null">
      <dl class="task-detail">
        <div><dt>账号</dt><dd>{{ selectedTask.account_name }}</dd></div>
        <div><dt>动作</dt><dd>{{ actionLabels[selectedTask.action] || selectedTask.action }}</dd></div>
        <div><dt>状态</dt><dd>{{ taskStatusLabels[selectedTask.status] || selectedTask.status }}</dd></div>
        <div><dt>错误</dt><dd>{{ selectedTask.error_message || '—' }}</dd></div>
      </dl>
      <ol v-if="selectedTask.events?.length" class="task-events">
        <li v-for="event in selectedTask.events" :key="event.id"><time>{{ formatDate(event.created_at) }}</time><span>{{ event.message }}</span></li>
      </ol>
      <p v-else class="admin-empty admin-empty--compact">暂无更多事件</p>
      <template v-if="!archiveView.diagnostics && !activeTaskStatuses.has(selectedTask.status)" #footer>
        <button class="secondary-button" type="button" @click="selectedTask = null">关闭</button>
        <button class="danger-button" type="button" @click="requestLifecycle('task', selectedTask)">归档任务记录</button>
      </template>
    </ModalPanel>

    <ModelProfileDrawer v-if="auth.canManage && modelDrawerOpen" :profile="editingModel" @close="closeModelDrawer" @saved="modelSaved" />
    <ArchiveConfirmModal
      v-if="auth.canManage && lifecycleDialog"
      :title="lifecycleDialog.title"
      :name="lifecycleDialog.name"
      :description="lifecycleDialog.description"
      :action-label="lifecycleDialog.actionLabel"
      :note="lifecycleDialog.note"
      :saving="lifecycleSaving"
      @close="lifecycleTarget = null"
      @confirm="confirmLifecycle"
    />
  </div>
</template>

<style scoped>
.recruitment-admin {
  --admin-ink: var(--ink, #0f172a);
  --admin-slate: var(--slate, #334155);
  --admin-muted: var(--muted, #64748b);
  --admin-line: var(--line, #e2e8f0);
  --admin-surface: var(--paper, #ffffff);
  --admin-canvas: var(--canvas, #f3f6f8);
  --admin-soft: color-mix(in srgb, var(--admin-canvas) 72%, var(--admin-surface));
  --admin-brand: var(--teal, #0f9f8f);
  --admin-brand-dark: var(--teal-dark, #087f73);
  --admin-warning: #d97706;
  --admin-danger: #dc4a4a;
  --admin-success-soft: color-mix(in srgb, var(--admin-brand) 8%, var(--admin-surface));
  --admin-warning-soft: color-mix(in srgb, var(--admin-warning) 8%, var(--admin-surface));
  --admin-danger-soft: color-mix(in srgb, var(--admin-danger) 8%, var(--admin-surface));
  --admin-info-soft: color-mix(in srgb, var(--admin-slate) 7%, var(--admin-surface));
  --admin-success-line: color-mix(in srgb, var(--admin-brand) 24%, transparent);
  --admin-warning-line: color-mix(in srgb, var(--admin-warning) 24%, transparent);
  --admin-danger-line: color-mix(in srgb, var(--admin-danger) 24%, transparent);
  --admin-radius-control: 9px;
  --admin-radius-panel: 15px;
  --admin-radius-status: 7px;
  --admin-shadow-panel: 0 1px 2px rgba(15, 23, 42, .025);
  --admin-focus-ring: 0 0 0 3px rgba(15, 159, 143, .16);
  --admin-duration: 180ms;
  --admin-space-1: 4px;
  --admin-space-2: 8px;
  --admin-space-3: 12px;
  --admin-space-4: 16px;
  --admin-space-5: 22px;
  --admin-space-6: 28px;
  --admin-space-7: 34px;
  --admin-control-height: 38px;
  --admin-control-height-compact: 34px;
  --admin-tab-height: 42px;
  --admin-status-dot: 7px;
  --admin-page-title: 27px;
  --admin-section-title: 18px;
  --admin-body: 13px;
  --admin-control: 12px;
  --admin-meta: 10px;
  --admin-row-min: 64px;
  gap: var(--admin-space-5);
}

.admin-permission {
  display: flex;
  align-items: flex-start;
  gap: var(--admin-space-4);
  padding: var(--admin-space-5);
  color: var(--admin-muted);
  background: var(--admin-surface);
  border: 1px solid var(--admin-line);
  border-radius: var(--admin-radius-panel);
  box-shadow: var(--admin-shadow-panel);
}

.admin-permission strong { display: block; margin-bottom: var(--admin-space-1); color: var(--admin-ink); }
.admin-permission p { margin: 0; }

.admin-hero,
.admin-section__header,
.account-card > header,
.account-card > footer,
.sync-console,
.admin-table-shell > header,
.workflow-list > article,
.workflow-list__identity,
.workflow-list__actions,
.workflow-editor-shell > header,
.model-card,
.admin-notice,
.admin-error,
.account-runtime-blocker {
  display: flex;
  align-items: center;
}

.admin-hero {
  align-items: flex-start;
  padding: 0;
}

.admin-hero__title-row { display: flex; align-items: center; gap: var(--admin-space-4); flex-wrap: wrap; }
.admin-hero__title-row .admin-button { min-height: var(--admin-control-height-compact); }

.admin-hero h2,
.admin-section__header h3 {
  margin: var(--admin-space-1) 0 var(--admin-space-2);
  color: var(--admin-ink);
  letter-spacing: -.025em;
}

.admin-hero h2 { font-size: var(--admin-page-title); }
.admin-hero p,
.admin-section__header p,
.admin-empty p,
.account-card span,
.model-card p,
.model-boundary p { margin: 0; color: var(--admin-muted); font-size: var(--admin-body); line-height: 1.6; }

.admin-tabs {
  display: flex;
  gap: var(--admin-space-6);
  padding: 0;
  border-bottom: 1px solid var(--admin-line);
  background: transparent;
  overflow-x: auto;
}

.admin-tabs button {
  flex: 0 0 max-content;
  min-height: var(--admin-tab-height);
  padding: 0 var(--admin-space-1);
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--admin-muted);
  font: inherit;
  font-size: var(--admin-body);
  font-weight: 600;
  cursor: pointer;
  transition: color var(--admin-duration) ease, box-shadow var(--admin-duration) ease;
}

.admin-tabs button:hover { color: var(--admin-ink); }
.admin-tabs button.active { color: var(--admin-brand-dark); box-shadow: inset 0 -2px var(--admin-brand); }

.admin-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--admin-space-2);
  min-height: var(--admin-control-height);
  padding: 0 var(--admin-space-4);
  border: 1px solid transparent;
  border-radius: var(--admin-radius-control);
  font: inherit;
  font-size: var(--admin-control);
  font-weight: 700;
  cursor: pointer;
  transition: color var(--admin-duration) ease, background var(--admin-duration) ease, border-color var(--admin-duration) ease;
}

.admin-button:disabled { opacity: .52; cursor: not-allowed; }
.admin-button--primary { color: var(--admin-surface); background: var(--admin-ink); }
.admin-button--primary:not(:disabled):hover { background: var(--admin-slate); }
.admin-button--quiet { color: var(--admin-slate); border-color: var(--admin-line); background: var(--admin-surface); }
.admin-button--quiet:not(:disabled):hover { color: var(--admin-ink); border-color: var(--admin-muted); background: var(--admin-soft); }
.admin-button:focus-visible,
.admin-tabs button:focus-visible,
.admin-segmented button:focus-visible,
.admin-link:focus-visible { outline: 0; box-shadow: var(--admin-focus-ring); }
.admin-header-actions { display: flex; align-items: center; justify-content: flex-start; gap: var(--admin-space-3); flex-wrap: wrap; }
.admin-segmented { display: inline-flex; gap: var(--admin-space-1); padding: var(--admin-space-1); border: 1px solid var(--admin-line); border-radius: var(--admin-radius-control); background: var(--admin-soft); }
.admin-segmented button { min-height: var(--admin-control-height-compact); padding: 0 var(--admin-space-3); border: 0; border-radius: var(--admin-radius-status); color: var(--admin-muted); background: transparent; font: inherit; font-size: var(--admin-control); font-weight: 700; cursor: pointer; }
.admin-segmented button.active { color: var(--admin-brand-dark); background: var(--admin-surface); box-shadow: var(--admin-shadow-panel); }

.admin-notice,
.admin-error {
  gap: var(--admin-space-2);
  min-height: 44px;
  padding: var(--admin-space-2) var(--admin-space-3);
  border-radius: var(--admin-radius-control);
  font-size: var(--admin-body);
}

.admin-notice { color: var(--admin-brand-dark); background: var(--admin-success-soft); border: 1px solid var(--admin-success-line); }
.admin-notice.is-attention { color: var(--admin-warning); background: var(--admin-warning-soft); border-color: var(--admin-warning-line); }
.admin-notice span,
.admin-error span { flex: 1; }
.admin-notice button,
.admin-error button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.admin-error { color: var(--admin-danger); background: var(--admin-danger-soft); border: 1px solid var(--admin-danger-line); }
.admin-error button { font-weight: 700; text-decoration: underline; }

.account-runtime-blocker {
  gap: var(--admin-space-3);
  padding: var(--admin-space-3) var(--admin-space-5);
  color: var(--admin-warning);
  background: var(--admin-warning-soft);
  border-bottom: 1px solid var(--admin-warning-line);
}
.account-runtime-blocker > div { display: grid; flex: 1; gap: var(--admin-space-1); }
.account-runtime-blocker strong { color: var(--admin-ink); }
.account-runtime-blocker p { margin: 0; color: var(--admin-muted); font-size: var(--admin-control); line-height: 1.6; }

.admin-loading {
  display: grid;
  gap: 0;
  overflow: hidden;
  border: 1px solid var(--admin-line);
  border-radius: var(--admin-radius-panel);
  background: var(--admin-surface);
  box-shadow: var(--admin-shadow-panel);
}

.admin-loading i {
  height: var(--admin-row-min);
  border-bottom: 1px solid var(--admin-line);
  background: linear-gradient(90deg, var(--admin-soft) 25%, var(--admin-surface) 45%, var(--admin-soft) 65%);
  background-size: 300% 100%;
  animation: admin-shimmer 1.3s infinite;
}
.admin-loading i:last-child { border-bottom: 0; }

.admin-section {
  display: grid;
  gap: 0;
  min-width: 0;
  overflow: visible;
  border: 1px solid var(--admin-line);
  border-radius: var(--admin-radius-panel);
  background: var(--admin-surface);
  box-shadow: var(--admin-shadow-panel);
}

.admin-section__header {
  align-items: flex-start;
  flex-direction: column;
  gap: var(--admin-space-3);
  padding: var(--admin-space-4) var(--admin-space-5);
  border-bottom: 1px solid var(--admin-line);
}

.admin-section__header > div:first-child { max-width: 920px; }
.admin-section__header > .admin-button { align-self: flex-start; }

.admin-section__header h3 { margin-top: 0; font-size: var(--admin-section-title); }
.admin-kicker { display: none; }

.account-grid {
  display: grid;
  gap: 0;
}

.account-card,
.sync-console,
.admin-table-shell,
.workflow-list,
.workflow-editor-shell,
.model-card,
.model-boundary,
.diagnostic-grid > article,
.admin-empty {
  background: var(--admin-surface);
}

.account-card {
  display: grid;
  grid-template-columns: minmax(180px, .7fr) minmax(130px, .5fr) minmax(320px, 1.5fr);
  grid-template-areas:
    "identity check guidance"
    "actions actions actions"
    "technical technical technical"
    "feedback feedback feedback";
  align-items: center;
  column-gap: var(--admin-space-4);
  row-gap: var(--admin-space-2);
  min-height: var(--admin-row-min);
  padding: var(--admin-space-3) var(--admin-space-5);
  border-bottom: 1px solid var(--admin-line);
}
.account-card:last-child { border-bottom: 0; }
.account-card > header { grid-area: identity; align-items: center; gap: var(--admin-space-2); min-width: 0; flex-wrap: wrap; }
.account-card > header strong { color: var(--admin-ink); font-size: 15px; }

.account-status,
.workflow-status,
.table-status {
  display: inline-flex;
  width: fit-content;
  padding: var(--admin-space-1) var(--admin-space-2);
  border-radius: var(--admin-radius-status);
  background: var(--admin-soft);
  color: var(--admin-muted);
  font-size: var(--admin-meta);
  font-weight: 700;
  white-space: nowrap;
}

.account-status.is-ready,
.workflow-status.is-enabled,
.table-status.is-succeeded { color: var(--admin-brand-dark); background: var(--admin-success-soft); }
.account-status.is-browser_stopped,
.account-status.is-error,
.account-status.is-token_invalid,
.table-status.is-failed,
.table-status.is-cancelled { color: var(--admin-danger); background: var(--admin-danger-soft); }
.account-status.is-waiting_login,
.account-status.is-waiting_human,
.account-status.is-risk_control,
.table-status.is-waiting_human { color: var(--admin-warning); background: var(--admin-warning-soft); }
.table-status.is-pending,
.table-status.is-leased,
.table-status.is-running { color: var(--admin-slate); background: var(--admin-info-soft); }

.task-detail {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--admin-space-3);
  margin: 0;
}

.task-detail div { min-width: 0; }
.task-detail dt { margin-bottom: var(--admin-space-1); color: var(--admin-muted); font-size: var(--admin-meta); }
.task-detail dd { margin: 0; color: var(--admin-slate); font-size: var(--admin-control); overflow-wrap: anywhere; }
.account-last-check { grid-area: check; display: grid; gap: var(--admin-space-1); min-width: 0; }
.account-last-check span { color: var(--admin-muted); font-size: var(--admin-meta); }
.account-last-check strong { color: var(--admin-slate); font-size: var(--admin-control); font-weight: 600; white-space: nowrap; }
.account-blocker,
.account-ready { grid-area: guidance; margin: 0; padding-left: var(--admin-space-3); border-left: 2px solid var(--admin-warning); color: var(--admin-muted); font-size: var(--admin-control); line-height: 1.6; }
.account-ready { border-left-color: var(--admin-brand); }
.account-feedback { grid-area: feedback; margin: 0; padding: var(--admin-space-2) var(--admin-space-3); border-radius: var(--admin-radius-status); font-size: var(--admin-control); line-height: 1.5; }
.account-feedback.is-success { color: var(--admin-brand-dark); background: var(--admin-success-soft); }
.account-feedback.is-attention { color: var(--admin-warning); background: var(--admin-warning-soft); }
.account-feedback.is-error { color: var(--admin-danger); background: var(--admin-danger-soft); }
.account-card > footer { grid-area: actions; justify-content: flex-start; gap: var(--admin-space-2); min-width: 0; flex-wrap: wrap; }
.account-card > footer .admin-button { min-height: var(--admin-control-height-compact); padding-inline: var(--admin-space-3); white-space: nowrap; }

.account-technical { grid-area: technical; min-width: 0; }
.account-technical summary { width: fit-content; color: var(--admin-muted); font-size: var(--admin-meta); font-weight: 700; cursor: pointer; }
.account-technical summary:hover { color: var(--admin-brand-dark); }
.account-technical summary:focus-visible { outline: 0; box-shadow: var(--admin-focus-ring); }
.account-technical summary::marker { color: var(--admin-muted); }
.account-technical dl { display: grid; grid-template-columns: minmax(150px, .45fr) minmax(110px, .35fr) minmax(260px, 1.2fr); gap: var(--admin-space-4); margin: var(--admin-space-3) 0 0; padding: var(--admin-space-3); border-radius: var(--admin-radius-status); background: var(--admin-soft); }
.account-technical dl div { min-width: 0; }
.account-technical dt { margin-bottom: var(--admin-space-1); color: var(--admin-muted); font-size: var(--admin-meta); }
.account-technical dd { margin: 0; color: var(--admin-slate); font-size: var(--admin-control); overflow-wrap: anywhere; }

/* A row may contain several actions, but only the section-level task stays filled. */
.account-card .admin-button--primary,
.workflow-list .admin-button--primary,
.model-profile-list .admin-button--primary,
.admin-empty .admin-button--primary {
  color: var(--admin-slate);
  border-color: var(--admin-line);
  background: var(--admin-surface);
}
.account-card .admin-button--primary:not(:disabled):hover,
.workflow-list .admin-button--primary:not(:disabled):hover,
.model-profile-list .admin-button--primary:not(:disabled):hover,
.admin-empty .admin-button--primary:not(:disabled):hover {
  color: var(--admin-ink);
  border-color: var(--admin-muted);
  background: var(--admin-soft);
}

.admin-empty {
  display: grid;
  justify-items: center;
  gap: var(--admin-space-2);
  padding: var(--admin-space-7) var(--admin-space-5);
  text-align: center;
  color: var(--admin-muted);
}

.admin-empty strong { color: var(--admin-ink); }
.admin-empty--compact { padding: var(--admin-space-6) var(--admin-space-5); background: transparent; }

.sync-console {
  display: grid;
  grid-template-columns: minmax(220px, 1.2fr) minmax(250px, 1fr) auto;
  align-items: end;
  gap: var(--admin-space-4);
  padding: var(--admin-space-4) var(--admin-space-5);
  border-bottom: 1px solid var(--admin-line);
}

.sync-console label,
.admin-form label { display: grid; gap: var(--admin-space-2); color: var(--admin-slate); font-size: var(--admin-control); font-weight: 700; }
.sync-console select,
.admin-form input,
.admin-form select {
  width: 100%;
  min-height: 40px;
  padding: 0 var(--admin-space-3);
  border: 1px solid var(--admin-line);
  border-radius: var(--admin-radius-control);
  background: var(--admin-surface);
  color: var(--admin-ink);
  font: inherit;
}

.sync-readiness { display: flex; align-items: center; gap: var(--admin-space-3); min-height: 40px; }
.sync-readiness > span { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; }
.sync-readiness > span.is-ready { background: var(--admin-brand); box-shadow: 0 0 0 4px var(--admin-success-soft); }
.sync-readiness > span.is-blocked { background: var(--admin-warning); box-shadow: 0 0 0 4px var(--admin-warning-soft); }
.sync-readiness div { display: grid; gap: var(--admin-space-1); }
.sync-readiness strong { color: var(--admin-ink); font-size: var(--admin-body); }
.sync-readiness small { color: var(--admin-muted); font-size: var(--admin-meta); }
.sync-progress { padding: var(--admin-space-3) var(--admin-space-5); border-bottom: 1px solid var(--admin-line); background: var(--admin-soft); }
.sync-progress p { margin: var(--admin-space-2) 0 0; color: var(--admin-muted); font-size: var(--admin-control); }

.admin-table-shell { overflow: hidden; }
.admin-table-shell + .admin-table-shell,
.diagnostic-grid + .admin-table-shell { border-top: 1px solid var(--admin-line); }
.admin-table-shell > header { justify-content: space-between; gap: var(--admin-space-4); padding: var(--admin-space-3) var(--admin-space-5); border-bottom: 1px solid var(--admin-line); }
.admin-table-shell > header div { display: grid; gap: var(--admin-space-1); }
.admin-table-shell > header strong { color: var(--admin-ink); }
.admin-table-shell > header small,
.admin-table-shell > header span { color: var(--admin-muted); font-size: var(--admin-control); }
.admin-table-scroll { overflow-x: auto; }
.admin-table-shell table { width: 100%; border-collapse: collapse; font-size: var(--admin-body); }
.admin-table-shell th { padding: var(--admin-space-2) var(--admin-space-4); color: var(--admin-muted); background: var(--admin-soft); font-size: var(--admin-meta); text-align: left; white-space: nowrap; }
.admin-table-shell td { min-height: 48px; padding: var(--admin-space-3) var(--admin-space-4); border-top: 1px solid var(--admin-line); color: var(--admin-muted); }
.admin-table-shell td strong { color: var(--admin-ink); }
.admin-link { min-height: var(--admin-control-height-compact); padding: 0 var(--admin-space-1); border: 0; background: none; color: var(--admin-brand-dark); font: inherit; font-size: var(--admin-control); font-weight: 700; cursor: pointer; white-space: nowrap; }
.admin-link:disabled { opacity: .5; cursor: not-allowed; }
.admin-link--danger { color: var(--admin-danger); }

.workflow-list { overflow: hidden; }
.workflow-list > article { min-height: var(--admin-row-min); gap: var(--admin-space-4); padding: var(--admin-space-3) var(--admin-space-5); border-bottom: 1px solid var(--admin-line); }
.workflow-list > article:last-child { border-bottom: 0; }
.workflow-list__identity { flex: 1; gap: var(--admin-space-3); min-width: 0; }
.workflow-list__identity i { display: grid; place-items: center; width: 34px; height: 34px; border-radius: var(--admin-radius-control); color: var(--admin-brand); background: var(--admin-success-soft); }
.workflow-list__identity div { display: grid; gap: var(--admin-space-1); }
.workflow-list__identity strong { color: var(--admin-ink); }
.workflow-list__identity span { color: var(--admin-muted); font-size: var(--admin-control); }
.workflow-list__actions { gap: var(--admin-space-2); }
.workflow-editor-shell { min-width: 0; overflow: hidden; border-top: 1px solid var(--admin-line); }
.workflow-editor-shell > header { justify-content: space-between; gap: var(--admin-space-4); padding: var(--admin-space-3) var(--admin-space-5); border-bottom: 1px solid var(--admin-line); }
.workflow-editor-shell > header div { display: grid; gap: var(--admin-space-1); }
.workflow-editor-shell > header strong { color: var(--admin-ink); }
.workflow-editor-shell > header small { color: var(--admin-muted); }
.workflow-editor-shell :deep(.workflow-builder) { border: 0; border-radius: 0; }

.model-card { gap: var(--admin-space-4); padding: var(--admin-space-5); }
.model-card__icon { display: grid; place-items: center; width: 36px; height: 36px; flex: 0 0 auto; border-radius: var(--admin-radius-control); color: var(--admin-muted); background: var(--admin-soft); }
.model-card__body { display: grid; flex: 1; gap: var(--admin-space-1); min-width: 0; }
.model-card__body > span { color: var(--admin-muted); font-size: var(--admin-meta); }
.model-card__body > strong { color: var(--admin-ink); font-size: 15px; }
.model-card__body p { overflow-wrap: anywhere; font-size: var(--admin-control); word-break: break-word; }
.model-card__body small { overflow: hidden; color: var(--admin-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.model-profile-list { display: grid; gap: 0; }
.model-profile-list > article { display: flex; align-items: center; gap: var(--admin-space-4); min-height: var(--admin-row-min); padding: var(--admin-space-3) var(--admin-space-5); border-bottom: 1px solid var(--admin-line); background: var(--admin-surface); }
.model-profile-list > article:last-child { border-bottom: 0; }
.model-profile-list > article.is-active { box-shadow: inset 3px 0 var(--admin-brand); }
.model-profile-list > article.is-active .model-card__icon { color: var(--admin-brand-dark); background: var(--admin-success-soft); }
.model-card__actions { display: flex; align-items: center; justify-content: flex-end; gap: var(--admin-space-2); flex-wrap: wrap; }
.model-active-chip { padding: var(--admin-space-1) var(--admin-space-2); color: var(--admin-brand-dark); background: var(--admin-success-soft); border-radius: var(--admin-radius-status); font-size: var(--admin-meta); font-weight: 800; }
.model-action-message { margin: 0; padding: var(--admin-space-2) var(--admin-space-5); color: var(--admin-brand-dark); background: var(--admin-success-soft); border-bottom: 1px solid var(--admin-success-line); font-size: var(--admin-control); }
.model-list-loading { display: grid; gap: 0; }
.model-list-loading i { height: var(--admin-row-min); border-bottom: 1px solid var(--admin-line); background: linear-gradient(90deg, var(--admin-soft) 25%, var(--admin-surface) 50%, var(--admin-soft) 75%); background-size: 300% 100%; animation: admin-shimmer 1.25s ease infinite; }
.model-list-loading i:last-child { border-bottom: 0; }
.model-boundary { padding: var(--admin-space-3) var(--admin-space-5); border-top: 1px solid var(--admin-line); background: var(--admin-soft); }
.model-boundary strong { color: var(--admin-ink); }
.model-boundary p { margin-top: var(--admin-space-1); font-size: var(--admin-control); }

.diagnostic-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; border-bottom: 1px solid var(--admin-line); }
.diagnostic-grid > article { position: relative; display: grid; grid-template-columns: auto 1fr; align-items: center; gap: var(--admin-space-1) var(--admin-space-2); min-width: 0; padding: var(--admin-space-3) var(--admin-space-4) var(--admin-space-3) var(--admin-space-6); overflow: hidden; border-right: 1px solid var(--admin-line); }
.diagnostic-grid > article:last-child { border-right: 0; }
.diagnostic-grid > article::before { position: absolute; left: var(--admin-space-3); top: var(--admin-space-4); width: var(--admin-status-dot); height: var(--admin-status-dot); border-radius: 50%; content: ''; background: var(--admin-muted); }
.diagnostic-grid > article.is-ok::before { background: var(--admin-brand); }
.diagnostic-grid > article.is-attention::before { background: var(--admin-warning); }
.diagnostic-grid > article.is-blocked::before { background: var(--admin-danger); }
.diagnostic-grid span { color: var(--admin-muted); font-size: var(--admin-meta); }
.diagnostic-grid strong { color: var(--admin-ink); font-size: 14px; }
.diagnostic-grid p { grid-column: 1 / -1; margin: 0; color: var(--admin-muted); font-size: var(--admin-meta); line-height: 1.45; }

.admin-form { display: grid; gap: var(--admin-space-4); }
.admin-form p { margin: 0; color: var(--admin-muted); font-size: var(--admin-control); line-height: 1.5; }
.task-events { display: grid; gap: var(--admin-space-3); margin: var(--admin-space-5) 0 0; padding: 0; list-style: none; }
.task-events li { display: grid; grid-template-columns: 120px 1fr; gap: var(--admin-space-3); padding-top: var(--admin-space-3); border-top: 1px solid var(--admin-line); font-size: var(--admin-control); }
.task-events time { color: var(--admin-muted); }
.task-events span { color: var(--admin-ink); }

@keyframes admin-shimmer { to { background-position: -300% 0; } }

@media (max-width: 1250px) {
  .account-card {
    grid-template-columns: minmax(160px, .7fr) minmax(110px, .45fr) minmax(240px, 1.3fr);
    grid-template-areas:
      "identity check guidance"
      "actions actions actions"
      "technical technical technical"
      "feedback feedback feedback";
  }
}

@media (max-width: 1050px) {
  .diagnostic-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .diagnostic-grid > article:nth-child(2) { border-right: 0; }
  .diagnostic-grid > article:nth-child(-n+2) { border-bottom: 1px solid var(--admin-line); }
  .sync-console { grid-template-columns: 1fr 1fr; }
  .sync-console > .admin-button { grid-column: 1 / -1; }
  .workflow-list > article { align-items: flex-start; flex-wrap: wrap; }
  .workflow-list__actions { width: 100%; justify-content: flex-end; }
}

@media (max-width: 720px) {
  .admin-hero,
  .admin-section__header,
  .model-card,
  .account-runtime-blocker { align-items: stretch; flex-direction: column; }
  .admin-hero > .admin-button,
  .admin-section__header > .admin-button,
  .model-card > .admin-button { width: 100%; }
  .admin-header-actions { align-items: stretch; flex-direction: column; width: 100%; }
  .admin-header-actions > .admin-button,.admin-header-actions > .admin-segmented { width: 100%; }
  .admin-segmented button { flex: 1; }
  .diagnostic-grid,
  .sync-console { grid-template-columns: 1fr; }
  .admin-tabs { gap: var(--admin-space-5); }
  .account-card {
    grid-template-columns: 1fr;
    grid-template-areas:
      "identity"
      "check"
      "guidance"
      "actions"
      "technical"
      "feedback";
  }
  .account-card > header { align-items: center; }
  .account-technical dl,
  .task-detail { grid-template-columns: 1fr; }
  .account-card > footer { align-items: stretch; justify-content: flex-start; }
  .workflow-list__actions { align-items: stretch; flex-direction: column; }
  .workflow-list__actions .admin-button { width: 100%; }
  .model-profile-list > article { align-items: stretch; flex-direction: column; }
  .model-card__actions { align-items: stretch; flex-direction: column; }
  .model-card__actions .admin-button,.model-card__actions .admin-link { width: 100%; min-height: 36px; text-align: center; }
  .task-events li { grid-template-columns: 1fr; }
  .diagnostic-grid > article { border-right: 0; border-bottom: 1px solid var(--admin-line); }
  .diagnostic-grid > article:last-child { border-bottom: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .admin-button,
  .admin-tabs button { transition: none; }
  .admin-loading i { animation: none; }
  .model-list-loading i { animation: none; }
}
</style>
