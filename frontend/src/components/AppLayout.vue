<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useRecruitmentContextStore } from '@/stores/recruitmentContext'
import {
  modules,
  moduleDestination,
  moduleForRoute,
  navigationForModule,
  rememberModuleRoute,
} from '@/navigation'
import RecruitmentCopilotDrawer from '@/components/RecruitmentCopilotDrawer.vue'
import UserAccountMenu from '@/components/UserAccountMenu.vue'
import AppIcon from '@/components/AppIcon.vue'
import RecruitmentJobContext from '@/components/RecruitmentJobContext.vue'

const auth = useAuthStore()
const recruitmentContext = useRecruitmentContextStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const copilotOpen = ref(false)

const currentModule = computed(() => moduleForRoute(route))
const topNavigation = computed(() => navigationForModule(currentModule.value))

watch(
  () => route.name,
  () => rememberModuleRoute(route),
  { immediate: true },
)

watch(
  () => auth.user?.id,
  async (userId) => {
    if (!userId) {
      recruitmentContext.reset()
      return
    }
    try { await recruitmentContext.loadJobs({ userId }) } catch {}
  },
  { immediate: true },
)

function moduleRoute(moduleId) {
  const name = moduleDestination(moduleId)
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
  await auth.logout()
  recruitmentContext.reset()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell" :class="{ 'shell--collapsed': collapsed }">
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
          ><AppIcon :name="item.icon" :size="18" /><span>{{ item.label }}</span></router-link>
        </nav>
        <div class="topbar__actions">
          <RecruitmentJobContext v-if="currentModule === 'recruitment'" />
          <button v-if="currentModule === 'recruitment'" class="copilot-entry" type="button" @click="copilotOpen = true">
            <AppIcon name="sparkles" :size="17" /> Copilot
          </button>
          <UserAccountMenu :user="auth.user" @model-settings="copilotOpen = true" @logout="signOut" />
        </div>
      </header>
      <section class="page-container"><router-view /></section>
    </main>
    <RecruitmentCopilotDrawer v-if="copilotOpen" @close="copilotOpen = false" />
  </div>
</template>
