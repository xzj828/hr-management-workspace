<script setup>
import { onMounted, ref } from 'vue'
import { api, listItems } from '@/api'
import RecruitmentDemoMenu from '@/components/RecruitmentDemoMenu.vue'
import RecruitmentDetailDrawer from '@/components/RecruitmentDetailDrawer.vue'
import ModalPanel from '@/components/ModalPanel.vue'
import { stageColumns } from '@/recruitment'

const applications = ref([])
const draggedId = ref(null)
const selected = ref(null)
const loading = ref(true)
const error = ref('')
const pendingMove = ref(null)
const stageReason = ref('')

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

function moveTo(stage) {
  const application = applications.value.find((item) => item.id === draggedId.value)
  draggedId.value = null
  if (!application || application.stage === stage) return

  pendingMove.value = { application, stage }
  stageReason.value = ''
}

async function confirmMove() {
  if (!pendingMove.value || !stageReason.value.trim()) return
  const { application, stage } = pendingMove.value
  pendingMove.value = null

  const previousStage = application.stage
  application.stage = stage
  error.value = ''
  try {
    const saved = await api(`recruitment/applications/${application.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ stage, stage_reason: stageReason.value.trim() }),
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
        <p>拖动候选人更新阶段；确认原因后保存，自动与人工变化均可追溯。</p>
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
      <section v-if="selected.stage_history?.length" class="recruitment-detail-section"><span>阶段记录</span><article v-for="history in selected.stage_history" :key="history.id" class="stage-history-line"><strong>{{ history.from_stage }} → {{ history.to_stage }}</strong><small>{{ history.reason }} · {{ history.actor_name || '系统' }}</small></article></section>
    </RecruitmentDetailDrawer>
    <ModalPanel v-if="pendingMove" title="确认阶段变更" @close="pendingMove = null">
      <div class="stage-change-confirm"><p>将 <strong>{{ pendingMove.application.candidate.name }}</strong> 移动到“{{ stageColumns.find((item) => item.key === pendingMove.stage)?.label }}”。</p><label class="field-label">变更原因<textarea v-model="stageReason" data-test="stage-reason" rows="4" maxlength="500" placeholder="例如：已完成电话沟通，进入面试安排"></textarea><small>原因会写入招聘审计记录。</small></label></div>
      <template #footer><button class="secondary-button" @click="pendingMove = null">取消</button><button class="primary-button" data-test="confirm-stage-change" :disabled="!stageReason.trim()" @click="confirmMove">确认变更</button></template>
    </ModalPanel>
  </div>
</template>
