<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { api, listItems } from '@/api'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import AppIcon from '@/components/AppIcon.vue'
import CandidateDiscoveryCard from '@/components/CandidateDiscoveryCard.vue'
import CommunicationConfirmDrawer from '@/components/CommunicationConfirmDrawer.vue'
import DeepMatchConfirmDrawer from '@/components/DeepMatchConfirmDrawer.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import TaskProgressBar from '@/components/TaskProgressBar.vue'
import ModalPanel from '@/components/ModalPanel.vue'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'
import { discoveryModes, discoveryPayload, discoverySyncMessage, discoveryTaskDone } from '@/candidateDiscovery'
import { stageColumns } from '@/recruitment'
import { createRequestId } from '@/recruitmentJobs'
import { communicationPayload } from '@/recruitmentCommunications'

const context = useRecruitmentContextStore()
const activeTab = ref('library')
const applications = ref([]), discoveries = ref([])
const selected = ref(null), selectedDiscovery = ref(null), selectedDiscoveryIds = ref(new Set())
const search = ref(''), stage = ref('')
const discoveryMode = ref('recommend'), keyword = ref(''), coreText = ref(''), bonusText = ref('')
const loading = ref(false), discoveryLoading = ref(false), error = ref('')
const task = ref(null), taskMessage = ref(''), approval = ref(null)
const confirming = ref(false), importing = ref(false)
const selectedApplicationIds = ref(new Set()), communicationOpen = ref(false), communicationSaving = ref(false)
const onlineResumeApplication = ref(null), onlineResumeSaving = ref(false)
const lifecycleTarget = ref(null), lifecycleSaving = ref(false), showArchived = ref(false)
let pollTimer = null
let applicationSequence = 0
let discoverySequence = 0

const currentJob = computed(() => context.currentJob)
const selectedDiscoveryCount = computed(() => selectedDiscoveryIds.value.size)
const taskRunning = computed(() => task.value && !discoveryTaskDone(task.value.status))
const selectedApplications = computed(() => applications.value.filter((application) => selectedApplicationIds.value.has(application.id)))
const communicationCandidates = computed(() => selectedApplications.value.map((application) => ({
  applicationId: application.id,
  name: application.candidate.name,
  jobTitle: application.job_title,
})))
const communicationAccount = computed(() => currentJob.value?.boss_account || null)
const communicationAccountName = computed(() => currentJob.value?.account_name || '当前职位账号')
const lines = (value) => value.split('\n').map((item) => item.trim()).filter(Boolean)

async function loadApplications() {
  if (!currentJob.value) return
  const sequence = ++applicationSequence
  loading.value = true
  const params = new URLSearchParams({ job: String(currentJob.value.id) })
  if (search.value.trim()) params.set('search', search.value.trim())
  if (stage.value) params.set('stage', stage.value)
  if (showArchived.value) params.set('archived', '1')
  try {
    const result = listItems(await api(`recruitment/applications/?${params}`))
    if (sequence !== applicationSequence) return
    applications.value = result
    const visible = new Set(applications.value.map((application) => application.id))
    selectedApplicationIds.value = new Set([...selectedApplicationIds.value].filter((id) => visible.has(id)))
  } catch (err) { if (sequence === applicationSequence) error.value = err.message }
  finally { if (sequence === applicationSequence) loading.value = false }
}

async function loadDiscoveries() {
  if (!currentJob.value || showArchived.value) return
  const sequence = ++discoverySequence
  discoveryLoading.value = true
  const params = new URLSearchParams({ imported: 'false', job: String(currentJob.value.id) })
  try {
    const result = listItems(await api(`recruitment/candidate-discoveries/?${params}`))
    if (sequence !== discoverySequence) return
    discoveries.value = result
    const visible = new Set(discoveries.value.map((item) => String(item.id)))
    selectedDiscoveryIds.value = new Set([...selectedDiscoveryIds.value].filter((id) => visible.has(id)))
  } catch (err) { if (sequence === discoverySequence) error.value = err.message }
  finally { if (sequence === discoverySequence) discoveryLoading.value = false }
}

async function loadWorkspace() {
  if (!currentJob.value) return
  error.value = ''
  await Promise.all([loadApplications(), loadDiscoveries()])
}

