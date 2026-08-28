<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'
import RecruitmentResultsNavigation from '@/components/RecruitmentResultsNavigation.vue'
import RecruitmentResultsView from './RecruitmentResultsView.vue'

const route = useRoute()
const router = useRouter()
const plan = ref(null)
const task = ref(null)
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const busy = ref('')
const archiveRequested = ref(false)
const pendingResumeApprovals = ref([])
const approvalInboxLoading = ref(false)
const approvalInboxError = ref('')
const approvalActionId = ref('')
const approvalNotice = ref('')
let pollTimer = null
let loadSequence = 0
let approvalLoadSequence = 0
let componentAlive = true

const planId = computed(() => String(route.params.planId || ''))
const isCurrentTask = computed(() => (
  !task.value
  || task.value.automation_plan_current_run
  || String(task.value.id) === String(plan.value?.current_run?.id || '')
))
const state = computed(() => {
  if (task.value?.archived_at) return 'archived'
  const value = String(
    (isCurrentTask.value ? plan.value?.effective_state : null)
      || task.value?.automation_plan_effective_state
      || task.value?.status
      || plan.value?.actual_state
      || plan.value?.current_run?.status
      || plan.value?.desired_state
      || '',
  )
  return {
    queued: 'starting',
    pending: 'starting',
    succeeded: 'completed',
    cancelled: 'stopped',
  }[value] || value || 'stopped'
})
const stateLabel = computed(() => ({
  starting: '正在开启',
  running: '运行中',
  waiting_human: '等待人工处理',
  paused: '已暂停',
  pausing: '正在暂停',
  stopping: '正在停止',
  stopped: '已停止',
  failed: '运行失败',
  completed: '本轮已完成',
  archived: '已删除',
}[state.value] || '状态同步中'))
const stateHint = computed(() => ({
  starting: '服务端正在创建本轮运行，结果会在下方自动刷新。',
  running: '任务正在执行；停止后不会再开始下一项外部动作。',
  waiting_human: '任务正在等待 HR 确认或处理风控事项。',
  paused: '当前不会领取新的执行步骤，可继续或停止任务。',
  pausing: '暂停指令已提交，正在等待当前动作安全收口。',
  stopping: '停止指令已生效，已进入浏览器的单个动作会安全收尾。',
  stopped: '任务已停止，不会再产生新的自动化动作。',
  failed: '本轮已结束，可检查失败原因后修改或重新开启。',
  completed: '本轮已完成，结果和运行证据已保留。',
  archived: '任务已从当前列表移除；历史结果和审计证据仍然保留。',
}[state.value] || '正在从服务端同步任务状态。'))
const active = computed(() => ['starting', 'running', 'waiting_human'].includes(state.value))
const terminal = computed(() => ['stopped', 'failed', 'completed'].includes(state.value))
const revisionLabel = computed(() => {
  const revision = task.value?.automation_plan_revision_number || plan.value?.current_revision?.revision
  return revision ? `方案 V${revision}` : '尚未生成方案版本'
})
const runLabel = computed(() => task.value?.id || plan.value?.current_run?.id
  ? `运行 #${String(task.value?.id || plan.value.current_run.id).slice(0, 8)}`
  : '暂无运行编号')
const taskKind = computed(() => task.value?.automation_plan_kind || plan.value?.kind)
const kindLabel = computed(() => taskKind.value === 'passive_resume' ? '被动咨询与简历获取' : '主动搜索并拉取简历')
const passiveStartAuthorized = computed(() => (
  isCurrentTask.value
  && plan.value?.kind === 'passive_resume'
  && plan.value?.current_revision?.config?.execution_authorization?.source === 'plan_start'
  && plan.value.current_revision.config.execution_authorization.actions?.includes('request_resume')
))
const monitoring = computed(() => isCurrentTask.value && plan.value?.kind === 'passive_resume' ? plan.value?.monitoring : null)
const monitoringHasFailures = computed(() => (
  Number(monitoring.value?.message_failed_count || 0) > 0
  || Number(monitoring.value?.attachment_failed_count || 0) > 0
  || ['failed', 'waiting_human'].includes(String(monitoring.value?.status || ''))
))
const monitoringHint = computed(() => {
  if (!monitoring.value) return '正在等待首次检查；系统会按方案间隔持续监听当前岗位的新咨询。'
  if (Number(monitoring.value.attachment_failed_count || 0) > 0) {
    return '候选人消息已保留，但附件状态尚未核验；系统已禁止自动求简历，请等待安全重试或人工处理。'
  }
  if (Number(monitoring.value.message_failed_count || 0) > 0) {
    return '发现了候选人会话，但消息读取失败；本轮没有进入意图判断，也没有执行外发。'
  }
  if (Number(monitoring.value.discovered_count || 0) === 0) {
    return '本轮没有可处理的新咨询，系统会继续按设置的间隔检查。'
  }
  return `本轮发现 ${Number(monitoring.value.discovered_count || 0)} 条，已安全处理 ${Number(monitoring.value.synced_count || 0)} 条。`
})
const approvalInboxVisible = computed(() => (
  isCurrentTask.value
  && plan.value?.kind === 'passive_resume'
  && !passiveStartAuthorized.value
  && ['starting', 'running', 'waiting_human'].includes(state.value)
))
const tasksTo = { name: 'recruitment-tasks' }

