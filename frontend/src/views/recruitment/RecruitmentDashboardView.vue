<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '@/api'

const summary = reactive({ open_jobs: 0, active_candidates: 0, waiting_resumes: 0, waiting_interviews: 0, boss_accounts_ready: 0 })
const error = ref('')

onMounted(async () => {
  try {
    Object.assign(summary, await api('recruitment/dashboard/'))
  } catch (err) {
    error.value = err.message
  }
})

const cards = [
  ['open_jobs', '在招职位'],
  ['active_candidates', '活跃候选人'],
  ['waiting_resumes', '待收简历'],
  ['waiting_interviews', '待安排面试'],
  ['boss_accounts_ready', '可用 BOSS 账号'],
]
</script>

<template>
  <div class="page-stack">
    <header class="page-hero">
      <div><span class="eyebrow">Recruitment Overview</span><h2>招聘看板</h2><p>统一查看职位、候选人、简历和自动化运行状态。</p></div>
    </header>
    <p v-if="error" class="form-error">{{ error }}</p>
    <section class="foundation-grid">
      <article v-for="([key, label]) in cards" :key="key" class="foundation-card"><span>{{ label }}</span><strong>{{ summary[key] }}</strong></article>
    </section>
    <section class="empty-state-panel"><span class="eyebrow">Foundation Ready</span><h2>招聘工作区已建立</h2><p>职位同步、候选人流程和 Windows RPA 任务将在后续阶段接入。</p></section>
  </div>
</template>
