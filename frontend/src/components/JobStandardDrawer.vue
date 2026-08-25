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
const form = reactive({ summary: '', dimensions: [], required: [], preferred: [], risks: [], unresolved_questions: [] })
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
function payload() {
  return {
    criteria: {
      summary: form.summary.trim(), dimensions: form.dimensions.map((item) => ({ ...item, weight: Number(item.weight || 0) })),
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
        <div><span class="eyebrow">FINAL CHECK</span><h3>启用这份评分标准？</h3><p>启用后内容将锁定，后续简历评分会严格引用此版本。不会自动淘汰或推进候选人。</p><div><button class="ghost-button" @click="confirmPublish = false">返回检查</button><button class="primary-button" data-test="confirm-publish-standard" :disabled="saving" @click="publish">确认启用</button></div></div>
      </div>
    </aside>
  </div>
</template>