function requestId() {
  return globalThis.crypto?.randomUUID?.()
    || `00000000-0000-4000-8000-${Date.now().toString().padStart(12, '0').slice(-12)}`
}

function approvalCandidate(approval) {
  return approval?.payload?.items?.[0] || {}
}

function approvalExpiry(value) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

async function loadPendingResumeApprovals(currentPlan = plan.value) {
  const sequence = ++approvalLoadSequence
  const revisionId = currentPlan?.current_revision?.id
  const generation = Number(currentPlan?.control_generation || 0)
  if (!componentAlive || !approvalInboxVisible.value || !revisionId || generation < 1) {
    pendingResumeApprovals.value = []
    approvalInboxError.value = ''
    approvalInboxLoading.value = false
    return []
  }
  approvalInboxLoading.value = true
  try {
    const query = new URLSearchParams({
      status: 'draft',
      action: 'request_resume',
      job: String(currentPlan.job),
      automation_plan_revision: String(revisionId),
      automation_generation: String(generation),
    })
    const payload = await api(`recruitment/automation-approvals/?${query.toString()}`)
    const approvals = listItems(payload)
    if (componentAlive && sequence === approvalLoadSequence && String(plan.value?.id) === String(currentPlan.id)) {
      pendingResumeApprovals.value = approvals
      approvalInboxError.value = ''
    }
    return approvals
  } catch (error) {
    if (sequence === approvalLoadSequence) approvalInboxError.value = error.message || '待确认消息读取失败'
    return []
  } finally {
    if (sequence === approvalLoadSequence) approvalInboxLoading.value = false
  }
}

async function approveResumeRequest(approval) {
  if (!approval?.id || approvalActionId.value || busy.value) return
  approvalActionId.value = String(approval.id)
  approvalInboxError.value = ''
  approvalNotice.value = ''
  try {
    const approved = await api(`recruitment/automation-approvals/${encodeURIComponent(approval.id)}/approve/`, {
      method: 'POST',
      body: '{}',
    })
    const executableStep = approved?.batch?.steps?.some((step) => step.status === 'pending')
    if (!approved?.batch?.id || !executableStep) {
      throw new Error('服务端尚未创建可执行发送步骤，请勿停止任务并刷新后重试')
    }
    const candidate = approvalCandidate(approval)
    pendingResumeApprovals.value = pendingResumeApprovals.value.filter((item) => String(item.id) !== String(approval.id))
    approvalNotice.value = `${candidate.name || '候选人'}的发送批次已创建；请保持任务运行，Worker 将先发送话术，再点击“求简历”。`
  } catch (error) {
    await loadPendingResumeApprovals()
    approvalInboxError.value = error.message || '确认发送失败，请刷新后重试'
  } finally {
    approvalActionId.value = ''
  }
}

function sameQueryValue(left, right) {
  return String(left || '') === String(right || '')
}

function syncRouteContext(value) {
  if (!value) return
  const selectedRunId = task.value?.id || route.query.run || value.current_run?.id
  const next = {
    ...route.query,
    job: String(value.job),
    run: selectedRunId ? String(selectedRunId) : undefined,
    view: route.query.view || 'tasks',
  }
  if (task.value?.archived_at || value.archived_at) next.status = 'archived'
  else if (next.status === 'archived') delete next.status
  if (
    sameQueryValue(route.query.job, next.job)
    && sameQueryValue(route.query.run, next.run)
    && sameQueryValue(route.query.view, next.view)
    && sameQueryValue(route.query.status, next.status)
  ) return
  router.replace({ name: route.name, params: route.params, query: next }).catch(() => {})
}

