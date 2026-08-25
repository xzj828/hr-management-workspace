<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '@/api'
import AppIcon from '@/components/AppIcon.vue'

const props = defineProps({
  job: { type: Object, required: true },
  standard: { type: Object, default: null },
  documents: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'saved', 'published', 'retry'])
const form = reactive({ summary: '', dimensions: [], hard_requirements: [], auto_reject_on_hard_fail: false, required: [], preferred: [], risks: [], unresolved_questions: [] })
const saving = ref(false)
const error = ref('')
const confirmPublish = ref(false)
const menuOpen = ref(false)
const isDraft = computed(() => props.standard?.status === 'draft')
const totalWeight = computed(() => form.dimensions.reduce((sum, item) => sum + Number(item.weight || 0), 0))
const canPublish = computed(() => isDraft.value && form.dimensions.length > 0 && Math.abs(totalWeight.value - 100) < 0.001)

function hydrate() {
  const criteria = props.standard?.criteria || {}
  form.summary = criteria.summary || ''
  form.dimensions = (criteria.dimensions || []).map((item) => ({ ...item, evidence_block_ids: [...(item.evidence_block_ids || [])] }))
  form.hard_requirements = (criteria.hard_requirements || []).map((item) => ({ ...item, evidence_block_ids: [...(item.evidence_block_ids || [])] }))
  form.auto_reject_on_hard_fail = criteria.auto_reject_on_hard_fail === true
  form.required = [...(criteria.required || [])]
  form.preferred = [...(criteria.preferred || [])]
  form.risks = [...(criteria.risks || [])]
  form.unresolved_questions = [...(props.standard?.unresolved_questions || [])]
}
watch(() => props.standard, hydrate, { immediate: true, deep: true })

function addDimension() {
  form.dimensions.push({ key: `dimension_${Date.now()}`, name: '新评分维度', weight: 0, description: '', evidence_block_ids: [] })
}
function removeDimension(index) { form.dimensions.splice(index, 1) }
function addHardRequirement() { form.hard_requirements.push({ key: `hard_${Date.now()}`, text: '', evidence_block_ids: [] }) }
function removeHardRequirement(index) { form.hard_requirements.splice(index, 1) }
function payload() {
  return {
    criteria: {
      summary: form.summary.trim(), dimensions: form.dimensions.map((item) => ({ ...item, weight: Number(item.weight || 0) })),
      hard_requirements: form.hard_requirements.map((item) => ({ ...item, text: item.text.trim() })),
      auto_reject_on_hard_fail: form.auto_reject_on_hard_fail,
      required: form.required, preferred: form.preferred, risks: form.risks,
    },
    unresolved_questions: form.unresolved_questions,
  }
}
async function save() {
  if (!props.standard || !isDraft.value) return
  saving.value = true; error.value = ''
  try {
    const result = await api(`recruitment/job-standards/${props.standard.id}/`, { method: 'PATCH', body: JSON.stringify(payload()) })
    emit('saved', result)
  } catch (err) { error.value = err.message }
  finally { saving.value = false }
}
async function publish() {
  saving.value = true; error.value = ''
  try {
    const result = await api(`recruitment/job-standards/${props.standard.id}/publish/`, { method: 'POST' })
    confirmPublish.value = false
    emit('published', result)
  } catch (err) { error.value = err.message }
  finally { saving.value = false }
}
</script>

