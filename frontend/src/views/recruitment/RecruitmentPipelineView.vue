<script setup>
import { onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import { stageColumns } from '@/recruitment'

const applications = ref([])
const draggedId = ref(null)
const selected = ref(null)
const loading = ref(true)
const error = ref('')

function applicationsFor(stage) {
  return applications.value.filter((application) => application.stage === stage)
}

async function loadApplications() {
  loading.value = true
  error.value = ''
  try {
    applications.value = listItems(await api('recruitment/applications/'))
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function startDrag(application) {
  draggedId.value = application.id
}

async function moveTo(stage) {
  const application = applications.value.find((item) => item.id === draggedId.value)
  draggedId.value = null
  if (!application || application.stage === stage) return

  const previousStage = application.stage
  application.stage = stage
  error.value = ''
  try {
    const saved = await api(`recruitment/applications/${application.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ stage }),
    })
    Object.assign(application, saved)
  } catch (err) {
    application.stage = previousStage
    error.value = err.message
  }
}

onMounted(loadApplications)
</script>

<template>
  <div class="page-stack">
    <header class="page-hero page-hero--compact recruitment-toolbar">
      <div>
        <span class="eyebrow">Hiring Pipeline</span>
        <h2>招聘流程</h2>
        <p>拖动候选人更新阶段，变更会立即保存到本地数据库。</p>
      </div>
      <RecruitmentDemoMenu @changed="loadApplications" />
    </header>

    <p v-if="error" class="recruitment-error-strip">{{ error }}</p>

    <section class="recruitment-board" aria-label="候选人招聘流程">
      <article
        v-for="column in stageColumns"
        :key="column.key"
        class="recruitment-column"
        :data-stage="column.key"
        @dragover.prevent
        @drop.prevent="moveTo(column.key)"
      >
        <header><strong>{{ column.label }}</strong><span>{{ applicationsFor(column.key).length }}</span></header>
        <div class="recruitment-column__cards">
          <button
            v-for="application in applicationsFor(column.key)"
            :key="application.id"
            class="recruitment-candidate-card"
            type="button"
            draggable="true"
            :data-application-id="application.id"
            @dragstart.stop="startDrag(application)"
            @click="selected = application"
          >
            <strong>{{ application.candidate.name }}</strong>
            <span>{{ application.job_title }}</span>
            <small>{{ application.candidate.current_title || '—' }} · {{ application.candidate.current_city || '—' }}</small>
            <i>{{ application.candidate.resume_count ? `${application.candidate.resume_count} 份简历` : '暂无简历' }}</i>
          </button>
          <p v-if="!loading && !applicationsFor(column.key).length" class="recruitment-column__empty">暂无候选人</p>
        </div>
      </article>
    </section>

    <RecruitmentDetailDrawer v-if="selected" :title="selected.candidate.name" @close="selected = null">
      <dl class="recruitment-detail-grid">
        <div><dt>应聘职位</dt><dd>{{ selected.job_title }}</dd></div>
        <div><dt>招聘阶段</dt><dd>{{ stageColumns.find((item) => item.key === selected.stage)?.label || selected.stage_label }}</dd></div>
        <div><dt>当前岗位</dt><dd>{{ selected.candidate.current_title || '—' }}</dd></div>
        <div><dt>所在城市</dt><dd>{{ selected.candidate.current_city || '—' }}</dd></div>
        <div><dt>负责人</dt><dd>{{ selected.owner_name || '未分配' }}</dd></div>
        <div><dt>简历</dt><dd>{{ selected.candidate.resume_count ? `${selected.candidate.resume_count} 份简历` : '暂无简历' }}</dd></div>
      </dl>
    </RecruitmentDetailDrawer>
  </div>
</template>
