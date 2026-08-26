<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  resume: { type: Object, required: true },
  structure: { type: Object, default: null },
  assessment: { type: Object, default: null },
  assessments: { type: Array, default: () => [] },
  tasks: { type: Array, default: () => [] },
  contextError: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'retry-structure', 'score', 'rescore'])
const activeTab = ref('original')
const focusedEvidence = ref('')
const panel = ref(null)
const closeButton = ref(null)
const tabs = [
  { key: 'original', label: '原始简历' },
  { key: 'structured', label: '结构化信息' },
  { key: 'evidence', label: '评分与证据' },
  { key: 'history', label: '历史版本' },
]
const latestTask = computed(() => props.tasks[0] || null)
const structureTask = computed(() => props.tasks.find((item) => item.kind === 'resume_structure'))
const scoreTask = computed(() => props.tasks.find((item) => item.kind === 'resume_score'))
const isBusy = computed(() => ['waiting_config', 'pending', 'extracting', 'ocr', 'model'].includes(latestTask.value?.status))
const display = (value) => value === null || value === undefined || value === '' ? '信息不足' : value

function showEvidence(blockId) {
  focusedEvidence.value = blockId
  activeTab.value = 'original'
}

function close() {
  emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const controls = [...panel.value.querySelectorAll('button:not(:disabled), [href], iframe, [tabindex]:not([tabindex="-1"])')]
  if (!controls.length) return
  const first = controls[0]
  const last = controls[controls.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  closeButton.value?.focus()
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="drawer-backdrop" role="presentation" @click.self="close">
    <aside ref="panel" class="intelligence-panel" role="dialog" aria-modal="true" aria-label="简历智能分析" :aria-busy="loading">
      <header class="intelligence-panel__header">
        <div><span class="eyebrow">Evidence-led Review</span><h2>{{ resume.candidate_name }}</h2><p>{{ resume.original_name }} · AI 结论仅供 HR 复核</p></div>
        <button ref="closeButton" type="button" aria-label="关闭" @click="close">×</button>
      </header>
      <nav class="intelligence-tabs" aria-label="简历分析视图">
        <button v-for="tab in tabs" :key="tab.key" :data-test="`tab-${tab.key}`" :aria-selected="activeTab === tab.key" @click="activeTab = tab.key">{{ tab.label }}</button>
      </nav>

      <main class="intelligence-panel__body">
        <div v-if="contextError" class="intelligence-task-state intelligence-task-state--error" role="status" data-test="intelligence-context-error"><AppIcon name="alert-circle" :size="20" /><div><strong>部分记录暂未加载</strong><p>{{ contextError }}</p></div></div>
        <div v-if="loading" class="intelligence-task-state" role="status" data-test="intelligence-detail-loading"><span class="intelligence-pulse"></span><div><strong>正在加载完整分析报告</strong><p>排名摘要仍可查看；结构化字段、证据和历史版本将在加载后显示。</p></div></div>
        <div v-else-if="isBusy" class="intelligence-task-state"><span class="intelligence-pulse"></span><div><strong>{{ latestTask.status_label || '正在处理' }}</strong><p>{{ latestTask.status === 'waiting_config' ? '请先通过“切换模型”新增并测试可用模型。' : '后台任务正在提取和整理信息，可离开此页。' }}</p></div></div>
        <div v-else-if="latestTask?.status === 'failed'" class="intelligence-task-state intelligence-task-state--error"><AppIcon name="alert-circle" :size="20" /><div><strong>处理失败</strong><p>{{ latestTask.error_message || '任务未完成，请重试。' }}</p></div><button v-if="structureTask?.status === 'failed'" class="secondary-button" data-test="retry-structure" @click="emit('retry-structure')">重新解析</button></div>

        <section v-if="activeTab === 'original'" class="intelligence-original">
          <p v-if="focusedEvidence" class="evidence-focus"><AppIcon name="search" :size="15" />正在核对证据块 <strong>{{ focusedEvidence }}</strong></p>
          <img v-if="resume.file_available !== false && resume.preview_url && resume.content_type === 'image/png'" :src="resume.preview_url" :alt="`${resume.candidate_name}的原始简历`" />
          <iframe v-else-if="resume.file_available !== false && resume.preview_url" :src="resume.preview_url" :title="`${resume.candidate_name}的原始简历`"></iframe>
          <div v-else class="intelligence-empty"><h3>原始文件暂不可预览</h3><p>文件恢复后可在这里核对原件；当前结构化信息与分析报告仍可查看。</p></div>
        </section>

        <section v-else-if="activeTab === 'structured'" class="structured-resume-view">
          <div v-if="structure" class="structured-facts">
            <article><span>姓名</span><strong>{{ display(structure.data?.basics?.name) }}</strong></article>
            <article><span>目标岗位</span><strong>{{ display(structure.data?.basics?.target_role) }}</strong></article>
            <article><span>所在城市</span><strong>{{ display(structure.data?.basics?.city) }}</strong></article>
            <article><span>经验月数</span><strong>{{ display(structure.data?.total_experience_months) }}</strong></article>
          </div>
          <div v-if="structure" class="structured-section"><span class="panel-kicker">PROFILE SUMMARY</span><h3>职业摘要</h3><p>{{ display(structure.data?.summary) }}</p></div>
          <div v-if="structure" class="structured-section"><span class="panel-kicker">SKILLS</span><h3>技能</h3><div class="structured-skills"><span v-for="skill in structure.data?.skills || []" :key="typeof skill === 'string' ? skill : skill.name">{{ typeof skill === 'string' ? skill : skill.name }}</span><em v-if="!structure.data?.skills?.length">信息不足</em></div></div>
          <div v-if="structure?.warnings?.length" class="structure-warnings"><strong>需要 HR 留意</strong><p v-for="warning in structure.warnings" :key="warning">{{ warning }}</p></div>
          <div v-if="!structure && !isBusy" class="intelligence-empty"><h3>尚未完成结构化</h3><p>系统会在简历归档后自动提取；也可以手动重新解析。</p><button class="secondary-button" data-test="retry-structure" @click="emit('retry-structure')">开始解析</button></div>
        </section>

        <section v-else-if="activeTab === 'evidence'" class="assessment-view">
          <template v-if="assessment">
            <header class="assessment-summary"><div><span>综合得分</span><strong>{{ Number(assessment.total_score) }}</strong><small>/ 100</small></div><div><span class="recommendation-note">AI 建议，需 HR 复核</span><h3>{{ assessment.recommendation_label }}</h3><p>置信度 {{ Math.round(Number(assessment.confidence) * 100) }}%</p></div></header>
            <div class="assessment-dimensions">
              <article v-for="failure in assessment.hard_failures || []" :key="`hard-${failure.criterion_key}`" class="hard-failure-card"><header><strong>重点项差距 · {{ failure.text }}</strong><span>重点评分项</span></header><p>{{ failure.reason }}</p><div class="evidence-chips"><button v-for="blockId in failure.resume_evidence_block_ids" :key="blockId" :data-test="`evidence-${blockId}`" @click="showEvidence(blockId)">{{ blockId }}</button></div></article>
              <article v-for="dimension in assessment.dimension_scores" :key="dimension.criterion_key">
                <header><strong>{{ dimension.criterion_name || dimension.criterion_key }}</strong><span>{{ dimension.score }} / {{ dimension.max_score }}</span></header>
                <div class="score-track"><i :style="{ width: `${Math.min(100, (Number(dimension.score) / Math.max(1, Number(dimension.max_score))) * 100)}%` }"></i></div>
                <p>{{ dimension.reason || '未提供判断说明' }}</p>
                <div class="evidence-chips"><button v-for="blockId in dimension.resume_evidence_block_ids || []" :key="blockId" :data-test="`evidence-${blockId}`" @click="showEvidence(blockId)">{{ blockId }}</button><span v-if="!dimension.resume_evidence_block_ids?.length">无原文证据 · 该维度不得分</span></div>
              </article>
            </div>
            <div v-if="assessment.gaps?.length || assessment.verification_questions?.length" class="assessment-review-notes"><div><strong>信息缺口</strong><p v-for="gap in assessment.gaps" :key="gap">{{ gap }}</p></div><div><strong>建议核实</strong><p v-for="question in assessment.verification_questions" :key="question">{{ question }}</p></div></div>
          </template>
          <div v-else-if="!structure" class="intelligence-empty"><h3>先完成简历结构化</h3><p>结构化完成后才能按已启用标准评分。</p></div>
          <div v-else class="intelligence-empty"><h3>尚未评分</h3><p>评分只使用已确认的岗位标准，并要求每项得分引用原文证据。</p><button class="primary-button" :disabled="scoreTask && isBusy" @click="emit('score')">开始评分</button></div>
        </section>

        <section v-else class="intelligence-history">
          <article v-for="item in assessments.length ? assessments : (assessment ? [assessment] : [])" :key="item.id"><span>评分 V{{ item.version }}</span><strong>{{ Number(item.total_score) }} 分</strong><small>{{ item.recommendation_label }} · {{ item.model_name }}</small></article>
          <div v-if="!assessment" class="intelligence-empty"><h3>暂无评分历史</h3><p>每次重新评分都会保留独立版本。</p></div>
        </section>
      </main>
      <footer class="intelligence-panel__footer"><span>评分仅作参考，不会自动淘汰或推进候选人</span><button v-if="assessment" class="secondary-button" @click="emit('rescore')">重新评分</button><a v-if="resume.file_available !== false && resume.download_url" class="ghost-button" :href="resume.download_url">下载原文件</a></footer>
    </aside>
  </div>
</template>

<style scoped>
.hard-failure-card{border-color:#efc8cb!important;background:#fff7f7!important}.hard-failure-card header strong,.hard-failure-card header span{color:#a63e47!important}
</style>
