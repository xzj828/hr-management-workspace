<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'

const route = useRoute()
const activeSection = computed(() => (
  ['recruitment-tasks', 'recruitment-task-detail'].includes(String(route.name)) ? 'tasks' : 'results'
))
const resultsTo = computed(() => {
  const query = route.query.job ? { job: String(route.query.job) } : {}
  if (route.name === 'recruitment-task-detail') {
    if (route.query.run) query.run = String(route.query.run)
    query.view = String(route.query.view || 'tasks')
    if (route.query.status) query.status = String(route.query.status)
  }
  return { name: 'recruitment-results', query }
})
</script>

<template>
  <nav class="results-workspace-navigation" aria-label="结果中心页面">
    <RouterLink :to="{ name: 'recruitment-tasks' }" :class="{ 'is-active': activeSection === 'tasks' }" data-test="results-nav-tasks">
      <AppIcon name="briefcase" :size="16" />
      <span><strong>招聘任务</strong><small>跨岗位查看与维护任务</small></span>
    </RouterLink>
    <RouterLink :to="resultsTo" :class="{ 'is-active': activeSection === 'results' }" data-test="results-nav-business">
      <AppIcon name="check-circle" :size="16" />
      <span><strong>业务结果</strong><small>候选人、简历与招聘进度</small></span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.results-workspace-navigation { display: inline-flex; align-items: stretch; gap: 4px; width: fit-content; max-width: 100%; padding: 4px; border: 1px solid #dce7e5; border-radius: 14px; background: #f4f8f7; }
.results-workspace-navigation a { display: flex; align-items: center; gap: 9px; min-width: 190px; min-height: 48px; padding: 7px 13px; border: 1px solid transparent; border-radius: 10px; color: #64748b; text-decoration: none; transition: 160ms ease; }
.results-workspace-navigation a:hover { color: #087f73; background: #eaf8f6; }
.results-workspace-navigation a.is-active { color: #087f73; border-color: #c4e6e1; background: #fff; box-shadow: 0 1px 3px rgba(15, 23, 42, .06); }
.results-workspace-navigation span { display: grid; gap: 1px; }
.results-workspace-navigation strong { font-size: 12px; }
.results-workspace-navigation small { font-size: 10px; font-weight: 600; white-space: nowrap; }
.results-workspace-navigation a:focus-visible { outline: 2px solid #0f9f8f; outline-offset: 2px; }
@media (max-width: 560px) {
  .results-workspace-navigation { display: grid; width: 100%; grid-template-columns: 1fr 1fr; }
  .results-workspace-navigation a { min-width: 0; }
  .results-workspace-navigation small { display: none; }
}
</style>