function stopPolling() { if (pollTimer) window.clearTimeout(pollTimer); pollTimer = null }
async function pollTask(taskId) {
  try {
    const current = await api(`recruitment/rpa-tasks/${taskId}/`)
    task.value = current
    if (current.status === 'succeeded') { taskMessage.value = discoverySyncMessage(current.result) || '候选人发现完成'; await loadDiscoveries(); return }
    if (current.status === 'waiting_human') { taskMessage.value = '需要在隔离浏览器中完成登录或验证'; return }
    if (['failed', 'cancelled'].includes(current.status)) { error.value = current.error_message || '候选人发现任务未完成'; return }
    pollTimer = window.setTimeout(() => pollTask(taskId), 900)
  } catch (err) { error.value = err.message }
}

async function startDiscovery() {
  if (!currentJob.value || !communicationAccount.value || taskRunning.value) return
  error.value = ''; taskMessage.value = ''
  if (discoveryMode.value === 'deep_search') {
    try {
      approval.value = await api('recruitment/candidate-discoveries/prepare-deep-match/', {
        method: 'POST',
        body: JSON.stringify({ boss_account: Number(communicationAccount.value), job: Number(currentJob.value.id), core: lines(coreText.value), bonus: lines(bonusText.value), request_id: createRequestId() }),
      })
    } catch (err) { error.value = err.message }
    return
  }
  task.value = { status: 'pending' }
  try {
    const created = await api('recruitment/candidate-discoveries/search/', {
      method: 'POST',
      body: JSON.stringify(discoveryPayload({ accountId: communicationAccount.value, jobId: currentJob.value.id, mode: discoveryMode.value, keyword: keyword.value })),
    })
    await pollTask(created.task_id)
  } catch (err) { task.value = { status: 'failed' }; error.value = err.message }
}

async function confirmDeepMatch() {
  confirming.value = true; task.value = { status: 'pending' }
  try {
    const result = await api(`recruitment/automation-approvals/${approval.value.id}/approve/`, { method: 'POST' })
    approval.value = null
    await pollTask(result.task_id)
  } catch (err) { error.value = err.message; task.value = { status: 'failed' } }
  finally { confirming.value = false }
}

function toggleDiscovery(id) {
  const next = new Set(selectedDiscoveryIds.value), key = String(id)
  next.has(key) ? next.delete(key) : next.add(key)
  selectedDiscoveryIds.value = next
}

async function importSelected() {
  if (!selectedDiscoveryCount.value) return
  importing.value = true; error.value = ''
  try {
    const result = await api('recruitment/candidate-discoveries/import-selected/', { method: 'POST', body: JSON.stringify({ ids: [...selectedDiscoveryIds.value] }) })
    taskMessage.value = `已入库 ${result.total} 人 · 新建候选人 ${result.created_candidates} 人`
    selectedDiscoveryIds.value = new Set()
    await Promise.all([loadDiscoveries(), loadApplications()])
    activeTab.value = 'library'
  } catch (err) { error.value = err.message }
  finally { importing.value = false }
}

function toggleApplication(applicationId) {
  const next = new Set(selectedApplicationIds.value)
  next.has(applicationId) ? next.delete(applicationId) : next.add(applicationId)
  selectedApplicationIds.value = next
}

function openCommunication() {
  if (!communicationAccount.value) { error.value = '当前职位未关联可用的 BOSS 账号'; return }
  communicationOpen.value = true
}

async function confirmCommunication(snapshot) {
  communicationSaving.value = true; error.value = ''
  try {
    const prepared = await api('recruitment/communication-actions/prepare/', {
      method: 'POST',
      body: JSON.stringify(communicationPayload({
        accountId: communicationAccount.value,
        applicationIds: communicationCandidates.value.map((item) => item.applicationId),
        action: snapshot.action,
        message: snapshot.message,
        invitation: snapshot.invitation,
        requestId: createRequestId(),
      })),
    })
    await api(`recruitment/automation-approvals/${prepared.approval_id}/approve/`, { method: 'POST' })
    communicationOpen.value = false
    selectedApplicationIds.value = new Set()
    taskMessage.value = `已创建 ${prepared.item_count} 人的人工确认沟通批次`
  } catch (err) { error.value = err.message }
  finally { communicationSaving.value = false }
}

