<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import AppIcon from '@/components/AppIcon.vue'
import { formatFileSize, formatRecruitmentDate } from '@/recruitment'
import ArchiveConfirmModal from '@/components/ArchiveConfirmModal.vue'

const resumes = ref([])
const selected = ref(null)
const loading = ref(true)
const error = ref('')
const lifecycleTarget = ref(null)
const lifecycleSaving = ref(false)
const showArchived = ref(false)
const selectedVersions = computed(() => selected.value ? resumes.value.filter((item) => item.candidate === selected.value.candidate || item.candidate_name === selected.value.candidate_name) : [])
const fileStatusLabel = (resume) => resume.file_available ? '已入库' : '文件不可用'

async function loadResumes() {
  loading.value = true
  error.value = ''
  try {
    resumes.value = listItems(await api(`recruitment/resumes/${showArchived.value ? '?archived=1' : ''}`))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(loadResumes)

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
        <p>集中管理从招聘渠道取得的 PDF 简历，支持预览、下载、归档与版本管理。</p>
      </div>
      <div class="recruitment-toolbar__actions"><button class="text-button" data-test="toggle-archived-resumes" type="button" @click="toggleArchiveView">{{ showArchived ? '返回当前简历' : '归档记录' }}</button><RecruitmentDemoMenu v-if="!showArchived" @changed="loadResumes" /></div>
    </header>

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
            <span class="panel-kicker">NEXT PHASE</span>
            <span class="recruitment-chip resume-screening-preview__status">下一阶段</span>
          </div>
          <h3 id="resume-screening-preview-title">智能初筛</h3>
          <p>按职位上传 Word 用户画像与招聘需求，系统将据此提取初筛标准并为简历评分。当前仅保留入口，暂不可用。</p>
        </div>
      </div>

      <ol class="resume-screening-preview__steps" aria-label="下一阶段智能初筛流程">
        <li><span>01</span><div><strong>上传 Word</strong><small>用户画像与招聘需求</small></div></li>
        <li><span>02</span><div><strong>提取初筛标准</strong><small>形成可确认的评判依据</small></div></li>
        <li><span>03</span><div><strong>生成简历评分</strong><small>展示得分、证据与结论</small></div></li>
      </ol>

      <div class="resume-screening-preview__actions">
        <button
          class="secondary-button button-with-icon resume-screening-preview__action"
          data-test="future-word-upload"
          type="button"
          disabled
        ><AppIcon name="upload" :size="16" /><span>上传 Word（暂未开放）</span></button>
        <small>不影响当前简历预览、下载与归档</small>
      </div>
    </section>

    <section class="recruitment-data-shell">
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>候选人</th><th>应聘职位</th><th>文件</th><th>来源</th><th>更新时间</th><th>文件状态</th><th></th></tr></thead>
          <tbody>
            <tr v-for="resume in resumes" :key="resume.id">
              <td><strong>{{ resume.candidate_name }}</strong></td>
              <td>{{ resume.job_title || '—' }}</td>
              <td><strong class="recruitment-file-name">{{ resume.original_name }}</strong><small class="block-text">PDF · {{ formatFileSize(resume.file_size) }} · V{{ resume.version || 1 }}</small></td>
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
            <tr v-if="!loading && !resumes.length"><td colspan="7" class="table-empty">{{ showArchived ? '暂无已归档简历' : '暂无简历，可从“演示数据”加载 3 份 PDF。' }}</td></tr>
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
      <iframe
        v-if="selected.file_available"
        class="recruitment-pdf-preview"
        :src="selected.preview_url"
        :title="`${selected.candidate_name}的简历`"
      ></iframe>
      <div v-else class="recruitment-file-unavailable">简历文件不可用</div>
      <template #footer>
        <a class="secondary-button recruitment-download-link button-with-icon" :href="selected.download_url"><AppIcon name="download" :size="16" /><span>下载 PDF</span></a>
      </template>
    </RecruitmentDetailDrawer>
    <ArchiveConfirmModal v-if="lifecycleTarget" title="归档简历" :name="lifecycleTarget.original_name" description="简历会从当前简历中心移除，文件与访问审计暂时保留，可从归档记录恢复。" action-label="确认归档" :saving="lifecycleSaving" @close="lifecycleTarget = null" @confirm="archiveResume" />
  </div>
</template>
