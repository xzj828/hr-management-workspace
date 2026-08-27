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
      <strong>招聘任务</strong>
    </RouterLink>
    <RouterLink :to="resultsTo" :class="{ 'is-active': activeSection === 'results' }" data-test="results-nav-business">
      <AppIcon name="check-circle" :size="16" />
      <strong>业务结果</strong>
    </RouterLink>
  </nav>
</template>

<style scoped>
.results-workspace-navigation { display: inline-flex; align-items: stretch; gap: 5px; width: fit-content; max-width: 100%; padding: 5px; border: 1px solid #d7e4e2; border-radius: 14px; background: #eef5f4; }
.results-workspace-navigation a { display: flex; align-items: center; justify-content: center; gap: 8px; min-width: clamp(136px, 12vw, 172px); min-height: 44px; padding: 0 18px; border: 1px solid transparent; border-radius: 10px; color: #5f6f7e; text-decoration: none; transition: 160ms ease; }
.results-workspace-navigation a:hover { color: #087f73; background: rgba(255, 255, 255, .62); }
.results-workspace-navigation a.is-active { color: #087f73; border-color: #b9ddd8; background: #fff; box-shadow: 0 2px 8px rgba(15, 23, 42, .06); }
.results-workspace-navigation strong { font-size: clamp(13px, .55rem + .35vw, 15px); font-weight: 800; white-space: nowrap; }
.results-workspace-navigation a:focus-visible { outline: 2px solid #0f9f8f; outline-offset: 2px; }
@media (max-width: 560px) {
  .results-workspace-navigation { display: grid; width: 100%; grid-template-columns: 1fr 1fr; }
  .results-workspace-navigation a { min-width: 0; padding: 0 10px; }
}
</style>
