<script setup>
import { computed, ref, watch } from 'vue'
import { api, listItems } from '@/api'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import AppIcon from '@/components/AppIcon.vue'
import { formatFileSize, formatRecruitmentDate } from '@/recruitment'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'
import JobStandardDrawer from '@/components/JobStandardDrawer.vue'

const context = useRecruitmentContextStore()
const currentJob = computed(() => context.currentJob)
const resumes = ref([])
const selected = ref(null)
const loading = ref(true)
const error = ref('')
const lifecycleTarget = ref(null)
const lifecycleSaving = ref(false)
const showArchived = ref(false)
const jobDocuments = ref([])
const standards = ref([])
const standardDrawerOpen = ref(false)
const generatingStandard = ref(false)
const generationNote = ref('')
const wordInput = ref(null)
const wordCategory = ref('persona')
const wordUploading = ref(false)
const selectedVersions = computed(() => selected.value ? resumes.value.filter((item) => item.candidate === selected.value.candidate || item.candidate_name === selected.value.candidate_name) : [])
const fileStatusLabel = (resume) => resume.file_available ? '已入库' : '文件不可用'
const currentStandard = computed(() => standards.value.find((item) => item.status === 'draft') || standards.value.find((item) => item.status === 'published') || standards.value[0] || null)
let loadSequence = 0