async function confirmOnlineResume() {
  if (!onlineResumeApplication.value) return
  onlineResumeSaving.value = true; error.value = ''
  try {
    const prepared = await api('recruitment/communication-actions/prepare-online-resume/', {
      method: 'POST', body: JSON.stringify({ application_id: onlineResumeApplication.value.id, request_id: createRequestId() }),
    })
    await api(`recruitment/automation-approvals/${prepared.id}/approve/`, { method: 'POST' })
    taskMessage.value = '在线简历 PDF 任务已创建，可在自动化任务中查看进度'
    onlineResumeApplication.value = null
  } catch (err) { error.value = err.message }
  finally { onlineResumeSaving.value = false }
}

async function archiveApplication() {
  if (!lifecycleTarget.value) return
  lifecycleSaving.value = true; error.value = ''
  try {
    await api(`recruitment/applications/${lifecycleTarget.value.id}/archive/`, { method: 'POST' })
    lifecycleTarget.value = null; selected.value = null
    await loadApplications()
  } catch (err) { error.value = err.message }
  finally { lifecycleSaving.value = false }
}

async function restoreApplication(application) {
  error.value = ''
  try {
    await api(`recruitment/applications/${application.id}/restore/?archived=1`, { method: 'POST' })
    selected.value = null
    await loadApplications()
  } catch (err) { error.value = err.message }
}

async function toggleArchiveView() {
  showArchived.value = !showArchived.value
  activeTab.value = 'library'
  selected.value = null
  selectedApplicationIds.value = new Set()
  await loadApplications()
}

watch(
  () => currentJob.value?.id,
  async () => {
    stopPolling()
    applicationSequence += 1
    discoverySequence += 1
    applications.value = []
    discoveries.value = []
    selected.value = null
    selectedDiscovery.value = null
    selectedApplicationIds.value = new Set()
    selectedDiscoveryIds.value = new Set()
    showArchived.value = false
    activeTab.value = 'library'
    if (currentJob.value) await loadWorkspace()
  },
  { immediate: true },
)
onUnmounted(stopPolling)
</script>

