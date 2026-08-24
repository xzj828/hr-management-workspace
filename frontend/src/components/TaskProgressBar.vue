<script setup>
import { computed } from 'vue'
import { taskProgress } from '@/recruitmentJobs'

const props = defineProps({
  status: { type: String, required: true },
  reducedMotion: { type: Boolean, default: false },
})

const progress = computed(() => taskProgress(props.status))
</script>

<template>
  <div :class="['task-progress', { 'is-reduced-motion': reducedMotion }]">
    <div class="task-progress__meta">
      <span>{{ progress.label }}</span>
      <strong>{{ progress.percent }}%</strong>
    </div>
    <div
      class="task-progress__track"
      role="progressbar"
      :aria-label="progress.label"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="progress.percent"
    >
      <i class="task-progress__bar" :style="{ transform: `scaleX(${progress.percent / 100})` }"></i>
    </div>
  </div>
</template>
