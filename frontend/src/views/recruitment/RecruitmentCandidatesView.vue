<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, listItems } from '@/api'
import AppIcon from '@/components/AppIcon.vue'
import CandidateDiscoveryCard from '@/components/CandidateDiscoveryCard.vue'
import CommunicationConfirmDrawer from '@/components/CommunicationConfirmDrawer.vue'
import DeepMatchConfirmDrawer from '@/components/DeepMatchConfirmDrawer.vue'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import TaskProgressBar from '@/components/TaskProgressBar.vue'
import ModalPanel from '@/components/ModalPanel.vue'
import { discoveryModes, discoveryPayload, discoverySyncMessage, discoveryTaskDone } from '@/candidateDiscovery'
import { stageColumns } from '@/recruitment'
import { createRequestId } from '@/recruitmentJobs'
import { communicationPayload } from '@/recruitmentCommunications'

const activeTab = ref('library')
const candidates = ref([]), discoveries = ref([]), jobs = ref([]), accounts = ref([])
const selected = ref(null), selectedDiscovery = ref(null), selectedIds = ref(new Set())
const search = ref(''), job = ref(''), stage = ref('')
const discoveryAccount = ref(''), discoveryJob = ref(''), discoveryMode = ref('recommend')
const keyword = ref(''), coreText = ref(''), bonusText = ref('')
const loading = ref(true), discoveryLoading = ref(false), error = ref('')
const task = ref(null), taskMessage = ref(''), approval = ref(null)
const confirming = ref(false), importing = ref(false)
const librarySelectedIds = ref(new Set()), communicationOpen = ref(false), communicationSaving = ref(false)
const onlineResumeApplication = ref(null), onlineResumeSaving = ref(false)
let pollTimer = null

const selectedCount = computed(() => selectedIds.value.size)
const taskRunning = computed(() => task.value && !discoveryTaskDone(task.value.status))
const filteredJobs = computed(() => jobs.value.filter((item) => !discoveryAccount.value || String(item.boss_account) === String(discoveryAccount.value)))
const primaryApplication = (candidate) => candidate.applications?.[0] || null
const selectedLibraryCandidates = computed(() => candidates.value.filter((candidate) => librarySelectedIds.value.has(candidate.id)))
const communicationCandidates = computed(() => selectedLibraryCandidates.value.map((candidate) => ({
  applicationId: primaryApplication(candidate)?.id,
  name: candidate.name,
  jobTitle: primaryApplication(candidate)?.job_title || '未关联职位',
})).filter((item) => item.applicationId))
const communicationAccount = computed(() => {
  const ids = new Set(selectedLibraryCandidates.value.map((candidate) => {
    const application = primaryApplication(candidate)
    return jobs.value.find((item) => String(item.id) === String(application?.job))?.boss_account
  }).filter(Boolean))
  return ids.size === 1 ? [...ids][0] : null
})
const communicationAccountName = computed(() => accounts.value.find((item) => String(item.id) === String(communicationAccount.value))?.name || '')
const lines = (value) => value.split('\n').map((item) => item.trim()).filter(Boolean)

async function loadCandidates() {
  loading.value = true
  const params = new URLSearchParams()
  if (search.value.trim()) params.set('search', search.value.trim())
  if (job.value) params.set('job', job.value)
  if (stage.value) params.set('stage', stage.value)
  try { candidates.value = listItems(await api(`recruitment/candidates/${params.size ? `?${params}` : ''}`)) }
  catch (err) { error.value = err.message }
  finally { loading.value = false }
}

async function loadDiscoveries() {
  discoveryLoading.value = true
  const params = new URLSearchParams({ imported: 'false' })
  if (discoveryAccount.value) params.set('boss_account', discoveryAccount.value)
  if (discoveryJob.value) params.set('job', discoveryJob.value)
  try {
    discoveries.value = listItems(await api(`recruitment/candidate-discoveries/?${params}`))
    const visible = new Set(discoveries.value.map((item) => String(item.id)))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => visible.has(id)))
  } catch (err) { error.value = err.message }
  finally { discoveryLoading.value = false }
}

async function loadWorkspace() {
  error.value = ''
  try {
    const [jobPayload, accountPayload] = await Promise.all([api('recruitment/jobs/'), api('recruitment/boss-accounts/')])
    jobs.value = listItems(jobPayload)
    accounts.value = listItems(accountPayload)
    discoveryAccount.value ||= accounts.value[0] ? String(accounts.value[0].id) : ''
    discoveryJob.value ||= filteredJobs.value[0] ? String(filteredJobs.value[0].id) : ''
  } catch (err) { error.value = err.message }
  await Promise.all([loadCandidates(), loadDiscoveries()])
}

