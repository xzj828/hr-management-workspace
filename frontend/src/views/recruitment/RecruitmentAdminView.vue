<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
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

const auth = useAuthStore()
const credentials = useModelCredentialStore()
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
const summary = reactive({ worker: null, cli_available: false, task_counts: {}, has_active_task: false })
const accounts = ref([])
const jobs = ref([])
const tasks = ref([])
const workflows = ref([])
const workflowVersions = ref([])
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
let syncPollTimer = null

const workerOnline = computed(() => summary.worker?.status === 'online')
const activeTaskStatuses = new Set(['pending', 'leased', 'running'])
const activeTasksByAccount = computed(() => Object.fromEntries(
  tasks.value
    .filter((task) => activeTaskStatuses.has(task.status))
    .map((task) => [task.boss_account, task]),
))
const selectedAccount = computed(() => accounts.value.find((account) => String(account.id) === String(selectedAccountId.value)) || null)
const selectedAccountReady = computed(() => selectedAccount.value?.login_status === 'ready')
const selectedAccountJobs = computed(() => jobs.value.filter((job) => String(job.boss_account) === String(selectedAccountId.value)))
const visibleWorkflowVersions = computed(() => {
  const templateIds = new Set(workflows.value.map((workflow) => workflow.id))
  return workflowVersions.value.filter((version) => templateIds.has(version.template))
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
  settled.forEach((result, index) => {
    const key = requests[index][0]
    if (result.status === 'rejected') {
      failures.push(result.reason?.message || `${key} 加载失败`)
      return
    }
    if (key === 'summary') Object.assign(summary, result.value)
    if (key === 'accounts') accounts.value = listItems(result.value)
    if (key === 'jobs') jobs.value = listItems(result.value)
    if (key === 'tasks') tasks.value = listItems(result.value)
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
  return account.login_status === 'ready' ? '重新打开登录环境' : '启动并登录'
}

async function reloadAccountsAndTasks() {
  const [accountPayload, taskPayload, summaryPayload] = await Promise.all([
    api('recruitment/boss-accounts/'),
    api('recruitment/rpa-tasks/'),
    api('recruitment/automation/summary/'),
  ])
  accounts.value = listItems(accountPayload)
  tasks.value = listItems(taskPayload)
  Object.assign(summary, summaryPayload)
  assignDefaultAccount()
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
    await reloadAccountsAndTasks()
    setNotice('success', workerOnline.value
      ? '账号已创建，隔离浏览器启动任务已提交。请在打开的窗口中完成登录。'
      : '账号已创建，启动任务已排队。请先启动本机 Worker。')
  } catch (err) {
    error.value = err.message
  } finally {
    accountSaving.value = false
  }
}

async function queueBrowserLogin(account) {
  const busyKey = `${account.id}:login`
  if (actionBusy[busyKey] || activeTasksByAccount.value[account.id]) return
  actionBusy[busyKey] = true
  error.value = ''
  try {
    await api('recruitment/rpa-tasks/', {
      method: 'POST',
      body: JSON.stringify({
        boss_account: account.id,
        action: 'check_status',
        request_payload: { open_login: true },
      }),
    })
    await reloadAccountsAndTasks()
    setNotice('success', workerOnline.value
      ? '隔离浏览器启动任务已提交。窗口打开后请完成 BOSS 登录，再点击“检查状态”。'
      : '启动任务已排队，但本机 Worker 尚未连接；启动 Worker 后任务会继续执行。')
  } catch (err) {
    error.value = err.message
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
      setNotice('attention', '检测到隔离浏览器未启动。点击“启动并登录”会创建可追踪的启动任务。')
    } else if (updated.login_status === 'ready') {
      setNotice('success', '账号登录状态正常，可以同步职位或运行招聘方案。')
    } else {
      setNotice('attention', updated.status_detail || accountStatusLabel(updated))
    }
  } catch (err) {
    error.value = err.message
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
      await loadJobs()
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
  if (!selectedAccount.value || !selectedAccountReady.value || (syncTask.value && !terminalTaskStatuses.has(syncTask.value.status))) return
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

onMounted(loadAdmin)
onUnmounted(stopSyncPolling)
</script>

<template>
  <div class="page-stack recruitment-admin">
    <header class="admin-hero">
      <div>
        <span class="eyebrow">Recruitment Administration</span>
        <h2>管理后台</h2>
        <p>低频设置与技术状态集中在这里；业务 HR 的准备和执行留在招聘作业台。</p>
      </div>
      <button v-if="auth.canManage" class="admin-button admin-button--quiet" type="button" :disabled="refreshing" @click="loadAdmin({ silent: true })">
        <AppIcon name="refresh" :size="16" />{{ refreshing ? '刷新中…' : '刷新状态' }}
      </button>
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
          <button class="admin-button admin-button--primary" type="button" @click="accountModalOpen = true">
            <AppIcon name="plus" :size="16" />添加账号
          </button>
        </header>

        <div v-if="accounts.length" class="account-grid">
          <article v-for="account in accounts" :key="account.id" class="account-card">
            <header>
              <div>
                <strong>{{ account.name }}</strong>
                <span>{{ account.browser_type === 'edge' ? 'Microsoft Edge' : 'Google Chrome' }} · CDP {{ account.cdp_port }}</span>
              </div>
              <span :class="['account-status', `is-${accountStatus(account)}`]">{{ accountStatusLabel(account) }}</span>
            </header>
            <dl>
              <div><dt>隔离目录</dt><dd>{{ account.browser_profile }}</dd></div>
              <div><dt>最近检查</dt><dd>{{ formatDate(account.last_checked_at) }}</dd></div>
            </dl>
            <p v-if="account.login_status !== 'ready'" class="account-blocker">
              {{ account.login_status === 'browser_stopped' ? '浏览器尚未启动，职位同步与正式执行暂不可用。' : '完成登录并检查状态后，才会开放业务执行。' }}
            </p>
            <p v-else class="account-ready">账号已就绪，可同步职位并运行已启用方案。</p>
            <footer>
              <button
                class="admin-button admin-button--primary"
                type="button"
                :disabled="Boolean(activeTasksByAccount[account.id]) || actionBusy[`${account.id}:login`]"
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
            </footer>
          </article>
        </div>
        <div v-else class="admin-empty">
          <AppIcon name="user" :size="24" />
          <strong>尚未添加 BOSS 账号</strong>
          <p>添加后系统会分配隔离浏览器目录和端口，并创建一次可追踪的启动任务。</p>
          <button class="admin-button admin-button--primary" type="button" @click="accountModalOpen = true">添加第一个账号</button>
        </div>
      </section>

      <section v-else-if="activeTab === 'jobs'" class="admin-section">
        <header class="admin-section__header">
          <div>
            <span class="admin-kicker">POSITION ARCHIVE</span>
            <h3>从 BOSS 同步职位</h3>
            <p>这里只负责把已发布职位归档到工作台，不在此处创建或编辑 BOSS 职位。</p>
          </div>
        </header>

        <div v-if="accounts.length" class="sync-console">
          <label>
            <span>同步账号</span>
            <select v-model="selectedAccountId" data-test="admin-sync-account">
              <option v-for="account in accounts" :key="account.id" :value="String(account.id)">
                {{ account.name }} · {{ accountStatusLabel(account) }}
              </option>
            </select>
          </label>
          <div class="sync-readiness">
            <span :class="selectedAccountReady ? 'is-ready' : 'is-blocked'"></span>
            <div>
              <strong>{{ selectedAccountReady ? '账号可同步' : '同步条件未满足' }}</strong>
              <small>{{ selectedAccountReady ? '将创建一个有审计记录的职位同步任务。' : '需要先启动隔离浏览器并完成登录。' }}</small>
            </div>
          </div>
          <button
            v-if="selectedAccountReady"
            class="admin-button admin-button--primary"
            data-test="admin-sync-positions"
            type="button"
            :disabled="syncTask && !terminalTaskStatuses.has(syncTask.status)"
            @click="syncPositions"
          >{{ syncTask && !terminalTaskStatuses.has(syncTask.status) ? '同步中…' : '一键同步职位' }}</button>
          <button v-else class="admin-button admin-button--quiet" type="button" @click="goToAccountReadiness">去启动并登录</button>
        </div>
        <div v-else class="admin-empty">
          <AppIcon name="workflow" :size="24" />
          <strong>没有可用于同步的账号</strong>
          <p>先添加 BOSS 账号并在隔离浏览器中完成登录。</p>
          <button class="admin-button admin-button--primary" type="button" @click="activeTab = 'accounts'; accountModalOpen = true">添加账号</button>
        </div>

        <div v-if="syncTask" class="sync-progress" aria-live="polite">
          <TaskProgressBar :status="syncTask.status" />
          <p v-if="syncMessage">{{ syncMessage }}</p>
        </div>

        <div v-if="accounts.length" class="admin-table-shell">
          <header>
            <div><strong>已归档职位</strong><small>{{ selectedAccount?.name || '当前账号' }}</small></div>
            <span>{{ selectedAccountJobs.length }} 个</span>
          </header>
          <div v-if="selectedAccountJobs.length" class="admin-table-scroll">
            <table>
              <thead><tr><th>职位</th><th>部门</th><th>招聘人数</th><th>状态</th><th>更新时间</th></tr></thead>
              <tbody>
                <tr v-for="job in selectedAccountJobs" :key="job.id">
                  <td><strong>{{ job.title }}</strong></td>
                  <td>{{ job.department || '—' }}</td>
                  <td>{{ job.headcount || '—' }}</td>
                  <td><span class="table-status">{{ { open: '招聘中', paused: '已暂停', closed: '已关闭' }[job.status] || job.status }}</span></td>
                  <td>{{ formatDate(job.updated_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="admin-empty admin-empty--compact">
            <strong>当前账号还没有归档职位</strong>
            <p>{{ selectedAccountReady ? '点击“一键同步职位”从 BOSS 获取已发布职位。' : '账号登录成功后才能同步职位。' }}</p>
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
          <button class="admin-button admin-button--primary" type="button" @click="openNewWorkflow">新建高级流程</button>
        </header>

        <div v-if="visibleWorkflowVersions.length" class="workflow-list">
          <article v-for="version in visibleWorkflowVersions" :key="version.id">
            <div class="workflow-list__identity">
              <i><AppIcon name="workflow" :size="18" /></i>
              <div><strong>{{ workflowName(version) }}</strong><span>版本 {{ version.version }} · {{ version.nodes?.length || 0 }} 个节点</span></div>
            </div>
            <span :class="['workflow-status', `is-${version.status}`]">{{ workflowStatusLabel(version.status) }}</span>
            <div class="workflow-list__actions">
              <button class="admin-button admin-button--quiet" type="button" :data-test="`edit-admin-workflow-${version.id}`" @click="editWorkflow(version)">基于此版本编排</button>
              <button v-if="version.status === 'draft'" class="admin-button admin-button--primary" type="button" :disabled="actionBusy[`workflow:${version.id}`]" @click="enableWorkflow(version)">{{ actionBusy[`workflow:${version.id}`] ? '校验中…' : '校验并启用' }}</button>
            </div>
          </article>
        </div>
        <div v-else class="admin-empty">
          <AppIcon name="workflow" :size="24" />
          <strong>尚未定义流程方案</strong>
          <p>可以先在招聘作业台使用标准方案；需要自定义节点时再创建高级流程。</p>
          <button class="admin-button admin-button--primary" type="button" @click="openNewWorkflow">打开高级编排</button>
        </div>

        <div v-if="workflowEditorOpen" class="workflow-editor-shell">
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
          <button class="admin-button admin-button--primary" data-test="open-model-config" type="button" @click="openModelDrawer()"><AppIcon name="plus" :size="16" />新增自定义模型</button>
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
              <button v-if="!profile.is_active" class="admin-button admin-button--primary" type="button" :disabled="Boolean(credentials.switchingId)" @click="activateModel(profile)">{{ String(credentials.switchingId) === String(profile.id) ? '切换中…' : '切换到此模型' }}</button>
              <span v-else class="model-active-chip">当前使用</span>
              <button class="admin-button admin-button--quiet" type="button" :disabled="Boolean(credentials.testingId)" @click="testModel(profile)">{{ String(credentials.testingId) === String(profile.id) ? '连接中…' : '测试连接' }}</button>
              <button class="admin-link" type="button" @click="openModelDrawer(profile)">编辑</button>
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
        </header>
        <div class="diagnostic-grid">
          <article v-for="item in diagnostics" :key="item.label" :class="`is-${item.state}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <p>{{ item.detail }}</p>
          </article>
        </div>

        <div class="admin-table-shell">
          <header>
            <div><strong>最近自动化任务</strong><small>状态、错误和事件均来自服务端审计记录</small></div>
            <span>{{ tasks.length }} 条</span>
          </header>
          <div v-if="tasks.length" class="admin-table-scroll">
            <table>
              <thead><tr><th>账号</th><th>动作</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
              <tbody>
                <tr v-for="task in tasks.slice(0, 20)" :key="task.id">
                  <td><strong>{{ task.account_name }}</strong></td>
                  <td>{{ actionLabels[task.action] || task.action }}</td>
                  <td><span :class="['table-status', `is-${task.status}`]">{{ taskStatusLabels[task.status] || task.status }}</span></td>
                  <td>{{ formatDate(task.created_at) }}</td>
                  <td><button class="admin-link" type="button" @click="selectedTask = task">查看记录</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="admin-empty admin-empty--compact"><strong>暂无自动化任务</strong><p>账号启动、职位同步和流程执行后会在这里留下记录。</p></div>
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
        <button class="primary-button" type="submit" form="admin-account-form" :disabled="accountSaving">{{ accountSaving ? '保存中…' : '保存并启动登录' }}</button>
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
    </ModalPanel>

    <ModelProfileDrawer v-if="auth.canManage && modelDrawerOpen" :profile="editingModel" @close="closeModelDrawer" @saved="modelSaved" />
  </div>
</template>

<style scoped>
.recruitment-admin {
  --admin-ink: #172822;
  --admin-muted: #66736e;
  --admin-line: #dfe7e3;
  --admin-soft: #f5f8f6;
  --admin-brand: #0f7655;
  --admin-brand-dark: #0a5b40;
  gap: 18px;
}

.admin-permission {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 22px;
  color: var(--admin-muted);
  background: #fff;
  border: 1px solid var(--admin-line);
  border-radius: 14px;
}

.admin-permission strong { display: block; color: var(--admin-ink); margin-bottom: 5px; }
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
.admin-error {
  display: flex;
  align-items: center;
}

.admin-hero {
  justify-content: space-between;
  gap: 24px;
  padding: 4px 2px 2px;
}

.admin-hero h2,
.admin-section__header h3 {
  margin: 4px 0 6px;
  color: var(--admin-ink);
  letter-spacing: -.025em;
}

.admin-hero h2 { font-size: clamp(25px, 3vw, 34px); }
.admin-hero p,
.admin-section__header p,
.admin-empty p,
.account-card span,
.model-card p,
.model-boundary p { margin: 0; color: var(--admin-muted); line-height: 1.55; }

.admin-tabs {
  display: flex;
  gap: 5px;
  padding: 5px;
  border: 1px solid var(--admin-line);
  border-radius: 14px;
  background: #fff;
  overflow-x: auto;
}

.admin-tabs button {
  flex: 1 0 max-content;
  min-height: 40px;
  padding: 0 15px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #66736e;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}

.admin-tabs button:hover { background: var(--admin-soft); color: var(--admin-ink); }
.admin-tabs button.active { background: #e7f4ed; color: var(--admin-brand-dark); box-shadow: inset 0 0 0 1px #c7e5d6; }

.admin-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 9px;
  font: inherit;
  font-size: 13px;
  font-weight: 680;
  cursor: pointer;
  transition: .16s ease;
}

.admin-button:disabled { opacity: .52; cursor: not-allowed; }
.admin-button--primary { color: #fff; background: var(--admin-brand); }
.admin-button--primary:not(:disabled):hover { background: var(--admin-brand-dark); transform: translateY(-1px); }
.admin-button--quiet { color: var(--admin-ink); border-color: var(--admin-line); background: #fff; }
.admin-button--quiet:not(:disabled):hover { border-color: #b8ccc3; background: var(--admin-soft); }

.admin-notice,
.admin-error {
  gap: 9px;
  min-height: 44px;
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 13px;
}

.admin-notice { color: #205743; background: #ebf7f0; border: 1px solid #cce9d9; }
.admin-notice.is-attention { color: #7a5315; background: #fff7e5; border-color: #f2ddb1; }
.admin-notice span,
.admin-error span { flex: 1; }
.admin-notice button,
.admin-error button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.admin-error { color: #8e372f; background: #fff0ee; border: 1px solid #f1cbc6; }
.admin-error button { font-weight: 700; text-decoration: underline; }

.admin-loading {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.admin-loading i {
  height: 150px;
  border-radius: 14px;
  background: linear-gradient(90deg, #f1f4f2 25%, #fafcfb 45%, #f1f4f2 65%);
  background-size: 300% 100%;
  animation: admin-shimmer 1.3s infinite;
}

.admin-section {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.admin-section__header {
  justify-content: space-between;
  gap: 20px;
  padding: 19px 21px;
  border: 1px solid var(--admin-line);
  border-radius: 14px;
  background: #fff;
}

.admin-section__header h3 { font-size: 20px; }
.admin-kicker { color: #7b8983; font-size: 10px; font-weight: 800; letter-spacing: .14em; }

.account-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
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
  border: 1px solid var(--admin-line);
  border-radius: 14px;
  background: #fff;
}

.account-card { padding: 17px; }
.account-card > header { justify-content: space-between; gap: 12px; }
.account-card > header div { display: grid; gap: 3px; min-width: 0; }
.account-card > header strong { color: var(--admin-ink); font-size: 16px; }
.account-card > header span { font-size: 12px; }

.account-status,
.workflow-status,
.table-status {
  display: inline-flex;
  width: fit-content;
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf1ef;
  color: #5f6e68;
  font-size: 11px;
  font-weight: 750;
  white-space: nowrap;
}

.account-status.is-ready,
.workflow-status.is-enabled,
.table-status.is-succeeded { color: #176548; background: #e6f5ed; }
.account-status.is-browser_stopped,
.account-status.is-error,
.account-status.is-token_invalid,
.table-status.is-failed,
.table-status.is-cancelled { color: #96483e; background: #faece9; }
.account-status.is-waiting_login,
.account-status.is-waiting_human,
.account-status.is-risk_control,
.table-status.is-waiting_human { color: #825a17; background: #fff4da; }
.table-status.is-pending,
.table-status.is-leased,
.table-status.is-running { color: #2d5d86; background: #eaf2f9; }

.account-card dl,
.task-detail {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 15px 0;
}

.account-card dl div,
.task-detail div { min-width: 0; }
.account-card dt,
.task-detail dt { margin-bottom: 3px; color: #87928e; font-size: 11px; }
.account-card dd,
.task-detail dd { margin: 0; color: #33463f; font-size: 12px; overflow-wrap: anywhere; }
.account-blocker,
.account-ready { min-height: 40px; margin: 0 0 14px; padding: 9px 10px; border-radius: 8px; font-size: 12px; line-height: 1.5; }
.account-blocker { color: #7a5315; background: #fff7e6; }
.account-ready { color: #176548; background: #ebf7f0; }
.account-card > footer { gap: 8px; }

.admin-empty {
  display: grid;
  justify-items: center;
  gap: 7px;
  padding: 42px 24px;
  text-align: center;
  color: var(--admin-muted);
}

.admin-empty strong { color: var(--admin-ink); }
.admin-empty--compact { border: 0; border-radius: 0; padding: 32px 20px; background: transparent; }

.sync-console {
  display: grid;
  grid-template-columns: minmax(220px, 1.2fr) minmax(250px, 1fr) auto;
  align-items: end;
  gap: 14px;
  padding: 17px;
}

.sync-console label,
.admin-form label { display: grid; gap: 6px; color: #4b5a55; font-size: 12px; font-weight: 700; }
.sync-console select,
.admin-form input,
.admin-form select {
  width: 100%;
  min-height: 40px;
  padding: 0 11px;
  border: 1px solid #cfdbd6;
  border-radius: 8px;
  background: #fff;
  color: var(--admin-ink);
  font: inherit;
}

.sync-readiness { display: flex; align-items: center; gap: 10px; min-height: 40px; }
.sync-readiness > span { width: 9px; height: 9px; flex: 0 0 auto; border-radius: 50%; }
.sync-readiness > span.is-ready { background: #25a36f; box-shadow: 0 0 0 4px #e6f5ed; }
.sync-readiness > span.is-blocked { background: #d88933; box-shadow: 0 0 0 4px #fff2db; }
.sync-readiness div { display: grid; gap: 2px; }
.sync-readiness strong { color: var(--admin-ink); font-size: 13px; }
.sync-readiness small { color: var(--admin-muted); font-size: 11px; }
.sync-progress { padding: 14px 17px; border: 1px solid #dce8e2; border-radius: 12px; background: #f8fbf9; }
.sync-progress p { margin: 8px 0 0; color: #4d6259; font-size: 12px; }

.admin-table-shell { overflow: hidden; }
.admin-table-shell > header { justify-content: space-between; gap: 16px; padding: 14px 17px; border-bottom: 1px solid var(--admin-line); }
.admin-table-shell > header div { display: grid; gap: 2px; }
.admin-table-shell > header strong { color: var(--admin-ink); }
.admin-table-shell > header small,
.admin-table-shell > header span { color: var(--admin-muted); font-size: 12px; }
.admin-table-scroll { overflow-x: auto; }
.admin-table-shell table { width: 100%; border-collapse: collapse; font-size: 13px; }
.admin-table-shell th { padding: 10px 16px; color: #77847f; background: var(--admin-soft); font-size: 11px; text-align: left; white-space: nowrap; }
.admin-table-shell td { padding: 12px 16px; border-top: 1px solid #edf1ef; color: #53615c; }
.admin-table-shell td strong { color: var(--admin-ink); }
.admin-link { border: 0; background: none; color: var(--admin-brand); font: inherit; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap; }

.workflow-list { overflow: hidden; }
.workflow-list > article { gap: 14px; padding: 14px 16px; border-bottom: 1px solid var(--admin-line); }
.workflow-list > article:last-child { border-bottom: 0; }
.workflow-list__identity { flex: 1; gap: 11px; min-width: 0; }
.workflow-list__identity i { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; color: var(--admin-brand); background: #e9f5ef; }
.workflow-list__identity div { display: grid; gap: 2px; }
.workflow-list__identity strong { color: var(--admin-ink); }
.workflow-list__identity span { color: var(--admin-muted); font-size: 12px; }
.workflow-list__actions { gap: 7px; }
.workflow-editor-shell { min-width: 0; overflow: hidden; }
.workflow-editor-shell > header { justify-content: space-between; gap: 14px; padding: 14px 16px; border-bottom: 1px solid var(--admin-line); }
.workflow-editor-shell > header div { display: grid; gap: 3px; }
.workflow-editor-shell > header strong { color: var(--admin-ink); }
.workflow-editor-shell > header small { color: var(--admin-muted); }
.workflow-editor-shell :deep(.workflow-builder) { border: 0; border-radius: 0; }

.model-card { gap: 16px; padding: 21px; }
.model-card__icon { display: grid; place-items: center; width: 48px; height: 48px; flex: 0 0 auto; border-radius: 13px; color: #785b13; background: #fff2c9; }
.model-card__body { display: grid; flex: 1; gap: 3px; min-width: 0; }
.model-card__body > span { color: var(--admin-muted); font-size: 11px; }
.model-card__body > strong { color: var(--admin-ink); font-size: 18px; }
.model-card__body p { overflow-wrap: anywhere; font-size: 12px; word-break: break-word; }
.model-card__body small { overflow: hidden; color: var(--admin-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.model-profile-list { display: grid; gap: 10px; }
.model-profile-list > article { display: flex; align-items: center; gap: 16px; padding: 18px 20px; border: 1px solid var(--admin-line); border-radius: 13px; background: #fff; }
.model-profile-list > article.is-active { border-color: #9fd4c6; box-shadow: inset 3px 0 #19927f; }
.model-profile-list > article.is-active .model-card__icon { color: #0d8172; background: #e5f6f1; }
.model-card__actions { display: flex; align-items: center; justify-content: flex-end; gap: 7px; flex-wrap: wrap; }
.model-active-chip { padding: 6px 9px; color: #0d766d; background: #e5f6f1; border-radius: 999px; font-size: 10px; font-weight: 800; }
.model-action-message { margin: 0; padding: 11px 13px; color: #0d766d; background: #e9f8f5; border: 1px solid #c9ece5; border-radius: 9px; font-size: 12px; }
.model-list-loading { display: grid; gap: 9px; }
.model-list-loading i { height: 82px; border-radius: 13px; background: linear-gradient(90deg, #f0f3f2 25%, #fafbfb 50%, #f0f3f2 75%); background-size: 300% 100%; animation: admin-shimmer 1.25s ease infinite; }
.model-boundary { padding: 17px 19px; }
.model-boundary strong { color: var(--admin-ink); }
.model-boundary p { margin-top: 5px; font-size: 13px; }

.diagnostic-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.diagnostic-grid > article { position: relative; min-width: 0; padding: 16px; overflow: hidden; }
.diagnostic-grid > article::before { position: absolute; inset: 0 auto 0 0; width: 3px; content: ''; background: #b9c5c0; }
.diagnostic-grid > article.is-ok::before { background: #25a36f; }
.diagnostic-grid > article.is-attention::before { background: #d88933; }
.diagnostic-grid > article.is-blocked::before { background: #c6584a; }
.diagnostic-grid span { color: var(--admin-muted); font-size: 11px; }
.diagnostic-grid strong { display: block; margin: 6px 0; color: var(--admin-ink); font-size: 19px; }
.diagnostic-grid p { margin: 0; color: #68766f; font-size: 11px; line-height: 1.45; }

.admin-form { display: grid; gap: 15px; }
.admin-form p { margin: 0; color: var(--admin-muted); font-size: 12px; line-height: 1.5; }
.task-events { display: grid; gap: 10px; margin: 18px 0 0; padding: 0; list-style: none; }
.task-events li { display: grid; grid-template-columns: 120px 1fr; gap: 10px; padding-top: 10px; border-top: 1px solid var(--admin-line); font-size: 12px; }
.task-events time { color: var(--admin-muted); }
.task-events span { color: var(--admin-ink); }

@keyframes admin-shimmer { to { background-position: -300% 0; } }

@media (max-width: 1050px) {
  .account-grid { grid-template-columns: 1fr; }
  .diagnostic-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sync-console { grid-template-columns: 1fr 1fr; }
  .sync-console > .admin-button { grid-column: 1 / -1; }
  .workflow-list > article { align-items: flex-start; flex-wrap: wrap; }
  .workflow-list__actions { width: 100%; justify-content: flex-end; }
}

@media (max-width: 720px) {
  .admin-hero,
  .admin-section__header,
  .model-card { align-items: stretch; flex-direction: column; }
  .admin-hero > .admin-button,
  .admin-section__header > .admin-button,
  .model-card > .admin-button { width: 100%; }
  .admin-loading,
  .diagnostic-grid,
  .sync-console { grid-template-columns: 1fr; }
  .admin-tabs { margin-inline: -2px; }
  .account-card dl,
  .task-detail { grid-template-columns: 1fr; }
  .account-card > footer { align-items: stretch; flex-direction: column; }
  .workflow-list__actions { align-items: stretch; flex-direction: column; }
  .workflow-list__actions .admin-button { width: 100%; }
  .model-profile-list > article { align-items: stretch; flex-direction: column; }
  .model-card__actions { align-items: stretch; flex-direction: column; }
  .model-card__actions .admin-button,.model-card__actions .admin-link { width: 100%; min-height: 36px; text-align: center; }
  .task-events li { grid-template-columns: 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .admin-button { transition: none; }
  .admin-loading i { animation: none; }
}
</style>
