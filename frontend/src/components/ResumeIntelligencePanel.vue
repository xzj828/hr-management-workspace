<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import ResumeDocumentViewer from '@/components/ResumeDocumentViewer.vue'

const props = defineProps({
  resume: { type: Object, required: true },
  structure: { type: Object, default: null },
  assessment: { type: Object, default: null },
  assessments: { type: Array, default: () => [] },
  tasks: { type: Array, default: () => [] },
  contextError: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'retry-structure', 'retry-report', 'score', 'rescore', 'purge'])

const panel = ref(null)
const closeButton = ref(null)
const originalVisible = ref(false)
const latestTask = computed(() => props.tasks[0] || null)
const structureTask = computed(() => props.tasks.find((item) => item.kind === 'resume_structure'))
const scoreTask = computed(() => props.tasks.find((item) => item.kind === 'resume_score'))
const isBusy = computed(() => ['waiting_config', 'pending', 'extracting', 'ocr', 'model'].includes(latestTask.value?.status))

const basics = computed(() => props.structure?.data?.basics || {})
const candidateName = computed(() => props.resume.candidate_name || basics.value.name || '候选人')
const candidateInitial = computed(() => candidateName.value.replace(/\*/g, '').trim().slice(0, 1) || '候')
const targetRole = computed(() => basics.value.target_role || props.resume.job_title || '目标岗位待确认')
const currentTitle = computed(() => basics.value.current_title || basics.value.current_role || '当前职位待确认')
const profileMeta = computed(() => {
  const values = [basics.value.education || basics.value.degree]
  const months = Number(props.structure?.data?.total_experience_months)
  if (Number.isFinite(months) && months > 0) values.push(`${Math.max(1, Math.round(months / 12))}年`)
  return values.filter(Boolean).join(' · ')
})
const recommendation = computed(() => props.assessment?.system_recommendation_label || props.assessment?.recommendation_label || (isBusy.value || props.loading ? 'AI 分析中' : '等待 AI 分析'))
const isEvidencePolicy = computed(() => props.assessment?.scoring_policy_version === 'evidence-level-v1')
const scoreLabel = computed(() => props.assessment ? Number(props.assessment.total_score || 0).toFixed(isEvidencePolicy.value ? 1 : 0) : '—')

function normalizedSkill(skill) {
  if (typeof skill === 'string') return skill.trim()
  return String(skill?.name || skill?.label || '').trim()
}

function compactText(value, maxLength) {
  const text = String(value || '').replace(/\s+/g, ' ').trim().replace(/[。；，、,.!?！？]+$/u, '')
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text
}

const keywords = computed(() => {
  const values = [
    ...(props.structure?.data?.skills || []).map(normalizedSkill),
    ...(props.assessment?.dimension_scores || []).map((item) => item.criterion_name || item.criterion_key),
  ]
  return [...new Set(values.filter(Boolean))].slice(0, 13)
})

const analysisParagraphs = computed(() => {
  if (!props.assessment) return []
  const persisted = props.assessment.analysis_report
  if (persisted?.overview && persisted?.strengths && persisted?.gaps_and_interview_focus) {
    return [persisted.overview, persisted.strengths, persisted.gaps_and_interview_focus]
  }
  if (isEvidencePolicy.value) return []
  const summary = String(props.structure?.data?.summary || '').trim()
  const dimensions = (props.assessment.dimension_scores || [])
    .map((item) => String(item.reason || '').trim())
    .filter(Boolean)
  const gaps = [
    ...(props.assessment.hard_failures || []).map((item) => item.reason || item.text),
    ...(props.assessment.gaps || []),
  ].map((item) => String(item || '').trim()).filter(Boolean)
  const questions = (props.assessment.verification_questions || []).map((item) => String(item || '').trim()).filter(Boolean)
  const skillText = keywords.value.slice(0, 4).join('、')
  const summaryText = compactText(summary, 72)
  const dimensionText = compactText(dimensions.slice(0, 2).join('；'), 104)
  const gapText = compactText(gaps.slice(0, 2).join('；'), 56)
  const questionText = compactText(questions.slice(0, 2).join('；'), 56)

  return [
    summaryText
      ? `${summaryText}。`
      : `候选人的简历信息已完成结构化整理，本次分析围绕${targetRole.value}的岗位要求，并结合现有项目、职责与技能证据进行核对。`,
    dimensions.length
      ? `${dimensionText}。`
      : `${skillText ? `简历中已识别出${skillText}等关键词。` : '简历中的明确技能证据仍然有限。'}当前报告仅基于已归档材料形成，不对缺失信息进行推测。`,
    gaps.length || questions.length
      ? `${gapText ? `仍需关注：${gapText}。` : ''}${questionText ? `后续沟通建议核实${questionText}。` : ''}AI 建议为“${recommendation.value}”，最终判断仍由 HR 复核。`
      : `综合现有证据，候选人与目标岗位的匹配情况已形成初步判断，AI 建议为“${recommendation.value}”。建议 HR 结合面试表现与业务团队意见完成最终复核。`,
  ]
})