function chooseAccount() {
  discoveryJob.value = filteredJobs.value[0] ? String(filteredJobs.value[0].id) : ''
  loadDiscoveries()
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
  if (!discoveryAccount.value || !discoveryJob.value || taskRunning.value) return
  error.value = ''; taskMessage.value = ''
  if (discoveryMode.value === 'deep_search') {
    try {
      approval.value = await api('recruitment/candidate-discoveries/prepare-deep-match/', { method: 'POST', body: JSON.stringify({ boss_account: Number(discoveryAccount.value), job: Number(discoveryJob.value), core: lines(coreText.value), bonus: lines(bonusText.value), request_id: createRequestId() }) })
    } catch (err) { error.value = err.message }
    return
  }
  task.value = { status: 'pending' }
  try {
    const created = await api('recruitment/candidate-discoveries/search/', { method: 'POST', body: JSON.stringify(discoveryPayload({ accountId: discoveryAccount.value, jobId: discoveryJob.value, mode: discoveryMode.value, keyword: keyword.value })) })
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
  const next = new Set(selectedIds.value), key = String(id)
  next.has(key) ? next.delete(key) : next.add(key)
  selectedIds.value = next
}
async function importSelected() {
  if (!selectedCount.value) return
  importing.value = true; error.value = ''
  try {
    const result = await api('recruitment/candidate-discoveries/import-selected/', { method: 'POST', body: JSON.stringify({ ids: [...selectedIds.value] }) })
    taskMessage.value = `已入库 ${result.total} 人 · 新建候选人 ${result.created_candidates} 人`
    selectedIds.value = new Set()
    await Promise.all([loadDiscoveries(), loadCandidates()])
    activeTab.value = 'library'
  } catch (err) { error.value = err.message }
  finally { importing.value = false }
}

function toggleLibrary(candidateId) {
  const next = new Set(librarySelectedIds.value)
  next.has(candidateId) ? next.delete(candidateId) : next.add(candidateId)
  librarySelectedIds.value = next
}

function openCommunication() {
  if (!communicationAccount.value) {
    error.value = '请选择属于同一个 BOSS 账号的候选人后再创建沟通批次'
    return
  }
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
    librarySelectedIds.value = new Set()
    taskMessage.value = `已创建 ${prepared.item_count} 人的人工确认沟通批次`
  } catch (err) { error.value = err.message }
  finally { communicationSaving.value = false }
}

async function confirmOnlineResume() {
  if (!onlineResumeApplication.value) return
  onlineResumeSaving.value = true; error.value = ''
  try {
    const approval = await api('recruitment/communication-actions/prepare-online-resume/', {
      method: 'POST', body: JSON.stringify({ application_id: onlineResumeApplication.value.id, request_id: createRequestId() }),
    })
    await api(`recruitment/automation-approvals/${approval.id}/approve/`, { method: 'POST' })
    taskMessage.value = '在线简历 PDF 任务已创建，可在自动化任务中查看进度'
    onlineResumeApplication.value = null
  } catch (err) { error.value = err.message }
  finally { onlineResumeSaving.value = false }
}

onMounted(loadWorkspace)
onUnmounted(stopPolling)
</script>