<template>
  <div class="drawer-backdrop" @click.self="emit('close')">
    <aside class="standard-drawer" aria-label="岗位评分标准">
      <header class="standard-drawer__header">
        <div><span class="eyebrow">Evaluation Blueprint · V{{ standard?.version || '—' }}</span><h2>{{ job.title }}的评分标准</h2><p>模型负责起草，HR 确认后才允许正式评分。</p></div>
        <button class="standard-drawer__close" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="standard-drawer__body">
        <p v-if="error" class="recruitment-error-strip">{{ error }}</p>
        <section v-if="!standard" class="standard-empty"><AppIcon name="document" :size="26" /><h3>尚未生成评分标准</h3><p>先上传岗位画像或招聘需求，再由模型整理成可确认的评分维度。</p></section>
        <template v-else>
          <div class="standard-status-line"><span :class="['standard-state', `standard-state--${standard.status}`]">{{ standard.status_label }}</span><span>{{ documents.length }} 份来源文档</span><span>{{ standard.model_name || '待模型生成' }}</span></div>
          <label class="standard-field standard-field--summary"><span>岗位目标摘要</span><textarea v-model="form.summary" rows="3" :disabled="!isDraft" placeholder="说明这个岗位真正要解决的问题" /></label>
          <section class="hard-requirements">
            <header><div><span class="panel-kicker">HARD GATES</span><h3>硬性指标</h3><p>只有简历出现明确反证才视为不满足；没有写明会交给 HR 核实。</p></div><button v-if="isDraft" class="secondary-button" data-test="add-hard-requirement" @click="addHardRequirement">添加指标</button></header>
            <article v-for="(item, index) in form.hard_requirements" :key="item.key"><span>{{ String(index + 1).padStart(2, '0') }}</span><label><small>指标标识</small><input v-model.trim="item.key" :disabled="!isDraft" placeholder="例如 degree" /></label><label><small>淘汰条件</small><input v-model.trim="item.text" :disabled="!isDraft" placeholder="例如：学历低于本科" /></label><button v-if="isDraft" :data-test="`remove-hard-requirement-${index}`" aria-label="删除硬性指标" @click="removeHardRequirement(index)">×</button></article>
            <label v-if="form.hard_requirements.length" class="hard-reject-toggle"><input v-model="form.auto_reject_on_hard_fail" type="checkbox" :disabled="!isDraft" /><span><strong>明确不满足时自动淘汰</strong><small>会改变招聘阶段并记录触发指标与原文证据；信息不足不会触发。</small></span></label>
          </section>
          <section class="standard-dimensions">
            <header><div><span class="panel-kicker">SCORING DIMENSIONS</span><h3>评分维度</h3></div><strong data-test="weight-total" :class="{ invalid: totalWeight !== 100 }">{{ totalWeight }} / 100</strong></header>
            <article v-for="(dimension, index) in form.dimensions" :key="dimension.key" class="standard-dimension">
              <span class="standard-dimension__number">{{ String(index + 1).padStart(2, '0') }}</span>
              <label><span>维度名称</span><input v-model="dimension.name" :disabled="!isDraft" /></label>
              <label class="standard-dimension__weight"><span>权重</span><input v-model.number="dimension.weight" :data-test="`dimension-weight-${index}`" type="number" min="0" max="100" :disabled="!isDraft" /></label>
              <label class="standard-dimension__description"><span>判断说明</span><textarea v-model="dimension.description" rows="2" :disabled="!isDraft" /></label>
              <button v-if="isDraft" class="standard-dimension__remove" :data-test="`remove-dimension-${index}`" aria-label="删除评分维度" @click="removeDimension(index)">×</button>
            </article>
            <button v-if="isDraft" class="standard-add" data-test="add-dimension" @click="addDimension"><span>＋</span>添加评分维度</button>
          </section>
          <section v-if="form.unresolved_questions.length" class="standard-questions"><span class="panel-kicker">NEEDS HR INPUT</span><h3>待确认问题</h3><p v-for="question in form.unresolved_questions" :key="question">{{ question }}</p></section>
        </template>
      </div>

      <footer v-if="standard" class="standard-drawer__footer">
        <div class="standard-more"><button class="ghost-button" aria-label="更多操作" @click="menuOpen = !menuOpen">···</button><div v-if="menuOpen"><button @click="emit('retry')">重新生成草稿</button><button disabled>查看历史版本</button></div></div>
        <span v-if="isDraft && totalWeight !== 100">权重合计必须为 100 才能启用</span>
        <button v-if="isDraft" class="secondary-button" data-test="save-standard" :disabled="saving" @click="save">保存草稿</button>
        <button v-if="isDraft" class="primary-button" data-test="publish-standard" :disabled="saving || !canPublish" @click="confirmPublish = true">确认并启用</button>
      </footer>

      <div v-if="confirmPublish" class="standard-confirm" data-test="publish-confirm">
        <div><span class="eyebrow">FINAL CHECK</span><h3>启用这份评分标准？</h3><p>启用后内容将锁定，后续简历评分会严格引用此版本。{{ form.auto_reject_on_hard_fail ? '明确违反硬性指标时将自动淘汰，并写入审计记录。' : 'AI 建议不会自动改变候选人阶段。' }}</p><div><button class="ghost-button" @click="confirmPublish = false">返回检查</button><button class="primary-button" data-test="confirm-publish-standard" :disabled="saving" @click="publish">确认启用</button></div></div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.hard-requirements{display:grid;gap:9px;padding:17px;background:#fffaf0;border:1px solid #eedfbd;border-radius:12px}.hard-requirements>header{display:flex;align-items:center;justify-content:space-between;gap:14px}.hard-requirements h3{margin:4px 0 2px;color:#3d3321;font-family:Georgia,"Noto Serif SC",serif;font-size:17px}.hard-requirements header p{margin:0;color:#8a7652;font-size:8px}.hard-requirements article{display:grid;grid-template-columns:28px 120px minmax(0,1fr) 26px;align-items:end;gap:8px;padding:10px;background:#fff;border:1px solid #eadfc9;border-radius:9px}.hard-requirements article>span{align-self:center;color:#a87522;font:10px Georgia,serif}.hard-requirements article label{display:grid;gap:4px}.hard-requirements article small{color:#8b7b60;font-size:8px}.hard-requirements article input{width:100%;height:34px;padding:0 9px;color:var(--ink);background:#fff;border:1px solid #ded6c7;border-radius:7px}.hard-requirements article>button{width:25px;height:25px;color:#9b8474;background:transparent;border:0;border-radius:6px;font-size:17px}.hard-requirements article>button:hover{color:#b33f4a;background:#fff0f0}.hard-reject-toggle{display:flex;align-items:flex-start;gap:9px;padding:11px 12px;color:#704c18;background:#fff3d7;border-radius:8px}.hard-reject-toggle input{margin-top:2px;accent-color:#b17418}.hard-reject-toggle span{display:grid;gap:3px}.hard-reject-toggle strong{font-size:9px}.hard-reject-toggle small{color:#987443;font-size:8px;line-height:1.5}
</style>
