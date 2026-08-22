<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, listItems } from '@/api'
import ModalPanel from '@/components/ModalPanel.vue'
import AppIcon from '@/components/AppIcon.vue'
import {
  accountDisplayStatus,
  actionLabels,
  availableActions,
  loginStatusLabel,
  taskStatusLabels,
} from '@/recruitmentAutomation'

const summary = reactive({ worker: null, cli_available: false, task_counts: {}, has_active_task: false })
const accounts = ref([])
const tasks = ref([])
const loading = ref(true)
const error = ref('')
const accountModalOpen = ref(false)
const selectedTask = ref(null)
const saving = ref(false)
const form = reactive({ name: '', browser_type: 'edge' })
const actionMenu = ref(null)
let refreshTimer = null

const activeTaskAccountIds = computed(() => new Set(
  tasks.value
    .filter((task) => ['pending', 'leased', 'running'].includes(task.status))
    .map((task) => task.boss_account),
))

const completedCount = computed(() => summary.task_counts?.succeeded || 0)

async function loadWorkspace({ silent = false } = {}) {
  if (!silent) {
    loading.value = true
    error.value = ''
  }
  try {
    const [summaryPayload, accountPayload, taskPayload] = await Promise.all([
      api('recruitment/automation/summary/'),
      api('recruitment/boss-accounts/'),
      api('recruitment/rpa-tasks/'),
    ])
    Object.assign(summary, summaryPayload)
    accounts.value = listItems(accountPayload)
    tasks.value = listItems(taskPayload)
  } catch (err) {
    if (!silent) error.value = err.message
  } finally {
    if (!silent) loading.value = false
  }
}

function actionsFor(account) {
  return availableActions({ ...account, has_active_task: activeTaskAccountIds.value.has(account.id) })
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
  const action = actionName === 'open_login' ? 'check_status' : actionName
  const requestPayload = actionName === 'open_login' ? { open_login: true } : actionName === 'check_status' ? { open_login: false } : {}
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
  window.removeEventListener('click', closeActionMenu)
  window.removeEventListener('resize', closeActionMenu)
  window.removeEventListener('scroll', closeActionMenu, true)
})
</script>

<template>
  <div class="page-stack automation-workspace">
    <header class="page-hero page-hero--compact">
      <div>
        <span class="eyebrow">BOSS Read-only Automation</span>
        <h2>自动化任务</h2>
        <p>每个账号使用独立浏览器环境；登录与安全验证始终由 HR 本人完成。</p>
      </div>
      <button class="text-button automation-add button-with-icon" type="button" @click="accountModalOpen = true"><AppIcon name="plus" :size="16" /><span>添加账号</span></button>
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
        <strong>状态检查 · 职位同步</strong>
      </div>
      <div>
        <span>已完成任务</span>
        <strong>{{ completedCount }}</strong>
      </div>
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
              <td><span :class="['status-badge', `status-badge--${accountDisplayStatus(account)}`]">{{ loginStatusLabel(accountDisplayStatus(account)) }}</span></td>
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
        <span>只读操作留痕</span>
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
              <td><button class="text-button" type="button" @click="selectedTask = task">查看记录</button></td>
            </tr>
            <tr v-if="!loading && !tasks.length"><td colspan="5" class="table-empty">暂无自动化任务</td></tr>
          </tbody>
        </table>
      </div>
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
          >{{ actionLabels[actionName] }}</button>
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
  </div>
</template>
