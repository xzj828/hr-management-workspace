<script setup>
import { onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import { stageColumns } from '@/recruitment'

const candidates = ref([])
const jobs = ref([])
const selected = ref(null)
const search = ref('')
const job = ref('')
const stage = ref('')
const loading = ref(true)
const error = ref('')

function primaryApplication(candidate) {
  return candidate.applications?.[0] || null
}

async function loadCandidates() {
  loading.value = true
  error.value = ''
  const params = new URLSearchParams()
  if (search.value.trim()) params.set('search', search.value.trim())
  if (job.value) params.set('job', job.value)
  if (stage.value) params.set('stage', stage.value)
  const query = params.toString()
  try {
    candidates.value = listItems(await api(`recruitment/candidates/${query ? `?${query}` : ''}`))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadWorkspace() {
  try {
    const jobPayload = await api('recruitment/jobs/')
    jobs.value = listItems(jobPayload)
  } catch (err) {
    error.value = err.message
  }
  await loadCandidates()
}

onMounted(loadWorkspace)
</script>

<template>
  <div class="page-stack">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div>
        <span class="eyebrow">Candidate Directory</span>
        <h2>候选人</h2>
        <p>按职位和招聘阶段查找候选人，点击行查看完整资料。</p>
      </div>
      <RecruitmentDemoMenu @changed="loadWorkspace" />
    </header>

    <p v-if="error" class="recruitment-error-strip">{{ error }}</p>

    <section class="recruitment-data-shell">
      <div class="recruitment-filter-row">
        <input v-model="search" data-test="candidate-search" type="search" placeholder="搜索姓名、岗位或城市" @input="loadCandidates" />
        <select v-model="job" aria-label="职位" @change="loadCandidates">
          <option value="">全部职位</option>
          <option v-for="item in jobs" :key="item.id" :value="item.id">{{ item.title }}</option>
        </select>
        <select v-model="stage" data-test="candidate-stage" aria-label="招聘阶段" @change="loadCandidates">
          <option value="">全部阶段</option>
          <option v-for="item in stageColumns" :key="item.key" :value="item.key">{{ item.label }}</option>
        </select>
        <span class="toolbar__count">{{ candidates.length }} 位候选人</span>
      </div>
      <div class="table-scroll">
        <table class="data-table">
          <thead><tr><th>候选人</th><th>当前岗位 / 城市</th><th>应聘职位</th><th>阶段</th><th>负责人</th><th>简历</th></tr></thead>
          <tbody>
            <tr
              v-for="candidate in candidates"
              :key="candidate.id"
              class="recruitment-row"
              tabindex="0"
              @click="selected = candidate"
              @keydown.enter="selected = candidate"
            >
              <td><strong>{{ candidate.name }}</strong></td>
              <td>{{ candidate.current_title || '—' }}<small class="block-text">{{ candidate.current_city || '—' }}</small></td>
              <td>{{ primaryApplication(candidate)?.job_title || '—' }}</td>
              <td><span class="recruitment-chip">{{ primaryApplication(candidate)?.stage_label || '—' }}</span></td>
              <td>{{ primaryApplication(candidate)?.owner_name || '—' }}</td>
              <td>{{ candidate.resume_count ? `${candidate.resume_count} 份简历` : '暂无简历' }}</td>
            </tr>
            <tr v-if="!loading && !candidates.length"><td colspan="6" class="table-empty">没有符合条件的候选人</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <RecruitmentDetailDrawer v-if="selected" :title="selected.name" @close="selected = null">
      <dl class="recruitment-detail-grid">
        <div><dt>当前岗位</dt><dd>{{ selected.current_title || '—' }}</dd></div>
        <div><dt>所在城市</dt><dd>{{ selected.current_city || '—' }}</dd></div>
        <div><dt>电话</dt><dd>{{ selected.phone || '—' }}</dd></div>
        <div><dt>邮箱</dt><dd>{{ selected.email || '—' }}</dd></div>
        <div><dt>简历</dt><dd>{{ selected.resume_count ? `${selected.resume_count} 份简历` : '暂无简历' }}</dd></div>
      </dl>
      <section class="recruitment-detail-section">
        <span>应聘记录</span>
        <article v-for="application in selected.applications" :key="application.id" class="recruitment-application-line">
          <strong>{{ application.job_title }}</strong>
          <small>{{ application.stage_label }} · 负责人 {{ application.owner_name || '未分配' }}</small>
        </article>
      </section>
    </RecruitmentDetailDrawer>
  </div>
</template>
