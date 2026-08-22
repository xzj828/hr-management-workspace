<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  modules,
  moduleDestination,
  moduleForRoute,
  navigationForModule,
  rememberModuleRoute,
} from '@/navigation'
import RecruitmentCopilotDrawer from '@/components/RecruitmentCopilotDrawer.vue'
import UserAccountMenu from '@/components/UserAccountMenu.vue'

const auth = useAuthStore()
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

function moduleRoute(moduleId) {
  return { name: moduleDestination(moduleId) }
}

async function signOut() {
  await auth.logout()
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
          <span class="nav-item__icon">{{ module.id === 'recruitment' ? '◇' : '⌁' }}</span>
          <span class="nav-item__label">{{ module.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar__foot">
        <div class="system-state"><i></i><span>本地服务运行中</span></div>
        <button class="collapse-button" type="button" @click="collapsed = !collapsed">{{ collapsed ? '›' : '‹ 收起导航' }}</button>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <nav class="top-navigation" :aria-label="`${currentModule === 'recruitment' ? '招聘' : '考勤'}功能`">
          <router-link
            v-for="item in topNavigation"
            :key="item.name"
            :to="{ name: item.name }"
            class="top-navigation__link"
          >{{ item.label }}</router-link>
        </nav>
        <div class="topbar__actions">
          <button v-if="currentModule === 'recruitment'" class="copilot-entry" type="button" @click="copilotOpen = true">
            <span aria-hidden="true">✦</span> Copilot
          </button>
          <UserAccountMenu :user="auth.user" @model-settings="copilotOpen = true" @logout="signOut" />
        </div>
      </header>
      <section class="page-container"><router-view /></section>
    </main>
    <RecruitmentCopilotDrawer v-if="copilotOpen" @close="copilotOpen = false" />
  </div>
</template>