async function fetchPlan() {
  const id = planId.value
  if (!id) throw new Error('任务标识无效')
  const preferArchived = Boolean(plan.value?.archived_at) || route.query.status === 'archived'
  const paths = preferArchived
    ? [`recruitment/automation-plans/${encodeURIComponent(id)}/?archived=1`, `recruitment/automation-plans/${encodeURIComponent(id)}/`]
    : [`recruitment/automation-plans/${encodeURIComponent(id)}/`, `recruitment/automation-plans/${encodeURIComponent(id)}/?archived=1`]
  let lastError = null
  for (const path of paths) {
    try {
      return await api(path)
    } catch (error) {
      lastError = error
      if (error.status !== 404) throw error
    }
  }
  throw lastError || new Error('招聘任务不存在或无权访问')
}

async function fetchTask(currentPlan) {
  const id = route.query.run || currentPlan?.current_run?.id
  if (!id) return null
  const value = await api(`recruitment/workflow-runs/${encodeURIComponent(id)}/`)
  if (String(value?.automation_plan || '') !== planId.value) {
    throw new Error('该运行不属于当前招聘任务')
  }
  return value
}

async function loadPlan({ silent = false } = {}) {
  const sequence = ++loadSequence
  if (!silent) loading.value = true
  try {
    const value = await fetchPlan()
    const selectedTask = await fetchTask(value)
    if (!componentAlive || sequence !== loadSequence) return
    plan.value = value
    task.value = selectedTask
    loadError.value = ''
    syncRouteContext(value)
    await loadPendingResumeApprovals(value)
  } catch (error) {
    if (sequence === loadSequence) loadError.value = error.message || '任务详情读取失败'
  } finally {
    if (!silent && sequence === loadSequence) loading.value = false
  }
}

async function controlPlan(action) {
  if (!plan.value?.id || busy.value) return false
  busy.value = action
  actionError.value = ''
  try {
    const updated = await api(`recruitment/automation-plans/${plan.value.id}/${action}/`, {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId(),
        expected_control_version: Number(plan.value.control_version || 0),
      }),
    })
    plan.value = updated
    if (updated.current_run?.id && String(updated.current_run.id) !== String(task.value?.id || '')) {
      task.value = null
      await router.replace({
        name: route.name,
        params: route.params,
        query: { ...route.query, run: String(updated.current_run.id), status: undefined },
      })
      await loadPlan({ silent: true })
      return true
    }
    syncRouteContext(updated)
    await loadPendingResumeApprovals(updated)
    return true
  } catch (error) {
    if (error.status === 409) await loadPlan({ silent: true })
    actionError.value = error.message || '任务控制失败，请刷新后重试'
    return false
  } finally {
    busy.value = ''
  }
}

async function modifyPlan() {
  if (active.value || state.value === 'paused') {
    const stopped = await controlPlan('stop')
    if (!stopped) return
  }
  await router.push({
    name: 'recruitment-workbench',
    query: { job: String(plan.value.job), editPlan: String(plan.value.id), step: 'standard' },
  })
}

async function restartPlan() {
  if (!plan.value?.current_revision || busy.value) return
  busy.value = 'restart'
  actionError.value = ''
  const revision = plan.value.current_revision
  const command = {
    job: Number(plan.value.job),
    kind: plan.value.kind,
    config: revision.config,
    request_id: requestId(),
    expected_control_version: Number(plan.value.control_version || 0),
  }
  if (revision.workflow_mode === 'custom') command.workflow_version = Number(revision.workflow_version)
  try {
    const updated = await api('recruitment/automation-plans/start/', {
      method: 'POST',
      body: JSON.stringify(command),
    })
    plan.value = updated
    task.value = null
    await router.replace({
      name: route.name,
      params: route.params,
      query: { ...route.query, run: String(updated.current_run.id), status: undefined },
    })
    await loadPlan({ silent: true })
  } catch (error) {
    if (error.status === 409) await loadPlan({ silent: true })
    actionError.value = error.message || '任务重新开启失败，请刷新后重试'
  } finally {
    busy.value = ''
  }
}

async function archiveTask() {
  if (!task.value?.id || busy.value) return
  busy.value = 'archive'
  actionError.value = ''
  try {
    task.value = await api(`recruitment/workflow-runs/${encodeURIComponent(task.value.id)}/archive/`, { method: 'POST' })
    archiveRequested.value = false
    syncRouteContext(plan.value)
    await loadPendingResumeApprovals(plan.value)
  } catch (error) {
    if (error.status === 409) await loadPlan({ silent: true })
    actionError.value = error.message || '任务删除失败，请刷新后重试'
  } finally {
    busy.value = ''
  }
}