function close() {
  emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    if (originalVisible.value) return
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
  <div class="resume-evidence-backdrop" role="presentation" @click.self="close">
    <aside ref="panel" class="resume-evidence-card" role="dialog" aria-modal="true" aria-label="证据详情" :aria-busy="loading">
      <header class="resume-evidence-card__header">
        <h2>证据详情</h2>
        <button ref="closeButton" type="button" aria-label="关闭" @click="close"><AppIcon name="close" :size="20" /></button>
      </header>

      <main class="resume-evidence-card__body">
        <section class="candidate-summary" aria-label="候选人摘要">
          <span class="candidate-summary__avatar" aria-hidden="true">{{ candidateInitial }}</span>
          <div class="candidate-summary__identity">
            <div><h3>{{ candidateName }}</h3><span v-if="profileMeta">{{ profileMeta }}</span></div>
            <p>当前：{{ currentTitle }}</p>
          </div>
          <div class="candidate-summary__recommendation">
            <span>推荐状态</span>
            <strong><i></i>{{ recommendation }}</strong>
          </div>
        </section>

        <div class="resume-evidence-card__divider"></div>

        <section class="target-role">
          <span>目标岗位</span>
          <strong>{{ targetRole }}</strong>
        </section>

        <section v-if="assessment" class="score-summary" aria-label="系统评分结果">
          <div><span>后端总分</span><strong>{{ scoreLabel }}</strong><small v-if="assessment.passing_score_snapshot">及格线 {{ Number(assessment.passing_score_snapshot).toFixed(0) }}</small></div>
          <div><span>系统判定</span><strong>{{ recommendation }}</strong><small>标准 V{{ assessment.standard_version }} · {{ assessment.scoring_policy_version }}</small></div>
        </section>

        <div v-if="contextError" class="report-state report-state--error" role="status" data-test="intelligence-context-error">
          <AppIcon name="alert-circle" :size="18" /><p>{{ contextError }}</p>
        </div>
        <div v-if="loading" class="report-state" role="status" data-test="intelligence-detail-loading">
          <span class="report-state__pulse"></span><p>正在加载完整分析报告…</p>
        </div>
        <div v-else-if="isBusy" class="report-state" role="status">
          <span class="report-state__pulse"></span><p>{{ latestTask.status_label || 'AI 正在提取简历信息并生成分析报告…' }}</p>
        </div>
        <div v-else-if="latestTask?.status === 'failed'" class="report-state report-state--error" role="alert">
          <AppIcon name="alert-circle" :size="18" /><p>{{ latestTask.error_message || '分析任务未完成，请重试。' }}</p>
          <button v-if="structureTask?.status === 'failed'" data-test="retry-structure" type="button" @click="emit('retry-structure')">重新解析</button>
        </div>

        <section class="analysis-report" data-test="ai-analysis-report">
          <h3>AI 分析报告</h3>
          <div v-if="assessment && analysisParagraphs.length" class="analysis-report__copy">
            <p v-for="paragraph in analysisParagraphs" :key="paragraph">{{ paragraph }}</p>
          </div>
          <div v-else-if="isBusy || loading" class="analysis-report__empty"><p>分析完成后，约 200 字的 AI 报告会直接显示在这里。</p></div>
          <div v-else-if="assessment?.report_status === 'failed'" class="analysis-report__empty">
            <p>评分和证据明细已保存，但分析报告生成失败，可以单独重试且不会改变分数。</p>
            <button type="button" data-test="retry-report" @click="emit('retry-report')">重试分析报告</button>
          </div>
          <div v-else-if="latestTask?.status === 'failed'" class="analysis-report__empty"><p>本次分析未完成。问题处理后重新解析，报告会直接显示在此卡片中。</p></div>
          <div v-else-if="!structure" class="analysis-report__empty">
            <p>完成简历结构化后，AI 会基于岗位标准生成分析报告。</p>
            <button data-test="retry-structure" type="button" @click="emit('retry-structure')">开始解析</button>
          </div>
          <div v-else class="analysis-report__empty">
            <p>结构化信息已就绪，可以生成 AI 分析报告。</p>
            <button :disabled="scoreTask && isBusy" type="button" @click="emit('score')">生成分析报告</button>
          </div>
        </section>

        <section v-if="isEvidencePolicy && assessment?.dimension_scores?.length" class="dimension-section">
          <h3>评分证据明细</h3>
          <article v-for="item in assessment.dimension_scores" :key="item.criterion_key">
            <div><strong>{{ item.criterion_name || item.criterion_key }}</strong><span>{{ item.evidence_level }} · {{ item.score }}/{{ item.max_score }}</span></div>
            <p>{{ item.reason }}</p>
            <small v-if="item.status === 'information_missing'">简历未提供相关信息，本项不推断。</small>
            <small v-else-if="item.status === 'contradicted'">原文明确不满足，本项为 L0。</small>
            <small v-else>证据等级由原文场景、本人行动和结果完整度共同确定。</small>
          </article>
        </section>

        <section v-if="keywords.length" class="keyword-section">
          <h3>关键信息提取</h3>
          <div><span v-for="keyword in keywords" :key="keyword">{{ keyword }}</span></div>
        </section>

        <button
          class="original-resume-button"
          data-test="view-original-resume"
          type="button"
          aria-haspopup="dialog"
          @click="originalVisible = true"
        >查看原始简历</button>
      </main>
    </aside>
    <ResumeDocumentViewer v-if="originalVisible" :resume="resume" :candidate-name="candidateName" @close="originalVisible = false" />
  </div>
</template>

<style scoped>
.resume-evidence-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 28px; background: rgba(29, 47, 55, .48); backdrop-filter: blur(9px); -webkit-backdrop-filter: blur(9px); }
.resume-evidence-card { width: min(642px, calc(100vw - 56px)); max-height: calc(100dvh - 48px); display: flex; flex-direction: column; overflow: hidden; color: #223044; background: #fffefc; border: 1px solid rgba(255, 255, 255, .92); border-radius: 16px; box-shadow: 0 30px 70px rgba(32, 45, 54, .24); font-family: var(--app-font-family); animation: detail-card-arrive .22s cubic-bezier(.2,.8,.2,1); }
.resume-evidence-card__header { display: flex; flex: none; align-items: center; justify-content: space-between; padding: 20px 20px 10px 32px; }
.resume-evidence-card__header h2 { margin: 0; color: #1f2e43; font-size: 23px; font-weight: 850; letter-spacing: -.025em; }
.resume-evidence-card__header button { width: 36px; height: 36px; display: grid; place-items: center; color: #5d6874; background: #fff; border: 1px solid #dce2e5; border-radius: 50%; cursor: pointer; transition: 150ms ease; }
.resume-evidence-card__header button:hover { color: #183d3a; border-color: #9fc6c0; background: #f5fbfa; }
.resume-evidence-card__header button:focus-visible { outline: 2px solid rgba(17, 137, 124, .16); outline-offset: 1px; }
.original-resume-button:focus-visible, .analysis-report__empty button:focus-visible, .report-state button:focus-visible { outline: 3px solid rgba(17, 137, 124, .2); outline-offset: 2px; }
.resume-evidence-card__body { flex: 1; overflow-y: auto; padding: 16px 32px 24px; scrollbar-color: #a8bfbb #f4f6f5; }
.candidate-summary { display: grid; grid-template-columns: 46px minmax(0, 1fr) auto; align-items: center; gap: 16px; padding: 7px 0 19px; }
.candidate-summary__avatar { width: 46px; height: 46px; display: grid; place-items: center; color: #fff; background: #2d958d; border-radius: 50%; font-size: 19px; font-weight: 800; box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .24); }
.candidate-summary__identity { min-width: 0; }
.candidate-summary__identity > div { display: flex; align-items: baseline; gap: 14px; }
.candidate-summary__identity h3 { margin: 0; color: #1f2d41; font-size: 19px; font-weight: 850; }
.candidate-summary__identity span, .candidate-summary__identity p, .candidate-summary__recommendation > span { color: #7a8795; font-size: 12px; }
.candidate-summary__identity p { margin: 5px 0 0; }
.candidate-summary__recommendation { min-width: 137px; display: grid; gap: 7px; }
.candidate-summary__recommendation strong { display: inline-flex; align-items: center; gap: 9px; color: #344255; font-size: 13px; font-weight: 750; }
.candidate-summary__recommendation i { width: 8px; height: 8px; border-radius: 50%; background: #178e82; }
.resume-evidence-card__divider { height: 1px; background: #dfe5e7; }
.target-role { display: grid; gap: 5px; padding: 20px 0 18px; }
.target-role span { color: #758292; font-size: 12px; }
.target-role strong { color: #26364a; font-size: 16px; }
.score-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 0 0 18px; }
.score-summary > div { display: grid; gap: 4px; padding: 12px 14px; background: #f5f8f7; border: 1px solid #e0e8e6; border-radius: 10px; }
.score-summary span, .score-summary small { color: #74818e; font-size: 11px; }
.score-summary strong { color: #23384a; font-size: 15px; }
.report-state { display: flex; align-items: center; gap: 10px; margin: -3px 0 17px; padding: 10px 12px; color: #246b64; background: #eff8f6; border-radius: 9px; }
.report-state p { margin: 0; font-size: 12px; line-height: 1.5; }
.report-state button { margin-left: auto; padding: 6px 10px; color: #176f67; background: #fff; border: 1px solid #bcded9; border-radius: 7px; font-weight: 750; cursor: pointer; }
.report-state--error { color: #a63e47; background: #fff3f3; }
.report-state__pulse { width: 8px; height: 8px; flex: none; border-radius: 50%; background: #178e82; animation: task-pulse 1.5s infinite; }
.analysis-report, .keyword-section { display: grid; gap: 11px; }
.analysis-report h3, .keyword-section h3 { margin: 0; color: #405065; font-size: 14px; font-weight: 760; }
.analysis-report__copy { display: grid; gap: 7px; padding-left: 14px; border-left: 3px solid #1e968a; }
.analysis-report__copy p { margin: 0; color: #405065; font-size: 13px; line-height: 1.75; }
.analysis-report__empty { min-height: 116px; display: grid; place-content: center; justify-items: center; gap: 11px; padding: 18px; color: #70808d; background: #f7faf9; border: 1px dashed #cbdad7; border-radius: 10px; text-align: center; }
.analysis-report__empty p { max-width: 390px; margin: 0; font-size: 12px; line-height: 1.7; }
.analysis-report__empty button { min-height: 34px; padding: 0 15px; color: #fff; background: #178e82; border: 0; border-radius: 8px; font-weight: 750; cursor: pointer; }
.keyword-section { margin-top: 24px; }
.dimension-section { display: grid; gap: 10px; margin-top: 24px; }
.dimension-section h3 { margin: 0; color: #405065; font-size: 14px; }
.dimension-section article { display: grid; gap: 5px; padding: 11px 13px; border: 1px solid #e1e7e8; border-radius: 9px; }
.dimension-section article > div { display: flex; justify-content: space-between; gap: 12px; }
.dimension-section article strong { color: #334457; font-size: 12px; }
.dimension-section article span { color: #147d73; font-size: 12px; font-weight: 750; }
.dimension-section p, .dimension-section small { margin: 0; color: #687785; font-size: 11px; line-height: 1.6; }
.keyword-section > div { display: flex; flex-wrap: wrap; gap: 8px 9px; }
.keyword-section span { display: inline-flex; align-items: center; min-height: 30px; padding: 0 14px; color: #36736e; background: #e9f4f2; border-radius: 999px; font-size: 12px; white-space: nowrap; }
.original-resume-button { width: 196px; min-height: 44px; display: block; margin: 38px auto 0; color: #fff; background: #178e82; border: 0; border-radius: 10px; box-shadow: 0 8px 18px rgba(23, 142, 130, .16); font-size: 14px; font-weight: 800; cursor: pointer; transition: 150ms ease; }
.original-resume-button:hover { background: #0f786e; transform: translateY(-1px); }
@keyframes task-pulse { 60% { box-shadow: 0 0 0 8px rgba(23, 142, 130, 0); } }
@keyframes detail-card-arrive { from { opacity: 0; transform: translateY(14px) scale(.985); } }
@media (max-width: 680px) {
  .resume-evidence-backdrop { padding: 12px; }
  .resume-evidence-card { width: calc(100vw - 24px); max-height: calc(100dvh - 24px); border-radius: 14px; }
  .resume-evidence-card__header { padding: 16px 14px 8px 20px; }
  .resume-evidence-card__header h2 { font-size: 20px; }
  .resume-evidence-card__body { padding: 13px 20px 22px; }
  .candidate-summary { grid-template-columns: 42px 1fr; gap: 12px; }
  .candidate-summary__avatar { width: 42px; height: 42px; }
  .candidate-summary__recommendation { grid-column: 2; min-width: 0; }
  .candidate-summary__identity > div { align-items: flex-start; flex-direction: column; gap: 3px; }
  .analysis-report__copy p { font-size: 12px; }
  .score-summary { grid-template-columns: 1fr; }
  .keyword-section span { min-height: 28px; padding: 0 11px; font-size: 11px; }
  .original-resume-button { width: 100%; margin-top: 28px; }
}
@media (prefers-reduced-motion: reduce) {
  .resume-evidence-card, .original-resume-button, .report-state__pulse { animation: none; transition: none; }
}
</style>