<template>
  <div class="page-stack candidate-workspace">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div><span class="eyebrow">Candidate Workspace</span><h2>候选人</h2><p>{{ currentJob ? `${currentJob.title} · 按应聘记录推进候选人` : '选择职位后查看和发现候选人' }}</p></div>
      <div v-if="currentJob" class="recruitment-toolbar__actions"><button class="text-button" data-test="toggle-archived-applications" type="button" @click="toggleArchiveView">{{ showArchived ? '返回当前职位' : '移出记录' }}</button></div>
    </header>

    <section v-if="!currentJob" class="panel job-context-required">
      <AppIcon name="briefcase" :size="25" />
      <div><strong>请先选择在招职位</strong><p>候选人、发现结果和沟通动作必须绑定到一个明确职位。</p></div>
    </section>

    <template v-else>
      <nav v-if="!showArchived" class="candidate-tabs" aria-label="候选人页面">
        <button data-test="candidate-tab-library" :class="{ active: activeTab === 'library' }" @click="activeTab = 'library'">候选人库 <span>{{ applications.length }}</span></button>
        <button data-test="candidate-tab-discovery" :class="{ active: activeTab === 'discovery' }" @click="activeTab = 'discovery'">发现候选人 <span>{{ discoveries.length }}</span></button>
      </nav>
      <p v-if="error" class="recruitment-error-strip">{{ error }}</p>
      <section v-if="task" class="job-sync-feedback"><TaskProgressBar :status="task.status" /><p>{{ taskMessage || '正在读取 BOSS 候选人…' }}</p></section>

      <section v-if="activeTab === 'library'" class="recruitment-data-shell">
        <div class="recruitment-filter-row">
          <input v-model="search" data-test="candidate-search" type="search" placeholder="搜索姓名、当前岗位或城市" @input="loadApplications" />
          <select v-model="stage" data-test="candidate-stage" aria-label="招聘阶段" @change="loadApplications"><option value="">全部阶段</option><option v-for="item in stageColumns" :key="item.key" :value="item.key">{{ item.label }}</option></select>
          <span class="toolbar__count">{{ applications.length }} 条应聘记录</span>
        </div>
        <div class="table-scroll"><table class="data-table"><thead><tr><th class="candidate-select-cell" aria-label="选择"></th><th>候选人</th><th>当前岗位 / 城市</th><th>招聘阶段</th><th>负责人</th><th>最近互动</th><th>简历</th></tr></thead><tbody>
          <tr v-for="application in applications" :key="application.id" :class="['recruitment-row', { 'is-selected': selectedApplicationIds.has(application.id) }]" tabindex="0" @click="selected = application" @keydown.enter="selected = application"><td class="candidate-select-cell" @click.stop><label v-if="!showArchived" class="candidate-row-check"><input :data-test="`application-check-${application.id}`" type="checkbox" :checked="selectedApplicationIds.has(application.id)" @change="toggleApplication(application.id)" /><span></span></label></td><td><strong>{{ application.candidate.name }}</strong></td><td>{{ application.candidate.current_title || '—' }}<small class="block-text">{{ application.candidate.current_city || '—' }}</small></td><td><span class="recruitment-chip">{{ application.stage_label }}</span></td><td>{{ application.owner_name || '未分配' }}</td><td>{{ application.last_interaction_at ? new Date(application.last_interaction_at).toLocaleDateString('zh-CN') : '暂无互动' }}</td><td>{{ application.resume_count ? `${application.resume_count} 份简历` : '暂无简历' }}</td></tr>
          <tr v-if="!loading && !applications.length"><td colspan="7" class="table-empty">{{ showArchived ? '没有已移出的应聘记录' : '该职位还没有候选人，可前往“发现候选人”开始搜索' }}</td></tr>
        </tbody></table></div>
      </section>

      <template v-else>
        <section class="discovery-console">
          <div class="discovery-console__top discovery-console__top--bound">
            <div class="discovery-bound-context"><span>BOSS 账号</span><strong>{{ currentJob.account_name || '未关联账号' }}</strong></div>
            <div class="discovery-bound-context"><span>当前职位</span><strong>{{ currentJob.title }}</strong></div>
            <div class="discovery-mode-switch"><button v-for="mode in discoveryModes" :key="mode.key" :class="{ active: discoveryMode === mode.key }" :data-test="`discovery-mode-${mode.key}`" @click="discoveryMode = mode.key">{{ mode.label }}</button></div>
          </div>
          <div class="discovery-query-row">
            <label v-if="discoveryMode === 'search'" class="discovery-keyword"><AppIcon name="search" :size="16" /><input v-model="keyword" maxlength="20" placeholder="输入技能或岗位关键词" /></label>
            <template v-else-if="discoveryMode === 'deep_search'"><label><span>核心要求（每行一项）</span><textarea v-model="coreText" rows="2" placeholder="Vue 3&#10;复杂后台系统经验"></textarea></label><label><span>加分项（每行一项）</span><textarea v-model="bonusText" rows="2" placeholder="ToB 项目经验"></textarea></label></template>
            <p v-else>读取当前职位的推荐人才，不会发送任何消息。</p>
            <button class="primary-button button-with-icon" data-test="start-discovery" :disabled="taskRunning || !communicationAccount" @click="startDiscovery"><AppIcon name="search" :size="15" />{{ discoveryMode === 'deep_search' ? '预览并确认' : '开始发现' }}</button>
          </div>
        </section>
        <section class="discovery-results">
          <header><div><span class="eyebrow">Discovery Pool</span><h3>临时候选人池</h3></div><small>仅显示 {{ currentJob.title }} 的发现结果</small></header>
          <div v-if="discoveries.length" class="discovery-grid"><CandidateDiscoveryCard v-for="item in discoveries" :key="item.id" :candidate="item" :selected="selectedDiscoveryIds.has(String(item.id))" @toggle="toggleDiscovery" @open="selectedDiscovery = item" /></div>
          <div v-else-if="!discoveryLoading" class="discovery-empty"><AppIcon name="users" :size="26" /><strong>还没有发现结果</strong><span>选择发现方式后开始读取当前职位候选人。</span></div>
        </section>
      </template>

      <Transition name="batch-bar"><aside v-if="selectedDiscoveryCount" class="discovery-batch-bar" data-test="discovery-batch-bar"><div><strong>已选择 {{ selectedDiscoveryCount }} 人</strong><span>只加入 {{ currentJob.title }}，不会自动联系候选人</span></div><button class="text-button" @click="selectedDiscoveryIds = new Set()">取消选择</button><button class="primary-button" data-test="import-selected" :disabled="importing" @click="importSelected">{{ importing ? '正在入库…' : '加入当前职位' }}</button></aside></Transition>
      <Transition name="batch-bar"><aside v-if="selectedApplicationIds.size && activeTab === 'library'" class="library-contact-bar" data-test="library-contact-bar"><div><strong>已选择 {{ selectedApplicationIds.size }} 人</strong><span>全部属于 {{ currentJob.title }}，发送前仍需人工确认</span></div><button class="text-button" @click="selectedApplicationIds = new Set()">取消选择</button><button class="primary-button" data-test="open-communication" @click="openCommunication">创建沟通批次</button></aside></Transition>

      <RecruitmentDetailDrawer v-if="selected" :title="selected.candidate.name" @close="selected = null"><dl class="recruitment-detail-grid"><div><dt>应聘职位</dt><dd>{{ selected.job_title }}</dd></div><div><dt>招聘阶段</dt><dd>{{ selected.stage_label }}</dd></div><div><dt>当前岗位</dt><dd>{{ selected.candidate.current_title || '—' }}</dd></div><div><dt>所在城市</dt><dd>{{ selected.candidate.current_city || '—' }}</dd></div><div><dt>电话</dt><dd>{{ selected.candidate.phone || '—' }}</dd></div><div><dt>邮箱</dt><dd>{{ selected.candidate.email || '—' }}</dd></div><div><dt>负责人</dt><dd>{{ selected.owner_name || '未分配' }}</dd></div><div><dt>简历</dt><dd>{{ selected.resume_count ? `${selected.resume_count} 份简历` : '暂无简历' }}</dd></div></dl><section v-if="selected.other_applications?.length" class="recruitment-detail-section"><details><summary>其他应聘职位（{{ selected.other_applications.length }}）</summary><article v-for="application in selected.other_applications" :key="application.id" class="recruitment-application-line"><div><strong>{{ application.job_title }}</strong><small>{{ application.stage_label }} · 负责人 {{ application.owner_name || '未分配' }}</small></div></article></details></section><template #footer><button v-if="showArchived" class="text-button" data-test="restore-application" type="button" @click="restoreApplication(selected)">恢复到当前职位</button><template v-else><button class="text-button" type="button" @click="onlineResumeApplication = selected">保存在线简历 PDF</button><button class="danger-text-button" data-test="archive-application" type="button" @click="lifecycleTarget = selected">移出当前职位</button></template></template></RecruitmentDetailDrawer>
      <RecruitmentDetailDrawer v-if="selectedDiscovery" :title="selectedDiscovery.display_name" @close="selectedDiscovery = null"><dl class="recruitment-detail-grid"><div><dt>当前岗位</dt><dd>{{ selectedDiscovery.current_title || '—' }}</dd></div><div><dt>城市</dt><dd>{{ selectedDiscovery.city || '—' }}</dd></div><div><dt>工作经历</dt><dd>{{ selectedDiscovery.experience || '—' }}</dd></div><div><dt>学历</dt><dd>{{ selectedDiscovery.education || '—' }}</dd></div><div><dt>身份依据</dt><dd>{{ selectedDiscovery.identity_quality_label }}</dd></div><div><dt>来源职位</dt><dd>{{ currentJob.title }}</dd></div></dl><section class="recruitment-detail-section"><span>候选人优势</span><p>{{ selectedDiscovery.advantage || '暂无' }}</p></section></RecruitmentDetailDrawer>
      <DeepMatchConfirmDrawer v-if="approval" :approval="approval" :confirming="confirming" @close="approval = null" @confirm="confirmDeepMatch" />
      <CommunicationConfirmDrawer v-if="communicationOpen" :candidates="communicationCandidates" :account-name="communicationAccountName" :saving="communicationSaving" @close="communicationOpen = false" @confirm="confirmCommunication" />
      <ModalPanel v-if="onlineResumeApplication" title="保存在线简历 PDF" @close="onlineResumeApplication = null"><p class="online-resume-confirm">打开在线简历可能消耗该账号的查看次数。系统会再次核验候选人与当前职位，成功后保存 PDF 到简历中心。</p><template #footer><button class="secondary-button" @click="onlineResumeApplication = null">取消</button><button class="primary-button" :disabled="onlineResumeSaving" @click="confirmOnlineResume">{{ onlineResumeSaving ? '正在创建…' : '确认并保存' }}</button></template></ModalPanel>
      <ArchiveConfirmModal v-if="lifecycleTarget" title="移出当前职位" :name="lifecycleTarget.candidate.name" description="只隐藏该候选人在当前职位的应聘记录，其他职位、简历和沟通审计不会删除。" action-label="确认移出" :saving="lifecycleSaving" @close="lifecycleTarget = null" @confirm="archiveApplication" />
    </template>
  </div>
</template>