async function restoreTask() {
  if (!task.value?.id || busy.value) return
  busy.value = 'restore'
  actionError.value = ''
  try {
    task.value = await api(`recruitment/workflow-runs/${encodeURIComponent(task.value.id)}/restore/?automation_plan=1&archived=1`, { method: 'POST' })
    syncRouteContext(plan.value)
    await loadPendingResumeApprovals(plan.value)
  } catch (error) {
    actionError.value = error.message || '任务恢复失败，请刷新后重试'
  } finally {
    busy.value = ''
  }
}

onMounted(async () => {
  await loadPlan()
  pollTimer = globalThis.setInterval(() => {
    if (!busy.value) loadPlan({ silent: true })
  }, 5000)
})

onUnmounted(() => {
  componentAlive = false
  loadSequence += 1
  approvalLoadSequence += 1
  if (pollTimer) globalThis.clearInterval(pollTimer)
  pollTimer = null
})
</script>

<template>
  <div class="page-stack task-detail">
    <RecruitmentResultsNavigation />
    <section v-if="loading" class="task-detail-card task-detail-loading" data-test="task-detail-loading" aria-live="polite">
      <span></span><span></span><span></span>
      <p>正在从服务端恢复招聘任务与运行结果…</p>
    </section>

    <section v-else-if="loadError && !plan" class="task-detail-card task-detail-error" data-test="task-detail-error">
      <AppIcon name="alert-circle" :size="25" />
      <div><strong>任务详情暂时无法加载</strong><p>{{ loadError }}</p></div>
      <button class="secondary-button" type="button" @click="loadPlan()">重新加载</button>
      <RouterLink class="secondary-button" :to="tasksTo">返回招聘任务</RouterLink>
    </section>

    <template v-else-if="plan">
      <header class="task-detail-hero">
        <div class="task-detail-heading">
          <nav aria-label="面包屑">
            <RouterLink :to="tasksTo"><AppIcon name="chevron-left" :size="12" />招聘任务</RouterLink>
            <span>/</span><span>任务详情</span>
          </nav>
          <div class="task-detail-title-row">
            <div><h2>{{ plan.job_title }}</h2><p>{{ kindLabel }} · {{ revisionLabel }} · {{ runLabel }}</p></div>
            <span :class="['task-state', `is-${state}`]" data-test="task-state"><i></i>{{ stateLabel }}</span>
          </div>
        </div>
        <div class="task-detail-actions">
          <RouterLink class="task-button" :to="{ name: 'recruitment-workbench', query: { new: '1' } }"><AppIcon name="plus" :size="15" />继续创建任务</RouterLink>
          <button v-if="isCurrentTask && active" class="task-button" type="button" :disabled="Boolean(busy)" data-test="stop-modify-task" @click="modifyPlan">{{ busy === 'stop' ? '正在停止…' : '停止并修改' }}</button>
          <button v-if="isCurrentTask && (active || state === 'paused')" class="task-button is-danger" type="button" :disabled="Boolean(busy)" data-test="stop-task" @click="controlPlan('stop')">{{ busy === 'stop' ? '正在停止…' : '停止任务' }}</button>
          <button v-if="isCurrentTask && state === 'paused'" class="task-button" type="button" :disabled="Boolean(busy)" data-test="resume-task" @click="controlPlan('resume')">{{ busy === 'resume' ? '正在继续…' : '继续任务' }}</button>
          <button v-if="isCurrentTask && terminal" class="task-button" type="button" :disabled="Boolean(busy)" data-test="modify-task" @click="modifyPlan">修改任务</button>
          <button v-if="isCurrentTask && terminal" class="task-button is-primary" type="button" :disabled="Boolean(busy)" data-test="restart-task" @click="restartPlan">{{ busy === 'restart' ? '正在开启…' : '重新开启' }}</button>
          <button v-if="terminal" class="task-button is-danger-text" type="button" :disabled="Boolean(busy)" data-test="archive-task" @click="archiveRequested = true">删除任务</button>
          <button v-if="state === 'archived'" class="task-button is-primary" type="button" :disabled="Boolean(busy)" data-test="restore-task" @click="restoreTask">{{ busy === 'restore' ? '正在恢复…' : '恢复任务' }}</button>
          <button v-if="isCurrentTask && ['stopping', 'pausing'].includes(state)" class="task-button" type="button" disabled>正在等待安全收尾…</button>
        </div>
      </header>

      <section :class="['task-detail-card', 'task-status-card', `is-${state}`]">
        <div><span>当前状态</span><strong>{{ stateLabel }}</strong><p>{{ stateHint }}</p></div>
        <dl><div><dt>{{ isCurrentTask ? '控制版本' : '方案版本' }}</dt><dd>V{{ isCurrentTask ? plan.control_version : task?.automation_plan_revision_number }}</dd></div><div><dt>运行代际</dt><dd>{{ task?.automation_generation || plan.control_generation }}</dd></div><div><dt>最近更新</dt><dd>{{ new Date(task?.updated_at || plan.updated_at).toLocaleString('zh-CN', { hour12: false }) }}</dd></div></dl>
      </section>

      <section
        v-if="isCurrentTask && plan.kind === 'passive_resume' && !task?.archived_at"
        :class="['task-detail-card', 'task-monitoring-card', { 'has-warning': monitoringHasFailures }]"
        data-test="passive-monitoring"
        aria-live="polite"
      >
        <AppIcon :name="monitoringHasFailures ? 'alert-circle' : 'workflow'" :size="18" />
        <div><strong>{{ monitoringHasFailures ? '监听发现异常' : '持续监听新咨询' }}</strong><small>{{ monitoringHint }}</small></div>
        <dl v-if="monitoring">
          <div><dt>上次检查</dt><dd>{{ new Date(monitoring.last_checked_at).toLocaleString('zh-CN', { hour12: false }) }}</dd></div>
          <div><dt>发现 / 处理</dt><dd>{{ monitoring.discovered_count || 0 }} / {{ monitoring.synced_count || 0 }}</dd></div>
          <div><dt>异常</dt><dd>{{ Number(monitoring.message_failed_count || 0) + Number(monitoring.attachment_failed_count || 0) }}</dd></div>
        </dl>
      </section>

      <section v-if="passiveStartAuthorized && active" class="task-detail-card task-plan-authorization" data-test="plan-start-authorization">
        <AppIcon name="shield" :size="18" />
        <div><strong>开始执行已包含求简历授权</strong><small>系统会按本方案冻结的话术自动建立发送批次，不再要求 HR 重复确认；身份歧义、风控或外部结果不确定时仍会停止并转人工。</small></div>
      </section>

      <section v-else-if="approvalInboxVisible" class="task-detail-card task-approval-inbox" data-test="resume-approval-inbox" aria-live="polite">
        <header>
          <span><AppIcon name="workflow" :size="18" /></span>
          <div><strong>新消息待确认</strong><small>确认后才会给候选人发话术，并点击 BOSS“求简历”。</small></div>
          <em v-if="pendingResumeApprovals.length">{{ pendingResumeApprovals.length }} 条</em>
        </header>
        <p v-if="approvalInboxLoading && !pendingResumeApprovals.length">正在检查新消息…</p>
        <p v-else-if="!pendingResumeApprovals.length && !approvalInboxError">当前没有待确认的新消息，系统会按设置的间隔继续检查。</p>
        <article v-for="approval in pendingResumeApprovals" :key="approval.id" :data-test="`resume-approval-${approval.id}`">
          <div><strong>{{ approvalCandidate(approval).name || '候选人' }}</strong><small>{{ approvalCandidate(approval).job_title || plan.job_title }}<template v-if="approvalExpiry(approval.expires_at)"> · {{ approvalExpiry(approval.expires_at) }} 前确认</template></small></div>
          <blockquote>{{ approval.payload?.message }}</blockquote>
          <button type="button" :disabled="Boolean(approvalActionId) || Boolean(busy)" :data-test="`approve-resume-${approval.id}`" @click="approveResumeRequest(approval)">
            {{ approvalActionId === String(approval.id) ? '正在确认…' : '确认发送并求简历' }}
          </button>
        </article>
        <p v-if="approvalInboxError" class="task-action-error" role="alert">{{ approvalInboxError }}</p>
        <p v-if="approvalNotice" class="task-approval-notice" role="status">{{ approvalNotice }}</p>
      </section>

      <p v-if="actionError || loadError" class="task-action-error" role="alert"><AppIcon name="alert-circle" :size="15" />{{ actionError || loadError }}</p>
      <RecruitmentResultsView embedded :auto-refresh-ms="5000" />
    </template>

    <ArchiveConfirmModal
      v-if="archiveRequested && plan"
      title="删除招聘任务"
      :name="`${plan.job_title} · ${revisionLabel}`"
      description="仅这一次任务会从当前列表移除；其他任务卡、方案版本、运行结果、候选人、简历和审计证据都会保留。"
      action-label="确认删除任务"
      note="恢复这次任务只会让卡片重新可见，不会自动重新启动。"
      :saving="busy === 'archive'"
      @close="archiveRequested = false"
      @confirm="archiveTask"
    />
  </div>