async function loadResumes() {
  if (!currentJob.value) return
  const sequence = ++loadSequence
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ job: String(currentJob.value.id) })
    if (showArchived.value) params.set('archived', '1')
    const result = listItems(await api(`recruitment/resumes/?${params}`))
    if (sequence === loadSequence) resumes.value = result
  } catch (err) {
    if (sequence === loadSequence) error.value = err.message
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function loadJobDocuments() {
  if (!currentJob.value) return
  try { jobDocuments.value = listItems(await api(`recruitment/job-documents/?job=${currentJob.value.id}`)) }
  catch (err) { error.value = err.message }
}

async function loadStandards() {
  if (!currentJob.value) return
  try { standards.value = listItems(await api(`recruitment/job-standards/?job=${currentJob.value.id}`)) }
  catch (err) { error.value = err.message }
}

async function generateStandard() {
  if (!currentJob.value || !jobDocuments.value.length) return
  generatingStandard.value = true; error.value = ''; generationNote.value = ''
  try {
    const result = await api('recruitment/job-standards/generate/', { method: 'POST', body: JSON.stringify({ job: currentJob.value.id }) })
    generationNote.value = result.status === 'waiting_config' ? '等待配置大模型后生成' : '标准草稿正在后台生成'
    window.setTimeout(loadStandards, 1200)
  } catch (err) { error.value = err.message }
  finally { generatingStandard.value = false }
}

function replaceStandard(standard) {
  const index = standards.value.findIndex((item) => item.id === standard.id)
  if (index >= 0) standards.value.splice(index, 1, standard)
  else standards.value.unshift(standard)
}

async function uploadWord(event) {
  const file = event.target.files?.[0]
  if (!file || !currentJob.value) return
  wordUploading.value = true; error.value = ''
  try {
    const body = new FormData()
    body.append('job', String(currentJob.value.id))
    body.append('category', wordCategory.value)
    body.append('title', file.name.replace(/\.(docx?|DOCX?)$/, ''))
    body.append('file', file)
    await api('recruitment/job-documents/', { method: 'POST', body })
    await Promise.all([loadJobDocuments(), loadStandards()])
  } catch (err) { error.value = err.message }
  finally { wordUploading.value = false; event.target.value = '' }
}

function resumeFormat(resume) {
  return resume.content_type === 'image/png' ? 'PNG 在线简历' : 'PDF 附件简历'
}

async function archiveJobDocument(document) {
  try {
    await api(`recruitment/job-documents/${document.id}/archive/`, { method: 'POST' })
    jobDocuments.value = jobDocuments.value.filter((item) => item.id !== document.id)
  } catch (err) { error.value = err.message }
}

watch(
  () => currentJob.value?.id,
  async () => {
    loadSequence += 1
    resumes.value = []
    selected.value = null
    lifecycleTarget.value = null
    showArchived.value = false
    error.value = ''
    loading.value = Boolean(currentJob.value)
    standards.value = []
    standardDrawerOpen.value = false
    generationNote.value = ''
    if (currentJob.value) await Promise.all([loadResumes(), loadJobDocuments(), loadStandards()])
  },
  { immediate: true },
)

async function archiveResume() {
  if (!lifecycleTarget.value) return
  lifecycleSaving.value = true; error.value = ''
  try {
    await api(`recruitment/resumes/${lifecycleTarget.value.id}/archive/`, { method: 'POST' })
    if (selected.value?.id === lifecycleTarget.value.id) selected.value = null
    lifecycleTarget.value = null
    await loadResumes()
  } catch (err) { error.value = err.message }
  finally { lifecycleSaving.value = false }
}

async function restoreResume(resume) {
  error.value = ''
  try {
    await api(`recruitment/resumes/${resume.id}/restore/?archived=1`, { method: 'POST' })
    await loadResumes()
  } catch (err) { error.value = err.message }
}

async function toggleArchiveView() {
  showArchived.value = !showArchived.value
  selected.value = null
  await loadResumes()
}
</script>

<template>
  <div class="page-stack">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div>
        <span class="eyebrow">Resume Library</span>
        <h2>简历中心</h2>
        <p>{{ currentJob ? `${currentJob.title} · 统一管理 BOSS 在线简历与候选人 PDF 附件` : '选择职位后查看对应简历资产' }}</p>
      </div>
      <div v-if="currentJob" class="recruitment-toolbar__actions"><button class="text-button" data-test="toggle-archived-resumes" type="button" @click="toggleArchiveView">{{ showArchived ? '返回当前简历' : '归档记录' }}</button><RecruitmentDemoMenu v-if="!showArchived" @changed="loadResumes" /></div>
    </header>

    <section v-if="!currentJob" class="panel job-context-required"><AppIcon name="document" :size="25" /><div><strong>请先选择在招职位</strong><p>简历按候选人的应聘职位归档，选择职位后才能预览和管理。</p></div></section>

    <template v-else>
    <p v-if="error" class="recruitment-error-strip">{{ error }}</p>

    <section
      v-if="!showArchived"
      class="panel resume-screening-preview"
      data-test="resume-screening-preview"
      aria-labelledby="resume-screening-preview-title"
    >
      <div class="resume-screening-preview__intro">
        <span class="resume-screening-preview__icon"><AppIcon name="sparkles" :size="21" /></span>
        <div>
          <div class="resume-screening-preview__heading">
            <span class="panel-kicker">EVALUATION BLUEPRINT</span>
            <span :class="['recruitment-chip', { 'resume-screening-preview__status': !currentStandard }]">{{ currentStandard?.status_label || '尚未生成' }}</span>
          </div>
          <h3 id="resume-screening-preview-title">岗位评分标准</h3>
          <p v-if="currentStandard">V{{ currentStandard.version }} · {{ currentStandard.criteria?.dimensions?.length || 0 }} 个评分维度。{{ currentStandard.status === 'published' ? '已锁定，可用于简历评分。' : '等待 HR 检查权重、依据和待确认问题。' }}</p>
          <p v-else>上传 Word 用户画像与招聘需求，由模型整理成草稿；HR 确认后才会用于简历评分。</p>
        </div>
      </div>

      <div class="standard-card-metrics">
        <div><span>来源文档</span><strong>{{ jobDocuments.length }}</strong></div>
        <div><span>评分维度</span><strong>{{ currentStandard?.criteria?.dimensions?.length || 0 }}</strong></div>
        <div><span>当前版本</span><strong>{{ currentStandard ? `V${currentStandard.version}` : '—' }}</strong></div>
      </div>

      <div class="resume-screening-preview__actions">
        <label class="resume-word-category"><span>文档用途</span><select v-model="wordCategory"><option value="persona">候选人画像</option><option value="requirement">招聘需求</option><option value="other">其他标准</option></select></label>
        <input ref="wordInput" data-test="word-file-input" type="file" accept=".doc,.docx" hidden @change="uploadWord" />
        <button class="secondary-button button-with-icon resume-screening-preview__action" data-test="word-upload" type="button" :disabled="wordUploading" @click="wordInput?.click()"><AppIcon name="upload" :size="16" /><span>{{ wordUploading ? '上传中…' : '上传 Word' }}</span></button>
        <button v-if="currentStandard" class="primary-button resume-screening-preview__action" data-test="open-standard" type="button" @click="standardDrawerOpen = true">{{ currentStandard.status === 'draft' ? '检查并确认' : '查看标准' }}</button>
        <button v-else class="primary-button resume-screening-preview__action" data-test="generate-standard" type="button" :disabled="generatingStandard || !jobDocuments.length" @click="generateStandard">{{ generatingStandard ? '生成中…' : '生成标准' }}</button>
        <small>{{ generationNote || (jobDocuments.length ? `已归档 ${jobDocuments.length} 份岗位标准文档` : '先上传至少一份 Word 文档') }}</small>
      </div>
    </section>

    <section v-if="!showArchived && jobDocuments.length" class="resume-requirement-docs">
      <article v-for="document in jobDocuments" :key="document.id">
        <a :href="`/api/recruitment/job-document-versions/${document.current_version.id}/file/`"><AppIcon name="document" :size="17" /><span><strong>{{ document.title }}</strong><small>{{ document.category_label }} · V{{ document.current_version.version }} · {{ formatRecruitmentDate(document.updated_at) }}</small></span><AppIcon name="download" :size="14" /></a>
        <button type="button" :data-test="`archive-job-document-${document.id}`" aria-label="移除岗位标准文档" @click="archiveJobDocument(document)">×</button>
      </article>
    </section>

    <section class="recruitment-data-shell">
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>候选人</th><th>应聘职位</th><th>文件</th><th>来源</th><th>更新时间</th><th>文件状态</th><th></th></tr></thead>
          <tbody>
            <tr v-for="resume in resumes" :key="resume.id">
              <td><strong>{{ resume.candidate_name }}</strong></td>
              <td>{{ resume.job_title || '—' }}</td>
              <td><strong class="recruitment-file-name">{{ resume.original_name }}</strong><small class="block-text">{{ resumeFormat(resume) }} · {{ formatFileSize(resume.file_size) }} · V{{ resume.version || 1 }}</small></td>
              <td>{{ resume.source_label }}</td>
              <td>{{ formatRecruitmentDate(resume.updated_at) }}</td>
              <td>
                <span v-if="resume.file_available" class="recruitment-chip">{{ fileStatusLabel(resume) }}</span>
                <span v-else class="recruitment-chip recruitment-chip--error">文件不可用</span>
              </td>
              <td class="recruitment-resume-actions">
                <button v-if="resume.file_available" :data-test="`preview-${resume.id}`" type="button" class="text-button button-with-icon" @click="selected = resume"><AppIcon name="eye" :size="16" /><span>预览</span></button>
                <a v-if="resume.file_available" :data-test="`download-${resume.id}`" class="button-with-icon" :href="resume.download_url"><AppIcon name="download" :size="16" /><span>下载</span></a>
                <button v-if="showArchived" :data-test="`restore-resume-${resume.id}`" type="button" class="text-button" @click="restoreResume(resume)">恢复</button>
                <button v-else :data-test="`archive-resume-${resume.id}`" type="button" class="danger-text-button" @click="lifecycleTarget = resume">归档</button>
              </td>
            </tr>
            <tr v-if="!loading && !resumes.length"><td colspan="7" class="table-empty">{{ showArchived ? '该职位暂无已归档简历' : `该职位暂无简历，可通过主动寻访拉取在线简历，或从沟通消息归档 PDF 附件。` }}</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <RecruitmentDetailDrawer v-if="selected" :title="`${selected.candidate_name}的简历`" @close="selected = null">
      <dl class="recruitment-detail-grid recruitment-detail-grid--resume">
        <div><dt>应聘职位</dt><dd>{{ selected.job_title || '—' }}</dd></div>
        <div><dt>文件大小</dt><dd>{{ formatFileSize(selected.file_size) }}</dd></div>
        <div><dt>数据来源</dt><dd>{{ selected.source_label }}</dd></div>
        <div><dt>文件状态</dt><dd>{{ fileStatusLabel(selected) }}</dd></div>
        <div><dt>版本</dt><dd>V{{ selected.version || 1 }}</dd></div>
        <div><dt>文件指纹</dt><dd class="resume-hash">{{ selected.sha256 ? selected.sha256.slice(0, 12) : '历史文件' }}</dd></div>
      </dl>
      <section v-if="selectedVersions.length > 1" class="resume-version-list"><span>历史版本</span><button v-for="version in selectedVersions" :key="version.id" type="button" :class="{ active: version.id === selected.id }" @click="selected = version"><strong>V{{ version.version || 1 }}</strong><small>{{ formatRecruitmentDate(version.acquired_at || version.updated_at) }}</small></button></section>
      <img v-if="selected.file_available && selected.content_type === 'image/png'" class="recruitment-image-preview" :src="selected.preview_url" :alt="`${selected.candidate_name}的在线简历`" />
      <iframe
        v-else-if="selected.file_available"
        class="recruitment-pdf-preview"
        :src="selected.preview_url"
        :title="`${selected.candidate_name}的简历`"
      ></iframe>
      <div v-else class="recruitment-file-unavailable">简历文件不可用</div>
      <template #footer>
        <a class="secondary-button recruitment-download-link button-with-icon" :href="selected.download_url"><AppIcon name="download" :size="16" /><span>下载{{ selected.content_type === 'image/png' ? '在线简历' : ' PDF' }}</span></a>
      </template>
    </RecruitmentDetailDrawer>
    <ArchiveConfirmModal v-if="lifecycleTarget" title="归档简历" :name="lifecycleTarget.original_name" description="简历会从当前简历中心移除，文件与访问审计暂时保留，可从归档记录恢复。" action-label="确认归档" :saving="lifecycleSaving" @close="lifecycleTarget = null" @confirm="archiveResume" />
    <JobStandardDrawer v-if="standardDrawerOpen" :job="currentJob" :standard="currentStandard" :documents="jobDocuments" @close="standardDrawerOpen = false" @saved="replaceStandard" @published="replaceStandard" @retry="generateStandard" />
    </template>
  </div>
</template>
