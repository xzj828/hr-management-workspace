<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import TaskProgressBar from '@/components/TaskProgressBar.vue'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'
import { formatRecruitmentDate } from '@/recruitment'
import { createRequestId, positionSyncSummary, terminalTaskStatuses } from '@/recruitmentJobs'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'

const auth = useAuthStore()
const recruitmentContext = useRecruitmentContextStore()

const jobs = ref([])
const accounts = ref([])
const selectedAccountId = ref('')
const selected = ref(null)
const loading = ref(true)
const error = ref('')
const syncTask = ref(null)
const syncMessage = ref('')
const lifecycleTarget = ref(null)
const lifecycleSaving = ref(false)
const showArchived = ref(false)
let pollTimer = null

const statusLabels = { open: '招聘中', paused: '已暂停', closed: '已关闭' }
const syncing = computed(() => syncTask.value && !terminalTaskStatuses.has(syncTask.value.status))

async function loadJobs() {
  loading.value = true
  error.value = ''
  try {
    jobs.value = listItems(await api(`recruitment/jobs/${showArchived.value ? '?archived=1' : ''}`))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadAccounts() {
  accounts.value = listItems(await api('recruitment/boss-accounts/'))
  if (!selectedAccountId.value && accounts.value.length) selectedAccountId.value = String(accounts.value[0].id)
}

function stopPolling() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = null
}

async function pollSyncTask(taskId) {
  try {
    const task = await api(`recruitment/rpa-tasks/${taskId}/`)
    syncTask.value = task
    if (task.status === 'succeeded') {
      syncMessage.value = positionSyncSummary(task.result) || '职位同步完成'
      await loadJobs()
      await recruitmentContext.loadJobs({ userId: auth.user?.id, force: true })
      return
    }
    if (task.status === 'waiting_human') {
      syncMessage.value = '需要在隔离浏览器中完成验证'
      return
    }
    if (task.status === 'failed' || task.status === 'cancelled') {
      error.value = task.error_message || (task.status === 'cancelled' ? '同步任务已取消' : '职位同步失败')
      return
    }
    pollTimer = window.setTimeout(() => pollSyncTask(taskId), 900)
  } catch (err) {
    error.value = err.message
  }
}

async function syncPositions() {
  if (!selectedAccountId.value || syncing.value) return
  stopPolling()
  error.value = ''
  syncMessage.value = ''
  syncTask.value = { status: 'pending' }
  try {
    const created = await api('recruitment/jobs/sync/', {
      method: 'POST',
      body: JSON.stringify({
        boss_account: Number(selectedAccountId.value),
        request_id: createRequestId(),
      }),
    })
    syncTask.value = created
    await pollSyncTask(created.task_id)
  } catch (err) {
    syncTask.value = { status: 'failed' }
    error.value = err.message
  }
}

function openJob(job) {
  selected.value = job
}

async function archiveJob() {
  if (!lifecycleTarget.value) return
  lifecycleSaving.value = true
  error.value = ''
  try {
    await api(`recruitment/jobs/${lifecycleTarget.value.id}/archive/`, { method: 'POST' })
    lifecycleTarget.value = null
    selected.value = null
    await loadJobs()
  } catch (err) { error.value = err.message }
  finally { lifecycleSaving.value = false }
}

async function restoreJob(job) {
  error.value = ''
  try {
    await api(`recruitment/jobs/${job.id}/restore/?archived=1`, { method: 'POST' })
    selected.value = null
    await loadJobs()
  } catch (err) { error.value = err.message }
}

async function toggleArchiveView() {
  showArchived.value = !showArchived.value
  selected.value = null
  await loadJobs()
}

onMounted(async () => {
  try {
    await Promise.all([loadJobs(), loadAccounts()])
  } catch (err) {
    error.value = err.message
  }
})
onUnmounted(stopPolling)
</script>

<template>
  <div class="page-stack">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div>
        <span class="eyebrow">Position Portfolio</span>
        <h2>职位管理</h2>
        <p>集中查看在招职位、负责人和候选人分布。</p>
      </div>
      <div class="recruitment-toolbar__actions">
        <button class="text-button" data-test="toggle-archived-jobs" type="button" @click="toggleArchiveView">{{ showArchived ? '返回当前职位' : '归档记录' }}</button>
        <label class="job-sync-account">
          <span>同步账号</span>
          <select v-model="selectedAccountId" data-test="sync-account" :disabled="syncing || !accounts.length">
            <option v-if="!accounts.length" value="">暂无可用账号</option>
            <option v-for="account in accounts" :key="account.id" :value="String(account.id)">{{ account.name }}</option>
          </select>
        </label>
        <button
          class="text-button button-with-icon job-sync-button"
          data-test="sync-positions"
          type="button"
          :disabled="syncing || !selectedAccountId"
          @click="syncPositions"
        ><AppIcon name="refresh" :size="16" /><span>{{ syncing ? '同步中…' : '同步职位' }}</span></button>
        <RecruitmentDemoMenu @changed="loadJobs" />
      </div>
    </header>

    <p v-if="error" class="recruitment-error-strip">{{ error }}</p>

    <Transition name="job-sync-feedback">
      <section v-if="syncTask" class="job-sync-feedback" aria-live="polite">
        <TaskProgressBar :status="syncTask.status" />
        <p v-if="syncMessage">{{ syncMessage }}</p>
      </section>
    </Transition>

    <section class="recruitment-data-shell">
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>职位</th><th>部门</th><th>招聘人数</th><th>候选人</th><th>负责人</th><th>状态</th></tr></thead>
          <tbody>
            <tr
              v-for="job in jobs"
              :key="job.id"
              class="recruitment-row"
              tabindex="0"
              @click="openJob(job)"
              @keydown.enter="openJob(job)"
            >
              <td><strong>{{ job.title }}</strong><small v-if="job.is_demo" class="block-text">演示职位</small></td>
              <td>{{ job.department || '—' }}</td>
              <td>{{ job.headcount }}</td>
              <td>{{ job.candidate_count }} 人</td>
              <td>{{ job.owner_name }}</td>
              <td><span class="recruitment-chip">{{ statusLabels[job.status] || job.status }}</span></td>
            </tr>
            <tr v-if="!loading && !jobs.length"><td colspan="6" class="table-empty">{{ showArchived ? '暂无已归档职位' : '暂无职位，可从“演示数据”加载示例。' }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <RecruitmentDetailDrawer v-if="selected" :title="selected.title" @close="selected = null">
      <dl class="recruitment-detail-grid">
        <div><dt>部门</dt><dd>{{ selected.department || '—' }}</dd></div>
        <div><dt>负责人</dt><dd>{{ selected.owner_name }}</dd></div>
        <div><dt>招聘人数</dt><dd>{{ selected.headcount }} 人</dd></div>
        <div><dt>候选人数</dt><dd>{{ selected.candidate_count }} 人</dd></div>
        <div><dt>职位状态</dt><dd>{{ statusLabels[selected.status] || selected.status }}</dd></div>
        <div><dt>数据来源</dt><dd>{{ selected.is_demo ? '内部演示数据' : (selected.account_name || '内部创建') }}</dd></div>
        <div><dt>更新时间</dt><dd>{{ formatRecruitmentDate(selected.updated_at) }}</dd></div>
      </dl>
      <section class="recruitment-detail-section"><span>职位描述</span><p>{{ selected.jd || '暂无职位描述' }}</p></section>
      <template #footer>
        <button v-if="showArchived" class="text-button" data-test="restore-job" type="button" @click="restoreJob(selected)">恢复职位</button>
        <button v-else class="danger-text-button" data-test="archive-job" type="button" @click="lifecycleTarget = selected">关闭并归档职位</button>
      </template>
    </RecruitmentDetailDrawer>
    <ArchiveConfirmModal v-if="lifecycleTarget" title="关闭并归档职位" :name="lifecycleTarget.title" description="职位会转为已关闭并从在招列表移除，候选人与历史流程仍会保留。" action-label="确认关闭并归档" :saving="lifecycleSaving" @close="lifecycleTarget = null" @confirm="archiveJob" />
  </div>
</template>
