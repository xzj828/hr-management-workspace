<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, listItems } from '@/api'
import ModalPanel from '@/components/ModalPanel.vue'
import AppIcon from '@/components/AppIcon.vue'
import AutomationBatchPanel from '@/components/AutomationBatchPanel.vue'
import WorkflowCanvas from '@/components/WorkflowCanvas.vue'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'
import WorkflowRunPanel from '@/components/WorkflowRunPanel.vue'
import {
  accountDisplayStatus,
  accountActionLabel,
  actionLabels,
  availableActions,
  loginStatusLabel,
  taskStatusLabels,
} from '@/recruitmentAutomation'

const summary = reactive({ worker: null, cli_available: false, task_counts: {}, has_active_task: false })
const accounts = ref([])
const tasks = ref([])
const batches = ref([]), workflows = ref([]), workflowVersions = ref([])
const attentions = ref([]), campaigns = ref([]), syncPolicies = ref([]), openJobs = ref([])
const workspaceTab = ref('accounts'), workflowSaving = ref(false)
const workflowEditorSnapshot = ref(null), workflowEditorKey = ref(0)
const loading = ref(true)
const error = ref('')
const accountModalOpen = ref(false)
const selectedTask = ref(null)
const saving = ref(false)
const form = reactive({ name: '', browser_type: 'edge' })
const actionMenu = ref(null)
const lifecycleTarget = ref(null), lifecycleSaving = ref(false)
const showArchived = ref(false)
const activeRun = ref(null), runBusy = ref(false), formalVersion = ref(null)
const formalJobs = ref([]), formalJobId = ref('')
const schemeModal = ref('')
const schemeSaving = ref(false)
const schemeForm = reactive({ accountId: '', jobId: '', interval: 2, source: 'search', keyword: '', target: 3, maxScan: 20 })
let refreshTimer = null
let runPollTimer = null

const activeTaskAccountIds = computed(() => new Set(
  tasks.value
    .filter((task) => ['pending', 'leased', 'running'].includes(task.status))
    .map((task) => task.boss_account),
))

const completedCount = computed(() => summary.task_counts?.succeeded || 0)
const workflowNodeStatuses = computed(() => Object.fromEntries((activeRun.value?.node_runs || []).map((node) => [node.node_key, node.status])))

async function loadWorkspace({ silent = false } = {}) {
  if (!silent) {
    loading.value = true
    error.value = ''
  }
  try {
    const archiveQuery = showArchived.value ? '?archived=1' : ''
    const [summaryPayload, accountPayload, taskPayload, batchPayload, workflowPayload, versionPayload] = await Promise.all([
      api('recruitment/automation/summary/'),
      api(`recruitment/boss-accounts/${archiveQuery}`),
      api(`recruitment/rpa-tasks/${archiveQuery}`),
      api('recruitment/execution-batches/'),
      api(`recruitment/workflows/${archiveQuery}`),
      api('recruitment/workflow-versions/'),
    ])
    Object.assign(summary, summaryPayload)
    accounts.value = listItems(accountPayload)
    tasks.value = listItems(taskPayload)
    batches.value = listItems(batchPayload)
    workflows.value = listItems(workflowPayload)
    const visibleTemplateIds = new Set(workflows.value.map((item) => item.id))
    workflowVersions.value = listItems(versionPayload).filter((item) => visibleTemplateIds.has(item.template))
    const operations = await Promise.allSettled([
      api('recruitment/human-attentions/?status=open'),
      api('recruitment/search-campaigns/'),
      api('recruitment/message-sync-policies/'),
      api('recruitment/jobs/'),
    ])
    if (operations[0].status === 'fulfilled') attentions.value = listItems(operations[0].value)
    if (operations[1].status === 'fulfilled') campaigns.value = listItems(operations[1].value)
    if (operations[2].status === 'fulfilled') syncPolicies.value = listItems(operations[2].value)
    if (operations[3].status === 'fulfilled') openJobs.value = listItems(operations[3].value).filter((job) => job.status === 'open')
  } catch (err) {
    if (!silent) error.value = err.message
  } finally {
    if (!silent) loading.value = false
  }
}

function actionsFor(account) {
  if (account.archived_at) return ['restore_account']
  return [...availableActions({ ...account, has_active_task: activeTaskAccountIds.value.has(account.id) }), 'archive_account']
}

