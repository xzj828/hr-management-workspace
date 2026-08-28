<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useModelCredentialStore } from '@/stores/modelCredential'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import {
  modules,
  moduleDestination,
  moduleForRoute,
  navigationForModule,
  rememberModuleRoute,
} from '@/navigation'
import ModelSwitcher from '@/components/ModelSwitcher.vue'
import ModelProfileDrawer from '@/components/ModelProfileDrawer.vue'
import UserAccountMenu from '@/components/UserAccountMenu.vue'
import AppIcon from '@/components/AppIcon.vue'
import RecruitmentJobContext from '@/components/RecruitmentJobContext.vue'

const auth = useAuthStore()
const modelCredentials = useModelCredentialStore()
const recruitmentContext = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const modelSettingsOpen = ref(false)

const currentModule = computed(() => moduleForRoute(route))
const isRecruitmentShell = computed(() => currentModule.value === 'recruitment')
const isResultsWorkspace = computed(() => ['recruitment-results', 'recruitment-tasks', 'recruitment-task-detail'].includes(String(route.name)))
const isRecruitmentTaskList = computed(() => route.name === 'recruitment-tasks')
const isRecruitmentDashboard = computed(() => route.name === 'recruitment-dashboard')
const isRecruitmentAdmin = computed(() => route.name === 'recruitment-admin')
const activeTopNavigationName = computed(() => (
  ['recruitment-tasks', 'recruitment-task-detail'].includes(String(route.name)) ? 'recruitment-results' : route.name
))
const topNavigation = computed(() => navigationForModule(currentModule.value).filter((item) => (
  item.name !== 'recruitment-admin' || auth.canManage
)))

watch(
  () => route.name,
  () => rememberModuleRoute(route),
  { immediate: true },
)

watch(
  () => auth.user?.id,
  async (userId) => {
    modelCredentials.reset()
    if (!userId) {
      recruitmentContext.reset()
      return
    }
    try { await recruitmentContext.loadJobs({ userId }) } catch {}
  },
  { immediate: true },
)

function moduleRoute(moduleId) {
  const destination = moduleDestination(moduleId)
  const name = moduleId === 'recruitment' && destination === 'recruitment-admin' && !auth.canManage
    ? 'recruitment-workbench'
    : destination
  const item = navigationForModule(moduleId).find((entry) => entry.name === name)
  return topNavigationRoute(item || { name })
}

function topNavigationRoute(item) {
  if (item.scope === 'job' && recruitmentContext.selectedJobId) {
    return { name: item.name, query: { job: recruitmentContext.selectedJobId } }
  }
  return { name: item.name }
}

async function signOut() {
  modelCredentials.reset()
  await auth.logout()
  recruitmentContext.reset()
  router.push({ name: 'login' })
}

function closeAccountModelSettings() {
  modelSettingsOpen.value = false
  nextTick(() => document.querySelector('[data-testid="account-trigger"]')?.focus())
}
</script>

<template>
  <div class="shell" :class="{ 'shell--collapsed': collapsed, 'shell--recruitment': isRecruitmentShell, 'shell--results': isResultsWorkspace, 'shell--task-list': isRecruitmentTaskList, 'shell--recruitment-dashboard': isRecruitmentDashboard, 'shell--recruitment-admin': isRecruitmentAdmin }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand__mark">XM</div>
        <div class="brand__text"><strong>西鸣人事</strong><span>People OS</span></div>
      </div>
      <nav class="module-nav" aria-label="业务模块">
        <router-link
          v-for="module in modules"
          :key="module.id"
          :to="moduleRoute(module.id)"
          class="nav-item"
          :class="{ 'nav-item--active': currentModule === module.id }"
        >
          <AppIcon class="nav-item__icon" :name="module.icon" :size="20" />
          <span class="nav-item__label">{{ module.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar__foot">
        <div class="system-state"><i></i><span>本地服务运行中</span></div>
        <button class="collapse-button" type="button" :aria-label="collapsed ? '展开导航' : '收起导航'" @click="collapsed = !collapsed">
          <AppIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="18" />
          <span v-if="!collapsed">收起导航</span>
        </button>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <nav class="top-navigation" :aria-label="`${currentModule === 'recruitment' ? '招聘' : '考勤'}功能`">
          <router-link
            v-for="item in topNavigation"
            :key="item.name"
            :to="topNavigationRoute(item)"
            class="top-navigation__link"
            :class="{ 'top-navigation__link--active': item.name === activeTopNavigationName }"
          ><AppIcon :name="item.icon" :size="18" /><span>{{ item.label }}</span></router-link>
        </nav>
        <div class="topbar__actions">
          <RecruitmentJobContext
            v-if="currentModule === 'recruitment' && route.meta.recruitmentScope === 'job' && !route.meta.inlineJobContext"
          />
          <ModelSwitcher v-if="currentModule === 'recruitment'" :compact="false" />
          <UserAccountMenu :user="auth.user" @model-settings="modelSettingsOpen = true" @logout="signOut" />
        </div>
      </header>
      <section
        class="page-container"
        :class="{
          'page-container--workbench': route.name === 'recruitment-workbench',
          'page-container--results': isResultsWorkspace,
          'page-container--task-list': isRecruitmentTaskList,
          'page-container--recruitment-dashboard': isRecruitmentDashboard,
          'page-container--recruitment-admin': isRecruitmentAdmin,
        }"
      >
        <router-view />
      </section>
    </main>
    <ModelProfileDrawer v-if="modelSettingsOpen" @close="closeAccountModelSettings" @saved="closeAccountModelSettings" />
  </div>
</template>