<template>
  <div class="page-stack candidate-workspace">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div><span class="eyebrow">Candidate Workspace</span><h2>候选人</h2><p>从 BOSS 发现人才，确认后再纳入正式招聘流程。</p></div>
      <RecruitmentDemoMenu @changed="loadWorkspace" />
    </header>
    <nav class="candidate-tabs" aria-label="候选人页面">
      <button data-test="candidate-tab-library" :class="{ active: activeTab === 'library' }" @click="activeTab = 'library'">候选人库 <span>{{ candidates.length }}</span></button>
      <button data-test="candidate-tab-discovery" :class="{ active: activeTab === 'discovery' }" @click="activeTab = 'discovery'">发现候选人 <span>{{ discoveries.length }}</span></button>
    </nav>
    <p v-if="error" class="recruitment-error-strip">{{ error }}</p>
    <section v-if="task" class="job-sync-feedback"><TaskProgressBar :status="task.status" /><p>{{ taskMessage || '正在读取 BOSS 候选人…' }}</p></section>

    <section v-if="activeTab === 'library'" class="recruitment-data-shell">
      <div class="recruitment-filter-row">
        <input v-model="search" data-test="candidate-search" type="search" placeholder="搜索姓名、岗位或城市" @input="loadCandidates" />
        <select v-model="job" aria-label="职位" @change="loadCandidates"><option value="">全部职位</option><option v-for="item in jobs" :key="item.id" :value="item.id">{{ item.title }}</option></select>
        <select v-model="stage" data-test="candidate-stage" aria-label="招聘阶段" @change="loadCandidates"><option value="">全部阶段</option><option v-for="item in stageColumns" :key="item.key" :value="item.key">{{ item.label }}</option></select>
        <span class="toolbar__count">{{ candidates.length }} 位候选人</span>
      </div>
      <div class="table-scroll"><table class="data-table"><thead><tr><th class="candidate-select-cell" aria-label="选择"></th><th>候选人</th><th>当前岗位 / 城市</th><th>应聘职位</th><th>阶段</th><th>负责人</th><th>简历</th></tr></thead><tbody>
        <tr v-for="candidate in candidates" :key="candidate.id" :class="['recruitment-row', { 'is-selected': librarySelectedIds.has(candidate.id) }]" tabindex="0" @click="selected = candidate" @keydown.enter="selected = candidate"><td class="candidate-select-cell" @click.stop><label class="candidate-row-check"><input :data-test="`candidate-check-${candidate.id}`" type="checkbox" :checked="librarySelectedIds.has(candidate.id)" @change="toggleLibrary(candidate.id)" /><span></span></label></td><td><strong>{{ candidate.name }}</strong></td><td>{{ candidate.current_title || '—' }}<small class="block-text">{{ candidate.current_city || '—' }}</small></td><td>{{ primaryApplication(candidate)?.job_title || '—' }}</td><td><span class="recruitment-chip">{{ primaryApplication(candidate)?.stage_label || '—' }}</span></td><td>{{ primaryApplication(candidate)?.owner_name || '—' }}</td><td>{{ candidate.resume_count ? `${candidate.resume_count} 份简历` : '暂无简历' }}</td></tr>
        <tr v-if="!loading && !candidates.length"><td colspan="7" class="table-empty">没有符合条件的候选人</td></tr>
      </tbody></table></div>
    </section>

    <template v-else>
      <section class="discovery-console">
        <div class="discovery-console__top">
          <label><span>BOSS 账号</span><select v-model="discoveryAccount" data-test="discovery-account" @change="chooseAccount"><option v-for="item in accounts" :key="item.id" :value="String(item.id)">{{ item.name }}</option></select></label>
          <label><span>来源职位</span><select v-model="discoveryJob" data-test="discovery-job" @change="loadDiscoveries"><option v-for="item in filteredJobs" :key="item.id" :value="String(item.id)">{{ item.title }}</option></select></label>
          <div class="discovery-mode-switch"><button v-for="mode in discoveryModes" :key="mode.key" :class="{ active: discoveryMode === mode.key }" :data-test="`discovery-mode-${mode.key}`" @click="discoveryMode = mode.key">{{ mode.label }}</button></div>
        </div>
        <div class="discovery-query-row">
          <label v-if="discoveryMode === 'search'" class="discovery-keyword"><AppIcon name="search" :size="16" /><input v-model="keyword" maxlength="20" placeholder="输入技能或岗位关键词" /></label>
          <template v-else-if="discoveryMode === 'deep_search'"><label><span>核心要求（每行一项）</span><textarea v-model="coreText" rows="2" placeholder="Vue 3&#10;复杂后台系统经验"></textarea></label><label><span>加分项（每行一项）</span><textarea v-model="bonusText" rows="2" placeholder="ToB 项目经验"></textarea></label></template>
          <p v-else>读取当前职位的推荐人才，不会发送任何消息。</p>
          <button class="primary-button button-with-icon" data-test="start-discovery" :disabled="taskRunning || !discoveryJob" @click="startDiscovery"><AppIcon name="search" :size="15" />{{ discoveryMode === 'deep_search' ? '预览并确认' : '开始发现' }}</button>
        </div>
      </section>
      <section class="discovery-results">
        <header><div><span class="eyebrow">Discovery Pool</span><h3>临时候选人池</h3></div><small>结果保留 7 天 · 正式入库前不会污染候选人库</small></header>
        <div v-if="discoveries.length" class="discovery-grid"><CandidateDiscoveryCard v-for="item in discoveries" :key="item.id" :candidate="item" :selected="selectedIds.has(String(item.id))" @toggle="toggleDiscovery" @open="selectedDiscovery = item" /></div>
        <div v-else-if="!discoveryLoading" class="discovery-empty"><AppIcon name="users" :size="26" /><strong>还没有发现结果</strong><span>选择账号、职位和发现方式后开始读取。</span></div>
      </section>
    </template>

    <Transition name="batch-bar"><aside v-if="selectedCount" class="discovery-batch-bar" data-test="discovery-batch-bar"><div><strong>已选择 {{ selectedCount }} 人</strong><span>只写入本地候选人库，不会联系候选人</span></div><button class="text-button" @click="selectedIds = new Set()">取消选择</button><button class="primary-button" data-test="import-selected" :disabled="importing" @click="importSelected">{{ importing ? '正在入库…' : '加入候选人库' }}</button></aside></Transition>
    <Transition name="batch-bar"><aside v-if="librarySelectedIds.size && activeTab === 'library'" class="library-contact-bar" data-test="library-contact-bar"><div><strong>已选择 {{ librarySelectedIds.size }} 人</strong><span>对外发送前还会显示最终话术与账号</span></div><button class="text-button" @click="librarySelectedIds = new Set()">取消选择</button><button class="primary-button" data-test="open-communication" @click="openCommunication">创建沟通批次</button></aside></Transition>
    <RecruitmentDetailDrawer v-if="selected" :title="selected.name" @close="selected = null"><dl class="recruitment-detail-grid"><div><dt>当前岗位</dt><dd>{{ selected.current_title || '—' }}</dd></div><div><dt>所在城市</dt><dd>{{ selected.current_city || '—' }}</dd></div><div><dt>电话</dt><dd>{{ selected.phone || '—' }}</dd></div><div><dt>邮箱</dt><dd>{{ selected.email || '—' }}</dd></div><div><dt>简历</dt><dd>{{ selected.resume_count ? `${selected.resume_count} 份简历` : '暂无简历' }}</dd></div></dl><section class="recruitment-detail-section"><span>应聘记录</span><article v-for="application in selected.applications" :key="application.id" class="recruitment-application-line"><div><strong>{{ application.job_title }}</strong><small>{{ application.stage_label }} · 负责人 {{ application.owner_name || '未分配' }}</small></div><button class="text-button" type="button" @click="onlineResumeApplication = application">保存在线简历 PDF</button></article></section></RecruitmentDetailDrawer>
    <RecruitmentDetailDrawer v-if="selectedDiscovery" :title="selectedDiscovery.display_name" @close="selectedDiscovery = null"><dl class="recruitment-detail-grid"><div><dt>当前岗位</dt><dd>{{ selectedDiscovery.current_title || '—' }}</dd></div><div><dt>城市</dt><dd>{{ selectedDiscovery.city || '—' }}</dd></div><div><dt>工作经历</dt><dd>{{ selectedDiscovery.experience || '—' }}</dd></div><div><dt>学历</dt><dd>{{ selectedDiscovery.education || '—' }}</dd></div><div><dt>身份依据</dt><dd>{{ selectedDiscovery.identity_quality_label }}</dd></div><div><dt>来源职位</dt><dd>{{ selectedDiscovery.job_title }}</dd></div></dl><section class="recruitment-detail-section"><span>候选人优势</span><p>{{ selectedDiscovery.advantage || '暂无' }}</p></section></RecruitmentDetailDrawer>
    <DeepMatchConfirmDrawer v-if="approval" :approval="approval" :confirming="confirming" @close="approval = null" @confirm="confirmDeepMatch" />
    <CommunicationConfirmDrawer v-if="communicationOpen" :candidates="communicationCandidates" :account-name="communicationAccountName" :saving="communicationSaving" @close="communicationOpen = false" @confirm="confirmCommunication" />
    <ModalPanel v-if="onlineResumeApplication" title="保存在线简历 PDF" @close="onlineResumeApplication = null"><p class="online-resume-confirm">打开在线简历可能消耗该账号的查看次数。系统会再次核验候选人身份，成功后保存 PDF 到简历中心；核验失败不会生成文件。</p><template #footer><button class="secondary-button" @click="onlineResumeApplication = null">取消</button><button class="primary-button" :disabled="onlineResumeSaving" @click="confirmOnlineResume">{{ onlineResumeSaving ? '正在创建…' : '确认并保存' }}</button></template></ModalPanel>
  </div>
</template>