function openScheme(kind) {
  schemeModal.value = kind
  schemeForm.accountId = accounts.value.find((item) => item.login_status === 'ready')?.id || accounts.value[0]?.id || ''
  const jobs = openJobs.value.filter((job) => String(job.boss_account) === String(schemeForm.accountId))
  schemeForm.jobId = jobs[0]?.id || ''
  const policy = syncPolicies.value.find((item) => String(item.boss_account) === String(schemeForm.accountId))
  schemeForm.interval = policy?.interval_minutes || 2
}

async function saveAndRunScheme() {
  schemeSaving.value = true; error.value = ''
  try {
    const kind = schemeModal.value
    if (!schemeForm.accountId || !schemeForm.jobId) throw new Error('请选择已登录账号和在招职位')
    if (kind === 'passive_resume') {
      const existing = syncPolicies.value.find((item) => String(item.boss_account) === String(schemeForm.accountId))
      const policyBody = JSON.stringify({ boss_account: Number(schemeForm.accountId), enabled: true, interval_minutes: Number(schemeForm.interval) })
      await api(existing ? `recruitment/message-sync-policies/${existing.id}/` : 'recruitment/message-sync-policies/', {
        method: existing ? 'PATCH' : 'POST', body: policyBody,
      })
    }
    const created = await api('recruitment/workflows/standard/', {
      method: 'POST',
      body: JSON.stringify({
        kind, boss_account: Number(schemeForm.accountId),
        config: kind === 'passive_resume'
          ? { reply_message: '您好，这边是招聘岗位，方便发送一份简历进一步沟通吗？' }
          : { source: schemeForm.source, keyword: schemeForm.keyword, target_resume_count: Number(schemeForm.target), max_scan_count: Number(schemeForm.maxScan) },
      }),
    })
    const enabled = await api(`recruitment/workflow-versions/${created.version.id}/enable/`, { method: 'POST' })
    activeRun.value = await api(`recruitment/workflow-versions/${enabled.id}/run/`, {
      method: 'POST',
      body: JSON.stringify({ mode: 'formal', request_id: requestId(), job: Number(schemeForm.jobId), input: {}, confirm: true }),
    })
    schemeModal.value = ''
    workspaceTab.value = 'workflows'
    await loadWorkspace({ silent: true })
    scheduleRunPolling()
  } catch (err) { error.value = err.message }
  finally { schemeSaving.value = false }
}

async function resolveAttention(item) {
  try {
    await api(`recruitment/human-attentions/${item.id}/resolve/`, { method: 'POST', body: JSON.stringify({ note: 'HR 已在工作台处理' }) })
    attentions.value = attentions.value.filter((entry) => entry.id !== item.id)
  } catch (err) { error.value = err.message }
}

async function disposeCampaign(campaign) {
  try {
    if (['queued', 'running', 'paused'].includes(campaign.status)) {
      await api(`recruitment/search-campaigns/${campaign.id}/stop/`, { method: 'POST' })
    } else {
      await api(`recruitment/search-campaigns/${campaign.id}/`, { method: 'DELETE' })
    }
    campaigns.value = listItems(await api('recruitment/search-campaigns/'))
  } catch (err) { error.value = err.message }
}

function campaignProgress(campaign) {
  if (!campaign.max_scan_count) return 0
  return Math.min(100, Math.round((campaign.scanned_count / campaign.max_scan_count) * 100))
}

const schemeJobs = computed(() => openJobs.value.filter((job) => String(job.boss_account) === String(schemeForm.accountId)))

function menuActionLabel(account, actionName) {
  if (actionName === 'archive_account') return '移除账号'
  if (actionName === 'restore_account') return '恢复账号'
  return accountActionLabel(account, actionName)
}

