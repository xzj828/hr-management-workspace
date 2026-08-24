<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import AppIcon from '@/components/AppIcon.vue'
import { formatFileSize, formatRecruitmentDate } from '@/recruitment'

const resumes = ref([])
const selected = ref(null)
const loading = ref(true)
const error = ref('')
const selectedVersions = computed(() => selected.value ? resumes.value.filter((item) => item.candidate === selected.value.candidate || item.candidate_name === selected.value.candidate_name) : [])

async function loadResumes() {
  loading.value = true
  error.value = ''
  try {
    resumes.value = listItems(await api('recruitment/resumes/'))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(loadResumes)
</script>

<template>
  <div class="page-stack">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div>
        <span class="eyebrow">Resume Library</span>
        <h2>简历中心</h2>
        <p>集中管理从招聘渠道取得的 PDF 简历，评分能力将在后续接入。</p>
      </div>
      <RecruitmentDemoMenu @changed="loadResumes" />
    </header>

    <p v-if="error" class="recruitment-error-strip">{{ error }}</p>

    <section class="recruitment-data-shell">
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>候选人</th><th>应聘职位</th><th>文件</th><th>来源</th><th>更新时间</th><th>处理状态</th><th></th></tr></thead>
          <tbody>
            <tr v-for="resume in resumes" :key="resume.id">
              <td><strong>{{ resume.candidate_name }}</strong></td>
              <td>{{ resume.job_title || '—' }}</td>
              <td><strong class="recruitment-file-name">{{ resume.original_name }}</strong><small class="block-text">PDF · {{ formatFileSize(resume.file_size) }} · V{{ resume.version || 1 }}</small></td>
              <td>{{ resume.source_label }}</td>
              <td>{{ formatRecruitmentDate(resume.updated_at) }}</td>
              <td>
                <span v-if="resume.file_available" class="recruitment-chip">{{ resume.status_label }}</span>
                <span v-else class="recruitment-chip recruitment-chip--error">文件不可用</span>
              </td>
              <td class="recruitment-resume-actions">
                <button v-if="resume.file_available" :data-test="`preview-${resume.id}`" type="button" class="text-button button-with-icon" @click="selected = resume"><AppIcon name="eye" :size="16" /><span>预览</span></button>
                <a v-if="resume.file_available" :data-test="`download-${resume.id}`" class="button-with-icon" :href="resume.download_url"><AppIcon name="download" :size="16" /><span>下载</span></a>
              </td>
            </tr>
            <tr v-if="!loading && !resumes.length"><td colspan="7" class="table-empty">暂无简历，可从“演示数据”加载 3 份 PDF。</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <RecruitmentDetailDrawer v-if="selected" :title="`${selected.candidate_name}的简历`" @close="selected = null">
      <dl class="recruitment-detail-grid recruitment-detail-grid--resume">
        <div><dt>应聘职位</dt><dd>{{ selected.job_title || '—' }}</dd></div>
        <div><dt>文件大小</dt><dd>{{ formatFileSize(selected.file_size) }}</dd></div>
        <div><dt>数据来源</dt><dd>{{ selected.source_label }}</dd></div>
        <div><dt>处理状态</dt><dd>{{ selected.status_label }}</dd></div>
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
  </div>
</template>
