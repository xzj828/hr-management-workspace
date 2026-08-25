<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import AppIcon from '@/components/AppIcon.vue'

const auth = useAuthStore()
const context = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()
const open = ref(false)
const search = ref('')

const isJobScope = computed(() => route.meta?.recruitmentScope === 'job')
const filteredJobs = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return context.jobs
  return context.jobs.filter((job) => [job.title, job.department, job.account_name]
    .some((value) => String(value || '').toLowerCase().includes(keyword)))
})

function routeQueryWithoutJob() {
  const query = { ...route.query }
  delete query.job
  return query
}

function chooseJob(job) {
  if (!context.selectJob(job.id, { userId: auth.user?.id })) return
  open.value = false
  search.value = ''
  router.replace({ name: route.name, query: { ...routeQueryWithoutJob(), job: String(job.id) } })
}

function toggleMenu() {
  open.value = !open.value
  if (!open.value) search.value = ''
}

watch(
  () => [route.meta?.recruitmentScope, route.query?.job, context.jobs.map((job) => job.id).join(',')],
  ([scope, routeJob]) => {
    if (scope !== 'job') {
      open.value = false
      if (routeJob) router.replace({ name: route.name, query: routeQueryWithoutJob() })
      return
    }
    if (routeJob) {
      if (context.jobs.some((job) => String(job.id) === String(routeJob))) {
        context.selectJob(routeJob, { userId: auth.user?.id })
      } else if (context.loaded) {
        context.invalidateSelection({ userId: auth.user?.id })
        router.replace({ name: route.name, query: routeQueryWithoutJob() })
      }
      return
    }
    if (context.selectedJobId) {
      router.replace({ name: route.name, query: { ...routeQueryWithoutJob(), job: context.selectedJobId } })
    }
  },
  { immediate: true },
)
</script>

<template>
  <div v-if="!isJobScope" class="recruitment-job-context recruitment-job-context--global">
    <AppIcon name="briefcase" :size="15" />
    <span><strong>全部职位</strong><small>全局视图</small></span>
  </div>
  <div v-else class="recruitment-job-context recruitment-job-context--selector">
    <button
      class="recruitment-job-context__trigger"
      data-test="job-context-trigger"
      type="button"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggleMenu"
    >
      <AppIcon name="briefcase" :size="15" />
      <span v-if="context.currentJob">
        <strong>{{ context.currentJob.title }}</strong>
        <small>{{ context.currentJob.department || context.currentJob.account_name || '当前招聘职位' }}</small>
      </span>
      <span v-else><strong>选择在招职位</strong><small>进入岗位工作区</small></span>
      <AppIcon name="chevron-down" :size="13" />
    </button>
    <Transition name="job-context-menu">
      <div v-if="open" class="recruitment-job-context__menu">
        <label class="recruitment-job-context__search">
          <AppIcon name="search" :size="14" />
          <input v-model="search" data-test="job-context-search" type="search" placeholder="搜索职位、部门或账号" autofocus />
        </label>
        <div class="recruitment-job-context__options" role="listbox" aria-label="在招职位">
          <button
            v-for="job in filteredJobs"
            :key="job.id"
            :data-test="`job-context-option-${job.id}`"
            type="button"
            role="option"
            :aria-selected="String(job.id) === context.selectedJobId"
            @click="chooseJob(job)"
          >
            <span><strong>{{ job.title }}</strong><small>{{ [job.department, job.account_name].filter(Boolean).join(' · ') || '在招职位' }}</small></span>
            <AppIcon v-if="String(job.id) === context.selectedJobId" name="check-circle" :size="15" />
          </button>
          <p v-if="!filteredJobs.length">{{ context.loading ? '正在读取职位…' : '没有匹配的在招职位' }}</p>
        </div>
      </div>
    </Transition>
  </div>
</template>