async function createAccount() {
  saving.value = true
  error.value = ''
  try {
    await api('recruitment/boss-accounts/', {
      method: 'POST',
      body: JSON.stringify({ name: form.name, browser_type: form.browser_type, daily_contact_limit: 50, active: true }),
    })
    accountModalOpen.value = false
    form.name = ''
    await loadWorkspace()
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}

async function runAction(account, actionName) {
  closeActionMenu()
  if (actionName === 'restore_account') {
    await restoreLifecycle('boss-accounts', account.id)
    return
  }
  if (actionName === 'archive_account') {
    lifecycleTarget.value = { kind: 'account', id: account.id, name: account.name, title: '移除 BOSS 账号', actionLabel: '确认移除', description: '账号会停用并从当前列表移除，隔离浏览器目录与历史任务保留，可从归档记录恢复。' }
    return
  }
  if (actionName === 'check_status') {
    error.value = ''
    try {
      await api(`recruitment/boss-accounts/${account.id}/check-status/`, { method: 'POST' })
      await loadWorkspace({ silent: true })
    } catch (err) {
      error.value = err.message
    }
    return
  }
  const action = actionName === 'open_login' ? 'check_status' : actionName
  const requestPayload = actionName === 'open_login' ? { open_login: true } : {}
  error.value = ''
  try {
    await api('recruitment/rpa-tasks/', {
      method: 'POST',
      body: JSON.stringify({ boss_account: account.id, action, request_payload: requestPayload }),
    })
    await loadWorkspace()
  } catch (err) {
    error.value = err.message
  }
}

async function saveWorkflow(snapshot) {
  workflowSaving.value = true; error.value = ''
  try {
    let templateId = snapshot.templateId
    if (!templateId) {
      const template = await api('recruitment/workflows/', {
        method: 'POST', body: JSON.stringify({ name: snapshot.name, description: '由招聘自动化工作台创建' }),
      })
      templateId = template.id
    }
    await api('recruitment/workflow-versions/', {
      method: 'POST', body: JSON.stringify({ template: templateId, boss_account: snapshot.accountId, nodes: snapshot.nodes, edges: snapshot.edges }),
    })
    await loadWorkspace({ silent: true })
    workflowEditorSnapshot.value = { ...snapshot, templateId }
    workflowEditorKey.value += 1
  } catch (err) { error.value = err.message }
  finally { workflowSaving.value = false }
}

async function restoreLifecycle(resource, id) {
  error.value = ''
  try {
    await api(`recruitment/${resource}/${id}/restore/?archived=1`, { method: 'POST' })
    await loadWorkspace({ silent: true })
  } catch (err) { error.value = err.message }
}

async function toggleArchiveView() {
  showArchived.value = !showArchived.value
  actionMenu.value = null
  selectedTask.value = null
  await loadWorkspace()
}

function requestTaskArchive(task) {
  lifecycleTarget.value = { kind: 'task', id: task.id, name: `${task.account_name} · ${actionLabels[task.action] || task.action}`, title: '归档自动化任务', actionLabel: '确认归档', description: '任务会从最近任务中隐藏，执行结果、事件与审计记录仍会保留。' }
}

function requestWorkflowDisposal(version) {
  const template = workflows.value.find((item) => item.id === version.template)
  lifecycleTarget.value = version.status === 'draft'
    ? { kind: 'workflow_version', id: version.id, name: `${template?.name || '招聘流程'} · 版本 ${version.version}`, title: '删除流程草稿', actionLabel: '确认删除草稿', description: '该草稿尚未启用，可以直接删除；已启用和历史版本不会受影响。' }
    : { kind: 'workflow_template', id: version.template, name: template?.name || '招聘流程', title: '归档招聘流程', actionLabel: '确认归档', description: '流程会停止启用并从当前版本列表移除，历史版本与审计信息仍会保留。' }
}

async function confirmLifecycle() {
  const target = lifecycleTarget.value
  if (!target) return
  lifecycleSaving.value = true; error.value = ''
  try {
    if (target.kind === 'workflow_version') {
      await api(`recruitment/workflow-versions/${target.id}/`, { method: 'DELETE' })
    } else {
      const resource = { account: 'boss-accounts', task: 'rpa-tasks', workflow_template: 'workflows' }[target.kind]
      await api(`recruitment/${resource}/${target.id}/archive/`, { method: 'POST' })
    }
    lifecycleTarget.value = null
    selectedTask.value = null
    await loadWorkspace({ silent: true })
  } catch (err) { error.value = err.message }
  finally { lifecycleSaving.value = false }
}

function editWorkflowVersion(version) {
  const template = workflows.value.find((item) => item.id === version.template)
  workflowEditorSnapshot.value = {
    templateId: version.template,
    name: template?.name || `流程 ${version.template}`,
    accountId: version.boss_account,
    nodes: version.nodes,
    edges: version.edges,
  }
  workflowEditorKey.value += 1
}

function newWorkflow() {
  workflowEditorSnapshot.value = null
  workflowEditorKey.value += 1
}

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `run-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function stopRunPolling() {
  if (runPollTimer) window.clearTimeout(runPollTimer)
  runPollTimer = null
}

function scheduleRunPolling() {
  stopRunPolling()
  if (!activeRun.value || ['succeeded', 'failed', 'cancelled'].includes(activeRun.value.status)) return
  runPollTimer = window.setTimeout(refreshRun, 2000)
}

async function refreshRun() {
  if (!activeRun.value) return
  try { activeRun.value = await api(`recruitment/workflow-runs/${activeRun.value.id}/`) }
  catch (err) { error.value = err.message }
  scheduleRunPolling()
}

async function createWorkflowRun(version, mode, jobId = '') {
  runBusy.value = true; error.value = ''
  try {
    activeRun.value = await api(`recruitment/workflow-versions/${version.id}/run/`, {
      method: 'POST',
      body: JSON.stringify({ mode, request_id: requestId(), job: jobId ? Number(jobId) : null, input: {}, confirm: mode === 'formal' }),
    })
    formalVersion.value = null
    scheduleRunPolling()
  } catch (err) { error.value = err.message }
  finally { runBusy.value = false }
}

function dryRun(version) { createWorkflowRun(version, 'dry_run') }

async function openFormalRun(version) {
  formalVersion.value = version; formalJobId.value = ''; error.value = ''
  try {
    formalJobs.value = listItems(await api('recruitment/jobs/')).filter((job) => String(job.boss_account) === String(version.boss_account) && job.status === 'open')
    formalJobId.value = formalJobs.value[0] ? String(formalJobs.value[0].id) : ''
  } catch (err) { error.value = err.message }
}

async function runControl(action, payload = {}) {
  if (!activeRun.value) return
  runBusy.value = true; error.value = ''
  try {
    activeRun.value = await api(`recruitment/workflow-runs/${activeRun.value.id}/${action}/`, { method: 'POST', body: JSON.stringify(payload) })
    scheduleRunPolling()
  } catch (err) { error.value = err.message }
  finally { runBusy.value = false }
}

function decideRunNode({ nodeId, approved }) { runControl('decision', { node_id: nodeId, approved, note: approved ? 'HR 在工作台确认通过' : 'HR 在工作台选择跳过' }) }
function retryRunNode(nodeId) { runControl('retry', { node_id: nodeId }) }

async function enableWorkflow(versionId) {
  error.value = ''
  try { await api(`recruitment/workflow-versions/${versionId}/enable/`, { method: 'POST' }); await loadWorkspace({ silent: true }) }
  catch (err) { error.value = err.message }
}

function toggleActionMenu(event, account) {
  if (actionMenu.value?.account.id === account.id) {
    closeActionMenu()
    return
  }
  const trigger = event.currentTarget
  const rect = trigger.getBoundingClientRect()
  const menuHeight = actionsFor(account).length * 34 + 14
  const below = rect.bottom + 8
  const top = below + menuHeight > window.innerHeight - 12
    ? Math.max(12, rect.top - menuHeight - 8)
    : below
  actionMenu.value = { account, left: rect.right, top }
}

function closeActionMenu() {
  actionMenu.value = null
}

function browserLabel(type) {
  return type === 'edge' ? 'Edge' : 'Chrome'
}

function formatDate(value) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '—'
}

onMounted(async () => {
  await loadWorkspace()
  refreshTimer = window.setInterval(() => loadWorkspace({ silent: true }), 5000)
  window.addEventListener('click', closeActionMenu)
  window.addEventListener('resize', closeActionMenu)
  window.addEventListener('scroll', closeActionMenu, true)
})
onUnmounted(() => {
  window.clearInterval(refreshTimer)
  stopRunPolling()
  window.removeEventListener('click', closeActionMenu)
  window.removeEventListener('resize', closeActionMenu)
  window.removeEventListener('scroll', closeActionMenu, true)
})
</script>

<template>
  <div class="page-stack automation-workspace">
    <header class="page-hero page-hero--compact">
      <div>
        <span class="eyebrow">BOSS Recruitment Automation</span>
        <h2>自动化任务</h2>
        <p>账号隔离、人工确认、逐人执行与结果留痕集中在同一工作区。</p>
      </div>
      <div class="recruitment-toolbar__actions"><button class="text-button" data-test="toggle-automation-archive" type="button" @click="toggleArchiveView">{{ showArchived ? '返回当前工作区' : '归档记录' }}</button><button v-if="!showArchived" class="text-button automation-add button-with-icon" type="button" @click="accountModalOpen = true"><AppIcon name="plus" :size="16" /><span>添加账号</span></button></div>
    </header>

    <p v-if="error" class="form-error">{{ error }}</p>

    <section class="panel automation-status" aria-label="运行状态">
      <div>
        <i :class="{ 'is-online': summary.worker?.status === 'online' }"></i>
        <span>本机 Worker</span>
        <strong>{{ summary.worker?.hostname || '尚未连接' }}</strong>
      </div>
      <div>
        <span>BOSS CLI</span>
        <strong>{{ summary.cli_available ? (summary.worker?.version || '已就绪') : '未检测到' }}</strong>
      </div>
      <div>
        <span>本次接入范围</span>
        <strong>发现 · 沟通 · 简历 · 流程</strong>
      </div>
      <div>
        <span>已完成任务</span>
        <strong>{{ completedCount }}</strong>
      </div>
    </section>

    <nav class="automation-workspace-tabs" aria-label="自动化工作区"><button :class="{ active: workspaceTab === 'accounts' }" @click="workspaceTab = 'accounts'">账号与任务</button><button :class="{ active: workspaceTab === 'batches' }" @click="workspaceTab = 'batches'">确认执行 <span>{{ batches.length }}</span></button><button :class="{ active: workspaceTab === 'workflows' }" @click="workspaceTab = 'workflows'">流程编排 <span>{{ workflowVersions.length }}</span></button></nav>

    <template v-if="workspaceTab === 'accounts'">
    <section class="automation-command-center" aria-label="标准自动化方案">
      <div class="automation-scheme-stage">
        <header><div><span class="panel-kicker">STANDARD OPERATIONS</span><h3>从结果出发</h3></div><p>选择标准方案即可运行，高级画布留给需要改节点的场景。</p></header>
        <div class="automation-scheme-grid">
          <button class="automation-scheme-card is-passive" type="button" @click="openScheme('passive_resume')">
            <i><AppIcon name="workflow" :size="22" /></i>
            <span><small>被动咨询</small><strong>同步消息并获取简历</strong><em>观望转人工，其余自动使用原生按钮索要简历</em></span>
            <AppIcon name="arrow-right" :size="18" />
          </button>
          <button class="automation-scheme-card is-active" type="button" @click="openScheme('active_resume_search')">
            <i><AppIcon name="search" :size="22" /></i>
            <span><small>主动寻访</small><strong>搜索、拉取并 AI 初筛</strong><em>按合格目标与 AI 分析上限执行，合格结果交给 HR 批量确认</em></span>
            <AppIcon name="arrow-right" :size="18" />
          </button>
        </div>
      </div>
      <aside class="automation-attention-rail">
        <header><div><span class="panel-kicker">HUMAN ATTENTION</span><h3>需要你处理</h3></div><span>{{ attentions.length }}</span></header>
        <div v-if="attentions.length" class="automation-attention-list">
          <article v-for="item in attentions.slice(0, 4)" :key="item.id">
            <i></i><div><strong>{{ item.title }}</strong><small>{{ item.job_title || item.account_name }} · {{ formatDate(item.created_at) }}</small></div>
            <button type="button" @click="resolveAttention(item)">完成</button>
          </article>
        </div>
        <div v-else class="automation-attention-empty"><AppIcon name="check-circle" :size="20" /><span>当前没有人工介入事项</span></div>
      </aside>
    </section>
    <section v-if="campaigns.length" class="automation-campaign-strip" aria-label="主动寻访运行记录">
      <article v-for="campaign in campaigns.slice(0, 4)" :key="campaign.id">
        <div class="automation-campaign-title"><i :class="`is-${campaign.status}`"></i><span><strong>{{ campaign.name }}</strong><small>{{ campaign.job_title }} · 目标合格 {{ campaign.target_resume_count }} 份</small></span></div>
        <div class="automation-campaign-meter"><span><i :style="{ width: `${campaignProgress(campaign)}%` }"></i></span><small>AI 已分析 {{ campaign.scanned_count }}/{{ campaign.max_scan_count }} · 合格 {{ campaign.qualified_resume_count || 0 }} · 已拉取 {{ campaign.pulled_resume_count }}</small></div>
        <button v-if="campaign.status !== 'succeeded'" type="button" @click="disposeCampaign(campaign)">{{ ['queued','running','analyzing','paused'].includes(campaign.status) ? '停止' : '删除' }}</button>
        <span v-else class="recruitment-chip">已完成</span>
      </article>
    </section>
    <section class="panel table-panel automation-panel automation-panel--accounts">
      <header class="panel__header panel__header--padded">
        <div><span class="panel-kicker">ISOLATED ACCOUNTS</span><h3>BOSS 账号</h3></div>
        <span>{{ accounts.length }} 个独立环境</span>
      </header>
      <div class="table-scroll">
        <table class="data-table automation-table">
          <thead><tr><th>账号</th><th>浏览器</th><th>登录状态</th><th>隔离环境</th><th>最近检查</th><th aria-label="操作"></th></tr></thead>
          <tbody>
            <tr v-for="account in accounts" :key="account.id">
              <td><strong>{{ account.name }}</strong><small class="block-text">账号配置 {{ account.active ? '启用' : '停用' }}</small></td>
              <td>{{ browserLabel(account.browser_type) }}</td>
              <td><span v-if="showArchived" class="status-badge">已归档</span><span v-else :class="['status-badge', `status-badge--${accountDisplayStatus(account)}`]">{{ loginStatusLabel(accountDisplayStatus(account)) }}</span></td>
              <td><span class="automation-mono">{{ account.browser_profile }}</span><small class="block-text">CDP {{ account.cdp_port }}</small></td>
              <td>{{ formatDate(account.last_checked_at) }}</td>
              <td class="automation-action-cell">
                <button
                  v-if="actionsFor(account).length"
                  class="automation-menu-trigger"
                  type="button"
                  aria-label="账号操作"
                  :aria-expanded="actionMenu?.account.id === account.id"
                  @click.stop="toggleActionMenu($event, account)"
                ><AppIcon name="more-horizontal" :size="19" /></button>
                <span v-else class="block-text">任务进行中</span>
              </td>
            </tr>
            <tr v-if="!loading && !accounts.length"><td colspan="6" class="table-empty">尚未添加 BOSS 账号</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel table-panel automation-panel automation-panel--tasks">
      <header class="panel__header panel__header--padded">
        <div><span class="panel-kicker">TASK TIMELINE</span><h3>最近任务</h3></div>
        <span>全部自动化操作留痕</span>
      </header>
      <div class="table-scroll">
        <table class="data-table data-table--dense">
          <thead><tr><th>账号</th><th>动作</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
          <tbody>
            <tr v-for="task in tasks" :key="task.id">
              <td><strong>{{ task.account_name }}</strong></td>
              <td>{{ actionLabels[task.action] || task.action }}</td>
              <td><span :class="['status-badge', `status-badge--${task.status}`]">{{ taskStatusLabels[task.status] || task.status }}</span></td>
              <td>{{ formatDate(task.created_at) }}</td>
              <td><button class="text-button" type="button" @click="selectedTask = task">查看记录</button><button v-if="showArchived" class="text-button task-archive-button" type="button" @click="restoreLifecycle('rpa-tasks', task.id)">恢复</button><button v-else-if="['waiting_human','succeeded','failed','cancelled'].includes(task.status)" class="danger-text-button task-archive-button" type="button" @click="requestTaskArchive(task)">归档</button></td>
            </tr>
            <tr v-if="!loading && !tasks.length"><td colspan="5" class="table-empty">暂无自动化任务</td></tr>
          </tbody>
        </table>
      </div>
    </section>
    </template>

    <section v-else-if="workspaceTab === 'batches'" class="automation-batch-workspace">
      <header><div><span class="panel-kicker">HUMAN APPROVED</span><h3>确认执行队列</h3></div><p>每位候选人独立执行；部分失败不会重复发送已成功项。</p></header>
      <div v-if="batches.length" class="automation-batch-grid"><AutomationBatchPanel v-for="batch in batches" :key="batch.id" :batch="batch" /></div>
      <div v-else class="automation-empty-state"><AppIcon name="shield" :size="25" /><strong>暂无待执行批次</strong><span>在候选人库勾选候选人后创建沟通批次。</span></div>
    </section>

    <section v-else class="workflow-workspace">
      <div class="workflow-main-column">
        <WorkflowCanvas v-if="!showArchived" :key="workflowEditorKey" :accounts="accounts" :saving="workflowSaving" :snapshot="workflowEditorSnapshot" :node-statuses="workflowNodeStatuses" @save="saveWorkflow" />
        <WorkflowRunPanel v-if="activeRun" :run="activeRun" :busy="runBusy" @close="activeRun = null; stopRunPolling()" @pause="runControl('pause')" @resume="runControl('resume')" @cancel="runControl('cancel')" @decision="decideRunNode" @retry="retryRunNode" />
      </div>
      <aside class="workflow-versions"><header><div><span class="panel-kicker">VERSION HISTORY</span><h3>{{ showArchived ? '已归档流程' : '流程版本' }}</h3></div><button v-if="!showArchived" class="text-button" type="button" @click="newWorkflow">新建</button></header><article v-for="version in workflowVersions" :key="version.id"><div><strong>{{ workflows.find((item) => item.id === version.template)?.name || `流程 ${version.template}` }}</strong><small>版本 {{ version.version }} · {{ version.nodes.length }} 个节点</small></div><span :class="['recruitment-chip', { 'is-draft': version.status === 'draft' }]">{{ version.status === 'enabled' ? '已启用' : version.status === 'draft' ? '草稿' : '已停用' }}</span><button v-if="showArchived" class="text-button" type="button" @click="restoreLifecycle('workflows', version.template)">恢复流程</button><template v-else><div class="workflow-version-run-actions"><button class="text-button" type="button" :data-test="`dry-run-${version.id}`" :disabled="runBusy" @click="dryRun(version)">试运行</button><button class="primary-button" type="button" :data-test="`formal-run-${version.id}`" :disabled="version.status !== 'enabled' || accounts.find((item) => item.id === version.boss_account)?.login_status !== 'ready' || runBusy" @click="openFormalRun(version)">正式运行</button></div><button class="text-button" type="button" :data-test="`edit-workflow-version-${version.id}`" @click="editWorkflowVersion(version)">基于此版本编排</button><button v-if="version.status === 'draft'" class="text-button" @click="enableWorkflow(version.id)">校验并启用</button><button class="danger-text-button" type="button" :data-test="`dispose-workflow-version-${version.id}`" @click="requestWorkflowDisposal(version)">{{ version.status === 'draft' ? '删除草稿' : '归档流程' }}</button></template></article><p v-if="!workflowVersions.length" class="table-empty">{{ showArchived ? '暂无已归档流程' : '保存后会在这里生成不可变版本。' }}</p></aside>
    </section>

    <Teleport to="body">
      <Transition name="automation-menu-fade">
        <div
          v-if="actionMenu"
          class="automation-menu-popover"
          :style="{ position: 'fixed', left: `${actionMenu.left}px`, top: `${actionMenu.top}px` }"
          @click.stop
        >
          <button
            v-for="actionName in actionsFor(actionMenu.account)"
            :key="actionName"
            type="button"
            @click="runAction(actionMenu.account, actionName)"
          >{{ menuActionLabel(actionMenu.account, actionName) }}</button>
        </div>
      </Transition>
    </Teleport>

    <ModalPanel v-if="accountModalOpen" title="添加 BOSS 账号" @close="accountModalOpen = false">
      <form id="boss-account-form" class="form-grid" @submit.prevent="createAccount">
        <label class="field-label field-label--full">账号名称<input v-model.trim="form.name" required maxlength="100" placeholder="例如：北京招聘主账号" /></label>
        <label class="field-label field-label--full">隔离浏览器<select v-model="form.browser_type"><option value="edge">Microsoft Edge</option><option value="chrome">Google Chrome</option></select><small>系统自动分配独立目录和端口，不会使用日常浏览器资料。</small></label>
      </form>
      <template #footer><button class="secondary-button" type="button" @click="accountModalOpen = false">取消</button><button class="primary-button" type="submit" form="boss-account-form" :disabled="saving">{{ saving ? '保存中…' : '保存账号' }}</button></template>
    </ModalPanel>

    <ModalPanel v-if="selectedTask" title="任务记录" @close="selectedTask = null">
      <div class="automation-task-detail">
        <div><span>账号</span><strong>{{ selectedTask.account_name }}</strong></div>
        <div><span>动作</span><strong>{{ actionLabels[selectedTask.action] || selectedTask.action }}</strong></div>
        <div><span>状态</span><strong>{{ taskStatusLabels[selectedTask.status] || selectedTask.status }}</strong></div>
        <ol v-if="selectedTask.events?.length"><li v-for="event in selectedTask.events" :key="event.id"><time>{{ formatDate(event.created_at) }}</time><span>{{ event.message }}</span></li></ol>
        <p v-else class="table-empty">暂无更多事件</p>
      </div>
    </ModalPanel>
    <ModalPanel v-if="formalVersion" title="确认正式运行" @close="formalVersion = null">
      <div class="workflow-formal-confirm">
        <div class="communication-intro"><i><AppIcon name="shield" :size="20" /></i><div><strong>{{ workflows.find((item) => item.id === formalVersion.template)?.name || '招聘流程' }} · 版本 {{ formalVersion.version }}</strong><p>读取节点交给本机 Worker；画布中的人工节点会暂停等待 HR，当前阶段不执行面试邀约。</p></div></div>
        <label class="field-label field-label--full">执行职位<select v-model="formalJobId" data-test="formal-run-job"><option value="">请选择职位</option><option v-for="job in formalJobs" :key="job.id" :value="String(job.id)">{{ job.title }}</option></select></label>
        <p v-if="!formalJobs.length" class="form-error">当前账号没有可用的在招职位，请先同步职位。</p>
      </div>
      <template #footer><button class="secondary-button" type="button" @click="formalVersion = null">取消</button><button class="primary-button" data-test="confirm-formal-run" type="button" :disabled="!formalJobId || runBusy" @click="createWorkflowRun(formalVersion, 'formal', formalJobId)">{{ runBusy ? '创建中…' : '确认并开始' }}</button></template>
    </ModalPanel>
    <ModalPanel v-if="schemeModal" :title="schemeModal === 'passive_resume' ? '运行被动咨询方案' : '运行主动寻访方案'" @close="schemeModal = ''">
      <form id="standard-scheme-form" class="form-grid automation-scheme-form" @submit.prevent="saveAndRunScheme">
        <div class="automation-scheme-note field-label--full"><AppIcon :name="schemeModal === 'passive_resume' ? 'workflow' : 'search'" :size="20" /><p><strong>{{ schemeModal === 'passive_resume' ? '完整消息同步 → 意图规则 → 原生求简历' : '搜索候选人 → 拉取在线简历 → AI 初筛 → HR 批量打招呼' }}</strong><span>系统会保存一份可追溯的流程版本，并立即按该版本运行。</span></p></div>
        <label class="field-label">执行账号<select v-model="schemeForm.accountId" required @change="schemeForm.jobId = schemeJobs[0]?.id || ''"><option value="">请选择</option><option v-for="account in accounts" :key="account.id" :value="account.id" :disabled="account.login_status !== 'ready'">{{ account.name }}{{ account.login_status === 'ready' ? '' : '（未登录）' }}</option></select></label>
        <label class="field-label">执行职位<select v-model="schemeForm.jobId" required><option value="">请选择</option><option v-for="job in schemeJobs" :key="job.id" :value="job.id">{{ job.title }}</option></select></label>
        <template v-if="schemeModal === 'passive_resume'">
          <label class="field-label field-label--full">消息同步间隔<select v-model.number="schemeForm.interval"><option :value="1">每 1 分钟</option><option :value="2">每 2 分钟</option><option :value="5">每 5 分钟</option><option :value="15">每 15 分钟</option><option :value="60">每小时</option><option :value="1440">每天</option></select><small>登录会话保存在账号独立浏览器环境中，无需每次重新登录。</small></label>
        </template>
        <template v-else>
          <label class="field-label">搜索来源<select v-model="schemeForm.source"><option value="search">常规搜索</option><option value="recommend">推荐牛人</option><option value="deep_search">深度搜索</option></select></label>
          <label class="field-label">搜索关键词<input v-model.trim="schemeForm.keyword" maxlength="20" placeholder="例如：Python" /></label>
          <label class="field-label">目标合格简历数<input v-model.number="schemeForm.target" type="number" min="1" max="100" /></label>
          <label class="field-label">AI 最大分析份数<input v-model.number="schemeForm.maxScan" type="number" :min="schemeForm.target" max="100" /></label>
        </template>
      </form>
      <template #footer><button class="secondary-button" type="button" @click="schemeModal = ''">取消</button><button class="primary-button" type="submit" form="standard-scheme-form" :disabled="schemeSaving || !schemeForm.jobId">{{ schemeSaving ? '正在创建并运行…' : '确认运行' }}</button></template>
    </ModalPanel>
    <ArchiveConfirmModal v-if="lifecycleTarget" :title="lifecycleTarget.title" :name="lifecycleTarget.name" :description="lifecycleTarget.description" :action-label="lifecycleTarget.actionLabel" :saving="lifecycleSaving" @close="lifecycleTarget = null" @confirm="confirmLifecycle" />
  </div>
</template>
