<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { actionLabels, taskStatusLabels } from '@/recruitmentAutomation'

const props = defineProps({ batch: { type: Object, required: true } })
const expanded = ref(true)
const percent = computed(() => Math.round(((props.batch.succeeded_items + props.batch.failed_items) / Math.max(props.batch.total_items, 1)) * 100))
</script>

<template>
  <article class="automation-batch-card">
    <header @click="expanded = !expanded">
      <div class="automation-batch-icon"><AppIcon name="workflow" :size="18" /></div>
      <div><strong>{{ actionLabels[batch.action] || batch.action }}</strong><small>{{ batch.account_name }} · {{ taskStatusLabels[batch.status] || batch.status }}</small></div>
      <span>{{ batch.succeeded_items }} / {{ batch.total_items }}</span>
      <button type="button" :aria-label="expanded ? '收起' : '展开'"><AppIcon name="chevron-down" :size="15" /></button>
    </header>
    <div class="automation-batch-track"><i :style="{ width: `${percent}%` }"></i></div>
    <Transition name="batch-details"><div v-if="expanded" class="automation-batch-steps"><div v-for="step in batch.steps" :key="step.id" :class="`is-${step.status}`"><i></i><strong>{{ step.candidate_name }}</strong><span>{{ taskStatusLabels[step.status] || step.status }}</span><small>{{ step.error_message || '身份核验与操作结果均会留痕' }}</small></div></div></Transition>
  </article>
</template>