</template>

<style scoped>
.task-detail {
  --task-font-family: var(--app-font-family);
  --task-ink: #0f172a;
  --task-slate: #334155;
  --task-muted: #64748b;
  --task-line: #e2e8f0;
  --task-paper: #ffffff;
  --task-soft: #f8faf9;
  --task-brand: #0f9f8f;
  --task-brand-dark: #087f73;
  --task-brand-soft: #eaf8f6;
  --task-warning: #d97706;
  --task-warning-soft: #fff7e3;
  --task-danger: #dc4a4a;
  --task-danger-soft: #fff0f2;
  --task-space-1: clamp(.3rem, .2rem + .1cqi, .45rem);
  --task-space-2: clamp(.55rem, .3rem + .3cqi, .85rem);
  --task-space-3: clamp(.8rem, .45rem + .42cqi, 1.1rem);
  --task-space-4: clamp(1.1rem, .6rem + .55cqi, 1.5rem);
  --task-space-5: clamp(1.5rem, .8rem + .75cqi, 2.1rem);
  --task-radius-control: clamp(.5625rem, .48rem + .06cqi, .75rem);
  --task-radius-panel: clamp(.9375rem, .78rem + .12cqi, 1.25rem);
  --task-transition: 180ms ease;
  gap: clamp(1.375rem, 1.1rem + .22vw, 1.75rem);
  width: 100%;
  min-width: 0;
  max-width: 100%;
  color: var(--task-ink);
  font-family: var(--task-font-family);
  container-name: task-detail;
  container-type: inline-size;
}

