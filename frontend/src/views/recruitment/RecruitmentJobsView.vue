<script setup>
import { onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import { formatRecruitmentDate } from '@/recruitment'

const jobs = ref([])
const selected = ref(null)
const loading = ref(true)
const error = ref('')

const statusLabels = { open: '招聘中', paused: '已暂停', closed: '已关闭' }

async function loadJobs() {
  loading.value = true
  error.value = ''
  try {
    jobs.value = listItems(await api('recruitment/jobs/'))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function openJob(job) {
  selected.value = job
}

onMounted(loadJobs)
</script>

<template>
  <div class="page-stack">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div>
        <span class="eyebrow">Position Portfolio</span>
        <h2>职位管理</h2>
        <p>集中查看在招职位、负责人和候选人分布。</p>
      </div>
      <RecruitmentDemoMenu @changed="loadJobs" />
    </header>

    <p v-if="error" class="recruitment-error-strip">{{ error }}</p>

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
            <tr v-if="!loading && !jobs.length"><td colspan="6" class="table-empty">暂无职位，可从“演示数据”加载示例。</td></tr>
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
    </RecruitmentDetailDrawer>
  </div>
</template>