.task-detail *, .task-detail *::before, .task-detail *::after { box-sizing: border-box; }
.task-detail-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--task-space-5); }
.task-detail-heading { display: grid; gap: var(--task-space-3); min-width: 0; }
.task-detail-heading nav { display: flex; align-items: center; gap: var(--task-space-2); color: var(--task-muted); font-size: clamp(13px, .35rem + .45cqi, 16px); }
.task-detail-heading nav a { display: inline-flex; align-items: center; gap: 3px; color: var(--task-brand-dark); font-weight: 700; text-decoration: none; }
.task-detail-title-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--task-space-4); }
.task-detail-title-row > div { min-width: 0; }
.task-detail-title-row h2 { margin: 0; color: var(--task-ink); font-size: clamp(2rem, 1.05rem + 1.15cqi, 2.75rem); letter-spacing: -.03em; }
.task-detail-title-row p { margin: var(--task-space-1) 0 0; color: var(--task-muted); font-size: clamp(14px, .35rem + .55cqi, 18px); }
.task-state { display: inline-flex; align-items: center; gap: 8px; min-height: 34px; padding: 0 13px; border-radius: 999px; color: var(--task-slate); background: var(--task-soft); font-size: clamp(12px, .35rem + .4cqi, 15px); font-weight: 800; }
.task-state i { width: 7px; height: 7px; border-radius: 50%; background: #94a3b8; }
.task-state.is-running, .task-state.is-starting, .task-state.is-completed { color: var(--task-brand-dark); background: var(--task-brand-soft); }
.task-state.is-running i, .task-state.is-starting i, .task-state.is-completed i { background: var(--task-brand); }
.task-state.is-waiting_human, .task-state.is-paused, .task-state.is-pausing, .task-state.is-stopping { color: #9a5b08; background: var(--task-warning-soft); }
.task-state.is-waiting_human i, .task-state.is-paused i, .task-state.is-pausing i, .task-state.is-stopping i { background: var(--task-warning); }
.task-state.is-failed { color: #b42332; background: var(--task-danger-soft); }
.task-state.is-failed i { background: var(--task-danger); }
.task-detail-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: var(--task-space-2); }
.task-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: clamp(44px, 2.25rem + .75cqi, 52px); padding: 0 clamp(15px, .8rem + .35cqi, 20px); border: 1px solid #cdd9d8; border-radius: var(--task-radius-control); color: var(--task-slate); background: var(--task-paper); font: 750 clamp(14px, .4rem + .45cqi, 16px)/1.3 var(--task-font-family); text-decoration: none; transition: border-color var(--task-transition), background var(--task-transition), color var(--task-transition), transform var(--task-transition); }
.task-button:not(:disabled):hover { border-color: #9bd3cc; color: var(--task-brand-dark); background: var(--task-brand-soft); }
.task-button:not(:disabled):active { transform: translateY(1px); }
.task-button.is-primary { color: white; border-color: var(--task-brand); background: var(--task-brand); }
.task-button.is-primary:not(:disabled):hover { color: white; border-color: var(--task-brand-dark); background: var(--task-brand-dark); }
.task-button.is-danger { color: #b42332; border-color: #f3c9cf; background: var(--task-danger-soft); }
.task-button.is-danger-text { color: var(--task-danger); border-color: transparent; background: transparent; }
.task-button:disabled { cursor: wait; opacity: .55; }
.task-button:focus-visible, .task-detail a:focus-visible, .task-detail button:focus-visible { outline: 2px solid var(--task-brand); outline-offset: 2px; }
.task-detail-card { min-width: 0; overflow: hidden; background: var(--task-paper); border: 1px solid var(--task-line); border-radius: var(--task-radius-panel); box-shadow: 0 1px 2px rgba(15, 23, 42, .025); }
.task-status-card { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(440px, 1fr); align-items: center; gap: var(--task-space-5); padding: clamp(22px, 1.1rem + .65cqi, 32px) var(--task-space-5); border-left: 4px solid #94a3b8; }
.task-status-card.is-running, .task-status-card.is-starting, .task-status-card.is-completed { border-left-color: var(--task-brand); }
.task-status-card.is-waiting_human, .task-status-card.is-paused, .task-status-card.is-pausing, .task-status-card.is-stopping { border-left-color: var(--task-warning); }
.task-status-card.is-failed { border-left-color: var(--task-danger); }
.task-status-card > div { display: grid; gap: var(--task-space-1); }
.task-status-card span, .task-status-card dt { color: var(--task-muted); font-size: clamp(12px, .35rem + .36cqi, 14px); font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.task-status-card strong { font-size: clamp(19px, .8rem + .55cqi, 24px); }
.task-status-card p { margin: 0; color: var(--task-slate); font-size: clamp(14px, .35rem + .5cqi, 17px); line-height: 1.65; }
.task-status-card dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--task-space-3); margin: 0; }
.task-status-card dl div { display: grid; gap: var(--task-space-1); min-width: 0; }
.task-status-card dd { margin: 0; overflow: hidden; color: var(--task-ink); font-size: clamp(13px, .35rem + .42cqi, 16px); font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.task-approval-inbox { display: grid; gap: var(--task-space-3); padding: var(--task-space-4) var(--task-space-5); border-left: 4px solid var(--task-warning); }
.task-monitoring-card { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: var(--task-space-3); padding: var(--task-space-4) var(--task-space-5); border-left: 4px solid var(--task-brand); }
.task-monitoring-card > svg { color: var(--task-brand); }
.task-monitoring-card > div { display: grid; gap: 3px; }
.task-monitoring-card strong { color: var(--task-ink); font-size: clamp(14px, .35rem + .45cqi, 17px); }
.task-monitoring-card small { color: var(--task-muted); font-size: clamp(13px, .35rem + .4cqi, 15px); line-height: 1.55; }
.task-monitoring-card dl { display: grid; grid-template-columns: repeat(3, auto); gap: var(--task-space-4); margin: 0; }
.task-monitoring-card dl div { display: grid; gap: 2px; }
.task-monitoring-card dt { color: var(--task-muted); font-size: 11px; font-weight: 800; }
.task-monitoring-card dd { margin: 0; color: var(--task-ink); font-size: 13px; font-weight: 750; }
.task-monitoring-card.has-warning { border-left-color: var(--task-warning); background: var(--task-warning-soft); }
.task-monitoring-card.has-warning > svg { color: var(--task-warning); }
.task-plan-authorization { display: flex; align-items: center; gap: var(--task-space-3); padding: var(--task-space-4) var(--task-space-5); border-left: 4px solid var(--task-brand); }
.task-plan-authorization > svg { flex: none; color: var(--task-brand); }
.task-plan-authorization > div { display: grid; gap: 3px; }
.task-plan-authorization strong { color: var(--task-ink); font-size: clamp(14px, .35rem + .45cqi, 17px); }
.task-plan-authorization small { color: var(--task-muted); font-size: clamp(13px, .35rem + .4cqi, 15px); line-height: 1.55; }
.task-approval-inbox > header { display: flex; align-items: center; gap: var(--task-space-3); }
.task-approval-inbox > header > span { display: grid; place-items: center; width: 34px; height: 34px; flex: none; border-radius: 10px; color: #9a5b08; background: var(--task-warning-soft); }
.task-approval-inbox > header > div, .task-approval-inbox article > div { display: grid; gap: 2px; min-width: 0; }
.task-approval-inbox > header strong, .task-approval-inbox article strong { color: var(--task-ink); font-size: clamp(14px, .35rem + .45cqi, 17px); }
.task-approval-inbox > header small, .task-approval-inbox article small, .task-approval-inbox > p { margin: 0; color: var(--task-muted); font-size: clamp(13px, .35rem + .4cqi, 15px); line-height: 1.55; }
.task-approval-inbox > header em { margin-left: auto; padding: 3px 8px; border-radius: 999px; color: #9a5b08; background: var(--task-warning-soft); font-size: 11px; font-style: normal; font-weight: 800; }
.task-approval-inbox article { display: grid; grid-template-columns: minmax(150px, .55fr) minmax(240px, 1.25fr) auto; align-items: center; gap: var(--task-space-4); padding-top: var(--task-space-3); border-top: 1px solid var(--task-line); }
.task-approval-inbox blockquote { margin: 0; color: var(--task-slate); font-size: clamp(13px, .35rem + .4cqi, 15px); line-height: 1.6; }
.task-approval-inbox article button { min-height: 36px; padding: 0 12px; border: 1px solid var(--task-brand); border-radius: var(--task-radius-control); color: white; background: var(--task-brand); font: 700 12px/1.3 var(--task-font-family); cursor: pointer; }
.task-approval-inbox article button:disabled { cursor: wait; opacity: .55; }
.task-approval-notice { color: var(--task-brand-dark) !important; }
.task-action-error { display: flex; align-items: center; gap: var(--task-space-2); margin: 0; padding: var(--task-space-3) var(--task-space-4); color: #b42332; background: var(--task-danger-soft); border: 1px solid #f3c9cf; border-radius: var(--task-radius-control); font-size: clamp(13px, .35rem + .4cqi, 15px); }
.task-detail-loading { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--task-space-3); padding: var(--task-space-5); }
.task-detail-loading span { height: 76px; border-radius: var(--task-radius-control); background: #f1f5f9; animation: task-pulse 1.2s ease-in-out infinite; }
.task-detail-loading p { grid-column: 1 / -1; margin: 0; color: var(--task-muted); text-align: center; }
.task-detail-error { display: flex; align-items: center; gap: var(--task-space-4); padding: var(--task-space-5); }
.task-detail-error > svg { flex: none; color: var(--task-danger); }
.task-detail-error > div { flex: 1; min-width: 0; }
.task-detail-error strong { font-size: 15px; }
.task-detail-error p { margin: var(--task-space-1) 0 0; color: var(--task-muted); font-size: 13px; }
.task-detail-error a { text-decoration: none; }
@keyframes task-pulse { 50% { opacity: .55; } }

@container task-detail (max-width: 980px) {
  .task-detail-hero { align-items: stretch; flex-direction: column; }
  .task-detail-actions { justify-content: flex-start; }
  .task-status-card { grid-template-columns: 1fr; }
}

@container task-detail (max-width: 620px) {
  .task-detail-actions > * { flex: 1 1 145px; min-height: 44px; }
  .task-status-card dl { grid-template-columns: 1fr; }
  .task-detail-loading { grid-template-columns: 1fr; }
  .task-detail-loading p { grid-column: auto; }
  .task-detail-error { align-items: flex-start; flex-wrap: wrap; }
  .task-approval-inbox article { grid-template-columns: 1fr; }
  .task-monitoring-card { grid-template-columns: auto minmax(0, 1fr); }
  .task-monitoring-card dl { grid-column: 1 / -1; grid-template-columns: 1fr; }
  .task-approval-inbox article button { min-height: 44px; }
}

@media (prefers-reduced-motion: reduce) {
  .task-button { transition: none; }
  .task-detail-loading span { animation: none; }
}
</style>
